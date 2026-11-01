"""Authentication routes: register, login, token refresh, API key management."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.api.auth_models import (
    APIKeyCreate,
    APIKeyResponse,
    TenantCreate,
    TenantResponse,
    TokenPair,
    UserCreate,
    UserLogin,
    UserResponse,
    UserRole,
)
from src.api.auth_service import AuthService

router = APIRouter(tags=["auth"], prefix="/api/auth")


def get_auth_service() -> AuthService:
    from src.api.app import auth_service

    return auth_service


def optional_auth(request: Request):
    """Optional auth dependency - returns AuthContext or None."""
    return getattr(request.state, "auth", None)


def required_auth(request: Request):
    """Required auth dependency - returns AuthContext or raises 401."""
    auth = getattr(request.state, "auth", None)
    if auth is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": 'Bearer realm="financial-copilot"'},
        )
    return auth


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Create a new user account. Optionally specify a tenant_id; otherwise a default tenant is created.",
)
def register(
    data: UserCreate,
    auth_svc: AuthService = Depends(get_auth_service),  # noqa: B008
    current=Depends(optional_auth),  # noqa: B008
):
    if current is not None:
        current.requires_role(UserRole.ADMIN)
    return auth_svc.register_user(
        data, created_by=current.user.user_id if current else None
    )


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Log in and get access tokens",
    description="Authenticate with email and password. Returns access and refresh JWT tokens.",
)
def login(
    data: UserLogin,
    auth_svc: AuthService = Depends(get_auth_service),  # noqa: B008
):
    user = auth_svc.authenticate_user(data)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": 'Bearer realm="financial-copilot"'},
        )
    return auth_svc.create_tokens(user)


@router.post(
    "/token",
    response_model=TokenPair,
    summary="Obtain access tokens (OAuth2 compatibility)",
    include_in_schema=False,
)
def token_endpoint(
    data: UserLogin,
    auth_svc: AuthService = Depends(get_auth_service),  # noqa: B008
):
    return login(data, auth_svc)


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Refresh access token",
    description="Exchange a valid refresh token for a new access token pair.",
)
def refresh(
    refresh_token: str = Query(..., description="Refresh token"),
    auth_svc: AuthService = Depends(get_auth_service),  # noqa: B008
):
    payload = auth_svc.decode_access_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )
    user = auth_svc.get_user_by_id(payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
        )
    return auth_svc.create_tokens(user)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
    description="Return the authenticated user's profile.",
)
def me(current=Depends(required_auth)):  # noqa: B008
    return UserResponse(
        user_id=current.user.user_id,
        email=current.user.email,
        name=current.user.name,
        role=current.user.role,
        tenant_id=current.user.tenant_id,
        is_active=current.user.is_active,
        is_verified=current.user.is_verified,
        created_at=current.user.created_at,
        last_login_at=current.user.last_login_at,
    )


@router.post(
    "/tenants",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tenant",
    description="Create a new organization tenant. Admin only.",
)
def create_tenant(
    data: TenantCreate,
    auth_svc: AuthService = Depends(get_auth_service),  # noqa: B008
    current=Depends(required_auth),  # noqa: B008
):
    current.requires_role(UserRole.ADMIN)
    return auth_svc.create_tenant(data, created_by=current.user.user_id)


@router.get(
    "/tenants",
    response_model=list[TenantResponse],
    summary="List tenants",
    description="List all tenants. Admin only.",
)
def list_tenants(
    auth_svc: AuthService = Depends(get_auth_service),  # noqa: B008
    current=Depends(required_auth),  # noqa: B008
):
    current.requires_role(UserRole.ADMIN)
    with auth_svc.db.get_connection() as conn:
        rows = conn.execute(
            "SELECT tenant_id, name, slug, is_active, created_at, updated_at FROM tenants ORDER BY created_at DESC"
        ).fetchall()
    return [
        TenantResponse(
            tenant_id=r[0],
            name=r[1],
            slug=r[2],
            is_active=bool(r[3]),
            created_at=datetime.fromisoformat(r[4]),
        )
        for r in rows
    ]


@router.post(
    "/keys",
    response_model=APIKeyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an API key",
    description="Create a new API key for the authenticated user. The raw key is returned only once.",
)
def create_api_key(
    data: APIKeyCreate,
    auth_svc: AuthService = Depends(get_auth_service),  # noqa: B008
    current=Depends(required_auth),  # noqa: B008
):
    return auth_svc.create_api_key(
        current.user.user_id, data, created_by=current.user.user_id
    )


@router.get(
    "/keys",
    response_model=list[APIKeyResponse],
    summary="List API keys",
    description="List the authenticated user's API keys (raw keys not included).",
)
def list_api_keys(
    auth_svc: AuthService = Depends(get_auth_service),  # noqa: B008
    current=Depends(required_auth),  # noqa: B008
):
    return auth_svc.list_api_keys(current.user.user_id)


@router.delete(
    "/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
    description="Revoke (deactivate) an API key owned by the authenticated user.",
)
def revoke_api_key(
    key_id: str,
    auth_svc: AuthService = Depends(get_auth_service),  # noqa: B008
    current=Depends(required_auth),  # noqa: B008
):
    auth_svc.revoke_api_key(key_id, current.user.user_id)


@router.get(
    "/users",
    response_model=list[UserResponse],
    summary="List users",
    description="List users in the current tenant. Admin or analyst required.",
)
def list_users(
    auth_svc: AuthService = Depends(get_auth_service),  # noqa: B008
    current=Depends(required_auth),  # noqa: B008
):
    current.requires_role(UserRole.ANALYST)
    with auth_svc.db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT user_id, email, name, role, tenant_id, is_active, is_verified, created_at, updated_at, last_login_at
            FROM users WHERE tenant_id = ? ORDER BY created_at DESC
            """,
            (current.user.tenant_id,),
        ).fetchall()
    return [
        UserResponse(
            user_id=r[0],
            email=r[1],
            name=r[2],
            role=UserRole(r[3]),
            tenant_id=r[4],
            is_active=bool(r[5]),
            is_verified=bool(r[6]),
            created_at=datetime.fromisoformat(r[7]),
            last_login_at=(datetime.fromisoformat(r[9]) if r[9] else None),
        )
        for r in rows
    ]
