"""OEM management API endpoints"""

import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import structlog

from app.database import get_db
from app.models.database import OEM, OEMStatus, AuditAction, Document
from app.models.schemas import (
    OEMCreate, OEMUpdate, OEMResponse, OEMWithApiKey, OEMStatistics
)
from app.services.security import security_service, audit_logger
from app.services.vector_db import vector_db
from app.dependencies import get_current_oem, get_client_ip

router = APIRouter(prefix="/oem", tags=["OEM Management"])
logger = structlog.get_logger(__name__)


@router.post("/", response_model=OEMWithApiKey, status_code=status.HTTP_201_CREATED)
async def create_oem(
    oem_data: OEMCreate,
    db: AsyncSession = Depends(get_db),
    ip_address: str = Depends(get_client_ip)
):
    """
    Create a new OEM account with isolated vector collection

    Returns API key - store it securely, it won't be shown again!
    """
    try:
        # Check if OEM name already exists
        result = await db.execute(
            select(OEM).where(OEM.name == oem_data.name)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OEM with name '{oem_data.name}' already exists"
            )

        # Generate IDs and keys
        oem_id = str(uuid.uuid4())
        api_key = security_service.generate_api_key()
        api_key_hash = security_service.hash_api_key(api_key)
        collection_name = f"oem_{oem_data.name.lower().replace(' ', '_')}_{oem_id[:8]}"

        # Generate OEM-specific encryption key
        oem_encryption_key = security_service.generate_encryption_key()
        encrypted_key = security_service.encrypt_data(oem_encryption_key)

        # Create OEM record
        new_oem = OEM(
            id=oem_id,
            name=oem_data.name,
            display_name=oem_data.display_name,
            description=oem_data.description,
            collection_name=collection_name,
            contact_email=oem_data.contact_email,
            contact_name=oem_data.contact_name,
            status=OEMStatus.ACTIVE,
            api_key_hash=api_key_hash,
            data_encryption_key=encrypted_key,
            metadata=oem_data.metadata or {}
        )

        db.add(new_oem)
        await db.commit()
        await db.refresh(new_oem)

        # Create isolated vector database collection
        await vector_db.create_oem_collection(oem_id, collection_name)

        # Audit log
        await audit_logger.log_action(
            action=AuditAction.OEM_CREATED.value,
            oem_id=oem_id,
            resource_type="oem",
            resource_id=oem_id,
            ip_address=ip_address,
            details={"name": oem_data.name}
        )

        logger.info("OEM created", oem_id=oem_id, name=oem_data.name)

        # Return OEM data with API key
        response_data = OEMResponse.from_orm(new_oem)
        return OEMWithApiKey(**response_data.dict(), api_key=api_key)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("Failed to create OEM", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create OEM account"
        )


@router.get("/me", response_model=OEMResponse)
async def get_current_oem_info(
    current_oem: OEM = Depends(get_current_oem)
):
    """Get current OEM's information"""
    return OEMResponse.from_orm(current_oem)


@router.patch("/me", response_model=OEMResponse)
async def update_current_oem(
    update_data: OEMUpdate,
    current_oem: OEM = Depends(get_current_oem),
    db: AsyncSession = Depends(get_db),
    ip_address: str = Depends(get_client_ip)
):
    """Update current OEM's information"""
    try:
        # Update fields
        update_dict = update_data.dict(exclude_unset=True)

        for field, value in update_dict.items():
            setattr(current_oem, field, value)

        current_oem.updated_at = datetime.utcnow()

        await db.commit()
        await db.refresh(current_oem)

        # Audit log
        await audit_logger.log_action(
            action=AuditAction.OEM_UPDATED.value,
            oem_id=current_oem.id,
            resource_type="oem",
            resource_id=current_oem.id,
            ip_address=ip_address,
            details={"updated_fields": list(update_dict.keys())}
        )

        logger.info("OEM updated", oem_id=current_oem.id)

        return OEMResponse.from_orm(current_oem)

    except Exception as e:
        await db.rollback()
        logger.error("Failed to update OEM", oem_id=current_oem.id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update OEM"
        )


@router.get("/stats", response_model=OEMStatistics)
async def get_oem_statistics(
    current_oem: OEM = Depends(get_current_oem),
    db: AsyncSession = Depends(get_db)
):
    """Get statistics for current OEM's knowledge base"""
    try:
        # Count documents
        result = await db.execute(
            select(func.count(Document.id)).where(
                Document.oem_id == current_oem.id,
                Document.deleted_at.is_(None)
            )
        )
        total_documents = result.scalar() or 0

        # Sum chunks and tokens
        result = await db.execute(
            select(
                func.sum(Document.total_chunks),
                func.sum(Document.total_tokens),
                func.sum(Document.file_size_bytes)
            ).where(
                Document.oem_id == current_oem.id,
                Document.deleted_at.is_(None)
            )
        )
        row = result.one()
        total_chunks = row[0] or 0
        total_tokens = row[1] or 0
        storage_bytes = row[2] or 0

        # Vector DB stats
        await vector_db.get_collection_stats(current_oem.collection_name)

        return OEMStatistics(
            oem_id=current_oem.id,
            total_documents=total_documents,
            total_chunks=total_chunks,
            total_tokens=total_tokens,
            total_queries=0,  # Would track this separately
            storage_bytes=storage_bytes,
            last_query_at=None,
            created_at=current_oem.created_at
        )

    except Exception as e:
        logger.error("Failed to get stats", oem_id=current_oem.id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve statistics"
        )


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_current_oem(
    current_oem: OEM = Depends(get_current_oem),
    db: AsyncSession = Depends(get_db),
    ip_address: str = Depends(get_client_ip)
):
    """
    Delete current OEM account (soft delete)

    WARNING: This will mark the OEM as deleted but preserve data for compliance.
    """
    try:
        # Soft delete
        current_oem.status = OEMStatus.DELETED
        current_oem.deleted_at = datetime.utcnow()

        await db.commit()

        # Audit log
        await audit_logger.log_action(
            action=AuditAction.OEM_DELETED.value,
            oem_id=current_oem.id,
            resource_type="oem",
            resource_id=current_oem.id,
            ip_address=ip_address
        )

        logger.info("OEM deleted", oem_id=current_oem.id)

        return None

    except Exception as e:
        await db.rollback()
        logger.error("Failed to delete OEM", oem_id=current_oem.id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete OEM"
        )
