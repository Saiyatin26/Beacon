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

from execution.evidence_models import OutputEvidence
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
            selected_dimensions=selected_dimensions,
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
        res.evaluation_hash = self._compute_evaluation_hash(res, selected_dimensions=selected_dimensions)
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

        # When target or reference is completely missing -> populate all selected dimensions explicitly
        if item.has_missing_target or item.is_extra_target:
            missing_side = "Target" if item.has_missing_target else "Reference"
            present_eid = ref_eid if item.has_missing_target else target_eid
            ev_refs = [present_eid] if present_eid else []

            for dim in selected_dimensions:
                if dim == BehaviorDimension.BOUNDARY:
                    if item.boundary_category and policy.boundary_policy.enabled:
                        diff = BehaviorDifference(
                            dimension=BehaviorDimension.BOUNDARY,
                            input_id=item.input_id,
                            difference_type=DifferenceType.EVIDENCE_MISSING,
                            reference_evidence_id=ref_eid,
                            target_evidence_id=target_eid,
                            comparison_method="execution_presence",
                            details={"message": f"Boundary input '{item.input_id}' missing {missing_side} execution."},
                        )
                        input_diffs.append(diff)
                        dim_results[BehaviorDimension.BOUNDARY] = DimensionResult(
                            dimension=BehaviorDimension.BOUNDARY,
                            status=EvaluationVerdict.INCONCLUSIVE,
                            verdict=EvaluationVerdict.INCONCLUSIVE,
                            comparison_method="execution_presence",
                            difference_type=DifferenceType.EVIDENCE_MISSING,
                            differences=[diff],
                            evidence_references=ev_refs,
                        )
                    else:
                        dim_results[BehaviorDimension.BOUNDARY] = DimensionResult(
                            dimension=BehaviorDimension.BOUNDARY,
                            status=EvaluationVerdict.NOT_APPLICABLE,
                            verdict=EvaluationVerdict.NOT_APPLICABLE,
                            comparison_method="metadata_presence",
                            details={"message": "No boundary metadata or boundary evaluation disabled."},
                        )
                elif dim == BehaviorDimension.NONFUNCTIONAL:
                    nf_active = policy.nonfunctional_policy.enabled or (policy.max_latency_ratio > 0)
                    if nf_active:
                        diff = BehaviorDifference(
                            dimension=BehaviorDimension.NONFUNCTIONAL,
                            input_id=item.input_id,
                            difference_type=DifferenceType.EVIDENCE_MISSING,
                            reference_evidence_id=ref_eid,
                            target_evidence_id=target_eid,
                            comparison_method="execution_presence",
                            details={"message": f"Input '{item.input_id}' missing {missing_side} execution metrics."},
                        )
                        input_diffs.append(diff)
                        dim_results[BehaviorDimension.NONFUNCTIONAL] = DimensionResult(
                            dimension=BehaviorDimension.NONFUNCTIONAL,
                            status=EvaluationVerdict.INCONCLUSIVE,
                            verdict=EvaluationVerdict.INCONCLUSIVE,
                            comparison_method="execution_presence",
                            difference_type=DifferenceType.EVIDENCE_MISSING,
                            differences=[diff],
                            evidence_references=ev_refs,
                        )
                    else:
                        dim_results[BehaviorDimension.NONFUNCTIONAL] = DimensionResult(
                            dimension=BehaviorDimension.NONFUNCTIONAL,
                            status=EvaluationVerdict.NOT_APPLICABLE,
                            verdict=EvaluationVerdict.NOT_APPLICABLE,
                            comparison_method="policy_disabled",
                            details={"message": "Nonfunctional evaluation disabled."},
                        )
                else:
                    diff = BehaviorDifference(
                        dimension=dim,
                        input_id=item.input_id,
                        difference_type=DifferenceType.EVIDENCE_MISSING,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="execution_presence",
                        details={"message": f"Input '{item.input_id}' missing {missing_side} execution evidence for {dim.value}."},
                    )
                    input_diffs.append(diff)
                    dim_results[dim] = DimensionResult(
                        dimension=dim,
                        status=EvaluationVerdict.INCONCLUSIVE,
                        verdict=EvaluationVerdict.INCONCLUSIVE,
                        comparison_method="execution_presence",
                        difference_type=DifferenceType.EVIDENCE_MISSING,
                        differences=[diff],
                        evidence_references=ev_refs,
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
            output_failures = [
                f for f in item.adaptation_failures
                if f.evidence_type.lower() in ("output", "evidencetype.output")
            ]
            if output_failures:
                failure_reasons = "; ".join([f.reason for f in output_failures])
                fail_eids = [f.evidence_id for f in output_failures if f.evidence_id]
                diff = BehaviorDifference(
                    dimension=BehaviorDimension.OUTPUT,
                    input_id=item.input_id,
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="adaptation_validation",
                    details={
                        "reason": "ADAPTATION_FAILED",
                        "message": f"Malformed output evidence payload: {failure_reasons}",
                        "failed_evidence_ids": fail_eids,
                    },
                )
                dim_results[BehaviorDimension.OUTPUT] = DimensionResult(
                    dimension=BehaviorDimension.OUTPUT,
                    status=EvaluationVerdict.INCONCLUSIVE,
                    verdict=EvaluationVerdict.INCONCLUSIVE,
                    comparison_method="adaptation_validation",
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    differences=[diff],
                    evidence_references=fail_eids or [eid for eid in (ref_eid, target_eid) if eid],
                    details={"reason": "ADAPTATION_FAILED", "message": failure_reasons},
                )
                input_diffs.append(diff)
            else:
                ref_out = item.reference_output
                target_out = item.target_output
                ref_out_status = item.reference_output_status or getattr(ref_out, "capture_status", getattr(ref_out, "status", None))
                target_out_status = item.target_output_status or getattr(target_out, "capture_status", getattr(target_out, "status", None))

                def _extract_payload(out_obj: Optional[OutputEvidence]) -> Any:
                    if out_obj is None:
                        return None
                    norm = getattr(out_obj, "normalized_output", None)
                    raw = getattr(out_obj, "raw_output", None)
                    if norm is not None and (norm or raw is None):
                        return norm
                    if raw is not None:
                        return raw
                    return norm

                ref_out_payload = _extract_payload(ref_out)
                target_out_payload = _extract_payload(target_out)

                res_out = self.output_eval.evaluate(
                    input_id=item.input_id,
                    reference_payload=ref_out_payload,
                    target_payload=target_out_payload,
                    policy=policy,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    reference_present=item.reference_output is not None,
                    target_present=item.target_output is not None,
                    reference_status=ref_out_status,
                    target_status=target_out_status,
                )
                dim_results[BehaviorDimension.OUTPUT] = res_out
                input_diffs.extend(res_out.differences)

        # Evaluate 2: ERROR
        # Extract observable error info from ErrorEvidence or OutputEvidence (status_code, exit_code, stderr)
        ref_err_obj = item.reference_error
        if ref_err_obj is None and item.reference_output:
            out = item.reference_output
            status_code = getattr(out, "status_code", None) or getattr(out, "http_status", None)
            exit_code = getattr(out, "exit_code", None)
            stderr = getattr(out, "stderr", None)
            if (exit_code is not None and exit_code != 0) or (status_code is not None and status_code >= 400):
                ref_err_obj = {
                    "status_code": status_code,
                    "exit_code": exit_code,
                    "message": stderr,
                }

        target_err_obj = item.target_error
        if target_err_obj is None and item.target_output:
            out = item.target_output
            status_code = getattr(out, "status_code", None) or getattr(out, "http_status", None)
            exit_code = getattr(out, "exit_code", None)
            stderr = getattr(out, "stderr", None)
            if (exit_code is not None and exit_code != 0) or (status_code is not None and status_code >= 400):
                target_err_obj = {
                    "status_code": status_code,
                    "exit_code": exit_code,
                    "message": stderr,
                }

        ref_has_err = bool(ref_err_obj) or (
            bool(item.reference_output) and getattr(item.reference_output, "exit_code", None) not in (0, None)
        ) or (
            bool(item.reference_output) and (getattr(item.reference_output, "status_code", None) or getattr(item.reference_output, "http_status", None) or 200) >= 400
        )
        target_has_err = bool(target_err_obj) or (
            bool(item.target_output) and getattr(item.target_output, "exit_code", None) not in (0, None)
        ) or (
            bool(item.target_output) and (getattr(item.target_output, "status_code", None) or getattr(item.target_output, "http_status", None) or 200) >= 400
        )

        if BehaviorDimension.ERROR in selected_dimensions:
            error_failures = [
                f for f in item.adaptation_failures
                if f.evidence_type.lower() in ("error", "evidencetype.error")
            ]
            if error_failures:
                failure_reasons = "; ".join([f.reason for f in error_failures])
                fail_eids = [f.evidence_id for f in error_failures if f.evidence_id]
                diff = BehaviorDifference(
                    dimension=BehaviorDimension.ERROR,
                    input_id=item.input_id,
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="adaptation_validation",
                    details={
                        "reason": "ADAPTATION_FAILED",
                        "message": f"Malformed error evidence payload: {failure_reasons}",
                        "failed_evidence_ids": fail_eids,
                    },
                )
                dim_results[BehaviorDimension.ERROR] = DimensionResult(
                    dimension=BehaviorDimension.ERROR,
                    status=EvaluationVerdict.INCONCLUSIVE,
                    verdict=EvaluationVerdict.INCONCLUSIVE,
                    comparison_method="adaptation_validation",
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    differences=[diff],
                    evidence_references=fail_eids or [eid for eid in (ref_eid, target_eid) if eid],
                    details={"reason": "ADAPTATION_FAILED", "message": failure_reasons},
                )
                input_diffs.append(diff)
            else:
                ref_err_status = item.reference_error_status or getattr(item.reference_error, "capture_status", getattr(item.reference_error, "status", None))
                target_err_status = item.target_error_status or getattr(item.target_error, "capture_status", getattr(item.target_error, "status", None))
                res_err = self.error_eval.evaluate(
                    input_id=item.input_id,
                    reference_error=ref_err_obj,
                    target_error=target_err_obj,
                    policy=policy,
                    reference_has_error=ref_has_err,
                    target_has_error=target_has_err,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    reference_status=ref_err_status,
                    target_status=target_err_status,
                )
                dim_results[BehaviorDimension.ERROR] = res_err
                input_diffs.extend(res_err.differences)

        # Evaluate 3: BOUNDARY
        if BehaviorDimension.BOUNDARY in selected_dimensions:
            res_boundary = self.boundary_eval.evaluate(
                input_id=item.input_id,
                boundary_category=item.boundary_category,
                reference_has_error=ref_has_err,
                target_has_error=target_has_err,
                reference_output=item.reference_output,
                target_output=item.target_output,
                reference_error=ref_err_obj,
                target_error=target_err_obj,
                policy=policy,
                reference_evidence_id=ref_eid,
                target_evidence_id=target_eid,
            )
            dim_results[BehaviorDimension.BOUNDARY] = res_boundary
            input_diffs.extend(res_boundary.differences)

        # Evaluate 4: STATE
        if BehaviorDimension.STATE in selected_dimensions:
            state_failures = [
                f for f in item.adaptation_failures
                if f.evidence_type.lower() in (
                    "database", "filesystem", "http",
                    "evidencetype.database", "evidencetype.filesystem", "evidencetype.http"
                )
            ]
            if state_failures:
                failure_reasons = "; ".join([f.reason for f in state_failures])
                fail_eids = [f.evidence_id for f in state_failures if f.evidence_id]
                diff = BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=item.input_id,
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="adaptation_validation",
                    details={
                        "reason": "ADAPTATION_FAILED",
                        "message": f"Malformed state/side-effect evidence payload: {failure_reasons}",
                        "failed_evidence_ids": fail_eids,
                    },
                )
                dim_results[BehaviorDimension.STATE] = DimensionResult(
                    dimension=BehaviorDimension.STATE,
                    status=EvaluationVerdict.INCONCLUSIVE,
                    verdict=EvaluationVerdict.INCONCLUSIVE,
                    comparison_method="adaptation_validation",
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    differences=[diff],
                    evidence_references=fail_eids or [eid for eid in (ref_eid, target_eid) if eid],
                    details={"reason": "ADAPTATION_FAILED", "message": failure_reasons},
                )
                input_diffs.append(diff)
            else:
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
            workflow_failures = [
                f for f in item.adaptation_failures
                if f.evidence_type.lower() in ("trace", "evidencetype.trace")
            ]
            if workflow_failures:
                failure_reasons = "; ".join([f.reason for f in workflow_failures])
                fail_eids = [f.evidence_id for f in workflow_failures if f.evidence_id]
                diff = BehaviorDifference(
                    dimension=BehaviorDimension.WORKFLOW,
                    input_id=item.input_id,
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="adaptation_validation",
                    details={
                        "reason": "ADAPTATION_FAILED",
                        "message": f"Malformed workflow trace evidence payload: {failure_reasons}",
                        "failed_evidence_ids": fail_eids,
                    },
                )
                dim_results[BehaviorDimension.WORKFLOW] = DimensionResult(
                    dimension=BehaviorDimension.WORKFLOW,
                    status=EvaluationVerdict.INCONCLUSIVE,
                    verdict=EvaluationVerdict.INCONCLUSIVE,
                    comparison_method="adaptation_validation",
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    differences=[diff],
                    evidence_references=fail_eids or [eid for eid in (ref_eid, target_eid) if eid],
                    details={"reason": "ADAPTATION_FAILED", "message": failure_reasons},
                )
                input_diffs.append(diff)
            else:
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

        # Check for invalid roles or integrity errors
        if item.invalid_role_records:
            diff = BehaviorDifference(
                dimension=selected_dimensions[0] if selected_dimensions else BehaviorDimension.OUTPUT,
                input_id=item.input_id,
                difference_type=DifferenceType.EVIDENCE_MISSING,
                reference_evidence_id=ref_eid,
                target_evidence_id=target_eid,
                comparison_method="role_validation",
                details={
                    "reason": "INVALID_ROLE",
                    "message": f"Invalid role records detected: {item.invalid_role_records}",
                },
            )
            input_diffs.append(diff)
            for dim in selected_dimensions:
                if dim not in dim_results or dim_results[dim].verdict == EvaluationVerdict.EQUIVALENT:
                    dim_results[dim] = DimensionResult(
                        dimension=dim,
                        status=EvaluationVerdict.ERROR,
                        verdict=EvaluationVerdict.ERROR,
                        comparison_method="role_validation",
                        difference_type=DifferenceType.EVIDENCE_MISSING,
                        differences=[diff],
                        details={"reason": "INVALID_ROLE", "message": f"Invalid role records: {item.invalid_role_records}"},
                    )

        # Compute overall input verdict
        verdicts = [dr.verdict for dr in dim_results.values()]
        if EvaluationVerdict.DIFFERENT in verdicts:
            input_verdict = EvaluationVerdict.DIFFERENT
        elif EvaluationVerdict.ERROR in verdicts or bool(item.invalid_role_records) or not item.integrity_valid:
            input_verdict = EvaluationVerdict.ERROR
        elif EvaluationVerdict.INCONCLUSIVE in verdicts:
            input_verdict = EvaluationVerdict.INCONCLUSIVE
        elif EvaluationVerdict.EQUIVALENT in verdicts:
            input_verdict = EvaluationVerdict.EQUIVALENT
        else:
            input_verdict = EvaluationVerdict.NOT_APPLICABLE

        valid_devs = [dr.deviation for dr in dim_results.values() if dr.deviation is not None]
        if valid_devs:
            item_dev = sum(valid_devs) / len(valid_devs)
        elif input_verdict == EvaluationVerdict.EQUIVALENT:
            item_dev = 0.0
        elif input_verdict in (EvaluationVerdict.DIFFERENT, EvaluationVerdict.ERROR):
            item_dev = 1.0
        else:
            item_dev = 0.0
        item_dev = min(1.0, max(0.0, item_dev))
        item_agreement = 1.0 - item_dev

        return InputEvaluationResult(
            input_id=item.input_id,
            verdict=input_verdict,
            status=input_verdict,
            dimension_results=dim_results,
            differences=input_diffs,
            boundary_category=item.boundary_category,
            reference_evidence_ids=[r.evidence_id for r in item.reference_records],
            target_evidence_ids=[r.evidence_id for r in item.target_records],
            observed_deviation=round(item_dev, 6),
            agreement=round(item_agreement, 6),
        )

    def _compute_summary(
        self,
        input_results: list[InputEvaluationResult],
        all_differences: list[BehaviorDifference],
        integrity_issues: list[str],
        total_items: int,
        selected_dimensions: Optional[list[BehaviorDimension]] = None,
    ) -> EvaluationSummary:
        """Computes summary metrics, counts, and rollups across all input evaluations according to the normative mathematical contract."""
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
        elif err_count > 0:
            overall_verdict = EvaluationVerdict.ERROR
        elif inconcl_count > 0:
            overall_verdict = EvaluationVerdict.INCONCLUSIVE
        elif equiv_count > 0 and (equiv_count + na_count) == len(input_results):
            overall_verdict = EvaluationVerdict.EQUIVALENT
        elif na_count == len(input_results) and len(input_results) > 0:
            overall_verdict = EvaluationVerdict.NOT_APPLICABLE
        elif not input_results:
            overall_verdict = EvaluationVerdict.NOT_APPLICABLE
        else:
            overall_verdict = EvaluationVerdict.INCONCLUSIVE

        # Dimension breakdown summaries & Normative Dimension Scoring
        dim_summaries: dict[BehaviorDimension, DimensionEvaluationSummary] = {}
        target_dims = selected_dimensions or list(BehaviorDimension)
        for dim in BehaviorDimension:
            if dim in target_dims:
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

                # Normative contract: MeanDeviation_d and DimensionScore_d = 1 - MeanDeviation_d
                n_d = len(dim_results)
                if n_d > 0:
                    devs = []
                    for dr in dim_results:
                        if dr.deviation is not None:
                            devs.append(dr.deviation)
                        elif dr.verdict == EvaluationVerdict.EQUIVALENT:
                            devs.append(0.0)
                        elif dr.verdict in (EvaluationVerdict.DIFFERENT, EvaluationVerdict.ERROR, EvaluationVerdict.INCONCLUSIVE):
                            devs.append(1.0)
                        else:
                            devs.append(0.0)
                    mean_dev = sum(devs) / n_d
                    dim_score = max(0.0, min(1.0, 1.0 - mean_dev))
                    is_available = True
                else:
                    mean_dev = None
                    dim_score = None
                    is_available = False

                dim_summaries[dim] = DimensionEvaluationSummary(
                    dimension=dim,
                    total_evaluated=n_d,
                    equivalent_count=d_equiv,
                    different_count=d_diff,
                    inconclusive_count=d_inconcl,
                    not_applicable_count=d_na,
                    overall_verdict=dim_verdict,
                    mean_deviation=round(mean_dev, 6) if mean_dev is not None else None,
                    dimension_score=round(dim_score, 6) if dim_score is not None else None,
                    is_available=is_available,
                )
            else:
                dim_summaries[dim] = DimensionEvaluationSummary(
                    dimension=dim,
                    total_evaluated=0,
                    equivalent_count=0,
                    different_count=0,
                    inconclusive_count=0,
                    not_applicable_count=0,
                    overall_verdict=EvaluationVerdict.NOT_APPLICABLE,
                    mean_deviation=None,
                    dimension_score=None,
                    is_available=False,
                )

        # Difference counts
        diff_by_type: dict[str, int] = {}
        diff_by_dim: dict[str, int] = {}
        for diff in all_differences:
            t_name = diff.difference_type.value if hasattr(diff.difference_type, "value") else str(diff.difference_type)
            d_name = diff.dimension.value if hasattr(diff.dimension, "value") else str(diff.dimension)
            diff_by_type[t_name] = diff_by_type.get(t_name, 0) + 1
            diff_by_dim[d_name] = diff_by_dim.get(d_name, 0) + 1

        # Dynamic Behavioral Score Calculation (Patent-Facing Spec)
        available_dims = [
            dim for dim in target_dims
            if dim_summaries[dim].is_available and dim_summaries[dim].dimension_score is not None
        ]
        dim_scores: dict[str, float] = {}
        scoring_weights: dict[str, float] = {}
        if available_dims:
            weight_val = round(1.0 / len(available_dims), 6)
            for dim in available_dims:
                d_val = dim_summaries[dim].dimension_score
                if d_val is not None:
                    dim_scores[dim.value] = d_val
                    scoring_weights[dim.value] = weight_val
            # Normalize weights to sum exactly to 1.0
            total_w = sum(scoring_weights.values())
            if total_w > 0.0:
                scoring_weights = {k: v / total_w for k, v in scoring_weights.items()}
            behavioral_score = sum(scoring_weights[k] * dim_scores[k] for k in dim_scores)
            behavioral_score = max(0.0, min(1.0, behavioral_score))
        else:
            behavioral_score = 1.0 if not input_results else 0.0

        observed_dev = max(0.0, min(1.0, 1.0 - behavioral_score))
        percentage_score = round(100.0 * behavioral_score, 2)

        # Coverage: ObservedComparableCells / RequiredComparableCells
        req_cells = total_items * len(target_dims) if total_items > 0 else 0
        obs_cells = sum(
            len([dr for dr in r.dimension_results.values() if dr.verdict != EvaluationVerdict.NOT_APPLICABLE])
            for r in input_results
        )
        coverage = (obs_cells / req_cells) if req_cells > 0 else 1.0
        coverage = max(0.0, min(1.0, coverage))

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
            dimension_scores=dim_scores,
            behavioral_score=round(behavioral_score, 6),
            observed_deviation=round(observed_dev, 6),
            percentage_score=percentage_score,
            scoring_weights={k: round(v, 6) for k, v in scoring_weights.items()},
            coverage=round(coverage, 6),
        )

    def _compute_evaluation_hash(
        self,
        result: EvaluationResult,
        selected_dimensions: Optional[list[BehaviorDimension]] = None,
    ) -> str:
        """Computes deterministic SHA-256 fingerprint over canonical evaluation content."""
        canonical_diffs = []
        for d in result.differences:
            canonical_diffs.append({
                "dimension": d.dimension.value if hasattr(d.dimension, "value") else str(d.dimension),
                "input_id": d.input_id,
                "difference_type": d.difference_type.value if hasattr(d.difference_type, "value") else str(d.difference_type),
                "field_path": d.field_path,
                "reference_value": d.reference_value,
                "target_value": d.target_value,
                "reference_evidence_id": d.reference_evidence_id,
                "target_evidence_id": d.target_evidence_id,
                "comparison_method": d.comparison_method,
                "details": d.details,
            })
        canonical_diffs.sort(key=lambda x: (x["input_id"], x["dimension"], x["difference_type"], str(x["field_path"])))

        canonical_inputs = []
        for inp in result.input_results:
            dim_res_canonical = {}
            for k, dr in inp.dimension_results.items():
                k_str = k.value if hasattr(k, "value") else str(k)
                dim_res_canonical[k_str] = {
                    "verdict": dr.verdict.value if hasattr(dr.verdict, "value") else str(dr.verdict),
                    "comparison_method": dr.comparison_method,
                    "difference_type": dr.difference_type.value if hasattr(dr.difference_type, "value") and dr.difference_type else (str(dr.difference_type) if dr.difference_type else None),
                }
            canonical_inputs.append({
                "input_id": inp.input_id,
                "verdict": inp.verdict.value if hasattr(inp.verdict, "value") else str(inp.verdict),
                "boundary_category": inp.boundary_category,
                "dimensions": dim_res_canonical,
            })
        canonical_inputs.sort(key=lambda x: x["input_id"])

        dim_names = [d.value if hasattr(d, "value") else str(d) for d in (selected_dimensions or list(BehaviorDimension))]
        dim_names.sort()

        canonical_dict = {
            "bundle_id": result.bundle_id or "",
            "application_id": result.application_id or "",
            "bundle_hash": result.bundle_hash or "",
            "policy_id": result.policy_id,
            "policy_hash": result.policy_hash,
            "selected_dimensions": dim_names,
            "verdict": result.verdict.value if hasattr(result.verdict, "value") else str(result.verdict),
            "summary": {
                "total_inputs": result.summary.total_inputs,
                "evaluated_inputs": result.summary.evaluated_inputs,
                "equivalent_inputs": result.summary.equivalent_inputs,
                "different_inputs": result.summary.different_inputs,
                "inconclusive_inputs": result.summary.inconclusive_inputs,
                "error_inputs": result.summary.error_inputs,
                "not_applicable_inputs": result.summary.not_applicable_inputs,
                "overall_verdict": result.summary.overall_verdict.value if hasattr(result.summary.overall_verdict, "value") else str(result.summary.overall_verdict),
                "total_differences": result.summary.total_differences,
                "behavioral_score": round(float(getattr(result.summary, "behavioral_score", 1.0)), 6),
                "observed_deviation": round(float(getattr(result.summary, "observed_deviation", 0.0)), 6),
                "coverage": round(float(getattr(result.summary, "coverage", 1.0)), 6),
            },
            "inputs": canonical_inputs,
            "differences": canonical_diffs,
        }
        canonical_str = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


behavioral_evaluation_engine = BehavioralEvaluationEngine()
