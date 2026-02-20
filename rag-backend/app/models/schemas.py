"""Pydantic schemas for API request/response validation"""

from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, validator
from enum import Enum


# Enums
class OEMStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class QueryStatus(str, Enum):
    CORRECT = "correct"
    NEEDS_ADJUSTMENT = "needs_adjustment"
    INCORRECT = "incorrect"
    UNCLEAR = "unclear"


# OEM Schemas
class OEMCreate(BaseModel):
    """Request to create a new OEM"""
    name: str = Field(..., min_length=3, max_length=255, description="Unique OEM identifier")
    display_name: str = Field(..., min_length=3, max_length=255)
    description: Optional[str] = None
    contact_email: str = Field(..., pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
    contact_name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = {}


class OEMUpdate(BaseModel):
    """Request to update OEM details"""
    display_name: Optional[str] = None
    description: Optional[str] = None
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    status: Optional[OEMStatus] = None
    metadata: Optional[Dict[str, Any]] = None


class OEMResponse(BaseModel):
    """OEM details response"""
    id: str
    name: str
    display_name: str
    description: Optional[str]
    collection_name: str
    contact_email: str
    contact_name: Optional[str]
    status: OEMStatus
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OEMWithApiKey(OEMResponse):
    """OEM response with API key (only returned on creation)"""
    api_key: str = Field(..., description="Store this securely - it won't be shown again")


# Document Schemas
class DocumentUploadMetadata(BaseModel):
    """Metadata for document upload"""
    title: Optional[str] = None
    equipment_model: Optional[str] = Field(None, max_length=255)
    document_type: Optional[str] = Field(None, max_length=100)
    tags: Optional[List[str]] = []
    custom_metadata: Optional[Dict[str, Any]] = {}


class DocumentResponse(BaseModel):
    """Document details response"""
    id: str
    oem_id: str
    filename: str
    original_filename: str
    file_type: str
    file_size_bytes: int
    status: DocumentStatus
    title: Optional[str]
    equipment_model: Optional[str]
    document_type: Optional[str]
    tags: List[str]
    total_chunks: int
    total_tokens: int
    uploaded_at: datetime
    processing_completed_at: Optional[datetime]
    processing_error: Optional[str]

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """Paginated list of documents"""
    documents: List[DocumentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# RAG Query Schemas
class SourceDocument(BaseModel):
    """Source document citation"""
    document_id: str
    document_title: str
    chunk_index: int
    page_number: Optional[int]
    section_title: Optional[str]
    content_snippet: str
    relevance_score: float = Field(..., ge=0.0, le=1.0)


class RAGQueryRequest(BaseModel):
    """Request for RAG query"""
    question: str = Field(..., min_length=5, max_length=2000)
    equipment_model: Optional[str] = None
    include_sources: bool = True
    max_sources: int = Field(5, ge=1, le=20)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(500, ge=50, le=2000)

    # Optional: include image for vision-based queries
    image_base64: Optional[str] = None
    image_context: Optional[str] = None


class RAGQueryResponse(BaseModel):
    """Response from RAG query"""
    answer: str
    sources: List[SourceDocument]
    confidence: float = Field(..., ge=0.0, le=1.0)
    query_id: str
    processing_time_ms: int

    # For vision-based queries
    status: Optional[QueryStatus] = None
    voice_instruction: Optional[str] = None
    reasoning: Optional[str] = None


# Chunk Schemas
class ChunkResponse(BaseModel):
    """Document chunk details"""
    id: str
    document_id: str
    chunk_index: int
    content: str
    page_number: Optional[int]
    section_title: Optional[str]
    token_count: int

    class Config:
        from_attributes = True


# Audit Log Schemas
class AuditLogResponse(BaseModel):
    """Audit log entry"""
    id: str
    oem_id: Optional[str]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    user_id: Optional[str]
    ip_address: Optional[str]
    details: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    """Paginated audit logs"""
    logs: List[AuditLogResponse]
    total: int
    page: int
    page_size: int


# Export Schema
class ExportRequest(BaseModel):
    """Request to export OEM knowledge base"""
    include_documents: bool = True
    include_metadata: bool = True
    encryption_password: Optional[str] = None


class ExportResponse(BaseModel):
    """Export job response"""
    export_id: str
    status: str
    download_url: Optional[str]
    created_at: datetime
    expires_at: datetime


# Statistics Schemas
class OEMStatistics(BaseModel):
    """OEM knowledge base statistics"""
    oem_id: str
    total_documents: int
    total_chunks: int
    total_tokens: int
    total_queries: int
    storage_bytes: int
    last_query_at: Optional[datetime]
    created_at: datetime


# Authentication Schemas
class Token(BaseModel):
    """JWT token response"""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Token payload data"""
    oem_id: str
    oem_name: str
    scopes: List[str] = []


# Health Check Schema
class HealthCheck(BaseModel):
    """Health check response"""
    status: str
    version: str
    timestamp: datetime
    services: Dict[str, str]


# Error Schemas
class ErrorResponse(BaseModel):
    """Standard error response"""
    error: str
    detail: Optional[str] = None
    error_code: Optional[str] = None


class ValidationErrorDetail(BaseModel):
    """Validation error detail"""
    loc: List[str]
    msg: str
    type: str


class ValidationErrorResponse(BaseModel):
    """Validation error response"""
    error: str = "Validation Error"
    details: List[ValidationErrorDetail]
