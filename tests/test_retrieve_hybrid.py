"""Hybrid retrieval against a real PostgreSQL database.

Covers the two failures that made the old endpoint dangerous:

* `LIMIT 500` was applied before Python-side scoring and without an
  ORDER BY, so for any term appearing in more than 500 chunks the best
  match was silently discarded and the caller got a confidently-scored
  wrong answer.
* Callers had to choose "semantic" or "keyword", and choosing wrong
  returned a plausible answer rather than an obvious failure.

Skipped when no test database is reachable.
"""

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api import retrieve as retrieve_module
from src.api.retrieve import reciprocal_rank_fusion, retrieve
from src.api.schemas import RetrieveRequest
from src.core.auth import AuthResult
from src.db.bootstrap import run_migrations

TEST_DB_ASYNC = os.environ.get(
    "VDB_TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres@/vdbtest?host=/tmp&port=55432",
)
TEST_DB_SYNC = os.environ.get(
    "VDB_TEST_DATABASE_URL_SYNC",
    "postgresql://postgres@/vdbtest?host=/tmp&port=55432",
)

FAULT_CODES = [
    ("AF-01-3021-6-1", "Slope is too steep"),
    ("AF-01-3022-6-1", "Slope is too steep"),
    ("AE-02-3605-2-4", "Brush motor overcurrent"),
]


async def _database_available() -> bool:
    try:
        engine = create_async_engine(TEST_DB_ASYNC)
        async with engine.connect() as conn:
            await conn.execute(sql_text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def db():
    if not await _database_available():
        pytest.skip("no PostgreSQL test database available")

    os.environ["VDB_DATABASE_URL_SYNC"] = TEST_DB_SYNC
    from src.core.config import settings

    settings.database_url_sync = TEST_DB_SYNC
    run_migrations()

    engine = create_async_engine(TEST_DB_ASYNC)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        await session.execute(sql_text("TRUNCATE chunks, documents, api_keys, tenants CASCADE"))
        await session.commit()
        yield session
    await engine.dispose()


class _Tenant:
    def __init__(self, tenant_id):
        self.id = tenant_id


async def seed(session, chunks: list[dict]) -> uuid.UUID:
    """Insert one tenant with one ready document holding `chunks`."""
    tenant_id, document_id = uuid.uuid4(), uuid.uuid4()
    await session.execute(
        sql_text(
            "INSERT INTO tenants (id, name, slug, is_active) VALUES (:id, 'T', :slug, true)"
        ),
        {"id": tenant_id, "slug": f"t-{tenant_id.hex[:8]}"},
    )
    await session.execute(
        sql_text(
            "INSERT INTO documents (id, tenant_id, filename, file_type, file_size_bytes,"
            " status, output_formats, chunk_count) VALUES (:id, :tenant, 'manual.pdf', 'pdf',"
            " 1, 'ready', 'vector', :n)"
        ),
        {"id": document_id, "tenant": tenant_id, "n": len(chunks)},
    )
    for index, chunk in enumerate(chunks):
        await session.execute(
            sql_text(
                "INSERT INTO chunks (id, document_id, chunk_index, content, page, section,"
                " kind, source_doc, revision, needs_review, lang)"
                " VALUES (:id, :doc, :i, :content, :page, :section, :kind, :src, :rev,"
                " :review, :lang)"
            ),
            {
                "id": uuid.uuid4(),
                "doc": document_id,
                "i": index,
                "content": chunk["content"],
                "page": chunk.get("page", 1),
                "section": chunk.get("section", "6.1 FAULT CODES"),
                "kind": chunk.get("kind", "table"),
                "src": chunk.get("source_doc", "R3 Vac"),
                "rev": chunk.get("revision", "v0.4"),
                "review": chunk.get("needs_review", False),
                "lang": chunk.get("lang", "en"),
            },
        )
    await session.commit()
    return tenant_id


def auth_for(tenant_id):
    return AuthResult(tenant=_Tenant(tenant_id), scope="retrieval")


class TestExactFaultCodeLookup:
    async def test_exact_code_ranks_first(self, db):
        tenant_id = await seed(
            db,
            [{"content": f"CODE: {code}; DESCRIPTION: {desc}"} for code, desc in FAULT_CODES],
        )
        response = await retrieve(
            RetrieveRequest(query="AF-01-3022-6-1", top_k=5), auth_for(tenant_id), db
        )
        assert response.snippets, "no snippets returned"
        assert "AF-01-3022-6-1" in response.snippets[0].content
        assert "AF-01-3021-6-1" not in response.snippets[0].content

    async def test_snippets_carry_citable_provenance(self, db):
        tenant_id = await seed(
            db,
            [{
                "content": "CODE: AE-02-3605-2-4; DESCRIPTION: Brush motor overcurrent",
                "page": 14,
                "section": "6.1 FAULT CODES",
                "source_doc": "R3 Vac",
                "revision": "Ed.01 v0.4",
                "needs_review": True,
            }],
        )
        snippet = (
            await retrieve(RetrieveRequest(query="AE-02-3605-2-4"), auth_for(tenant_id), db)
        ).snippets[0]

        assert snippet.page == 14
        assert snippet.section == "6.1 FAULT CODES"
        assert snippet.source_doc == "R3 Vac"
        assert snippet.revision == "Ed.01 v0.4"
        assert snippet.needs_review is True


class TestLimitBeforeScoringBugIsGone:
    async def test_exact_match_survives_a_flood_of_common_term_matches(self, db):
        """>500 chunks share a common term; exactly one holds the phrase.

        The old implementation took an arbitrary unordered 500 rows and
        scored those, so the single real match was usually never seen.
        """
        common = [
            {"content": f"The robot reports a fault on the slope during cycle {i}."}
            for i in range(600)
        ]
        needle = {"content": "The robot reports a fault: hydraulic pressure valve HPV-200 seized."}
        tenant_id = await seed(db, common + [needle])

        response = await retrieve(
            RetrieveRequest(query="hydraulic pressure valve HPV-200", top_k=5),
            auth_for(tenant_id),
            db,
        )
        assert response.snippets
        assert "HPV-200" in response.snippets[0].content

    async def test_every_leg_orders_before_limiting(self, db):
        tenant_id = await seed(
            db, [{"content": f"Slope is too steep on segment {i}"} for i in range(600)]
            + [{"content": "Slope is too steep - push the robot away and retry"}]
        )
        rows = await retrieve_module._exact_leg(db, tenant_id, "push the robot away")
        assert rows, "exact leg returned nothing"
        assert "push the robot away" in rows[0].content


class TestHybridBehaviour:
    async def test_natural_language_query_finds_prose(self, db):
        tenant_id = await seed(
            db,
            [
                {"content": "PROBLEM: THE ROBOT DOES NOT START; SOLUTION: Perform a complete "
                            "recharge cycle and attempt restarting the robot."},
                {"content": "PROBLEM: BRUSH DOES NOT ROTATE; SOLUTION: Verify the deck is mounted."},
            ],
        )
        response = await retrieve(
            RetrieveRequest(query="robot will not power on, battery flat"), auth_for(tenant_id), db
        )
        assert response.snippets

    async def test_french_content_is_searchable(self, db):
        tenant_id = await seed(
            db,
            [{
                "content": "La pente est trop raide - éloignez le robot de la pente et réessayez",
                "lang": "fr",
            }],
        )
        response = await retrieve(RetrieveRequest(query="pente trop raide"), auth_for(tenant_id), db)
        assert response.snippets
        assert "pente" in response.snippets[0].content

    async def test_deprecated_mode_is_accepted_and_ignored(self, db):
        tenant_id = await seed(db, [{"content": "CODE: AF-01-3021-6-1; Slope is too steep"}])

        with_mode = await retrieve(
            RetrieveRequest(query="AF-01-3021-6-1", mode="keyword"), auth_for(tenant_id), db
        )
        without_mode = await retrieve(
            RetrieveRequest(query="AF-01-3021-6-1"), auth_for(tenant_id), db
        )
        assert [s.snippet_id for s in with_mode.snippets] == [
            s.snippet_id for s in without_mode.snippets
        ]

    async def test_tenant_isolation_holds(self, db):
        mine = await seed(db, [{"content": "CODE: AF-01-3021-6-1; Slope is too steep"}])
        theirs = await seed(db, [{"content": "CODE: AF-01-3021-6-1; Slope is too steep"}])

        response = await retrieve(RetrieveRequest(query="AF-01-3021-6-1"), auth_for(mine), db)
        assert len(response.snippets) == 1
        other = await retrieve(RetrieveRequest(query="AF-01-3021-6-1"), auth_for(theirs), db)
        assert other.snippets[0].snippet_id != response.snippets[0].snippet_id


class TestFusion:
    def test_exact_leg_outranks_a_document_matching_no_substring(self):
        exact = retrieve_module.Candidate("a", "x", 1, None, None, None, False, "f.pdf")
        other = retrieve_module.Candidate("b", "y", 1, None, None, None, False, "f.pdf")

        fused = reciprocal_rank_fusion({"exact": [exact], "fts": [other], "vector": [other]})
        assert fused[0][0].id == "a"

    def test_a_document_found_by_every_leg_wins(self):
        everywhere = retrieve_module.Candidate("a", "x", 1, None, None, None, False, "f.pdf")
        one_leg = retrieve_module.Candidate("b", "y", 1, None, None, None, False, "f.pdf")

        fused = reciprocal_rank_fusion(
            {"exact": [one_leg, everywhere], "fts": [everywhere], "vector": [everywhere]}
        )
        assert fused[0][0].id == "a"
