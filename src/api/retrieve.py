"""Retrieval endpoint — what AI SaaS tools call.

This is the key privacy feature: AI tools get ONLY the relevant snippets
they need to function, never full manuals or proprietary documents.

Two search modes:
- semantic: vector similarity over embedded chunks (documents uploaded
  with the 'vector' output). Best for natural language questions.
- keyword:  exact text matching over chunk content. Best for error codes,
  part numbers, and model names — works for EVERY document and never
  calls an embeddings API.

Works with both admin and retrieval API keys.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import RetrieveRequest, RetrieveResponse, RetrievedSnippet
from src.core.auth import AuthResult, authenticate
from src.core.config import settings
from src.db.session import get_db
from src.ingestion.pipeline import embed_texts
from src.models.database import Chunk, Document

router = APIRouter(prefix="/retrieve", tags=["retrieval"])

# How many candidate chunks keyword mode fetches before ranking in-process
KEYWORD_CANDIDATE_LIMIT = 500


def _escape_like(term: str) -> str:
    """Escape ILIKE wildcards so user input matches literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def keyword_terms(query: str) -> list[str]:
    """Split a query into search terms (whole query is used if it's one word)."""
    terms = [t for t in query.split() if len(t) >= 2]
    return terms or [query.strip()]


def score_keyword_match(content: str, query: str, terms: list[str]) -> float:
    """Score a chunk for a keyword query.

    Exact phrase match scores 1.0; otherwise the fraction of query terms
    present (case-insensitive), scaled to stay below any phrase match.
    """
    haystack = content.lower()
    if query.strip().lower() in haystack:
        return 1.0
    matched = sum(1 for t in terms if t.lower() in haystack)
    return round(0.99 * matched / len(terms), 4) if terms else 0.0


@router.post("", response_model=RetrieveResponse)
async def retrieve(
    body: RetrieveRequest,
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Search across all of this tenant's documents.

    Returns only the relevant text snippets — not full documents.
    This is what AI SaaS tools (CRM bots, support agents, etc.) call
    to get the context they need without accessing proprietary docs.

    Set mode='keyword' for exact matching (error codes, part numbers);
    mode='semantic' (default) for natural language similarity search.
    """
    if body.mode == "keyword":
        snippets = await _keyword_search(db, auth, body)
    else:
        snippets = await _semantic_search(db, auth, body)
    return RetrieveResponse(snippets=snippets, query=body.query)


async def _semantic_search(
    db: AsyncSession, auth: AuthResult, body: RetrieveRequest
) -> list[RetrievedSnippet]:
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=400,
            detail=(
                "Semantic search requires an OpenAI API key (VDB_OPENAI_API_KEY). "
                "Use mode='keyword' instead — it works without embeddings."
            ),
        )

    # Embed the query
    query_embedding = (await embed_texts([body.query]))[0]

    # Search across ALL of this tenant's embedded documents
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
            Chunk.embedding.is_not(None),
        )
        .order_by("distance")
        .limit(body.top_k)
    )
    rows = await db.execute(stmt)

    return [
        RetrievedSnippet(
            snippet_id=row.id,
            content=row.content,
            source_filename=row.filename,
            relevance_score=round(1 - row.distance, 4),
        )
        for row in rows.all()
    ]


async def _keyword_search(
    db: AsyncSession, auth: AuthResult, body: RetrieveRequest
) -> list[RetrievedSnippet]:
    terms = keyword_terms(body.query)
    conditions = [
        Chunk.content.ilike(f"%{_escape_like(t)}%", escape="\\") for t in terms
    ]

    stmt = (
        select(Chunk.id, Chunk.content, Document.filename)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Document.tenant_id == auth.tenant.id,
            Document.status == "ready",
            or_(*conditions),
        )
        .limit(KEYWORD_CANDIDATE_LIMIT)
    )
    rows = await db.execute(stmt)

    scored = [
        (score_keyword_match(row.content, body.query, terms), row)
        for row in rows.all()
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)

    return [
        RetrievedSnippet(
            snippet_id=row.id,
            content=row.content,
            source_filename=row.filename,
            relevance_score=score,
        )
        for score, row in scored[: body.top_k]
    ]
