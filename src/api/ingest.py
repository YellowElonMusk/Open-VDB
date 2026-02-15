"""Ingestion endpoints — push data into the vector database."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import DocumentResponse, IngestTextRequest
from src.core.auth import get_current_tenant
from src.db.session import get_db
from src.ingestion.pipeline import ingest_text
from src.models.database import Chunk, Collection, Tenant

router = APIRouter(prefix="/ingest", tags=["ingestion"])


@router.post("/text", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def ingest_text_endpoint(
    body: IngestTextRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # Verify the collection belongs to this tenant
    result = await db.execute(
        select(Collection).where(
            Collection.id == body.collection_id,
            Collection.tenant_id == tenant.id,
        )
    )
    collection = result.scalar_one_or_none()
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    doc = await ingest_text(
        db=db,
        collection_id=body.collection_id,
        source=body.source,
        content=body.content,
        metadata=body.metadata,
    )

    # Count chunks
    count_result = await db.execute(select(func.count()).where(Chunk.document_id == doc.id))
    chunk_count = count_result.scalar()

    return DocumentResponse(
        id=doc.id,
        source=doc.source,
        collection_id=doc.collection_id,
        chunk_count=chunk_count,
        created_at=doc.created_at,
    )
