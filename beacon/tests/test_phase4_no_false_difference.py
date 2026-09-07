"""BEACON V2 — Phase 4: Elimination of False Difference.

Validates that missing, incomplete, or absent evidence yields INCONCLUSIVE,
never a false DIFFERENT verdict.
"""

import pytest

from evaluation.evaluators import (
    BoundaryEvaluator,
    ErrorEvaluator,
    NonfunctionalEvaluator,
    OutputEvaluator,
    StateEvaluator,
    WorkflowEvaluator,
)
from evaluation.models import (
    DifferenceType,
    EvaluationVerdict,
)
from evaluation.policies import (
    ComparisonPolicy,
    DEFAULT_COMPARISON_POLICY,
    NonfunctionalComparisonPolicy,
)
from execution.evidence_models import (
    DatabaseEvidence,
    EvidenceCaptureStatus,
    FileEvidence,
    FileStateSnapshot,
    HttpEvidence,
    TraceEvent,
    TraceEvidence,
)


class TestPhase4NoFalseDifference:
    """Suite verifying no false DIFFERENT verdict is returned when evidence is merely insufficient."""

    @pytest.fixture
    def policy(self):
        return DEFAULT_COMPARISON_POLICY

    def test_db_missing_row_count_yields_inconclusive_not_different(self, policy):
        evaluator = StateEvaluator()
        ref_db = DatabaseEvidence(
            configured_tables=["customers"],
            table_row_counts_before={"customers": 10},
            table_row_counts_after={"customers": 15},
            status=EvidenceCaptureStatus.CAPTURED,
        )
        tgt_db = DatabaseEvidence(
            configured_tables=["customers"],
            table_row_counts_before={"customers": 10},
            table_row_counts_after={},  # row count omitted
            status=EvidenceCaptureStatus.CAPTURED,
        )
        res = evaluator.evaluate("in_nfd_db", reference_db_or_records=ref_db, target_db_or_records=tgt_db, policy=policy)
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.verdict != EvaluationVerdict.DIFFERENT
        assert any(d.difference_type == DifferenceType.EVIDENCE_MISSING for d in res.differences)

    def test_file_missing_hash_yields_inconclusive_not_different(self, policy):
        evaluator = StateEvaluator()
        ref_fs = FileEvidence(
            configured_paths=["/log.txt"],
            after_state={"/log.txt": FileStateSnapshot(path="/log.txt", exists=True, size_bytes=50, sha256_hash="H_LOG")},
            status=EvidenceCaptureStatus.CAPTURED,
        )
        tgt_fs = FileEvidence(
            configured_paths=["/log.txt"],
            after_state={"/log.txt": FileStateSnapshot(path="/log.txt", exists=True, size_bytes=50, sha256_hash=None)},
            status=EvidenceCaptureStatus.CAPTURED,
        )
        res = evaluator.evaluate("in_nfd_fs", reference_db_or_records=None, target_db_or_records=None, reference_file=ref_fs, target_file=tgt_fs, policy=policy)
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.verdict != EvaluationVerdict.DIFFERENT

    def test_http_missing_field_yields_inconclusive_not_different(self, policy):
        evaluator = StateEvaluator()
        ref_http = HttpEvidence(calls=[{"method": "GET", "url": "/items", "status": 200}])
        tgt_http = HttpEvidence(calls=[{"method": "GET"}])  # url and status missing
        res = evaluator.evaluate("in_nfd_http", reference_db_or_records=None, target_db_or_records=None, reference_http=ref_http, target_http=tgt_http, policy=policy)
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.verdict != EvaluationVerdict.DIFFERENT

    def test_workflow_missing_trace_yields_inconclusive_not_different(self, policy):
        evaluator = WorkflowEvaluator()
        ref_tr = TraceEvidence(events=[TraceEvent(event_id="e1", sequence=1, event_type="START")])
        tgt_tr = None
        res = evaluator.evaluate("in_nfd_wf", reference_trace=ref_tr, target_trace=tgt_tr, policy=policy)
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.verdict != EvaluationVerdict.DIFFERENT

    def test_nonfunctional_missing_metric_yields_inconclusive_not_different(self):
        evaluator = NonfunctionalEvaluator()
        active_policy = ComparisonPolicy(
            policy_id="nf_policy",
            nonfunctional_policy=NonfunctionalComparisonPolicy(enabled=True),
        )
        res = evaluator.evaluate("in_nfd_nf", reference_duration_ms=None, target_duration_ms=200.0, policy=active_policy)
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.verdict != EvaluationVerdict.DIFFERENT
