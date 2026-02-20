"""Security services: authentication, encryption, audit logging"""

import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from cryptography.fernet import Fernet
import structlog

from app.config import settings
from app.models.schemas import TokenData

logger = structlog.get_logger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Encryption for OEM data keys
fernet = Fernet(settings.encryption_key.encode()[:44])  # Fernet needs 44 bytes


class SecurityService:
    """Security service for auth, encryption, and audit logging"""

    @staticmethod
    def generate_api_key() -> str:
        """Generate a secure API key"""
        return secrets.token_urlsafe(32)

    @staticmethod
    def hash_api_key(api_key: str) -> str:
        """Hash an API key for storage"""
        return pwd_context.hash(api_key)

    @staticmethod
    def verify_api_key(plain_key: str, hashed_key: str) -> bool:
        """Verify an API key against its hash"""
        try:
            return pwd_context.verify(plain_key, hashed_key)
        except Exception:
            return False

    @staticmethod
    def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
        """
        Create JWT access token

        Args:
            data: Token payload
            expires_delta: Token expiration time

        Returns:
            Encoded JWT token
        """
        to_encode = data.copy()

        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)

        to_encode.update({"exp": expire})

        encoded_jwt = jwt.encode(
            to_encode,
            settings.secret_key,
            algorithm=settings.algorithm
        )

        return encoded_jwt

    @staticmethod
    def verify_token(token: str) -> Optional[TokenData]:
        """
        Verify and decode JWT token

        Args:
            token: JWT token string

        Returns:
            TokenData if valid, None otherwise
        """
        try:
            payload = jwt.decode(
                token,
                settings.secret_key,
                algorithms=[settings.algorithm]
            )

            oem_id: str = payload.get("oem_id")
            oem_name: str = payload.get("oem_name")

            if oem_id is None:
                return None

            return TokenData(
                oem_id=oem_id,
                oem_name=oem_name,
                scopes=payload.get("scopes", [])
            )

        except JWTError as e:
            logger.warning("Invalid token", error=str(e))
            return None

    @staticmethod
    def encrypt_data(data: str) -> str:
        """
        Encrypt sensitive data (AES-256)

        Args:
            data: Plain text data

        Returns:
            Encrypted data (base64 encoded)
        """
        return fernet.encrypt(data.encode()).decode()

    @staticmethod
    def decrypt_data(encrypted_data: str) -> str:
        """
        Decrypt sensitive data

        Args:
            encrypted_data: Encrypted data (base64 encoded)

        Returns:
            Plain text data
        """
        return fernet.decrypt(encrypted_data.encode()).decode()

    @staticmethod
    def generate_encryption_key() -> str:
        """Generate a new encryption key for OEM data"""
        return Fernet.generate_key().decode()

    @staticmethod
    def hash_file(file_path: str) -> str:
        """
        Generate SHA-256 hash of a file

        Args:
            file_path: Path to file

        Returns:
            Hex digest of SHA-256 hash
        """
        sha256_hash = hashlib.sha256()

        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)

        return sha256_hash.hexdigest()

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        Sanitize filename to prevent path traversal

        Args:
            filename: Original filename

        Returns:
            Safe filename
        """
        # Remove path separators and dangerous characters
        safe_name = filename.replace("/", "_").replace("\\", "_")
        safe_name = "".join(c for c in safe_name if c.isalnum() or c in "._- ")
        return safe_name[:255]  # Limit length


class AuditLogger:
    """Audit logging for compliance"""

    @staticmethod
    async def log_action(
        action: str,
        oem_id: Optional[str] = None,
        user_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        """
        Log an auditable action

        This would typically write to the audit_logs database table.
        For now, we'll use structured logging.
        """
        log_data = {
            "action": action,
            "oem_id": oem_id,
            "user_id": user_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "ip_address": ip_address,
            "details": details or {},
            "timestamp": datetime.utcnow().isoformat(),
        }
        log_data.update(kwargs)

        logger.info("AUDIT", **log_data)


# Global instances
security_service = SecurityService()
audit_logger = AuditLogger()
