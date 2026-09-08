"""BEACON V2 — Phase 6 Behavioral Rule / Invariant Discovery REST API Router.

Provides endpoints to trigger automatic rule and invariant discovery from evidence bundles,
inspect discovered candidate rules, and query discovery run history.
"""

import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from auth import Permission, User, get_current_active_user, require_project_permission
from discovery.engine import rule_discovery_engine
from discovery.models import DiscoveryPolicy, DiscoveryResult
from discovery.persistence import discovery_persistence
from evaluation.models import EvaluationResult
from execution.evidence_models import EvidenceBundle
from execution.evidence_store import evidence_store

logger = logging.getLogger("beacon.api.discovery")

discovery_router = APIRouter(prefix="/api/v2/discovery", tags=["v2-rule-discovery"])


class DiscoverRulesRequest(BaseModel):
    """Payload to trigger automatic behavioral rule/invariant discovery."""
    bundle_id: Optional[str] = None
    bundle: Optional[EvidenceBundle] = None
    policy: Optional[DiscoveryPolicy] = None
    phase4_evaluation_id: Optional[str] = None
    phase4_result: Optional[EvaluationResult] = None
    persist: bool = True


@discovery_router.post("", response_model=DiscoveryResult, status_code=status.HTTP_200_OK)
@discovery_router.post("/discover", response_model=DiscoveryResult, status_code=status.HTTP_200_OK)
def discover_rules_endpoint(
    req: DiscoverRulesRequest,
    current_user: User = Depends(require_project_permission(Permission.CERTIFY)),
):
    """Discovers candidate behavioral rules and invariants from an EvidenceBundle."""
    bundle: Optional[EvidenceBundle] = req.bundle

    if bundle is None and req.bundle_id:
        bundle = evidence_store.get_bundle(req.bundle_id)
        if not bundle:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Evidence bundle '{req.bundle_id}' not found.",
            )

    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'bundle' or 'bundle_id' must be provided.",
        )

    try:
        result = rule_discovery_engine.discover_rules(
            bundle=bundle,
            policy=req.policy,
            phase4_result=req.phase4_result,
            persist=req.persist,
        )
        return result
    except Exception as exc:
        logger.error(f"Rule discovery failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Rule discovery execution failed: {exc}",
        )


@discovery_router.get("/{discovery_id}", response_model=DiscoveryResult, status_code=status.HTTP_200_OK)
def get_discovery_result_endpoint(
    discovery_id: str,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Retrieves a persisted DiscoveryResult by ID."""
    result = discovery_persistence.get_discovery_result(discovery_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discovery result '{discovery_id}' not found.",
        )
    return result


@discovery_router.get("", response_model=list[dict[str, Any]], status_code=status.HTTP_200_OK)
def list_discoveries_endpoint(
    application_id: Optional[str] = Query(None, description="Filter by application_id"),
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Lists summary metadata of stored discovery runs."""
    return discovery_persistence.list_discoveries(application_id=application_id)
