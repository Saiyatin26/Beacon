"""BEACON V2 — Phase 5 Controlled Mode & Business Rules REST API Router.

Provides endpoints to manage business rules (CRUD, versioning, validation) and execute
Controlled Mode evaluations combining user-defined rules, Phase 3 evidence, and Phase 4 results
with durable audit persistence.
"""

from datetime import datetime, timezone
import json
import logging
import sqlite3
from typing import Any, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from auth import Permission, User, get_current_active_user, require_project_permission
from evaluation.models import EvaluationResult
from execution.evidence_models import EvidenceBundle
from execution.evidence_store import evidence_store
from rules.engine import controlled_assessment_engine
from rules.models import (
    BusinessRule,
    ControlledEvaluationResult,
    RuleStatus,
)
from rules.registry import RulePersistenceError, rule_registry
from rules.validator import rule_validator

logger = logging.getLogger("beacon.api.controlled")

controlled_router = APIRouter(prefix="/api/v2", tags=["v2-controlled-business-rules"])

# In-memory cache for controlled evaluation results (complemented by SQLite persistence)
_controlled_evaluations_cache: dict[str, ControlledEvaluationResult] = {}
_EVAL_DB_PATH = "beacon.sqlite3"


class EvaluateControlledRequest(BaseModel):
    """Payload to trigger a Controlled Mode rule evaluation."""
    rule_ids: Optional[list[str]] = None
    rules: Optional[list[BusinessRule]] = None
    bundle_id: Optional[str] = None
    bundle: Optional[EvidenceBundle] = None
    phase4_evaluation_id: Optional[str] = None
    phase4_result: Optional[EvaluationResult] = None


class ValidateRuleRequest(BaseModel):
    """Payload to statically validate a candidate business rule."""
    rule: Union[BusinessRule, dict[str, Any]]


class UpdateRuleRequest(BaseModel):
    """Payload to update an existing business rule."""
    name: Optional[str] = None
    description: Optional[str] = None
    condition: Optional[Any] = None
    expected_behavior: Optional[Any] = None
    severity: Optional[Any] = None
    status: Optional[RuleStatus] = None
    metadata: Optional[dict[str, Any]] = None


# ==============================================================================
# Rule Management Endpoints
# ==============================================================================

@controlled_router.post("/rules", response_model=BusinessRule, status_code=status.HTTP_201_CREATED)
def create_rule_endpoint(
    rule: BusinessRule,
    current_user: User = Depends(require_project_permission(Permission.CERTIFY)),
):
    """Registers a new user-defined BusinessRule in the repository."""
    is_valid, errors = rule_validator.validate_rule(rule)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rule validation failed: {'; '.join(errors)}",
        )
    try:
        return rule_registry.register_rule(rule)
    except RulePersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database persistence failure: {exc}",
        )


@controlled_router.get("/rules", response_model=list[BusinessRule])
def list_rules_endpoint(
    status: Optional[RuleStatus] = None,
    scope: Optional[str] = None,
    latest_only: bool = Query(True, description="Return only the latest version of each rule"),
    current_user: User = Depends(get_current_active_user),
):
    """Lists registered business rules matching filters."""
    return rule_registry.list_rules(status=status, scope=scope, latest_only=latest_only)


@controlled_router.get("/rules/{rule_id}", response_model=BusinessRule)
def get_rule_endpoint(
    rule_id: str,
    version: Optional[int] = Query(None, description="Optional specific version number"),
    current_user: User = Depends(get_current_active_user),
):
    """Retrieves a business rule by its ID and optional version."""
    rule = rule_registry.get_rule(rule_id, version=version)
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rule '{rule_id}' (version={version or 'latest'}) not found.",
        )
    return rule


@controlled_router.put("/rules/{rule_id}", response_model=BusinessRule)
def update_rule_endpoint(
    rule_id: str,
    req: UpdateRuleRequest,
    current_user: User = Depends(require_project_permission(Permission.CERTIFY)),
):
    """Updates a business rule by creating a new version with preserved history."""
    try:
        updated = rule_registry.update_rule(
            rule_id=rule_id,
            name=req.name,
            description=req.description,
            condition=req.condition,
            expected_behavior=req.expected_behavior,
            severity=req.severity,
            status=req.status,
            metadata=req.metadata,
        )
        return updated
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rule '{rule_id}' not found.",
        )
    except RulePersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database persistence failure: {exc}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Update failed: {exc}",
        )


@controlled_router.post("/rules/validate")
def validate_rule_endpoint(
    req: ValidateRuleRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Statically validates a candidate business rule syntax and semantics."""
    is_valid, errors = rule_validator.validate_rule(req.rule)
    return {
        "is_valid": is_valid,
        "errors": errors,
    }


# ==============================================================================
# Controlled Mode Evaluation Endpoints
# ==============================================================================

@controlled_router.post("/controlled/evaluate", response_model=ControlledEvaluationResult)
def evaluate_controlled_endpoint(
    req: EvaluateControlledRequest,
    current_user: User = Depends(require_project_permission(Permission.CERTIFY)),
):
    """Evaluates business rule compliance across Reference and Target using Phase 3 evidence."""
    # 1. Resolve EvidenceBundle
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

    # 2. Resolve Rules
    rules_to_evaluate: list[BusinessRule] = []
    if req.rules:
        rules_to_evaluate.extend(req.rules)
    elif req.rule_ids:
        for r_id in req.rule_ids:
            r = rule_registry.get_rule(r_id)
            if not r:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Rule '{r_id}' not found in registry.",
                )
            rules_to_evaluate.append(r)
    else:
        # Default to all active rules in registry
        rules_to_evaluate = rule_registry.list_rules(status=RuleStatus.ACTIVE)

    if not rules_to_evaluate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No rules provided or found for evaluation.",
        )

    # 3. Execute Controlled Mode Evaluation
    try:
        result = controlled_assessment_engine.evaluate_controlled_mode(
            rules=rules_to_evaluate,
            bundle=bundle,
            phase4_result=req.phase4_result,
        )
    except Exception as exc:
        logger.exception("Controlled Mode evaluation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Controlled evaluation failed: {exc}",
        )

    _controlled_evaluations_cache[result.evaluation_id] = result

    # Persist evaluation result to SQLite for durable auditability
    try:
        with sqlite3.connect(_EVAL_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO beacon_controlled_evaluations (
                    evaluation_id, bundle_id, application_id, overall_verdict,
                    evaluation_fingerprint, evaluation_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.evaluation_id,
                    result.bundle_id or "",
                    result.application_id or "",
                    result.overall_verdict.value,
                    result.evaluation_fingerprint,
                    result.model_dump_json(),
                    result.timestamp.isoformat(),
                ),
            )
            conn.commit()
    except Exception as db_exc:
        logger.warning(f"Could not persist controlled evaluation '{result.evaluation_id}' to SQLite: {db_exc}")

    return result


@controlled_router.get("/controlled/evaluations/{evaluation_id}", response_model=ControlledEvaluationResult)
def get_controlled_evaluation_endpoint(
    evaluation_id: str,
    current_user: User = Depends(require_project_permission(Permission.AUDIT)),
):
    """Retrieves an existing Controlled Mode evaluation result by its ID."""
    if evaluation_id in _controlled_evaluations_cache:
        return _controlled_evaluations_cache[evaluation_id]

    # Try lookup from SQLite
    try:
        with sqlite3.connect(_EVAL_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT evaluation_json FROM beacon_controlled_evaluations WHERE evaluation_id = ?",
                (evaluation_id,),
            )
            row = cursor.fetchone()
            if row:
                res_data = json.loads(row[0])
                res = ControlledEvaluationResult(**res_data)
                _controlled_evaluations_cache[evaluation_id] = res
                return res
    except Exception as exc:
        logger.debug(f"SQLite evaluation lookup failed: {exc}")

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Controlled evaluation result '{evaluation_id}' not found.",
    )
