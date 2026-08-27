"""Export downloads — get your documents back as plain files.

For simple use cases (matching an error code to its fix, reading an SOP),
an AI agent doesn't need a vector database — it needs a file it can open:

- GET /documents/{id}/export/markdown  → the document as a clean .md file
- GET /documents/{id}/export/sqlite    → a standalone SQLite .db file
- GET /export/sqlite                   → ALL documents in one SQLite .db
                                         file with an FTS5 keyword index
- GET /export/markdown                 → all markdown exports bundled into
                                         a single .md file

Exports contain full document text, so they require an admin API key —
retrieval keys (handed to AI SaaS tools) can never download them.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import AuthResult, authenticate
from src.db.session import get_db
from src.ingestion.exporters import FORMAT_MARKDOWN, FORMAT_SQLITE, build_sqlite
from src.models.database import Artifact, Chunk, Document

router = APIRouter(tags=["exports"])

MEDIA_TYPES = {
    FORMAT_MARKDOWN: "text/markdown; charset=utf-8",
    FORMAT_SQLITE: "application/vnd.sqlite3",
}


def _file_response_doc(description: str, *media_types: str) -> dict:
    """OpenAPI documentation for a binary file download response."""
    return {
        200: {
            "description": description,
            "content": {
                mt: {"schema": {"type": "string", "format": "binary"}} for mt in media_types
            },
        }
    }


def _file_response(filename: str, format: str, content: bytes) -> Response:
    return Response(
        content=content,
        media_type=MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/documents/{document_id}/export/{format}",
    responses=_file_response_doc(
        "The document's generated export file",
        "text/markdown; charset=utf-8",
        "application/vnd.sqlite3",
    ),
    response_class=Response,
)
async def download_document_export(
    document_id: str,
    format: str,
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Download a single document's generated export (markdown or sqlite)."""
    auth.require_admin()

    if format not in MEDIA_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown export format '{format}'. Available: {', '.join(sorted(MEDIA_TYPES))}",
        )

    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == auth.tenant.id,
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    result = await db.execute(
        select(Artifact).where(
            Artifact.document_id == document.id,
            Artifact.format == format,
        )
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No {format} export exists for this document. "
                f"It was uploaded with outputs='{document.output_formats}'. "
                f"Re-upload it with '{format}' included in the outputs field to generate one."
            ),
        )

    return _file_response(artifact.filename, format, artifact.content)


@router.get(
    "/export/sqlite",
    responses=_file_response_doc(
        "One SQLite database file containing every ready document", "application/vnd.sqlite3"
    ),
    response_class=Response,
)
async def export_all_sqlite(
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Download ALL of this tenant's documents as one SQLite database file.

    Built on the fly from the stored text chunks, so it includes every
    ready document regardless of the outputs chosen at upload time. This is
    the file to hand to a local AI agent: one .db with every manual, FAQ,
    and SOP, keyword-searchable via FTS5.
    """
    auth.require_admin()

    result = await db.execute(
        select(Document)
        .where(Document.tenant_id == auth.tenant.id, Document.status == "ready")
        .order_by(Document.created_at)
    )
    documents = result.scalars().all()
    if not documents:
        raise HTTPException(status_code=404, detail="No ready documents to export")

    docs_payload = []
    for doc in documents:
        chunk_rows = await db.execute(
            select(Chunk)
            .where(Chunk.document_id == doc.id)
            .order_by(Chunk.chunk_index)
        )
        # Pass whole rows so page/section/provenance and the fault-code
        # table survive into the exported database.
        docs_payload.append(
            {
                "id": doc.id,
                "filename": doc.filename,
                "file_type": doc.file_type,
                "chunks": list(chunk_rows.scalars().all()),
            }
        )

    db_bytes = build_sqlite(docs_payload)
    return _file_response(f"{auth.tenant.slug}-documents.db", FORMAT_SQLITE, db_bytes)


@router.get(
    "/export/markdown",
    responses=_file_response_doc(
        "All markdown exports bundled into a single .md file", "text/markdown; charset=utf-8"
    ),
    response_class=Response,
)
async def export_all_markdown(
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Download all markdown exports bundled into a single .md file.

    Includes documents uploaded with the 'markdown' output. Documents
    uploaded without it are listed at the top so you know what's missing.
    """
    auth.require_admin()

    result = await db.execute(
        select(Document)
        .where(Document.tenant_id == auth.tenant.id, Document.status == "ready")
        .order_by(Document.created_at)
    )
    documents = result.scalars().all()

    sections = []
    missing = []
    for doc in documents:
        artifact_result = await db.execute(
            select(Artifact).where(
                Artifact.document_id == doc.id,
                Artifact.format == FORMAT_MARKDOWN,
            )
        )
        artifact = artifact_result.scalar_one_or_none()
        if artifact is not None:
            sections.append(artifact.content.decode("utf-8"))
        else:
            missing.append(doc.filename)

    if not sections:
        raise HTTPException(
            status_code=404,
            detail=(
                "No markdown exports exist yet. Upload documents with "
                "'markdown' included in the outputs field to generate them."
            ),
        )

    parts = [f"# {auth.tenant.name} — Document Library\n"]
    if missing:
        parts.append(
            "> Not included (uploaded without the markdown output): "
            + ", ".join(f"`{name}`" for name in missing)
            + "\n"
        )
    parts.extend(sections)

    content = "\n\n".join(parts).encode("utf-8")
    return _file_response(f"{auth.tenant.slug}-documents.md", FORMAT_MARKDOWN, content)
