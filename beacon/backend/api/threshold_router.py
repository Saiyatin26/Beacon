"""BEACON V2 — Phase 8 Threshold and Advanced Evaluation REST API Router.

Exposes endpoints for creating and managing threshold policies,
resolving evidence-driven thresholds, and executing advanced behavioral evaluation.
"""

import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from auth import User, get_current_active_user
from common.contracts import AdapterRole
from execution.evidence_store import evidence_store
from execution.repository import execution_repository
from reconciliation.models import OracleSet
from reconciliation.persistence import reconciliation_persistence
from threshold.engine import threshold_engine
from threshold.evaluator import advanced_evaluator
from threshold.models import (
    AdvancedEvaluationRequest,
    AdvancedEvaluationResult,
    DifferenceMetric,
    ThresholdPolicy,
    ThresholdResolution,
)
from threshold.persistence import threshold_persistence

logger = logging.getLogger("beacon.api.threshold")

threshold_router = APIRouter(tags=["v2-dynamic-thresholds"])


class ThresholdResolveRequest(BaseModel):
    """Payload to explicitly resolve and freeze a threshold."""
    metric: DifferenceMetric = DifferenceMetric.ABSOLUTE_DIFF
    policy: Optional[ThresholdPolicy] = None
    policy_id: Optional[str] = None
    reference_observations: list[float] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


@threshold_router.post("/api/v2/threshold/policies", response_model=ThresholdPolicy, status_code=status.HTTP_200_OK)
def create_or_update_policy(
    policy: ThresholdPolicy,
    current_user: Optional[User] = Depends(get_current_active_user),
) -> ThresholdPolicy:
    """Creates or updates a versioned threshold policy."""
    try:
        threshold_persistence.save_policy(policy)
        return policy
    except Exception as exc:
        logger.error(f"Error saving threshold policy: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@threshold_router.get("/api/v2/threshold/policies", response_model=list[ThresholdPolicy], status_code=status.HTTP_200_OK)
def list_policies(
    current_user: Optional[User] = Depends(get_current_active_user),
) -> list[ThresholdPolicy]:
    """Lists all registered threshold policies."""
    try:
        return threshold_persistence.list_policies()
    except Exception as exc:
        logger.error(f"Error listing threshold policies: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@threshold_router.get("/api/v2/threshold/policies/{policy_id}", response_model=ThresholdPolicy, status_code=status.HTTP_200_OK)
def get_policy(
    policy_id: str,
    current_user: Optional[User] = Depends(get_current_active_user),
) -> ThresholdPolicy:
    """Retrieves a threshold policy by ID."""
    policy = threshold_persistence.get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail=f"Threshold policy '{policy_id}' not found.")
    return policy


@threshold_router.post("/api/v2/threshold/resolve", response_model=ThresholdResolution, status_code=status.HTTP_200_OK)
def resolve_threshold(
    req: ThresholdResolveRequest,
    current_user: Optional[User] = Depends(get_current_active_user),
) -> ThresholdResolution:
    """Resolves and freezes a deterministic tolerance threshold."""
    policy = req.policy
    if not policy and req.policy_id:
        policy = threshold_persistence.get_policy(req.policy_id)
    if not policy:
        policy = ThresholdPolicy(metric=req.metric)

    try:
        resolution = threshold_engine.resolve_threshold(
            metric=req.metric,
            policy=policy,
            reference_observations=req.reference_observations,
            evidence_ids=req.evidence_ids,
        )
        threshold_persistence.save_resolution(resolution)
        return resolution
    except Exception as exc:
        logger.error(f"Error resolving threshold: {exc}")
        raise HTTPException(status_code=400, detail=str(exc))


@threshold_router.post("/api/v2/evaluation/advanced", response_model=AdvancedEvaluationResult, status_code=status.HTTP_200_OK)
def evaluate_advanced(
    req: AdvancedEvaluationRequest,
    current_user: Optional[User] = Depends(get_current_active_user),
) -> AdvancedEvaluationResult:
    """Executes advanced behavioral evaluation using Phase 7 OracleSet, real Phase 3 evidence, and dynamic thresholds."""
    # 1. Retrieve or construct OracleSet
    oracle_set = None
    if req.oracle_set_id:
        oracle_set = reconciliation_persistence.get_oracle_set(req.oracle_set_id)
    
    if not oracle_set:
        # Fallback to empty draft OracleSet if not found
        oracle_set = OracleSet(
            oracle_set_id=req.oracle_set_id or f"os_{req.application_id}_default",
            application_id=req.application_id,
        )

    # 2. Retrieve policy
    policy = req.custom_policy
    if not policy and req.policy_id:
        policy = threshold_persistence.get_policy(req.policy_id)
    if not policy:
        policy = ThresholdPolicy()

    # 3. Load Real Phase 3 Reference Evidence
    reference_evidence: list[Any] = []
    if req.reference_session_id:
        ref_sess = execution_repository.get_session(req.reference_session_id)
        paired_sess = evidence_store.get_session(req.reference_session_id)
        
        if not ref_sess and not paired_sess:
            raise HTTPException(
                status_code=404,
                detail=f"Reference session '{req.reference_session_id}' not found in execution or evidence store.",
            )

        # Validate Role
        if ref_sess:
            role_val = str(getattr(ref_sess.role, "value", ref_sess.role)).lower()
            if any(t in role_val for t in ("target", "modernized")):
                raise HTTPException(
                    status_code=400,
                    detail=f"Session '{req.reference_session_id}' has role '{ref_sess.role}', expected REFERENCE.",
                )
            results = execution_repository.list_results_for_session(req.reference_session_id)
            reference_evidence.extend(results)

        # Also load from evidence_store if records exist
        ev_records = evidence_store.list_records_for_session(req.reference_session_id)
        if ev_records:
            ref_records = [r for r in ev_records if any(ref_k in str(getattr(r.role, "value", r.role)).lower() for ref_k in ("reference", "legacy"))]
            if ref_records:
                reference_evidence.extend(ref_records)

    # 4. Load Real Phase 3 Target Evidence
    target_evidence: list[Any] = []
    if req.target_session_id:
        tar_sess = execution_repository.get_session(req.target_session_id)
        paired_sess = evidence_store.get_session(req.target_session_id)
        
        if not tar_sess and not paired_sess:
            raise HTTPException(
                status_code=404,
                detail=f"Target session '{req.target_session_id}' not found in execution or evidence store.",
            )

        # Validate Role
        if tar_sess:
            role_val = str(getattr(tar_sess.role, "value", tar_sess.role)).lower()
            if any(r in role_val for r in ("reference", "legacy")):
                raise HTTPException(
                    status_code=400,
                    detail=f"Session '{req.target_session_id}' has role '{tar_sess.role}', expected TARGET.",
                )
            results = execution_repository.list_results_for_session(req.target_session_id)
            target_evidence.extend(results)

        # Also load from evidence_store if records exist
        ev_records = evidence_store.list_records_for_session(req.target_session_id)
        if ev_records:
            tar_records = [r for r in ev_records if any(tar_k in str(getattr(r.role, "value", r.role)).lower() for tar_k in ("target", "modernized"))]
            if tar_records:
                target_evidence.extend(tar_records)

    # 5. Execute evaluation with real loaded evidence
    try:
        result = advanced_evaluator.evaluate(
            application_id=req.application_id,
            oracle_set=oracle_set,
            reference_evidence=reference_evidence,
            target_evidence=target_evidence,
            policy=policy,
        )

        if req.persist:
            threshold_persistence.save_evaluation_result(result)

        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error in advanced evaluation: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@threshold_router.get("/api/v2/evaluation/advanced/{evaluation_id}", response_model=AdvancedEvaluationResult, status_code=status.HTTP_200_OK)
def get_advanced_evaluation(
    evaluation_id: str,
    current_user: Optional[User] = Depends(get_current_active_user),
) -> AdvancedEvaluationResult:
    """Retrieves an advanced evaluation result by ID."""
    result = threshold_persistence.get_evaluation_result(evaluation_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Advanced evaluation run '{evaluation_id}' not found.")
    return result
