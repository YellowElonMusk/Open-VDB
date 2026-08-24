"""Tests for output format selection and the markdown/SQLite exporters."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.ingestion.exporters import (
    build_markdown,
    build_sqlite,
    export_stem,
    parse_output_formats,
)


class TestParseOutputFormats:
    def test_default_vector(self):
        assert parse_output_formats("vector") == ["vector"]

    def test_multiple_formats_canonical_order(self):
        assert parse_output_formats("sqlite,markdown") == ["markdown", "sqlite"]
        assert parse_output_formats("markdown, vector") == ["vector", "markdown"]

    def test_all_formats(self):
        assert parse_output_formats("vector,markdown,sqlite") == ["vector", "markdown", "sqlite"]

    def test_case_insensitive_and_whitespace(self):
        assert parse_output_formats(" Markdown , SQLITE ") == ["markdown", "sqlite"]

    def test_duplicates_removed(self):
        assert parse_output_formats("markdown,markdown") == ["markdown"]

    def test_unknown_format_rejected(self):
        with pytest.raises(ValueError, match="Unknown output format"):
            parse_output_formats("vector,mongodb")

    def test_empty_rejected(self):
        with pytest.raises(ValueError, match="No output format"):
            parse_output_formats("  , ")


class TestExportStem:
    def test_plain_filename(self):
        assert export_stem("manual.pdf") == "manual"

    def test_unsafe_characters_replaced(self):
        assert export_stem("robot arm/spec v2.pdf") == "spec_v2"

    def test_empty_filename(self):
        assert export_stem("") == "document"


class TestBuildMarkdown:
    def test_contains_source_and_text(self):
        md = build_markdown("faq.pdf", "pdf", "E-042: Replace the servo fuse.")
        assert "# faq" in md
        assert "`faq.pdf`" in md
        assert "E-042: Replace the servo fuse." in md
        assert md.endswith("\n")


class TestBuildSqlite:
    def _open(self, db_bytes: bytes) -> sqlite3.Connection:
        # Write to a temp file so any SQLite build can open it
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        f.write(db_bytes)
        f.close()
        self._path = Path(f.name)
        return sqlite3.connect(f.name)

    def teardown_method(self):
        if getattr(self, "_path", None) and self._path.exists():
            self._path.unlink()

    def _sample_docs(self):
        return [
            {
                "id": "doc-1",
                "filename": "faq.pdf",
                "file_type": "pdf",
                "chunks": [
                    "E-042: Replace the servo fuse and restart the controller.",
                    "E-100: Check the hydraulic pressure valve HPV-200.",
                ],
            },
            {
                "id": "doc-2",
                "filename": "sop.docx",
                "file_type": "docx",
                "chunks": ["Lockout procedure: disconnect main power before service."],
            },
        ]

    def test_documents_and_chunks_stored(self):
        conn = self._open(build_sqlite(self._sample_docs()))
        docs = conn.execute("SELECT id, filename, chunk_count FROM documents ORDER BY id").fetchall()
        assert docs == [("doc-1", "faq.pdf", 2), ("doc-2", "sop.docx", 1)]
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        assert chunks == 3
        conn.close()

    def test_fts_error_code_lookup(self):
        conn = self._open(build_sqlite(self._sample_docs()))
        fts = conn.execute("SELECT value FROM meta WHERE key = 'fts'").fetchone()[0]
        assert fts == "fts5"

        rows = conn.execute(
            """
            SELECT c.content, d.filename
            FROM chunks_fts f
            JOIN chunks c ON c.id = f.rowid
            JOIN documents d ON d.id = c.document_id
            WHERE chunks_fts MATCH '"E-042"'
            """
        ).fetchall()
        assert len(rows) == 1
        assert "servo fuse" in rows[0][0]
        assert rows[0][1] == "faq.pdf"
        conn.close()

    def test_empty_document_list(self):
        conn = self._open(build_sqlite([]))
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        conn.close()
