"""Export builders — turn parsed documents into portable, agent-friendly files.

Not every use case needs a vector database. Matching a robot error code to
its fix in an FAQ or SOP doc is a lookup, not a semantic search. For those,
OEMs can generate:

- Markdown (.md):  a clean plain-text version of the document that any AI
  agent can read directly (drop it in the agent's context or workspace).
- SQLite (.db):    a standalone, dependency-free SQL database file with the
  document's text chunks and an FTS5 full-text search index. Agents query
  it locally with any SQLite client — no server, no API key.

Both are generated fully offline; no external API calls are involved.
"""

import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path


# Output formats an OEM can choose at upload time.
FORMAT_VECTOR = "vector"
FORMAT_MARKDOWN = "markdown"
FORMAT_SQLITE = "sqlite"
SUPPORTED_OUTPUT_FORMATS = {FORMAT_VECTOR, FORMAT_MARKDOWN, FORMAT_SQLITE}


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

    # Canonical order, no duplicates
    return [f for f in (FORMAT_VECTOR, FORMAT_MARKDOWN, FORMAT_SQLITE) if f in requested]


def export_stem(filename: str) -> str:
    """Filesystem-safe stem for generated export filenames."""
    stem = Path(filename).stem or "document"
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in stem)


def build_markdown(filename: str, file_type: str, text: str) -> str:
    """Render a parsed document as a standalone Markdown file."""
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = (
        f"# {Path(filename).stem}\n\n"
        f"> Source: `{filename}` ({file_type})  \n"
        f"> Generated: {generated}\n\n"
        "---\n\n"
    )
    return header + text.strip() + "\n"


def build_sqlite(documents: list[dict]) -> bytes:
    """Build a standalone SQLite database file and return its bytes.

    `documents` is a list of dicts:
        {"id": str, "filename": str, "file_type": str, "chunks": [str, ...]}

    Schema:
        documents(id, filename, file_type, chunk_count)
        chunks(id, document_id, chunk_index, content)
        chunks_fts — FTS5 full-text index over chunk content (when available)

    Example agent query (find the fix for an error code):
        SELECT c.content, d.filename
        FROM chunks_fts f
        JOIN chunks c ON c.id = f.rowid
        JOIN documents d ON d.id = c.document_id
        WHERE chunks_fts MATCH '"E-042"'
        ORDER BY rank LIMIT 5;
    """
    # Build in a temp file (works on every SQLite build, unlike serialize()).
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
            chunk_count INTEGER NOT NULL
        );
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(id),
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL
        );
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        """
    )

    conn.execute(
        "INSERT INTO meta VALUES ('generated_at', ?)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.execute("INSERT INTO meta VALUES ('generator', 'vectordb-oem-platform')")

    rowid = 0
    for doc in documents:
        conn.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?)",
            (str(doc["id"]), doc["filename"], doc["file_type"], len(doc["chunks"])),
        )
        for i, content in enumerate(doc["chunks"]):
            rowid += 1
            conn.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?)",
                (rowid, str(doc["id"]), i, content),
            )

    # FTS5 index for fast keyword lookup (error codes, part numbers, ...).
    # Some minimal SQLite builds lack FTS5 — the plain chunks table with
    # LIKE queries still works, so degrade gracefully.
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE chunks_fts USING fts5(content, content=chunks, content_rowid=id)"
        )
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
        conn.execute("INSERT INTO meta VALUES ('fts', 'fts5')")
    except sqlite3.OperationalError:
        conn.execute("INSERT INTO meta VALUES ('fts', 'none')")
