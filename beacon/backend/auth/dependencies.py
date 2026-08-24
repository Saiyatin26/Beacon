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
from operations.logging_config import current_project_id, current_user_id
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
) -> User:
    """Extracts, verifies, and resolves the current authenticated User.
    Mandatory for all protected endpoints.
    - If a valid Bearer token is provided: returns the resolved User.
    - If no token is provided: raises HTTP 401 Unauthorized.
    - If a token is provided but invalid/expired/tampered/revoked: raises HTTP 401 Unauthorized.
    """
    token = extract_bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(token)
        user = auth_repository.get_user_by_id(payload.sub)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is deactivated or does not exist",
                headers={"WWW-Authenticate": "Bearer"},
            )
        current_user_id.set(user.user_id)
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


async def get_current_active_user(
    user: User = Depends(get_current_user),
) -> User:
    """Enforces that an active authenticated user is present."""
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_project_permission(permission: Permission, project_id_param: str = "project_id"):
    """FastAPI dependency factory enforcing authoritative project membership and role permissions.

    Authoritatively resolves target project_id from:
    1. Authoritative backend resource (CertificationArtifact, CustomDataset, CertificationJob) if resource ID is present.
    2. Request query parameters or path parameters.
    3. Request JSON body.
    
    Security rules:
    - Never uses a fallback such as 'default_project' when the project cannot be resolved.
    - System Admins hold universal permissions across all projects.
    - Project Members are verified against their assigned role permissions in the authoritative target project.
    - If the project cannot be resolved or membership is missing, access is denied (HTTP 403 Forbidden).
    """

    async def _dependency(
        request: Request,
        user: User = Depends(get_current_user),
    ) -> User:
        # 1. System Admin bypasses project boundary checks
        if user.is_system_admin:
            return user

        # 2. Authoritative Resource-First Resolution:
        # Check path and query params for resource identifiers
        cert_id = (
            request.path_params.get("certification_id")
            or request.path_params.get("run_id")
            or request.query_params.get("certification_id")
            or request.query_params.get("run_id")
        )
        dataset_id = (
            request.path_params.get("dataset_id")
            or request.query_params.get("dataset_id")
        )
        job_id = (
            request.path_params.get("job_id")
            or request.query_params.get("job_id")
        )

        target_project_id: Optional[str] = None

        if cert_id:
            try:
                from certification import certification_repository
                art = certification_repository.get_artifact(cert_id)
                if art and art.project_id:
                    target_project_id = art.project_id
            except Exception:
                pass
            if not target_project_id:
                try:
                    from api.main import local_store
                    r = local_store.get_run(cert_id)
                    if r and r.get("project_id"):
                        target_project_id = r.get("project_id")
                except Exception:
                    pass
        elif dataset_id:
            try:
                from ingestion.dataset_registry import user_dataset_registry
                ds = user_dataset_registry.get_dataset_metadata(dataset_id)
                if ds and ds.project_id:
                    target_project_id = ds.project_id
            except Exception:
                pass
        elif job_id:
            try:
                from operations import certification_job_tracker
                job = certification_job_tracker.get_job(job_id)
                if job and job.project_id:
                    target_project_id = job.project_id
            except Exception:
                pass

        # 3. Direct project / benchmark parameters from query / path
        if not target_project_id:
            target_project_id = (
                request.query_params.get(project_id_param)
                or request.path_params.get(project_id_param)
                or request.query_params.get("benchmark_id")
                or request.path_params.get("benchmark_id")
            )

        # 4. Resolve from JSON request body if present
        if not target_project_id and request.method in ("POST", "PUT", "PATCH"):
            try:
                body_bytes = await request.body()
                if body_bytes:
                    import json
                    body_json = json.loads(body_bytes.decode("utf-8"))
                    if isinstance(body_json, dict):
                        b_cert_id = body_json.get("certification_id") or body_json.get("run_id")
                        b_ds_id = body_json.get("dataset_id")
                        b_job_id = body_json.get("job_id")

                        if b_cert_id:
                            try:
                                from certification import certification_repository
                                art = certification_repository.get_artifact(b_cert_id)
                                if art and art.project_id:
                                    target_project_id = art.project_id
                            except Exception:
                                pass
                        elif b_ds_id:
                            try:
                                from ingestion.dataset_registry import user_dataset_registry
                                ds = user_dataset_registry.get_dataset_metadata(b_ds_id)
                                if ds and ds.project_id:
                                    target_project_id = ds.project_id
                            except Exception:
                                pass
                        elif b_job_id:
                            try:
                                from operations import certification_job_tracker
                                job = certification_job_tracker.get_job(b_job_id)
                                if job and job.project_id:
                                    target_project_id = job.project_id
                            except Exception:
                                pass

                        if not target_project_id:
                            target_project_id = (
                                body_json.get(project_id_param)
                                or body_json.get("benchmark_id")
                            )
            except Exception:
                pass

        # 5. Strict rejection if target project cannot be resolved (NO DEFAULT FALLBACK)
        if not target_project_id:
            audit_logger.log(
                project_id="UNKNOWN",
                action=AuditAction.ACCESS_DENIED,
                status="FAIL",
                details={
                    "user_id": user.user_id,
                    "username": user.username,
                    "reason": "Target project could not be determined",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Target project could not be resolved or resource does not exist.",
            )

        # 6. Lookup User's Memberships for the Target Project
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

        # 7. Verify Role Permission
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

        if target_project_id:
            current_project_id.set(target_project_id)
        return user

    return _dependency


async def require_system_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Enforces that the current user has SYSTEM_ADMIN privileges."""
    if not user.is_system_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: System administrator privilege required",
        )
    return user
