"""Ingestion pipeline: parse file → chunk text → embed → store.

This is the core automation — OEMs upload a file and it becomes
a queryable vector database automatically.
"""

import json
import uuid

import openai
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.ingestion.parser import parse_file
from src.models.database import Chunk, Document


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
) -> Document:
    """Full pipeline: parse the file, chunk it, embed it, store chunks.

    Updates the Document record with status and chunk count.
    """
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

        # 3. Embed all chunks
        embeddings = await embed_texts(chunks)

        # 4. Store chunks with embeddings
        for i, (chunk_text_content, embedding) in enumerate(zip(chunks, embeddings)):
            chunk = Chunk(
                document_id=document.id,
                chunk_index=i,
                content=chunk_text_content,
                embedding=embedding,
            )
            db.add(chunk)

        # 5. Mark document as ready
        document.status = "ready"
        document.chunk_count = len(chunks)
        await db.commit()

    except Exception as e:
        document.status = "failed"
        document.error_message = str(e)[:1000]
        await db.commit()

    return document
