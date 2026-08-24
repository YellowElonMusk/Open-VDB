"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api import export, retrieve, tenants, upload
from src.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the schema exists so `uvicorn src.main:app` works without any
    # manual migration step. Idempotent; failures are non-fatal (the /health
    # endpoint will report the database as down).
    try:
        from src.db.bootstrap import ensure_schema
        from src.db.session import engine

        await ensure_schema(engine)
    except Exception as e:
        print(f"Warning: could not initialize database schema: {type(e).__name__}: {e}")
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    description=(
        "Self-hosted vector database for OEMs. "
        "Upload manuals, guides, and SOPs — AI tools retrieve only the snippets they need. "
        "Deploy on your own infrastructure. Your data never leaves your network."
    ),
)

# CORS — allow the web UI and any OEM-hosted frontends to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OEM admin endpoints
app.include_router(tenants.router, prefix=settings.api_prefix)
app.include_router(upload.router, prefix=settings.api_prefix)
app.include_router(export.router, prefix=settings.api_prefix)

# AI SaaS tool endpoint
app.include_router(retrieve.router, prefix=settings.api_prefix)


@app.get("/health")
async def health():
    """Health check — used by Docker and monitoring."""
    checks = {"api": "ok"}

    # Check database connectivity
    try:
        from sqlalchemy import text

        from src.db.session import engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}
