"""Hybrid search: bilingual FTS, trigram matching, HNSW vectors.

Revision ID: 0004_hybrid_search
Revises: 0003_dedup_provenance
Create Date: 2026-08-27

Three changes, one goal — a caller should never have to pick a search
algorithm:

* A per-chunk `lang` drives a generated tsvector, so French and English
  content are each stemmed by their own configuration instead of sharing
  one that stems both badly.
* pg_trgm indexes `content` for substring matching, which is how a fault
  code like AF-01-3021-6-1 is found regardless of tokenisation.
* The vector index becomes HNSW. ivfflat partitions the vector space using
  centroids computed at build time; built on an empty table — as it was,
  since the schema is created before any data is loaded — those centroids
  are meaningless and recall is near random. HNSW has no such requirement.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_hybrid_search"
down_revision = "0003_dedup_provenance"
branch_labels = None
depends_on = None

# to_tsvector() must be IMMUTABLE to be used in a generated column, which
# rules out casting the lang column to regconfig at runtime. Branching on
# literal regconfigs keeps the expression immutable.
TSVECTOR_EXPRESSION = (
    "to_tsvector("
    "CASE lang WHEN 'fr' THEN 'french'::regconfig ELSE 'english'::regconfig END, "
    "content)"
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.add_column(
        "chunks",
        sa.Column("lang", sa.String(10), nullable=False, server_default="en"),
    )

    op.execute(
        f"ALTER TABLE chunks ADD COLUMN content_tsv tsvector "
        f"GENERATED ALWAYS AS ({TSVECTOR_EXPRESSION}) STORED"
    )
    op.execute("CREATE INDEX ix_chunks_content_tsv ON chunks USING GIN (content_tsv)")
    op.execute("CREATE INDEX ix_chunks_content_trgm ON chunks USING GIN (content gin_trgm_ops)")

    # Replace the ivfflat index with HNSW.
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding")
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_chunks_content_trgm")
    op.execute("DROP INDEX IF EXISTS ix_chunks_content_tsv")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS content_tsv")
    op.drop_column("chunks", "lang")
    op.execute(
        "CREATE INDEX ix_chunks_embedding ON chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
