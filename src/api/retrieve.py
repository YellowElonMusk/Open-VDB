"""Retrieval endpoint — what AI SaaS tools call.

This is the key privacy feature: AI tools get ONLY the relevant snippets
they need to function, never full manuals or proprietary documents.

Works with both admin and retrieval API keys.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import RetrieveRequest, RetrieveResponse, RetrievedSnippet
from src.core.auth import AuthResult, authenticate
from src.db.session import get_db
from src.ingestion.pipeline import embed_texts
from src.models.database import Chunk, Document

router = APIRouter(prefix="/retrieve", tags=["retrieval"])


@router.post("", response_model=RetrieveResponse)
async def retrieve(
    body: RetrieveRequest,
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Semantic search across all of this tenant's documents.

    Returns only the relevant text snippets — not full documents.
    This is what AI SaaS tools (CRM bots, support agents, etc.) call
    to get the context they need without accessing proprietary docs.
    """
    # Embed the query
    query_embedding = (await embed_texts([body.query]))[0]

    # Search across ALL of this tenant's documents
    stmt = (
        select(
            Chunk.id,
            Chunk.content,
            Document.filename,
            Chunk.embedding.cosine_distance(query_embedding).label("distance"),
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Document.tenant_id == auth.tenant.id,
            Document.status == "ready",
        )
        .order_by("distance")
        .limit(body.top_k)
    )
    rows = await db.execute(stmt)

    snippets = [
        RetrievedSnippet(
            snippet_id=row.id,
            content=row.content,
            source_filename=row.filename,
            relevance_score=round(1 - row.distance, 4),
        )
        for row in rows.all()
    ]
    return RetrieveResponse(snippets=snippets, query=body.query)
