"""BEACON V2 — Phase 7 Rule Reconciliation & OracleSet REST API Router.

Provides endpoints to trigger reconciliation between user rules and discovered candidate rules,
inspect generated OracleSets, query conflict logs, and trace complete decision provenance.
"""

import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from auth import Permission, User, require_project_permission
from discovery.models import DiscoveredCandidate, DiscoveryResult
from discovery.persistence import discovery_persistence
from execution.evidence_models import EvidenceBundle
from execution.evidence_store import evidence_store
from reconciliation.engine import rule_reconciliation_engine
from reconciliation.models import (
    OracleRule,
    OracleSet,
    ReconciliationPolicy,
    ReconciliationResult,
    RuleConflict,
)
from reconciliation.persistence import reconciliation_persistence
from rules.models import BusinessRule
from rules.registry import RuleRegistry

logger = logging.getLogger("beacon.api.reconciliation")

reconciliation_router = APIRouter(tags=["v2-rule-reconciliation"])


class ReconcileRequest(BaseModel):
    """Payload to trigger behavioral rule reconciliation and OracleSet generation."""
    application_id: str
    user_rules: Optional[list[BusinessRule]] = None
    discovered_candidates: Optional[list[DiscoveredCandidate]] = None
    discovery_id: Optional[str] = None
    bundle_id: Optional[str] = None
    policy: Optional[ReconciliationPolicy] = None
    session_id: Optional[str] = None
    version: int = 1
    persist: bool = True


@reconciliation_router.post("/api/v2/reconciliation/reconcile", response_model=ReconciliationResult, status_code=status.HTTP_200_OK)
@reconciliation_router.post("/api/v2/reconciliation", response_model=ReconciliationResult, status_code=status.HTTP_200_OK)
def reconcile_rules_endpoint(
    req: ReconcileRequest,
    current_user: User = Depends(require_project_permission(Permission.CERTIFY)),
):
    """Reconciles user-defined rules and discovered candidate rules into an OracleSet."""
    candidates = list(req.discovered_candidates or [])
    if not candidates and req.discovery_id:
        disc_res = discovery_persistence.get_discovery_result(req.discovery_id)
        if disc_res:
            candidates = list(disc_res.candidates)

    user_rules = list(req.user_rules or [])

    evidence_bundle: Optional[EvidenceBundle] = None
    if req.bundle_id:
        evidence_bundle = evidence_store.get_bundle(req.bundle_id)

    try:
        result = rule_reconciliation_engine.reconcile(
            application_id=req.application_id,
            user_rules=user_rules,
            discovered_candidates=candidates,
            evidence_bundle=evidence_bundle,
            policy=req.policy,
            session_id=req.session_id,
            version=req.version,
            persist=req.persist,
        )
        return result
    except Exception as exc:
        logger.error(f"Rule reconciliation failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Rule reconciliation execution failed: {exc}",
        )


@reconciliation_router.get("/api/v2/reconciliation/runs/{run_id}", response_model=ReconciliationResult, status_code=status.HTTP_200_OK)
def get_reconciliation_run_endpoint(
    run_id: str,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Retrieves a persisted ReconciliationResult by run ID."""
    result = reconciliation_persistence.get_reconciliation_result(run_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation run '{run_id}' not found.",
        )
    return result


@reconciliation_router.get("/api/v2/reconciliation/runs", response_model=list[dict[str, Any]], status_code=status.HTTP_200_OK)
def list_reconciliation_runs_endpoint(
    application_id: Optional[str] = Query(None, description="Filter by application_id"),
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Lists summary metadata of stored reconciliation runs."""
    return reconciliation_persistence.list_reconciliation_runs(application_id=application_id)


@reconciliation_router.get("/api/v2/oraclesets/{oracle_set_id}", response_model=OracleSet, status_code=status.HTTP_200_OK)
def get_oracle_set_endpoint(
    oracle_set_id: str,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Retrieves a persisted OracleSet by ID."""
    oset = reconciliation_persistence.get_oracle_set(oracle_set_id)
    if not oset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OracleSet '{oracle_set_id}' not found.",
        )
    return oset


@reconciliation_router.get("/api/v2/oraclesets", response_model=list[dict[str, Any]], status_code=status.HTTP_200_OK)
def list_oracle_sets_endpoint(
    application_id: Optional[str] = Query(None, description="Filter by application_id"),
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Lists summary metadata of stored OracleSets."""
    return reconciliation_persistence.list_oracle_sets(application_id=application_id)


@reconciliation_router.get("/api/v2/reconciliation/conflicts/{run_id}", response_model=list[RuleConflict], status_code=status.HTTP_200_OK)
def get_reconciliation_conflicts_endpoint(
    run_id: str,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Retrieves conflict records for a specific reconciliation run."""
    result = reconciliation_persistence.get_reconciliation_result(run_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation run '{run_id}' not found.",
        )
    return result.conflicts


@reconciliation_router.get("/api/v2/reconciliation/provenance/{oracle_set_id}/{rule_id}", response_model=dict[str, Any], status_code=status.HTTP_200_OK)
def get_rule_provenance_endpoint(
    oracle_set_id: str,
    rule_id: str,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Retrieves detailed provenance and decision trace graph for a specific Oracle rule."""
    oset = reconciliation_persistence.get_oracle_set(oracle_set_id)
    if not oset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OracleSet '{oracle_set_id}' not found.",
        )
    matching_rule = next((r for r in oset.rules if r.rule_id == rule_id), None)
    if not matching_rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rule '{rule_id}' not found in OracleSet '{oracle_set_id}'.",
        )
    return {
        "rule_id": matching_rule.rule_id,
        "oracle_set_id": oracle_set_id,
        "fingerprint": matching_rule.fingerprint,
        "source": matching_rule.source.value,
        "source_rule_ids": matching_rule.source_rule_ids,
        "source_candidate_ids": matching_rule.source_candidate_ids,
        "candidate_fingerprints": matching_rule.candidate_fingerprints,
        "evidence_ids": matching_rule.evidence_ids,
        "input_ids": matching_rule.input_ids,
        "confidence": matching_rule.confidence,
        "support_count": matching_rule.support_count,
        "decision_trace": [dt.model_dump() for dt in matching_rule.decision_trace],
    }
