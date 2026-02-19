"""File upload endpoint — the main OEM workflow.

Upload a PDF, DOCX, TXT, CSV, or Markdown file.
The platform automatically parses, chunks, embeds, and stores it.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import DocumentListResponse, DocumentResponse
from src.core.auth import AuthResult, authenticate
from src.core.config import settings
from src.core.rate_limit import check_rate_limit
from src.db.session import get_db
from src.ingestion.parser import SUPPORTED_EXTENSIONS
from src.ingestion.pipeline import process_upload
from src.models.database import Document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(..., description="Manual, guide, or SOP document"),
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
    x_api_key: str = Header(...),
):
    """Upload a document. It's automatically processed into a searchable vector database.

    Supported formats: PDF, DOCX, TXT, CSV, Markdown.
    Rate limited: 20 uploads/minute per API key.
    """
    auth.require_admin()
    await check_rate_limit(x_api_key, action="upload", limit=20)

    # Validate file type
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    # Read file content
    content = await file.read()
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.max_upload_size_mb} MB",
        )

    # Create document record
    document = Document(
        tenant_id=auth.tenant.id,
        filename=file.filename or "unknown",
        file_type=ext.lstrip("."),
        file_size_bytes=len(content),
        status="processing",
    )
    db.add(document)
    await db.flush()

    # Process: parse → chunk → embed → store
    document = await process_upload(db, document, content)

    return DocumentResponse.model_validate(document)


@router.post("/upload/batch", response_model=list[DocumentResponse], status_code=status.HTTP_201_CREATED)
async def upload_documents_batch(
    files: list[UploadFile] = File(..., description="Multiple documents to upload at once"),
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Upload multiple documents at once. Each is processed independently."""
    auth.require_admin()

    results = []
    for file in files:
        ext = Path(file.filename or "").suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue

        content = await file.read()
        if len(content) > settings.max_upload_size_mb * 1024 * 1024:
            continue

        document = Document(
            tenant_id=auth.tenant.id,
            filename=file.filename or "unknown",
            file_type=ext.lstrip("."),
            file_size_bytes=len(content),
            status="processing",
        )
        db.add(document)
        await db.flush()

        document = await process_upload(db, document, content)
        results.append(DocumentResponse.model_validate(document))

    return results


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """List all uploaded documents for this tenant."""
    result = await db.execute(
        select(Document)
        .where(Document.tenant_id == auth.tenant.id)
        .order_by(Document.created_at.desc())
    )
    docs = [DocumentResponse.model_validate(d) for d in result.scalars().all()]
    return DocumentListResponse(documents=docs, total=len(docs))


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Get the status and metadata of a single document."""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == auth.tenant.id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse.model_validate(doc)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document and all its chunks (admin only)."""
    auth.require_admin()
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == auth.tenant.id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(doc)
    await db.commit()
