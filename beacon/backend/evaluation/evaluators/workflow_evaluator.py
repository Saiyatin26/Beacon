"""BEACON V2 — Phase 4 Workflow & Sequence Evaluator.

Evaluates observable execution sequence equivalence, comparing ordered trace events
and filtering non-deterministic internal system noise.
"""

from typing import Any, Optional

from ..models import (
    BehaviorDifference,
    BehaviorDimension,
    DifferenceType,
    DimensionResult,
    EvaluationVerdict,
)
from ..policies import ComparisonPolicy, WorkflowComparisonPolicy


class WorkflowEvaluator:
    """Evaluates observable workflow and event sequence equivalence."""

    def evaluate(
        self,
        input_id: str,
        reference_trace: Optional[Any],
        target_trace: Optional[Any],
        policy: ComparisonPolicy,
        reference_evidence_id: Optional[str] = None,
        target_evidence_id: Optional[str] = None,
    ) -> DimensionResult:
        """Evaluates observable event sequences between Reference and Target."""
        wf_policy = policy.workflow_policy
        evidence_refs = [eid for eid in (reference_evidence_id, target_evidence_id) if eid]

        if reference_trace is None and target_trace is None:
            return DimensionResult(
                dimension=BehaviorDimension.WORKFLOW,
                status=EvaluationVerdict.NOT_APPLICABLE,
                verdict=EvaluationVerdict.NOT_APPLICABLE,
                comparison_method="none",
                details={"message": "No workflow or trace evidence recorded for either implementation."},
            )

        if reference_trace is None or target_trace is None:
            diff = BehaviorDifference(
                dimension=BehaviorDimension.WORKFLOW,
                input_id=input_id,
                difference_type=DifferenceType.WORKFLOW_SEQUENCE_MISMATCH,
                reference_evidence_id=reference_evidence_id,
                target_evidence_id=target_evidence_id,
                reference_value=bool(reference_trace),
                target_value=bool(target_trace),
                comparison_method="presence_check",
                details={
                    "message": "Workflow trace recorded for one implementation but absent for the other.",
                    "reference_present": reference_trace is not None,
                    "target_present": target_trace is not None,
                },
            )
            return DimensionResult(
                dimension=BehaviorDimension.WORKFLOW,
                status=EvaluationVerdict.DIFFERENT,
                verdict=EvaluationVerdict.DIFFERENT,
                comparison_method="presence_check",
                difference_type=DifferenceType.WORKFLOW_SEQUENCE_MISMATCH,
                differences=[diff],
                evidence_references=evidence_refs,
            )

        # Extract sequence of observable event names / stages
        ref_events = self._extract_events(reference_trace, wf_policy.filter_internal_events)
        target_events = self._extract_events(target_trace, wf_policy.filter_internal_events)

        if not ref_events and not target_events:
            return DimensionResult(
                dimension=BehaviorDimension.WORKFLOW,
                status=EvaluationVerdict.EQUIVALENT,
                verdict=EvaluationVerdict.EQUIVALENT,
                comparison_method="empty_sequences",
                evidence_references=evidence_refs,
                details={"message": "No external observable events in trace; both sequences empty."},
            )

        differences: list[BehaviorDifference] = []

        if wf_policy.sequence_matching == "exact":
            if ref_events != target_events:
                diff_type = (
                    DifferenceType.WORKFLOW_ORDER_MISMATCH
                    if sorted(ref_events) == sorted(target_events)
                    else DifferenceType.WORKFLOW_SEQUENCE_MISMATCH
                )
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.WORKFLOW,
                        input_id=input_id,
                        difference_type=diff_type,
                        field_path="trace.events",
                        reference_value=ref_events,
                        target_value=target_events,
                        reference_evidence_id=reference_evidence_id,
                        target_evidence_id=target_evidence_id,
                        comparison_method="exact_sequence",
                        details={
                            "reference_events": ref_events,
                            "target_events": target_events,
                        },
                    )
                )

        if not differences:
            return DimensionResult(
                dimension=BehaviorDimension.WORKFLOW,
                status=EvaluationVerdict.EQUIVALENT,
                verdict=EvaluationVerdict.EQUIVALENT,
                reference_value=ref_events,
                target_value=target_events,
                comparison_method="sequence_match",
                evidence_references=evidence_refs,
                details={"message": "Observable workflow execution sequences match."},
            )

        return DimensionResult(
            dimension=BehaviorDimension.WORKFLOW,
            status=EvaluationVerdict.DIFFERENT,
            verdict=EvaluationVerdict.DIFFERENT,
            reference_value=ref_events,
            target_value=target_events,
            comparison_method="sequence_match",
            difference_type=differences[0].difference_type,
            differences=differences,
            evidence_references=evidence_refs,
            details={"total_differences": len(differences)},
        )

    def _extract_events(self, trace_obj: Any, filter_internal: bool) -> list[str]:
        # Support TraceEvidencePayload.call_sequence as a direct string list
        call_seq = getattr(trace_obj, "call_sequence", None)
        if call_seq is not None and isinstance(call_seq, list):
            if all(isinstance(e, str) for e in call_seq):
                return list(call_seq)

        raw_events = (
            getattr(trace_obj, "events", None)
            or getattr(trace_obj, "spans", None)
            or getattr(trace_obj, "stages", None)
            or []
        )

        extracted: list[str] = []
        for ev in raw_events:
            name = ""
            if isinstance(ev, dict):
                name = ev.get("name") or ev.get("event") or ev.get("stage") or ""
            elif isinstance(ev, str):
                name = ev
            elif hasattr(ev, "name"):
                name = getattr(ev, "name") or ""

            if filter_internal:
                # Filter internal harness noise
                if name.startswith("internal_") or name.startswith("harness_") or name == "timer":
                    continue

            if name:
                extracted.append(name)

        return extracted


workflow_evaluator = WorkflowEvaluator()
