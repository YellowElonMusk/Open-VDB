"""Tests for API key auth: generation, hashing, scope enforcement."""

import pytest

from src.core.auth import (
    SCOPE_ADMIN,
    SCOPE_RETRIEVAL,
    AuthResult,
    generate_api_key,
    hash_api_key,
)
from tests.conftest import make_tenant


def test_generate_admin_key_has_correct_prefix():
    key = generate_api_key(SCOPE_ADMIN)
    assert key.startswith("vdb_adm_")


def test_generate_retrieval_key_has_correct_prefix():
    key = generate_api_key(SCOPE_RETRIEVAL)
    assert key.startswith("vdb_ret_")


def test_generated_keys_are_unique():
    keys = {generate_api_key(SCOPE_ADMIN) for _ in range(10)}
    assert len(keys) == 10


def test_hash_is_deterministic():
    key = "vdb_adm_testkey123"
    assert hash_api_key(key) == hash_api_key(key)


def test_different_keys_have_different_hashes():
    assert hash_api_key("key_a") != hash_api_key("key_b")


def test_hash_is_not_reversible():
    key = generate_api_key(SCOPE_ADMIN)
    h = hash_api_key(key)
    assert key not in h


class TestAuthResult:
    def test_admin_scope_is_admin(self):
        auth = AuthResult(tenant=make_tenant(), scope=SCOPE_ADMIN)
        assert auth.is_admin is True

    def test_retrieval_scope_is_not_admin(self):
        auth = AuthResult(tenant=make_tenant(), scope=SCOPE_RETRIEVAL)
        assert auth.is_admin is False

    def test_require_admin_passes_for_admin(self):
        auth = AuthResult(tenant=make_tenant(), scope=SCOPE_ADMIN)
        auth.require_admin()  # should not raise

    def test_require_admin_raises_for_retrieval(self):
        from fastapi import HTTPException
        auth = AuthResult(tenant=make_tenant(), scope=SCOPE_RETRIEVAL)
        with pytest.raises(HTTPException) as exc_info:
            auth.require_admin()
        assert exc_info.value.status_code == 403
