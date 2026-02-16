from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "VectorDB OEM Platform"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/vectordb_oem"
    database_url_sync: str = "postgresql://postgres:postgres@localhost:5432/vectordb_oem"

    # Redis (for rate limiting / caching)
    redis_url: str = "redis://localhost:6379/0"

    # Embedding
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Ingestion
    chunk_size: int = 512
    chunk_overlap: int = 64
    max_upload_size_mb: int = 50

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # API
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = [
        "https://aidatabasebuilder.base44.app",
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    model_config = {"env_prefix": "VDB_", "env_file": ".env"}


settings = Settings()
