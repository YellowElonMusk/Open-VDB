"""Collection management endpoints — scoped to the authenticated tenant."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import CollectionCreate, CollectionResponse
from src.core.auth import get_current_tenant
from src.db.session import get_db
from src.models.database import Collection, Tenant

router = APIRouter(prefix="/collections", tags=["collections"])


@router.post("", response_model=CollectionResponse, status_code=status.HTTP_201_CREATED)
async def create_collection(
    body: CollectionCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(Collection).where(Collection.tenant_id == tenant.id, Collection.name == body.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Collection already exists for this tenant")

    collection = Collection(tenant_id=tenant.id, name=body.name, description=body.description)
    db.add(collection)
    await db.commit()
    await db.refresh(collection)
    return CollectionResponse.model_validate(collection)


@router.get("", response_model=list[CollectionResponse])
async def list_collections(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Collection).where(Collection.tenant_id == tenant.id))
    return [CollectionResponse.model_validate(c) for c in result.scalars().all()]
