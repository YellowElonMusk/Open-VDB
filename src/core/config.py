from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Open VDB"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/vectordb_oem"
    database_url_sync: str = "postgresql://postgres:postgres@localhost:5432/vectordb_oem"

    # Embeddings. Local mode works offline with no API key; OpenAI gives stronger
    # semantic matching but sends document chunks and queries to OpenAI.
    embedding_provider: Literal["local", "openai"] = "local"
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Ingestion
    chunk_size: int = 900
    chunk_overlap: int = 120
    max_upload_size_mb: int = 50
    max_batch_files: int = 50

    # Local desktop mode. Requests from the bundled UI do not need an API key.
    # Docker binds to 127.0.0.1 by default, so this is not exposed to the LAN.
    local_mode: bool = True
    local_tenant_name: str = "My Knowledge Base"
    local_tenant_slug: str = "local"

    # API
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = []

    model_config = {"env_prefix": "VDB_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
