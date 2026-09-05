"""BEACON V2 — Adapter & Execution REST API Router.

Exposes endpoints for querying registered ImplementationAdapters, executing
live health checks, running pre-flight readiness validations, and triggering
execution sessions.
"""

import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from application.models import ApplicationSpec
from application.repository import application_repository
from auth import Permission, User, get_current_active_user, require_project_permission
from certification.adapter_registry import adapter_registry
from execution.models import AdapterHealth, ExecutionRequest, ExecutionResult, ExecutionSession
from execution.preflight import PreFlightResult, preflight_validator
from execution.repository import execution_repository
from execution.runner import application_executor

logger = logging.getLogger("beacon.api.adapters")

adapter_router = APIRouter(prefix="/api/v2", tags=["v2-adapters-and-executions"])


class ValidateSpecRequest(BaseModel):
    spec: ApplicationSpec


class ExecuteApplicationRequest(BaseModel):
    application_id: str
    target_variant_index: int = 0
    inputs: Optional[list[dict[str, Any]]] = None


@adapter_router.get("/adapters")
def list_adapters_endpoint(
    current_user: User = Depends(get_current_active_user),
):
    """Lists all registered implementation adapters with roles and capabilities."""
    adapters = adapter_registry.list_adapters()
    return {"adapters": adapters, "count": len(adapters)}


@adapter_router.get("/adapters/{adapter_id}")
def get_adapter_endpoint(
    adapter_id: str,
    version: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
):
    """Retrieves adapter details and runs a live operational health check."""
    adp = adapter_registry.get_adapter(adapter_id, version=version)
    if not adp:
        raise HTTPException(status_code=404, detail=f"Adapter '{adapter_id}' not found.")

    health = adp.health_check() if hasattr(adp, "health_check") else None
    reg = adapter_registry.get_registration(adapter_id, version=version)

    return {
        "name": adp.name,
        "version": adp.version,
        "role": str(getattr(adp, "role", "target")),
        "adapter_type": getattr(adp, "adapter_type", type(adp).__name__),
        "implementation_hash": getattr(adp, "implementation_hash", ""),
        "capabilities": getattr(adp, "capabilities", None),
        "health": health.model_dump() if health else None,
        "registration": reg.model_dump() if reg else None,
    }


@adapter_router.post("/adapters/validate")
def validate_spec_readiness(
    req: ValidateSpecRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Performs pre-flight validation on an ApplicationSpec without certifying."""
    result = preflight_validator.validate(req.spec)
    return result.model_dump()


@adapter_router.post("/executions", status_code=status.HTTP_201_CREATED)
def trigger_execution_session(
    req: ExecuteApplicationRequest,
    current_user: User = Depends(require_project_permission(Permission.CERTIFY)),
):
    """Runs an execution session for a registered ApplicationSpec across its adapters."""
    spec = application_repository.get_application(req.application_id)
    if not spec:
        raise HTTPException(status_code=404, detail=f"Application '{req.application_id}' not found.")

    from application.resolver import application_resolver
    ref_adp, target_adp = application_resolver.resolve_adapters(spec)

    test_inputs = req.inputs or [
        inp.values if hasattr(inp, "values") else inp
        for inp in application_resolver.resolve_inputs(spec)
    ]

    # Pre-flight validation
    preflight = application_executor.preflight_check(spec, ref_adp, [target_adp])
    if not preflight.is_ready:
        raise HTTPException(
            status_code=400,
            detail={"message": "Pre-flight validation failed", "errors": preflight.errors},
        )

    # Execute batch against target
    session, results = application_executor.execute_batch(
        adapter=target_adp,
        inputs=test_inputs,
        application_id=spec.application_id,
    )

    return {
        "session": session.model_dump(),
        "results_summary": {
            "total": len(results),
            "succeeded": session.succeeded_count,
            "failed": session.failed_count,
            "timeout": session.timeout_count,
        },
    }


@adapter_router.get("/executions/{session_id}")
def get_execution_session_endpoint(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Retrieves an execution session by session ID."""
    session = execution_repository.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Execution session '{session_id}' not found.")
    return session.model_dump()
