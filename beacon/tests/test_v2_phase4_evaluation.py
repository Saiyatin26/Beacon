"""BEACON V2 — Phase 4 Behavioral Evaluation Test Suite.

Validates the Behavioral Equivalence Evaluation Engine across all 6 core dimensions:
1. OUTPUT: Exact, structural, array ordering, numeric tolerance, and ignored keys.
2. ERROR: Status codes, error categories, error messages, and success-vs-error divergence.
3. BOUNDARY: Boundary inputs, extreme values, off-by-one, and edge-case behavior.
4. STATE: Side-effects, database mutations, filesystem modifications, and state deltas.
5. WORKFLOW: Execution traces, sequence of calls, intermediate states, and dependencies.
6. NONFUNCTIONAL: Execution duration, memory, and performance delta bounds.

Also verifies:
- Declarative Comparison Policies (default_v2, strict_v2, relaxed_v2, custom).
- Cryptographic tamper verification and fail-closed evaluation on corrupt bundles.
- Deterministic SHA-256 evaluation fingerprinting.
- REST API endpoints under /api/v2/evaluation/*.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))

from api.main import app
from auth import create_access_token
from common.contracts import AdapterRole, ExecutionStatus
from evaluation.models import (
    BehaviorDifference,
    BehaviorDimension,
    DifferenceType,
    DimensionResult,
    EvaluationResult,
    EvaluationSummary,
    EvaluationVerdict,
    InputEvaluationResult,
)
from evaluation.policies import (
    ComparisonPolicy,
    FloatComparisonMode,
    get_builtin_policy,
    list_builtin_policies,
    resolve_comparison_policy,
)
from evaluation.evaluators import (
    BoundaryEvaluator,
    ErrorEvaluator,
    NonFunctionalEvaluator,
    OutputEvaluator,
    StateEvaluator,
    WorkflowEvaluator,
)
from evaluation.input_adapter import EvaluationInputAdapter
from evaluation.engine import BehavioralEvaluationEngine
from execution.evidence import (
    EvidenceBundle,
    EvidenceManifest,
    EvidenceRecord,
    EvidenceType,
    OutputEvidencePayload,
    ErrorEvidencePayload,
    TraceEvidencePayload,
)


@pytest.fixture
def auth_client():
    token = create_access_token({"sub": "admin", "role": "admin"})
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def default_policy() -> ComparisonPolicy:
    return resolve_comparison_policy("default_v2")


@pytest.fixture
def strict_policy() -> ComparisonPolicy:
    return resolve_comparison_policy("strict_v2")


@pytest.fixture
def relaxed_policy() -> ComparisonPolicy:
    return resolve_comparison_policy("relaxed_v2")


# ==============================================================================
# 1. Comparison Policy Tests
# ==============================================================================

class TestComparisonPolicies:
    def test_builtin_policies_available(self):
        policies = list_builtin_policies()
        assert len(policies) >= 3
        policy_ids = [p.policy_id for p in policies]
        assert "default_v2" in policy_ids
        assert "strict_v2" in policy_ids
        assert "relaxed_v2" in policy_ids

    def test_policy_resolution_defaults(self):
        p = resolve_comparison_policy(None)
        assert p.policy_id == "default_v2"
        assert p.float_mode == FloatComparisonMode.ABSOLUTE
        assert p.float_tolerance == 1e-5

    def test_policy_resolution_named(self):
        strict = resolve_comparison_policy("strict_v2")
        assert strict.policy_id == "strict_v2"
        assert strict.ignore_array_order is False
        assert strict.float_tolerance == 0.0

        relaxed = resolve_comparison_policy("relaxed_v2")
        assert relaxed.policy_id == "relaxed_v2"
        assert relaxed.ignore_array_order is True
        assert relaxed.float_tolerance == 1e-2

    def test_custom_policy_dictionary(self):
        custom = resolve_comparison_policy({
            "policy_id": "my_custom_policy",
            "float_tolerance": 0.05,
            "ignore_keys": ["extra_timestamp", "uuid"],
        })
        assert custom.policy_id == "my_custom_policy"
        assert custom.float_tolerance == 0.05
        assert "extra_timestamp" in custom.ignore_keys

    def test_policy_hash_determinism(self):
        p1 = ComparisonPolicy(policy_id="test_p", float_tolerance=1e-4, ignore_keys=["b", "a"])
        p2 = ComparisonPolicy(policy_id="test_p", float_tolerance=1e-4, ignore_keys=["a", "b"])
        # Should be deterministic
        assert p1.compute_policy_hash() == p2.compute_policy_hash()


# ==============================================================================
# 2. Output Evaluator Tests
# ==============================================================================

class TestOutputEvaluator:
    def test_identical_outputs_equivalent(self, default_policy):
        evaluator = OutputEvaluator()
        res = evaluator.evaluate(
            input_id="in-1",
            reference_payload={"status": "approved", "score": 95},
            target_payload={"status": "approved", "score": 95},
            policy=default_policy,
        )
        assert res.verdict == EvaluationVerdict.EQUIVALENT
        assert len(res.differences) == 0

    def test_value_mismatch_detected(self, default_policy):
        evaluator = OutputEvaluator()
        res = evaluator.evaluate(
            input_id="in-2",
            reference_payload={"status": "approved", "score": 95},
            target_payload={"status": "rejected", "score": 95},
            policy=default_policy,
        )
        assert res.verdict == EvaluationVerdict.DIFFERENT
        assert len(res.differences) == 1
        diff = res.differences[0]
        assert diff.difference_type == DifferenceType.OUTPUT_VALUE_MISMATCH
        assert diff.field_path == "status"
        assert diff.reference_value == "approved"
        assert diff.target_value == "rejected"

    def test_missing_and_extra_fields(self, default_policy):
        evaluator = OutputEvaluator()
        res = evaluator.evaluate(
            input_id="in-3",
            reference_payload={"a": 1, "b": 2},
            target_payload={"a": 1, "c": 3},
            policy=default_policy,
        )
        assert res.verdict == EvaluationVerdict.DIFFERENT
        diff_types = [d.difference_type for d in res.differences]
        assert DifferenceType.MISSING_FIELD in diff_types
        assert DifferenceType.EXTRA_FIELD in diff_types

    def test_numeric_tolerance_handling(self):
        policy = ComparisonPolicy(float_tolerance=0.01)
        evaluator = OutputEvaluator()
        # Within tolerance -> EQUIVALENT
        res_ok = evaluator.evaluate(
            input_id="in-4",
            reference_payload={"rate": 3.14159},
            target_payload={"rate": 3.14500},
            policy=policy,
        )
        assert res_ok.verdict == EvaluationVerdict.EQUIVALENT

        # Exceeds tolerance -> DIFFERENT
        res_fail = evaluator.evaluate(
            input_id="in-5",
            reference_payload={"rate": 3.14159},
            target_payload={"rate": 3.19000},
            policy=policy,
        )
        assert res_fail.verdict == EvaluationVerdict.DIFFERENT
        assert res_fail.differences[0].difference_type == DifferenceType.NUMERIC_TOLERANCE_EXCEEDED

    def test_array_ordering_policy(self):
        ordered_policy = ComparisonPolicy(ignore_array_order=False)
        unordered_policy = ComparisonPolicy(ignore_array_order=True)
        evaluator = OutputEvaluator()

        ref = {"tags": ["alpha", "beta", "gamma"]}
        target = {"tags": ["gamma", "alpha", "beta"]}

        res_ordered = evaluator.evaluate("in-6", ref, target, ordered_policy)
        assert res_ordered.verdict == EvaluationVerdict.DIFFERENT

        res_unordered = evaluator.evaluate("in-7", ref, target, unordered_policy)
        assert res_unordered.verdict == EvaluationVerdict.EQUIVALENT

    def test_ignored_keys(self):
        policy = ComparisonPolicy(ignore_keys=["timestamp", "session_token"])
        evaluator = OutputEvaluator()
        ref = {"user_id": 42, "timestamp": "2026-01-01T00:00:00Z"}
        target = {"user_id": 42, "timestamp": "2026-09-06T12:00:00Z"}
        res = evaluator.evaluate("in-8", ref, target, policy)
        assert res.verdict == EvaluationVerdict.EQUIVALENT


# ==============================================================================
# 3. Error Evaluator Tests
# ==============================================================================

class TestErrorEvaluator:
    def test_both_success_equivalent(self, default_policy):
        evaluator = ErrorEvaluator()
        res = evaluator.evaluate(
            input_id="in-err-1",
            reference_error=None,
            target_error=None,
            policy=default_policy,
        )
        assert res.verdict == EvaluationVerdict.EQUIVALENT
        assert len(res.differences) == 0

    def test_success_error_divergence(self, default_policy):
        evaluator = ErrorEvaluator()
        target_err = ErrorEvidencePayload(
            error_message="Invalid input parameter",
            error_category="VALIDATION_ERROR",
            status_code=400,
        )
        res = evaluator.evaluate(
            input_id="in-err-2",
            reference_error=None,
            target_error=target_err,
            policy=default_policy,
        )
        assert res.verdict == EvaluationVerdict.DIFFERENT
        assert res.differences[0].difference_type == DifferenceType.SUCCESS_ERROR_MISMATCH

    def test_error_status_code_mismatch(self, default_policy):
        evaluator = ErrorEvaluator()
        ref_err = ErrorEvidencePayload(error_message="Not found", status_code=404, error_category="NOT_FOUND")
        target_err = ErrorEvidencePayload(error_message="Forbidden", status_code=403, error_category="AUTH_ERROR")
        res = evaluator.evaluate(
            input_id="in-err-3",
            reference_error=ref_err,
            target_error=target_err,
            policy=default_policy,
        )
        assert res.verdict == EvaluationVerdict.DIFFERENT
        diff_types = [d.difference_type for d in res.differences]
        assert DifferenceType.ERROR_STATUS_MISMATCH in diff_types

    def test_matching_error_is_equivalent(self, default_policy):
        evaluator = ErrorEvaluator()
        ref_err = ErrorEvidencePayload(error_message="Resource 42 missing", status_code=404, error_category="NOT_FOUND")
        target_err = ErrorEvidencePayload(error_message="Item 42 could not be found", status_code=404, error_category="NOT_FOUND")
        res = evaluator.evaluate(
            input_id="in-err-4",
            reference_error=ref_err,
            target_error=target_err,
            policy=default_policy,
        )
        # Status and category match; default policy does not require exact error message match
        assert res.verdict == EvaluationVerdict.EQUIVALENT


# ==============================================================================
# 4. Boundary Evaluator Tests
# ==============================================================================

class TestBoundaryEvaluator:
    def test_boundary_behavior_divergence(self, default_policy):
        evaluator = BoundaryEvaluator()
        res = evaluator.evaluate(
            input_id="in-bnd-1",
            boundary_category="OFF_BY_ONE",
            reference_output={"valid": True, "count": 100},
            target_output={"valid": False, "error": "Max length is 99"},
            reference_error=None,
            target_error=None,
            policy=default_policy,
        )
        assert res.verdict == EvaluationVerdict.DIFFERENT
        assert any(d.difference_type == DifferenceType.BOUNDARY_BEHAVIOR_MISMATCH for d in res.differences)

    def test_boundary_behavior_agreement(self, default_policy):
        evaluator = BoundaryEvaluator()
        res = evaluator.evaluate(
            input_id="in-bnd-2",
            boundary_category="MAX_INTEGER",
            reference_output={"status": "overflow_handled"},
            target_output={"status": "overflow_handled"},
            reference_error=None,
            target_error=None,
            policy=default_policy,
        )
        assert res.verdict == EvaluationVerdict.EQUIVALENT


# ==============================================================================
# 5. State Evaluator Tests
# ==============================================================================

class TestStateEvaluator:
    def test_database_mutations_equivalent(self, default_policy):
        evaluator = StateEvaluator()
        ref_records = [
            EvidenceRecord(
                evidence_id="ref_db_1",
                session_id="s1",
                input_id="in-st-1",
                role=AdapterRole.REFERENCE,
                evidence_type=EvidenceType.DATABASE,
                payload={"table": "accounts", "operation": "UPDATE", "row_count": 1},
            )
        ]
        target_records = [
            EvidenceRecord(
                evidence_id="tgt_db_1",
                session_id="s1",
                input_id="in-st-1",
                role=AdapterRole.TARGET,
                evidence_type=EvidenceType.DATABASE,
                payload={"table": "accounts", "operation": "UPDATE", "row_count": 1},
            )
        ]
        res = evaluator.evaluate("in-st-1", ref_records, target_records, default_policy)
        assert res.verdict == EvaluationVerdict.EQUIVALENT

    def test_database_mutation_mismatch_detected(self, default_policy):
        evaluator = StateEvaluator()
        ref_records = [
            EvidenceRecord(
                evidence_id="ref_db_2",
                session_id="s1",
                input_id="in-st-2",
                role=AdapterRole.REFERENCE,
                evidence_type=EvidenceType.DATABASE,
                payload={"table": "accounts", "operation": "UPDATE", "row_count": 1},
            )
        ]
        target_records = [
            EvidenceRecord(
                evidence_id="tgt_db_2",
                session_id="s1",
                input_id="in-st-2",
                role=AdapterRole.TARGET,
                evidence_type=EvidenceType.DATABASE,
                payload={"table": "accounts", "operation": "DELETE", "row_count": 1},
            )
        ]
        res = evaluator.evaluate("in-st-2", ref_records, target_records, default_policy)
        assert res.verdict == EvaluationVerdict.DIFFERENT
        assert any(d.difference_type == DifferenceType.DATABASE_MUTATION_MISMATCH for d in res.differences)


# ==============================================================================
# 6. Workflow & Nonfunctional Evaluator Tests
# ==============================================================================

class TestWorkflowAndNonFunctionalEvaluators:
    def test_workflow_call_sequence_mismatch(self, default_policy):
        evaluator = WorkflowEvaluator()
        ref_trace = TraceEvidencePayload(
            call_sequence=["fetch_user", "check_balance", "process_transfer"],
            span_count=3,
        )
        target_trace = TraceEvidencePayload(
            call_sequence=["fetch_user", "process_transfer"],  # Skipped check_balance
            span_count=2,
        )
        res = evaluator.evaluate("in-wf-1", ref_trace, target_trace, default_policy)
        assert res.verdict == EvaluationVerdict.DIFFERENT
        assert any(d.difference_type == DifferenceType.WORKFLOW_SEQUENCE_MISMATCH for d in res.differences)

    def test_nonfunctional_latency_tolerance(self):
        policy = ComparisonPolicy(max_latency_ratio=2.0)
        evaluator = NonFunctionalEvaluator()

        # Within 2x ratio -> EQUIVALENT
        res_ok = evaluator.evaluate("in-nf-1", 100.0, 150.0, policy)
        assert res_ok.verdict == EvaluationVerdict.EQUIVALENT

        # Exceeds 2x ratio -> DIFFERENT
        res_diff = evaluator.evaluate("in-nf-2", 100.0, 350.0, policy)
        assert res_diff.verdict == EvaluationVerdict.DIFFERENT
        assert any(d.difference_type == DifferenceType.NONFUNCTIONAL_THRESHOLD_EXCEEDED for d in res_diff.differences)


# ==============================================================================
# 7. End-to-End Evaluation Engine & Bundle Verification
# ==============================================================================

def create_sample_bundle(tamper: bool = False, include_difference: bool = False) -> EvidenceBundle:
    """Helper to construct a valid, cryptographically verified EvidenceBundle."""
    session_id = "sess_test_123"
    app_id = "app_credit_score"

    ref_payload = {"score": 750, "risk_tier": "LOW"}
    target_payload = {"score": 600, "risk_tier": "HIGH"} if include_difference else {"score": 750, "risk_tier": "LOW"}

    r_out = OutputEvidencePayload(
        status_code=200,
        raw_output=ref_payload,
        normalized_output=ref_payload,
        duration_ms=45.0,
    )
    t_out = OutputEvidencePayload(
        status_code=200,
        raw_output=target_payload,
        normalized_output=target_payload,
        duration_ms=50.0,
    )

    rec_ref = EvidenceRecord(
        evidence_id="rec_ref_01",
        session_id=session_id,
        input_id="input_01",
        role=AdapterRole.REFERENCE,
        evidence_type=EvidenceType.OUTPUT,
        payload=r_out.model_dump(),
    )
    rec_target = EvidenceRecord(
        evidence_id="rec_tgt_01",
        session_id=session_id,
        input_id="input_01",
        role=AdapterRole.TARGET,
        evidence_type=EvidenceType.OUTPUT,
        payload=t_out.model_dump(),
    )

    if tamper:
        # Tamper record hash without updating payload
        rec_ref.payload_hash = "bad_hash_tampered"

    manifest = EvidenceManifest(
        session_id=session_id,
        application_id=app_id,
        records=[rec_ref, rec_target],
    )

    bundle = EvidenceBundle(
        bundle_id="bnd_test_01",
        session_id=session_id,
        application_id=app_id,
        manifest=manifest,
        records=[rec_ref, rec_target],
    )
    return bundle


class TestEvaluationEngineBundle:
    def test_bundle_evaluation_equivalent(self, default_policy):
        engine = BehavioralEvaluationEngine()
        bundle = create_sample_bundle(tamper=False, include_difference=False)

        res = engine.evaluate_bundle(bundle=bundle, policy=default_policy)
        assert res.verdict == EvaluationVerdict.EQUIVALENT
        assert res.summary.total_inputs == 1
        assert res.summary.equivalent_inputs == 1
        assert res.summary.different_inputs == 0
        assert len(res.differences) == 0
        assert res.evaluation_hash is not None

    def test_bundle_evaluation_with_difference(self, default_policy):
        engine = BehavioralEvaluationEngine()
        bundle = create_sample_bundle(tamper=False, include_difference=True)

        res = engine.evaluate_bundle(bundle=bundle, policy=default_policy)
        assert res.verdict == EvaluationVerdict.DIFFERENT
        assert res.summary.different_inputs == 1
        assert res.summary.total_differences >= 1
        diff_types = [d.difference_type for d in res.differences]
        assert DifferenceType.OUTPUT_VALUE_MISMATCH in diff_types

    def test_bundle_tamper_detection_fails_closed(self, default_policy):
        engine = BehavioralEvaluationEngine()
        bundle = create_sample_bundle(tamper=True, include_difference=False)

        res = engine.evaluate_bundle(bundle=bundle, policy=default_policy, verify_integrity=True)
        assert res.verdict == EvaluationVerdict.ERROR
        assert len(res.metadata["integrity_issues"]) > 0

    def test_deterministic_evaluation_hashing(self, default_policy):
        engine = BehavioralEvaluationEngine()
        bundle = create_sample_bundle(tamper=False, include_difference=False)

        res1 = engine.evaluate_bundle(bundle=bundle, policy=default_policy)
        res2 = engine.evaluate_bundle(bundle=bundle, policy=default_policy)
        # Evaluated independently, the fingerprint must match
        assert res1.verdict == res2.verdict
        assert res1.summary.total_inputs == res2.summary.total_inputs
        assert res1.summary.total_differences == res2.summary.total_differences


# ==============================================================================
# 8. REST API Endpoints Verification
# ==============================================================================

class TestEvaluationAPIRouter:
    def test_get_policies_endpoint(self, auth_client):
        resp = auth_client.get("/api/v2/evaluation/policies")
        assert resp.status_code == 200
        policies = resp.json()
        assert isinstance(policies, list)
        policy_ids = [p["policy_id"] for p in policies]
        assert "default_v2" in policy_ids
        assert "strict_v2" in policy_ids
        assert "relaxed_v2" in policy_ids

    def test_get_specific_policy_endpoint(self, auth_client):
        resp = auth_client.get("/api/v2/evaluation/policies/default_v2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["policy_id"] == "default_v2"
        assert "float_tolerance" in data

    def test_get_unknown_policy_404(self, auth_client):
        resp = auth_client.get("/api/v2/evaluation/policies/non_existent_policy")
        assert resp.status_code == 404

    def test_evaluate_non_existent_session_fails_cleanly(self, auth_client):
        resp = auth_client.post(
            "/api/v2/evaluation/evaluate",
            json={"execution_session_id": "sess_non_existent_xyz"},
        )
        assert resp.status_code in (400, 404)


# ==============================================================================
# 9. Phase 4 Comprehensive Remediation & Correctness Verification (31 Scenarios)
# ==============================================================================

class TestPhase4RemediationCorrectness:
    """Explicit tests for all 31 Phase 4 correctness requirements."""

    # --- MISSING EVIDENCE (1-5) ---

    def test_1_ref_output_exists_target_output_missing_is_inconclusive(self, default_policy):
        evaluator = OutputEvaluator()
        res = evaluator.evaluate(
            input_id="in-miss-1",
            reference_payload={"result": 42},
            target_payload=None,
            policy=default_policy,
            reference_evidence_id="ref_out_1",
        )
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.status == EvaluationVerdict.INCONCLUSIVE

    def test_2_target_output_exists_ref_output_missing_is_inconclusive(self, default_policy):
        evaluator = OutputEvaluator()
        res = evaluator.evaluate(
            input_id="in-miss-2",
            reference_payload=None,
            target_payload={"result": 42},
            policy=default_policy,
            target_evidence_id="tgt_out_2",
        )
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.status == EvaluationVerdict.INCONCLUSIVE

    def test_3_ref_workflow_exists_target_workflow_missing_is_inconclusive(self, default_policy):
        evaluator = WorkflowEvaluator()
        res = evaluator.evaluate(
            input_id="in-miss-3",
            reference_trace={"events": ["auth", "process", "done"]},
            target_trace=None,
            policy=default_policy,
            reference_evidence_id="ref_tr_3",
        )
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.status == EvaluationVerdict.INCONCLUSIVE

    def test_4_ref_state_exists_target_state_missing_is_inconclusive(self, default_policy):
        evaluator = StateEvaluator()
        res = evaluator.evaluate(
            input_id="in-miss-4",
            reference_db_or_records={"table": "orders", "operation": "INSERT", "row_count": 1},
            target_db_or_records=None,
            policy=default_policy,
            reference_evidence_id="ref_st_4",
        )
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.status == EvaluationVerdict.INCONCLUSIVE

    def test_5_boundary_metadata_exists_required_evidence_missing_is_inconclusive(self, default_policy):
        evaluator = BoundaryEvaluator()
        res = evaluator.evaluate(
            input_id="in-miss-5",
            boundary_category="MAX_INTEGER",
            reference_output={"value": 2147483647},
            target_output=None,
            policy=default_policy,
            reference_evidence_id="ref_bnd_5",
        )
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.status == EvaluationVerdict.INCONCLUSIVE

    # --- ERROR (6-9) ---

    def test_6_ref_http_400_vs_target_http_500_is_different(self, default_policy):
        evaluator = ErrorEvaluator()
        res = evaluator.evaluate(
            input_id="in-err-6",
            reference_error={"status_code": 400, "message": "Bad request format"},
            target_error={"status_code": 500, "message": "Internal server crash"},
            policy=default_policy,
            reference_has_error=True,
            target_has_error=True,
            reference_evidence_id="ref_e_6",
            target_evidence_id="tgt_e_6",
        )
        assert res.verdict == EvaluationVerdict.DIFFERENT
        assert any(d.difference_type == DifferenceType.ERROR_STATUS_MISMATCH for d in res.differences)

    def test_7_ref_exit_code_1_vs_target_exit_code_2_is_different(self, default_policy):
        evaluator = ErrorEvaluator()
        res = evaluator.evaluate(
            input_id="in-err-7",
            reference_error={"exit_code": 1, "message": "General error"},
            target_error={"exit_code": 2, "message": "Misuse of shell builtin"},
            policy=default_policy,
            reference_has_error=True,
            target_has_error=True,
            reference_evidence_id="ref_e_7",
            target_evidence_id="tgt_e_7",
        )
        assert res.verdict == EvaluationVerdict.DIFFERENT
        assert any(d.difference_type == DifferenceType.ERROR_STATUS_MISMATCH for d in res.differences)

    def test_8_ref_success_vs_target_error_is_different(self, default_policy):
        evaluator = ErrorEvaluator()
        res = evaluator.evaluate(
            input_id="in-err-8",
            reference_error=None,
            target_error={"status_code": 500, "message": "Crash"},
            policy=default_policy,
            reference_has_error=False,
            target_has_error=True,
            reference_evidence_id="ref_e_8",
            target_evidence_id="tgt_e_8",
        )
        assert res.verdict == EvaluationVerdict.DIFFERENT
        assert any(d.difference_type == DifferenceType.SUCCESS_ERROR_MISMATCH for d in res.differences)

    def test_9_both_error_insufficient_evidence_is_inconclusive(self, default_policy):
        evaluator = ErrorEvaluator()
        res = evaluator.evaluate(
            input_id="in-err-9",
            reference_error=None,
            target_error=None,
            policy=default_policy,
            reference_has_error=True,
            target_has_error=True,
            reference_evidence_id="ref_e_9",
            target_evidence_id="tgt_e_9",
        )
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    # --- BOUNDARY (10-12) ---

    def test_10_same_boundary_equivalent_outputs_is_equivalent(self, default_policy):
        evaluator = BoundaryEvaluator()
        res = evaluator.evaluate(
            input_id="in-bnd-10",
            boundary_category="EMPTY_STRING",
            reference_output={"valid": False, "count": 0},
            target_output={"valid": False, "count": 0},
            policy=default_policy,
            reference_evidence_id="ref_b_10",
            target_evidence_id="tgt_b_10",
        )
        assert res.verdict == EvaluationVerdict.EQUIVALENT

    def test_11_same_boundary_different_outputs_is_different(self, default_policy):
        evaluator = BoundaryEvaluator()
        res = evaluator.evaluate(
            input_id="in-bnd-11",
            boundary_category="ZERO_DIVISOR",
            reference_output={"result": "error_handled"},
            target_output={"result": "infinity"},
            policy=default_policy,
            reference_evidence_id="ref_b_11",
            target_evidence_id="tgt_b_11",
        )
        assert res.verdict == EvaluationVerdict.DIFFERENT
        assert any(d.difference_type == DifferenceType.BOUNDARY_BEHAVIOR_MISMATCH for d in res.differences)

    def test_12_no_boundary_metadata_is_not_applicable(self, default_policy):
        evaluator = BoundaryEvaluator()
        res = evaluator.evaluate(
            input_id="in-bnd-12",
            boundary_category=None,
            reference_output={"result": 10},
            target_output={"result": 10},
            policy=default_policy,
        )
        assert res.verdict == EvaluationVerdict.NOT_APPLICABLE

    # --- STATE (13-15) ---

    def test_13_equivalent_db_evidence_is_equivalent(self, default_policy):
        evaluator = StateEvaluator()
        res = evaluator.evaluate(
            input_id="in-st-13",
            reference_db_or_records={"table": "users", "operation": "UPDATE", "row_count": 1},
            target_db_or_records={"table": "users", "operation": "UPDATE", "row_count": 1},
            policy_or_file=default_policy,
            reference_evidence_id="ref_st_13",
            target_evidence_id="tgt_st_13",
        )
        assert res.verdict == EvaluationVerdict.EQUIVALENT

    def test_14_different_db_evidence_is_different(self, default_policy):
        evaluator = StateEvaluator()
        res = evaluator.evaluate(
            input_id="in-st-14",
            reference_db_or_records={"table": "users", "operation": "INSERT", "row_count": 1},
            target_db_or_records={"table": "users", "operation": "DELETE", "row_count": 1},
            policy_or_file=default_policy,
            reference_evidence_id="ref_st_14",
            target_evidence_id="tgt_st_14",
        )
        assert res.verdict == EvaluationVerdict.DIFFERENT
        assert any(d.difference_type == DifferenceType.DATABASE_MUTATION_MISMATCH for d in res.differences)

    def test_15_missing_target_db_evidence_is_inconclusive(self, default_policy):
        evaluator = StateEvaluator()
        res = evaluator.evaluate(
            input_id="in-st-15",
            reference_db_or_records={"table": "users", "operation": "UPDATE", "row_count": 1},
            target_db_or_records=None,
            policy_or_file=default_policy,
            reference_evidence_id="ref_st_15",
        )
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    # --- WORKFLOW (16-18) ---

    def test_16_same_observable_sequence_is_equivalent(self, default_policy):
        evaluator = WorkflowEvaluator()
        res = evaluator.evaluate(
            input_id="in-wf-16",
            reference_trace={"events": ["stage_parse", "stage_validate", "stage_commit"]},
            target_trace={"events": ["stage_parse", "stage_validate", "stage_commit"]},
            policy=default_policy,
            reference_evidence_id="ref_wf_16",
            target_evidence_id="tgt_wf_16",
        )
        assert res.verdict == EvaluationVerdict.EQUIVALENT

    def test_17_different_observable_sequence_is_different(self, default_policy):
        evaluator = WorkflowEvaluator()
        res = evaluator.evaluate(
            input_id="in-wf-17",
            reference_trace={"events": ["stage_validate", "stage_commit"]},
            target_trace={"events": ["stage_commit", "stage_validate"]},
            policy=default_policy,
            reference_evidence_id="ref_wf_17",
            target_evidence_id="tgt_wf_17",
        )
        assert res.verdict == EvaluationVerdict.DIFFERENT

    def test_18_missing_target_trace_is_inconclusive(self, default_policy):
        evaluator = WorkflowEvaluator()
        res = evaluator.evaluate(
            input_id="in-wf-18",
            reference_trace={"events": ["stage_validate", "stage_commit"]},
            target_trace=None,
            policy=default_policy,
            reference_evidence_id="ref_wf_18",
        )
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    # --- NONFUNCTIONAL (19-22) ---

    def test_19_disabled_nonfunctional_policy_is_not_applicable(self):
        policy = resolve_comparison_policy("default_v2")
        evaluator = NonFunctionalEvaluator()
        res = evaluator.evaluate(
            input_id="in-nf-19",
            reference_duration_ms=100.0,
            target_duration_ms=500.0,
            policy=policy,
        )
        assert res.verdict == EvaluationVerdict.NOT_APPLICABLE

    def test_20_enabled_within_fixed_threshold_is_equivalent(self):
        policy = ComparisonPolicy(
            policy_id="nf_policy",
            max_latency_ratio=2.5,
        )
        evaluator = NonFunctionalEvaluator()
        res = evaluator.evaluate(
            input_id="in-nf-20",
            reference_duration_ms=100.0,
            target_duration_ms=150.0,
            policy=policy,
        )
        assert res.verdict == EvaluationVerdict.EQUIVALENT

    def test_21_enabled_threshold_exceeded_is_different(self):
        policy = ComparisonPolicy(
            policy_id="nf_policy",
            max_latency_ratio=1.5,
        )
        evaluator = NonFunctionalEvaluator()
        res = evaluator.evaluate(
            input_id="in-nf-21",
            reference_duration_ms=100.0,
            target_duration_ms=300.0,
            policy=policy,
            reference_evidence_id="ref_nf_21",
            target_evidence_id="tgt_nf_21",
        )
        assert res.verdict == EvaluationVerdict.DIFFERENT
        assert any(d.difference_type == DifferenceType.NONFUNCTIONAL_THRESHOLD_EXCEEDED for d in res.differences)

    def test_22_enabled_missing_metric_is_inconclusive(self):
        policy = ComparisonPolicy(
            policy_id="nf_policy",
            max_latency_ratio=2.0,
        )
        evaluator = NonFunctionalEvaluator()
        res = evaluator.evaluate(
            input_id="in-nf-22",
            reference_duration_ms=100.0,
            target_duration_ms=None,
            policy=policy,
            reference_evidence_id="ref_nf_22",
        )
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    # --- AGGREGATION (23-27) ---

    def test_23_any_different_yields_overall_different(self, default_policy):
        engine = BehavioralEvaluationEngine()
        # Create bundle with 2 inputs: one equivalent, one different
        session_id = "sess_agg_23"
        app_id = "app_agg"
        r_out1 = OutputEvidencePayload(status_code=200, raw_output={"val": 1}, normalized_output={"val": 1})
        t_out1 = OutputEvidencePayload(status_code=200, raw_output={"val": 1}, normalized_output={"val": 1})
        r_out2 = OutputEvidencePayload(status_code=200, raw_output={"val": 10}, normalized_output={"val": 10})
        t_out2 = OutputEvidencePayload(status_code=200, raw_output={"val": 99}, normalized_output={"val": 99})

        recs = [
            EvidenceRecord(evidence_id="r1", session_id=session_id, input_id="in-1", role=AdapterRole.REFERENCE, evidence_type=EvidenceType.OUTPUT, payload=r_out1.model_dump()),
            EvidenceRecord(evidence_id="t1", session_id=session_id, input_id="in-1", role=AdapterRole.TARGET, evidence_type=EvidenceType.OUTPUT, payload=t_out1.model_dump()),
            EvidenceRecord(evidence_id="r2", session_id=session_id, input_id="in-2", role=AdapterRole.REFERENCE, evidence_type=EvidenceType.OUTPUT, payload=r_out2.model_dump()),
            EvidenceRecord(evidence_id="t2", session_id=session_id, input_id="in-2", role=AdapterRole.TARGET, evidence_type=EvidenceType.OUTPUT, payload=t_out2.model_dump()),
        ]
        bundle = EvidenceBundle(
            bundle_id="bnd_agg_23",
            session_id=session_id,
            application_id=app_id,
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c23", application_id=app_id, input_set_id="is23", input_set_hash="h23", records=recs),
            records=recs,
        )
        res = engine.evaluate_bundle(bundle, policy=default_policy)
        assert res.verdict == EvaluationVerdict.DIFFERENT

    def test_24_no_different_with_inconclusive_yields_overall_inconclusive(self, default_policy):
        engine = BehavioralEvaluationEngine()
        # Input 1: equivalent, Input 2: target missing (inconclusive)
        session_id = "sess_agg_24"
        app_id = "app_agg"
        r_out1 = OutputEvidencePayload(status_code=200, raw_output={"val": 1}, normalized_output={"val": 1})
        t_out1 = OutputEvidencePayload(status_code=200, raw_output={"val": 1}, normalized_output={"val": 1})
        r_out2 = OutputEvidencePayload(status_code=200, raw_output={"val": 10}, normalized_output={"val": 10})

        recs = [
            EvidenceRecord(evidence_id="r1", session_id=session_id, input_id="in-1", role=AdapterRole.REFERENCE, evidence_type=EvidenceType.OUTPUT, payload=r_out1.model_dump()),
            EvidenceRecord(evidence_id="t1", session_id=session_id, input_id="in-1", role=AdapterRole.TARGET, evidence_type=EvidenceType.OUTPUT, payload=t_out1.model_dump()),
            EvidenceRecord(evidence_id="r2", session_id=session_id, input_id="in-2", role=AdapterRole.REFERENCE, evidence_type=EvidenceType.OUTPUT, payload=r_out2.model_dump()),
        ]
        bundle = EvidenceBundle(
            bundle_id="bnd_agg_24",
            session_id=session_id,
            application_id=app_id,
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c24", application_id=app_id, input_set_id="is24", input_set_hash="h24", records=recs),
            records=recs,
        )
        res = engine.evaluate_bundle(bundle, policy=default_policy)
        assert res.verdict == EvaluationVerdict.INCONCLUSIVE

    def test_25_all_required_dimensions_equivalent_yields_overall_equivalent(self, default_policy):
        engine = BehavioralEvaluationEngine()
        session_id = "sess_agg_25"
        app_id = "app_agg"
        r_out = OutputEvidencePayload(status_code=200, raw_output={"val": 1}, normalized_output={"val": 1})
        t_out = OutputEvidencePayload(status_code=200, raw_output={"val": 1}, normalized_output={"val": 1})

        recs = [
            EvidenceRecord(evidence_id="r1", session_id=session_id, input_id="in-1", role=AdapterRole.REFERENCE, evidence_type=EvidenceType.OUTPUT, payload=r_out.model_dump()),
            EvidenceRecord(evidence_id="t1", session_id=session_id, input_id="in-1", role=AdapterRole.TARGET, evidence_type=EvidenceType.OUTPUT, payload=t_out.model_dump()),
        ]
        bundle = EvidenceBundle(
            bundle_id="bnd_agg_25",
            session_id=session_id,
            application_id=app_id,
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c25", application_id=app_id, input_set_id="is25", input_set_hash="h25", records=recs),
            records=recs,
        )
        res = engine.evaluate_bundle(bundle, policy=default_policy)
        assert res.verdict == EvaluationVerdict.EQUIVALENT

    def test_26_not_applicable_dimensions_do_not_falsely_fail_evaluation(self, default_policy):
        engine = BehavioralEvaluationEngine()
        # Bundle with only output evidence (other 4 dimensions return NOT_APPLICABLE)
        bundle = create_sample_bundle(tamper=False, include_difference=False)
        res = engine.evaluate_bundle(bundle, policy=default_policy)
        assert res.verdict == EvaluationVerdict.EQUIVALENT
        # Verify NOT_APPLICABLE dimensions exist but overall verdict is EQUIVALENT
        assert res.summary.dimension_summaries[BehaviorDimension.STATE].overall_verdict == EvaluationVerdict.NOT_APPLICABLE
        assert res.summary.dimension_summaries[BehaviorDimension.WORKFLOW].overall_verdict == EvaluationVerdict.NOT_APPLICABLE

    def test_27_unselected_dimensions_do_not_affect_overall_verdict(self, default_policy):
        engine = BehavioralEvaluationEngine()
        # Given matching outputs but mismatched trace in evidence
        session_id = "sess_agg_27"
        app_id = "app_agg"
        r_out = OutputEvidencePayload(status_code=200, raw_output={"val": 1}, normalized_output={"val": 1})
        t_out = OutputEvidencePayload(status_code=200, raw_output={"val": 1}, normalized_output={"val": 1})
        r_tr = TraceEvidencePayload(call_sequence=["A", "B"])
        t_tr = TraceEvidencePayload(call_sequence=["B", "A"])  # differing trace

        recs = [
            EvidenceRecord(evidence_id="r1", session_id=session_id, input_id="in-1", role=AdapterRole.REFERENCE, evidence_type=EvidenceType.OUTPUT, payload=r_out.model_dump()),
            EvidenceRecord(evidence_id="t1", session_id=session_id, input_id="in-1", role=AdapterRole.TARGET, evidence_type=EvidenceType.OUTPUT, payload=t_out.model_dump()),
            EvidenceRecord(evidence_id="r2", session_id=session_id, input_id="in-1", role=AdapterRole.REFERENCE, evidence_type=EvidenceType.TRACE, payload=r_tr.model_dump()),
            EvidenceRecord(evidence_id="t2", session_id=session_id, input_id="in-1", role=AdapterRole.TARGET, evidence_type=EvidenceType.TRACE, payload=t_tr.model_dump()),
        ]
        bundle = EvidenceBundle(
            bundle_id="bnd_agg_27",
            session_id=session_id,
            application_id=app_id,
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c27", application_id=app_id, input_set_id="is27", input_set_hash="h27", records=recs),
            records=recs,
        )
        # When evaluating with ONLY OUTPUT dimension selected, workflow mismatch is ignored
        res_output_only = engine.evaluate_bundle(
            bundle=bundle,
            policy=default_policy,
            dimensions=[BehaviorDimension.OUTPUT],
        )
        assert res_output_only.verdict == EvaluationVerdict.EQUIVALENT

    # --- DETERMINISM (28-30) ---

    def test_28_evaluate_exact_same_bundle_twice_same_evaluation_hash(self, default_policy):
        engine = BehavioralEvaluationEngine()
        bundle = create_sample_bundle(tamper=False, include_difference=False)

        res1 = engine.evaluate_bundle(bundle=bundle, policy=default_policy)
        res2 = engine.evaluate_bundle(bundle=bundle, policy=default_policy)
        assert res1.evaluation_hash == res2.evaluation_hash

    def test_29_same_policy_twice_same_policy_hash(self):
        p1 = ComparisonPolicy(policy_id="test_hash", float_tolerance=0.01, ignore_keys=["z", "a"])
        p2 = ComparisonPolicy(policy_id="test_hash", float_tolerance=0.01, ignore_keys=["a", "z"])
        assert p1.compute_policy_hash() == p2.compute_policy_hash()

    def test_30_equivalent_evidence_ordering_produces_stable_evaluation(self, default_policy):
        engine = BehavioralEvaluationEngine()
        session_id = "sess_det_30"
        app_id = "app_det"
        r1 = OutputEvidencePayload(status_code=200, raw_output={"v": 1}, normalized_output={"v": 1})
        t1 = OutputEvidencePayload(status_code=200, raw_output={"v": 1}, normalized_output={"v": 1})
        r2 = OutputEvidencePayload(status_code=200, raw_output={"v": 2}, normalized_output={"v": 2})
        t2 = OutputEvidencePayload(status_code=200, raw_output={"v": 2}, normalized_output={"v": 2})

        rec_r1 = EvidenceRecord(evidence_id="r1", session_id=session_id, input_id="in-01", role=AdapterRole.REFERENCE, evidence_type=EvidenceType.OUTPUT, payload=r1.model_dump())
        rec_t1 = EvidenceRecord(evidence_id="t1", session_id=session_id, input_id="in-01", role=AdapterRole.TARGET, evidence_type=EvidenceType.OUTPUT, payload=t1.model_dump())
        rec_r2 = EvidenceRecord(evidence_id="r2", session_id=session_id, input_id="in-02", role=AdapterRole.REFERENCE, evidence_type=EvidenceType.OUTPUT, payload=r2.model_dump())
        rec_t2 = EvidenceRecord(evidence_id="t2", session_id=session_id, input_id="in-02", role=AdapterRole.TARGET, evidence_type=EvidenceType.OUTPUT, payload=t2.model_dump())

        bundle_order1 = EvidenceBundle(
            bundle_id="bnd_det_30",
            session_id=session_id,
            application_id=app_id,
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c30", application_id=app_id, input_set_id="is30", input_set_hash="h30", records=[rec_r1, rec_t1, rec_r2, rec_t2]),
            records=[rec_r1, rec_t1, rec_r2, rec_t2],
        )
        bundle_order2 = EvidenceBundle(
            bundle_id="bnd_det_30",
            session_id=session_id,
            application_id=app_id,
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c30", application_id=app_id, input_set_id="is30", input_set_hash="h30", records=[rec_t2, rec_r1, rec_t1, rec_r2]),
            records=[rec_t2, rec_r1, rec_t1, rec_r2],
        )
        res1 = engine.evaluate_bundle(bundle_order1, policy=default_policy)
        res2 = engine.evaluate_bundle(bundle_order2, policy=default_policy)
        assert res1.verdict == res2.verdict
        assert res1.evaluation_hash == res2.evaluation_hash

    # --- TRACEABILITY (31) ---

    def test_31_all_detected_behavioral_differences_contain_evidence_ids(self, default_policy):
        evaluator = OutputEvaluator()
        res = evaluator.evaluate(
            input_id="in-tr-31",
            reference_payload={"status": "A"},
            target_payload={"status": "B"},
            policy=default_policy,
            reference_evidence_id="ref_trace_31",
            target_evidence_id="tgt_trace_31",
        )
        assert res.verdict == EvaluationVerdict.DIFFERENT
        assert len(res.differences) > 0
        for diff in res.differences:
            assert diff.reference_evidence_id == "ref_trace_31"
            assert diff.target_evidence_id == "tgt_trace_31"
            assert diff.input_id == "in-tr-31"

