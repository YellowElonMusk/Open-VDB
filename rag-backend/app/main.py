"""Main FastAPI application"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import structlog
import time

from app.config import settings
from app.database import init_db, close_db
from app.services.vector_db import vector_db
from app.services.embeddings import embeddings_service
from app.services.llm import llm_service
from app.routers import oem, documents, rag

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("Starting RAG backend", version=settings.app_version, env=settings.environment)

    # Initialize database
    await init_db()

    # Connect to vector database
    await vector_db.connect()

    # Load embeddings model
    await embeddings_service.load_model()

    # Initialize LLM service
    await llm_service.initialize()

    logger.info("RAG backend started successfully")

    yield

    # Shutdown
    logger.info("Shutting down RAG backend")

    # Disconnect from vector database
    await vector_db.disconnect()

    # Close database connections
    await close_db()

    logger.info("RAG backend shutdown complete")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Multi-tenant RAG knowledge base for AI Vision App",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests"""
    start_time = time.time()

    logger.info(
        "Request started",
        method=request.method,
        path=request.url.path,
        client=request.client.host if request.client else None
    )

    response = await call_next(request)

    process_time = int((time.time() - start_time) * 1000)
    logger.info(
        "Request completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        process_time_ms=process_time
    )

    response.headers["X-Process-Time"] = str(process_time)

    return response


# Exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors"""
    logger.warning("Validation error", errors=exc.errors(), body=exc.body)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation Error",
            "details": exc.errors()
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors"""
    logger.error(
        "Unexpected error",
        error=str(exc),
        path=request.url.path,
        method=request.method
    )

    if settings.is_production:
        detail = "An internal error occurred"
    else:
        detail = str(exc)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "detail": detail
        }
    )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "environment": settings.environment,
        "services": {
            "database": "connected",
            "vector_db": "connected" if vector_db.connected else "disconnected",
            "embeddings": "loaded" if embeddings_service.model else "not_loaded",
            "llm": "initialized" if llm_service.client else "not_initialized"
        }
    }


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs" if settings.debug else "disabled in production"
    }


# Include routers
app.include_router(oem.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(rag.router, prefix="/api/v1")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info"
    )
