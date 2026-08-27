"""The extractor must not weld words together or lose table structure.

The previous implementation used a text extractor in "layout" mode, which
snaps glyphs to a character grid. Where a table cell ended within one grid
cell of the next column, the separating space was destroyed and the two
columns fused into tokens like "isout of charge". This asserts the class
of defect is gone and that rows keep their header binding.
"""

from src.ingestion.parser import KIND_TABLE, parse_file
from src.ingestion.pipeline import assessment_text
from src.ingestion.quality_gate import count_fused_words


def test_no_fused_words_anywhere(manual_pdf):
    blocks = parse_file("R3 Scrub Ed.01 v0.4.pdf", manual_pdf)
    text = assessment_text(blocks)

    assert count_fused_words(text) == 0, f"fused words found in:\n{text}"


def test_known_fusion_victims_survive_intact(manual_pdf):
    """Phrases that fused at column boundaries in the old extractor."""
    text = assessment_text(parse_file("manual.pdf", manual_pdf))

    for phrase in ("is out of charge", "is triggered", "is not mounted"):
        assert phrase in text, f"expected {phrase!r} to survive extraction"
    for corruption in ("isout", "istriggered", "ismounted", "iscase"):
        assert corruption not in text.lower()


def test_table_row_binds_header_to_every_value(manual_pdf):
    blocks = parse_file("manual.pdf", manual_pdf)
    rows = [b for b in blocks if b.kind == KIND_TABLE]
    assert rows, "no table rows extracted"

    start = next(b for b in rows if "THE ROBOT DOES NOT START" in b.text)

    assert start.table_header[:3] == ["PROBLEM", "POSSIBLE CAUSE", "SOLUTION"]
    assert "PROBLEM: THE ROBOT DOES NOT START" in start.text
    assert "POSSIBLE CAUSE: The battery is out of charge" in start.text
    assert "SOLUTION: Perform a complete recharge cycle" in start.text


def test_wrapped_cell_continuations_stay_in_their_cell(manual_pdf):
    """A cell wrapped over several lines must rejoin, not leak sideways."""
    blocks = parse_file("manual.pdf", manual_pdf)
    row = next(b for b in blocks if b.kind == KIND_TABLE and "THE ROBOT DOES NOT START" in b.text)

    cause = row.cells[1]
    solution = row.cells[2]
    assert cause == "The battery is out of charge and the onboard charger is disconnected"
    assert solution == "Perform a complete recharge cycle and attempt restarting the robot."
    # The continuation of column 1 must not be pipe-joined to column 3.
    assert "recharge" not in cause


def test_table_content_is_not_duplicated_as_prose(manual_pdf):
    blocks = parse_file("manual.pdf", manual_pdf)
    prose = " ".join(b.text for b in blocks if b.kind != KIND_TABLE)
    assert "THE ROBOT DOES NOT START" not in prose


def test_reading_order_gives_rows_the_right_section(manual_pdf):
    blocks = parse_file("manual.pdf", manual_pdf)
    fault_rows = [b for b in blocks if b.kind == KIND_TABLE and "AF-01-3021-6-1" in b.text]
    assert fault_rows, "fault code row not found"
    assert "FAULT CODES" in fault_rows[0].section


def test_document_identity_parsed_from_filename(manual_pdf):
    blocks = parse_file("R3 Vac Ed.01 v0.6.pdf", manual_pdf)
    assert blocks[0].source_doc == "R3 Vac"
    assert blocks[0].revision == "Ed.01 v0.6"
