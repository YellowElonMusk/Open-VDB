"""Deduplication provenance and review flag.

Revision ID: 0003_dedup_provenance
Revises: 0002_chunk_structure
Create Date: 2026-08-27

A surviving chunk records every source it was found in, and whether its
near-duplicate group disagreed on facts (different fault codes, different
rated values across revisions) and therefore needs a human look.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_dedup_provenance"
down_revision = "0002_chunk_structure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("provenance", postgresql.JSONB(), nullable=True))
    op.add_column(
        "chunks",
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_chunks_needs_review", "chunks", ["needs_review"])


def downgrade() -> None:
    op.drop_index("ix_chunks_needs_review", table_name="chunks")
    op.drop_column("chunks", "needs_review")
    op.drop_column("chunks", "provenance")
