"""Phase 17 — Authentication and User Management API Endpoints.

Provides:
1. Rate-limited user login returning JWT bearer tokens.
2. Safe user logout with audit logging.
3. User profile self-inspection (/api/v1/auth/me).
4. Administrator user provisioning and project role management.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from common.config import settings
from ingestion.audit import AuditAction, audit_logger
from .dependencies import (
    extract_bearer_token,
    get_current_active_user,
    get_current_user,
    require_project_permission,
    require_system_admin,
)
from .models import (
    AssignProjectRoleRequest,
    CreateUserRequest,
    LoginRequest,
    LoginResponse,
    Permission,
    ProjectMembershipInfo,
    User,
    UserProfileResponse,
    UserRole,
)
from .rate_limiter import auth_rate_limiter
from .repository import auth_repository
from .security import create_access_token, decode_access_token, verify_password

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/api/v1/auth", tags=["Authentication & Security"])


def _get_client_ip(request: Request) -> str:
    """Extracts client IP safely from request headers or client tuple."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


@auth_router.post("/login", response_model=LoginResponse)
async def login_endpoint(req: LoginRequest, request: Request):
    """Authenticates credentials, generates an HS256 JWT access token, and logs the event."""
    client_ip = _get_client_ip(request)
    rate_key = f"{client_ip}:{req.username.strip().lower()}"

    # 1. Check Rate Limit (Anti-Brute Force)
    allowed, retry_after = auth_rate_limiter.is_allowed(rate_key, max_attempts=10, window_seconds=60)
    if not allowed:
        audit_logger.log(
            project_id="system",
            action=AuditAction.LOGIN_FAILURE,
            status="FAIL",
            details={
                "username": req.username,
                "reason": "Rate limit exceeded",
                "retry_after_seconds": retry_after,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Please retry after {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    # 2. Look up User
    user = auth_repository.get_user_by_username(req.username)

    # 3. Verify Password in constant time
    if not user or not user.is_active or not verify_password(req.password, user.password_hash):
        auth_rate_limiter.record_attempt(rate_key)
        audit_logger.log(
            project_id="system",
            action=AuditAction.LOGIN_FAILURE,
            status="FAIL",
            details={
                "username": req.username,
                "reason": "Invalid credentials",
                "client_ip": client_ip,
            },
        )
        # Safe generic response preventing account enumeration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 4. Successful Authentication
    auth_rate_limiter.reset(rate_key)
    memberships = auth_repository.get_user_memberships(user.user_id)
    token = create_access_token(user, memberships)

    audit_logger.log(
        project_id="system",
        action=AuditAction.LOGIN_SUCCESS,
        status="SUCCESS",
        details={
            "user_id": user.user_id,
            "username": user.username,
            "is_system_admin": user.is_system_admin,
            "client_ip": client_ip,
        },
    )

    expire_minutes = getattr(settings, "jwt_access_token_expire_minutes", 60)
    membership_infos = [
        ProjectMembershipInfo(project_id=m.project_id, role=m.role) for m in memberships
    ]

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in_seconds=expire_minutes * 60,
        user=UserProfileResponse(
            user_id=user.user_id,
            username=user.username,
            full_name=user.full_name,
            email=user.email,
            is_system_admin=user.is_system_admin,
            memberships=membership_infos,
        ),
    )


@auth_router.post("/logout")
async def logout_endpoint(
    request: Request,
    user: User = Depends(get_current_user),
    authorization: Optional[str] = Header(None),
):
    """Logs out the active user session, revokes the token, and creates an audit record."""
    token = extract_bearer_token(authorization)
    if token:
        try:
            payload = decode_access_token(token, verify_exp=False)
            if payload.jti:
                auth_repository.revoke_token(payload.jti, user.user_id, payload.exp)
        except Exception as exc:
            logger.debug(f"Logout token decode note: {exc}")

    audit_logger.log(
        project_id="system",
        action=AuditAction.LOGOUT,
        status="SUCCESS",
        details={
            "user_id": user.user_id,
            "username": user.username,
        },
    )
    return {"status": "logged_out", "message": "Session invalidated and token revoked successfully."}


@auth_router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile(user: User = Depends(get_current_active_user)):
    """Returns the current authenticated user profile and active project memberships."""
    memberships = auth_repository.get_user_memberships(user.user_id)
    membership_infos = [
        ProjectMembershipInfo(project_id=m.project_id, role=m.role) for m in memberships
    ]
    return UserProfileResponse(
        user_id=user.user_id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        is_system_admin=user.is_system_admin,
        memberships=membership_infos,
    )


@auth_router.post("/users", response_model=UserProfileResponse)
async def create_user_endpoint(
    req: CreateUserRequest,
    current_admin: User = Depends(require_system_admin),
):
    """Provisions a new user. Restricted to SYSTEM_ADMIN."""
    existing = auth_repository.get_user_by_username(req.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with username '{req.username}' already exists.",
        )

    user = auth_repository.create_user(
        username=req.username,
        password=req.password,
        full_name=req.full_name,
        email=req.email,
        is_system_admin=req.is_system_admin,
    )
    return UserProfileResponse(
        user_id=user.user_id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        is_system_admin=user.is_system_admin,
        memberships=[],
    )


@auth_router.post("/projects/{project_id}/members")
async def assign_project_member_endpoint(
    project_id: str,
    req: AssignProjectRoleRequest,
    current_user: User = Depends(require_project_permission(Permission.MANAGE_PROJECT)),
):
    """Assigns or updates a user's role in a project tenant."""
    target_user = auth_repository.get_user_by_username(req.username)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{req.username}' not found.",
        )

    membership = auth_repository.assign_user_to_project(
        user_id=target_user.user_id,
        project_id=project_id,
        role=req.role,
    )

    audit_logger.log(
        project_id=project_id,
        action=AuditAction.PROJECT_ACCESS_GRANTED,
        status="SUCCESS",
        details={
            "target_user_id": target_user.user_id,
            "target_username": target_user.username,
            "assigned_role": req.role.value,
            "assigned_by": current_user.username if current_user else "system",
        },
    )

    return {
        "user_id": target_user.user_id,
        "username": target_user.username,
        "project_id": project_id,
        "role": membership.role.value,
        "status": "assigned",
    }
