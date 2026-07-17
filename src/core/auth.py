"""API-key authentication with an optional safe local desktop mode."""

import hashlib
import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.config import settings
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
    def __init__(self, tenant: Tenant, scope: str):
        self.tenant = tenant
        self.scope = scope

    @property
    def is_admin(self) -> bool:
        return self.scope == SCOPE_ADMIN

    def require_admin(self) -> None:
        if not self.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This action requires an admin API key",
            )


async def _get_or_create_local_tenant(db: AsyncSession) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.slug == settings.local_tenant_slug))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(name=settings.local_tenant_name, slug=settings.local_tenant_slug)
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)
    return tenant


async def authenticate(
    x_api_key: str | None = Header(default=None, description="API key for server mode"),
    db: AsyncSession = Depends(get_db),
) -> AuthResult:
    """Authenticate an API key, or use the private local workspace in local mode."""
    if settings.local_mode and not x_api_key:
        tenant = await _get_or_create_local_tenant(db)
        return AuthResult(tenant=tenant, scope=SCOPE_ADMIN)

    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key required")

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
