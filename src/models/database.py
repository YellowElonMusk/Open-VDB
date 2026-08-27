"""SQLAlchemy models for tenant isolation and document management."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.core.config import settings


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    """Each OEM gets one tenant. All data is scoped to a tenant."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class ApiKey(Base):
    """API keys with scoped permissions.

    - 'admin' keys: OEM uses to upload/manage docs.
    - 'retrieval' keys: handed to AI SaaS tools, can only query — never see full docs.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)  # "admin" or "retrieval"
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="api_keys")


class Document(Base):
    """An uploaded file (manual, guide, SOP) processed into chunks."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)  # pdf, docx, txt, csv, md
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")  # processing, ready, failed
    # Comma-separated output formats chosen at upload: vector, markdown, sqlite
    output_formats: Mapped[str] = mapped_column(String(100), nullable=False, default="vector")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    """A chunk of text from a document.

    The embedding is present only when the document was uploaded with the
    'vector' output format — markdown/sqlite-only documents store plain text
    chunks (still searchable via keyword mode) without calling any
    embeddings API.
    """

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dimensions), nullable=True
    )

    # Structure carried from the parsed document so a retrieved snippet can
    # be cited: which manual, which revision, which page, which section.
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(500))
    kind: Mapped[str | None] = mapped_column(String(20))  # heading, prose, table
    source_doc: Mapped[str | None] = mapped_column(String(500))
    revision: Mapped[str | None] = mapped_column(String(100))

    # Deduplication results: where this text was found, and whether members
    # of its near-duplicate group disagreed on facts.
    provenance: Mapped[list | None] = mapped_column(JSONB)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Language of the chunk, selecting the Postgres text search config.
    lang: Mapped[str] = mapped_column(String(10), nullable=False, default="en")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="chunks")

    # Indexes are created by Alembic migrations, not by metadata reflection:
    # the HNSW vector index, the generated tsvector column with its GIN
    # index, and the trigram index all need raw DDL.
    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_source_doc", "source_doc"),
    )


class Artifact(Base):
    """A generated export of a document, stored for download.

    Formats:
    - 'markdown': the parsed document as a clean .md file
    - 'sqlite':   a standalone SQLite database file with the document's
                  chunks and a full-text search index (FTS5)
    """

    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    format: Mapped[str] = mapped_column(String(20), nullable=False)  # markdown, sqlite
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="artifacts")
