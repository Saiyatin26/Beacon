"""BEACON V2 — Phase 11 Canonical Workflow REST API Router.

Exposes endpoints to execute, inspect, and recover production-grade end-to-end
behavioral equivalence certification workflows.
"""

import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth import (
    Permission,
    User,
    get_current_active_user,
    require_system_admin,
    verify_user_project_permission,
)
from workflow.models import (
    WorkflowRunRequest,
    WorkflowRun,
    WorkflowResult,
    WorkflowState,
    WorkflowErrorCode,
)
from workflow.engine import workflow_engine
from workflow.persistence import workflow_persistence
from workflow.recovery import workflow_recovery

logger = logging.getLogger("beacon.api.workflow")

workflow_router = APIRouter(prefix="/api/v2/workflow", tags=["v2-production-workflow"])


@workflow_router.post(
    "/certify",
    response_model=WorkflowResult,
    status_code=status.HTTP_200_OK,
    summary="Execute canonical V2 behavioral equivalence certification workflow",
)
def certify_workflow(
    req: WorkflowRunRequest,
    current_user: User = Depends(get_current_active_user),
) -> WorkflowResult:
    """Executes the canonical, end-to-end V2 certification workflow with strict authority checks,

    fail-closed guarantees, idempotency, and audit persistence.
    Note: HTTP 200 represents successful workflow processing; the response payload contains
    the authoritative 'certified' boolean and certification 'status'.
    """
    # 1. Enforce RBAC permission
    verify_user_project_permission(current_user, req.application_id, Permission.CERTIFY)

    # Attach authenticated user identity
    req.user_id = current_user.user_id

    try:
        result = workflow_engine.execute_workflow(req)
        return result
    except Exception as exc:
        logger.error(f"Workflow execution unexpected exception for application '{req.application_id}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow execution failed: {str(exc)}",
        )


@workflow_router.get(
    "/runs/{run_id}",
    response_model=WorkflowRun,
    status_code=status.HTTP_200_OK,
    summary="Get workflow execution run status and authoritative links",
)
def get_workflow_run(
    run_id: str,
    current_user: User = Depends(get_current_active_user),
) -> WorkflowRun:
    """Retrieves an authoritative workflow run by ID."""
    run = workflow_persistence.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run '{run_id}' not found.",
        )

    verify_user_project_permission(current_user, run.application_id, Permission.VIEW)
    return run


@workflow_router.get(
    "/runs",
    response_model=list[WorkflowRun],
    status_code=status.HTTP_200_OK,
    summary="List workflow execution runs with optional filtering",
)
def list_workflow_runs(
    application_id: Optional[str] = Query(None, description="Filter by application ID"),
    state: Optional[WorkflowState] = Query(None, description="Filter by workflow state"),
    limit: int = Query(50, ge=1, le=500, description="Max runs to return"),
    current_user: User = Depends(get_current_active_user),
) -> list[WorkflowRun]:
    """Lists workflow runs matching criteria."""
    if application_id:
        verify_user_project_permission(current_user, application_id, Permission.VIEW)

    return workflow_persistence.list_runs(
        application_id=application_id,
        state=state,
        limit=limit,
    )


@workflow_router.post(
    "/recover",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Trigger interrupted workflow recovery scan",
)
def recover_workflows(
    current_user: User = Depends(require_system_admin),
) -> dict[str, Any]:
    """Scans and recovers any non-terminal workflow runs safely."""
    recovered = workflow_recovery.recover_interrupted_workflows()
    return {
        "status": "SUCCESS",
        "recovered_count": len(recovered),
        "recovered_runs": [r.model_dump(mode="json") for r in recovered],
    }
