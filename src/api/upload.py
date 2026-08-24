"""File upload endpoint — the main OEM workflow.

Upload a PDF, DOCX, TXT, CSV, or Markdown file and choose what to build
from it:

- vector   (default): embedded into pgvector for semantic search
- markdown:           a clean .md export any AI agent can read directly
- sqlite:             a standalone SQLite .db export with keyword search

Only the vector output calls the OpenAI embeddings API — markdown and
sqlite are generated fully offline, no API key needed.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import DocumentListResponse, DocumentResponse
from src.core.auth import AuthResult, authenticate
from src.core.config import settings
from src.db.session import get_db
from src.ingestion.exporters import FORMAT_VECTOR, parse_output_formats
from src.ingestion.parser import SUPPORTED_EXTENSIONS
from src.ingestion.pipeline import process_upload
from src.models.database import Document

router = APIRouter(prefix="/documents", tags=["documents"])

OUTPUTS_FIELD_DESCRIPTION = (
    "Comma-separated outputs to generate: 'vector' (semantic search, needs OpenAI key), "
    "'markdown' (downloadable .md file), 'sqlite' (downloadable SQLite .db file). "
    "Example: 'markdown,sqlite'. Default: 'vector'."
)


def _validate_outputs(outputs: str) -> list[str]:
    """Parse the outputs form field, enforcing that vector needs an API key."""
    try:
        formats = parse_output_formats(outputs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if FORMAT_VECTOR in formats and not settings.openai_api_key:
        raise HTTPException(
            status_code=400,
            detail=(
                "The 'vector' output requires an OpenAI API key. "
                "Set VDB_OPENAI_API_KEY in your .env, or choose "
                "outputs=markdown and/or sqlite — those work fully offline."
            ),
        )
    return formats


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(..., description="Manual, guide, or SOP document"),
    outputs: str = Form("vector", description=OUTPUTS_FIELD_DESCRIPTION),
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Upload a document and choose which outputs to generate.

    Supported file formats: PDF, DOCX, TXT, CSV, Markdown.
    Outputs: 'vector' (semantic search), 'markdown' (.md export),
    'sqlite' (SQLite .db export) — any combination, e.g. outputs=markdown,sqlite.
    """
    auth.require_admin()
    formats = _validate_outputs(outputs)

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
        output_formats=",".join(formats),
    )
    db.add(document)
    await db.flush()

    # Process: parse → chunk → build the chosen outputs
    document = await process_upload(db, document, content, formats)

    return DocumentResponse.model_validate(document)


@router.post("/upload/batch", response_model=list[DocumentResponse], status_code=status.HTTP_201_CREATED)
async def upload_documents_batch(
    files: list[UploadFile] = File(..., description="Multiple documents to upload at once"),
    outputs: str = Form("vector", description=OUTPUTS_FIELD_DESCRIPTION),
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Upload multiple documents at once. Each is processed independently.

    The chosen outputs apply to every file in the batch.
    """
    auth.require_admin()
    formats = _validate_outputs(outputs)

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
            output_formats=",".join(formats),
        )
        db.add(document)
        await db.flush()

        document = await process_upload(db, document, content, formats)
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
