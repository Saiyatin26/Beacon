"""BEACON V2 — Phase 4: Elimination of False Equivalence.

Validates that missing, incomplete, partial, or unsupported evidence never yields EQUIVALENT.
Any missing required observable evidence must yield INCONCLUSIVE.
"""

import pytest

from evaluation.engine import BehavioralEvaluationEngine
from evaluation.evaluators import (
    BoundaryEvaluator,
    ErrorEvaluator,
    NonfunctionalEvaluator,
    OutputEvaluator,
    StateEvaluator,
    WorkflowEvaluator,
)
from evaluation.models import (
    BehaviorDimension,
    DifferenceType,
    EvaluationVerdict,
)
from evaluation.policies import (
    ComparisonPolicy,
    DEFAULT_COMPARISON_POLICY,
    NonfunctionalComparisonPolicy,
    resolve_comparison_policy,
)
from execution.evidence_models import (
    DatabaseEvidence,
    ErrorEvidence,
    EvidenceBundle,
    EvidenceCaptureStatus,
    EvidenceManifest,
    EvidenceRecord,
    EvidenceType,
    FileEvidence,
    FileStateSnapshot,
    HttpEvidence,
    OutputEvidence,
    TraceEvent,
    TraceEvidence,
)


class TestPhase4NoFalseEquivalence:
    """Suite verifying no false EQUIVALENT verdict is ever returned on missing/partial evidence."""

    @pytest.fixture
    def policy(self):
        return DEFAULT_COMPARISON_POLICY

    # 1. DATABASE FALSE-EQUIVALENCE ELIMINATION
    def test_db_test_a_partial_vs_partial_inconclusive(self, policy):
        """Test A: Reference = PARTIAL, Target = PARTIAL -> INCONCLUSIVE."""
        evaluator = StateEvaluator()
        ref_db = DatabaseEvidence(
            configured_tables=["customers"],
            status=EvidenceCaptureStatus.PARTIAL,
        )
        tgt_db = DatabaseEvidence(
            configured_tables=["customers"],
            status=EvidenceCaptureStatus.PARTIAL,
        )
        res = evaluator.evaluate("in_db_part_a", reference_db_or_records=ref_db, target_db_or_records=tgt_db, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_db_test_b_captured_vs_partial_inconclusive(self, policy):
        """Test B: Reference = CAPTURED, Target = PARTIAL -> INCONCLUSIVE."""
        evaluator = StateEvaluator()
        ref_db = DatabaseEvidence(
            configured_tables=["customers"],
            table_row_counts_before={"customers": 5},
            table_row_counts_after={"customers": 5},
            status=EvidenceCaptureStatus.CAPTURED,
        )
        tgt_db = DatabaseEvidence(
            configured_tables=["customers"],
            status=EvidenceCaptureStatus.PARTIAL,
        )
        res = evaluator.evaluate("in_db_part_b", reference_db_or_records=ref_db, target_db_or_records=tgt_db, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_db_test_c_partial_vs_captured_inconclusive(self, policy):
        """Test C: Reference = PARTIAL, Target = CAPTURED -> INCONCLUSIVE."""
        evaluator = StateEvaluator()
        ref_db = DatabaseEvidence(
            configured_tables=["customers"],
            status=EvidenceCaptureStatus.PARTIAL,
        )
        tgt_db = DatabaseEvidence(
            configured_tables=["customers"],
            table_row_counts_before={"customers": 5},
            table_row_counts_after={"customers": 5},
            status=EvidenceCaptureStatus.CAPTURED,
        )
        res = evaluator.evaluate("in_db_part_c", reference_db_or_records=ref_db, target_db_or_records=tgt_db, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_db_test_d_partial_vs_not_supported_inconclusive(self, policy):
        """Test D: Reference = PARTIAL, Target = NOT_SUPPORTED -> INCONCLUSIVE."""
        evaluator = StateEvaluator()
        ref_db = DatabaseEvidence(
            configured_tables=["customers"],
            status=EvidenceCaptureStatus.PARTIAL,
        )
        tgt_db = DatabaseEvidence(
            configured_tables=["customers"],
            status=EvidenceCaptureStatus.NOT_SUPPORTED,
        )
        res = evaluator.evaluate("in_db_part_d", reference_db_or_records=ref_db, target_db_or_records=tgt_db, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_db_test_e_partial_with_observed_difference_yields_different(self, policy):
        """Test E: Reference = PARTIAL, Target = observed difference (row count mismatch) -> DIFFERENT."""
        evaluator = StateEvaluator()
        ref_db = DatabaseEvidence(
            configured_tables=["customers"],
            table_row_counts_before={"customers": 5},
            table_row_counts_after={"customers": 10},
            status=EvidenceCaptureStatus.PARTIAL,
        )
        tgt_db = DatabaseEvidence(
            configured_tables=["customers"],
            table_row_counts_before={"customers": 5},
            table_row_counts_after={"customers": 20},
            status=EvidenceCaptureStatus.CAPTURED,
        )
        res = evaluator.evaluate("in_db_part_e", reference_db_or_records=ref_db, target_db_or_records=tgt_db, policy=policy)
        assert res.verdict == EvaluationVerdict.DIFFERENT
        assert any(d.difference_type == DifferenceType.DATABASE_ROW_COUNT_MISMATCH for d in res.differences)

    def test_db_missing_row_count_not_equivalent(self, policy):
        evaluator = StateEvaluator()
        ref_db = DatabaseEvidence(
            configured_tables=["customers"],
            table_row_counts_before={"customers": 5},
            table_row_counts_after={"customers": 10},
            status=EvidenceCaptureStatus.CAPTURED,
        )
        tgt_db = DatabaseEvidence(
            configured_tables=["customers"],
            table_row_counts_before={"customers": 5},
            table_row_counts_after={},  # missing after count
            status=EvidenceCaptureStatus.CAPTURED,
        )
        res = evaluator.evaluate("in_db_1", reference_db_or_records=ref_db, target_db_or_records=tgt_db, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert any(d.difference_type == DifferenceType.EVIDENCE_MISSING for d in res.differences)

    def test_db_missing_snapshot_not_equivalent(self, policy):
        evaluator = StateEvaluator()
        ref_db = DatabaseEvidence(
            configured_tables=["customers"],
            table_row_counts_before={"customers": 5},
            table_row_counts_after={"customers": 5},
            snapshot_after={"hash": "H1"},
            status=EvidenceCaptureStatus.CAPTURED,
        )
        tgt_db = DatabaseEvidence(
            configured_tables=["customers"],
            table_row_counts_before={"customers": 5},
            table_row_counts_after={"customers": 5},
            snapshot_after=None,  # missing snapshot
            status=EvidenceCaptureStatus.CAPTURED,
        )
        res = evaluator.evaluate("in_db_2", reference_db_or_records=ref_db, target_db_or_records=tgt_db, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_db_not_supported_status_not_equivalent(self, policy):
        evaluator = StateEvaluator()
        ref_db = DatabaseEvidence(
            configured_tables=["customers"],
            status=EvidenceCaptureStatus.NOT_SUPPORTED,
        )
        tgt_db = DatabaseEvidence(
            configured_tables=["customers"],
            status=EvidenceCaptureStatus.NOT_SUPPORTED,
        )
        res = evaluator.evaluate("in_db_3", reference_db_or_records=ref_db, target_db_or_records=tgt_db, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_db_capture_error_and_configuration_error_inconclusive(self, policy):
        evaluator = StateEvaluator()
        ref_db = DatabaseEvidence(status=EvidenceCaptureStatus.CONFIGURATION_ERROR)
        tgt_db = DatabaseEvidence(status=EvidenceCaptureStatus.CAPTURE_ERROR)
        res = evaluator.evaluate("in_db_err", reference_db_or_records=ref_db, target_db_or_records=tgt_db, policy=policy)
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    # 2. FILESYSTEM FALSE-EQUIVALENCE ELIMINATION
    def test_file_test_a_partial_vs_partial_inconclusive(self, policy):
        """Test A: Reference = PARTIAL, Target = PARTIAL -> INCONCLUSIVE."""
        evaluator = StateEvaluator()
        ref_fs = FileEvidence(configured_paths=["/tmp/a.txt"], status=EvidenceCaptureStatus.PARTIAL)
        tgt_fs = FileEvidence(configured_paths=["/tmp/a.txt"], status=EvidenceCaptureStatus.PARTIAL)
        res = evaluator.evaluate("in_fs_part_a", reference_db_or_records=None, target_db_or_records=None, reference_file=ref_fs, target_file=tgt_fs, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_file_test_b_captured_vs_partial_inconclusive(self, policy):
        """Test B: Reference = CAPTURED, Target = PARTIAL -> INCONCLUSIVE."""
        evaluator = StateEvaluator()
        ref_fs = FileEvidence(
            configured_paths=["/tmp/a.txt"],
            after_state={"/tmp/a.txt": FileStateSnapshot(path="/tmp/a.txt", exists=True, size_bytes=10, sha256_hash="H_A")},
            status=EvidenceCaptureStatus.CAPTURED,
        )
        tgt_fs = FileEvidence(configured_paths=["/tmp/a.txt"], status=EvidenceCaptureStatus.PARTIAL)
        res = evaluator.evaluate("in_fs_part_b", reference_db_or_records=None, target_db_or_records=None, reference_file=ref_fs, target_file=tgt_fs, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_file_test_c_partial_vs_captured_inconclusive(self, policy):
        """Test C: Reference = PARTIAL, Target = CAPTURED -> INCONCLUSIVE."""
        evaluator = StateEvaluator()
        ref_fs = FileEvidence(configured_paths=["/tmp/a.txt"], status=EvidenceCaptureStatus.PARTIAL)
        tgt_fs = FileEvidence(
            configured_paths=["/tmp/a.txt"],
            after_state={"/tmp/a.txt": FileStateSnapshot(path="/tmp/a.txt", exists=True, size_bytes=10, sha256_hash="H_A")},
            status=EvidenceCaptureStatus.CAPTURED,
        )
        res = evaluator.evaluate("in_fs_part_c", reference_db_or_records=None, target_db_or_records=None, reference_file=ref_fs, target_file=tgt_fs, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_file_test_d_not_supported_vs_not_supported_inconclusive(self, policy):
        """Test D: Reference = NOT_SUPPORTED, Target = NOT_SUPPORTED -> INCONCLUSIVE."""
        evaluator = StateEvaluator()
        ref_fs = FileEvidence(status=EvidenceCaptureStatus.NOT_SUPPORTED)
        tgt_fs = FileEvidence(status=EvidenceCaptureStatus.NOT_SUPPORTED)
        res = evaluator.evaluate("in_fs_part_d", reference_db_or_records=None, target_db_or_records=None, reference_file=ref_fs, target_file=tgt_fs, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_file_test_e_partial_with_observed_hash_difference_yields_different(self, policy):
        """Test E: Reference = PARTIAL, Target = observed hash difference -> DIFFERENT."""
        evaluator = StateEvaluator()
        ref_fs = FileEvidence(
            configured_paths=["/tmp/a.txt"],
            after_state={"/tmp/a.txt": FileStateSnapshot(path="/tmp/a.txt", exists=True, size_bytes=10, sha256_hash="H_A")},
            status=EvidenceCaptureStatus.PARTIAL,
        )
        tgt_fs = FileEvidence(
            configured_paths=["/tmp/a.txt"],
            after_state={"/tmp/a.txt": FileStateSnapshot(path="/tmp/a.txt", exists=True, size_bytes=10, sha256_hash="H_B")},
            status=EvidenceCaptureStatus.CAPTURED,
        )
        res = evaluator.evaluate("in_fs_part_e", reference_db_or_records=None, target_db_or_records=None, reference_file=ref_fs, target_file=tgt_fs, policy=policy)
        assert res.verdict == EvaluationVerdict.DIFFERENT
        assert any(d.difference_type == DifferenceType.FILESYSTEM_DELTA_MISMATCH for d in res.differences)

    def test_file_missing_after_hash_not_equivalent(self, policy):
        evaluator = StateEvaluator()
        ref_fs = FileEvidence(
            configured_paths=["/data/report.pdf"],
            after_state={"/data/report.pdf": FileStateSnapshot(path="/data/report.pdf", exists=True, size_bytes=100, sha256_hash="HASH_A")},
            status=EvidenceCaptureStatus.CAPTURED,
        )
        tgt_fs = FileEvidence(
            configured_paths=["/data/report.pdf"],
            after_state={"/data/report.pdf": FileStateSnapshot(path="/data/report.pdf", exists=True, size_bytes=100, sha256_hash=None)},  # missing hash
            status=EvidenceCaptureStatus.CAPTURED,
        )
        res = evaluator.evaluate("in_fs_1", reference_db_or_records=None, target_db_or_records=None, reference_file=ref_fs, target_file=tgt_fs, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_file_missing_path_state_not_equivalent(self, policy):
        evaluator = StateEvaluator()
        ref_fs = FileEvidence(
            configured_paths=["/data/report.pdf"],
            after_state={"/data/report.pdf": FileStateSnapshot(path="/data/report.pdf", exists=True, size_bytes=100, sha256_hash="HASH_A")},
            status=EvidenceCaptureStatus.CAPTURED,
        )
        tgt_fs = FileEvidence(
            configured_paths=["/data/report.pdf"],
            after_state={},  # empty after state map
            status=EvidenceCaptureStatus.CAPTURED,
        )
        res = evaluator.evaluate("in_fs_2", reference_db_or_records=None, target_db_or_records=None, reference_file=ref_fs, target_file=tgt_fs, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_file_not_supported_status_not_equivalent(self, policy):
        evaluator = StateEvaluator()
        ref_fs = FileEvidence(status=EvidenceCaptureStatus.NOT_SUPPORTED)
        tgt_fs = FileEvidence(status=EvidenceCaptureStatus.NOT_SUPPORTED)
        res = evaluator.evaluate("in_fs_3", reference_db_or_records=None, target_db_or_records=None, reference_file=ref_fs, target_file=tgt_fs, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    # 3. HTTP FALSE-EQUIVALENCE ELIMINATION
    def test_http_partial_status_not_equivalent(self, policy):
        evaluator = StateEvaluator()
        ref_http = {"calls": [{"method": "GET", "url": "/api/users", "status": 200}], "status": EvidenceCaptureStatus.PARTIAL}
        tgt_http = {"calls": [{"method": "GET", "url": "/api/users", "status": 200}], "status": EvidenceCaptureStatus.PARTIAL}
        res = evaluator.evaluate("in_http_part", reference_db_or_records=None, target_db_or_records=None, reference_http=ref_http, target_http=tgt_http, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_http_missing_method_not_equivalent(self, policy):
        evaluator = StateEvaluator()
        ref_http = HttpEvidence(calls=[{"method": "POST", "url": "/api/item", "status": 200}])
        tgt_http = HttpEvidence(calls=[{"url": "/api/item", "status": 200}])  # method missing
        res = evaluator.evaluate("in_http_1", reference_db_or_records=None, target_db_or_records=None, reference_http=ref_http, target_http=tgt_http, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_http_missing_url_not_equivalent(self, policy):
        evaluator = StateEvaluator()
        ref_http = HttpEvidence(calls=[{"method": "POST", "url": "/api/item", "status": 200}])
        tgt_http = HttpEvidence(calls=[{"method": "POST", "status": 200}])  # url missing
        res = evaluator.evaluate("in_http_2", reference_db_or_records=None, target_db_or_records=None, reference_http=ref_http, target_http=tgt_http, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    # 4. OUTPUT FALSE-EQUIVALENCE ELIMINATION
    def test_output_missing_vs_null_not_equivalent(self, policy):
        evaluator = OutputEvaluator()
        # Reference has explicit payload None, Target output evidence record is missing entirely
        res = evaluator.evaluate("in_out_1", reference_payload=None, target_payload=None, policy=policy, reference_present=True, target_present=False)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    # 5. ERROR FALSE-EQUIVALENCE ELIMINATION
    def test_error_missing_details_not_equivalent(self, policy):
        evaluator = ErrorEvaluator()
        ref_err = {"message": "Database connection failed", "status_code": 500, "category": "DATABASE"}
        tgt_err = {}  # error exists but all details missing
        res = evaluator.evaluate("in_err_1", reference_error=ref_err, target_error=tgt_err, policy=policy, reference_has_error=True, target_has_error=True)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    # 6. WORKFLOW FALSE-EQUIVALENCE ELIMINATION
    def test_workflow_missing_trace_not_equivalent(self, policy):
        evaluator = WorkflowEvaluator()
        ref_tr = TraceEvidence(events=[TraceEvent(event_id="e1", sequence=1, event_type="INIT")])
        tgt_tr = None  # trace missing entirely
        res = evaluator.evaluate("in_wf_1", reference_trace=ref_tr, target_trace=tgt_tr, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_workflow_partial_status_not_equivalent(self, policy):
        evaluator = WorkflowEvaluator()
        ref_tr = {"events": [{"name": "STEP1"}], "status": EvidenceCaptureStatus.PARTIAL}
        tgt_tr = {"events": [{"name": "STEP1"}], "status": EvidenceCaptureStatus.PARTIAL}
        res = evaluator.evaluate("in_wf_part", reference_trace=ref_tr, target_trace=tgt_tr, policy=policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    # 7. NONFUNCTIONAL FALSE-EQUIVALENCE ELIMINATION
    def test_nonfunctional_missing_metric_not_equivalent(self):
        evaluator = NonfunctionalEvaluator()
        active_policy = ComparisonPolicy(
            policy_id="nf_policy",
            nonfunctional_policy=NonfunctionalComparisonPolicy(enabled=True),
        )
        res = evaluator.evaluate("in_nf_1", reference_duration_ms=150.0, target_duration_ms=None, policy=active_policy)
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    # 8. MISSING EXECUTION ACROSS ALL DIMENSIONS
    def test_missing_target_execution_all_dimensions_inconclusive(self, policy):
        session_id = "sess_no_false_eq"
        app_id = "app_no_false_eq"
        recs = [
            EvidenceRecord(
                evidence_id="rec_r1",
                session_id=session_id,
                input_id="inp_missing_tgt",
                role="reference",
                evidence_type=EvidenceType.OUTPUT,
                payload={"raw_output": {"data": 123}, "normalized_output": {"data": 123}},
            ),
        ]
        bundle = EvidenceBundle(
            bundle_id="bnd_missing_tgt",
            session_id=session_id,
            correlation_id="c_missing",
            application_id=app_id,
            input_set_id="is_missing",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_missing", application_id=app_id, input_set_id="is_missing", input_set_hash="h_missing", records=recs),
            records=recs,
        )
        engine = BehavioralEvaluationEngine()
        dims = [
            BehaviorDimension.OUTPUT,
            BehaviorDimension.ERROR,
            BehaviorDimension.STATE,
            BehaviorDimension.WORKFLOW,
        ]
        res = engine.evaluate_bundle(bundle, policy=policy, dimensions=dims)
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert len(res.input_results) == 1
        inp_res = res.input_results[0]
        for dim in dims:
            assert inp_res.dimension_results[dim].verdict == EvaluationVerdict.INCONCLUSIVE
