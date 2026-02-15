"""FastAPI application entry point."""

from fastapi import FastAPI

from src.api import retrieve, tenants, upload
from src.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Upload manuals, guides, and SOPs — get an instant vector database. "
        "AI SaaS tools retrieve only the snippets they need, never your full proprietary docs."
    ),
)

# OEM admin endpoints
app.include_router(tenants.router, prefix=settings.api_prefix)
app.include_router(upload.router, prefix=settings.api_prefix)

# AI SaaS tool endpoint
app.include_router(retrieve.router, prefix=settings.api_prefix)


@app.get("/health")
async def health():
    return {"status": "ok"}
