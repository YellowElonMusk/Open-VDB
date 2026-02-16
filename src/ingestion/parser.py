"""Document parsers — extract plain text from uploaded files.

Supports: PDF, DOCX, TXT, CSV, Markdown.
OEMs upload manuals, guides, SOPs in these formats and the platform
automatically converts them to text for chunking and embedding.

PDF parsing is enhanced for manufacturing documents: handles tables,
multi-column layouts, and extracts text with structural awareness.
"""

import csv
import io
import re
from pathlib import Path

import docx
from pypdf import PdfReader


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".csv", ".md"}


def parse_file(filename: str, content: bytes) -> str:
    """Extract plain text from an uploaded file based on its extension."""
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        return _parse_pdf(content)
    elif ext == ".docx":
        return _parse_docx(content)
    elif ext in {".txt", ".md"}:
        return content.decode("utf-8", errors="replace")
    elif ext == ".csv":
        return _parse_csv(content)
    else:
        raise ValueError(
            f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )


def _parse_pdf(content: bytes) -> str:
    """Extract text from PDF with enhanced handling for manufacturing documents.

    Handles:
    - Multi-page documents with page boundary markers
    - Table extraction (preserves tabular structure as readable text)
    - Multi-column layouts (via pypdf's layout mode)
    - Header/footer deduplication
    """
    reader = PdfReader(io.BytesIO(content))
    pages = []

    for page_num, page in enumerate(reader.pages, 1):
        # Use layout mode for better multi-column and table extraction
        text = page.extract_text(extraction_mode="layout")
        if not text:
            # Fallback to plain extraction
            text = page.extract_text()
        if not text:
            continue

        # Clean up common PDF artifacts
        text = _clean_pdf_text(text)

        # Add page reference for traceability
        pages.append(f"[Page {page_num}]\n{text}")

    full_text = "\n\n".join(pages)

    # Remove duplicate headers/footers that appear on every page
    full_text = _deduplicate_headers_footers(full_text, len(reader.pages))

    return full_text


def _clean_pdf_text(text: str) -> str:
    """Clean common PDF extraction artifacts."""
    # Fix broken words from line wrapping (hyphenation)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # Collapse excessive whitespace within lines (common in layout mode)
    # but preserve intentional spacing (tables)
    lines = []
    for line in text.split("\n"):
        # If a line has multiple large gaps, it's likely a table row — preserve it
        if re.search(r"\S\s{4,}\S", line):
            # Table-like line: normalize gaps to " | " for readability
            line = re.sub(r"\s{3,}", " | ", line.strip())
        else:
            # Normal line: collapse extra spaces
            line = re.sub(r" {2,}", " ", line)
        lines.append(line)

    text = "\n".join(lines)

    # Remove excessive blank lines
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    return text.strip()


def _deduplicate_headers_footers(text: str, page_count: int) -> str:
    """Remove repeated headers/footers that appear on every page.

    Manufacturing manuals often have "Company Name | Document Title | Page X"
    on every page — this just wastes chunk space.
    """
    if page_count < 3:
        return text

    lines = text.split("\n")
    # Count line occurrences (ignoring page numbers)
    line_counts: dict[str, int] = {}
    for line in lines:
        normalized = re.sub(r"\d+", "#", line.strip())
        if normalized and len(normalized) > 5:
            line_counts[normalized] = line_counts.get(normalized, 0) + 1

    # Lines appearing on >60% of pages are likely headers/footers
    threshold = page_count * 0.6
    noise_patterns = {pat for pat, count in line_counts.items() if count >= threshold}

    if not noise_patterns:
        return text

    cleaned_lines = []
    for line in lines:
        normalized = re.sub(r"\d+", "#", line.strip())
        if normalized not in noise_patterns:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def _parse_docx(content: bytes) -> str:
    """Extract text from DOCX with table support."""
    doc = docx.Document(io.BytesIO(content))
    parts = []

    for element in doc.element.body:
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

        if tag == "p":
            # Paragraph
            text = element.text
            if text and text.strip():
                parts.append(text.strip())

        elif tag == "tbl":
            # Table — extract and format as readable text
            table_text = _extract_docx_table(element, doc)
            if table_text:
                parts.append(table_text)

    return "\n\n".join(parts)


def _extract_docx_table(tbl_element, doc) -> str:
    """Extract a DOCX table into readable text format."""
    rows = []
    for tr in tbl_element.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr"):
        cells = []
        for tc in tr.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc"):
            cell_text = ""
            for p in tc.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                if p.text:
                    cell_text += p.text
                # Also get text from runs
                for r in p.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}r"):
                    for t in r.findall("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
                        if t.text:
                            cell_text += t.text
            cells.append(cell_text.strip())
        if any(cells):
            rows.append(cells)

    if not rows:
        return ""

    # If first row looks like headers, format as "header: value" pairs
    if len(rows) >= 2:
        headers = rows[0]
        data_rows = rows[1:]
        lines = []
        for row in data_rows:
            parts = []
            for h, v in zip(headers, row):
                if v.strip():
                    parts.append(f"{h}: {v}" if h.strip() else v)
            if parts:
                lines.append("; ".join(parts))
        return "\n".join(lines)

    # Single row or no clear headers — just join with pipes
    return "\n".join(" | ".join(row) for row in rows)


def _parse_csv(content: bytes) -> str:
    """Convert CSV rows to readable text lines so they can be chunked and searched."""
    text = content.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        return text

    headers = rows[0]
    lines = []
    for row in rows[1:]:
        parts = [f"{h}: {v}" for h, v in zip(headers, row) if v.strip()]
        if parts:
            lines.append("; ".join(parts))
    return "\n".join(lines)
