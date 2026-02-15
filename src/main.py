"""FastAPI application entry point."""

from fastapi import FastAPI

from src.api import collections, connectors, ingest, query, tenants
from src.core.config import settings

# Ensure example connector is registered on import
import src.connectors.example_crm  # noqa: F401

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Tenant-isolated vector database platform for OEM AI tool integration",
)

app.include_router(tenants.router, prefix=settings.api_prefix)
app.include_router(collections.router, prefix=settings.api_prefix)
app.include_router(ingest.router, prefix=settings.api_prefix)
app.include_router(query.router, prefix=settings.api_prefix)
app.include_router(connectors.router, prefix=settings.api_prefix)


@app.get("/health")
async def health():
    return {"status": "ok"}
