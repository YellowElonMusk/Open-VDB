"""Document parsers — extract plain text from uploaded files.

Supports: PDF, DOCX, TXT, CSV, Markdown.
OEMs upload manuals, guides, SOPs in these formats and the platform
automatically converts them to text for chunking and embedding.
"""

import csv
import io
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
    reader = PdfReader(io.BytesIO(content))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n\n".join(pages)


def _parse_docx(content: bytes) -> str:
    doc = docx.Document(io.BytesIO(content))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


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
