"""API key authentication with scoped permissions.

Two key types:
- admin:     OEM uses to upload docs, manage settings, create retrieval keys
- retrieval: AI SaaS tools use to query — read-only, returns only relevant chunks
"""

import hashlib
import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.session import get_db
from src.models.database import ApiKey, Tenant


SCOPE_ADMIN = "admin"
SCOPE_RETRIEVAL = "retrieval"


def generate_api_key(scope: str) -> str:
    prefix = "vdb_adm" if scope == SCOPE_ADMIN else "vdb_ret"
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class AuthResult:
    """Wraps the authenticated tenant + the scope of the key used."""

    def __init__(self, tenant: Tenant, scope: str):
        self.tenant = tenant
        self.scope = scope

    @property
    def is_admin(self) -> bool:
        return self.scope == SCOPE_ADMIN

    def require_admin(self):
        if not self.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This action requires an admin API key",
            )


async def authenticate(
    x_api_key: str = Header(..., description="API key (admin or retrieval)"),
    db: AsyncSession = Depends(get_db),
) -> AuthResult:
    key_hash = hash_api_key(x_api_key)
    result = await db.execute(
        select(ApiKey)
        .options(selectinload(ApiKey.tenant))
        .where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
    )
    api_key = result.scalar_one_or_none()
    if api_key is None or not api_key.tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )
    return AuthResult(tenant=api_key.tenant, scope=api_key.scope)
