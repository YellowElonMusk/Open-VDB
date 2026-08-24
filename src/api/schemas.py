"""Pydantic schemas for API request/response models."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# --- Tenant ---

class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9\-]+$")


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    admin_api_key: str | None = None  # only returned on creation

    model_config = {"from_attributes": True}


# --- API Keys ---

class ApiKeyCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=255, description="Human-readable label (e.g. 'CRM Bot Key')")
    scope: str = Field(..., pattern=r"^(admin|retrieval)$", description="'admin' for full access, 'retrieval' for read-only search")


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    label: str
    scope: str
    created_at: datetime
    api_key: str | None = None  # only returned on creation

    model_config = {"from_attributes": True}


# --- Tenant Dashboard (for web UI connect flow) ---

class TenantDashboard(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    scope: str
    document_count: int = 0
    total_chunks: int = 0


# --- Documents ---

class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    file_type: str
    file_size_bytes: int
    status: str
    output_formats: list[str] = Field(
        default=["vector"],
        description="Outputs generated for this document: vector, markdown, sqlite",
    )
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("output_formats", mode="before")
    @classmethod
    def _split_formats(cls, v):
        # Stored as a comma-separated string on the Document model
        if isinstance(v, str):
            return [f for f in v.split(",") if f]
        return v


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


# --- Retrieval (for AI SaaS tools) ---

class RetrieveRequest(BaseModel):
    """What AI SaaS tools send to get relevant information."""
    query: str = Field(..., min_length=1, description="Natural language question or search query")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of relevant snippets to return")
    mode: str = Field(
        default="semantic",
        pattern=r"^(semantic|keyword)$",
        description=(
            "'semantic' uses vector similarity (documents uploaded with the vector output). "
            "'keyword' does exact text matching — ideal for error codes and part numbers, "
            "works for every document and needs no embeddings API"
        ),
    )


class RetrievedSnippet(BaseModel):
    """A single relevant snippet — NOT the full document, just the piece the AI tool needs."""
    snippet_id: uuid.UUID
    content: str
    source_filename: str
    relevance_score: float


class RetrieveResponse(BaseModel):
    """What the AI SaaS tool gets back: only the snippets it needs, nothing more."""
    snippets: list[RetrievedSnippet]
    query: str
