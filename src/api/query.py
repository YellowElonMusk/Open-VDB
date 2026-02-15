"""Semantic search / query endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import QueryRequest, QueryResponse, QueryResult
from src.core.auth import get_current_tenant
from src.db.session import get_db
from src.ingestion.pipeline import embed_texts
from src.models.database import Chunk, Collection, Document, Tenant

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
async def query_collection(
    body: QueryRequest,
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

    # Embed the query
    query_embedding = (await embed_texts([body.query]))[0]

    # Perform cosine similarity search scoped to the tenant's collection
    stmt = (
        select(
            Chunk.id,
            Chunk.document_id,
            Chunk.content,
            Document.source,
            Chunk.embedding.cosine_distance(query_embedding).label("distance"),
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.collection_id == body.collection_id)
        .order_by("distance")
        .limit(body.top_k)
    )
    rows = await db.execute(stmt)

    results = [
        QueryResult(
            chunk_id=row.id,
            document_id=row.document_id,
            source=row.source,
            content=row.content,
            score=1 - row.distance,  # convert distance to similarity
        )
        for row in rows.all()
    ]
    return QueryResponse(results=results)
