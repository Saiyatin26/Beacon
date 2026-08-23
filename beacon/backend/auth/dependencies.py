"""Phase 17 — FastAPI Authentication and Authorization Dependencies.

Provides reusable dependency functions to enforce:
1. Bearer token extraction and cryptographic validation (401 on failure).
2. Active user identity resolution.
3. Multi-tenant project boundary checking (403 on tenant mismatch).
4. Role-Based Access Control (RBAC) permission enforcement.
5. System Admin privilege verification.
"""

import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status

from common.config import settings
from ingestion.audit import AuditAction, audit_logger
from .models import Permission, User, UserRole, role_has_permission
from .repository import auth_repository
from .security import InvalidTokenError, TokenExpiredError, decode_access_token

logger = logging.getLogger(__name__)


def extract_bearer_token(authorization: Optional[str] = None) -> Optional[str]:
    """Extracts raw JWT token from 'Authorization: Bearer <token>' header."""
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    elif len(parts) == 1 and "." in parts[0]:
        # Direct token string passed
        return parts[0]
    return None


async def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Optional[User]:
    """Extracts, verifies, and resolves the current authenticated User.

    - If a valid Bearer token is provided: returns the resolved User.
    - If a token is provided but invalid/expired/tampered: raises HTTP 401.
    - If no token is provided:
        - When settings.auth_required is True: raises HTTP 401.
        - When settings.auth_required is False: returns None (for backward compatibility with legacy tests).
    """
    token = extract_bearer_token(authorization)

    if token:
        try:
            payload = decode_access_token(token)
            user = auth_repository.get_user_by_id(payload.sub)
            if not user or not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User account is deactivated or does not exist",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return user
        except TokenExpiredError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(f"Unexpected token validation error: {exc}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    # No token provided
    auth_required = getattr(settings, "auth_required", False)
    if auth_required:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return None


async def get_current_active_user(
    user: Optional[User] = Depends(get_current_user),
) -> User:
    """Enforces that an active authenticated user is present."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_project_permission(permission: Permission, project_id_param: str = "project_id"):
    """FastAPI dependency factory enforcing project membership and role permission.

    Resolves target project_id from query params, path params, or request JSON body.
    - System Admins hold all permissions across all projects.
    - Project Members are verified against their assigned role permissions.
    - Cross-project requests or insufficient role permissions return HTTP 403 Forbidden.
    """

    async def _dependency(
        request: Request,
        user: Optional[User] = Depends(get_current_user),
    ) -> Optional[User]:
        # 1. Resolve project_id from request
        target_project_id = (
            request.query_params.get(project_id_param)
            or request.path_params.get(project_id_param)
            or request.query_params.get("benchmark_id")
            or request.path_params.get("benchmark_id")
        )

        if not target_project_id:
            cert_id = request.path_params.get("certification_id") or request.path_params.get("run_id")
            if cert_id:
                try:
                    from certification import certification_repository
                    art = certification_repository.get_artifact(cert_id)
                    if art and art.project_id:
                        target_project_id = art.project_id
                except Exception:
                    pass

        if not target_project_id and request.method in ("POST", "PUT", "PATCH"):
            try:
                body_bytes = await request.body()
                if body_bytes:
                    import json
                    body_json = json.loads(body_bytes.decode("utf-8"))
                    if isinstance(body_json, dict):
                        target_project_id = (
                            body_json.get(project_id_param)
                            or body_json.get("benchmark_id")
                        )
            except Exception:
                pass

        if not target_project_id:
            target_project_id = "default_project"

        # 2. Check Authentication
        auth_required = getattr(settings, "auth_required", False)
        if user is None:
            if auth_required:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required to access project resources",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            # Legacy unauthenticated fallback mode
            return None

        # 3. System Admin bypasses project boundary checks
        if user.is_system_admin:
            return user

        # 4. Lookup User's Memberships for the Target Project
        memberships = auth_repository.get_user_memberships(user.user_id)
        # Check direct match or benchmark_ prefix match
        proj_membership = next(
            (
                m for m in memberships
                if m.project_id == target_project_id
                or m.project_id == f"benchmark_{target_project_id}"
                or (target_project_id.startswith("benchmark_") and m.project_id == target_project_id.replace("benchmark_", ""))
            ),
            None,
        )

        if not proj_membership:
            # Audit access denied event
            audit_logger.log(
                project_id=target_project_id,
                action=AuditAction.ACCESS_DENIED,
                status="FAIL",
                details={
                    "user_id": user.user_id,
                    "username": user.username,
                    "reason": "Not a member of project",
                    "target_project_id": target_project_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: User '{user.username}' is not a member of project '{target_project_id}'",
            )

        # 5. Verify Role Permission
        if not role_has_permission(proj_membership.role, permission):
            audit_logger.log(
                project_id=target_project_id,
                action=AuditAction.ACCESS_DENIED,
                status="FAIL",
                details={
                    "user_id": user.user_id,
                    "username": user.username,
                    "role": proj_membership.role.value,
                    "required_permission": permission.value,
                    "reason": "Insufficient role permission",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Role '{proj_membership.role.value}' lacks permission '{permission.value}'",
            )

        return user

    return _dependency


async def require_system_admin(
    user: Optional[User] = Depends(get_current_user),
) -> Optional[User]:
    """Enforces that the current user has SYSTEM_ADMIN privileges."""
    auth_required = getattr(settings, "auth_required", False)
    if user is None:
        if auth_required:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None

    if not user.is_system_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: System administrator privilege required",
        )
    return user
