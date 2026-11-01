"""Authentication service: user registration, login, API keys, session management."""

import logging
from datetime import datetime, timedelta

from src.api.auth_models import (
    APIKeyCreate,
    APIKeyResponse,
    AuthContext,
    PasswordHash,
    Tenant,
    TenantCreate,
    TenantResponse,
    TokenPair,
    TokenService,
    User,
    UserCreate,
    UserLogin,
    UserResponse,
    UserRole,
    generate_api_key,
    hash_api_key,
    now_utc,
    slugify,
    verify_api_key,
)
from src.storage.database import DatabaseStorage

logger = logging.getLogger(__name__)


class AuthService:
    """Identity and access management service backed by SQLite."""

    def __init__(
        self,
        db: DatabaseStorage,
        token_secret: str | None = None,
        access_token_expire_minutes: int = 30,
    ):
        self.db = db
        self.access_token_expire_minutes = access_token_expire_minutes
        self._ensure_tables()
        self.token_service = TokenService(token_secret or self._load_or_create_secret())

    def _load_or_create_secret(self) -> str:
        import os

        secret = os.getenv("AUTH_SECRET_KEY")
        if secret:
            return secret
        # Generate a persistent secret stored in the database metadata table
        try:
            with self.db.get_connection() as conn:
                row = conn.execute(
                    "SELECT value FROM app_metadata WHERE key = 'auth_secret_key'"
                ).fetchone()
                if row:
                    return row[0]
                new_secret = secrets_token_urlsafe(32)
                conn.execute(
                    "INSERT OR REPLACE INTO app_metadata (key, value) VALUES (?, ?)",
                    ("auth_secret_key", new_secret),
                )
                conn.commit()
                return new_secret
        except Exception:  # noqa: BLE001 - graceful degradation
            return secrets_token_urlsafe(32)

    def _ensure_tables(self) -> None:
        from src.storage.migrations import run_migrations

        run_migrations(db_path=self.db.db_path)

    def create_tenant(
        self, data: TenantCreate, created_by: str | None = None
    ) -> TenantResponse:
        tenant_id = f"tenant_{secrets_token_urlsafe(16)}"
        slug = data.slug or slugify(data.name)
        now = now_utc()

        with self.db.get_connection() as conn:
            existing = conn.execute(
                "SELECT tenant_id FROM tenants WHERE slug = ?", (slug,)
            ).fetchone()
            if existing:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=409, detail=f"Tenant slug '{slug}' already exists."
                )
            conn.execute(
                """
                INSERT INTO tenants (tenant_id, name, slug, is_active, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (tenant_id, data.name, slug, now.isoformat(), now.isoformat()),
            )
            conn.commit()

        return TenantResponse(
            tenant_id=tenant_id,
            name=data.name,
            slug=slug,
            is_active=True,
            created_at=now,
        )

    def register_user(
        self, data: UserCreate, created_by: str | None = None
    ) -> UserResponse:
        # Resolve tenant
        tenant_id = data.tenant_id
        if tenant_id is None:
            # Create a default tenant for the user with unique slug
            base_slug = slugify(f"{data.name}-workspace")
            slug = base_slug
            with self.db.get_connection() as conn:
                existing = conn.execute(
                    "SELECT tenant_id FROM tenants WHERE slug = ?", (slug,)
                ).fetchone()
                if existing:
                    slug = f"{base_slug}-{secrets_token_urlsafe(6).lower()}"
            tenant = self.create_tenant(
                TenantCreate(name=f"{data.name}'s Workspace", slug=slug),
                created_by=created_by,
            )
            tenant_id = tenant.tenant_id

        user_id = f"user_{secrets_token_urlsafe(16)}"
        now = now_utc()
        password_hash = PasswordHash.hash(data.password)

        with self.db.get_connection() as conn:
            existing = conn.execute(
                "SELECT user_id FROM users WHERE email = ?", (data.email,)
            ).fetchone()
            if existing:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=409,
                    detail=f"User with email '{data.email}' already exists.",
                )
            conn.execute(
                """
                INSERT INTO users
                (user_id, email, name, role, tenant_id, password_hash, is_active, is_verified, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?)
                """,
                (
                    user_id,
                    data.email,
                    data.name,
                    data.role.value,
                    tenant_id,
                    password_hash,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            conn.commit()

        return UserResponse(
            user_id=user_id,
            email=data.email,
            name=data.name,
            role=data.role,
            tenant_id=tenant_id,
            is_active=True,
            is_verified=False,
            created_at=now,
            last_login_at=None,
        )

    def authenticate_user(self, data: UserLogin) -> User | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT user_id, email, name, role, tenant_id, password_hash, is_active, is_verified, created_at, updated_at, last_login_at
                FROM users WHERE email = ?
                """,
                (data.email,),
            ).fetchone()
            if not row:
                return None
            user = User(
                user_id=row[0],
                email=row[1],
                name=row[2],
                role=UserRole(row[3]),
                tenant_id=row[4],
                is_active=bool(row[6]),
                is_verified=bool(row[7]),
                created_at=datetime.fromisoformat(row[8]),
                updated_at=datetime.fromisoformat(row[9]),
                last_login_at=(datetime.fromisoformat(row[10]) if row[10] else None),
            )
            if not user.is_active:
                return None
            if not PasswordHash.verify(data.password, row[5]):
                return None
            # Update last login
            now = now_utc()
            conn.execute(
                "UPDATE users SET last_login_at = ?, updated_at = ? WHERE user_id = ?",
                (now.isoformat(), now.isoformat(), user.user_id),
            )
            conn.commit()
            user.last_login_at = now
            return user

    def create_tokens(self, user: User) -> TokenPair:
        access_expires = timedelta(minutes=self.access_token_expire_minutes)
        refresh_expires = timedelta(days=7)
        access_token = self.token_service.create_access_token(
            user.user_id, user.tenant_id, access_expires
        )
        refresh_token = self.token_service.create_refresh_token(
            user.user_id, user.tenant_id, refresh_expires
        )
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int(access_expires.total_seconds()),
        )

    def decode_access_token(self, token: str) -> dict | None:
        return self.token_service.decode_token(token)

    def get_user_by_id(self, user_id: str) -> User | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT user_id, email, name, role, tenant_id, password_hash, is_active, is_verified, created_at, updated_at, last_login_at
                FROM users WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if not row:
                return None
            return User(
                user_id=row[0],
                email=row[1],
                name=row[2],
                role=UserRole(row[3]),
                tenant_id=row[4],
                is_active=bool(row[6]),
                is_verified=bool(row[7]),
                created_at=datetime.fromisoformat(row[8]),
                updated_at=datetime.fromisoformat(row[9]),
                last_login_at=(datetime.fromisoformat(row[10]) if row[10] else None),
            )

    def get_tenant_by_id(self, tenant_id: str) -> Tenant | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT tenant_id, name, slug, is_active, created_at, updated_at FROM tenants WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
            if not row:
                return None
            return Tenant(
                tenant_id=row[0],
                name=row[1],
                slug=row[2],
                is_active=bool(row[3]),
                created_at=datetime.fromisoformat(row[4]),
                updated_at=datetime.fromisoformat(row[5]),
            )

    def create_api_key(
        self, user_id: str, data: APIKeyCreate, created_by: str | None = None
    ) -> APIKeyResponse:
        user = self.get_user_by_id(user_id)
        if not user:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="User not found.")
        raw_key, prefix = generate_api_key()
        key_id = f"key_{secrets_token_urlsafe(16)}"
        now = now_utc()
        expires_at = None
        if data.expires_in_days:
            expires_at = (now + timedelta(days=data.expires_in_days)).isoformat()

        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO api_keys
                (key_id, user_id, tenant_id, name, key_hash, prefix, is_active, expires_at, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    key_id,
                    user_id,
                    user.tenant_id,
                    data.name,
                    hash_api_key(raw_key),
                    prefix,
                    expires_at,
                    now.isoformat(),
                    created_by or user_id,
                ),
            )
            conn.commit()

        return APIKeyResponse(
            key_id=key_id,
            name=data.name,
            prefix=prefix,
            key=raw_key,
            is_active=True,
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
            created_at=now,
        )

    def list_api_keys(self, user_id: str) -> list[APIKeyResponse]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT key_id, user_id, tenant_id, name, key_hash, prefix, is_active, expires_at, last_used_at, created_at, created_by
                FROM api_keys WHERE user_id = ? ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        results = []
        for row in rows:
            results.append(
                APIKeyResponse(
                    key_id=row[0],
                    name=row[3],
                    prefix=row[5],
                    key="",  # never return raw key on list
                    is_active=bool(row[6]),
                    expires_at=(datetime.fromisoformat(row[7]) if row[7] else None),
                    created_at=datetime.fromisoformat(row[9]),
                )
            )
        return results

    def revoke_api_key(self, key_id: str, user_id: str) -> None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT user_id FROM api_keys WHERE key_id = ?", (key_id,)
            ).fetchone()
            if not row or row[0] != user_id:
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail="API key not found.")
            conn.execute(
                "UPDATE api_keys SET is_active = 0 WHERE key_id = ?", (key_id,)
            )
            conn.commit()

    def authenticate_api_key(self, raw_key: str) -> AuthContext | None:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT ak.key_id, ak.user_id, ak.tenant_id, ak.name, ak.key_hash, ak.prefix,
                       ak.is_active, ak.expires_at, u.email, u.name, u.role, u.tenant_id,
                       u.is_active, u.is_verified, u.created_at, u.updated_at, u.last_login_at,
                       t.name, t.slug, t.is_active, t.created_at, t.updated_at
                FROM api_keys ak
                JOIN users u ON ak.user_id = u.user_id
                JOIN tenants t ON ak.tenant_id = t.tenant_id
                WHERE ak.prefix = ?
                """,
                (raw_key[:8],),
            ).fetchall()
        for row in rows:
            key_hash = row[4]
            if not verify_api_key(raw_key, key_hash):
                continue
            if not bool(row[6]):
                continue
            if row[7] and datetime.fromisoformat(row[7]) < now_utc():
                continue
            if not bool(row[12]):
                continue
            if not bool(row[20]):
                continue

            user = User(
                user_id=row[1],
                email=row[8],
                name=row[9],
                role=UserRole(row[10]),
                tenant_id=row[11],
                is_active=bool(row[12]),
                is_verified=bool(row[13]),
                created_at=datetime.fromisoformat(row[14]),
                updated_at=datetime.fromisoformat(row[15]),
                last_login_at=(datetime.fromisoformat(row[16]) if row[16] else None),
            )
            tenant = Tenant(
                tenant_id=row[2],
                name=row[17],
                slug=row[18],
                is_active=bool(row[19]),
                created_at=datetime.fromisoformat(row[20]),
                updated_at=datetime.fromisoformat(row[21]),
            )
            # Update last used
            try:
                with self.db.get_connection() as conn2:
                    conn2.execute(
                        "UPDATE api_keys SET last_used_at = ? WHERE key_id = ?",
                        (now_utc().isoformat(), row[0]),
                    )
                    conn2.commit()
            except Exception:  # noqa: BLE001,S110 - graceful degradation
                pass
            return AuthContext(
                user=user,
                tenant=tenant,
                api_key_id=row[0],
                auth_method="api_key",
            )
        return None

    def authenticate_bearer(self, token: str) -> AuthContext | None:
        payload = self.decode_access_token(token)
        if not payload or payload.get("type") != "access":
            return None
        user = self.get_user_by_id(payload["sub"])
        if not user or not user.is_active:
            return None
        tenant = self.get_tenant_by_id(user.tenant_id)
        if not tenant or not tenant.is_active:
            return None
        return AuthContext(
            user=user,
            tenant=tenant,
            auth_method="bearer",
        )


def secrets_token_urlsafe(n: int) -> str:
    import secrets

    return secrets.token_urlsafe(n)
