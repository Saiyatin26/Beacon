"""BEACON V2 -- Phase 4 Nonfunctional Evaluator.

Evaluates duration, latency, and resource metrics against explicit tolerance limits.
Defaults to NOT_APPLICABLE unless nonfunctional evaluation is explicitly enabled in policy
OR the policy-level ``max_latency_ratio`` flat field is set to a positive value.
"""

from typing import Any, Optional

from ..models import (
    BehaviorDifference,
    BehaviorDimension,
    DifferenceType,
    DimensionResult,
    EvaluationVerdict,
)
from ..policies import ComparisonPolicy


class NonfunctionalEvaluator:
    """Evaluates nonfunctional execution metrics when explicitly enabled."""

    def evaluate(
        self,
        input_id: str,
        reference_duration_ms: Optional[float],
        target_duration_ms: Optional[float],
        policy: ComparisonPolicy,
        reference_evidence_id: Optional[str] = None,
        target_evidence_id: Optional[str] = None,
    ) -> DimensionResult:
        """Evaluates nonfunctional metrics against policy thresholds.

        Nonfunctional evaluation is activated when:
        - ``policy.nonfunctional_policy.enabled`` is True, OR
        - ``policy.max_latency_ratio`` is > 0 (flat convenience field).

        In the latter case, max_latency_ratio acts as the ratio threshold while
        max_absolute_diff_ms from nonfunctional_policy is still applied.
        """
        nf_policy = policy.nonfunctional_policy
        # Determine effective ratio threshold
        effective_ratio = (
            policy.max_latency_ratio
            if policy.max_latency_ratio > 0
            else nf_policy.max_duration_ratio
        )
        # Determine if nonfunctional evaluation is active
        is_active = nf_policy.enabled or (policy.max_latency_ratio > 0)

        if not is_active:
            return DimensionResult(
                dimension=BehaviorDimension.NONFUNCTIONAL,
                status=EvaluationVerdict.NOT_APPLICABLE,
                verdict=EvaluationVerdict.NOT_APPLICABLE,
                comparison_method="policy_disabled",
                details={"message": "Nonfunctional evaluation is disabled in the active comparison policy."},
            )

        evidence_refs = [eid for eid in (reference_evidence_id, target_evidence_id) if eid]

        if reference_duration_ms is None or target_duration_ms is None:
            diff = BehaviorDifference(
                dimension=BehaviorDimension.NONFUNCTIONAL,
                input_id=input_id,
                difference_type=DifferenceType.EVIDENCE_MISSING,
                reference_evidence_id=reference_evidence_id,
                target_evidence_id=target_evidence_id,
                reference_value={"duration_ms": reference_duration_ms},
                target_value={"duration_ms": target_duration_ms},
                comparison_method="missing_duration",
                details={"message": "Execution duration metrics not available for both implementations."},
            )
            return DimensionResult(
                dimension=BehaviorDimension.NONFUNCTIONAL,
                status=EvaluationVerdict.INCONCLUSIVE,
                verdict=EvaluationVerdict.INCONCLUSIVE,
                comparison_method="missing_duration",
                difference_type=DifferenceType.EVIDENCE_MISSING,
                differences=[diff],
                evidence_references=evidence_refs,
                details={"message": "Execution duration metrics not available for both implementations."},
            )

        abs_diff = abs(target_duration_ms - reference_duration_ms)
        ratio = (target_duration_ms / reference_duration_ms) if reference_duration_ms > 0 else 1.0

        differences: list[BehaviorDifference] = []

        if abs_diff > nf_policy.max_absolute_diff_ms or ratio > effective_ratio:
            diff = BehaviorDifference(
                dimension=BehaviorDimension.NONFUNCTIONAL,
                input_id=input_id,
                difference_type=DifferenceType.NONFUNCTIONAL_THRESHOLD_EXCEEDED,
                reference_evidence_id=reference_evidence_id,
                target_evidence_id=target_evidence_id,
                reference_value={"duration_ms": reference_duration_ms},
                target_value={"duration_ms": target_duration_ms},
                comparison_method="duration_threshold",
                details={
                    "absolute_diff_ms": abs_diff,
                    "max_absolute_diff_ms": nf_policy.max_absolute_diff_ms,
                    "ratio": ratio,
                    "effective_ratio_threshold": effective_ratio,
                },
            )
            differences.append(diff)

            return DimensionResult(
                dimension=BehaviorDimension.NONFUNCTIONAL,
                status=EvaluationVerdict.DIFFERENT,
                verdict=EvaluationVerdict.DIFFERENT,
                reference_value={"duration_ms": reference_duration_ms},
                target_value={"duration_ms": target_duration_ms},
                comparison_method="duration_threshold",
                difference_type=DifferenceType.NONFUNCTIONAL_THRESHOLD_EXCEEDED,
                differences=differences,
                evidence_references=evidence_refs,
                details={"absolute_diff_ms": abs_diff, "ratio": ratio},
            )

        return DimensionResult(
            dimension=BehaviorDimension.NONFUNCTIONAL,
            status=EvaluationVerdict.EQUIVALENT,
            verdict=EvaluationVerdict.EQUIVALENT,
            reference_value={"duration_ms": reference_duration_ms},
            target_value={"duration_ms": target_duration_ms},
            comparison_method="duration_threshold",
            evidence_references=evidence_refs,
            details={"absolute_diff_ms": abs_diff, "ratio": ratio},
        )


nonfunctional_evaluator = NonfunctionalEvaluator()
