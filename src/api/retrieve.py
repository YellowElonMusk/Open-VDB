"""Retrieval endpoint — what AI SaaS tools call.

This is the key privacy feature: AI tools get ONLY the relevant snippets
they need to function, never full manuals or proprietary documents.

Search is hybrid and always runs every leg:

  vector   pgvector cosine similarity (HNSW)  — meaning
  fts      Postgres full-text search          — words, stemmed per language
  exact    trigram-indexed substring match    — codes, part numbers

The three ranked lists are fused with reciprocal rank fusion. Callers do
not choose an algorithm: an agent asked to pick between "semantic" and
"keyword" will pick wrong, and a wrong pick returns a confident wrong
answer rather than an obvious failure.

Every leg orders in SQL before it limits. Limiting an unordered set and
ranking afterwards — as this endpoint used to do — silently discards the
best match whenever a term appears more often than the limit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import RetrieveRequest, RetrieveResponse, RetrievedSnippet
from src.core.auth import AuthResult, authenticate
from src.core.config import settings
from src.db.session import get_db
from src.ingestion.pipeline import embed_texts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/retrieve", tags=["retrieval"])

# Candidates fetched per leg before fusion.
LEG_LIMIT = 50
# Reciprocal rank fusion constant. 60 is the value from the original RRF
# paper and damps the difference between adjacent ranks.
RRF_K = 60

# Leg weights. A literal substring hit on the query is the strongest
# evidence available — it is the difference between the fault code the
# caller asked about and one that merely resembles it — so the exact leg
# is weighted above the others. With these values a top-ranked exact match
# always outranks anything that matched no substring at all.
LEG_WEIGHTS = {"exact": 3.0, "fts": 1.0, "vector": 1.0}

_COMMON_COLUMNS = """
    c.id, c.content, c.page, c.section, c.source_doc, c.revision,
    c.needs_review, d.filename
"""
_TENANT_FILTER = """
    JOIN documents d ON d.id = c.document_id
    WHERE d.tenant_id = :tenant_id AND d.status = 'ready'
"""


@dataclass
class Candidate:
    """One row returned by a search leg."""

    id: str
    content: str
    page: int | None
    section: str | None
    source_doc: str | None
    revision: str | None
    needs_review: bool
    filename: str


def _to_candidate(row) -> Candidate:
    return Candidate(
        id=str(row.id),
        content=row.content,
        page=row.page,
        section=row.section,
        source_doc=row.source_doc,
        revision=row.revision,
        needs_review=bool(row.needs_review),
        filename=row.filename,
    )


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so the query matches literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _exact_leg(db: AsyncSession, tenant_id, query: str) -> list[Candidate]:
    """Literal substring match, ranked by trigram similarity.

    Uses the GIN trigram index rather than a sequential scan, and orders
    before limiting so a common term cannot bury the exact hit.
    """
    stmt = sql_text(
        f"""
        SELECT {_COMMON_COLUMNS}, similarity(c.content, :query) AS score
        FROM chunks c
        {_TENANT_FILTER}
          AND c.content ILIKE '%' || :pattern || '%' ESCAPE '\\'
        ORDER BY score DESC, length(c.content) ASC
        LIMIT :limit
        """
    )
    rows = await db.execute(
        stmt,
        {
            "tenant_id": tenant_id,
            "query": query,
            "pattern": _escape_like(query),
            "limit": LEG_LIMIT,
        },
    )
    return [_to_candidate(row) for row in rows.all()]


# plainto_tsquery ANDs its terms, so a natural-language question only
# matches a chunk containing every word — which for "robot will not power
# on, battery flat" is no chunk at all. Rewriting the operators to OR lets
# partial matches surface, and ts_rank_cd still puts the chunks matching
# the most terms first. The query text is sanitised by plainto_tsquery
# before the rewrite, so no user input reaches the tsquery parser raw.
_ANY_TERM = "NULLIF(replace(plainto_tsquery('{config}', :query)::text, '&', '|'), '')::tsquery"


async def _fts_leg(db: AsyncSession, tenant_id, query: str) -> list[Candidate]:
    """Full-text search against the per-language generated tsvector.

    The corpus is mixed English and French, so the query is compiled under
    both configurations and a chunk matches under either.
    """
    english = _ANY_TERM.format(config="english")
    french = _ANY_TERM.format(config="french")
    stmt = sql_text(
        f"""
        SELECT {_COMMON_COLUMNS},
               GREATEST(
                   ts_rank_cd(c.content_tsv, {english}),
                   ts_rank_cd(c.content_tsv, {french})
               ) AS score
        FROM chunks c
        {_TENANT_FILTER}
          AND (c.content_tsv @@ {english} OR c.content_tsv @@ {french})
        ORDER BY score DESC
        LIMIT :limit
        """
    )
    rows = await db.execute(stmt, {"tenant_id": tenant_id, "query": query, "limit": LEG_LIMIT})
    return [_to_candidate(row) for row in rows.all()]


async def _vector_leg(db: AsyncSession, tenant_id, query: str) -> list[Candidate]:
    """Cosine similarity over embedded chunks (HNSW index)."""
    if not settings.openai_api_key:
        return []
    try:
        embedding = (await embed_texts([query]))[0]
    except Exception as e:  # embeddings unavailable — the other legs still answer
        logger.warning("vector leg unavailable: %s: %s", type(e).__name__, e)
        return []

    stmt = sql_text(
        f"""
        SELECT {_COMMON_COLUMNS},
               c.embedding <=> CAST(:embedding AS vector) AS distance
        FROM chunks c
        {_TENANT_FILTER}
          AND c.embedding IS NOT NULL
        ORDER BY distance ASC
        LIMIT :limit
        """
    )
    rows = await db.execute(
        stmt,
        {"tenant_id": tenant_id, "embedding": str(embedding), "limit": LEG_LIMIT},
    )
    return [_to_candidate(row) for row in rows.all()]


def reciprocal_rank_fusion(legs: dict[str, list[Candidate]]) -> list[tuple[Candidate, float]]:
    """Fuse ranked lists: each leg contributes weight / (K + rank)."""
    scores: dict[str, float] = {}
    best: dict[str, Candidate] = {}

    for leg, candidates in legs.items():
        weight = LEG_WEIGHTS.get(leg, 1.0)
        for rank, candidate in enumerate(candidates, start=1):
            scores[candidate.id] = scores.get(candidate.id, 0.0) + weight / (RRF_K + rank)
            best.setdefault(candidate.id, candidate)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [(best[chunk_id], score) for chunk_id, score in ranked]


@router.post("", response_model=RetrieveResponse)
async def retrieve(
    body: RetrieveRequest,
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Search across all of this tenant's documents.

    Returns only the relevant text snippets — not full documents. Each
    snippet carries the manual, revision, page and section it came from so
    the calling agent can cite its source, plus `needs_review` when the
    text belongs to a group whose sources disagreed on facts.
    """
    requested_mode = body.model_dump().get("mode")
    if requested_mode is not None:
        logger.warning(
            "RetrieveRequest.mode=%r is deprecated and ignored: retrieval is always hybrid "
            "(vector + full-text + exact). Remove the field from your client.",
            requested_mode,
        )

    tenant_id = auth.tenant.id
    legs = {
        "exact": await _exact_leg(db, tenant_id, body.query),
        "fts": await _fts_leg(db, tenant_id, body.query),
        "vector": await _vector_leg(db, tenant_id, body.query),
    }

    fused = reciprocal_rank_fusion(legs)[: body.top_k]
    top_score = fused[0][1] if fused else 1.0

    snippets = [
        RetrievedSnippet(
            snippet_id=candidate.id,
            content=candidate.content,
            source_filename=candidate.filename,
            relevance_score=round(score / top_score, 4) if top_score else 0.0,
            page=candidate.page,
            section=candidate.section,
            source_doc=candidate.source_doc,
            revision=candidate.revision,
            needs_review=candidate.needs_review,
        )
        for candidate, score in fused
    ]
    return RetrieveResponse(snippets=snippets, query=body.query)
