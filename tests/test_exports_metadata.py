"""The SQLite and Markdown outputs must carry structure, not flat text.

Both are built from the same parse as the vector index, so they inherit
the extraction fix — but they also have to expose it: an exactly-queryable
fault code table, real GFM tables, and provenance an agent can cite.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.ingestion.exporters import build_markdown, build_sqlite
from src.ingestion.parser import parse_file
from src.ingestion.pipeline import chunk_text


@pytest.fixture
def artifacts(manual_pdf):
    blocks = parse_file("R3 Vac Ed.01 v0.4.pdf", manual_pdf)
    drafts = chunk_text(blocks)
    return blocks, drafts


@pytest.fixture
def sqlite_conn(artifacts):
    blocks, drafts = artifacts
    payload = [{
        "id": "doc-1",
        "filename": "R3 Vac Ed.01 v0.4.pdf",
        "file_type": "pdf",
        "chunks": drafts,
        "blocks": blocks,
    }]
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        handle.write(build_sqlite(payload))
        path = Path(handle.name)
    conn = sqlite3.connect(path)
    yield conn
    conn.close()
    path.unlink()


class TestSqliteFaultCodes:
    def test_fault_codes_table_is_populated(self, sqlite_conn):
        rows = sqlite_conn.execute("SELECT code, description FROM fault_codes ORDER BY code").fetchall()
        codes = [row[0] for row in rows]
        assert codes == ["AE-02-3605-2-4", "AF-01-3021-6-1", "AF-01-3022-6-1"]

    def test_lookup_is_an_exact_query_not_a_similarity_search(self, sqlite_conn):
        """Adjacent codes must resolve to their own row, never a neighbour."""
        row = sqlite_conn.execute(
            "SELECT code, description FROM fault_codes WHERE code = ?", ("AF-01-3022-6-1",)
        ).fetchone()
        assert row[0] == "AF-01-3022-6-1"
        assert "Slope is too steep" in row[1]

        missing = sqlite_conn.execute(
            "SELECT code FROM fault_codes WHERE code = ?", ("AF-01-9999-6-1",)
        ).fetchone()
        assert missing is None, "an unknown code must return nothing, not a near match"

    def test_fault_codes_carry_source_and_page(self, sqlite_conn):
        row = sqlite_conn.execute(
            "SELECT source_doc, page FROM fault_codes WHERE code = 'AE-02-3605-2-4'"
        ).fetchone()
        assert row[0] == "R3 Vac"
        assert row[1] >= 1


class TestSqliteChunkMetadata:
    def test_metadata_columns_are_populated(self, sqlite_conn):
        row = sqlite_conn.execute(
            "SELECT page, section, kind, source_doc, revision, provenance, needs_review"
            " FROM chunks WHERE content LIKE '%AF-01-3021-6-1%'"
        ).fetchone()
        page, section, kind, source_doc, revision, provenance, needs_review = row

        assert page >= 1
        assert "FAULT CODES" in section
        assert kind == "table"
        assert source_doc == "R3 Vac"
        assert revision == "Ed.01 v0.4"
        assert "R3 Vac Ed.01 v0.4 p." in provenance
        assert needs_review in (0, 1)

    def test_search_mode_is_recorded_for_the_agent(self, sqlite_conn):
        mode = sqlite_conn.execute("SELECT value FROM meta WHERE key = 'search_mode'").fetchone()[0]
        assert mode in {"fts5", "like"}

    def test_full_text_search_finds_a_row(self, sqlite_conn):
        mode = sqlite_conn.execute("SELECT value FROM meta WHERE key = 'search_mode'").fetchone()[0]
        if mode != "fts5":
            pytest.skip("SQLite build without FTS5")
        rows = sqlite_conn.execute(
            "SELECT c.content FROM chunks_fts f JOIN chunks c ON c.id = f.rowid"
            " WHERE chunks_fts MATCH ? ORDER BY rank LIMIT 3",
            ('"AF-01-3021-6-1"',),
        ).fetchall()
        assert any("AF-01-3021-6-1" in row[0] for row in rows)

    def test_indexes_exist(self, sqlite_conn):
        names = {
            row[0]
            for row in sqlite_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "ix_chunks_source_doc" in names
        assert "ix_chunks_section" in names


class TestMarkdown:
    @pytest.fixture
    def markdown(self, artifacts):
        blocks, drafts = artifacts
        return build_markdown("R3 Vac Ed.01 v0.4.pdf", "pdf", blocks, drafts)

    def test_front_matter_records_the_extraction(self, markdown):
        assert markdown.startswith("---\n")
        for key in ("source_filename:", "file_type:", "language:", "page_count:",
                    "extraction_quality:", "fused_per_1k_words:", "generated_at:"):
            assert key in markdown

    def test_real_gfm_tables_are_emitted(self, markdown):
        assert "| PROBLEM | POSSIBLE CAUSE | SOLUTION |" in markdown
        assert "| --- | --- | --- |" in markdown
        assert "| AF-01-3021-6-1 |" in markdown

    def test_headings_are_real_markdown(self, markdown):
        assert "## 6. TROUBLESHOOTING" in markdown
        assert "## 6.1 FAULT CODES" in markdown

    def test_provenance_comments_are_present(self, markdown):
        assert "<!-- src: R3 Vac Ed.01 v0.4 p.1 -->" in markdown

    def test_no_orphan_pipe_fragments(self, markdown):
        """Every pipe belongs to a real table row, not a whitespace artefact."""
        for line in markdown.splitlines():
            if "|" in line:
                assert line.strip().startswith("|") and line.strip().endswith("|")

    def test_conflicted_blocks_are_flagged_inline(self, artifacts):
        from src.ingestion.dedup import deduplicate

        blocks, drafts = artifacts
        markdown = build_markdown("R3 Vac.pdf", "pdf", blocks, deduplicate(drafts))
        # The two adjacent fault codes conflict, so the table is annotated.
        assert "⚠️ REVIEW" in markdown
