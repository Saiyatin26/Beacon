"""BEACON V2 — Phase 4 Error Evaluator.

Evaluates domain-agnostic error handling equivalence between Reference and Target,
comparing exit codes, HTTP statuses, structured error codes, categories, and messages.
"""

from datetime import datetime, timezone
import re
from typing import Any, Optional, Union

from ..models import (
    BehaviorDifference,
    BehaviorDimension,
    DifferenceType,
    DimensionResult,
    EvaluationVerdict,
)
from ..policies import ComparisonPolicy, ErrorComparisonPolicy


class ErrorEvaluator:
    """Evaluates error behavior equivalence between Reference and Target applications."""

    def evaluate(
        self,
        input_id: str,
        reference_error: Optional[Any],
        target_error: Optional[Any],
        policy: ComparisonPolicy,
        reference_has_error: Optional[bool] = None,
        target_has_error: Optional[bool] = None,
        reference_evidence_id: Optional[str] = None,
        target_evidence_id: Optional[str] = None,
    ) -> DimensionResult:
        """Evaluates whether error behavior matches between Reference and Target.

        reference_has_error and target_has_error can be omitted; when absent they
        are inferred from whether reference_error / target_error objects are present.
        """
        err_policy = policy.error_policy

        # Infer error presence from the objects when not explicitly provided
        if reference_has_error is None:
            reference_has_error = reference_error is not None
        if target_has_error is None:
            target_has_error = target_error is not None

        # Case 1: Both succeeded without error
        if not reference_has_error and not target_has_error:
            return DimensionResult(
                dimension=BehaviorDimension.ERROR,
                status=EvaluationVerdict.EQUIVALENT,
                verdict=EvaluationVerdict.EQUIVALENT,
                comparison_method="success_status",
                details={"message": "Both implementations succeeded without error."},
            )

        # Case 2: One succeeded and the other produced an error (Major mismatch)
        if reference_has_error != target_has_error:
            diff = BehaviorDifference(
                dimension=BehaviorDimension.ERROR,
                input_id=input_id,
                difference_type=DifferenceType.SUCCESS_ERROR_MISMATCH,
                reference_evidence_id=reference_evidence_id,
                target_evidence_id=target_evidence_id,
                reference_value={"has_error": reference_has_error},
                target_value={"has_error": target_has_error},
                comparison_method="error_state",
                details={
                    "reference_has_error": reference_has_error,
                    "target_has_error": target_has_error,
                    "message": "One implementation succeeded while the other failed with an error.",
                },
            )
            return DimensionResult(
                dimension=BehaviorDimension.ERROR,
                status=EvaluationVerdict.DIFFERENT,
                verdict=EvaluationVerdict.DIFFERENT,
                reference_value=reference_error,
                target_value=target_error,
                comparison_method="error_state",
                difference_type=DifferenceType.SUCCESS_ERROR_MISMATCH,
                differences=[diff],
                evidence_references=[eid for eid in (reference_evidence_id, target_evidence_id) if eid],
            )

        # Case 3: Both produced errors — compare attributes
        differences: list[BehaviorDifference] = []

        ref_status = self._get_attr(reference_error, ["status_code", "exit_code", "status", "http_status"])
        target_status = self._get_attr(target_error, ["status_code", "exit_code", "status", "http_status"])

        ref_code = self._get_attr(reference_error, ["error_code", "code", "type"])
        target_code = self._get_attr(target_error, ["error_code", "code", "type"])

        ref_category = self._get_attr(reference_error, ["category", "error_category"])
        target_category = self._get_attr(target_error, ["category", "error_category"])

        ref_msg = self._get_attr(reference_error, ["message", "error_message", "error", "stderr"])
        target_msg = self._get_attr(target_error, ["message", "error_message", "error", "stderr"])

        has_any_ref_info = any(v is not None for v in (ref_status, ref_code, ref_category, ref_msg))
        has_any_target_info = any(v is not None for v in (target_status, target_code, target_category, target_msg))

        # If both produced errors but neither has detailed error evidence
        if not has_any_ref_info and not has_any_target_info:
            diff = BehaviorDifference(
                dimension=BehaviorDimension.ERROR,
                input_id=input_id,
                difference_type=DifferenceType.EVIDENCE_MISSING,
                reference_evidence_id=reference_evidence_id,
                target_evidence_id=target_evidence_id,
                reference_value=reference_error,
                target_value=target_error,
                comparison_method="insufficient_error_evidence",
                details={"message": "Both implementations produced errors, but detailed error evidence is unavailable."},
            )
            return DimensionResult(
                dimension=BehaviorDimension.ERROR,
                status=EvaluationVerdict.INCONCLUSIVE,
                verdict=EvaluationVerdict.INCONCLUSIVE,
                reference_value=reference_error,
                target_value=target_error,
                comparison_method="insufficient_error_evidence",
                difference_type=DifferenceType.EVIDENCE_MISSING,
                differences=[diff],
                evidence_references=[eid for eid in (reference_evidence_id, target_evidence_id) if eid],
                details={"message": "Insufficient error evidence to establish error equivalence."},
            )

        # If one has error details and the other has none
        if has_any_ref_info != has_any_target_info:
            diff = BehaviorDifference(
                dimension=BehaviorDimension.ERROR,
                input_id=input_id,
                difference_type=DifferenceType.EVIDENCE_MISSING,
                reference_evidence_id=reference_evidence_id,
                target_evidence_id=target_evidence_id,
                reference_value=reference_error,
                target_value=target_error,
                comparison_method="error_presence",
                details={
                    "message": "Detailed error evidence present for one implementation but absent for the other.",
                    "reference_has_details": has_any_ref_info,
                    "target_has_details": has_any_target_info,
                },
            )
            return DimensionResult(
                dimension=BehaviorDimension.ERROR,
                status=EvaluationVerdict.INCONCLUSIVE,
                verdict=EvaluationVerdict.INCONCLUSIVE,
                reference_value=reference_error,
                target_value=target_error,
                comparison_method="error_presence",
                difference_type=DifferenceType.EVIDENCE_MISSING,
                differences=[diff],
                evidence_references=[eid for eid in (reference_evidence_id, target_evidence_id) if eid],
            )

        # Compare status/exit code
        if err_policy.compare_status and (ref_status is not None or target_status is not None):
            if ref_status != target_status:
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.ERROR,
                        input_id=input_id,
                        difference_type=DifferenceType.ERROR_STATUS_MISMATCH,
                        field_path="status_code",
                        reference_value=ref_status,
                        target_value=target_status,
                        reference_evidence_id=reference_evidence_id,
                        target_evidence_id=target_evidence_id,
                        comparison_method="exact_status",
                    )
                )

        # Compare error code
        if err_policy.compare_code and (ref_code is not None or target_code is not None):
            if ref_code != target_code:
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.ERROR,
                        input_id=input_id,
                        difference_type=DifferenceType.ERROR_CODE_MISMATCH,
                        field_path="error_code",
                        reference_value=ref_code,
                        target_value=target_code,
                        reference_evidence_id=reference_evidence_id,
                        target_evidence_id=target_evidence_id,
                        comparison_method="exact_code",
                    )
                )

        # Compare category
        if ref_category is not None and target_category is not None:
            if str(ref_category).lower() != str(target_category).lower():
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.ERROR,
                        input_id=input_id,
                        difference_type=DifferenceType.ERROR_CATEGORY_MISMATCH,
                        field_path="category",
                        reference_value=ref_category,
                        target_value=target_category,
                        reference_evidence_id=reference_evidence_id,
                        target_evidence_id=target_evidence_id,
                        comparison_method="case_insensitive_category",
                    )
                )

        # Compare message
        if err_policy.compare_message and (ref_msg is not None or target_msg is not None):
            ref_str = str(ref_msg or "")
            target_str = str(target_msg or "")

            if err_policy.message_matching == "normalized":
                ref_str = re.sub(r"\s+", " ", ref_str).strip().lower()
                target_str = re.sub(r"\s+", " ", target_str).strip().lower()

            if ref_str != target_str:
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.ERROR,
                        input_id=input_id,
                        difference_type=DifferenceType.ERROR_MESSAGE_MISMATCH,
                        field_path="message",
                        reference_value=ref_msg,
                        target_value=target_msg,
                        reference_evidence_id=reference_evidence_id,
                        target_evidence_id=target_evidence_id,
                        comparison_method=f"message_{err_policy.message_matching}",
                    )
                )

        evidence_refs = [eid for eid in (reference_evidence_id, target_evidence_id) if eid]

        if not differences:
            return DimensionResult(
                dimension=BehaviorDimension.ERROR,
                status=EvaluationVerdict.EQUIVALENT,
                verdict=EvaluationVerdict.EQUIVALENT,
                reference_value=reference_error,
                target_value=target_error,
                comparison_method="error_attributes",
                evidence_references=evidence_refs,
                details={"message": "Both implementations produced equivalent error behaviors."},
            )

        return DimensionResult(
            dimension=BehaviorDimension.ERROR,
            status=EvaluationVerdict.DIFFERENT,
            verdict=EvaluationVerdict.DIFFERENT,
            reference_value=reference_error,
            target_value=target_error,
            comparison_method="error_attributes",
            difference_type=differences[0].difference_type,
            differences=differences,
            evidence_references=evidence_refs,
            details={"total_differences": len(differences)},
        )

    def _get_attr(self, obj: Any, field_names: list[str]) -> Optional[Any]:
        """Extracts field from dict or object by checking candidate field names."""
        if obj is None:
            return None
        if isinstance(obj, dict):
            for name in field_names:
                if name in obj and obj[name] is not None:
                    return obj[name]
        for name in field_names:
            if hasattr(obj, name):
                val = getattr(obj, name)
                if val is not None:
                    return val
        return None


error_evaluator = ErrorEvaluator()
