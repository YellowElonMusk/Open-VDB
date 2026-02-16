"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api import retrieve, tenants, upload
from src.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
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

# AI SaaS tool endpoint
app.include_router(retrieve.router, prefix=settings.api_prefix)


@app.get("/health")
async def health():
    """Health check — used by Docker and monitoring."""
    checks = {"api": "ok"}

    # Check database connectivity
    try:
        from src.db.session import async_engine

        async with async_engine.connect() as conn:
            await conn.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}
