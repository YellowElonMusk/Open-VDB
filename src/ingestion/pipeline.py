"""Ingestion pipeline: parse file → chunk text → build the chosen outputs.

This is the core automation — OEMs upload a file and choose what it becomes:

- vector:   chunks are embedded and stored in pgvector (semantic search)
- markdown: a clean .md export is generated for direct agent consumption
- sqlite:   a standalone SQLite .db export with an FTS5 keyword index

Text chunks are always stored, so keyword search works for every document
even when no embeddings were generated (no OpenAI key required).
"""

import openai
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.ingestion.exporters import (
    FORMAT_MARKDOWN,
    FORMAT_SQLITE,
    FORMAT_VECTOR,
    build_markdown,
    build_sqlite,
    export_stem,
)
from src.ingestion.parser import parse_file
from src.models.database import Artifact, Chunk, Document


def chunk_text(
    text: str,
    chunk_size: int = settings.chunk_size,
    overlap: int = settings.chunk_overlap,
) -> list[str]:
    """Split text into overlapping chunks.

    Uses sentence-aware splitting: tries to break on sentence boundaries
    (periods, newlines) rather than cutting mid-word.
    """
    if not text.strip():
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size

        # Try to break at a sentence boundary if we're not at the end
        if end < len(text):
            # Look backwards from `end` for a good break point
            for sep in ["\n\n", "\n", ". ", "? ", "! "]:
                break_at = text.rfind(sep, start + chunk_size // 2, end)
                if break_at != -1:
                    end = break_at + len(sep)
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap if end < len(text) else end

    return chunks


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings via OpenAI. Batches automatically."""
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    return [item.embedding for item in response.data]


async def process_upload(
    db: AsyncSession,
    document: Document,
    file_content: bytes,
    formats: list[str] | None = None,
) -> Document:
    """Full pipeline: parse the file, chunk it, then build the chosen outputs.

    `formats` is the list of output formats the OEM selected at upload
    (defaults to the document's stored output_formats). Updates the Document
    record with status and chunk count.
    """
    if formats is None:
        formats = document.output_formats.split(",")

    try:
        # 1. Parse file to plain text
        text = parse_file(document.filename, file_content)
        if not text.strip():
            document.status = "failed"
            document.error_message = "No text content could be extracted from the file"
            await db.commit()
            return document

        # 2. Chunk the text
        chunks = chunk_text(text)
        if not chunks:
            document.status = "failed"
            document.error_message = "Text extraction produced no usable chunks"
            await db.commit()
            return document

        # 3. Embed chunks only when the vector output was requested
        embeddings: list[list[float] | None]
        if FORMAT_VECTOR in formats:
            embeddings = await embed_texts(chunks)
        else:
            embeddings = [None] * len(chunks)

        # 4. Store chunks (always — keyword search works without embeddings)
        for i, (chunk_text_content, embedding) in enumerate(zip(chunks, embeddings)):
            chunk = Chunk(
                document_id=document.id,
                chunk_index=i,
                content=chunk_text_content,
                embedding=embedding,
            )
            db.add(chunk)

        # 5. Generate downloadable exports for the chosen file formats
        stem = export_stem(document.filename)
        if FORMAT_MARKDOWN in formats:
            md_bytes = build_markdown(document.filename, document.file_type, text).encode("utf-8")
            db.add(
                Artifact(
                    document_id=document.id,
                    format=FORMAT_MARKDOWN,
                    filename=f"{stem}.md",
                    content=md_bytes,
                    size_bytes=len(md_bytes),
                )
            )
        if FORMAT_SQLITE in formats:
            db_bytes = build_sqlite(
                [
                    {
                        "id": document.id,
                        "filename": document.filename,
                        "file_type": document.file_type,
                        "chunks": chunks,
                    }
                ]
            )
            db.add(
                Artifact(
                    document_id=document.id,
                    format=FORMAT_SQLITE,
                    filename=f"{stem}.db",
                    content=db_bytes,
                    size_bytes=len(db_bytes),
                )
            )

        # 6. Mark document as ready
        document.status = "ready"
        document.chunk_count = len(chunks)
        await db.commit()

    except Exception as e:
        document.status = "failed"
        document.error_message = str(e)[:1000]
        await db.commit()

    return document
