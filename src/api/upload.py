"""Document upload endpoints."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import DocumentListResponse, DocumentResponse
from src.core.auth import AuthResult, authenticate
from src.core.config import settings
from src.db.session import get_db
from src.ingestion.parser import SUPPORTED_EXTENSIONS
from src.ingestion.pipeline import process_upload
from src.models.database import Document

router = APIRouter(prefix="/documents", tags=["documents"])


def _validate_filename(filename: str | None) -> str:
    safe_name = Path(filename or "").name
    extension = Path(safe_name).suffix.lower()
    if not safe_name or extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Supported: {supported}")
    return safe_name


async def _read_validated(file: UploadFile) -> tuple[str, bytes]:
    filename = _validate_filename(file.filename)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail=f"{filename} is empty")
    maximum = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > maximum:
        raise HTTPException(
            status_code=413,
            detail=f"{filename} exceeds the {settings.max_upload_size_mb} MB limit",
        )
    return filename, content


async def _process(
    db: AsyncSession,
    auth: AuthResult,
    filename: str,
    content: bytes,
) -> Document:
    document = Document(
        tenant_id=auth.tenant.id,
        filename=filename,
        file_type=Path(filename).suffix.lower().lstrip("."),
        file_size_bytes=len(content),
        status="processing",
    )
    db.add(document)
    await db.flush()
    return await process_upload(db, document, content)


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    auth.require_admin()
    filename, content = await _read_validated(file)
    return DocumentResponse.model_validate(await _process(db, auth, filename, content))


@router.post("/upload/batch", response_model=list[DocumentResponse], status_code=status.HTTP_201_CREATED)
async def upload_documents_batch(
    files: list[UploadFile] = File(...),
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Upload a validated batch. Invalid files are reported instead of silently skipped."""
    auth.require_admin()
    if not files:
        raise HTTPException(status_code=400, detail="Select at least one file")
    if len(files) > settings.max_batch_files:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {settings.max_batch_files} files per batch",
        )

    validated = [await _read_validated(file) for file in files]
    results = []
    for filename, content in validated:
        document = await _process(db, auth, filename, content)
        results.append(DocumentResponse.model_validate(document))
    return results


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document)
        .where(Document.tenant_id == auth.tenant.id)
        .order_by(Document.created_at.desc())
    )
    documents = [DocumentResponse.model_validate(item) for item in result.scalars().all()]
    return DocumentListResponse(documents=documents, total=len(documents))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    auth.require_admin()
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == auth.tenant.id,
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(document)
    await db.commit()
