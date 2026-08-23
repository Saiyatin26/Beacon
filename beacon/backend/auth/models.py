"""Phase 17 — Authentication, RBAC, and Multi-Tenant Security Domain Models.

Defines:
1. User roles (VIEWER, CERTIFIER, AUDITOR, PROJECT_ADMIN, SYSTEM_ADMIN)
2. Permissions (VIEW, CERTIFY, AUDIT, MANAGE_PROJECT, SYSTEM_OPERATIONS)
3. Domain entities (User, ProjectMembership, TokenPayload)
4. API request and response DTO schemas
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class UserRole(str, Enum):
    """Explicit Role-Based Access Control (RBAC) roles."""
    VIEWER = "VIEWER"
    CERTIFIER = "CERTIFIER"
    AUDITOR = "AUDITOR"
    PROJECT_ADMIN = "PROJECT_ADMIN"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"


class Permission(str, Enum):
    """Atomic authorization permissions."""
    VIEW = "VIEW"
    CERTIFY = "CERTIFY"
    AUDIT = "AUDIT"
    MANAGE_PROJECT = "MANAGE_PROJECT"
    SYSTEM_OPERATIONS = "SYSTEM_OPERATIONS"


# Authoritative role-to-permissions mapping
ROLE_PERMISSIONS: dict[UserRole, set[Permission]] = {
    UserRole.VIEWER: {
        Permission.VIEW,
    },
    UserRole.CERTIFIER: {
        Permission.VIEW,
        Permission.CERTIFY,
    },
    UserRole.AUDITOR: {
        Permission.VIEW,
        Permission.AUDIT,
    },
    UserRole.PROJECT_ADMIN: {
        Permission.VIEW,
        Permission.CERTIFY,
        Permission.AUDIT,
        Permission.MANAGE_PROJECT,
    },
    UserRole.SYSTEM_ADMIN: {
        Permission.VIEW,
        Permission.CERTIFY,
        Permission.AUDIT,
        Permission.MANAGE_PROJECT,
        Permission.SYSTEM_OPERATIONS,
    },
}


def role_has_permission(role: UserRole, permission: Permission) -> bool:
    """Checks whether a given role holds the requested permission."""
    perms = ROLE_PERMISSIONS.get(role, set())
    return permission in perms


class ProjectMembership(BaseModel):
    """Association linking a user to a specific project tenant with an explicit role."""
    user_id: str
    project_id: str
    role: UserRole
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class User(BaseModel):
    """User account entity. Passwords must be hashed; never stored plaintext."""
    user_id: str
    username: str
    password_hash: str
    full_name: str = ""
    email: str = ""
    is_active: bool = True
    is_system_admin: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TokenPayload(BaseModel):
    """Structure encoded into the cryptographic JWT bearer token."""
    sub: str  # user_id
    username: str
    is_system_admin: bool = False
    memberships: dict[str, str] = Field(default_factory=dict)  # project_id -> role string
    iat: int = 0
    exp: int = 0
    token_type: str = "access"


# ==============================================================================
# API Request & Response Schemas
# ==============================================================================

class LoginRequest(BaseModel):
    username: str
    password: str


class ProjectMembershipInfo(BaseModel):
    project_id: str
    role: UserRole


class UserProfileResponse(BaseModel):
    user_id: str
    username: str
    full_name: str
    email: str
    is_system_admin: bool
    memberships: list[ProjectMembershipInfo] = Field(default_factory=list)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    user: UserProfileResponse


class CreateUserRequest(BaseModel):
    username: str
    password: str
    full_name: str = ""
    email: str = ""
    is_system_admin: bool = False


class AssignProjectRoleRequest(BaseModel):
    username: str
    project_id: str
    role: UserRole
