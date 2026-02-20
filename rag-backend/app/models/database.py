"""SQLAlchemy database models for metadata and audit logging"""

from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, DateTime, Boolean, Text,
    JSON, ForeignKey, Index, Enum as SQLEnum
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()


class OEMStatus(str, enum.Enum):
    """OEM account status"""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class DocumentStatus(str, enum.Enum):
    """Document processing status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AuditAction(str, enum.Enum):
    """Audit log action types"""
    OEM_CREATED = "oem_created"
    OEM_UPDATED = "oem_updated"
    OEM_DELETED = "oem_deleted"
    DOCUMENT_UPLOADED = "document_uploaded"
    DOCUMENT_DELETED = "document_deleted"
    QUERY_EXECUTED = "query_executed"
    COLLECTION_CREATED = "collection_created"
    COLLECTION_DELETED = "collection_deleted"
    EXPORT_REQUESTED = "export_requested"
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILED = "auth_failed"


class OEM(Base):
    """OEM (Original Equipment Manufacturer) entity - multi-tenant isolation"""
    __tablename__ = "oems"

    id = Column(String(36), primary_key=True)  # UUID
    name = Column(String(255), nullable=False, unique=True, index=True)
    display_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Vector DB collection name (isolated namespace)
    collection_name = Column(String(255), nullable=False, unique=True, index=True)

    # Contact information
    contact_email = Column(String(255), nullable=False)
    contact_name = Column(String(255), nullable=True)

    # Status and access control
    status = Column(SQLEnum(OEMStatus), default=OEMStatus.ACTIVE, nullable=False, index=True)
    api_key_hash = Column(String(255), nullable=False)  # Hashed API key for authentication

    # Encryption key for this OEM's data (encrypted at rest)
    data_encryption_key = Column(Text, nullable=False)  # Encrypted with master key

    # Metadata
    metadata = Column(JSON, nullable=True, default={})

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True)  # Soft delete

    # Relationships
    documents = relationship("Document", back_populates="oem", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="oem", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_oem_status_created", "status", "created_at"),
    )


class Document(Base):
    """Document metadata - actual content stored in vector DB"""
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True)  # UUID
    oem_id = Column(String(36), ForeignKey("oems.id"), nullable=False, index=True)

    # Document information
    filename = Column(String(512), nullable=False)
    original_filename = Column(String(512), nullable=False)
    file_type = Column(String(50), nullable=False)  # pdf, txt, docx, md
    file_size_bytes = Column(Integer, nullable=False)
    file_hash = Column(String(64), nullable=False)  # SHA-256 hash

    # Storage location
    storage_path = Column(Text, nullable=False)  # Local path or S3 URL

    # Processing status
    status = Column(SQLEnum(DocumentStatus), default=DocumentStatus.PENDING, nullable=False, index=True)
    processing_started_at = Column(DateTime, nullable=True)
    processing_completed_at = Column(DateTime, nullable=True)
    processing_error = Column(Text, nullable=True)

    # Document metadata
    title = Column(String(512), nullable=True)
    equipment_model = Column(String(255), nullable=True, index=True)  # LionsBot_R3, etc.
    document_type = Column(String(100), nullable=True)  # manual, troubleshooting, sop, etc.
    tags = Column(JSON, nullable=True, default=[])  # List of tags
    custom_metadata = Column(JSON, nullable=True, default={})

    # Chunking statistics
    total_chunks = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)

    # Timestamps
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True)  # Soft delete

    # Relationships
    oem = relationship("OEM", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_document_oem_status", "oem_id", "status"),
        Index("idx_document_equipment", "equipment_model", "deleted_at"),
    )


class DocumentChunk(Base):
    """Document chunk metadata - vectors stored in Milvus"""
    __tablename__ = "document_chunks"

    id = Column(String(36), primary_key=True)  # UUID, also used in Milvus
    document_id = Column(String(36), ForeignKey("documents.id"), nullable=False, index=True)

    # Chunk information
    chunk_index = Column(Integer, nullable=False)  # Position in document
    content = Column(Text, nullable=False)  # The actual text chunk
    content_hash = Column(String(64), nullable=False)  # SHA-256 hash

    # Source location
    page_number = Column(Integer, nullable=True)  # For PDFs
    section_title = Column(String(512), nullable=True)

    # Token count
    token_count = Column(Integer, nullable=False)

    # Vector ID in Milvus
    vector_id = Column(String(36), nullable=True, unique=True)

    # Metadata
    metadata = Column(JSON, nullable=True, default={})

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("idx_chunk_document_index", "document_id", "chunk_index"),
    )


class AuditLog(Base):
    """Audit log for all operations - compliance and security"""
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True)  # UUID
    oem_id = Column(String(36), ForeignKey("oems.id"), nullable=True, index=True)

    # Action information
    action = Column(SQLEnum(AuditAction), nullable=False, index=True)
    resource_type = Column(String(100), nullable=True)  # oem, document, query, etc.
    resource_id = Column(String(36), nullable=True)

    # User/API information
    user_id = Column(String(36), nullable=True)  # If user-initiated
    api_key_prefix = Column(String(20), nullable=True)  # First few chars of API key
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(Text, nullable=True)

    # Request details
    request_method = Column(String(10), nullable=True)  # GET, POST, etc.
    request_path = Column(String(512), nullable=True)
    request_params = Column(JSON, nullable=True, default={})

    # Response details
    response_status = Column(Integer, nullable=True)
    response_time_ms = Column(Integer, nullable=True)

    # Additional context
    details = Column(JSON, nullable=True, default={})
    error_message = Column(Text, nullable=True)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    oem = relationship("OEM", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_oem_action_time", "oem_id", "action", "created_at"),
        Index("idx_audit_created", "created_at"),
    )


class QueryCache(Base):
    """Cache for RAG query results to improve performance"""
    __tablename__ = "query_cache"

    id = Column(String(36), primary_key=True)  # UUID
    oem_id = Column(String(36), nullable=False, index=True)

    # Query hash (for cache key)
    query_hash = Column(String(64), nullable=False, unique=True, index=True)
    query_text = Column(Text, nullable=False)

    # Cached response
    response = Column(JSON, nullable=False)

    # Cache metadata
    hit_count = Column(Integer, default=0, nullable=False)
    last_accessed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)  # TTL

    __table_args__ = (
        Index("idx_cache_expires", "expires_at"),
        Index("idx_cache_oem_hash", "oem_id", "query_hash"),
    )
