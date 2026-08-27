"""Export builders — turn parsed documents into portable, agent-friendly files.

Not every use case needs a vector database. Matching a robot error code to
its fix in an FAQ or SOP doc is a lookup, not a semantic search. For those,
OEMs can generate:

- Markdown (.md):  the document rendered from its parsed structure — real
  headings, real GFM tables, provenance comments, and front matter
  recording how good the extraction was.
- SQLite (.db):    a standalone, dependency-free SQL database with the
  chunks, their metadata, an FTS5 index, and a dedicated `fault_codes`
  table so a code lookup is an exact SQL query rather than a similarity
  search that could invent a neighbouring code.

Both are generated fully offline; no external API calls are involved.
"""

from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.ingestion import quality_gate
from src.ingestion.parser import (
    KIND_HEADING,
    KIND_TABLE,
    Block,
    blocks_to_text,
    detect_language,
)

# Output formats an OEM can choose at upload time.
FORMAT_VECTOR = "vector"
FORMAT_MARKDOWN = "markdown"
FORMAT_SQLITE = "sqlite"
SUPPORTED_OUTPUT_FORMATS = {FORMAT_VECTOR, FORMAT_MARKDOWN, FORMAT_SQLITE}

# OEM fault codes: AE-02-3605-2-4, AF-01-3021-6-1.
FAULT_CODE_RE = re.compile(r"^[A-Z]{2}-\d{2}-\d{3,4}-\d-\d$")
FAULT_CODE_INLINE_RE = re.compile(r"\b[A-Z]{2}-\d{2}-\d{3,4}-\d-\d\b")


def parse_output_formats(outputs: str) -> list[str]:
    """Parse a comma-separated outputs string (e.g. 'vector,markdown').

    Returns a de-duplicated list in canonical order.
    Raises ValueError for unknown format names or an empty selection.
    """
    requested = [part.strip().lower() for part in outputs.split(",") if part.strip()]
    if not requested:
        raise ValueError(
            "No output format selected. Choose one or more of: "
            f"{', '.join(sorted(SUPPORTED_OUTPUT_FORMATS))}"
        )

    unknown = [f for f in requested if f not in SUPPORTED_OUTPUT_FORMATS]
    if unknown:
        raise ValueError(
            f"Unknown output format(s): {', '.join(unknown)}. "
            f"Supported: {', '.join(sorted(SUPPORTED_OUTPUT_FORMATS))}"
        )

    return [f for f in (FORMAT_VECTOR, FORMAT_MARKDOWN, FORMAT_SQLITE) if f in requested]


def export_stem(filename: str) -> str:
    """Filesystem-safe stem for generated export filenames."""
    stem = Path(filename).stem or "document"
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in stem)


# ── Chunk adapter ────────────────────────────────────────────────────
# Exports are built from ChunkDrafts during ingestion and from Chunk rows
# for the tenant-wide export, so both shapes are read through one view.

class _ChunkView:
    __slots__ = (
        "content", "page", "section", "kind", "source_doc",
        "revision", "provenance", "needs_review",
    )

    def __init__(self, obj):
        if isinstance(obj, str):
            self.content = obj
            self.page = None
            self.section = self.kind = self.source_doc = self.revision = None
            self.provenance = []
            self.needs_review = False
            return
        self.content = getattr(obj, "text", None) or getattr(obj, "content", "")
        self.page = getattr(obj, "page", None)
        self.section = getattr(obj, "section", None) or None
        self.kind = getattr(obj, "kind", None)
        self.source_doc = getattr(obj, "source_doc", None) or None
        self.revision = getattr(obj, "revision", None) or None
        self.provenance = list(getattr(obj, "provenance", None) or [])
        self.needs_review = bool(getattr(obj, "needs_review", False))


# ── SQLite ───────────────────────────────────────────────────────────

def build_sqlite(documents: list[dict]) -> bytes:
    """Build a standalone SQLite database file and return its bytes.

    `documents` is a list of dicts:
        {"id", "filename", "file_type", "chunks": [...], "blocks": [...]}

    `chunks` accepts ChunkDrafts, Chunk rows, or plain strings. `blocks`
    is optional and, when present, gives the most precise fault-code
    extraction because it sees individual table cells.

    Example agent queries:

        -- exact fault code lookup (never a similarity search)
        SELECT description, source_doc, page FROM fault_codes WHERE code = 'AF-01-3021-6-1';

        -- full-text search
        SELECT c.content, c.source_doc, c.page
        FROM chunks_fts f JOIN chunks c ON c.id = f.rowid
        WHERE chunks_fts MATCH '"slope"' ORDER BY rank LIMIT 5;
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        try:
            _populate_sqlite(conn, documents)
            conn.commit()
        finally:
            conn.close()
        return Path(path).read_bytes()
    finally:
        os.unlink(path)


def _populate_sqlite(conn: sqlite3.Connection, documents: list[dict]) -> None:
    conn.executescript(
        """
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            source_doc TEXT,
            revision TEXT,
            chunk_count INTEGER NOT NULL
        );
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(id),
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            page INTEGER,
            section TEXT,
            kind TEXT,
            source_doc TEXT,
            revision TEXT,
            provenance TEXT,
            needs_review INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE fault_codes (
            code TEXT PRIMARY KEY,
            description TEXT,
            source_doc TEXT,
            page INTEGER
        );
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE INDEX ix_chunks_source_doc ON chunks(source_doc);
        CREATE INDEX ix_chunks_section ON chunks(section);
        """
    )

    conn.execute(
        "INSERT INTO meta VALUES ('generated_at', ?)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.execute("INSERT INTO meta VALUES ('generator', 'vectordb-oem-platform')")

    rowid = 0
    for doc in documents:
        views = [_ChunkView(chunk) for chunk in doc.get("chunks", [])]
        first = views[0] if views else None
        conn.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(doc["id"]),
                doc["filename"],
                doc["file_type"],
                first.source_doc if first else None,
                first.revision if first else None,
                len(views),
            ),
        )
        for index, view in enumerate(views):
            rowid += 1
            conn.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rowid,
                    str(doc["id"]),
                    index,
                    view.content,
                    view.page,
                    view.section,
                    view.kind,
                    view.source_doc,
                    view.revision,
                    "; ".join(view.provenance) if view.provenance else None,
                    int(view.needs_review),
                ),
            )
        _insert_fault_codes(conn, doc.get("blocks") or [], views)

    _create_search_index(conn)


def _insert_fault_codes(conn, blocks: list[Block], views: list[_ChunkView]) -> None:
    """Extract fault codes into their own exactly-queryable table.

    Table cells are authoritative: a cell that is exactly a fault code
    pairs with the rest of its row as the description. Chunk text is a
    fallback so exports built without blocks still get a code table.
    """
    found: dict[str, tuple[str, str | None, int | None]] = {}

    for block in blocks:
        if block.kind != KIND_TABLE or not block.cells:
            continue
        codes = [cell for cell in block.cells if FAULT_CODE_RE.match(cell.strip())]
        if not codes:
            continue
        description = "; ".join(
            cell for cell in block.cells if cell.strip() and not FAULT_CODE_RE.match(cell.strip())
        )
        for code in codes:
            found.setdefault(code.strip(), (description, block.source_doc or None, block.page))

    if not found:
        for view in views:
            for match in FAULT_CODE_INLINE_RE.finditer(view.content):
                code = match.group(0)
                if code not in found:
                    found[code] = (view.content.strip(), view.source_doc, view.page)

    for code, (description, source_doc, page) in found.items():
        conn.execute(
            "INSERT OR IGNORE INTO fault_codes VALUES (?, ?, ?, ?)",
            (code, description, source_doc, page),
        )


def _create_search_index(conn) -> None:
    """FTS5 when available, with a usable fallback recorded in `meta`.

    An agent must be able to branch on what search this file supports, so
    `meta.search_mode` always says which one it got: 'fts5' or 'like'.
    """
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE chunks_fts USING fts5(content, content=chunks, content_rowid=id)"
        )
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
        conn.execute("INSERT INTO meta VALUES ('fts', 'fts5')")
        conn.execute("INSERT INTO meta VALUES ('search_mode', 'fts5')")
    except sqlite3.OperationalError:
        # No FTS5 in this SQLite build. Give LIKE scans a covering index
        # instead of leaving the agent with nothing.
        conn.execute("CREATE INDEX ix_chunks_content_like ON chunks(content, id)")
        conn.execute("INSERT INTO meta VALUES ('fts', 'none')")
        conn.execute("INSERT INTO meta VALUES ('search_mode', 'like')")


# ── Markdown ─────────────────────────────────────────────────────────

def _md_escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>").strip()


def _provenance_comment(block: Block) -> str:
    parts = [part for part in (block.source_doc, block.revision) if part]
    parts.append(f"p.{block.page}")
    return f"<!-- src: {' '.join(parts)} -->"


def _conflict_index(drafts) -> list[tuple[str, list[str]]]:
    index = []
    for draft in drafts or []:
        view = _ChunkView(draft)
        if view.needs_review:
            index.append((re.sub(r"\s+", " ", view.content).strip().lower(), view.provenance))
    return index


def _conflict_for(block: Block, index: list[tuple[str, list[str]]]) -> list[str] | None:
    if not index:
        return None
    needle = re.sub(r"\s+", " ", block.text).strip().lower()
    if not needle:
        return None
    for haystack, provenance in index:
        if needle in haystack:
            return provenance
    return None


def build_markdown(filename: str, file_type: str, blocks: list[Block], drafts=None) -> str:
    """Render parsed blocks as Markdown with front matter and real tables."""
    text = blocks_to_text(blocks)
    metrics = quality_gate.measure("\n".join(b.text for b in blocks if b.text.strip()))
    language = detect_language(text)
    pages = max((block.page for block in blocks), default=1)
    source_doc = next((b.source_doc for b in blocks if b.source_doc), "")
    revision = next((b.revision for b in blocks if b.revision), "")
    conflicts = _conflict_index(drafts)

    front = [
        "---",
        f'source_filename: "{filename}"',
        f'source_doc: "{source_doc}"',
        f'revision: "{revision}"',
        f"file_type: {file_type}",
        f"language: {language}",
        f"page_count: {pages}",
        "extraction_quality:",
        f"  fused_per_1k_words: {metrics['fused_per_1k_words']}",
        f"  orphan_pipe_ratio: {metrics['orphan_pipe_ratio']}",
        f"  blank_line_ratio: {metrics['blank_line_ratio']}",
        f"  word_count: {int(metrics['word_count'])}",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "---",
        "",
    ]

    body: list[str] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]

        if block.kind == KIND_HEADING:
            body.append(f"## {block.text}\n")
            index += 1
            continue

        if block.kind == KIND_TABLE:
            header = block.table_header
            group = []
            while (
                index < len(blocks)
                and blocks[index].kind == KIND_TABLE
                and blocks[index].table_header == header
                and blocks[index].section == block.section
            ):
                group.append(blocks[index])
                index += 1
            body.append(_provenance_comment(block))
            body.extend(_render_table(header, group, conflicts))
            body.append("")
            continue

        body.append(_provenance_comment(block))
        conflict = _conflict_for(block, conflicts)
        if conflict:
            body.append(
                f"> ⚠️ REVIEW: values differ across sources ({', '.join(conflict) or 'multiple sources'})"
            )
        body.append(f"{block.text}\n")
        index += 1

    return "\n".join(front + body).rstrip() + "\n"


def _render_table(header, rows: list[Block], conflicts) -> list[str]:
    """Render table blocks as a GFM pipe table."""
    width = max(len(row.cells or []) for row in rows) if rows else 0
    if header:
        columns = [_md_escape_cell(cell) for cell in header]
        columns += [""] * (width - len(columns))
    else:
        columns = [f"Column {i + 1}" for i in range(width)]

    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    flagged: list[str] = []
    for row in rows:
        cells = [_md_escape_cell(cell) for cell in (row.cells or [])]
        cells += [""] * (len(columns) - len(cells))
        lines.append("| " + " | ".join(cells) + " |")
        conflict = _conflict_for(row, conflicts)
        if conflict:
            flagged.append(f"{cells[0] or 'row'} ({', '.join(conflict)})")

    if flagged:
        lines.append("")
        lines.append(f"> ⚠️ REVIEW: values differ across sources ({'; '.join(flagged)})")
    return lines
