"""BEACON V2 -- Phase 4 Boundary Evaluator.

Evaluates behavioral equivalence specifically on boundary and edge-case inputs
based on explicit input provenance and metadata, without inventing domain heuristics.
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


class BoundaryEvaluator:
    """Evaluates whether applications handle boundary inputs equivalently."""

    def evaluate(
        self,
        input_id: str,
        boundary_category: Optional[str],
        reference_output: Optional[Any] = None,
        target_output: Optional[Any] = None,
        reference_error: Optional[Any] = None,
        target_error: Optional[Any] = None,
        policy: Optional[ComparisonPolicy] = None,
        reference_has_error: Optional[bool] = None,
        target_has_error: Optional[bool] = None,
        reference_evidence_id: Optional[str] = None,
        target_evidence_id: Optional[str] = None,
    ) -> DimensionResult:
        """Evaluates boundary behavior equivalence.

        Returns NOT_APPLICABLE if no boundary metadata exists.

        Parameters:
            input_id: Canonical input identifier.
            boundary_category: Explicit boundary type (e.g., 'OFF_BY_ONE', 'MAX_INTEGER').
            reference_output: Reference output payload for boundary input.
            target_output: Target output payload for boundary input.
            reference_error: Reference error object (if the execution resulted in error).
            target_error: Target error object (if the execution resulted in error).
            policy: Comparison policy governing boundary evaluation.
            reference_has_error: Explicit error flag (inferred from reference_error if None).
            target_has_error: Explicit error flag (inferred from target_error if None).
            reference_evidence_id: Reference evidence record ID for traceability.
            target_evidence_id: Target evidence record ID for traceability.
        """
        if policy is None:
            from ..policies import DEFAULT_COMPARISON_POLICY
            policy = DEFAULT_COMPARISON_POLICY

        if not policy.boundary_policy.enabled or not boundary_category:
            return DimensionResult(
                dimension=BehaviorDimension.BOUNDARY,
                status=EvaluationVerdict.NOT_APPLICABLE,
                verdict=EvaluationVerdict.NOT_APPLICABLE,
                comparison_method="metadata_presence",
                details={"message": "Input is not classified with boundary metadata; boundary evaluation skipped."},
            )

        # Infer error presence from objects when not explicitly provided
        if reference_has_error is None:
            reference_has_error = reference_error is not None
        if target_has_error is None:
            target_has_error = target_error is not None

        evidence_refs = [eid for eid in (reference_evidence_id, target_evidence_id) if eid]

        # Compare outcome type (success vs error)
        if reference_has_error != target_has_error:
            diff = BehaviorDifference(
                dimension=BehaviorDimension.BOUNDARY,
                input_id=input_id,
                difference_type=DifferenceType.BOUNDARY_BEHAVIOR_MISMATCH,
                reference_evidence_id=reference_evidence_id,
                target_evidence_id=target_evidence_id,
                reference_value={"boundary_category": boundary_category, "has_error": reference_has_error},
                target_value={"boundary_category": boundary_category, "has_error": target_has_error},
                comparison_method="boundary_outcome",
                details={
                    "boundary_category": boundary_category,
                    "reference_has_error": reference_has_error,
                    "target_has_error": target_has_error,
                    "message": (
                        f"Boundary condition '{boundary_category}' was handled differently: "
                        f"Reference has_error={reference_has_error} vs Target has_error={target_has_error}."
                    ),
                },
            )
            return DimensionResult(
                dimension=BehaviorDimension.BOUNDARY,
                status=EvaluationVerdict.DIFFERENT,
                verdict=EvaluationVerdict.DIFFERENT,
                reference_value={"boundary_category": boundary_category, "has_error": reference_has_error},
                target_value={"boundary_category": boundary_category, "has_error": target_has_error},
                comparison_method="boundary_outcome",
                difference_type=DifferenceType.BOUNDARY_BEHAVIOR_MISMATCH,
                differences=[diff],
                evidence_references=evidence_refs,
                details={"boundary_category": boundary_category},
            )

        # Both had same error/success outcome; now compare output payloads if available
        if reference_output is not None and target_output is not None:
            from .output_evaluator import OutputEvaluator
            out_ev = OutputEvaluator()
            out_result = out_ev.evaluate(
                input_id=input_id,
                reference_payload=reference_output,
                target_payload=target_output,
                policy=policy,
                reference_evidence_id=reference_evidence_id,
                target_evidence_id=target_evidence_id,
            )
            if out_result.verdict == EvaluationVerdict.DIFFERENT:
                # Relabel differences as BOUNDARY_BEHAVIOR_MISMATCH
                boundary_diffs = []
                for d in out_result.differences:
                    boundary_diffs.append(BehaviorDifference(
                        dimension=BehaviorDimension.BOUNDARY,
                        input_id=d.input_id,
                        difference_type=DifferenceType.BOUNDARY_BEHAVIOR_MISMATCH,
                        field_path=d.field_path,
                        reference_value=d.reference_value,
                        target_value=d.target_value,
                        reference_evidence_id=d.reference_evidence_id,
                        target_evidence_id=d.target_evidence_id,
                        comparison_method=d.comparison_method,
                        details={**d.details, "boundary_category": boundary_category},
                    ))
                return DimensionResult(
                    dimension=BehaviorDimension.BOUNDARY,
                    status=EvaluationVerdict.DIFFERENT,
                    verdict=EvaluationVerdict.DIFFERENT,
                    reference_value=reference_output,
                    target_value=target_output,
                    comparison_method="boundary_output",
                    difference_type=DifferenceType.BOUNDARY_BEHAVIOR_MISMATCH,
                    differences=boundary_diffs,
                    evidence_references=evidence_refs,
                    details={"boundary_category": boundary_category},
                )

        # Both handled boundary consistently
        return DimensionResult(
            dimension=BehaviorDimension.BOUNDARY,
            status=EvaluationVerdict.EQUIVALENT,
            verdict=EvaluationVerdict.EQUIVALENT,
            reference_value={"boundary_category": boundary_category},
            target_value={"boundary_category": boundary_category},
            comparison_method="boundary_outcome",
            evidence_references=evidence_refs,
            details={
                "boundary_category": boundary_category,
                "message": f"Both implementations handled boundary condition '{boundary_category}' consistently.",
            },
        )


boundary_evaluator = BoundaryEvaluator()
