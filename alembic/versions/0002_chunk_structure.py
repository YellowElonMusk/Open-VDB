"""Structure metadata on chunks.

Revision ID: 0002_chunk_structure
Revises: 0001_baseline
Create Date: 2026-08-27

Chunks now carry where they came from — manual, revision, page, section,
and whether the text is prose or a table row — so a retrieved snippet can
be cited rather than merely quoted.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_chunk_structure"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("page", sa.Integer(), nullable=True))
    op.add_column("chunks", sa.Column("section", sa.String(500), nullable=True))
    op.add_column("chunks", sa.Column("kind", sa.String(20), nullable=True))
    op.add_column("chunks", sa.Column("source_doc", sa.String(500), nullable=True))
    op.add_column("chunks", sa.Column("revision", sa.String(100), nullable=True))
    op.create_index("ix_chunks_source_doc", "chunks", ["source_doc"])


def downgrade() -> None:
    op.drop_index("ix_chunks_source_doc", table_name="chunks")
    for column in ("revision", "source_doc", "kind", "section", "page"):
        op.drop_column("chunks", column)
