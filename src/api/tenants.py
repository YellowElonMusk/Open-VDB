"""Tenant management — OEM onboarding."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func

from src.api.schemas import ApiKeyCreate, ApiKeyResponse, TenantCreate, TenantDashboard, TenantResponse
from src.core.auth import (
    SCOPE_ADMIN,
    AuthResult,
    authenticate,
    generate_api_key,
    hash_api_key,
)
from src.db.session import get_db
from src.models.database import ApiKey, Document, Tenant

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(body: TenantCreate, db: AsyncSession = Depends(get_db)):
    """Register a new OEM tenant. Returns the admin API key (shown only once)."""
    existing = await db.execute(select(Tenant).where(Tenant.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tenant slug already exists")

    tenant = Tenant(name=body.name, slug=body.slug)
    db.add(tenant)
    await db.flush()

    # Create the first admin key
    raw_key = generate_api_key(SCOPE_ADMIN)
    api_key = ApiKey(
        tenant_id=tenant.id,
        key_hash=hash_api_key(raw_key),
        label="Default admin key",
        scope=SCOPE_ADMIN,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(tenant)

    resp = TenantResponse.model_validate(tenant)
    resp.admin_api_key = raw_key
    return resp


@router.get("/me", response_model=TenantDashboard)
async def get_current_tenant(
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Validate API key and return tenant info.

    This is what the web UI calls when the user clicks 'Connect to Platform'.
    Works with both admin and retrieval keys.
    """
    # Count documents and chunks for this tenant
    doc_count_result = await db.execute(
        select(func.count(Document.id)).where(Document.tenant_id == auth.tenant.id)
    )
    chunk_count_result = await db.execute(
        select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
            Document.tenant_id == auth.tenant.id, Document.status == "ready"
        )
    )

    return TenantDashboard(
        id=auth.tenant.id,
        name=auth.tenant.name,
        slug=auth.tenant.slug,
        is_active=auth.tenant.is_active,
        created_at=auth.tenant.created_at,
        scope=auth.scope,
        document_count=doc_count_result.scalar() or 0,
        total_chunks=chunk_count_result.scalar() or 0,
    )


@router.post("/keys", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreate,
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key. Admin keys can create retrieval keys for AI SaaS tools."""
    auth.require_admin()

    raw_key = generate_api_key(body.scope)
    api_key = ApiKey(
        tenant_id=auth.tenant.id,
        key_hash=hash_api_key(raw_key),
        label=body.label,
        scope=body.scope,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    resp = ApiKeyResponse.model_validate(api_key)
    resp.api_key = raw_key
    return resp


@router.get("/keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    auth: AuthResult = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """List all API keys for this tenant (admin only)."""
    auth.require_admin()
    result = await db.execute(
        select(ApiKey).where(ApiKey.tenant_id == auth.tenant.id, ApiKey.is_active.is_(True))
    )
    return [ApiKeyResponse.model_validate(k) for k in result.scalars().all()]
