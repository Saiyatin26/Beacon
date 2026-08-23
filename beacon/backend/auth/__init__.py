"""Phase 17 — Authentication, RBAC, and Multi-Tenant Security Package."""

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
    ProjectMembership,
    ProjectMembershipInfo,
    ROLE_PERMISSIONS,
    TokenPayload,
    User,
    UserProfileResponse,
    UserRole,
    role_has_permission,
)
from .rate_limiter import auth_rate_limiter
from .repository import auth_repository
from .routes import auth_router
from .security import (
    AuthSecurityError,
    InvalidTokenError,
    TokenExpiredError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

__all__ = [
    "UserRole",
    "Permission",
    "ROLE_PERMISSIONS",
    "role_has_permission",
    "User",
    "ProjectMembership",
    "TokenPayload",
    "LoginRequest",
    "LoginResponse",
    "UserProfileResponse",
    "CreateUserRequest",
    "AssignProjectRoleRequest",
    "ProjectMembershipInfo",
    "auth_repository",
    "auth_rate_limiter",
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_access_token",
    "AuthSecurityError",
    "InvalidTokenError",
    "TokenExpiredError",
    "extract_bearer_token",
    "get_current_user",
    "get_current_active_user",
    "require_project_permission",
    "require_system_admin",
    "auth_router",
]
