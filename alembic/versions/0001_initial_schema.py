"""Initial schema: tenants, api_keys, documents, chunks with pgvector.

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(20), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="processing"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # vector column — alembic doesn't natively know the type so we use raw SQL
        sa.Column("embedding", sa.Text(), nullable=False),  # placeholder; real DDL below
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Replace the placeholder TEXT column with the real vector type
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)")

    # IVFFlat index for fast cosine similarity search
    op.execute(
        "CREATE INDEX ix_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("api_keys")
    op.drop_table("tenants")
    op.execute("DROP EXTENSION IF EXISTS vector")
