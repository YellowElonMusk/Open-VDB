"""Ingestion pipeline: parse file, chunk text, embed it, and store it."""

import hashlib
import math
import re

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
    """Split text into overlapping chunks, preferring sentence boundaries."""
    if not text.strip():
        return []
    if overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            for separator in ["\n\n", "\n", ". ", "? ", "! "]:
                break_at = text.rfind(separator, start + chunk_size // 2, end)
                if break_at != -1:
                    end = break_at + len(separator)
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap if end < len(text) else end

    return chunks


def _local_embedding(text: str) -> list[float]:
    """Create a deterministic offline feature-hashing vector.

    This is intentionally dependency-free and provides solid keyword/fuzzy retrieval.
    Set VDB_EMBEDDING_PROVIDER=openai for stronger semantic retrieval.
    """
    vector = [0.0] * settings.embedding_dimensions
    tokens = re.findall(r"[\w'-]+", text.lower(), flags=re.UNICODE)
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
        index = int.from_bytes(digest[:8], "big") % settings.embedding_dimensions
        sign = 1.0 if digest[8] & 1 else -1.0
        vector[index] += sign

    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude:
        vector = [value / magnitude for value in vector]
    return vector


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate local or OpenAI embeddings."""
    if settings.embedding_provider == "local":
        return [_local_embedding(text) for text in texts]

    if not settings.openai_api_key:
        raise RuntimeError("VDB_OPENAI_API_KEY is required when using OpenAI embeddings")

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
        dimensions=settings.embedding_dimensions,
    )
    return [item.embedding for item in response.data]


async def process_upload(
    db: AsyncSession,
    document: Document,
    file_content: bytes,
) -> Document:
    """Run the full parse -> chunk -> embed -> store pipeline."""
    try:
        text = parse_file(document.filename, file_content)
        if not text.strip():
            raise ValueError("No text content could be extracted from the file")

        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("Text extraction produced no usable chunks")

        embeddings = await embed_texts(chunks)
        if len(embeddings) != len(chunks):
            raise RuntimeError("Embedding provider returned an unexpected result count")

        for index, (content, embedding) in enumerate(zip(chunks, embeddings)):
            db.add(
                Chunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=content,
                    embedding=embedding,
                )
            )

        document.status = "ready"
        document.chunk_count = len(chunks)
        document.error_message = None
        await db.commit()
    except Exception as exc:
        await db.rollback()
        document.status = "failed"
        document.error_message = str(exc)[:1000]
        db.add(document)
        await db.commit()

    await db.refresh(document)
    return document
