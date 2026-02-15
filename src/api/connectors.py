"""Connector sync endpoint — pull data from external systems into the vector DB."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import ConnectorSyncRequest, DocumentResponse
from src.connectors.registry import get_connector, list_connectors
from src.core.auth import get_current_tenant
from src.db.session import get_db
from src.ingestion.pipeline import ingest_text
from src.models.database import Collection, Chunk, Tenant
from sqlalchemy import func

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.get("/types", response_model=list[str])
async def get_connector_types():
    return list_connectors()


@router.post("/sync", response_model=list[DocumentResponse], status_code=status.HTTP_201_CREATED)
async def sync_connector(
    body: ConnectorSyncRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # Verify collection ownership
    result = await db.execute(
        select(Collection).where(
            Collection.id == body.collection_id,
            Collection.tenant_id == tenant.id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    try:
        connector = get_connector(body.connector_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await connector.authenticate(body.credentials)
    records = await connector.fetch_records(body.config)

    docs = []
    for record in records:
        doc = await ingest_text(
            db=db,
            collection_id=body.collection_id,
            source=f"{body.connector_type}:{record.source_id}",
            content=record.content,
            metadata=record.metadata,
        )
        count_result = await db.execute(select(func.count()).where(Chunk.document_id == doc.id))
        chunk_count = count_result.scalar()
        docs.append(DocumentResponse(
            id=doc.id,
            source=doc.source,
            collection_id=doc.collection_id,
            chunk_count=chunk_count,
            created_at=doc.created_at,
        ))
    return docs
