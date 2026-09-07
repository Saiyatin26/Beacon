"""BEACON V2 — Phase 4 Behavioral Evaluation Engine.

The central coordinator that ingests tamper-evident Phase 3 evidence bundles,
correlates canonical inputs across Reference and Target implementations, invokes
modular dimension evaluators under declarative comparison policies, and generates
cryptographically bound, audit-ready EvaluationResult objects.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import uuid
from typing import Any, Optional, Union

# Accept any EvidenceBundle-like object (canonical from evidence_models or
# the Phase 4 test shim from evidence.py) via duck-typing.

from .input_adapter import CorrelatedInputItem, evaluation_input_adapter
from .models import (
    BehaviorDifference,
    BehaviorDimension,
    DifferenceType,
    DimensionEvaluationSummary,
    DimensionResult,
    EvaluationResult,
    EvaluationSession,
    EvaluationSummary,
    EvaluationVerdict,
    InputEvaluationResult,
)
from .policies import ComparisonPolicy, resolve_comparison_policy

logger = logging.getLogger("beacon.evaluation.engine")


class BehavioralEvaluationEngine:
    """Core evaluation engine assessing behavioral equivalence across six dimensions."""

    def __init__(self) -> None:
        from .evaluators import (
            boundary_evaluator,
            error_evaluator,
            nonfunctional_evaluator,
            output_evaluator,
            state_evaluator,
            workflow_evaluator,
        )

        self.output_eval = output_evaluator
        self.error_eval = error_evaluator
        self.boundary_eval = boundary_evaluator
        self.state_eval = state_evaluator
        self.workflow_eval = workflow_evaluator
        self.nonfunctional_eval = nonfunctional_evaluator

    def evaluate_bundle(
        self,
        bundle: Any,
        policy: Optional[Union[ComparisonPolicy, dict[str, Any], str]] = None,
        verify_integrity: bool = True,
        dimensions: Optional[list[BehaviorDimension]] = None,
    ) -> EvaluationResult:
        """Evaluates an EvidenceBundle containing Reference and Target execution evidence.

        Args:
            bundle: The tamper-evident EvidenceBundle produced by Phase 3.
            policy: Declarative ComparisonPolicy or name ('default_v2', 'strict_v2', 'relaxed_v2').
            verify_integrity: Whether to verify cryptographic hashes of manifest and records.
            dimensions: Optional list of dimensions to restrict evaluation to.

        Returns:
            EvaluationResult with comprehensive per-input and per-dimension breakdowns.
        """
        active_policy = resolve_comparison_policy(policy)
        selected_dimensions = dimensions or list(BehaviorDimension)

        correlated_items, integrity_issues = evaluation_input_adapter.adapt_bundle(
            bundle=bundle, verify_integrity=verify_integrity
        )

        input_results: list[InputEvaluationResult] = []
        all_differences: list[BehaviorDifference] = []

        for item in correlated_items:
            item_result = self._evaluate_correlated_input(
                item=item,
                policy=active_policy,
                selected_dimensions=selected_dimensions,
            )
            input_results.append(item_result)
            all_differences.extend(item_result.differences)

        summary = self._compute_summary(
            input_results=input_results,
            all_differences=all_differences,
            integrity_issues=integrity_issues,
            total_items=len(correlated_items),
        )

        res = EvaluationResult(
            evaluation_id=f"eval_{uuid.uuid4().hex[:12]}",
            bundle_id=bundle.bundle_id,
            application_id=bundle.application_id,
            timestamp=datetime.now(timezone.utc),
            verdict=summary.overall_verdict,
            status=summary.overall_verdict,
            policy_id=active_policy.policy_id,
            policy_hash=active_policy.compute_policy_hash(),
            summary=summary,
            input_results=input_results,
            differences=all_differences,
            bundle_hash=bundle.bundle_hash,
            metadata={
                "records_evaluated": len(bundle.records),
                "integrity_issues_count": len(integrity_issues),
                "integrity_issues": integrity_issues,
                "policy_description": active_policy.description,
            },
        )

        # Compute deterministic evaluation hash
        res.evaluation_hash = self._compute_evaluation_hash(res)
        return res

    def _evaluate_correlated_input(
        self,
        item: CorrelatedInputItem,
        policy: ComparisonPolicy,
        selected_dimensions: list[BehaviorDimension],
    ) -> InputEvaluationResult:
        """Evaluates a single CorrelatedInputItem across all configured dimensions."""
        dim_results: dict[BehaviorDimension, DimensionResult] = {}
        input_diffs: list[BehaviorDifference] = []

        # Find primary reference and target evidence IDs for traceability
        ref_eid = item.reference_records[0].evidence_id if item.reference_records else None
        target_eid = item.target_records[0].evidence_id if item.target_records else None

        # Fail closed if target or reference is completely missing
        if item.has_missing_target:
            diff = BehaviorDifference(
                dimension=BehaviorDimension.OUTPUT,
                input_id=item.input_id,
                difference_type=DifferenceType.EVIDENCE_MISSING,
                reference_evidence_id=ref_eid,
                target_evidence_id=None,
                comparison_method="execution_presence",
                details={"message": f"Input '{item.input_id}' was executed by Reference but omitted by Target."},
            )
            input_diffs.append(diff)
            dim_results[BehaviorDimension.OUTPUT] = DimensionResult(
                dimension=BehaviorDimension.OUTPUT,
                status=EvaluationVerdict.DIFFERENT,
                verdict=EvaluationVerdict.DIFFERENT,
                comparison_method="execution_presence",
                difference_type=DifferenceType.EVIDENCE_MISSING,
                differences=[diff],
                evidence_references=[ref_eid] if ref_eid else [],
            )
            return InputEvaluationResult(
                input_id=item.input_id,
                verdict=EvaluationVerdict.DIFFERENT,
                status=EvaluationVerdict.DIFFERENT,
                dimension_results=dim_results,
                differences=input_diffs,
                boundary_category=item.boundary_category,
                reference_evidence_ids=[r.evidence_id for r in item.reference_records],
                target_evidence_ids=[r.evidence_id for r in item.target_records],
            )

        if item.is_extra_target:
            diff = BehaviorDifference(
                dimension=BehaviorDimension.OUTPUT,
                input_id=item.input_id,
                difference_type=DifferenceType.EVIDENCE_MISSING,
                reference_evidence_id=None,
                target_evidence_id=target_eid,
                comparison_method="execution_presence",
                details={"message": f"Input '{item.input_id}' was executed by Target but absent from Reference."},
            )
            input_diffs.append(diff)
            dim_results[BehaviorDimension.OUTPUT] = DimensionResult(
                dimension=BehaviorDimension.OUTPUT,
                status=EvaluationVerdict.INCONCLUSIVE,
                verdict=EvaluationVerdict.INCONCLUSIVE,
                comparison_method="execution_presence",
                difference_type=DifferenceType.EVIDENCE_MISSING,
                differences=[diff],
                evidence_references=[target_eid] if target_eid else [],
            )
            return InputEvaluationResult(
                input_id=item.input_id,
                verdict=EvaluationVerdict.INCONCLUSIVE,
                status=EvaluationVerdict.INCONCLUSIVE,
                dimension_results=dim_results,
                differences=input_diffs,
                boundary_category=item.boundary_category,
                reference_evidence_ids=[r.evidence_id for r in item.reference_records],
                target_evidence_ids=[r.evidence_id for r in item.target_records],
            )

        # Evaluate 1: OUTPUT
        if BehaviorDimension.OUTPUT in selected_dimensions:
            ref_out = item.reference_output
            target_out = item.target_output
            ref_out_payload = (
                ref_out.normalized_output
                if (ref_out and ref_out.normalized_output is not None)
                else (ref_out.raw_output if ref_out else None)
            )
            target_out_payload = (
                target_out.normalized_output
                if (target_out and target_out.normalized_output is not None)
                else (target_out.raw_output if target_out else None)
            )

            res_out = self.output_eval.evaluate(
                input_id=item.input_id,
                reference_payload=ref_out_payload,
                target_payload=target_out_payload,
                policy=policy,
                reference_evidence_id=ref_eid,
                target_evidence_id=target_eid,
            )
            dim_results[BehaviorDimension.OUTPUT] = res_out
            input_diffs.extend(res_out.differences)

        # Evaluate 2: ERROR
        if BehaviorDimension.ERROR in selected_dimensions:
            ref_has_err = bool(item.reference_error) or (
                bool(item.reference_output) and getattr(item.reference_output, "exit_code", 0) != 0
            ) or (
                bool(item.reference_output) and getattr(item.reference_output, "status_code", 200) >= 400
            )
            target_has_err = bool(item.target_error) or (
                bool(item.target_output) and getattr(item.target_output, "exit_code", 0) != 0
            ) or (
                bool(item.target_output) and getattr(item.target_output, "status_code", 200) >= 400
            )

            res_err = self.error_eval.evaluate(
                input_id=item.input_id,
                reference_error=item.reference_error,
                target_error=item.target_error,
                policy=policy,
                reference_has_error=ref_has_err,
                target_has_error=target_has_err,
                reference_evidence_id=ref_eid,
                target_evidence_id=target_eid,
            )
            dim_results[BehaviorDimension.ERROR] = res_err
            input_diffs.extend(res_err.differences)

        # Evaluate 3: BOUNDARY
        if BehaviorDimension.BOUNDARY in selected_dimensions:
            ref_has_err = bool(item.reference_error)
            target_has_err = bool(item.target_error)
            res_boundary = self.boundary_eval.evaluate(
                input_id=item.input_id,
                boundary_category=item.boundary_category,
                reference_has_error=ref_has_err,
                target_has_error=target_has_err,
                reference_output=item.reference_output,
                target_output=item.target_output,
                policy=policy,
                reference_evidence_id=ref_eid,
                target_evidence_id=target_eid,
            )
            dim_results[BehaviorDimension.BOUNDARY] = res_boundary
            input_diffs.extend(res_boundary.differences)

        # Evaluate 4: STATE
        if BehaviorDimension.STATE in selected_dimensions:
            res_state = self.state_eval._evaluate_typed(
                input_id=item.input_id,
                reference_db=item.reference_database,
                target_db=item.target_database,
                reference_file=item.reference_file,
                target_file=item.target_file,
                reference_http=item.reference_http,
                target_http=item.target_http,
                policy=policy,
                reference_evidence_id=ref_eid,
                target_evidence_id=target_eid,
            )
            dim_results[BehaviorDimension.STATE] = res_state
            input_diffs.extend(res_state.differences)

        # Evaluate 5: WORKFLOW
        if BehaviorDimension.WORKFLOW in selected_dimensions:
            res_wf = self.workflow_eval.evaluate(
                input_id=item.input_id,
                reference_trace=item.reference_trace,
                target_trace=item.target_trace,
                policy=policy,
                reference_evidence_id=ref_eid,
                target_evidence_id=target_eid,
            )
            dim_results[BehaviorDimension.WORKFLOW] = res_wf
            input_diffs.extend(res_wf.differences)

        # Evaluate 6: NONFUNCTIONAL
        if BehaviorDimension.NONFUNCTIONAL in selected_dimensions:
            ref_dur = getattr(item.reference_output, "duration_ms", None) if item.reference_output else None
            target_dur = getattr(item.target_output, "duration_ms", None) if item.target_output else None
            res_nf = self.nonfunctional_eval.evaluate(
                input_id=item.input_id,
                reference_duration_ms=ref_dur,
                target_duration_ms=target_dur,
                policy=policy,
                reference_evidence_id=ref_eid,
                target_evidence_id=target_eid,
            )
            dim_results[BehaviorDimension.NONFUNCTIONAL] = res_nf
            input_diffs.extend(res_nf.differences)

        # Compute overall input verdict
        verdicts = [dr.verdict for dr in dim_results.values()]
        if EvaluationVerdict.DIFFERENT in verdicts:
            input_verdict = EvaluationVerdict.DIFFERENT
        elif EvaluationVerdict.ERROR in verdicts:
            input_verdict = EvaluationVerdict.ERROR
        elif EvaluationVerdict.INCONCLUSIVE in verdicts:
            input_verdict = EvaluationVerdict.INCONCLUSIVE
        elif EvaluationVerdict.EQUIVALENT in verdicts:
            input_verdict = EvaluationVerdict.EQUIVALENT
        else:
            input_verdict = EvaluationVerdict.NOT_APPLICABLE

        return InputEvaluationResult(
            input_id=item.input_id,
            verdict=input_verdict,
            status=input_verdict,
            dimension_results=dim_results,
            differences=input_diffs,
            boundary_category=item.boundary_category,
            reference_evidence_ids=[r.evidence_id for r in item.reference_records],
            target_evidence_ids=[r.evidence_id for r in item.target_records],
        )

    def _compute_summary(
        self,
        input_results: list[InputEvaluationResult],
        all_differences: list[BehaviorDifference],
        integrity_issues: list[str],
        total_items: int,
    ) -> EvaluationSummary:
        """Computes summary metrics, counts, and rollups across all input evaluations."""
        equiv_count = sum(1 for r in input_results if r.verdict == EvaluationVerdict.EQUIVALENT)
        diff_count = sum(1 for r in input_results if r.verdict == EvaluationVerdict.DIFFERENT)
        inconcl_count = sum(1 for r in input_results if r.verdict == EvaluationVerdict.INCONCLUSIVE)
        err_count = sum(1 for r in input_results if r.verdict == EvaluationVerdict.ERROR)
        na_count = sum(1 for r in input_results if r.verdict == EvaluationVerdict.NOT_APPLICABLE)

        # Determine overall verdict
        if integrity_issues:
            overall_verdict = EvaluationVerdict.ERROR
        elif diff_count > 0:
            overall_verdict = EvaluationVerdict.DIFFERENT
        elif err_count > 0 or inconcl_count > 0:
            overall_verdict = EvaluationVerdict.INCONCLUSIVE
        elif equiv_count > 0 and (equiv_count + na_count) == len(input_results):
            overall_verdict = EvaluationVerdict.EQUIVALENT
        elif not input_results:
            overall_verdict = EvaluationVerdict.NOT_APPLICABLE
        else:
            overall_verdict = EvaluationVerdict.INCONCLUSIVE

        # Dimension breakdown summaries
        dim_summaries: dict[BehaviorDimension, DimensionEvaluationSummary] = {}
        for dim in BehaviorDimension:
            dim_results = [r.dimension_results[dim] for r in input_results if dim in r.dimension_results]
            d_equiv = sum(1 for dr in dim_results if dr.verdict == EvaluationVerdict.EQUIVALENT)
            d_diff = sum(1 for dr in dim_results if dr.verdict == EvaluationVerdict.DIFFERENT)
            d_inconcl = sum(1 for dr in dim_results if dr.verdict == EvaluationVerdict.INCONCLUSIVE)
            d_na = sum(1 for dr in dim_results if dr.verdict == EvaluationVerdict.NOT_APPLICABLE)

            if d_diff > 0:
                dim_verdict = EvaluationVerdict.DIFFERENT
            elif d_inconcl > 0:
                dim_verdict = EvaluationVerdict.INCONCLUSIVE
            elif d_equiv > 0:
                dim_verdict = EvaluationVerdict.EQUIVALENT
            else:
                dim_verdict = EvaluationVerdict.NOT_APPLICABLE

            dim_summaries[dim] = DimensionEvaluationSummary(
                dimension=dim,
                total_evaluated=len(dim_results),
                equivalent_count=d_equiv,
                different_count=d_diff,
                inconclusive_count=d_inconcl,
                not_applicable_count=d_na,
                overall_verdict=dim_verdict,
            )

        # Difference counts
        diff_by_type: dict[str, int] = {}
        diff_by_dim: dict[str, int] = {}
        for diff in all_differences:
            t_name = diff.difference_type.value if hasattr(diff.difference_type, "value") else str(diff.difference_type)
            d_name = diff.dimension.value if hasattr(diff.dimension, "value") else str(diff.dimension)
            diff_by_type[t_name] = diff_by_type.get(t_name, 0) + 1
            diff_by_dim[d_name] = diff_by_dim.get(d_name, 0) + 1

        coverage = (len(input_results) / total_items) if total_items > 0 else 1.0

        return EvaluationSummary(
            total_inputs=total_items,
            evaluated_inputs=len(input_results),
            equivalent_inputs=equiv_count,
            different_inputs=diff_count,
            inconclusive_inputs=inconcl_count,
            error_inputs=err_count,
            not_applicable_inputs=na_count,
            overall_verdict=overall_verdict,
            dimension_summaries=dim_summaries,
            total_differences=len(all_differences),
            differences_by_type=diff_by_type,
            differences_by_dimension=diff_by_dim,
            coverage_ratio=coverage,
        )

    def _compute_evaluation_hash(self, result: EvaluationResult) -> str:
        """Computes deterministic SHA-256 fingerprint over canonical representation."""
        canonical_dict = {
            "evaluation_id": result.evaluation_id,
            "bundle_id": result.bundle_id,
            "application_id": result.application_id,
            "verdict": result.verdict.value,
            "policy_id": result.policy_id,
            "policy_hash": result.policy_hash,
            "total_differences": result.summary.total_differences,
            "differences_count": len(result.differences),
            "bundle_hash": result.bundle_hash,
        }
        canonical = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


behavioral_evaluation_engine = BehavioralEvaluationEngine()
