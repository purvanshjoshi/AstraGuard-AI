"""
Authentication and Authorization Module for AstraGuard AI

Provides comprehensive API security including:
- API key generation, validation, and rotation
- Role-Based Access Control (RBAC) with operator, analyst, admin roles
- JWT token management with configurable expiration
- Secure key storage with encryption
- User management functions
- Audit logging integration
"""

import os
import secrets
import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass, asdict
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
from passlib.context import CryptContext
from jose import JWTError, jwt
from fastapi import HTTPException, status, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from astraguard.logging_config import get_logger
from core.audit_logger import get_audit_logger, AuditEventType

# Constants
API_KEY_LENGTH = 32
JWT_SECRET_KEY_MIN_LENGTH = 32
ENCRYPTION_KEY_LENGTH = 32
DEFAULT_JWT_EXPIRATION_HOURS = 24
DEFAULT_API_KEY_EXPIRATION_DAYS = 365

# File paths
AUTH_DATA_DIR = Path("data/auth")
AUTH_DATA_DIR.mkdir(parents=True, exist_ok=True)
USERS_FILE = AUTH_DATA_DIR / "users.json"
API_KEYS_FILE = AUTH_DATA_DIR / "api_keys.json"
ENCRYPTION_KEY_FILE = AUTH_DATA_DIR / "encryption.key"

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT Security
security = HTTPBearer()


class UserRole(str, Enum):
    """User roles with hierarchical permissions."""
    ADMIN = "admin"      # Full system access including user management
    OPERATOR = "operator"  # Full operational access (telemetry, phase changes)
    ANALYST = "analyst"   # Read-only access (status, history, monitoring)


class Permission(str, Enum):
    """Granular permissions for RBAC."""
    # System management
    MANAGE_USERS = "manage_users"
    SYSTEM_CONFIG = "system_config"

    # Operational
    SUBMIT_TELEMETRY = "submit_telemetry"
    UPDATE_PHASE = "update_phase"
    MANAGE_MEMORY = "manage_memory"

    # Monitoring/Read-only
    READ_STATUS = "read_status"
    READ_HISTORY = "read_history"
    READ_METRICS = "read_metrics"


# Role-based permissions mapping
ROLE_PERMISSIONS = {
    UserRole.ADMIN: [
        Permission.MANAGE_USERS,
        Permission.SYSTEM_CONFIG,
        Permission.SUBMIT_TELEMETRY,
        Permission.UPDATE_PHASE,
        Permission.MANAGE_MEMORY,
        Permission.READ_STATUS,
        Permission.READ_HISTORY,
        Permission.READ_METRICS,
    ],
    UserRole.OPERATOR: [
        Permission.SUBMIT_TELEMETRY,
        Permission.UPDATE_PHASE,
        Permission.MANAGE_MEMORY,
        Permission.READ_STATUS,
        Permission.READ_HISTORY,
        Permission.READ_METRICS,
    ],
    UserRole.ANALYST: [
        Permission.READ_STATUS,
        Permission.READ_HISTORY,
        Permission.READ_METRICS,
    ],
}


@dataclass
class User:
    """User account information."""
    id: str
    username: str
    email: str
    role: UserRole
    created_at: datetime
    last_login: Optional[datetime] = None
    is_active: bool = True
    hashed_password: Optional[str] = None  # For future password auth

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        data = asdict(self)
        data['created_at'] = self.created_at.isoformat()
        if self.last_login:
            data['last_login'] = self.last_login.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'User':
        """Create from dictionary."""
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        if data.get('last_login'):
            data['last_login'] = datetime.fromisoformat(data['last_login'])
        return cls(**data)


@dataclass
class APIKey:
    """API key with metadata."""
    id: str
    user_id: str
    name: str
    hashed_key: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_used: Optional[datetime] = None
    is_active: bool = True
    rate_limit: Optional[int] = None  # requests per minute

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        data = asdict(self)
        data['created_at'] = self.created_at.isoformat()
        if self.expires_at:
            data['expires_at'] = self.expires_at.isoformat()
        if self.last_used:
            data['last_used'] = self.last_used.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'APIKey':
        """Create from dictionary."""
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        if data.get('expires_at'):
            data['expires_at'] = datetime.fromisoformat(data['expires_at'])
        if data.get('last_used'):
            data['last_used'] = datetime.fromisoformat(data['last_used'])
        return cls(**data)

    def is_expired(self) -> bool:
        """Check if API key is expired."""
        if self.expires_at:
            return datetime.now() > self.expires_at
        return False


class AuthManager:
    """Central authentication and authorization manager."""

    def __init__(self):
        self.logger = get_logger(__name__)
        self._encryption_key = self._load_or_create_encryption_key()
        self._fernet = Fernet(self._encryption_key)
        self._users = self._load_users()
        self._api_keys = self._load_api_keys()
        self._jwt_secret = self._get_jwt_secret()

    def _load_or_create_encryption_key(self) -> bytes:
        """Load or create encryption key for secure storage."""
        if ENCRYPTION_KEY_FILE.exists():
            with open(ENCRYPTION_KEY_FILE, 'rb') as f:
                return f.read()

        # Generate new key
        key = Fernet.generate_key()
        with open(ENCRYPTION_KEY_FILE, 'wb') as f:
            f.write(key)
        return key

    def _load_users(self) -> Dict[str, User]:
        """Load users from encrypted storage."""
        if not USERS_FILE.exists():
            return {}

        try:
            with open(USERS_FILE, 'rb') as f:
                encrypted_data = f.read()
            decrypted_data = self._fernet.decrypt(encrypted_data)
            users_data = json.loads(decrypted_data.decode())

            users = {}
            for user_data in users_data.values():
                user = User.from_dict(user_data)
                users[user.id] = user
            return users
        except Exception as e:
            self.logger.error(f"Failed to load users: {e}")
            return {}

    def _save_users(self):
        """Save users to encrypted storage."""
        users_data = {uid: user.to_dict() for uid, user in self._users.items()}
        json_data = json.dumps(users_data).encode()
        encrypted_data = self._fernet.encrypt(json_data)

        with open(USERS_FILE, 'wb') as f:
            f.write(encrypted_data)

    def _load_api_keys(self) -> Dict[str, APIKey]:
        """Load API keys from encrypted storage."""
        if not API_KEYS_FILE.exists():
            return {}

        try:
            with open(API_KEYS_FILE, 'rb') as f:
                encrypted_data = f.read()
            decrypted_data = self._fernet.decrypt(encrypted_data)
            keys_data = json.loads(decrypted_data.decode())

            api_keys = {}
            for key_data in keys_data.values():
                api_key = APIKey.from_dict(key_data)
                api_keys[api_key.id] = api_key
            return api_keys
        except Exception as e:
            self.logger.error(f"Failed to load API keys: {e}")
            return {}

    def _save_api_keys(self):
        """Save API keys to encrypted storage."""
        keys_data = {kid: key.to_dict() for kid, key in self._api_keys.items()}
        json_data = json.dumps(keys_data).encode()
        encrypted_data = self._fernet.encrypt(json_data)

        with open(API_KEYS_FILE, 'wb') as f:
            f.write(encrypted_data)

    def _get_jwt_secret(self) -> str:
        """Get JWT secret key from environment or generate one."""
        secret = os.getenv("JWT_SECRET_KEY")
        if secret and len(secret) >= JWT_SECRET_KEY_MIN_LENGTH:
            return secret

        # Generate a secure random secret
        if not secret:
            secret = secrets.token_urlsafe(32)
            self.logger.warning("JWT_SECRET_KEY not set, using generated secret. Set environment variable for production.")

        return secret

    def _hash_api_key(self, api_key: str) -> str:
        """Hash API key for storage."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    def _verify_api_key(self, provided_key: str, stored_hash: str) -> bool:
        """Verify API key against stored hash."""
        return secrets.compare_digest(self._hash_api_key(provided_key), stored_hash)

    def create_user(self, username: str, email: str, role: UserRole, password: Optional[str] = None) -> User:
        """Create a new user account."""
        if any(u.username == username for u in self._users.values()):
            raise ValueError(f"User {username} already exists")

        user_id = secrets.token_urlsafe(16)
        hashed_password = pwd_context.hash(password) if password else None

        user = User(
            id=user_id,
            username=username,
            email=email,
            role=role,
            created_at=datetime.now(),
            hashed_password=hashed_password
        )

        self._users[user_id] = user
        self._save_users()

        self.logger.info("user_created", user_id=user_id, username=username, role=role.value)

        # Audit logging
        audit_logger = get_audit_logger()
        audit_logger.log_event(
            AuditEventType.USER_CREATED,
            user_id=user_id,
            resource="user",
            action="create",
            details={"username": username, "email": email, "role": role.value}
        )

        return user

    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        return self._users.get(user_id)

    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        for user in self._users.values():
            if user.username == username:
                return user
        return None

    def update_user_last_login(self, user_id: str):
        """Update user's last login timestamp."""
        if user_id in self._users:
            self._users[user_id].last_login = datetime.now()
            self._save_users()

    def generate_api_key(self, user_id: str, name: str, expiration_days: Optional[int] = None,
                        rate_limit: Optional[int] = None) -> Tuple[str, APIKey]:
        """Generate a new API key for a user."""
        if user_id not in self._users:
            raise ValueError(f"User {user_id} not found")

        # Generate secure random API key
        api_key = secrets.token_urlsafe(API_KEY_LENGTH)
        hashed_key = self._hash_api_key(api_key)

        key_id = secrets.token_urlsafe(16)
        expires_at = None
        if expiration_days:
            expires_at = datetime.now() + timedelta(days=expiration_days)

        api_key_obj = APIKey(
            id=key_id,
            user_id=user_id,
            name=name,
            hashed_key=hashed_key,
            created_at=datetime.now(),
            expires_at=expires_at,
            rate_limit=rate_limit
        )

        self._api_keys[key_id] = api_key_obj
        self._save_api_keys()

        self.logger.info("api_key_created", key_id=key_id, user_id=user_id, name=name)

        # Audit logging
        audit_logger = get_audit_logger()
        audit_logger.log_event(
            AuditEventType.API_KEY_CREATED,
            user_id=user_id,
            resource="api_key",
            action="create",
            details={"key_id": key_id, "name": name, "expiration_days": expiration_days, "rate_limit": rate_limit}
        )

        return api_key, api_key_obj

    def validate_api_key(self, provided_key: str) -> Optional[Tuple[User, APIKey]]:
        """Validate API key and return user and key info."""
        for api_key in self._api_keys.values():
            if api_key.is_active and not api_key.is_expired():
                if self._verify_api_key(provided_key, api_key.hashed_key):
                    user = self._users.get(api_key.user_id)
                    if user and user.is_active:
                        # Update last used timestamp
                        api_key.last_used = datetime.now()
                        self._save_api_keys()

                        # Update user last login
                        self.update_user_last_login(user.id)

                        self.logger.info("api_key_validated", key_id=api_key.id, user_id=user.id)

                        # Audit logging for successful authentication
                        audit_logger = get_audit_logger()
                        audit_logger.log_event(
                            AuditEventType.AUTHENTICATION_SUCCESS,
                            user_id=user.id,
                            resource="api_key",
                            action="validate",
                            details={"key_id": api_key.id, "key_name": api_key.name}
                        )

                        return user, api_key

        self.logger.warning("api_key_validation_failed", key_provided=True)

        # Audit logging for failed authentication
        audit_logger = get_audit_logger()
        audit_logger.log_event(
            AuditEventType.AUTHENTICATION_FAILURE,
            resource="api_key",
            action="validate",
            status="failure",
            details={"reason": "invalid_api_key"}
        )

        return None

    def revoke_api_key(self, key_id: str, user_id: str):
        """Revoke an API key."""
        if key_id not in self._api_keys:
            raise ValueError(f"API key {key_id} not found")

        api_key = self._api_keys[key_id]
        if api_key.user_id != user_id:
            raise ValueError("Unauthorized to revoke this API key")

        api_key.is_active = False
        self._save_api_keys()

        self.logger.info("api_key_revoked", key_id=key_id, user_id=user_id)

        # Audit logging
        audit_logger = get_audit_logger()
        audit_logger.log_event(
            AuditEventType.API_KEY_REVOKED,
            user_id=user_id,
            resource="api_key",
            action="revoke",
            details={"key_id": key_id, "key_name": api_key.name}
        )

    def rotate_api_key(self, key_id: str, user_id: str, name: Optional[str] = None) -> Tuple[str, APIKey]:
        """Rotate an existing API key."""
        if key_id not in self._api_keys:
            raise ValueError(f"API key {key_id} not found")

        old_key = self._api_keys[key_id]
        if old_key.user_id != user_id:
            raise ValueError("Unauthorized to rotate this API key")

        # Revoke old key
        old_key.is_active = False
        self._save_api_keys()

        # Generate new key with same properties
        new_name = name or f"{old_key.name} (rotated)"
        new_key, new_key_obj = self.generate_api_key(
            user_id=user_id,
            name=new_name,
            expiration_days=None,  # Keep existing expiration logic
            rate_limit=old_key.rate_limit
        )

        # Audit logging for key rotation
        audit_logger = get_audit_logger()
        audit_logger.log_event(
            AuditEventType.API_KEY_ROTATED,
            user_id=user_id,
            resource="api_key",
            action="rotate",
            details={"old_key_id": key_id, "old_key_name": old_key.name, "new_key_id": new_key_obj.id, "new_key_name": new_key_obj.name}
        )

        return new_key, new_key_obj

    def list_user_api_keys(self, user_id: str) -> List[APIKey]:
        """List all API keys for a user."""
        return [key for key in self._api_keys.values() if key.user_id == user_id]

    def check_permission(self, user: User, permission: Permission) -> bool:
        """Check if user has a specific permission."""
        user_permissions = ROLE_PERMISSIONS.get(user.role, [])
        has_permission = permission in user_permissions

        # Audit logging for permission checks
        audit_logger = get_audit_logger()
        audit_logger.log_event(
            AuditEventType.PERMISSION_CHECK,
            user_id=user.id,
            resource="permission",
            action="check",
            status="success" if has_permission else "failure",
            details={"permission": permission.value, "user_role": user.role.value, "has_permission": has_permission}
        )

        return has_permission

    def create_jwt_token(self, user: User, expires_delta: Optional[timedelta] = None) -> str:
        """Create JWT token for user."""
        if expires_delta is None:
            expires_delta = timedelta(hours=DEFAULT_JWT_EXPIRATION_HOURS)

        expire = datetime.utcnow() + expires_delta
        to_encode = {
            "sub": user.id,
            "username": user.username,
            "role": user.role.value,
            "exp": expire,
            "iat": datetime.utcnow(),
        }

        encoded_jwt = jwt.encode(to_encode, self._jwt_secret, algorithm="HS256")
        return encoded_jwt

    def validate_jwt_token(self, token: str) -> Optional[User]:
        """Validate JWT token and return user."""
        try:
            payload = jwt.decode(token, self._jwt_secret, algorithms=["HS256"])
            user_id: str = payload.get("sub")
            if user_id is None:
                # Audit logging for failed JWT validation
                audit_logger = get_audit_logger()
                audit_logger.log_event(
                    AuditEventType.AUTHENTICATION_FAILURE,
                    resource="jwt_token",
                    action="validate",
                    status="failure",
                    details={"reason": "missing_user_id"}
                )
                return None

            user = self.get_user(user_id)
            if user is None or not user.is_active:
                # Audit logging for failed JWT validation
                audit_logger = get_audit_logger()
                audit_logger.log_event(
                    AuditEventType.AUTHENTICATION_FAILURE,
                    resource="jwt_token",
                    action="validate",
                    status="failure",
                    details={"reason": "user_not_found_or_inactive", "user_id": user_id}
                )
                return None

            # Update last login
            self.update_user_last_login(user.id)

            # Audit logging for successful JWT validation
            audit_logger = get_audit_logger()
            audit_logger.log_event(
                AuditEventType.AUTHENTICATION_SUCCESS,
                user_id=user.id,
                resource="jwt_token",
                action="validate",
                details={"username": user.username}
            )

            return user
        except JWTError as e:
            # Audit logging for failed JWT validation
            audit_logger = get_audit_logger()
            audit_logger.log_event(
                AuditEventType.AUTHENTICATION_FAILURE,
                resource="jwt_token",
                action="validate",
                status="failure",
                details={"reason": "jwt_decode_error", "error": str(e)}
            )
            return None

    def get_user_rate_limit(self, user_id: str) -> Optional[int]:
        """Get rate limit for user (from their API keys)."""
        user_keys = [k for k in self._api_keys.values() if k.user_id == user_id and k.is_active]
        if user_keys:
            # Return the most restrictive rate limit
            limits = [k.rate_limit for k in user_keys if k.rate_limit is not None]
            return min(limits) if limits else None
        return None


# Global auth manager instance
_auth_manager = None

def get_auth_manager() -> AuthManager:
    """Get global auth manager instance."""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager


# FastAPI Dependencies
def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> User:
    """FastAPI dependency to get current authenticated user."""
    auth_manager = get_auth_manager()

    # Try API key first
    user_key = auth_manager.validate_api_key(credentials.credentials)
    if user_key:
        return user_key[0]

    # Try JWT token
    user = auth_manager.validate_jwt_token(credentials.credentials)
    if user:
        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_permission(permission: Permission):
    """Create dependency for requiring specific permission."""
    def permission_checker(current_user: User = Depends(get_current_user)) -> User:
        auth_manager = get_auth_manager()
        if not auth_manager.check_permission(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions: {permission.value} required"
            )
        return current_user
    return permission_checker


# Convenience dependencies for common roles
require_admin = require_permission(Permission.MANAGE_USERS)
require_operator = require_permission(Permission.SUBMIT_TELEMETRY)
require_analyst = require_permission(Permission.READ_STATUS)


# Pydantic models for API
class UserCreateRequest(BaseModel):
    """Request to create a new user."""
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., regex=r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    role: UserRole
    password: Optional[str] = Field(None, min_length=8)


class UserResponse(BaseModel):
    """User information response."""
    id: str
    username: str
    email: str
    role: UserRole
    created_at: datetime
    last_login: Optional[datetime]
    is_active: bool


class APIKeyCreateRequest(BaseModel):
    """Request to create a new API key."""
    name: str = Field(..., min_length=1, max_length=100)
    expiration_days: Optional[int] = Field(None, ge=1, le=365*2)
    rate_limit: Optional[int] = Field(None, ge=1, le=10000)


class APIKeyResponse(BaseModel):
    """API key information response."""
    id: str
    name: str
    created_at: datetime
    expires_at: Optional[datetime]
    last_used: Optional[datetime]
    is_active: bool
    rate_limit: Optional[int]


class APIKeyCreateResponse(BaseModel):
    """Response when creating a new API key."""
    key: str
    key_info: APIKeyResponse


class LoginRequest(BaseModel):
    """Login request for JWT token."""
    username: str
    password: str


class TokenResponse(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: UserResponse
