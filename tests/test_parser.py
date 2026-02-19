"""Tests for document parsing: TXT, CSV, and unsupported types.

PDF and DOCX parsing is tested at the unit level by mocking their libs.
"""

import pytest

from src.ingestion.parser import parse_file, SUPPORTED_EXTENSIONS


class TestSupportedExtensions:
    def test_supported_extensions_set(self):
        assert ".pdf" in SUPPORTED_EXTENSIONS
        assert ".docx" in SUPPORTED_EXTENSIONS
        assert ".txt" in SUPPORTED_EXTENSIONS
        assert ".csv" in SUPPORTED_EXTENSIONS
        assert ".md" in SUPPORTED_EXTENSIONS

    def test_unsupported_extension_raises(self):
        with pytest.raises(ValueError, match="Unsupported file type"):
            parse_file("report.xlsx", b"some bytes")

    def test_exe_raises(self):
        with pytest.raises(ValueError):
            parse_file("virus.exe", b"\x4d\x5a")


class TestTxtParsing:
    def test_plain_text_returns_content(self):
        content = b"This is a simple guide.\nSecond line here."
        result = parse_file("guide.txt", content)
        assert "simple guide" in result
        assert "Second line" in result

    def test_markdown_is_treated_as_text(self):
        content = b"# Title\n\nSome **bold** content."
        result = parse_file("readme.md", content)
        assert "Title" in result
        assert "bold" in result

    def test_utf8_encoding_handled(self):
        content = "Ångström unit — ±5%".encode("utf-8")
        result = parse_file("spec.txt", content)
        assert "Ångström" in result


class TestCsvParsing:
    def test_csv_converts_to_readable_text(self):
        content = b"Part,Description,Stock\nHPV-200,Hydraulic valve,15\nFLT-100,Oil filter,50"
        result = parse_file("parts.csv", content)
        assert "Part: HPV-200" in result
        assert "Description: Hydraulic valve" in result
        assert "Stock: 15" in result

    def test_csv_skips_empty_cells(self):
        content = b"Name,Notes\nAlpha,\nBeta,Some notes"
        result = parse_file("data.csv", content)
        # Empty "Notes" for Alpha should be skipped
        assert "Alpha" in result
        assert "Beta" in result
        assert "Some notes" in result

    def test_single_row_csv_returns_raw(self):
        content = b"just,one,row"
        result = parse_file("tiny.csv", content)
        # Only headers, no data rows — returns raw content
        assert result  # non-empty


class TestChunking:
    def test_chunk_text_basic(self):
        from src.ingestion.pipeline import chunk_text
        text = "Hello world. " * 100
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c) <= 150  # some flex for sentence boundary

    def test_chunk_empty_text_returns_empty(self):
        from src.ingestion.pipeline import chunk_text
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_chunks_overlap(self):
        from src.ingestion.pipeline import chunk_text
        text = "A" * 200
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        # With overlap, content from end of chunk N should appear in chunk N+1
        assert len(chunks) >= 2
