"""Tests for the semantic search retrieval endpoint."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_document


class TestRetrieve:
    async def test_retrieve_returns_snippets(self, admin_client, mock_db):
        """POST /retrieve returns relevant snippets for a query."""
        snippet_id = uuid.uuid4()
        row = MagicMock()
        row.id = snippet_id
        row.content = "Reset the hydraulic pressure valve by turning it counter-clockwise."
        row.filename = "service-manual.pdf"
        row.distance = 0.05  # close match

        mock_result = MagicMock()
        mock_result.all.return_value = [row]
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("src.api.retrieve.embed_texts", new=AsyncMock(return_value=[[0.1] * 1536])):
            with patch("src.core.rate_limit.check_rate_limit", new=AsyncMock()):
                resp = await admin_client.post(
                    "/api/v1/retrieve",
                    json={"query": "how to reset hydraulic pressure valve", "top_k": 3},
                    headers={"X-API-Key": "vdb_ret_testkey"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "how to reset hydraulic pressure valve"
        assert len(data["snippets"]) == 1
        snippet = data["snippets"][0]
        assert snippet["content"] == row.content
        assert snippet["source_filename"] == "service-manual.pdf"
        assert snippet["relevance_score"] == round(1 - row.distance, 4)

    async def test_retrieve_empty_when_no_documents(self, retrieval_client, mock_db):
        """Returns empty list when no documents are indexed."""
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("src.api.retrieve.embed_texts", new=AsyncMock(return_value=[[0.1] * 1536])):
            with patch("src.core.rate_limit.check_rate_limit", new=AsyncMock()):
                resp = await retrieval_client.post(
                    "/api/v1/retrieve",
                    json={"query": "anything", "top_k": 5},
                    headers={"X-API-Key": "vdb_ret_testkey"},
                )

        assert resp.status_code == 200
        assert resp.json()["snippets"] == []

    async def test_retrieve_top_k_validation(self, admin_client, mock_db):
        """top_k must be between 1 and 20."""
        with patch("src.core.rate_limit.check_rate_limit", new=AsyncMock()):
            resp = await admin_client.post(
                "/api/v1/retrieve",
                json={"query": "something", "top_k": 0},
                headers={"X-API-Key": "vdb_ret_testkey"},
            )
        assert resp.status_code == 422

        with patch("src.core.rate_limit.check_rate_limit", new=AsyncMock()):
            resp = await admin_client.post(
                "/api/v1/retrieve",
                json={"query": "something", "top_k": 21},
                headers={"X-API-Key": "vdb_ret_testkey"},
            )
        assert resp.status_code == 422

    async def test_retrieve_requires_query(self, admin_client, mock_db):
        """Empty query string is rejected."""
        with patch("src.core.rate_limit.check_rate_limit", new=AsyncMock()):
            resp = await admin_client.post(
                "/api/v1/retrieve",
                json={"query": "", "top_k": 5},
                headers={"X-API-Key": "vdb_ret_testkey"},
            )
        assert resp.status_code == 422


class TestRateLimit:
    async def test_rate_limit_exceeded_returns_429(self, admin_client, mock_db):
        """Exceeding rate limit returns 429."""
        from fastapi import HTTPException

        with patch(
            "src.api.retrieve.check_rate_limit",
            new=AsyncMock(side_effect=HTTPException(status_code=429, detail="Rate limit exceeded")),
        ):
            with patch("src.api.retrieve.embed_texts", new=AsyncMock(return_value=[[0.1] * 1536])):
                resp = await admin_client.post(
                    "/api/v1/retrieve",
                    json={"query": "something", "top_k": 5},
                    headers={"X-API-Key": "vdb_adm_testkey"},
                )

        assert resp.status_code == 429
