"""Document management API endpoints"""

import uuid
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import structlog
import json

from app.database import get_db
from app.models.database import OEM, Document, DocumentChunk, DocumentStatus, AuditAction
from app.models.schemas import (
    DocumentResponse, DocumentListResponse, DocumentUploadMetadata, ChunkResponse
)
from app.dependencies import get_current_oem, get_client_ip
from app.services.document_processor import document_processor
from app.services.embeddings import embeddings_service
from app.services.vector_db import vector_db
from app.services.security import security_service, audit_logger
from app.config import settings

router = APIRouter(prefix="/documents", tags=["Document Management"])
logger = structlog.get_logger(__name__)


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    metadata: Optional[str] = Form(None),
    current_oem: OEM = Depends(get_current_oem),
    db: AsyncSession = Depends(get_db),
    ip_address: str = Depends(get_client_ip)
):
    """
    Upload a document for processing and ingestion into knowledge base

    Supports: PDF, TXT, DOCX, MD files
    """
    try:
        # Validate file type
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in settings.allowed_extensions_list:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type {file_ext} not allowed. Allowed: {', '.join(settings.allowed_extensions_list)}"
            )

        # Parse metadata
        doc_metadata = {}
        if metadata:
            try:
                doc_metadata = json.loads(metadata)
                DocumentUploadMetadata(**doc_metadata)  # Validate
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid metadata: {str(e)}"
                )

        # Read file
        file_content = await file.read()
        file_size = len(file_content)

        # Check file size
        if file_size > settings.max_upload_size_mb * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size exceeds {settings.max_upload_size_mb}MB limit"
            )

        # Generate document ID
        doc_id = str(uuid.uuid4())

        # Save file to disk
        upload_dir = Path(settings.upload_dir) / current_oem.id
        upload_dir.mkdir(parents=True, exist_ok=True)

        safe_filename = security_service.sanitize_filename(file.filename)
        file_path = upload_dir / f"{doc_id}_{safe_filename}"

        with open(file_path, "wb") as f:
            f.write(file_content)

        # Calculate file hash
        file_hash = security_service.hash_file(str(file_path))

        # Create document record
        document = Document(
            id=doc_id,
            oem_id=current_oem.id,
            filename=safe_filename,
            original_filename=file.filename,
            file_type=file_ext,
            file_size_bytes=file_size,
            file_hash=file_hash,
            storage_path=str(file_path),
            status=DocumentStatus.PENDING,
            title=doc_metadata.get("title"),
            equipment_model=doc_metadata.get("equipment_model"),
            document_type=doc_metadata.get("document_type"),
            tags=doc_metadata.get("tags", []),
            custom_metadata=doc_metadata.get("custom_metadata", {})
        )

        db.add(document)
        await db.commit()
        await db.refresh(document)

        # Audit log
        await audit_logger.log_action(
            action=AuditAction.DOCUMENT_UPLOADED.value,
            oem_id=current_oem.id,
            resource_type="document",
            resource_id=doc_id,
            ip_address=ip_address,
            details={
                "filename": file.filename,
                "size_bytes": file_size,
                "file_type": file_ext
            }
        )

        logger.info(
            "Document uploaded",
            oem_id=current_oem.id,
            document_id=doc_id,
            filename=file.filename
        )

        # Process document synchronously for MVP
        await process_document_task(doc_id, current_oem.id, db)

        # Refresh to get updated status
        await db.refresh(document)

        return DocumentResponse.from_orm(document)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Document upload failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload document"
        )


async def process_document_task(document_id: str, oem_id: str, db: AsyncSession):
    """Background task to process document"""
    try:
        # Get document
        result = await db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one()

        # Get OEM
        result = await db.execute(
            select(OEM).where(OEM.id == oem_id)
        )
        oem = result.scalar_one()

        # Update status
        document.status = DocumentStatus.PROCESSING
        document.processing_started_at = datetime.utcnow()
        await db.commit()

        # Extract text
        text, extraction_metadata = await document_processor.extract_text(
            document.storage_path,
            document.file_type
        )

        # Auto-extract metadata if not provided
        if not document.title:
            auto_metadata = await document_processor.extract_metadata_from_content(text)
            document.title = auto_metadata.get("auto_title")

        # Chunk text
        chunks = document_processor.chunk_text(text, extraction_metadata)

        # Prepare document metadata
        doc_metadata = {
            "title": document.title or document.filename,
            "equipment_model": document.equipment_model or "",
            "document_type": document.document_type
        }

        # Process chunks (generate embeddings)
        processed_chunks = await document_processor.process_chunks(
            chunks,
            document_id,
            doc_metadata
        )

        # Insert into vector database
        await vector_db.insert_chunks(oem.collection_name, processed_chunks)

        # Save chunk metadata to database
        for chunk in processed_chunks:
            db_chunk = DocumentChunk(
                id=chunk["id"],
                document_id=document_id,
                chunk_index=chunk["chunk_index"],
                content=chunk["content"],
                content_hash=chunk["content_hash"],
                page_number=chunk.get("page_number"),
                section_title=chunk.get("section_title"),
                token_count=chunk["token_count"],
                vector_id=chunk["id"]
            )
            db.add(db_chunk)

        # Update document status
        document.status = DocumentStatus.COMPLETED
        document.processing_completed_at = datetime.utcnow()
        document.total_chunks = len(processed_chunks)
        document.total_tokens = sum(c["token_count"] for c in processed_chunks)

        await db.commit()

        logger.info(
            "Document processed",
            document_id=document_id,
            chunks=len(processed_chunks)
        )

    except Exception as e:
        logger.error("Document processing failed", document_id=document_id, error=str(e))

        # Update status to failed
        document.status = DocumentStatus.FAILED
        document.processing_error = str(e)
        await db.commit()


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    page: int = 1,
    page_size: int = 20,
    equipment_model: Optional[str] = None,
    current_oem: OEM = Depends(get_current_oem),
    db: AsyncSession = Depends(get_db)
):
    """List all documents for current OEM"""
    try:
        # Build query
        query = select(Document).where(
            Document.oem_id == current_oem.id,
            Document.deleted_at.is_(None)
        )

        if equipment_model:
            query = query.where(Document.equipment_model == equipment_model)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        result = await db.execute(count_query)
        total = result.scalar()

        # Paginate
        query = query.order_by(Document.uploaded_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await db.execute(query)
        documents = result.scalars().all()

        return DocumentListResponse(
            documents=[DocumentResponse.from_orm(doc) for doc in documents],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size
        )

    except Exception as e:
        logger.error("Failed to list documents", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve documents"
        )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    current_oem: OEM = Depends(get_current_oem),
    db: AsyncSession = Depends(get_db)
):
    """Get document details"""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.oem_id == current_oem.id,
            Document.deleted_at.is_(None)
        )
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    return DocumentResponse.from_orm(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    current_oem: OEM = Depends(get_current_oem),
    db: AsyncSession = Depends(get_db),
    ip_address: str = Depends(get_client_ip)
):
    """Delete a document (soft delete)"""
    try:
        result = await db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.oem_id == current_oem.id,
                Document.deleted_at.is_(None)
            )
        )
        document = result.scalar_one_or_none()

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        # Soft delete
        document.deleted_at = datetime.utcnow()
        await db.commit()

        # Delete from vector database
        await vector_db.delete_document_chunks(current_oem.collection_name, document_id)

        # Audit log
        await audit_logger.log_action(
            action=AuditAction.DOCUMENT_DELETED.value,
            oem_id=current_oem.id,
            resource_type="document",
            resource_id=document_id,
            ip_address=ip_address
        )

        logger.info("Document deleted", document_id=document_id)

        return None

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete document", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete document"
        )
