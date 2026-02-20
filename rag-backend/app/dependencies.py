"""FastAPI dependencies for authentication and authorization"""

from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.database import get_db
from app.models.database import OEM, OEMStatus
from app.models.schemas import TokenData
from app.services.security import security_service

security = HTTPBearer()


async def get_current_oem(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> OEM:
    """
    Dependency to get current OEM from JWT token

    Raises:
        HTTPException: If token is invalid or OEM not found
    """
    token = credentials.credentials

    # Verify token
    token_data = security_service.verify_token(token)
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get OEM from database
    result = await db.execute(
        select(OEM).where(
            OEM.id == token_data.oem_id,
            OEM.status == OEMStatus.ACTIVE,
            OEM.deleted_at.is_(None)
        )
    )
    oem = result.scalar_one_or_none()

    if oem is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OEM not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return oem


async def get_current_oem_from_api_key(
    x_api_key: str = Header(..., description="OEM API Key"),
    db: AsyncSession = Depends(get_db)
) -> OEM:
    """
    Alternative authentication using API key header

    Raises:
        HTTPException: If API key is invalid
    """
    # Query all active OEMs
    result = await db.execute(
        select(OEM).where(
            OEM.status == OEMStatus.ACTIVE,
            OEM.deleted_at.is_(None)
        )
    )
    oems = result.scalars().all()

    # Verify API key against each OEM
    for oem in oems:
        if security_service.verify_api_key(x_api_key, oem.api_key_hash):
            return oem

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key"
    )


def get_client_ip(x_forwarded_for: Optional[str] = Header(None)) -> str:
    """Get client IP address from headers"""
    if x_forwarded_for:
        # Take the first IP in the chain
        return x_forwarded_for.split(",")[0].strip()
    return "unknown"
