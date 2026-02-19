"""Tests for document upload, listing, and deletion endpoints."""

import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_document


class TestUploadDocument:
    async def test_upload_txt_file_success(self, admin_client, mock_db):
        """Admin can upload a .txt file and it gets processed."""
        doc = make_document(status="ready")
        doc.chunk_count = 3

        with patch("src.api.upload.process_upload", return_value=doc) as mock_process:
            with patch("src.core.rate_limit.check_rate_limit", new=AsyncMock()):
                resp = await admin_client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("guide.txt", b"This is the content of the guide.", "text/plain")},
                    headers={"X-API-Key": "vdb_adm_testkey"},
                )

        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "ready"
        assert data["chunk_count"] == 3

    async def test_upload_unsupported_extension_returns_400(self, admin_client, mock_db):
        """Uploading an .exe file returns 400."""
        with patch("src.core.rate_limit.check_rate_limit", new=AsyncMock()):
            resp = await admin_client.post(
                "/api/v1/documents/upload",
                files={"file": ("malware.exe", b"not a doc", "application/octet-stream")},
                headers={"X-API-Key": "vdb_adm_testkey"},
            )

        assert resp.status_code == 400
        assert "Unsupported file type" in resp.json()["detail"]

    async def test_upload_requires_admin(self, retrieval_client, mock_db):
        """Retrieval-scope keys cannot upload."""
        with patch("src.core.rate_limit.check_rate_limit", new=AsyncMock()):
            resp = await retrieval_client.post(
                "/api/v1/documents/upload",
                files={"file": ("guide.txt", b"content", "text/plain")},
                headers={"X-API-Key": "vdb_ret_testkey"},
            )

        assert resp.status_code == 403

    async def test_upload_file_too_large_returns_413(self, admin_client, mock_db):
        """Files over the size limit return 413."""
        big_content = b"x" * (51 * 1024 * 1024)  # 51 MB

        with patch("src.core.rate_limit.check_rate_limit", new=AsyncMock()):
            resp = await admin_client.post(
                "/api/v1/documents/upload",
                files={"file": ("huge.txt", big_content, "text/plain")},
                headers={"X-API-Key": "vdb_adm_testkey"},
            )

        assert resp.status_code == 413


class TestBatchUpload:
    async def test_batch_upload_skips_unsupported_types(self, admin_client, mock_db):
        """Batch upload silently skips unsupported file types and processes the rest."""
        doc = make_document(status="ready")

        with patch("src.api.upload.process_upload", return_value=doc):
            with patch("src.core.rate_limit.check_rate_limit", new=AsyncMock()):
                resp = await admin_client.post(
                    "/api/v1/documents/upload/batch",
                    files=[
                        ("files", ("valid.txt", b"content", "text/plain")),
                        ("files", ("invalid.exe", b"binary", "application/octet-stream")),
                    ],
                    headers={"X-API-Key": "vdb_adm_testkey"},
                )

        assert resp.status_code == 201
        assert len(resp.json()) == 1  # only the .txt was processed


class TestListDocuments:
    async def test_list_documents_returns_all(self, admin_client, mock_db):
        docs = [make_document(), make_document()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = docs
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await admin_client.get("/api/v1/documents", headers={"X-API-Key": "vdb_adm_testkey"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["documents"]) == 2


class TestGetDocument:
    async def test_get_existing_document(self, admin_client, mock_db):
        doc = make_document(status="ready")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await admin_client.get(
            f"/api/v1/documents/{doc.id}",
            headers={"X-API-Key": "vdb_adm_testkey"},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"

    async def test_get_nonexistent_document_returns_404(self, admin_client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await admin_client.get(
            f"/api/v1/documents/{uuid.uuid4()}",
            headers={"X-API-Key": "vdb_adm_testkey"},
        )

        assert resp.status_code == 404


class TestDeleteDocument:
    async def test_delete_document_success(self, admin_client, mock_db):
        doc = make_document()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await admin_client.delete(
            f"/api/v1/documents/{doc.id}",
            headers={"X-API-Key": "vdb_adm_testkey"},
        )

        assert resp.status_code == 204
        mock_db.delete.assert_called_once_with(doc)

    async def test_delete_nonexistent_document_returns_404(self, admin_client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await admin_client.delete(
            f"/api/v1/documents/{uuid.uuid4()}",
            headers={"X-API-Key": "vdb_adm_testkey"},
        )

        assert resp.status_code == 404
