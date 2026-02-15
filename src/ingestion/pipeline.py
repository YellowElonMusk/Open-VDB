"""Ingestion pipeline: chunking and embedding."""

import json
import uuid

import openai
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.models.database import Chunk, Document


def chunk_text(text: str, chunk_size: int = settings.chunk_size, overlap: int = settings.chunk_overlap) -> list[str]:
    """Split text into overlapping chunks by character count."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a batch of texts using OpenAI."""
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    return [item.embedding for item in response.data]


async def ingest_text(
    db: AsyncSession,
    collection_id: uuid.UUID,
    source: str,
    content: str,
    metadata: dict | None = None,
) -> Document:
    """Chunk text, embed it, and store in the database."""
    doc = Document(
        collection_id=collection_id,
        source=source,
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    db.add(doc)
    await db.flush()  # get doc.id

    chunks = chunk_text(content)
    embeddings = await embed_texts(chunks)

    for i, (text, embedding) in enumerate(zip(chunks, embeddings)):
        chunk = Chunk(
            document_id=doc.id,
            chunk_index=i,
            content=text,
            embedding=embedding,
        )
        db.add(chunk)

    await db.commit()
    await db.refresh(doc)
    return doc
