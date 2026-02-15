"""Tenant management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import TenantCreate, TenantResponse
from src.core.auth import generate_api_key, hash_api_key
from src.db.session import get_db
from src.models.database import Tenant

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(body: TenantCreate, db: AsyncSession = Depends(get_db)):
    # Check slug uniqueness
    existing = await db.execute(select(Tenant).where(Tenant.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tenant slug already exists")

    api_key = generate_api_key()
    tenant = Tenant(
        name=body.name,
        slug=body.slug,
        api_key_hash=hash_api_key(api_key),
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    resp = TenantResponse.model_validate(tenant)
    resp.api_key = api_key  # only returned once
    return resp
