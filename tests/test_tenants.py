"""Tests for tenant management endpoints."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_api_key, make_tenant


class TestCreateTenant:
    async def test_create_tenant_success(self, mock_db):
        """POST /tenants creates a tenant and returns an admin key."""
        from httpx import ASGITransport, AsyncClient
        from src.main import app
        from src.db.session import get_db

        # No existing tenant with that slug
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/tenants",
                json={"name": "Acme Corp", "slug": "acme-corp"},
            )

        app.dependency_overrides.clear()

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Acme Corp"
        assert data["slug"] == "acme-corp"
        assert data["admin_api_key"].startswith("vdb_adm_")

    async def test_create_tenant_duplicate_slug_returns_409(self, mock_db):
        """POST /tenants with an existing slug returns 409."""
        from httpx import ASGITransport, AsyncClient
        from src.main import app
        from src.db.session import get_db

        existing_tenant = make_tenant()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_tenant
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/tenants",
                json={"name": "Dupe Corp", "slug": "acme-corp"},
            )

        app.dependency_overrides.clear()

        assert resp.status_code == 409

    async def test_create_tenant_invalid_slug_returns_422(self, mock_db):
        """Slug with uppercase or spaces is rejected."""
        from httpx import ASGITransport, AsyncClient
        from src.main import app
        from src.db.session import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/tenants",
                json={"name": "Bad Slug Corp", "slug": "Bad Slug!"},
            )

        app.dependency_overrides.clear()

        assert resp.status_code == 422


class TestGetMe:
    async def test_get_me_returns_tenant_info(self, admin_client, mock_db):
        """/tenants/me returns dashboard info for the authenticated tenant."""
        doc_count_result = MagicMock()
        doc_count_result.scalar.return_value = 3
        chunk_count_result = MagicMock()
        chunk_count_result.scalar.return_value = 42
        mock_db.execute = AsyncMock(side_effect=[doc_count_result, chunk_count_result])

        resp = await admin_client.get("/api/v1/tenants/me", headers={"X-API-Key": "vdb_adm_testkey"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["document_count"] == 3
        assert data["total_chunks"] == 42
        assert data["scope"] == "admin"


class TestApiKeys:
    async def test_create_retrieval_key(self, admin_client, mock_db):
        """Admin can create a retrieval key."""
        new_key = make_api_key(scope="retrieval")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.refresh = AsyncMock(side_effect=lambda obj: None)

        with patch("src.api.tenants.generate_api_key", return_value="vdb_ret_newkey123"):
            with patch("src.api.tenants.hash_api_key", return_value="hash123"):
                resp = await admin_client.post(
                    "/api/v1/tenants/keys",
                    json={"label": "CRM Bot Key", "scope": "retrieval"},
                    headers={"X-API-Key": "vdb_adm_testkey"},
                )

        assert resp.status_code == 201
        data = resp.json()
        assert data["label"] == "CRM Bot Key"
        assert data["scope"] == "retrieval"

    async def test_retrieval_key_cannot_create_keys(self, retrieval_client, mock_db):
        """Retrieval keys cannot create other keys (admin only)."""
        resp = await retrieval_client.post(
            "/api/v1/tenants/keys",
            json={"label": "Another key", "scope": "retrieval"},
            headers={"X-API-Key": "vdb_ret_testkey"},
        )
        assert resp.status_code == 403

    async def test_revoke_key(self, admin_client, mock_db):
        """Admin can revoke an API key by ID."""
        existing_key = make_api_key()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_key
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await admin_client.delete(
            f"/api/v1/tenants/keys/{existing_key.id}",
            headers={"X-API-Key": "vdb_adm_testkey"},
        )

        assert resp.status_code == 204
        assert existing_key.is_active is False

    async def test_revoke_nonexistent_key_returns_404(self, admin_client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await admin_client.delete(
            f"/api/v1/tenants/keys/{uuid.uuid4()}",
            headers={"X-API-Key": "vdb_adm_testkey"},
        )

        assert resp.status_code == 404
