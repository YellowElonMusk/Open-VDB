"""Pydantic schemas for API request/response models."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


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
    api_key: str | None = None  # only returned on creation

    model_config = {"from_attributes": True}


# --- Collection ---

class CollectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class CollectionResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Document / Ingestion ---

class IngestTextRequest(BaseModel):
    """Ingest raw text into a collection."""
    collection_id: uuid.UUID
    source: str = Field(..., max_length=500, description="Identifier for the source (filename, URL, etc.)")
    content: str = Field(..., min_length=1)
    metadata: dict | None = None


class DocumentResponse(BaseModel):
    id: uuid.UUID
    source: str
    collection_id: uuid.UUID
    chunk_count: int
    created_at: datetime


# --- Query ---

class QueryRequest(BaseModel):
    collection_id: uuid.UUID
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)


class QueryResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    source: str
    content: str
    score: float


class QueryResponse(BaseModel):
    results: list[QueryResult]


# --- Connector ---

class ConnectorSyncRequest(BaseModel):
    connector_type: str  # e.g. "salesforce", "hubspot", "zendesk"
    collection_id: uuid.UUID
    credentials: dict  # connector-specific auth
    config: dict | None = None  # connector-specific options
