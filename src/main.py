"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles

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
    # /docs is served below from vendored Swagger UI assets so it works
    # air-gapped (the default loads them from a CDN). ReDoc is CDN-only,
    # so it's disabled.
    docs_url=None,
    redoc_url=None,
)


@app.get("/docs", include_in_schema=False)
async def swagger_docs():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{settings.app_name} — API docs",
        swagger_js_url="/swagger/swagger-ui-bundle.js",
        swagger_css_url="/swagger/swagger-ui.css",
        swagger_favicon_url=(
            "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
            "%3Crect width='32' height='32' rx='7' fill='%233b5bdb'/%3E"
            "%3Cellipse cx='16' cy='10' rx='8' ry='3.4' fill='none' stroke='white' stroke-width='2'/%3E"
            "%3Cpath d='M8 10v12c0 1.9 3.6 3.4 8 3.4s8-1.5 8-3.4V10' fill='none' stroke='white' stroke-width='2'/%3E"
            "%3Cpath d='M8 16c0 1.9 3.6 3.4 8 3.4s8-1.5 8-3.4' fill='none' stroke='white' stroke-width='2'/%3E%3C/svg%3E"
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


# Web UI — a static, no-build frontend served at the site root.
# Mounted last so API routes and /health take precedence.
_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="ui")
