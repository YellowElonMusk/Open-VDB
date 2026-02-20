"""Application configuration using Pydantic Settings"""

from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import validator


class Settings(BaseSettings):
    # Application
    app_name: str = "AI Vision RAG Backend"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = True

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Security
    secret_key: str = "change-this-to-a-secure-random-string-at-least-32-chars"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    encryption_key: str = "change-this-encryption-key-in-production-aes256"

    # Vector Database (Milvus)
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_user: str = ""
    milvus_password: str = ""
    milvus_secure: bool = False

    # Alternative: Pinecone
    pinecone_api_key: Optional[str] = None
    pinecone_environment: Optional[str] = None
    pinecone_index_name: Optional[str] = None

    # Embeddings
    embeddings_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embeddings_dimension: int = 384
    chunk_size: int = 512
    chunk_overlap: int = 50

    # LLM (OpenAI)
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4-turbo-preview"

    # Azure OpenAI (alternative)
    azure_openai_api_key: Optional[str] = None
    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_version: str = "2024-02-01"
    azure_openai_deployment_name: Optional[str] = None

    # Database (PostgreSQL)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_metadata"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # File Storage
    max_upload_size_mb: int = 50
    allowed_extensions: str = ".pdf,.txt,.docx,.md"
    upload_dir: str = "/app/uploads"
    processed_dir: str = "/app/processed"

    # AWS S3 (optional)
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: str = "us-east-1"
    s3_bucket_name: Optional[str] = None

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:8080"

    # Audit Logging
    enable_audit_logging: bool = True

    # Rate Limiting
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 60

    @validator("cors_origins")
    def parse_cors_origins(cls, v):
        return v

    @validator("allowed_extensions")
    def parse_allowed_extensions(cls, v):
        return v

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_extensions_list(self) -> List[str]:
        return [ext.strip() for ext in self.allowed_extensions.split(",") if ext.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def use_azure_openai(self) -> bool:
        return bool(self.azure_openai_api_key and self.azure_openai_endpoint)

    @property
    def use_pinecone(self) -> bool:
        return bool(self.pinecone_api_key and self.pinecone_environment)

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
