"""API key authentication for tenant-scoped requests."""

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.models.database import Tenant


def generate_api_key() -> str:
    return f"vdb_{secrets.token_urlsafe(32)}"


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def get_current_tenant(
    x_api_key: str = Header(..., description="Tenant API key"),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    key_hash = hash_api_key(x_api_key)
    result = await db.execute(select(Tenant).where(Tenant.api_key_hash == key_hash, Tenant.is_active.is_(True)))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive API key")
    return tenant
