"""Pydantic schemas for API request and response models."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9\-]+$")


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    admin_api_key: str | None = None

    model_config = {"from_attributes": True}


class ApiKeyCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=255)
    scope: str = Field(..., pattern=r"^(admin|retrieval)$")


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    label: str
    scope: str
    created_at: datetime
    api_key: str | None = None

    model_config = {"from_attributes": True}


class TenantDashboard(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    scope: str
    document_count: int = 0
    total_chunks: int = 0


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    file_type: str
    file_size_bytes: int
    status: str
    chunk_count: int
    error_message: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)


class RetrievedSnippet(BaseModel):
    snippet_id: uuid.UUID
    content: str
    source_filename: str
    relevance_score: float


class RetrieveResponse(BaseModel):
    snippets: list[RetrievedSnippet]
    query: str
