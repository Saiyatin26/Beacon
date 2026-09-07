"""BEACON V2 — Phase 4 Output Evaluator.

Performs domain-agnostic, deterministic structural comparison of execution outputs,
enforcing object key invariance, conservative array order rules, configurable numeric
tolerances, string normalization options, and explicit difference attribution.
"""

from datetime import datetime, timezone
import math
import re
from typing import Any, Optional, Union

from ..models import (
    BehaviorDifference,
    BehaviorDimension,
    DifferenceType,
    DimensionResult,
    EvaluationVerdict,
)
from ..policies import ComparisonPolicy, OutputComparisonPolicy


class OutputEvaluator:
    """Evaluates behavioral equivalence between Reference and Target application outputs."""

    def evaluate(
        self,
        input_id: str,
        reference_payload: Optional[Any],
        target_payload: Optional[Any],
        policy: ComparisonPolicy,
        reference_evidence_id: Optional[str] = None,
        target_evidence_id: Optional[str] = None,
    ) -> DimensionResult:
        """Compares Reference and Target outputs against the specified OutputComparisonPolicy.

        Flat convenience fields on ComparisonPolicy (ignore_array_order, ignore_keys,
        float_tolerance) override/augment the nested output_policy when set.
        """
        # Build effective output policy, applying flat convenience fields as overrides
        nested = policy.output_policy
        arrays_val = "unordered" if policy.ignore_array_order else nested.arrays
        # Determine effective tolerance and numbers mode
        if policy.float_tolerance > 0.0:
            numbers_val = "absolute_tolerance"
            abs_tol_val = policy.float_tolerance
        else:
            numbers_val = nested.numbers
            abs_tol_val = nested.abs_tolerance

        # Merge ignored fields: nested ignored_fields + flat ignore_keys
        effective_ignored = list(set(nested.ignored_fields) | set(policy.ignore_keys))

        from ..policies import OutputComparisonPolicy as _OCP
        out_policy = _OCP(
            objects=nested.objects,
            arrays=arrays_val,
            strings=nested.strings,
            numbers=numbers_val,
            abs_tolerance=abs_tol_val,
            rel_tolerance=nested.rel_tolerance,
            ignore_extra_fields=nested.ignore_extra_fields,
            ignored_fields=effective_ignored,
        )

        # Case 1: Both outputs absent
        if reference_payload is None and target_payload is None:
            return DimensionResult(
                dimension=BehaviorDimension.OUTPUT,
                status=EvaluationVerdict.NOT_APPLICABLE,
                verdict=EvaluationVerdict.NOT_APPLICABLE,
                comparison_method="none",
                details={"message": "No output payload provided for either Reference or Target."},
            )

        # Case 2: One side absent
        if reference_payload is None or target_payload is None:
            diff = BehaviorDifference(
                dimension=BehaviorDimension.OUTPUT,
                input_id=input_id,
                difference_type=DifferenceType.EVIDENCE_MISSING,
                reference_evidence_id=reference_evidence_id,
                target_evidence_id=target_evidence_id,
                reference_value=reference_payload,
                target_value=target_payload,
                comparison_method="presence_check",
                details={
                    "message": "Output payload present on one side but absent on the other.",
                    "reference_present": reference_payload is not None,
                    "target_present": target_payload is not None,
                },
            )
            return DimensionResult(
                dimension=BehaviorDimension.OUTPUT,
                status=EvaluationVerdict.DIFFERENT,
                verdict=EvaluationVerdict.DIFFERENT,
                reference_value=reference_payload,
                target_value=target_payload,
                comparison_method="presence_check",
                difference_type=DifferenceType.EVIDENCE_MISSING,
                differences=[diff],
                evidence_references=[eid for eid in (reference_evidence_id, target_evidence_id) if eid],
            )

        # Case 3: Both outputs present -- perform deep structural comparison
        differences: list[BehaviorDifference] = []
        self._compare_nodes(
            path="$",
            ref=reference_payload,
            target=target_payload,
            input_id=input_id,
            ref_eid=reference_evidence_id,
            target_eid=target_evidence_id,
            policy=out_policy,
            differences=differences,
        )

        evidence_refs = [eid for eid in (reference_evidence_id, target_evidence_id) if eid]

        if not differences:
            return DimensionResult(
                dimension=BehaviorDimension.OUTPUT,
                status=EvaluationVerdict.EQUIVALENT,
                verdict=EvaluationVerdict.EQUIVALENT,
                reference_value=reference_payload,
                target_value=target_payload,
                comparison_method=f"structural_{out_policy.arrays}",
                evidence_references=evidence_refs,
                details={"message": "Outputs are structurally equivalent under configured policy."},
            )

        primary_diff_type = differences[0].difference_type
        return DimensionResult(
            dimension=BehaviorDimension.OUTPUT,
            status=EvaluationVerdict.DIFFERENT,
            verdict=EvaluationVerdict.DIFFERENT,
            reference_value=reference_payload,
            target_value=target_payload,
            comparison_method=f"structural_{out_policy.arrays}",
            difference_type=primary_diff_type,
            differences=differences,
            evidence_references=evidence_refs,
            details={"total_differences": len(differences)},
        )


    def _compare_nodes(
        self,
        path: str,
        ref: Any,
        target: Any,
        input_id: str,
        ref_eid: Optional[str],
        target_eid: Optional[str],
        policy: OutputComparisonPolicy,
        differences: list[BehaviorDifference],
    ) -> None:
        """Recursively compares ref and target data nodes, recording differences."""
        # Normalize OutputEvidence or wrappers if passed directly
        if hasattr(ref, "normalized_output") and getattr(ref, "normalized_output"):
            ref = ref.normalized_output
        elif hasattr(ref, "raw_output") and getattr(ref, "raw_output") is not None:
            ref = ref.raw_output

        if hasattr(target, "normalized_output") and getattr(target, "normalized_output"):
            target = target.normalized_output
        elif hasattr(target, "raw_output") and getattr(target, "raw_output") is not None:
            target = target.raw_output

        # Skip ignored fields
        if path.split(".")[-1] in policy.ignored_fields:
            return

        # 1. Type Mismatch Check
        if ref is None and target is not None:
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.OUTPUT,
                    input_id=input_id,
                    difference_type=DifferenceType.NULL_VS_MISSING_MISMATCH,
                    field_path=path,
                    reference_value=ref,
                    target_value=target,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="type_check",
                    details={"message": f"Field '{path}' is null in reference but not null in target."},
                )
            )
            return

        if ref is not None and target is None:
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.OUTPUT,
                    input_id=input_id,
                    difference_type=DifferenceType.NULL_VS_MISSING_MISMATCH,
                    field_path=path,
                    reference_value=ref,
                    target_value=target,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="type_check",
                    details={"message": f"Field '{path}' is not null in reference but null in target."},
                )
            )
            return

        # Check Python / JSON types
        ref_type = type(ref)
        target_type = type(target)

        # Allow float vs int if numeric policy allows
        both_numeric = isinstance(ref, (int, float)) and isinstance(target, (int, float)) and not isinstance(ref, bool) and not isinstance(target, bool)

        if not both_numeric and ref_type != target_type:
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.OUTPUT,
                    input_id=input_id,
                    difference_type=DifferenceType.TYPE_MISMATCH,
                    field_path=path,
                    reference_value=ref,
                    target_value=target,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="type_check",
                    details={
                        "reference_type": ref_type.__name__,
                        "target_type": target_type.__name__,
                    },
                )
            )
            return

        # 2. Dictionary / Object Comparison
        if isinstance(ref, dict):
            ref_keys = set(ref.keys())
            target_keys = set(target.keys())

            # Missing fields in Target
            missing_in_target = ref_keys - target_keys
            for key in sorted(missing_in_target):
                if key in policy.ignored_fields:
                    continue
                subpath = f"{path}.{key}" if path != "$" else f"$.{key}"
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.OUTPUT,
                        input_id=input_id,
                        difference_type=DifferenceType.MISSING_FIELD,
                        field_path=subpath,
                        reference_value=ref[key],
                        target_value=None,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="key_presence",
                        details={"field": key, "message": f"Field '{key}' missing in Target output."},
                    )
                )

            # Extra fields in Target
            extra_in_target = target_keys - ref_keys
            for key in sorted(extra_in_target):
                if key in policy.ignored_fields or policy.ignore_extra_fields:
                    continue
                subpath = f"{path}.{key}" if path != "$" else f"$.{key}"
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.OUTPUT,
                        input_id=input_id,
                        difference_type=DifferenceType.EXTRA_FIELD,
                        field_path=subpath,
                        reference_value=None,
                        target_value=target[key],
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="key_presence",
                        details={"field": key, "message": f"Field '{key}' unexpectedly present in Target output."},
                    )
                )

            # Common keys recursive check
            common_keys = ref_keys & target_keys
            for key in sorted(common_keys):
                subpath = f"{path}.{key}" if path != "$" else f"$.{key}"
                self._compare_nodes(
                    path=subpath,
                    ref=ref[key],
                    target=target[key],
                    input_id=input_id,
                    ref_eid=ref_eid,
                    target_eid=target_eid,
                    policy=policy,
                    differences=differences,
                )
            return

        # 3. List / Array Comparison
        if isinstance(ref, list):
            if len(ref) != len(target):
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.OUTPUT,
                        input_id=input_id,
                        difference_type=DifferenceType.ARRAY_LENGTH_MISMATCH,
                        field_path=path,
                        reference_value=ref,
                        target_value=target,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="array_length",
                        details={
                            "reference_length": len(ref),
                            "target_length": len(target),
                        },
                    )
                )
                return

            if policy.arrays == "ordered":
                for idx, (ref_item, target_item) in enumerate(zip(ref, target)):
                    subpath = f"{path}[{idx}]"
                    self._compare_nodes(
                        path=subpath,
                        ref=ref_item,
                        target=target_item,
                        input_id=input_id,
                        ref_eid=ref_eid,
                        target_eid=target_eid,
                        policy=policy,
                        differences=differences,
                    )
            else:
                # Unordered array comparison
                # Try sorting if elements are comparable or serialize
                import json
                ref_sorted = sorted(ref, key=lambda x: json.dumps(x, sort_keys=True, default=str))
                target_sorted = sorted(target, key=lambda x: json.dumps(x, sort_keys=True, default=str))
                for idx, (ref_item, target_item) in enumerate(zip(ref_sorted, target_sorted)):
                    subpath = f"{path}[{idx}]"
                    self._compare_nodes(
                        path=subpath,
                        ref=ref_item,
                        target=target_item,
                        input_id=input_id,
                        ref_eid=ref_eid,
                        target_eid=target_eid,
                        policy=policy,
                        differences=differences,
                    )
            return

        # 4. Numeric Comparison
        if both_numeric:
            ref_num = float(ref)
            target_num = float(target)

            if math.isnan(ref_num) and math.isnan(target_num):
                return
            if math.isinf(ref_num) and math.isinf(target_num) and (ref_num > 0) == (target_num > 0):
                return

            if policy.numbers == "exact":
                if ref_num != target_num:
                    differences.append(
                        BehaviorDifference(
                            dimension=BehaviorDimension.OUTPUT,
                            input_id=input_id,
                            difference_type=DifferenceType.OUTPUT_VALUE_MISMATCH,
                            field_path=path,
                            reference_value=ref,
                            target_value=target,
                            reference_evidence_id=ref_eid,
                            target_evidence_id=target_eid,
                            comparison_method="numeric_exact",
                            details={"delta": abs(ref_num - target_num)},
                        )
                    )
            elif policy.numbers == "absolute_tolerance":
                delta = abs(ref_num - target_num)
                if delta > policy.abs_tolerance:
                    differences.append(
                        BehaviorDifference(
                            dimension=BehaviorDimension.OUTPUT,
                            input_id=input_id,
                            difference_type=DifferenceType.NUMERIC_TOLERANCE_EXCEEDED,
                            field_path=path,
                            reference_value=ref,
                            target_value=target,
                            reference_evidence_id=ref_eid,
                            target_evidence_id=target_eid,
                            comparison_method="numeric_absolute_tolerance",
                            details={
                                "delta": delta,
                                "abs_tolerance": policy.abs_tolerance,
                            },
                        )
                    )
            elif policy.numbers == "relative_tolerance":
                delta = abs(ref_num - target_num)
                denom = max(abs(ref_num), abs(target_num))
                rel_delta = (delta / denom) if denom != 0.0 else delta
                if rel_delta > policy.rel_tolerance:
                    differences.append(
                        BehaviorDifference(
                            dimension=BehaviorDimension.OUTPUT,
                            input_id=input_id,
                            difference_type=DifferenceType.NUMERIC_TOLERANCE_EXCEEDED,
                            field_path=path,
                            reference_value=ref,
                            target_value=target,
                            reference_evidence_id=ref_eid,
                            target_evidence_id=target_eid,
                            comparison_method="numeric_relative_tolerance",
                            details={
                                "relative_delta": rel_delta,
                                "rel_tolerance": policy.rel_tolerance,
                            },
                        )
                    )
            return

        # 5. String Comparison
        if isinstance(ref, str) and isinstance(target, str):
            ref_str = ref
            target_str = target

            if policy.strings == "normalized_whitespace":
                ref_str = re.sub(r"\s+", " ", ref_str).strip()
                target_str = re.sub(r"\s+", " ", target_str).strip()
            elif policy.strings == "case_insensitive":
                ref_str = ref_str.lower()
                target_str = target_str.lower()

            if ref_str != target_str:
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.OUTPUT,
                        input_id=input_id,
                        difference_type=DifferenceType.OUTPUT_VALUE_MISMATCH,
                        field_path=path,
                        reference_value=ref,
                        target_value=target,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method=f"string_{policy.strings}",
                    )
                )
            return

        # 6. Boolean & Other Primitive Comparison
        if ref != target:
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.OUTPUT,
                    input_id=input_id,
                    difference_type=DifferenceType.OUTPUT_VALUE_MISMATCH,
                    field_path=path,
                    reference_value=ref,
                    target_value=target,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="primitive_exact",
                )
            )


output_evaluator = OutputEvaluator()
