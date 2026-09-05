"""BEACON V2 — Phase 3 Paired Execution & Evidence REST API Router.

Exposes endpoints for triggering paired reference/target runs, querying execution sessions,
retrieving structured evidence bundles, examining case-level evidence, and verifying cryptographic
tamper-evident SHA-256 hashes.
"""

import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from application.models import ApplicationSpec
from application.repository import application_repository
from auth import Permission, User, get_current_active_user, require_project_permission
from execution.evidence_models import EvidenceConfiguration
from execution.evidence_store import evidence_store
from execution.paired_models import PairedExecutionRequest, PairedExecutionSession
from execution.paired_runner import paired_execution_coordinator
from execution.readiness import ReadinessConfig

logger = logging.getLogger("beacon.api.paired")

paired_router = APIRouter(prefix="/api/v3/paired", tags=["v3-paired-execution"])


class TriggerPairedRunRequest(BaseModel):
    """Payload to launch a paired reference/target execution session."""
    application_id: str
    custom_inputs: Optional[list[dict[str, Any]]] = None
    input_set_id: Optional[str] = None
    allow_synthetic_inputs: Optional[bool] = None
    evidence_config: Optional[EvidenceConfiguration] = None
    readiness_config_ref: Optional[ReadinessConfig] = None
    readiness_config_target: Optional[ReadinessConfig] = None
    timeout_seconds: float = 30.0
    correlation_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@paired_router.post("/sessions", status_code=status.HTTP_201_CREATED)
def trigger_paired_execution_endpoint(
    req: TriggerPairedRunRequest,
    current_user: User = Depends(require_project_permission(Permission.CERTIFY)),
):
    """Triggers an end-to-end paired reference/target execution against identical canonical inputs."""
    spec = application_repository.get_application(req.application_id)
    if not spec:
        raise HTTPException(status_code=404, detail=f"Application '{req.application_id}' not found.")

    exec_req = PairedExecutionRequest(
        application_id=req.application_id,
        custom_inputs=req.custom_inputs,
        input_set_id=req.input_set_id,
        allow_synthetic_inputs=req.allow_synthetic_inputs,
        evidence_config=req.evidence_config,
        readiness_config_ref=req.readiness_config_ref,
        readiness_config_target=req.readiness_config_target,
        timeout_seconds=req.timeout_seconds,
        correlation_id=req.correlation_id,
        metadata=req.metadata,
    )

    try:
        session, bundle = paired_execution_coordinator.execute_paired(exec_req, spec=spec)
    except Exception as exc:
        logger.error(f"Paired execution failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Paired execution could not be completed", "error": str(exc)},
        )

    return {
        "session": session.model_dump(),
        "bundle_id": bundle.bundle_id,
        "bundle_hash": bundle.bundle_hash,
        "evidence_count": len(bundle.records),
        "is_partial": bundle.is_partial,
        "summary": {
            "total_inputs": session.total_inputs,
            "executed_inputs": session.executed_inputs,
            "status": session.status.value,
        },
    }


@paired_router.get("/sessions")
def list_paired_sessions_endpoint(
    application_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
):
    """Lists recent paired execution sessions."""
    sessions = evidence_store.list_sessions(application_id=application_id, limit=limit)
    return {
        "sessions": [s.model_dump() for s in sessions],
        "count": len(sessions),
    }


@paired_router.get("/sessions/{session_id}")
def get_paired_session_endpoint(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Retrieves session status and per-input correlated execution results."""
    sess = evidence_store.get_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail=f"Paired session '{session_id}' not found.")
    return sess.model_dump()


@paired_router.get("/sessions/{session_id}/bundle")
def get_evidence_bundle_endpoint(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Retrieves the full EvidenceBundle, manifest, and records for a paired session."""
    bundle = evidence_store.get_bundle(session_id)
    if not bundle:
        raise HTTPException(status_code=404, detail=f"Evidence bundle for session '{session_id}' not found.")
    return bundle.model_dump()


@paired_router.get("/sessions/{session_id}/inputs/{input_id}")
def get_paired_input_evidence_endpoint(
    session_id: str,
    input_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Retrieves paired evidence segregated by Reference and Target for a specific input ID."""
    sess = evidence_store.get_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail=f"Paired session '{session_id}' not found.")

    ref_recs, target_recs = evidence_store.get_paired_evidence(session_id, input_id)
    return {
        "session_id": session_id,
        "input_id": input_id,
        "reference_evidence": [r.model_dump() for r in ref_recs],
        "target_evidence": [r.model_dump() for r in target_recs],
        "reference_count": len(ref_recs),
        "target_count": len(target_recs),
    }


@paired_router.get("/evidence/{evidence_id}")
def get_evidence_record_endpoint(
    evidence_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Retrieves a single atomic EvidenceRecord by its unique evidence ID."""
    rec = evidence_store.get_record(evidence_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Evidence record '{evidence_id}' not found.")
    return rec.model_dump()


@paired_router.get("/evidence/{evidence_id}/verify")
def verify_evidence_record_integrity_endpoint(
    evidence_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Performs real-time cryptographic SHA-256 verification of an evidence item."""
    ok, message = evidence_store.verify_evidence_integrity(evidence_id)
    return {
        "evidence_id": evidence_id,
        "verified": ok,
        "message": message,
    }


@paired_router.get("/bundles/{session_id}/verify")
def verify_bundle_integrity_endpoint(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Performs real-time cryptographic SHA-256 verification of an evidence bundle manifest."""
    ok, message = evidence_store.verify_bundle_integrity(session_id)
    return {
        "session_id": session_id,
        "verified": ok,
        "message": message,
    }
