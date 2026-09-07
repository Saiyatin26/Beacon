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

    # 9. END-TO-END EVIDENCEBUNDLE CAPTURE_STATUS INTEGRATION TESTS
    def test_e2e_partial_output_yields_inconclusive(self, policy):
        """Section 16: Ref & Target Output capture_status=PARTIAL -> INCONCLUSIVE."""
        session_id = "sess_e2e_part_out"
        app_id = "app_e2e_1"
        rec_r = EvidenceRecord(
            evidence_id="r_part_out",
            session_id=session_id,
            input_id="in_part_1",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.PARTIAL,
            payload={"raw_output": {"x": 1}, "normalized_output": {"x": 1}},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_part_out",
            session_id=session_id,
            input_id="in_part_1",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.PARTIAL,
            payload={"raw_output": {"x": 1}, "normalized_output": {"x": 1}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_part_out",
            session_id=session_id,
            correlation_id="c_part",
            application_id=app_id,
            input_set_id="is_part",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_part", application_id=app_id, input_set_id="is_part", input_set_hash="h_part", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )
        engine = BehavioralEvaluationEngine()
        res = engine.evaluate_bundle(bundle, policy=policy, dimensions=[BehaviorDimension.OUTPUT])
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.input_results[0].dimension_results[BehaviorDimension.OUTPUT].verdict == EvaluationVerdict.INCONCLUSIVE

    def test_e2e_captured_output_matching_yields_equivalent(self, policy):
        """Section 17: Ref & Target Output capture_status=CAPTURED -> EQUIVALENT."""
        session_id = "sess_e2e_cap_out"
        app_id = "app_e2e_2"
        rec_r = EvidenceRecord(
            evidence_id="r_cap_out",
            session_id=session_id,
            input_id="in_cap_1",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"x": 1}, "normalized_output": {"x": 1}},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_cap_out",
            session_id=session_id,
            input_id="in_cap_1",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"x": 1}, "normalized_output": {"x": 1}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_cap_out",
            session_id=session_id,
            correlation_id="c_cap",
            application_id=app_id,
            input_set_id="is_cap",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_cap", application_id=app_id, input_set_id="is_cap", input_set_hash="h_cap", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )
        engine = BehavioralEvaluationEngine()
        res = engine.evaluate_bundle(bundle, policy=policy, dimensions=[BehaviorDimension.OUTPUT])
        assert res.verdict == EvaluationVerdict.EQUIVALENT

    def test_e2e_captured_output_different_yields_different(self, policy):
        """Section 18: Ref & Target Output capture_status=CAPTURED with different payload -> DIFFERENT."""
        session_id = "sess_e2e_diff_out"
        app_id = "app_e2e_3"
        rec_r = EvidenceRecord(
            evidence_id="r_diff_out",
            session_id=session_id,
            input_id="in_diff_1",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"x": 1}, "normalized_output": {"x": 1}},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_diff_out",
            session_id=session_id,
            input_id="in_diff_1",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"x": 2}, "normalized_output": {"x": 2}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_diff_out",
            session_id=session_id,
            correlation_id="c_diff",
            application_id=app_id,
            input_set_id="is_diff",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_diff", application_id=app_id, input_set_id="is_diff", input_set_hash="h_diff", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )
        engine = BehavioralEvaluationEngine()
        res = engine.evaluate_bundle(bundle, policy=policy, dimensions=[BehaviorDimension.OUTPUT])
        assert res.verdict == EvaluationVerdict.DIFFERENT

    def test_e2e_partial_vs_captured_output_yields_inconclusive_unless_diff(self, policy):
        """Section 19: Ref=PARTIAL, Target=CAPTURED."""
        session_id = "sess_e2e_part_cap"
        app_id = "app_e2e_4"
        # Same values -> INCONCLUSIVE
        rec_r1 = EvidenceRecord(
            evidence_id="r_pc1",
            session_id=session_id,
            input_id="in_pc_1",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.PARTIAL,
            payload={"raw_output": {"x": 1}, "normalized_output": {"x": 1}},
        )
        rec_t1 = EvidenceRecord(
            evidence_id="t_pc1",
            session_id=session_id,
            input_id="in_pc_1",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"x": 1}, "normalized_output": {"x": 1}},
        )
        bundle1 = EvidenceBundle(
            bundle_id="bnd_pc1",
            session_id=session_id,
            correlation_id="c_pc1",
            application_id=app_id,
            input_set_id="is_pc1",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_pc1", application_id=app_id, input_set_id="is_pc1", input_set_hash="h_pc1", records=[rec_r1, rec_t1]),
            records=[rec_r1, rec_t1],
        )
        engine = BehavioralEvaluationEngine()
        res1 = engine.evaluate_bundle(bundle1, policy=policy, dimensions=[BehaviorDimension.OUTPUT])
        assert res1.verdict == EvaluationVerdict.INCONCLUSIVE

        # Different values -> DIFFERENT
        rec_r2 = EvidenceRecord(
            evidence_id="r_pc2",
            session_id=session_id,
            input_id="in_pc_2",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.PARTIAL,
            payload={"raw_output": {"x": 1}, "normalized_output": {"x": 1}},
        )
        rec_t2 = EvidenceRecord(
            evidence_id="t_pc2",
            session_id=session_id,
            input_id="in_pc_2",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"x": 999}, "normalized_output": {"x": 999}},
        )
        bundle2 = EvidenceBundle(
            bundle_id="bnd_pc2",
            session_id=session_id,
            correlation_id="c_pc2",
            application_id=app_id,
            input_set_id="is_pc2",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_pc2", application_id=app_id, input_set_id="is_pc2", input_set_hash="h_pc2", records=[rec_r2, rec_t2]),
            records=[rec_r2, rec_t2],
        )
        res2 = engine.evaluate_bundle(bundle2, policy=policy, dimensions=[BehaviorDimension.OUTPUT])
        assert res2.verdict == EvaluationVerdict.DIFFERENT

    def test_e2e_partial_error_evidence_yields_inconclusive(self, policy):
        """Section 20: Error evidence partial/unsupported checks."""
        session_id = "sess_e2e_err_part"
        app_id = "app_e2e_5"
        rec_r = EvidenceRecord(
            evidence_id="r_err_p",
            session_id=session_id,
            input_id="in_err_p",
            role="reference",
            evidence_type=EvidenceType.ERROR,
            capture_status=EvidenceCaptureStatus.PARTIAL,
            payload={"message": "Failure occurred", "status_code": 500, "category": "DATABASE"},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_err_p",
            session_id=session_id,
            input_id="in_err_p",
            role="target",
            evidence_type=EvidenceType.ERROR,
            capture_status=EvidenceCaptureStatus.PARTIAL,
            payload={"message": "Failure occurred", "status_code": 500, "category": "DATABASE"},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_err_p",
            session_id=session_id,
            correlation_id="c_err_p",
            application_id=app_id,
            input_set_id="is_err_p",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_err_p", application_id=app_id, input_set_id="is_err_p", input_set_hash="h_err_p", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )
        engine = BehavioralEvaluationEngine()
        res = engine.evaluate_bundle(bundle, policy=policy, dimensions=[BehaviorDimension.ERROR])
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_e2e_unknown_status_fails_closed_inconclusive(self, policy):
        """Section 11: Unknown/weird status must fail closed."""
        session_id = "sess_e2e_weird_st"
        app_id = "app_e2e_6"
        rec_r = EvidenceRecord(
            evidence_id="r_weird",
            session_id=session_id,
            input_id="in_weird",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            payload={"raw_output": {"data": 123}, "normalized_output": {"data": 123}},
        )
        # Manually assign unknown status
        rec_r.capture_status = "WEIRD_CUSTOM_STATUS"  # type: ignore
        rec_t = EvidenceRecord(
            evidence_id="t_weird",
            session_id=session_id,
            input_id="in_weird",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            payload={"raw_output": {"data": 123}, "normalized_output": {"data": 123}},
        )
        rec_t.capture_status = "WEIRD_CUSTOM_STATUS"  # type: ignore
        bundle = EvidenceBundle(
            bundle_id="bnd_weird",
            session_id=session_id,
            correlation_id="c_weird",
            application_id=app_id,
            input_set_id="is_weird",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_weird", application_id=app_id, input_set_id="is_weird", input_set_hash="h_weird", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )
        engine = BehavioralEvaluationEngine()
        res = engine.evaluate_bundle(bundle, policy=policy, dimensions=[BehaviorDimension.OUTPUT])
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_e2e_content_hash_tamper_on_empty_payload_detected(self, policy):
        """Section 31: Content hash verification works even on empty/falsy payloads."""
        session_id = "sess_e2e_empty_tamper"
        app_id = "app_e2e_7"
        rec_r = EvidenceRecord(
            evidence_id="r_empty_tamp",
            session_id=session_id,
            input_id="in_empty_tamp",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            payload={},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_empty_tamp",
            session_id=session_id,
            input_id="in_empty_tamp",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            payload={},
        )
        # Intentionally tamper target record content_hash
        rec_t.content_hash = "0000000000000000000000000000000000000000000000000000000000000000"
        bundle = EvidenceBundle(
            bundle_id="bnd_empty_tamp",
            session_id=session_id,
            correlation_id="c_et",
            application_id=app_id,
            input_set_id="is_et",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_et", application_id=app_id, input_set_id="is_et", input_set_hash="h_et", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )
        engine = BehavioralEvaluationEngine()
        res = engine.evaluate_bundle(bundle, policy=policy, dimensions=[BehaviorDimension.OUTPUT])
        assert res.verdict == EvaluationVerdict.ERROR
        assert res.metadata["integrity_issues_count"] > 0

    # 10. CRITICAL CENTRAL REGRESSION: MALFORMED STATE WITH VALID EQUAL OUTPUT
    def test_e2e_central_regression_malformed_state_with_valid_output(self, policy):
        """Sections 10 & 32: Ref & Target have equal valid OUTPUT but malformed STATE.
        Expected: OUTPUT -> EQUIVALENT, STATE -> INCONCLUSIVE, OVERALL -> INCONCLUSIVE.
        Must NEVER be: STATE -> NOT_APPLICABLE, OVERALL -> EQUIVALENT.
        """
        session_id = "sess_central_reg"
        app_id = "app_central_1"
        rec_r_out = EvidenceRecord(
            evidence_id="r_out",
            session_id=session_id,
            input_id="inp_01",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"result": "success"}, "normalized_output": {"result": "success"}},
        )
        rec_t_out = EvidenceRecord(
            evidence_id="t_out",
            session_id=session_id,
            input_id="inp_01",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"result": "success"}, "normalized_output": {"result": "success"}},
        )
        # Malformed STATE: table_row_counts_before should be a dict, passing a string/invalid schema
        rec_r_state = EvidenceRecord(
            evidence_id="r_state",
            session_id=session_id,
            input_id="inp_01",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"table_row_counts_before": "NOT_A_DICT_INVALID_PAYLOAD"},
        )
        rec_t_state = EvidenceRecord(
            evidence_id="t_state",
            session_id=session_id,
            input_id="inp_01",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"table_row_counts_before": "NOT_A_DICT_INVALID_PAYLOAD"},
        )
        recs = [rec_r_out, rec_t_out, rec_r_state, rec_t_state]
        bundle = EvidenceBundle(
            bundle_id="bnd_central",
            session_id=session_id,
            correlation_id="c_central",
            application_id=app_id,
            input_set_id="is_central",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_central", application_id=app_id, input_set_id="is_central", input_set_hash="h_central", records=recs),
            records=recs,
        )
        engine = BehavioralEvaluationEngine()
        dims = [BehaviorDimension.OUTPUT, BehaviorDimension.STATE]
        res = engine.evaluate_bundle(bundle, policy=policy, dimensions=dims)

        inp_res = res.input_results[0]
        # Dimension OUTPUT must be EQUIVALENT
        assert inp_res.dimension_results[BehaviorDimension.OUTPUT].verdict == EvaluationVerdict.EQUIVALENT
        # Dimension STATE must be INCONCLUSIVE (NOT NOT_APPLICABLE and NOT EQUIVALENT)
        assert inp_res.dimension_results[BehaviorDimension.STATE].verdict == EvaluationVerdict.INCONCLUSIVE
        # Overall verdict must be INCONCLUSIVE
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.verdict != EvaluationVerdict.EQUIVALENT

        # Unselected dimension verification: if only OUTPUT is selected, OVERALL is EQUIVALENT
        res_out_only = engine.evaluate_bundle(bundle, policy=policy, dimensions=[BehaviorDimension.OUTPUT])
        assert res_out_only.verdict == EvaluationVerdict.EQUIVALENT

    # 11. ONE-SIDED MALFORMED EVIDENCE
    def test_e2e_one_sided_malformed_state(self, policy):
        """Section 11: Reference STATE malformed, Target STATE valid CAPTURED -> INCONCLUSIVE."""
        session_id = "sess_one_sided"
        app_id = "app_one_sided_1"
        rec_r_state = EvidenceRecord(
            evidence_id="r_state_mal",
            session_id=session_id,
            input_id="inp_os_01",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"table_row_counts_before": "INVALID_TYPE"},
        )
        rec_t_state = EvidenceRecord(
            evidence_id="t_state_val",
            session_id=session_id,
            input_id="inp_os_01",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"configured_tables": ["users"], "table_row_counts_before": {"users": 10}, "table_row_counts_after": {"users": 10}},
        )
        recs = [rec_r_state, rec_t_state]
        bundle = EvidenceBundle(
            bundle_id="bnd_os",
            session_id=session_id,
            correlation_id="c_os",
            application_id=app_id,
            input_set_id="is_os",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_os", application_id=app_id, input_set_id="is_os", input_set_hash="h_os", records=recs),
            records=recs,
        )
        engine = BehavioralEvaluationEngine()
        res = engine.evaluate_bundle(bundle, policy=policy, dimensions=[BehaviorDimension.STATE])
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.verdict != EvaluationVerdict.EQUIVALENT

    # 12. MALFORMED OUTPUT TEST
    def test_e2e_malformed_output_payload(self, policy):
        """Section 13: Ref OUTPUT valid, Target OUTPUT malformed -> OUTPUT INCONCLUSIVE."""
        session_id = "sess_mal_out"
        app_id = "app_mal_out_1"
        rec_r = EvidenceRecord(
            evidence_id="r_out_val",
            session_id=session_id,
            input_id="inp_mo",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"data": 123}, "normalized_output": {"data": 123}},
        )
        # Passing invalid non-dict or unparseable fields that fail OutputEvidence model instantiation
        rec_t = EvidenceRecord(
            evidence_id="t_out_mal",
            session_id=session_id,
            input_id="inp_mo",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"duration_ms": "NOT_A_FLOAT_OR_INT_INVALID"},
        )
        recs = [rec_r, rec_t]
        bundle = EvidenceBundle(
            bundle_id="bnd_mo",
            session_id=session_id,
            correlation_id="c_mo",
            application_id=app_id,
            input_set_id="is_mo",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_mo", application_id=app_id, input_set_id="is_mo", input_set_hash="h_mo", records=recs),
            records=recs,
        )
        engine = BehavioralEvaluationEngine()
        res = engine.evaluate_bundle(bundle, policy=policy, dimensions=[BehaviorDimension.OUTPUT])
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.input_results[0].dimension_results[BehaviorDimension.OUTPUT].verdict == EvaluationVerdict.INCONCLUSIVE

    # 13. MALFORMED HTTP EVIDENCE
    def test_e2e_malformed_http_evidence(self, policy):
        """Section 14: Malformed HTTP evidence -> STATE INCONCLUSIVE, not NOT_APPLICABLE."""
        session_id = "sess_mal_http"
        app_id = "app_mal_http_1"
        rec_r = EvidenceRecord(
            evidence_id="r_http_mal",
            session_id=session_id,
            input_id="inp_m_http",
            role="reference",
            evidence_type=EvidenceType.HTTP,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"calls": "NOT_A_LIST"},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_http_mal",
            session_id=session_id,
            input_id="inp_m_http",
            role="target",
            evidence_type=EvidenceType.HTTP,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"calls": "NOT_A_LIST"},
        )
        recs = [rec_r, rec_t]
        bundle = EvidenceBundle(
            bundle_id="bnd_m_http",
            session_id=session_id,
            correlation_id="c_mh",
            application_id=app_id,
            input_set_id="is_mh",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_mh", application_id=app_id, input_set_id="is_mh", input_set_hash="h_mh", records=recs),
            records=recs,
        )
        engine = BehavioralEvaluationEngine()
        res = engine.evaluate_bundle(bundle, policy=policy, dimensions=[BehaviorDimension.STATE])
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.input_results[0].dimension_results[BehaviorDimension.STATE].verdict == EvaluationVerdict.INCONCLUSIVE

    # 14. MALFORMED FILESYSTEM EVIDENCE
    def test_e2e_malformed_filesystem_evidence(self, policy):
        """Section 15: Malformed filesystem evidence -> STATE INCONCLUSIVE."""
        session_id = "sess_mal_fs"
        app_id = "app_mal_fs_1"
        rec_r = EvidenceRecord(
            evidence_id="r_fs_mal",
            session_id=session_id,
            input_id="inp_m_fs",
            role="reference",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"configured_paths": "NOT_A_LIST_OF_PATHS"},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_fs_mal",
            session_id=session_id,
            input_id="inp_m_fs",
            role="target",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"configured_paths": "NOT_A_LIST_OF_PATHS"},
        )
        recs = [rec_r, rec_t]
        bundle = EvidenceBundle(
            bundle_id="bnd_m_fs",
            session_id=session_id,
            correlation_id="c_mfs",
            application_id=app_id,
            input_set_id="is_mfs",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_mfs", application_id=app_id, input_set_id="is_mfs", input_set_hash="h_mfs", records=recs),
            records=recs,
        )
        engine = BehavioralEvaluationEngine()
        res = engine.evaluate_bundle(bundle, policy=policy, dimensions=[BehaviorDimension.STATE])
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    # 15. MALFORMED WORKFLOW EVIDENCE
    def test_e2e_malformed_workflow_evidence(self, policy):
        """Section 17: Malformed workflow trace evidence -> WORKFLOW INCONCLUSIVE."""
        session_id = "sess_mal_wf"
        app_id = "app_mal_wf_1"
        rec_r = EvidenceRecord(
            evidence_id="r_wf_mal",
            session_id=session_id,
            input_id="inp_m_wf",
            role="reference",
            evidence_type=EvidenceType.TRACE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"events": "NOT_A_LIST_OF_EVENTS"},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_wf_mal",
            session_id=session_id,
            input_id="inp_m_wf",
            role="target",
            evidence_type=EvidenceType.TRACE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"events": "NOT_A_LIST_OF_EVENTS"},
        )
        recs = [rec_r, rec_t]
        bundle = EvidenceBundle(
            bundle_id="bnd_m_wf",
            session_id=session_id,
            correlation_id="c_mwf",
            application_id=app_id,
            input_set_id="is_mwf",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_mwf", application_id=app_id, input_set_id="is_mwf", input_set_hash="h_mwf", records=recs),
            records=recs,
        )
        engine = BehavioralEvaluationEngine()
        res = engine.evaluate_bundle(bundle, policy=policy, dimensions=[BehaviorDimension.WORKFLOW])
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    # 16. INVALID ROLE TESTS (FAIL-CLOSED)
    @pytest.mark.parametrize("bad_role", ["banana", "unknown", "", None, 12345])
    def test_e2e_invalid_role_fails_closed(self, bad_role, policy):
        """Sections 18, 19, 20: Unknown/invalid role must NEVER be treated as target; must fail closed."""
        session_id = "sess_bad_role"
        app_id = "app_bad_role_1"
        rec_r = EvidenceRecord(
            evidence_id="r_good",
            session_id=session_id,
            input_id="inp_bad_role",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"x": 1}, "normalized_output": {"x": 1}},
        )
        rec_bad = EvidenceRecord.model_construct(
            evidence_id="rec_invalid_role",
            session_id=session_id,
            input_id="inp_bad_role",
            role=bad_role,
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"x": 1}, "normalized_output": {"x": 1}},
            metadata={},
            provenance={},
        )
        recs = [rec_r, rec_bad]
        bundle = EvidenceBundle(
            bundle_id="bnd_bad_role",
            session_id=session_id,
            correlation_id="c_br",
            application_id=app_id,
            input_set_id="is_br",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_br", application_id=app_id, input_set_id="is_br", input_set_hash="h_br", records=recs),
            records=recs,
        )
        engine = BehavioralEvaluationEngine()
        res = engine.evaluate_bundle(bundle, policy=policy, dimensions=[BehaviorDimension.OUTPUT])
        assert res.verdict != EvaluationVerdict.EQUIVALENT
        assert res.verdict in (EvaluationVerdict.ERROR, EvaluationVerdict.INCONCLUSIVE)
        assert res.metadata["integrity_issues_count"] > 0 or any("INVALID_ROLE" in issue for issue in res.metadata.get("integrity_issues", []))

    # 17. DETERMINISM ON REPEATED EVALUATION WITH ADAPTATION FAILURES
    def test_e2e_adaptation_failure_determinism(self, policy):
        """Section 39: Repeated evaluation of bundle with adaptation failures yields identical hash."""
        session_id = "sess_det"
        app_id = "app_det_1"
        recs = [
            EvidenceRecord(
                evidence_id="r1",
                session_id=session_id,
                input_id="inp_det",
                role="reference",
                evidence_type=EvidenceType.OUTPUT,
                payload={"raw_output": {"data": 1}, "normalized_output": {"data": 1}},
            ),
            EvidenceRecord(
                evidence_id="t1",
                session_id=session_id,
                input_id="inp_det",
                role="target",
                evidence_type=EvidenceType.OUTPUT,
                payload={"raw_output": {"data": 1}, "normalized_output": {"data": 1}},
            ),
            EvidenceRecord(
                evidence_id="r2_mal",
                session_id=session_id,
                input_id="inp_det",
                role="reference",
                evidence_type=EvidenceType.DATABASE,
                payload={"table_row_counts_before": "INVALID"},
            ),
        ]
        bundle = EvidenceBundle(
            bundle_id="bnd_det",
            session_id=session_id,
            correlation_id="c_det",
            application_id=app_id,
            input_set_id="is_det",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_det", application_id=app_id, input_set_id="is_det", input_set_hash="h_det", records=recs),
            records=recs,
        )
        engine = BehavioralEvaluationEngine()
        dims = [BehaviorDimension.OUTPUT, BehaviorDimension.STATE]
        res1 = engine.evaluate_bundle(bundle, policy=policy, dimensions=dims)
        res2 = engine.evaluate_bundle(bundle, policy=policy, dimensions=dims)

        assert res1.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res2.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res1.evaluation_hash == res2.evaluation_hash


