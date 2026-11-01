"""Authentication and authorization models for the Financial Filing Research Copilot.

Provides a full identity/tenant system with:
- Users with roles (admin, analyst, viewer)
- Tenants (organizations) for multi-tenant isolation
- API keys per user
- JWT access tokens
- Role-based access control (RBAC)

All tables live alongside the existing storage schema so a single SQLite
database can serve both research data and identity data.
"""

import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRole(str, Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


# Role hierarchy: higher index = more privileges
ROLE_PRECEDENCE: dict[UserRole, int] = {
    UserRole.VIEWER: 0,
    UserRole.ANALYST: 1,
    UserRole.ADMIN: 2,
}


class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: EmailStr
    name: str
    role: UserRole = UserRole.ANALYST
    tenant_id: str
    is_active: bool = True
    is_verified: bool = False
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None


class Tenant(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tenant_id: str
    name: str
    slug: str
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class APIKey(BaseModel):
    model_config = ConfigDict(extra="ignore")
    key_id: str
    user_id: str
    tenant_id: str
    name: str
    key_hash: str  # bcrypt hash of the actual key
    prefix: str  # first 8 chars for display
    is_active: bool = True
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime
    created_by: str | None = None


class TokenPair(BaseModel):
    model_config = ConfigDict(extra="ignore")
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    email: EmailStr
    name: str
    password: str = Field(min_length=8)
    role: UserRole = UserRole.ANALYST
    tenant_id: str | None = None


class UserLogin(BaseModel):
    model_config = ConfigDict(extra="ignore")
    email: EmailStr
    password: str


class APIKeyCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    expires_in_days: int | None = None


class APIKeyResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    key_id: str
    name: str
    prefix: str
    key: str  # only returned on creation
    is_active: bool
    expires_at: datetime | None = None
    created_at: datetime


class UserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    role: UserRole
    tenant_id: str
    is_active: bool
    is_verified: bool
    created_at: datetime
    last_login_at: datetime | None = None


class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    slug: str | None = None


class TenantResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tenant_id: str
    name: str
    slug: str
    is_active: bool
    created_at: datetime


class AuthContext(BaseModel):
    """Populated per-request after successful authentication."""

    model_config = ConfigDict(extra="ignore")
    user: User
    tenant: Tenant
    api_key_id: str | None = None
    auth_method: str  # "bearer", "api_key", "session"

    def has_role(self, role: UserRole) -> bool:
        return ROLE_PRECEDENCE[self.user.role] >= ROLE_PRECEDENCE[role]

    def requires_role(self, role: UserRole) -> None:
        if not self.has_role(role):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=403,
                detail=f"Role '{role.value}' or higher required.",
            )


class PasswordHash:
    """bcrypt-based password hashing with a fallback to PBKDF2 if bcrypt unavailable."""

    @staticmethod
    def hash(password: str) -> str:
        try:
            import bcrypt

            return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode(
                "utf-8"
            )
        except ImportError:
            import hashlib

            salt = secrets.token_hex(16)
            dk = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
            )
            return f"pbkdf2:$pbkdf2-sha256$100000${salt}${dk.hex()}"

    @staticmethod
    def verify(password: str, hashed: str) -> bool:
        try:
            import bcrypt

            return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        except ImportError:
            parts = hashed.split("$")
            if len(parts) != 5 or parts[0] != "pbkdf2":
                return False
            _, algo, iterations, salt, dk_hex = parts
            import hashlib

            dk = hashlib.pbkdf2_hmac(
                algo,
                password.encode("utf-8"),
                salt.encode("utf-8"),
                int(iterations),
            )
            return dk.hex() == dk_hex


class TokenService:
    """JWT token creation and validation with HS256 signing."""

    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        self.secret_key = secret_key
        self.algorithm = algorithm

    def create_access_token(
        self,
        user_id: str,
        tenant_id: str,
        expires_delta: timedelta | None = None,
        token_type: str = "access",
    ) -> str:
        import time

        try:
            import jwt

            now = int(time.time())
            expire = now + int((expires_delta or timedelta(minutes=30)).total_seconds())
            payload = {
                "sub": user_id,
                "tenant_id": tenant_id,
                "iat": now,
                "exp": expire,
                "type": token_type,
            }
            return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        except ImportError:
            # Fallback: signed HMAC token without PyJWT
            import base64
            import hashlib
            import hmac
            import json

            now = int(time.time())
            expire = now + int((expires_delta or timedelta(minutes=30)).total_seconds())
            header = (
                base64.urlsafe_b64encode(
                    json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
                )
                .rstrip(b"=")
                .decode()
            )
            payload_b64 = (
                base64.urlsafe_b64encode(
                    json.dumps(
                        {
                            "sub": user_id,
                            "tenant_id": tenant_id,
                            "iat": now,
                            "exp": expire,
                            "type": token_type,
                        }
                    ).encode()
                )
                .rstrip(b"=")
                .decode()
            )
            signing_input = f"{header}.{payload_b64}".encode()
            sig = (
                base64.urlsafe_b64encode(
                    hmac.new(
                        self.secret_key.encode(), signing_input, hashlib.sha256
                    ).digest()
                )
                .rstrip(b"=")
                .decode()
            )
            return f"{signing_input.decode()}.{sig}"

    def create_refresh_token(
        self,
        user_id: str,
        tenant_id: str,
        expires_delta: timedelta | None = None,
    ) -> str:
        return self.create_access_token(
            user_id,
            tenant_id,
            expires_delta=expires_delta,
            token_type="refresh",
        )

    def decode_token(self, token: str) -> dict[str, Any] | None:
        try:
            import jwt

            try:
                return jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            except (jwt.PyJWTError, ValueError, TypeError):
                return None
        except ImportError:
            # Fallback: verify HMAC signature manually
            import base64
            import hashlib
            import hmac
            import json
            import time

            try:
                parts = token.split(".")
                if len(parts) != 3:
                    return None
                signing_input = f"{parts[0]}.{parts[1]}".encode()
                expected_sig = (
                    base64.urlsafe_b64encode(
                        hmac.new(
                            self.secret_key.encode(), signing_input, hashlib.sha256
                        ).digest()
                    )
                    .rstrip(b"=")
                    .decode()
                )
                if not hmac.compare_digest(expected_sig, parts[2]):
                    return None
                payload_json = base64.urlsafe_b64decode(parts[1] + "==").decode()
                payload = json.loads(payload_json)
                if payload.get("exp", 0) < time.time():
                    return None
                return payload
            except (ValueError, KeyError, TypeError, IndexError):
                return None
        except (ValueError, KeyError, TypeError, IndexError):
            return None


def generate_api_key() -> tuple[str, str]:
    """Generate a new API key. Returns (raw_key, key_prefix)."""
    raw = f"frc_{secrets.token_urlsafe(32)}"
    prefix = raw[:8]
    return raw, prefix


def hash_api_key(key: str) -> str:
    return PasswordHash.hash(key)


def verify_api_key(raw_key: str, key_hash: str) -> bool:
    return PasswordHash.verify(raw_key, key_hash)


def slugify(name: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "tenant"


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)
