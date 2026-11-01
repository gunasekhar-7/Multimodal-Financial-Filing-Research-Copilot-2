import os
import tempfile
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.auth_models import (
    APIKeyCreate,
    PasswordHash,
    TokenService,
    UserCreate,
    UserLogin,
    UserRole,
    generate_api_key,
    hash_api_key,
    now_utc,
    verify_api_key,
)
from src.api.auth_service import AuthService
from src.storage.database import DatabaseStorage


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = DatabaseStorage(db_path=db_path)
    yield db
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


@pytest.fixture
def auth_service(temp_db):
    return AuthService(
        db=temp_db, token_secret="test-secret-key-1234567890-32bytes-secure"
    )


class TestAuthPrimitives:
    def test_password_hashing(self):
        password = "SecurePassword123!"
        hashed = PasswordHash.hash(password)
        assert hashed != password
        assert PasswordHash.verify(password, hashed) is True
        assert PasswordHash.verify("WrongPassword", hashed) is False

    def test_api_key_generation_and_hashing(self):
        raw_key, prefix = generate_api_key()
        assert len(prefix) == 8
        assert raw_key.startswith(prefix)
        key_hash = hash_api_key(raw_key)
        assert verify_api_key(raw_key, key_hash) is True
        assert verify_api_key("wrong_key_12345678", key_hash) is False

    def test_jwt_token_service(self):
        service = TokenService(
            secret_key="my-super-secret-key-that-is-at-least-32-bytes-long"
        )
        token = service.create_access_token(
            user_id="user_123",
            tenant_id="tenant_abc",
            expires_delta=timedelta(minutes=15),
        )
        assert isinstance(token, str)
        payload = service.decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user_123"
        assert payload["tenant_id"] == "tenant_abc"
        assert payload["type"] == "access"

    def test_jwt_refresh_token(self):
        service = TokenService(
            secret_key="my-super-secret-key-that-is-at-least-32-bytes-long"
        )
        refresh = service.create_refresh_token(
            user_id="user_123",
            tenant_id="tenant_abc",
        )
        assert isinstance(refresh, str)
        payload = service.decode_token(refresh)
        assert payload is not None
        assert payload["sub"] == "user_123"
        assert payload["type"] == "refresh"

    def test_jwt_expired_token(self):
        service = TokenService(
            secret_key="my-super-secret-key-that-is-at-least-32-bytes-long"
        )
        expired_token = service.create_access_token(
            user_id="user_123",
            tenant_id="tenant_abc",
            expires_delta=timedelta(seconds=-10),
        )
        payload = service.decode_token(expired_token)
        assert payload is None


class TestAuthService:
    def test_register_user_creates_tenant_and_user(self, auth_service):
        user = auth_service.register_user(
            UserCreate(
                email="analyst@example.com",
                name="Research Analyst",
                password="Password123!",
                role=UserRole.ANALYST,
            )
        )
        assert user.user_id.startswith("user_")
        assert user.email == "analyst@example.com"
        assert user.tenant_id.startswith("tenant_")
        assert user.role == UserRole.ANALYST

        # Verify tenant was created
        tenant = auth_service.get_tenant_by_id(user.tenant_id)
        assert tenant is not None
        assert (
            "workspace" in tenant.name.lower()
            or "research analyst" in tenant.name.lower()
        )

    def test_register_duplicate_email_raises_conflict(self, auth_service):
        data = UserCreate(
            email="dup@example.com",
            name="Duplicate User",
            password="Password123!",
        )
        auth_service.register_user(data)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            auth_service.register_user(data)
        assert exc_info.value.status_code == 409

    def test_user_authentication_flow(self, auth_service):
        email = "auth_test@example.com"
        password = "ValidPassword123!"
        auth_service.register_user(
            UserCreate(email=email, name="Auth Test", password=password)
        )

        # Successful login
        user = auth_service.authenticate_user(UserLogin(email=email, password=password))
        assert user is not None
        assert user.email == email

        # Bad password
        bad_user = auth_service.authenticate_user(
            UserLogin(email=email, password="WrongPassword!")
        )
        assert bad_user is None

        # Unknown email
        no_user = auth_service.authenticate_user(
            UserLogin(email="nonexistent@example.com", password=password)
        )
        assert no_user is None

    def test_create_and_validate_tokens(self, auth_service):
        user = auth_service.register_user(
            UserCreate(
                email="jwt_user@example.com",
                name="JWT User",
                password="Password123!",
            )
        )
        tokens = auth_service.create_tokens(user)
        assert tokens.access_token != ""
        assert tokens.refresh_token != ""
        assert tokens.token_type.lower() == "bearer"
        assert tokens.expires_in > 0

        # Authenticate bearer token
        auth_ctx = auth_service.authenticate_bearer(tokens.access_token)
        assert auth_ctx is not None
        assert auth_ctx.user.user_id == user.user_id
        assert auth_ctx.tenant.tenant_id == user.tenant_id

    def test_api_key_lifecycle(self, auth_service):
        user = auth_service.register_user(
            UserCreate(
                email="key_user@example.com",
                name="Key User",
                password="Password123!",
            )
        )

        key_resp = auth_service.create_api_key(
            user_id=user.user_id,
            data=APIKeyCreate(name="Production Key", expires_in_days=30),
        )
        assert key_resp.key != ""
        assert key_resp.prefix == key_resp.key[:8]

        # Authenticate via key
        ctx = auth_service.authenticate_api_key(key_resp.key)
        assert ctx is not None
        assert ctx.user.user_id == user.user_id
        assert ctx.auth_method == "api_key"

        # List keys (raw key should be redacted)
        keys = auth_service.list_api_keys(user.user_id)
        assert len(keys) == 1
        assert keys[0].key == ""
        assert keys[0].name == "Production Key"

        # Revoke key
        auth_service.revoke_api_key(key_resp.key_id, user.user_id)
        revoked_ctx = auth_service.authenticate_api_key(key_resp.key)
        assert revoked_ctx is None

    def test_bearer_token_authentication(self, auth_service):
        user = auth_service.register_user(
            UserCreate(
                email="token_user@example.com",
                name="Token User",
                password="Password123!",
            )
        )

        tokens = auth_service.create_tokens(user)
        assert tokens.access_token is not None

        ctx = auth_service.authenticate_bearer(tokens.access_token)
        assert ctx is not None
        assert ctx.user.user_id == user.user_id
        assert ctx.auth_method == "bearer"


class TestAuthAPIEndpoints:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_auth_registration_and_login_flow(self, client):
        reg_payload = {
            "email": f"api_user_{now_utc().timestamp()}@example.com",
            "name": "API User",
            "password": "StrongPassword123!",
            "role": "analyst",
        }
        res = client.post("/api/auth/register", json=reg_payload)
        assert res.status_code in (200, 201)
        user_data = res.json()
        assert user_data["email"] == reg_payload["email"]

        # Login to obtain tokens
        login_res = client.post(
            "/api/auth/token",
            json={"email": reg_payload["email"], "password": reg_payload["password"]},
        )
        assert login_res.status_code == 200
        token_data = login_res.json()
        assert "access_token" in token_data
        token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]

        # Access /api/auth/me with Bearer token
        me_res = client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert me_res.status_code == 200
        assert me_res.json()["email"] == reg_payload["email"]

        # Refresh token endpoint works
        ref_res = client.post(f"/api/auth/refresh?refresh_token={refresh_token}")
        assert ref_res.status_code == 200
        new_tokens = ref_res.json()
        assert "access_token" in new_tokens

        # Attempting to refresh with an access token is rejected
        bad_ref = client.post(f"/api/auth/refresh?refresh_token={token}")
        assert bad_ref.status_code == 401

    def test_auth_required_middleware_permits_login(self, client, monkeypatch):
        # When AUTH_REQUIRED=true, login and public paths remain accessible
        monkeypatch.setenv("AUTH_REQUIRED", "true")

        # Public login attempt works (returns 401 only for bad credentials, not middleware blocking)
        res = client.post(
            "/api/auth/login",
            json={"email": "nonexistent@example.com", "password": "wrong"},
        )
        # Should be handled by login route returning 401 "Invalid email or password"
        assert res.status_code == 401
        assert res.json()["detail"] == "Invalid email or password."

        # Protected data route is blocked by AuthMiddleware
        query_res = client.post(
            "/api/query",
            json={"question": "What was Apple revenue?", "ticker": "AAPL"},
        )
        assert query_res.status_code == 401
        assert "Authentication required." in query_res.json()["detail"]
