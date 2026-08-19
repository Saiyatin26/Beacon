"""Phase 10 — Post-Migration Drift Evaluator Service.

Evaluates post-migration runtime observations against a frozen Oracle Set
using the language-independent Phase-8 OracleEvaluator.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Optional, Union
import uuid

from oracle.evaluator import evaluate_oracle
from oracle.models import OracleDefinition, OracleSet
from .models import DriftEvent, DriftObservation, DriftPolicy, DriftStatus

logger = logging.getLogger(__name__)


def evaluate_drift_observation(
    observation: DriftObservation,
    oracle_set: Union[OracleSet, list[OracleDefinition]],
    policy: Optional[DriftPolicy] = None,
    certification_id: Optional[str] = None,
) -> DriftEvent:
    """Evaluates a single post-migration runtime observation against a frozen OracleSet."""
    drift_policy = policy or DriftPolicy()
    oracles: list[OracleDefinition] = []
    set_id = ""
    set_hash = ""

    if isinstance(oracle_set, OracleSet):
        oracles = oracle_set.oracles
        set_id = oracle_set.oracle_set_id
        set_hash = oracle_set.oracle_set_hash
    else:
        oracles = list(oracle_set)
        if oracles:
            from oracle.serializer import compute_oracle_set_hash
            set_hash = compute_oracle_set_hash([o.content_hash for o in oracles])
            set_id = f"SET-{set_hash[:8]}"

    applicable_oracles: list[str] = []
    violated_oracles: list[str] = []
    eval_details: list[dict[str, Any]] = []
    has_error = False
    has_invalid_input = False

    for oracle in oracles:
        report = evaluate_oracle(
            oracle=oracle,
            inputs=observation.inputs,
            outputs=observation.outputs,
        )

        detail = {
            "oracle_id": oracle.oracle_id,
            "status": report.status,
            "condition_satisfied": report.condition_satisfied,
            "consequence_satisfied": report.consequence_satisfied,
            "reason": report.reason,
        }
        eval_details.append(detail)

        if report.status == "PASS":
            applicable_oracles.append(oracle.oracle_id)
        elif report.status == "FAIL":
            applicable_oracles.append(oracle.oracle_id)
            violated_oracles.append(oracle.oracle_id)
        elif report.status == "INVALID_INPUT":
            has_invalid_input = True
        elif report.status == "EVALUATION_ERROR":
            has_error = True

    # Determine final drift status
    event_id = f"DRFT-{uuid.uuid4().hex[:8]}"
    timestamp = observation.timestamp or datetime.now(timezone.utc).isoformat()

    if violated_oracles:
        status = DriftStatus.ORACLE_VIOLATION
        alert = True
        reason = f"Observation violates {len(violated_oracles)} behavioral oracle(s): {', '.join(violated_oracles)}"
    elif has_error:
        status = DriftStatus.EXECUTION_ERROR
        alert = False
        reason = "Execution error during oracle evaluation"
    elif has_invalid_input:
        status = DriftStatus.INVALID_INPUT
        alert = False
        reason = "Observation inputs missing required fields"
    elif applicable_oracles:
        status = DriftStatus.NORMAL
        alert = False
        reason = "Observation is compliant with all exercised oracles"
    else:
        status = DriftStatus.UNCOVERED_INPUT
        alert = False
        reason = "Observation did not exercise any oracle antecedent in the frozen set"

    return DriftEvent(
        event_id=event_id,
        observation_id=observation.observation_id,
        timestamp=timestamp,
        oracle_set_id=set_id,
        oracle_set_hash=set_hash,
        certification_id=certification_id,
        status=status,
        violated_oracle_ids=violated_oracles,
        applicable_oracle_ids=applicable_oracles,
        evaluation_details=eval_details,
        alert_triggered=alert,
        reason=reason,
    )
