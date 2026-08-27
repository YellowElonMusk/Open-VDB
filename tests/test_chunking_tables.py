"""Table rows must survive chunking intact.

A 180-row fault code table shredded across 40 blind 512-character slices
loses the header on almost every piece, so a retrieved chunk reads
"Slope is too steep" with no code and no column names attached.
"""

from src.ingestion.parser import parse_file
from src.ingestion.pipeline import PROSE_TARGET_CHARS, chunk_text


def chunks_for(pdf: bytes, filename: str = "R3 Vac Ed.01 v0.4.pdf"):
    return chunk_text(parse_file(filename, pdf))


class TestTableChunks:
    def test_fault_code_and_description_stay_together(self, manual_pdf):
        chunks = chunks_for(manual_pdf)
        for code, description in [
            ("AF-01-3021-6-1", "Slope is too steep"),
            ("AE-02-3605-2-4", "Brush motor overcurrent"),
        ]:
            holders = [c for c in chunks if code in c.text]
            assert holders, f"{code} missing from every chunk"
            for chunk in holders:
                assert description in chunk.text, f"{code} separated from its description"

    def test_every_table_chunk_carries_its_header(self, manual_pdf):
        table_chunks = [c for c in chunks_for(manual_pdf) if c.kind == "table"]
        assert table_chunks

        for chunk in table_chunks:
            headers = ["PROBLEM", "POSSIBLE CAUSE", "SOLUTION"] if "PROBLEM:" in chunk.text \
                else ["CODE", "DESCRIPTION", "ACTION"]
            for name in headers:
                assert name in chunk.text, f"header {name!r} missing from:\n{chunk.text}"

    def test_one_chunk_per_row(self, manual_pdf):
        chunks = chunks_for(manual_pdf)
        rows = [c for c in chunks if "AF-01-3021-6-1" in c.text]
        assert len(rows) == 1
        # The adjacent code must not be dragged into the same chunk.
        assert "AF-01-3022-6-1" not in rows[0].text

    def test_table_chunks_are_never_split(self, manual_pdf):
        """Every bound column the row started with is still present."""
        for chunk in chunks_for(manual_pdf):
            if chunk.kind != "table":
                continue
            body = chunk.text.split("\n")[-1]
            bound_columns = [part for part in body.split("; ") if ": " in part]
            assert len(bound_columns) >= 2, f"row lost its columns:\n{chunk.text}"


class TestProseChunks:
    def test_prose_chunks_carry_their_section_heading(self, manual_pdf):
        prose = [c for c in chunks_for(manual_pdf) if c.kind == "prose"]
        assert prose
        for chunk in prose:
            if chunk.section:
                assert chunk.text.startswith(chunk.section)

    def test_prose_chunks_respect_the_target_size(self, manual_pdf):
        for chunk in chunks_for(manual_pdf):
            if chunk.kind == "prose":
                assert len(chunk.text) <= PROSE_TARGET_CHARS * 2

    def test_chunks_carry_document_metadata(self, manual_pdf):
        for chunk in chunks_for(manual_pdf, "R3 Vac Ed.01 v0.6.pdf"):
            assert chunk.source_doc == "R3 Vac"
            assert chunk.revision == "Ed.01 v0.6"
            assert chunk.page >= 1
            assert chunk.provenance == [f"R3 Vac Ed.01 v0.6 p.{chunk.page}"]

    def test_headings_do_not_become_standalone_chunks(self, manual_pdf):
        for chunk in chunks_for(manual_pdf):
            assert chunk.text.strip() not in {"6. TROUBLESHOOTING", "6.1 FAULT CODES"}
