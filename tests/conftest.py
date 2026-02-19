"""Shared test fixtures and app configuration."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.core.auth import AuthResult, SCOPE_ADMIN, SCOPE_RETRIEVAL
from src.main import app
from src.models.database import ApiKey, Chunk, Document, Tenant


def _make_tenant(name="Test OEM", slug="test-oem") -> Tenant:
    tenant = MagicMock(spec=Tenant)
    tenant.id = uuid.uuid4()
    tenant.name = name
    tenant.slug = slug
    tenant.is_active = True
    tenant.created_at = datetime.now(timezone.utc)
    tenant.api_keys = []
    tenant.documents = []
    return tenant


def _make_document(tenant_id=None, status="ready") -> Document:
    doc = MagicMock(spec=Document)
    doc.id = uuid.uuid4()
    doc.tenant_id = tenant_id or uuid.uuid4()
    doc.filename = "test-manual.pdf"
    doc.file_type = "pdf"
    doc.file_size_bytes = 1024
    doc.status = status
    doc.chunk_count = 5
    doc.error_message = None
    doc.created_at = datetime.now(timezone.utc)
    return doc


def _make_api_key(tenant_id=None, scope=SCOPE_ADMIN) -> ApiKey:
    key = MagicMock(spec=ApiKey)
    key.id = uuid.uuid4()
    key.tenant_id = tenant_id or uuid.uuid4()
    key.key_hash = "abc123"
    key.label = "Test key"
    key.scope = scope
    key.is_active = True
    key.created_at = datetime.now(timezone.utc)
    return key


@pytest.fixture
def tenant():
    return _make_tenant()


@pytest.fixture
def admin_auth(tenant):
    return AuthResult(tenant=tenant, scope=SCOPE_ADMIN)


@pytest.fixture
def retrieval_auth(tenant):
    return AuthResult(tenant=tenant, scope=SCOPE_RETRIEVAL)


@pytest.fixture
def mock_db():
    """Async mock database session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture
async def admin_client(admin_auth, mock_db):
    """HTTP client authenticated as admin."""
    from src.core.auth import authenticate
    from src.db.session import get_db

    app.dependency_overrides[authenticate] = lambda: admin_auth
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def retrieval_client(retrieval_auth, mock_db):
    """HTTP client authenticated as retrieval (read-only)."""
    from src.core.auth import authenticate
    from src.db.session import get_db

    app.dependency_overrides[authenticate] = lambda: retrieval_auth
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


# Re-export helpers for use in tests
make_tenant = _make_tenant
make_document = _make_document
make_api_key = _make_api_key
