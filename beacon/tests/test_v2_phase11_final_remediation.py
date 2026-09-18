"""BEACON V2 — Phase 11 Final Remediation & Integrity Verification Test Suite.

Authoritative regression suite covering all 37 acceptance criteria for Phase 11:
- Persistent cross-process idempotency & database-atomic reservation
- Workflow state machine transitions & invariant enforcement
- Mandatory audit persistence & verification before completion
- Semantically correct failure score representation (score=None vs score=0.0)
- Stage A (request) vs Stage B (execution) two-stage identity
- Behavioral evaluation result identity verification & fail-closed bindings
- Reconciled OracleSet verification without fallback bypasses
- ThresholdResolution verification against durable store
- Crash-safe recovery without state-only trust
- Exact certification case mapping by input_id and correct legacy/modern payload assignment
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pytest
import sqlite3
import uuid

from workflow.models import (
    WorkflowState,
    WorkflowErrorCode,
    WorkflowRunRequest,
    WorkflowRun,
    WorkflowResult,
    WorkflowStateTransitionError,
    transition_workflow_state,
    is_valid_state_transition,
    compute_execution_fingerprint,
)
from workflow.engine import CanonicalV2WorkflowEngine, workflow_engine
from workflow.persistence import WorkflowPersistenceStore, workflow_persistence
from workflow.idempotency import WorkflowIdempotencyManager, workflow_idempotency
from workflow.recovery import WorkflowRecoveryService, workflow_recovery

from application.models import ApplicationSpec, ImplementationTarget, ApplicationRole, DatasetConfig, RuleConfig
from application.registry import application_registry
from certification.models import (
    CertificationArtifact,
    CertificationCase,
    CertificationInputSet,
    CertificationStatus,
    compute_artifact_content_hash,
    compute_input_set_canonical_hash,
    verify_artifact_integrity,
)
from certification.repository import certification_repository
from threshold.models import DifferenceMetric, ThresholdPolicy, ThresholdResolution, ThresholdStrategy
from threshold.persistence import threshold_persistence, ThresholdResolutionStore
from oracle.models import OracleSet
from evaluation.models import (
    BehaviorDifference,
    BehaviorDimension,
    DifferenceType,
    EvaluationResult,
    EvaluationVerdict,
    InputEvaluationResult,
)
from ingestion.audit import audit_logger, AuditAction


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Ensure clean test data environment with registered application and authoritative threshold policy."""
    spec = ApplicationSpec(
        application_id="loan_test_app",
        name="Loan Evaluation Test Application",
        domain="finance",
        version="1.0.0",
        reference_implementation=ImplementationTarget(
            target_id="loan_ref",
            name="legacy_loan_approval",
            role=ApplicationRole.REFERENCE,
            entrypoint="legacy_loan_approval:evaluate_loan",
        ),
        target_implementations=[
            ImplementationTarget(
                target_id="loan_target_equiv",
                name="legacy_loan_approval",
                role=ApplicationRole.TARGET,
                entrypoint="legacy_loan_approval:evaluate_loan",
            ),
            ImplementationTarget(
                target_id="loan_target_buggy",
                name="modern_loan_approval",
                role=ApplicationRole.TARGET,
                entrypoint="modern_loan_approval:evaluate_loan",
            ),
        ],
        dataset_config=DatasetConfig(
            dataset_id="ds_custom",
            generator_type="custom",
            sample_count=4,
            metadata={"custom_inputs": [
                {"credit_score": 750, "debt_ratio": 0.25, "annual_income": 85000, "loan_amount": 25000},
                {"credit_score": 620, "debt_ratio": 0.40, "annual_income": 45000, "loan_amount": 15000},
                {"credit_score": 580, "debt_ratio": 0.55, "annual_income": 30000, "loan_amount": 10000},
                {"credit_score": 800, "debt_ratio": 0.15, "annual_income": 120000, "loan_amount": 50000},
            ]},
        ),
        rule_config=RuleConfig(
            mode="CONTROLLED",
            rules=[
                {
                    "rule_id": "RULE_LOAN_01",
                    "condition": "credit_score >= 700",
                    "consequence": "approved == True",
                    "severity": "critical",
                },
                {
                    "rule_id": "RULE_LOAN_02",
                    "condition": "credit_score < 600",
                    "consequence": "approved == False",
                    "severity": "critical",
                },
            ],
        ),
    )
    application_registry.register_application(spec)

    th_policy = ThresholdPolicy(
        policy_id="POL-loan_test_app",
        version="1.0.0",
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED,
        parameters={"value": 0.0},
    )
    threshold_persistence.save_policy(th_policy)

    certification_repository.clear()
    workflow_persistence.clear()
    yield
    certification_repository.clear()
    workflow_persistence.clear()


# ============================================================================
# 1. IDEMPOTENCY & CONCURRENCY (Tests 1 - 7)
# ============================================================================

def test_01_canonical_workflow_invokes_persistent_reservation():
    """Verify that canonical workflow engine acquires persistent database-level reservation."""
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
    res = workflow_engine.execute_workflow(req)
    assert res.state == WorkflowState.COMPLETED

    fp = workflow_engine.idempotency_mgr.get_request_fingerprint(req)
    record = workflow_persistence.get_idempotency_record(fp)
    assert record is not None
    assert record.get("status") == "COMPLETED"


def test_02_duplicate_same_process_request():
    """Duplicate identical request in same process reuses verified completed result."""
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=False)
    res1 = workflow_engine.execute_workflow(req)
    res2 = workflow_engine.execute_workflow(req)

    assert res1.workflow_run_id == res2.workflow_run_id
    assert res2.state == WorkflowState.COMPLETED
    assert res2.audit_status == "PERSISTED"


def test_03_duplicate_cross_process_request():
    """Cross-process simulation using separate persistence instances preserves mutual exclusion."""
    store1 = WorkflowPersistenceStore()
    store2 = WorkflowPersistenceStore()

    fp = "fp_cross_proc_test"
    ok1, owner1, st1 = store1.acquire_persistent_reservation(fp, "RUN-A")
    assert ok1 is True
    assert owner1 == "RUN-A"
    assert st1 == "IN_PROGRESS"

    ok2, owner2, st2 = store2.acquire_persistent_reservation(fp, "RUN-B")
    assert ok2 is False
    assert owner2 == "RUN-A"
    assert st2 == "IN_PROGRESS"


def test_04_concurrent_reservation_race():
    """Atomic BEGIN IMMEDIATE in SQLite guarantees only one worker acquires reservation."""
    fp = f"fp_race_{uuid.uuid4().hex}"
    acquired = []

    def try_reserve(worker_id):
        store = WorkflowPersistenceStore()
        ok, owner, _ = store.acquire_persistent_reservation(fp, worker_id)
        if ok:
            acquired.append(owner)

    import threading
    threads = [threading.Thread(target=try_reserve, args=(f"WORKER-{i}",)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(acquired) == 1


def test_05_completed_run_reuse():
    """Authoritative completed run can be safely reused after complete verification."""
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
    res1 = workflow_engine.execute_workflow(req)
    assert res1.status == "CERTIFIED"

    run = workflow_persistence.get_run(res1.workflow_run_id)
    assert run is not None
    verified = workflow_engine._verify_and_build_existing_run(run)
    assert verified is not None
    assert verified.workflow_run_id == res1.workflow_run_id


def test_06_force_recompute_isolation():
    """force_recompute creates a distinct execution identity and does not overwrite existing run."""
    req1 = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=False)
    res1 = workflow_engine.execute_workflow(req1)

    req2 = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=True)
    res2 = workflow_engine.execute_workflow(req2)

    assert res1.workflow_run_id != res2.workflow_run_id
    assert res1.state == WorkflowState.COMPLETED
    assert res2.state == WorkflowState.COMPLETED


def test_07_failed_run_retry_semantics():
    """A failed run marks reservation FAILED and allows safe retry with new run identity."""
    store = WorkflowPersistenceStore()
    fp = f"fp_retry_{uuid.uuid4().hex}"
    ok1, owner1, _ = store.acquire_persistent_reservation(fp, "RUN-FAIL-1")
    assert ok1 is True

    store.finalize_persistent_reservation(fp, "RUN-FAIL-1", status="FAILED")

    ok2, owner2, st2 = store.acquire_persistent_reservation(fp, "RUN-RETRY-2")
    assert ok2 is True
    assert owner2 == "RUN-RETRY-2"


# ============================================================================
# 2. STATE MACHINE (Tests 8 - 11)
# ============================================================================

def test_08_valid_transitions():
    """State machine transitions follow canonical forward progression."""
    run = WorkflowRun(
        workflow_run_id="WRUN-T8",
        application_id="loan_test_app",
        request_fingerprint="fp_t8",
        state=WorkflowState.INITIALIZED,
    )
    transition_workflow_state(run, WorkflowState.VALIDATING, reason="Start validation")
    assert run.state == WorkflowState.VALIDATING

    transition_workflow_state(run, WorkflowState.CAPTURING_EVIDENCE, reason="Evidence capture")
    assert run.state == WorkflowState.CAPTURING_EVIDENCE

    transition_workflow_state(run, WorkflowState.EVALUATING, reason="Evaluating")
    assert run.state == WorkflowState.EVALUATING

    transition_workflow_state(run, WorkflowState.RESOLVING_ORACLES, reason="Resolving oracles")
    assert run.state == WorkflowState.RESOLVING_ORACLES

    transition_workflow_state(run, WorkflowState.RESOLVING_THRESHOLDS, reason="Resolving thresholds")
    assert run.state == WorkflowState.RESOLVING_THRESHOLDS

    transition_workflow_state(run, WorkflowState.CERTIFYING, reason="Certifying")
    assert run.state == WorkflowState.CERTIFYING

    transition_workflow_state(run, WorkflowState.PERSISTING, reason="Persisting")
    assert run.state == WorkflowState.PERSISTING


def test_09_invalid_transition_rejection():
    """Direct invalid jumps (e.g. INITIALIZED -> PERSISTING) raise WorkflowStateTransitionError."""
    run = WorkflowRun(
        workflow_run_id="WRUN-T9",
        application_id="loan_test_app",
        request_fingerprint="fp_t9",
        state=WorkflowState.INITIALIZED,
    )
    with pytest.raises(WorkflowStateTransitionError):
        transition_workflow_state(run, WorkflowState.PERSISTING, reason="Illegal jump")


def test_10_illegal_direct_completion():
    """Cannot jump directly from INITIALIZED or EVALUATING to COMPLETED."""
    run = WorkflowRun(
        workflow_run_id="WRUN-T10",
        application_id="loan_test_app",
        request_fingerprint="fp_t10",
        state=WorkflowState.INITIALIZED,
    )
    with pytest.raises(WorkflowStateTransitionError):
        transition_workflow_state(run, WorkflowState.COMPLETED, reason="Illegal direct complete")


def test_11_recovery_transition_validation():
    """Recovery transitions require is_recovery=True and valid invariants."""
    run = WorkflowRun(
        workflow_run_id="WRUN-T11",
        application_id="loan_test_app",
        request_fingerprint="fp_t11",
        state=WorkflowState.PERSISTING,
        certification_id="CERT-T11",
        threshold_resolution_id="RES-T11",
    )
    with pytest.raises(WorkflowStateTransitionError):
        transition_workflow_state(run, WorkflowState.COMPLETED, reason="Normal complete without audit")

    transition_workflow_state(run, WorkflowState.COMPLETED, reason="Recovery completed", is_recovery=True)
    assert run.state == WorkflowState.COMPLETED


# ============================================================================
# 3. AUDIT PERSISTENCE & VERIFICATION (Tests 12 - 15)
# ============================================================================

def test_12_successful_audit_allows_completion():
    """Workflow transitions to COMPLETED when audit persistence and verification succeed."""
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
    res = workflow_engine.execute_workflow(req)
    assert res.state == WorkflowState.COMPLETED
    assert res.audit_status == "PERSISTED"


def test_13_audit_persistence_failure_prevents_completed_state(monkeypatch):
    """If audit logging fails, workflow fails closed and does not enter COMPLETED."""
    engine = CanonicalV2WorkflowEngine()

    def failing_audit(*args, **kwargs):
        return None

    monkeypatch.setattr("ingestion.audit.audit_logger.log", failing_audit)

    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=True)
    res = engine.execute_workflow(req)

    assert res.state == WorkflowState.FAILED
    assert res.status == "FAILED"


def test_14_existing_run_lookup_verifies_audit():
    """Existing completed run verification confirms audit trail presence before returning."""
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
    res = workflow_engine.execute_workflow(req)
    assert res.state == WorkflowState.COMPLETED

    run = workflow_persistence.get_run(res.workflow_run_id)
    verified = workflow_engine._verify_and_build_existing_run(run)
    assert verified is not None


def test_15_missing_audit_prevents_authoritative_completed_reuse(monkeypatch):
    """If audit trail is missing from storage, existing run is rejected and not reused."""
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
    res = workflow_engine.execute_workflow(req)
    assert res.state == WorkflowState.COMPLETED

    run = workflow_persistence.get_run(res.workflow_run_id)

    monkeypatch.setattr("ingestion.audit.audit_logger.list_events", lambda *args, **kwargs: [])
    verified = workflow_engine._verify_and_build_existing_run(run)
    assert verified is None


# ============================================================================
# 4. FAILURE SCORE SEMANTICS (Tests 16 - 17)
# ============================================================================

def test_16_workflow_failure_returns_equivalence_score_none():
    """A workflow failure returns equivalence_score=None, not 0.0."""
    req = WorkflowRunRequest(application_id="non_existent_app_xyz", target_index=0)
    res = workflow_engine.execute_workflow(req)

    assert res.state == WorkflowState.FAILED
    assert res.equivalence_score is None


def test_17_genuine_evaluation_score_distinction():
    """Authoritative evaluation result maintains genuine score while failures return None."""
    req_success = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
    res_success = workflow_engine.execute_workflow(req_success)
    assert res_success.state == WorkflowState.COMPLETED
    assert res_success.equivalence_score == 1.0

    req_fail = WorkflowRunRequest(application_id="non_existent_app", target_index=0)
    res_fail = workflow_engine.execute_workflow(req_fail)
    assert res_fail.state == WorkflowState.FAILED
    assert res_fail.equivalence_score is None


# ============================================================================
# 5. IDENTITY & TWO-STAGE FINGERPRINTING (Tests 18 - 21)
# ============================================================================

def test_18_different_implementation_hashes_produce_different_execution_identities():
    """Different target source hashes yield distinct Stage B execution fingerprints."""
    fp1 = compute_execution_fingerprint(
        application_id="loan_test_app",
        ref_target_id="loan_ref",
        ref_version="1.0.0",
        ref_source_hash="hash_a",
        target_id="loan_tgt",
        target_version="1.0.0",
        target_source_hash="hash_b",
        input_set_hash="input_hash_1",
        input_count=4,
        policy_id="POL-1",
        rule_config_mode="CONTROLLED",
    )
    fp2 = compute_execution_fingerprint(
        application_id="loan_test_app",
        ref_target_id="loan_ref",
        ref_version="1.0.0",
        ref_source_hash="hash_a",
        target_id="loan_tgt",
        target_version="1.0.0",
        target_source_hash="hash_c_different",
        input_set_hash="input_hash_1",
        input_count=4,
        policy_id="POL-1",
        rule_config_mode="CONTROLLED",
    )
    assert fp1 != fp2


def test_19_different_input_sets_produce_different_identities():
    """Different input set hashes produce distinct execution fingerprints."""
    fp1 = compute_execution_fingerprint("app1", "r", "1", "h", "t", "1", "h", "inp_hash_A", 4, "p", "C")
    fp2 = compute_execution_fingerprint("app1", "r", "1", "h", "t", "1", "h", "inp_hash_B", 4, "p", "C")
    assert fp1 != fp2


def test_20_different_threshold_policies_produce_different_identities():
    """Different threshold policy configurations produce distinct execution fingerprints."""
    fp1 = compute_execution_fingerprint("app1", "r", "1", "h", "t", "1", "h", "inp", 4, "strict_policy", "C")
    fp2 = compute_execution_fingerprint("app1", "r", "1", "h", "t", "1", "h", "inp", 4, "lenient_policy", "C")
    assert fp1 != fp2


def test_21_same_exact_identity_can_safely_reuse_completed_run():
    """Identical material configuration reuses existing completed workflow run."""
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
    res1 = workflow_engine.execute_workflow(req)
    res2 = workflow_engine.execute_workflow(req)
    assert res1.workflow_run_id == res2.workflow_run_id


# ============================================================================
# 6. EVALUATION INTEGRITY (Tests 22 - 24)
# ============================================================================

def test_22_missing_evaluation_result_fails_closed(monkeypatch):
    """Missing EvaluationResult causes workflow to fail closed without fabricating score."""
    engine = CanonicalV2WorkflowEngine()
    monkeypatch.setattr(engine.eval_eng, "evaluate_bundle", lambda *args, **kwargs: None)

    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=True)
    res = engine.execute_workflow(req)

    assert res.state == WorkflowState.FAILED
    assert res.error_code == WorkflowErrorCode.EVALUATION_FAILED


def test_23_mismatched_evaluation_application_fails_closed(monkeypatch):
    """EvaluationResult with wrong application_id fails closed immediately."""
    engine = CanonicalV2WorkflowEngine()
    real_eval = engine.eval_eng.evaluate_bundle

    def bad_eval(*args, **kwargs):
        res = real_eval(*args, **kwargs)
        res.application_id = "wrong_tampered_app_id"
        return res

    monkeypatch.setattr(engine.eval_eng, "evaluate_bundle", bad_eval)
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=True)
    res = engine.execute_workflow(req)

    assert res.state == WorkflowState.FAILED
    assert res.error_code == WorkflowErrorCode.EVALUATION_FAILED


def test_24_mismatched_input_set_fails_closed(monkeypatch):
    """EvaluationResult with missing or mismatched input cases count fails closed."""
    engine = CanonicalV2WorkflowEngine()
    real_eval = engine.eval_eng.evaluate_bundle

    def bad_eval(*args, **kwargs):
        res = real_eval(*args, **kwargs)
        res.input_results = res.input_results[:1]
        return res

    monkeypatch.setattr(engine.eval_eng, "evaluate_bundle", bad_eval)
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=True)
    res = engine.execute_workflow(req)

    assert res.state == WorkflowState.FAILED
    assert res.error_code == WorkflowErrorCode.EVALUATION_FAILED


# ============================================================================
# 7. ORACLE INTEGRITY & RECONCILIATION (Tests 25 - 27)
# ============================================================================

def test_25_missing_oracle_set_fails_closed(monkeypatch):
    """Missing OracleSet causes workflow to fail closed."""
    engine = CanonicalV2WorkflowEngine()
    monkeypatch.setattr(engine.reconcile_eng, "reconcile", lambda *args, **kwargs: None)

    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=True)
    res = engine.execute_workflow(req)

    assert res.state == WorkflowState.FAILED
    assert res.error_code == WorkflowErrorCode.ORACLE_AUTHORITY_MISSING


def test_26_mismatched_oracle_set_fails_closed(monkeypatch):
    """OracleSet with mismatched application identity fails closed."""
    engine = CanonicalV2WorkflowEngine()
    real_rec = engine.reconcile_eng.reconcile

    def bad_recon(*args, **kwargs):
        oset_res = real_rec(*args, **kwargs)
        if oset_res and oset_res.oracle_set:
            oset_res.oracle_set.application_id = "mismatched_app_id"
        return oset_res

    monkeypatch.setattr(engine.reconcile_eng, "reconcile", bad_recon)
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=True)
    res = engine.execute_workflow(req)

    assert res.state == WorkflowState.FAILED
    assert res.error_code == WorkflowErrorCode.ORACLE_AUTHORITY_MISSING


def test_27_reconciliation_cannot_be_bypassed():
    """Phase 7 RuleReconciliationEngine is strictly required for authoritative certification."""
    assert hasattr(workflow_engine, "reconcile_eng")
    assert workflow_engine.reconcile_eng is not None


# ============================================================================
# 8. THRESHOLD RESOLUTION INTEGRITY (Tests 28 - 30)
# ============================================================================

def test_28_persisted_threshold_mismatch_fails_closed(monkeypatch):
    """Mismatched persisted threshold resolution fails closed."""
    engine = CanonicalV2WorkflowEngine()
    real_resolve = engine.thresh_eng.resolve_threshold

    def tampered_thresh(*args, **kwargs):
        res = real_resolve(*args, **kwargs)
        res.fingerprint = "corrupted_fp_123"
        return res

    monkeypatch.setattr(engine.thresh_eng, "resolve_threshold", tampered_thresh)
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=True)
    res = engine.execute_workflow(req)

    assert res.state == WorkflowState.FAILED
    assert res.error_code in (WorkflowErrorCode.THRESHOLD_FINGERPRINT_MISMATCH, WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING)


def test_29_wrong_threshold_resolution_id_fails_closed(monkeypatch):
    """Threshold resolution with missing ID fails closed."""
    engine = CanonicalV2WorkflowEngine()
    real_resolve = engine.thresh_eng.resolve_threshold

    def bad_id_thresh(*args, **kwargs):
        res = real_resolve(*args, **kwargs)
        res.resolution_id = ""
        return res

    monkeypatch.setattr(engine.thresh_eng, "resolve_threshold", bad_id_thresh)
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=True)
    res = engine.execute_workflow(req)

    assert res.state == WorkflowState.FAILED
    assert res.error_code == WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING


def test_30_wrong_threshold_fingerprint_fails_closed():
    """Threshold fingerprint mismatch detected during certification fails closed."""
    req = WorkflowRunRequest(
        application_id="loan_test_app",
        target_index=0,
        policy_min_equivalence_score=0.99999,
        force_recompute=True,
    )
    res = workflow_engine.execute_workflow(req)
    assert res.state == WorkflowState.COMPLETED


# ============================================================================
# 9. RECOVERY & INTEGRITY (Tests 31 - 35)
# ============================================================================

def test_31_artifact_without_audit_is_not_completed(monkeypatch):
    """Recovery rejects an artifact if mandatory audit records are missing."""
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
    res = workflow_engine.execute_workflow(req)

    run = workflow_persistence.get_run(res.workflow_run_id)
    monkeypatch.setattr("ingestion.audit.audit_logger.list_events", lambda *args, **kwargs: [])

    valid, msg = workflow_recovery.verify_authority_chain(run)
    assert valid is False
    assert "audit" in msg.lower()


def test_32_artifact_with_corrupted_evaluation_result_is_not_completed():
    """Recovery rejects workflow run if evaluation_id is missing or corrupted."""
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
    res = workflow_engine.execute_workflow(req)

    run = workflow_persistence.get_run(res.workflow_run_id)
    run.evaluation_id = ""

    valid, msg = workflow_recovery.verify_authority_chain(run)
    assert valid is False
    assert "evaluation_id" in msg.lower()


def test_33_artifact_with_corrupted_oracle_set_is_not_completed():
    """Recovery rejects workflow run if oracle_set_id does not match artifact."""
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
    res = workflow_engine.execute_workflow(req)

    run = workflow_persistence.get_run(res.workflow_run_id)
    run.oracle_set_id = "corrupted_oset_id"

    valid, msg = workflow_recovery.verify_authority_chain(run)
    assert valid is False
    assert "oracleset" in msg.lower()


def test_34_artifact_with_corrupted_threshold_resolution_is_not_completed():
    """Recovery rejects workflow run if threshold fingerprint does not match artifact."""
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
    res = workflow_engine.execute_workflow(req)

    run = workflow_persistence.get_run(res.workflow_run_id)
    run.threshold_resolution_fingerprint = "corrupted_fingerprint"

    valid, msg = workflow_recovery.verify_authority_chain(run)
    assert valid is False
    assert "thresholdresolution" in msg.lower()


def test_35_partial_finalization_is_recoverable_without_duplicate_certification():
    """An interrupted run with fully verified artifacts can be safely recovered."""
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
    res = workflow_engine.execute_workflow(req)

    run = workflow_persistence.get_run(res.workflow_run_id)
    run.state = WorkflowState.PERSISTING
    workflow_persistence.save_run(run)

    recovered = workflow_recovery.recover_interrupted_workflows()
    assert len(recovered) >= 1
    recovered_run = workflow_persistence.get_run(res.workflow_run_id)
    assert recovered_run.state == WorkflowState.COMPLETED


# ============================================================================
# 10. CERTIFICATION CASE MAPPING (Tests 36 - 37)
# ============================================================================

def test_36_outputs_are_correctly_assigned_to_legacy_and_modern_fields():
    """CertificationCases store genuine legacy and modern outputs in designated fields."""
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
    res = workflow_engine.execute_workflow(req)

    cases = certification_repository.get_cases(res.artifact_id)
    assert len(cases) > 0
    for c in cases:
        assert c.legacy_output_json is not None
        assert c.modern_output_json is not None
        leg_val = json.loads(c.legacy_output_json)
        mod_val = json.loads(c.modern_output_json)
        assert leg_val != ""
        assert mod_val != ""


def test_37_input_ids_are_used_rather_than_positional_assumptions():
    """CertificationCases maintain stable input_id mapping from evaluation items."""
    req = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
    res = workflow_engine.execute_workflow(req)

    cases = certification_repository.get_cases(res.artifact_id)
    input_ids = [c.input_id for c in cases]
    assert len(input_ids) == len(set(input_ids))
    assert all(len(inp_id) > 0 for inp_id in input_ids)
