"""Authentication and authorization middleware with full identity/tenant support.

Supports two auth methods:
1. Bearer JWT: Authorization: Bearer <access_token>
2. API Key: Authorization: Api-Key <key>

When AUTH_REQUIRED is set, protected endpoints require authentication.
RBAC is enforced via the `require_role` dependency which can be used
in route dependencies or called directly from an AuthContext.

The auth system is opt-in: when AUTH_REQUIRED is not set, the middleware
attaches identity if credentials are present, and all endpoints remain accessible.
"""

import logging
import os
from collections.abc import Callable

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.api.auth_models import AuthContext, UserRole
from src.api.auth_service import AuthService
from src.storage.database import DatabaseStorage

logger = logging.getLogger(__name__)

# Paths that require authentication when AUTH_REQUIRED is set.
# State-changing and data-reading endpoints are protected; health/metrics are public.
AUTH_REQUIRED_PATHS = {"/api/query", "/api/search", "/api/facts", "/api/companies"}

# Public paths that never require auth.
PUBLIC_PATHS = {
    "/",
    "/health",
    "/api/metrics",
    "/docs",
    "/openapi.json",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/token",
    "/api/auth/refresh",
}

# Paths that require admin role.
ADMIN_REQUIRED_PATHS = {"/api/auth/users", "/api/auth/tenants"}


def _auth_required() -> bool:
    return os.getenv("AUTH_REQUIRED", "").strip().lower() in {"1", "true", "yes", "on"}


def _is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(("/static", "/api/v1/health"))


def _requires_admin(path: str) -> bool:
    return any(path.startswith(p) for p in ADMIN_REQUIRED_PATHS)


class AuthMiddleware(BaseHTTPMiddleware):
    """Full authentication middleware with JWT and API key support."""

    def __init__(self, app, db: DatabaseStorage, auth_service: AuthService):
        super().__init__(app)
        self.db = db
        self.auth_service = auth_service

    async def dispatch(self, request: Request, call_next: Callable):
        # Attach an empty auth context by default.
        request.state.auth = None

        # Extract credentials if provided.
        authorization = request.headers.get("authorization", "")
        auth_context: AuthContext | None = None

        if authorization.startswith("Bearer "):
            token = authorization[len("Bearer ") :].strip()
            auth_context = self.auth_service.authenticate_bearer(token)
        elif authorization.startswith("Api-Key "):
            key = authorization[len("Api-Key ") :].strip()
            auth_context = self.auth_service.authenticate_api_key(key)

        request.state.auth = auth_context

        if not _auth_required():
            return await call_next(request)

        path = request.url.path
        if _is_public_path(path):
            return await call_next(request)

        if auth_context is None:
            logger.warning("Unauthenticated access attempt to %s", path)
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "detail": "Authentication required.",
                    "auth_methods": ["Bearer <access_token>", "Api-Key <key>"],
                },
                headers={"WWW-Authenticate": 'Bearer realm="financial-copilot"'},
            )

        # Admin check
        if _requires_admin(path) and not auth_context.has_role(UserRole.ADMIN):
            logger.warning(
                "Admin access required for %s by user %s",
                path,
                auth_context.user.user_id,
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Admin privileges required."},
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# Route dependency helpers
# ---------------------------------------------------------------------------


def get_current_user(request: Request) -> AuthContext:
    """FastAPI dependency to require an authenticated user."""
    auth = getattr(request.state, "auth", None)
    if auth is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": 'Bearer realm="financial-copilot"'},
        )
    return auth


def require_role(role: UserRole):
    """FastAPI dependency factory to require a minimum role."""

    def _checker(request: Request) -> AuthContext:
        auth = get_current_user(request)
        if not auth.has_role(role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role.value}' required.",
            )
        return auth

    return _checker


def require_admin(request: Request) -> AuthContext:
    return require_role(UserRole.ADMIN)(request)


def require_analyst(request: Request) -> AuthContext:
    return require_role(UserRole.ANALYST)(request)
