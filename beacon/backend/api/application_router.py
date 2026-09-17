"""BEACON V2 — Domain-Agnostic Application API Router.

Provides endpoints for registering, querying, and certifying arbitrary applications
independent of pre-packaged benchmark scenarios.
"""

import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from application import (
    ApplicationRegistry,
    ApplicationResolutionError,
    ApplicationResolver,
    ApplicationSpec,
    application_registry,
)
from auth import get_current_active_user, User, Permission, verify_user_project_permission
from certification import (
    CertificationArtifact,
    CertificationContext,
    CertificationPolicy,
    certification_engine,
    certification_repository,
)
from llm.explanation import CertificationExplainer

logger = logging.getLogger("beacon.api.applications")

application_router = APIRouter(prefix="/api/v2/applications", tags=["Applications V2"])
application_resolver = ApplicationResolver()
certification_explainer = CertificationExplainer()


class ApplicationCertifyRequest(BaseModel):
    """Request payload for certifying an application."""
    target_index: int = 0
    sample_count: Optional[int] = None
    custom_inputs: Optional[list[dict[str, Any]]] = None
    policy_min_equivalence_score: float = 0.999
    policy_min_oracle_coverage: float = 0.0
    allow_warnings: bool = False
    explain: bool = False


@application_router.post(
    "",
    response_model=ApplicationSpec,
    status_code=status.HTTP_201_CREATED,
    summary="Register or update an ApplicationSpec",
)
def register_application(
    spec: ApplicationSpec,
    current_user: User = Depends(get_current_active_user),
):
    """Registers an application for behavioral equivalence certification."""
    try:
        registered = application_registry.register_application(spec)
        return registered
    except Exception as exc:
        logger.error(f"Failed to register application: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Application registration failed: {str(exc)}",
        )


@application_router.get(
    "",
    response_model=list[ApplicationSpec],
    summary="List registered applications",
)
def list_applications(
    domain: Optional[str] = Query(None, description="Optional domain filter metadata (e.g. 'agriculture', 'banking')"),
    current_user: User = Depends(get_current_active_user),
):
    """Lists all registered applications, optionally filtered by domain metadata."""
    return application_registry.list_applications(domain=domain)


@application_router.get(
    "/{app_id}",
    response_model=ApplicationSpec,
    summary="Get ApplicationSpec by ID",
)
def get_application(
    app_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Retrieves an application specification by its identifier."""
    app = application_registry.get_application(app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )
    return app


@application_router.delete(
    "/{app_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unregister an application",
)
def delete_application(
    app_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Removes an application from the registry."""
    success = application_registry.unregister_application(app_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )


@application_router.post(
    "/{app_id}/certify",
    summary="Execute behavioral equivalence certification for an application",
)
def certify_application(
    app_id: str,
    req: ApplicationCertifyRequest = ApplicationCertifyRequest(),
    current_user: User = Depends(get_current_active_user),
):
    """Executes deterministic behavioral equivalence certification for an application via Canonical V2 Workflow Engine."""
    from workflow.models import WorkflowRunRequest, WorkflowErrorCode
    from workflow.engine import workflow_engine

    verify_user_project_permission(current_user, app_id, Permission.CERTIFY)

    spec = application_registry.get_application(app_id)
    if not spec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )

    try:
        wf_req = WorkflowRunRequest(
            application_id=app_id,
            target_index=req.target_index,
            custom_inputs=req.custom_inputs,
            policy_min_equivalence_score=req.policy_min_equivalence_score,
            policy_min_oracle_coverage=req.policy_min_oracle_coverage,
            allow_warnings=req.allow_warnings,
            explain=req.explain,
            explanation_mode="deterministic",
            user_id=current_user.user_id,
        )

        result = workflow_engine.execute_workflow(wf_req)

        if result.error_code:
            if result.error_code in (WorkflowErrorCode.APPLICATION_NOT_FOUND,):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Application '{app_id}' not found",
                )
            elif result.error_code in (WorkflowErrorCode.INVALID_INPUT, WorkflowErrorCode.ADAPTER_RESOLUTION_FAILED, WorkflowErrorCode.PREFLIGHT_FAILED):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=result.error_message or "Application resolution or validation failed",
                )
            elif result.error_code in (WorkflowErrorCode.INTERNAL_ERROR, WorkflowErrorCode.PERSISTENCE_FAILED):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=result.error_message or "Internal execution failed",
                )

        response_payload: dict[str, Any] = {
            "application_id": spec.application_id,
            "application_name": spec.name,
            "domain": spec.domain,
            "status": result.status,
            "equivalence_score": result.equivalence_score,
            "artifact_id": result.artifact_id,
            "artifact_hash": result.artifact_hash,
            "unique_input_count": result.unique_input_count,
            "regressions_count": result.regressions_count,
            "regressions": result.regressions[:10] if result.regressions else [],
            "workflow_run_id": result.workflow_run_id,
        }

        if result.explanation:
            response_payload["explanation"] = result.explanation

        return response_payload

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Certification failed for application '{app_id}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Certification execution failed: {str(exc)}",
        )

