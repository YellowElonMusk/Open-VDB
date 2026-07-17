"""Open VDB application entry point."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from src.api import retrieve, tenants, upload
from src.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="Drop in documents and get a searchable local vector database.",
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(tenants.router, prefix=settings.api_prefix)
app.include_router(upload.router, prefix=settings.api_prefix)
app.include_router(retrieve.router, prefix=settings.api_prefix)

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def home():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"name": settings.app_name, "docs": "/docs"}


@app.get("/health")
async def health():
    checks = {"api": "ok"}
    try:
        from src.db.session import engine

        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"

    overall = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
    return {
        "status": overall,
        "checks": checks,
        "embedding_provider": settings.embedding_provider,
        "local_mode": settings.local_mode,
    }
