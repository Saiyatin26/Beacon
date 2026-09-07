"""BEACON V2 — Phase 4 Behavioral Evaluation REST API Router.

Provides endpoints to trigger behavioral equivalence evaluations from evidence bundles,
inspect evaluation results across six dimensions, generate Markdown and JSON audit reports,
and query declarative comparison policies.
"""

import logging
from typing import Any, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from auth import Permission, User, get_current_active_user, require_project_permission
from evaluation.engine import behavioral_evaluation_engine
from evaluation.models import BehaviorDimension, EvaluationResult
from evaluation.policies import (
    DEFAULT_COMPARISON_POLICY,
    RELAXED_COMPARISON_POLICY,
    STRICT_COMPARISON_POLICY,
    ComparisonPolicy,
    get_builtin_policy,
    list_builtin_policies,
    resolve_comparison_policy,
)
from evaluation.reporting import generate_json_report, generate_markdown_report
from execution.evidence_models import EvidenceBundle
from execution.evidence_store import evidence_store

logger = logging.getLogger("beacon.api.evaluation")

evaluation_router = APIRouter(prefix="/api/v2/evaluation", tags=["v2-behavioral-evaluation"])

# In-memory store for evaluation results
_evaluations_cache: dict[str, EvaluationResult] = {}


class EvaluateBundleRequest(BaseModel):
    """Payload to evaluate behavioral equivalence from an evidence bundle."""
    bundle_id: Optional[str] = None
    bundle: Optional[EvidenceBundle] = None
    policy_id: Optional[str] = None
    policy: Optional[ComparisonPolicy] = None
    verify_integrity: bool = True
    dimensions: Optional[list[BehaviorDimension]] = None


@evaluation_router.post("/evaluate", response_model=EvaluationResult, status_code=status.HTTP_200_OK)
def evaluate_bundle_endpoint(
    req: EvaluateBundleRequest,
    current_user: User = Depends(require_project_permission(Permission.CERTIFY)),
):
    """Evaluates behavioral equivalence between Reference and Target from an evidence bundle."""
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
            detail="Either 'bundle' (inline) or 'bundle_id' must be provided.",
        )

    # Resolve policy
    chosen_policy = req.policy or req.policy_id or DEFAULT_COMPARISON_POLICY
    resolved_policy = resolve_comparison_policy(chosen_policy)

    try:
        result = behavioral_evaluation_engine.evaluate_bundle(
            bundle=bundle,
            policy=resolved_policy,
            verify_integrity=req.verify_integrity,
            dimensions=req.dimensions,
        )
    except Exception as exc:
        logger.exception("Evaluation execution failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Evaluation failed: {exc}",
        )

    _evaluations_cache[result.evaluation_id] = result
    return result


@evaluation_router.get("/results/{evaluation_id}", response_model=EvaluationResult)
def get_evaluation_result_endpoint(
    evaluation_id: str,
    current_user: User = Depends(require_project_permission(Permission.AUDIT)),
):
    """Retrieves an existing behavioral evaluation result by its ID."""
    result = _evaluations_cache.get(evaluation_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evaluation result '{evaluation_id}' not found.",
        )
    return result


@evaluation_router.get("/results/{evaluation_id}/report")
def get_evaluation_report_endpoint(
    evaluation_id: str,
    format: Literal["markdown", "json"] = "markdown",
    current_user: User = Depends(require_project_permission(Permission.AUDIT)),
):
    """Returns an audit-ready Markdown or JSON report for an evaluation result."""
    result = _evaluations_cache.get(evaluation_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evaluation result '{evaluation_id}' not found.",
        )

    if format == "markdown":
        md_text = generate_markdown_report(result)
        return {
            "evaluation_id": result.evaluation_id,
            "format": "markdown",
            "report": md_text,
        }
    else:
        return generate_json_report(result)


@evaluation_router.get("/policies")
def list_comparison_policies_endpoint(
    current_user: User = Depends(get_current_active_user),
):
    """Lists standard declarative comparison policies available in BEACON."""
    built_in = list_builtin_policies()
    return [
        {
            "policy_id": p.policy_id,
            "description": p.description,
            "float_tolerance": p.float_tolerance,
            "ignore_array_order": p.ignore_array_order,
            "max_latency_ratio": p.max_latency_ratio,
            "policy_hash": p.compute_policy_hash(),
            "policy": p.model_dump(),
        }
        for p in built_in
    ]


@evaluation_router.get("/policies/{policy_id}")
def get_comparison_policy_endpoint(
    policy_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Retrieves full specification and configuration for a comparison policy."""
    policy = get_builtin_policy(policy_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy '{policy_id}' not found. Use GET /policies to list available policies.",
        )
    return {
        "policy_id": policy.policy_id,
        "description": policy.description,
        "float_tolerance": policy.float_tolerance,
        "ignore_array_order": policy.ignore_array_order,
        "max_latency_ratio": policy.max_latency_ratio,
        "policy_hash": policy.compute_policy_hash(),
        "policy": policy.model_dump(),
    }
