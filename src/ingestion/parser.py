"""Document parsers — extract structured Blocks from uploaded files.

OEM manuals are structured documents: sections, prose, and troubleshooting
tables whose meaning lives in the header-to-cell binding. Flattening them
to a string destroys exactly the information a support agent needs, so
parsing returns a list of `Block`s instead.

PDF extraction uses PyMuPDF at span level with an explicit space guard.
Text extractors that snap glyphs to a character grid (e.g. pypdf's layout
mode) delete the space between adjacent table columns, producing fused
tokens like "isout of charge" that cannot be repaired downstream.

Tables come from PyMuPDF's table finder — never from whitespace geometry.
Each table row becomes one unit with the header cells bound to each value,
so a fault code can never be separated from its description.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import docx
import fitz  # PyMuPDF


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".csv", ".md"}

KIND_HEADING = "heading"
KIND_PROSE = "prose"
KIND_TABLE = "table"

# Bands (fraction of page height) searched for repeating headers/footers.
_MARGIN_BAND = 0.10
# A line must repeat on at least this fraction of pages to count as furniture.
_FURNITURE_RATIO = 0.60


@dataclass
class Block:
    """One semantic unit of a document.

    `cells`/`table_header` are populated for table rows so downstream
    consumers can rebuild a real table instead of re-parsing text.
    """

    text: str
    page: int = 1
    kind: str = KIND_PROSE
    section: str = ""
    table_header: list[str] | None = None
    cells: list[str] | None = None
    source_doc: str = ""
    revision: str = ""

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "page": self.page,
            "kind": self.kind,
            "section": self.section,
            "table_header": self.table_header,
            "cells": self.cells,
            "source_doc": self.source_doc,
            "revision": self.revision,
        }


# ── Document identity ────────────────────────────────────────────────

_REVISION_RE = re.compile(
    r"\b(?:v|ver|version|rev|revision|ed|edition)[\s._-]*([0-9]+(?:\.[0-9]+)*)\b",
    re.IGNORECASE,
)


def parse_document_identity(filename: str) -> tuple[str, str]:
    """Split a filename into (source_doc, revision).

    "R3 Vac Ed.01 v0.6.pdf" -> ("R3 Vac", "Ed.01 v0.6")
    """
    stem = Path(filename).stem
    revisions = []
    for match in _REVISION_RE.finditer(stem):
        token = match.group(0).strip()
        token = re.sub(r"[\s._-]+", ".", token).rstrip(".")
        revisions.append(token)
    source = _REVISION_RE.sub(" ", stem)
    source = re.sub(r"[_]+", " ", source)
    source = re.sub(r"\s{2,}", " ", source).strip(" -.")
    return (source or stem or "document", " ".join(revisions))


_FR_MARKERS = {
    "le", "la", "les", "des", "une", "un", "est", "sont", "pour", "dans",
    "avec", "sur", "vous", "pas", "que", "qui", "aux", "par", "ce", "cette",
}
_EN_MARKERS = {
    "the", "is", "are", "and", "for", "with", "that", "this", "not", "you",
    "from", "have", "will", "can", "must", "of", "to", "in", "on", "it",
}


def detect_language(text: str) -> str:
    """Cheap EN/FR discriminator — used to pick a Postgres FTS config."""
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    if not words:
        return "en"
    sample = words[:5000]
    fr = sum(1 for w in sample if w in _FR_MARKERS)
    en = sum(1 for w in sample if w in _EN_MARKERS)
    return "fr" if fr > en else "en"


# ── Entry point ──────────────────────────────────────────────────────

def parse_file(filename: str, content: bytes) -> list[Block]:
    """Extract structured blocks from an uploaded file."""
    ext = Path(filename).suffix.lower()
    source_doc, revision = parse_document_identity(filename)

    if ext == ".pdf":
        blocks = _parse_pdf(content)
    elif ext == ".docx":
        blocks = _parse_docx(content)
    elif ext in {".txt", ".md"}:
        blocks = _parse_text(content.decode("utf-8", errors="replace"), markdown=(ext == ".md"))
    elif ext == ".csv":
        blocks = _parse_csv(content)
    else:
        raise ValueError(
            f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    for block in blocks:
        block.source_doc = source_doc
        block.revision = revision
    return blocks


def blocks_to_text(blocks: list[Block]) -> str:
    """Flatten blocks to plain text.

    Provided for quality assessment and legacy callers. The ingestion path
    must consume Blocks directly — flattening throws away the structure
    that chunking and the exporters depend on.
    """
    return "\n\n".join(b.text for b in blocks if b.text.strip())


# ── PDF ──────────────────────────────────────────────────────────────

def _parse_pdf(content: bytes) -> list[Block]:
    doc = fitz.open(stream=content, filetype="pdf")
    try:
        furniture = _detect_furniture(doc)
        body_size = _modal_body_size(doc)
        blocks: list[Block] = []
        section = ""

        for page_index, page in enumerate(doc, start=1):
            units = _page_units(page, furniture, body_size)
            for y0, kind, payload in units:
                if kind == KIND_HEADING:
                    section = payload
                    blocks.append(Block(text=payload, page=page_index, kind=KIND_HEADING, section=payload))
                elif kind == KIND_PROSE:
                    blocks.append(Block(text=payload, page=page_index, kind=KIND_PROSE, section=section))
                else:  # table row
                    header, cells, text = payload
                    blocks.append(
                        Block(
                            text=text,
                            page=page_index,
                            kind=KIND_TABLE,
                            section=section,
                            table_header=header,
                            cells=cells,
                        )
                    )
        return blocks
    finally:
        doc.close()


def _normalise_furniture(text: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", text.strip()))


def _detect_furniture(doc) -> set[str]:
    """Find repeating headers/footers *geometrically*.

    Only lines inside the top/bottom margin bands are considered, so
    legitimate repeated body content (a warning restated in every section)
    is never deleted.
    """
    page_count = doc.page_count
    if page_count < 3:
        return set()

    counts: Counter[str] = Counter()
    for page in doc:
        height = page.rect.height
        seen_on_page = set()
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                y0, y1 = line["bbox"][1], line["bbox"][3]
                in_band = y1 < height * _MARGIN_BAND or y0 > height * (1 - _MARGIN_BAND)
                if not in_band:
                    continue
                text = "".join(span["text"] for span in line.get("spans", []))
                key = _normalise_furniture(text)
                if len(key) > 3:
                    seen_on_page.add(key)
        counts.update(seen_on_page)

    threshold = page_count * _FURNITURE_RATIO
    return {key for key, count in counts.items() if count >= threshold}


def _modal_body_size(doc) -> float:
    """Most common font size, weighted by characters — the body text size."""
    weights: Counter[float] = Counter()
    for page in doc:
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if text:
                        weights[round(span.get("size", 0) * 2) / 2] += len(text)
    return weights.most_common(1)[0][0] if weights else 10.0


def _is_bold(span) -> bool:
    return bool(span.get("flags", 0) & 2 ** 4) or "bold" in span.get("font", "").lower()


def _join_spans(spans) -> str:
    """Join spans, inserting a space wherever the glyphs are visually apart.

    The PDF's own spacing is not trusted: a span boundary with a real gap
    becomes a space, a boundary with no gap (a font change mid-word) does
    not. This is what prevents column-collision fusion.
    """
    out = ""
    prev_x1 = None
    prev_size = 10.0
    for span in spans:
        text = span.get("text", "")
        if not text:
            continue
        if out and prev_x1 is not None:
            gap = span["bbox"][0] - prev_x1
            already_spaced = out.endswith(" ") or text.startswith(" ")
            if not already_spaced and gap > max(0.18 * prev_size, 0.4):
                out += " "
        out += text
        prev_x1 = span["bbox"][2]
        prev_size = span.get("size", prev_size) or prev_size
    return out.strip()


def _line_is_heading(spans, text: str, body_size: float) -> bool:
    if not text or len(text) > 120:
        return False
    sizes = [span.get("size", 0) for span in spans if span.get("text", "").strip()]
    if not sizes:
        return False
    size = max(sizes)
    bold = any(_is_bold(span) for span in spans if span.get("text", "").strip())

    if size >= body_size * 1.15:
        return True
    if bold and size >= body_size and not text.rstrip().endswith((".", ";", ",")):
        return True
    # Numbered section headings ("6.1 FAULT CODES") even when set in body type
    if re.match(r"^\d+(\.\d+)*[.)]?\s+\S", text) and len(text) < 90 and text == text.upper():
        return True
    return False


def _dehyphenate(previous: str, nxt: str) -> str | None:
    if previous.endswith("-") and len(previous) > 1 and previous[-2].isalpha() and nxt[:1].islower():
        return previous[:-1] + nxt
    return None


def _page_units(page, furniture: set[str], body_size: float) -> list[tuple[float, str, object]]:
    """Return (y0, kind, payload) units for one page, in reading order."""
    units: list[tuple[float, str, object]] = []
    table_rects: list[fitz.Rect] = []

    for table in _find_tables(page):
        rect = fitz.Rect(table.bbox)
        table_rects.append(rect)
        rows = table.extract()
        if not rows:
            continue
        header = _clean_row(rows[0])
        body_rows = rows[1:]
        if not any(cell for cell in header) or not body_rows:
            # No usable header — emit rows as plain cell joins rather than
            # inventing a binding.
            header = []
            body_rows = rows
        for row in body_rows:
            cells = _clean_row(row)
            if not any(cells):
                continue
            units.append((rect.y0, KIND_TABLE, (header or None, cells, _bind_row(header, cells))))

    height = page.rect.height
    paragraph: list[str] = []
    paragraph_y: float | None = None

    def flush():
        nonlocal paragraph, paragraph_y
        if paragraph:
            text = " ".join(paragraph).strip()
            if text:
                units.append((paragraph_y or 0.0, KIND_PROSE, text))
        paragraph = []
        paragraph_y = None

    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        block_rect = fitz.Rect(block["bbox"])
        if _covered_by(block_rect, table_rects):
            continue
        for line in block.get("lines", []):
            line_rect = fitz.Rect(line["bbox"])
            if _covered_by(line_rect, table_rects):
                continue
            spans = line.get("spans", [])
            text = _join_spans(spans)
            if not text:
                continue
            y0, y1 = line_rect.y0, line_rect.y1
            in_band = y1 < height * _MARGIN_BAND or y0 > height * (1 - _MARGIN_BAND)
            if in_band and _normalise_furniture(text) in furniture:
                continue
            if _line_is_heading(spans, text, body_size):
                flush()
                units.append((y0, KIND_HEADING, text))
                continue
            if paragraph:
                merged = _dehyphenate(paragraph[-1], text)
                if merged is not None:
                    paragraph[-1] = merged
                    continue
            if paragraph_y is None:
                paragraph_y = y0
            paragraph.append(text)
        flush()

    units.sort(key=lambda unit: unit[0])
    return units


def _find_tables(page):
    """Ruled tables first; fall back to text alignment with strict validation."""
    try:
        found = page.find_tables()
        tables = list(found.tables)
    except Exception:
        tables = []
    if tables:
        return tables
    try:
        found = page.find_tables(strategy="text")
        candidates = list(found.tables)
    except Exception:
        return []
    valid = []
    for table in candidates:
        rows = table.extract()
        if len(rows) < 2 or table.col_count < 2:
            continue
        filled = sum(1 for row in rows for cell in row if (cell or "").strip())
        if filled >= 0.5 * len(rows) * table.col_count:
            valid.append(table)
    return valid


def _covered_by(rect: fitz.Rect, others: list[fitz.Rect]) -> bool:
    area = _area(rect)
    if area <= 0:
        return any(rect.intersects(other) for other in others)
    for other in others:
        if _area(fitz.Rect(rect) & other) > 0.5 * area:
            return True
    return False


def _area(rect: fitz.Rect) -> float:
    width = max(0.0, rect.x1 - rect.x0)
    height = max(0.0, rect.y1 - rect.y0)
    return width * height


def _clean_cell(value) -> str:
    return re.sub(r"\s{2,}", " ", (value or "").replace("\n", " ")).strip()


def _clean_row(row) -> list[str]:
    return [_clean_cell(cell) for cell in row]


def _bind_row(header: list[str], cells: list[str]) -> str:
    """Bind header names to values so a row survives on its own."""
    parts = []
    for index, value in enumerate(cells):
        if not value:
            continue
        name = header[index] if index < len(header) else ""
        parts.append(f"{name}: {value}" if name else value)
    return "; ".join(parts)


# ── DOCX ─────────────────────────────────────────────────────────────

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _parse_docx(content: bytes) -> list[Block]:
    document = docx.Document(io.BytesIO(content))
    blocks: list[Block] = []
    section = ""

    style_sizes: Counter[float] = Counter()
    for paragraph in document.paragraphs:
        size = paragraph.style.font.size.pt if paragraph.style and paragraph.style.font.size else None
        if size and paragraph.text.strip():
            style_sizes[size] += len(paragraph.text)
    body_size = style_sizes.most_common(1)[0][0] if style_sizes else 11.0

    body = document.element.body
    paragraphs = iter(document.paragraphs)

    for element in body:
        tag = element.tag.split("}")[-1]
        if tag == "p":
            paragraph = next(paragraphs, None)
            text = (paragraph.text if paragraph is not None else element.text or "").strip()
            if not text:
                continue
            style_name = (paragraph.style.name if paragraph is not None and paragraph.style else "") or ""
            size = (
                paragraph.style.font.size.pt
                if paragraph is not None and paragraph.style and paragraph.style.font.size
                else None
            )
            is_heading = style_name.lower().startswith("heading") or style_name.lower() == "title"
            if not is_heading and size and size >= body_size * 1.15 and len(text) < 120:
                is_heading = True
            if is_heading:
                section = text
                blocks.append(Block(text=text, kind=KIND_HEADING, section=text))
            else:
                blocks.append(Block(text=text, kind=KIND_PROSE, section=section))
        elif tag == "tbl":
            blocks.extend(_docx_table_blocks(element, section))

    return blocks


def _docx_table_blocks(tbl_element, section: str) -> list[Block]:
    rows: list[list[str]] = []
    for tr in tbl_element.findall(f".//{_W}tr"):
        cells = []
        for tc in tr.findall(f".//{_W}tc"):
            texts = [t.text or "" for t in tc.findall(f".//{_W}t")]
            cells.append(_clean_cell("".join(texts)))
        if any(cells):
            rows.append(cells)

    if not rows:
        return []

    header = rows[0] if len(rows) >= 2 and any(rows[0]) else []
    body_rows = rows[1:] if header else rows
    blocks = []
    for cells in body_rows:
        blocks.append(
            Block(
                text=_bind_row(header, cells),
                kind=KIND_TABLE,
                section=section,
                table_header=header or None,
                cells=cells,
            )
        )
    return blocks


# ── Plain text / Markdown / CSV ──────────────────────────────────────

def _parse_text(text: str, markdown: bool = False) -> list[Block]:
    blocks: list[Block] = []
    section = ""
    for raw in re.split(r"\n\s*\n", text):
        chunk = raw.strip()
        if not chunk:
            continue
        if markdown and chunk.startswith("#"):
            heading = chunk.lstrip("#").strip()
            section = heading
            blocks.append(Block(text=heading, kind=KIND_HEADING, section=heading))
            continue
        blocks.append(Block(text=chunk, kind=KIND_PROSE, section=section))
    return blocks


def _parse_csv(content: bytes) -> list[Block]:
    text = content.decode("utf-8", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    if len(rows) < 2:
        return [Block(text=", ".join(rows[0]), kind=KIND_PROSE)]

    header = _clean_row(rows[0])
    blocks = []
    for row in rows[1:]:
        cells = _clean_row(row)
        if not any(cells):
            continue
        blocks.append(
            Block(text=_bind_row(header, cells), kind=KIND_TABLE, table_header=header, cells=cells)
        )
    return blocks
