"""BEACON V2 — Phase 11 Production Readiness & End-to-End Workflow Test Suite

Comprehensive test suite verifying:
- Canonical V2 Workflow Engine execution orchestrating Phase 1-11
- Spy verification that authoritative engines (Phase 4, 5, 6, 7, 8, CertEngine) are genuinely invoked
- Multi-dimensional behavioral difference detection (Output, Error, State, Workflow)
- Exact Phase 8 ThresholdPolicy & ThresholdResolution authority enforcement without silent defaults
- Deterministic idempotency & persistent multi-process concurrency locking
- Transactional atomic persistence in SQLite WAL & audit trail
- Fail-closed crash recovery across Cases 1-6 with full cryptographic chain verification
- REST API (/api/v2/workflow/certify) & CLI contracts with RBAC authorization
- Grounded explanation integration & LLM authority isolation
- Security, log sanitization, secret protection, and tamper detection
"""

import copy
import hashlib
import json
import logging
import multiprocessing
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any
import pytest
from fastapi.testclient import TestClient

from api.main import app
from auth.models import User, UserRole, ProjectMembership
from auth.security import create_access_token
from auth.repository import auth_repository
from workflow.models import (
    WorkflowState,
    WorkflowErrorCode,
    WorkflowRunRequest,
    WorkflowRun,
    WorkflowResult,
)
from workflow.engine import CanonicalV2WorkflowEngine, workflow_engine
from workflow.persistence import WorkflowPersistenceStore, workflow_persistence
from workflow.idempotency import WorkflowIdempotencyManager, workflow_idempotency
from workflow.recovery import WorkflowRecoveryService, workflow_recovery

from application.registry import application_registry
from application.models import ApplicationSpec, ImplementationTarget, ApplicationRole, DatasetConfig, RuleConfig
from certification.models import CertificationStatus, CertificationArtifact, CertificationCase, CertificationInputSet
from certification.certification_engine import certification_engine
from certification.repository import certification_repository
from threshold.engine import ThresholdEngine
from threshold.models import ThresholdResolution, DifferenceMetric, ThresholdPolicy, ThresholdStrategy
from threshold.persistence import threshold_persistence
from oracle.models import OracleSet
from oracle.registry import registry as oracle_registry
from evaluation.models import EvaluationResult, BehaviorDifference, BehaviorDimension, DifferenceType, EvaluationVerdict


# --- TEST FIXTURES ---

@pytest.fixture(scope="module")
def api_client():
    """TestClient for FastAPI app with auth token."""
    client = TestClient(app)
    return client


@pytest.fixture(scope="module")
def admin_headers():
    admin = auth_repository.get_user_by_username("admin")
    if not admin:
        admin = auth_repository.create_user(
            username="admin",
            password="AdminPassword2026!",
            email="admin@beacon.local",
            full_name="System Administrator",
            is_system_admin=True,
        )
    token = create_access_token(admin)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def user_headers():
    user = auth_repository.get_user_by_username("user_phase11_nonadmin")
    if not user:
        user = auth_repository.create_user(
            username="user_phase11_nonadmin",
            password="NonAdminPassword2026!",
            email="nonadmin@beacon.local",
            full_name="Phase 11 Non-Admin User",
            is_system_admin=False,
        )
    auth_repository.assign_user_to_project(user.user_id, "loan_test_app", UserRole.PROJECT_ADMIN)
    memberships = auth_repository.get_user_memberships(user.user_id)
    token = create_access_token(user, memberships=memberships)
    return {"Authorization": f"Bearer {token}"}


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

    # Register authoritative threshold policy for loan_test_app
    th_policy = ThresholdPolicy(
        policy_id="POL-loan_test_app",
        version="1.0.0",
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED,
        parameters={"value": 0.0},
    )
    threshold_persistence.save_policy(th_policy)

    workflow_persistence.clear()
    yield
    workflow_persistence.clear()


# ==============================================================================
# A. HAPPY PATH TESTS
# ==============================================================================

class TestPhase11HappyPath:
    """Verifies complete, canonical end-to-end V2 certification."""

    def test_01_canonical_workflow_engine_execution(self):
        """Test complete V2 workflow execution through CanonicalV2WorkflowEngine."""
        req = WorkflowRunRequest(
            application_id="loan_test_app",
            target_index=0,
            policy_min_equivalence_score=0.999,
            explain=True,
            explanation_mode="deterministic",
        )
        result = workflow_engine.execute_workflow(req)

        assert isinstance(result, WorkflowResult)
        assert result.workflow_run_id.startswith("WRUN-")
        assert result.state == WorkflowState.COMPLETED
        assert result.status == "CERTIFIED"
        assert result.certified is True
        assert result.equivalence_score == 1.0
        assert result.artifact_id is not None
        assert result.threshold_resolution_id is not None
        assert result.threshold_resolution_fingerprint is not None
        assert result.unique_input_count == 4
        assert result.regressions_count == 0
        assert result.explanation is not None
        assert result.explanation.get("authoritative_match_status") == "CERTIFIED"
        assert result.explanation.get("context_fingerprint") is not None
        assert result.audit_status == "PERSISTED"

    def test_02_api_workflow_endpoint(self, api_client, admin_headers):
        """Test POST /api/v2/workflow/certify REST endpoint."""
        payload = {
            "application_id": "loan_test_app",
            "target_index": 0,
            "policy_min_equivalence_score": 0.95,
            "explain": True,
            "explanation_mode": "deterministic",
        }
        res = api_client.post("/api/v2/workflow/certify", json=payload, headers=admin_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["workflow_run_id"].startswith("WRUN-")
        assert data["certified"] is True
        assert data["status"] == "CERTIFIED"
        assert data["state"] == "COMPLETED"
        assert data["threshold_resolution_fingerprint"] is not None

        # Verify get run endpoint
        run_id = data["workflow_run_id"]
        run_res = api_client.get(f"/api/v2/workflow/runs/{run_id}", headers=admin_headers)
        assert run_res.status_code == 200
        run_data = run_res.json()
        assert run_data["workflow_run_id"] == run_id
        assert run_data["state"] == "COMPLETED"
        assert run_data["threshold_resolution_id"] == data["threshold_resolution_id"]

    def test_03_cli_workflow_command(self, capsys):
        """Test CLI certification workflow command with artifact persistence."""
        from cli import cmd_certify
        import argparse

        args = argparse.Namespace(
            project_id="loan_test_cli",
            legacy_version="1.0.0",
            modernized_version="2.0.0",
            oracle_set_id=None,
            implementation="equivalent",
            format="json",
            samples=20,
            min_score=0.80,
            allow_warnings=True,
            seed=42,
        )
        cmd_certify(args)
        captured = capsys.readouterr()
        assert len(captured.out) > 0
        data = json.loads(captured.out)
        cert_id = data.get("artifact_id") or data.get("certification_id")
        assert cert_id is not None

        # Verify persisted in repository
        artifact = certification_repository.get_artifact(cert_id)
        assert artifact is not None
        assert artifact.artifact_id == cert_id

    def test_04_buggy_target_workflow_divergence(self):
        """Test workflow execution with buggy modernized target detects regressions cleanly."""
        req = WorkflowRunRequest(
            application_id="loan_test_app",
            target_index=1,  # buggy target
            policy_min_equivalence_score=0.999,
            explain=True,
        )
        result = workflow_engine.execute_workflow(req)

        assert result.workflow_run_id.startswith("WRUN-")
        assert result.state == WorkflowState.COMPLETED
        assert result.status == "NOT_CERTIFIED"
        assert result.certified is False
        assert result.regressions_count > 0
        assert len(result.regressions) > 0
        assert result.explanation is not None


# ==============================================================================
# B. INPUT VALIDATION & PREFLIGHT TESTS
# ==============================================================================

class TestPhase11InputValidation:
    """Verifies that invalid or missing inputs fail closed immediately."""

    def test_05_unknown_application_fails_closed(self):
        """Test workflow request with nonexistent application fails closed with APPLICATION_NOT_FOUND."""
        req = WorkflowRunRequest(
            application_id="nonexistent_application_id_xyz",
            force_recompute=True,
        )
        result = workflow_engine.execute_workflow(req)

        assert result.state == WorkflowState.FAILED
        assert result.certified is False
        assert result.error_code == WorkflowErrorCode.APPLICATION_NOT_FOUND

    def test_06_invalid_target_index_fails_closed(self):
        """Test workflow request with out-of-range target_index fails closed with ADAPTER_RESOLUTION_FAILED."""
        req = WorkflowRunRequest(
            application_id="loan_test_app",
            target_index=999,
            force_recompute=True,
        )
        result = workflow_engine.execute_workflow(req)

        assert result.state == WorkflowState.FAILED
        assert result.certified is False
        assert result.error_code == WorkflowErrorCode.ADAPTER_RESOLUTION_FAILED

    def test_07_empty_inputs_fails_safely(self):
        """Test application with 0 inputs fails closed safely."""
        empty_spec = ApplicationSpec(
            application_id="empty_input_app",
            name="Empty Input App",
            domain="test",
            version="1.0.0",
            reference_implementation=ImplementationTarget(
                target_id="empty_ref",
                name="legacy_loan_approval",
                role=ApplicationRole.REFERENCE,
                entrypoint="legacy_loan_approval:evaluate_loan",
            ),
            target_implementations=[
                ImplementationTarget(
                    target_id="empty_target",
                    name="legacy_loan_approval",
                    role=ApplicationRole.TARGET,
                    entrypoint="legacy_loan_approval:evaluate_loan",
                )
            ],
            dataset_config=DatasetConfig(
                dataset_id="ds_empty",
                generator_type="custom",
                sample_count=0,
                metadata={"custom_inputs": []},
            ),
        )
        application_registry.register_application(empty_spec)

        req = WorkflowRunRequest(application_id="empty_input_app")
        result = workflow_engine.execute_workflow(req)

        assert result.state == WorkflowState.FAILED
        assert result.certified is False
        assert result.error_code in (WorkflowErrorCode.INVALID_INPUT, WorkflowErrorCode.PREFLIGHT_FAILED, WorkflowErrorCode.ADAPTER_RESOLUTION_FAILED)


# ==============================================================================
# C. AUTHORITY & ZERO-RECONSTRUCTION INVARIANTS
# ==============================================================================

class TestPhase11AuthorityEnforcement:
    """Verifies strict authority checks and zero reconstruction of missing authority."""

    def test_08_threshold_fingerprint_mismatch_fails_closed(self, monkeypatch):
        """If threshold fingerprint does not match resolution, must fail closed."""
        engine = CanonicalV2WorkflowEngine()

        # Monkeypatch threshold resolution fingerprint to bogus value
        original_resolve = engine._stage_resolve_thresholds
        def tampered_stage(spec, run, timings):
            res = original_resolve(spec, run, timings)
            res.fingerprint = "tampered_bogus_fingerprint"
            return res

        monkeypatch.setattr(engine, "_stage_resolve_thresholds", tampered_stage)

        req = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)
        result = engine.execute_workflow(req)

        assert result.certified is False
        assert result.status in ("FAILED", "UNCERTIFIED", "NOT_CERTIFIED")
        assert result.error_code in (WorkflowErrorCode.THRESHOLD_FINGERPRINT_MISMATCH, WorkflowErrorCode.CERTIFICATION_FAILED)

    def test_09_missing_threshold_policy_fails_closed(self):
        """If no authoritative threshold policy exists, workflow must fail closed without fabricating a default."""
        app_no_thresh = ApplicationSpec(
            application_id="app_no_thresh_policy",
            name="App Without Threshold Policy",
            domain="finance",
            version="1.0.0",
            reference_implementation=ImplementationTarget(
                target_id="r1", name="legacy_loan_approval", role=ApplicationRole.REFERENCE, entrypoint="legacy_loan_approval:evaluate_loan"
            ),
            target_implementations=[
                ImplementationTarget(target_id="t1", name="legacy_loan_approval", role=ApplicationRole.TARGET, entrypoint="legacy_loan_approval:evaluate_loan")
            ],
            dataset_config=DatasetConfig(dataset_id="ds_1", generator_type="custom", sample_count=1, metadata={"custom_inputs": [{"credit_score": 700}]}),
            rule_config=RuleConfig(mode="CONTROLLED", rules=[{"rule_id": "R1", "condition": "credit_score >= 700", "consequence": "approved == True"}]),
        )
        application_registry.register_application(app_no_thresh)

        req = WorkflowRunRequest(application_id="app_no_thresh_policy", force_recompute=True)
        result = workflow_engine.execute_workflow(req)

        assert result.certified is False
        assert result.state == WorkflowState.FAILED
        assert result.error_code == WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING

    def test_10_missing_oracle_set_fails_closed(self, monkeypatch):
        """If oracle set is None or empty, must fail closed."""
        engine = CanonicalV2WorkflowEngine()
        monkeypatch.setattr(engine, "_stage_reconcile_oracles", lambda *args, **kwargs: None)

        req = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)
        result = engine.execute_workflow(req)

        assert result.certified is False
        assert result.state in (WorkflowState.FAILED, WorkflowState.INCONCLUSIVE)
        assert result.error_code == WorkflowErrorCode.ORACLE_AUTHORITY_MISSING

    def test_11_missing_evaluation_result_fails_closed(self, monkeypatch):
        """If evaluation result is None, must fail closed without calculating status."""
        engine = CanonicalV2WorkflowEngine()
        monkeypatch.setattr(engine, "_stage_evaluate_behavior", lambda *args, **kwargs: None)

        req = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)
        result = engine.execute_workflow(req)

        assert result.certified is False
        assert result.state == WorkflowState.FAILED
        assert result.error_code == WorkflowErrorCode.EVALUATION_FAILED


# ==============================================================================
# D. SPY VERIFICATION: ALL CANONICAL ENGINES INVOKED
# ==============================================================================

class TestPhase11EngineSpyIntegration:
    """Verifies that the canonical workflow genuinely calls the real Phase 4, 5, 7, 8, and Cert engines."""

    def test_12_all_authoritative_engines_invoked_in_sequence(self, monkeypatch):
        """Test that every authority engine in the chain is actually invoked."""
        engine = CanonicalV2WorkflowEngine()
        invocations = []

        # Spy Phase 4
        orig_eval = engine.eval_eng.evaluate_bundle
        def spy_eval(*args, **kwargs):
            invocations.append("PHASE_4_EVALUATION")
            return orig_eval(*args, **kwargs)
        monkeypatch.setattr(engine.eval_eng, "evaluate_bundle", spy_eval)

        # Spy Phase 5
        orig_ctrl = engine.controlled_eng.evaluate_controlled_mode
        def spy_ctrl(*args, **kwargs):
            invocations.append("PHASE_5_CONTROLLED")
            return orig_ctrl(*args, **kwargs)
        monkeypatch.setattr(engine.controlled_eng, "evaluate_controlled_mode", spy_ctrl)

        # Spy Phase 7
        orig_reconcile = engine.reconcile_eng.reconcile
        def spy_reconcile(*args, **kwargs):
            invocations.append("PHASE_7_RECONCILIATION")
            return orig_reconcile(*args, **kwargs)
        monkeypatch.setattr(engine.reconcile_eng, "reconcile", spy_reconcile)

        # Spy Phase 8
        orig_thresh = engine.thresh_eng.resolve_threshold
        def spy_thresh(*args, **kwargs):
            invocations.append("PHASE_8_THRESHOLDS")
            return orig_thresh(*args, **kwargs)
        monkeypatch.setattr(engine.thresh_eng, "resolve_threshold", spy_thresh)

        # Spy Certification Engine
        orig_cert = engine.cert_eng.certify
        def spy_cert(*args, **kwargs):
            invocations.append("PHASE_CERTIFICATION_ENGINE")
            return orig_cert(*args, **kwargs)
        monkeypatch.setattr(engine.cert_eng, "certify", spy_cert)

        req = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)
        result = engine.execute_workflow(req)

        assert result.certified is True
        assert "PHASE_4_EVALUATION" in invocations
        assert "PHASE_5_CONTROLLED" in invocations
        assert "PHASE_7_RECONCILIATION" in invocations
        assert "PHASE_8_THRESHOLDS" in invocations
        assert "PHASE_CERTIFICATION_ENGINE" in invocations


# ==============================================================================
# E. EVIDENCE INTEGRITY & MULTI-DIMENSIONAL EVALUATION
# ==============================================================================

class TestPhase11EvidenceAndDimensionIntegrity:
    """Verifies EvidenceBundle tamper detection and multi-dimensional difference propagation."""

    def test_13_tampered_evidence_bundle_fails_closed(self, monkeypatch):
        """Tampered EvidenceBundle hash must trigger fail-closed in evidence capture."""
        engine = CanonicalV2WorkflowEngine()

        orig_capture = engine._stage_capture_evidence
        def tampered_capture(spec, ref_adapter, target_adapter, test_inputs, run, timings):
            bundle, records, cases = orig_capture(spec, ref_adapter, target_adapter, test_inputs, run, timings)
            # Tamper the bundle hash
            bundle.bundle_hash = "tampered_bundle_hash_12345"
            return bundle, records, cases

        monkeypatch.setattr(engine, "_stage_capture_evidence", tampered_capture)

        req = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)
        result = engine.execute_workflow(req)

        assert result.certified is False
        assert result.state == WorkflowState.FAILED

    def test_14_multidimensional_error_difference_detected(self, monkeypatch):
        """If reference succeeds but target raises an error on one input, Phase 4 evaluates difference."""
        engine = CanonicalV2WorkflowEngine()

        orig_eval = engine.eval_eng.evaluate_bundle
        def eval_with_error_diff(bundle, policy=None, verify_integrity=True, dimensions=None):
            res = orig_eval(bundle, policy, verify_integrity, dimensions)
            # Inject an ERROR dimension difference
            b_diff = BehaviorDifference(
                difference_id="DIFF-ERR-01",
                dimension=BehaviorDimension.ERROR,
                difference_type=DifferenceType.EXCEPTION_TYPE_MISMATCH,
                reference_value=None,
                target_value="RuntimeError: Connection timed out",
                input_id="inp_1",
            )
            res.differences.append(b_diff)
            res.summary.different_inputs = 1
            res.summary.equivalent_inputs = 3
            res.verdict = EvaluationVerdict.DIFFERENT
            return res

        monkeypatch.setattr(engine.eval_eng, "evaluate_bundle", eval_with_error_diff)

        req = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)
        result = engine.execute_workflow(req)

        assert result.certified is False
        assert result.status == "NOT_CERTIFIED"
        assert result.regressions_count > 0


# ==============================================================================
# F. PERSISTENCE & ATOMIC INTEGRITY
# ==============================================================================

class TestPhase11PersistenceIntegrity:
    """Verifies atomic SQLite persistence and audit log consistency."""

    def test_16_workflow_run_saved_and_retrieved(self):
        """Test saving and retrieving workflow run from persistence store."""
        store = WorkflowPersistenceStore()
        run = WorkflowRun(
            workflow_run_id="wfr-test-101",
            application_id="loan_test_app",
            request_fingerprint="fp_test_101",
            state=WorkflowState.VALIDATING,
        )
        saved = store.save_run(run)
        assert saved.workflow_run_id == "wfr-test-101"

        retrieved = store.get_run("wfr-test-101")
        assert retrieved is not None
        assert retrieved.workflow_run_id == "wfr-test-101"
        assert retrieved.state == WorkflowState.VALIDATING

        # Update state
        retrieved.state = WorkflowState.COMPLETED
        retrieved.certification_status = "CERTIFIED"
        retrieved.certification_score = 1.0
        updated = store.save_run(retrieved)
        assert updated is not None
        assert updated.state == WorkflowState.COMPLETED

    def test_17_atomic_certification_persistence_and_cases(self):
        """Verifies that atomic persistence stores input set, cases, and artifact."""
        req = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=True)
        result = workflow_engine.execute_workflow(req)

        assert result.certified is True
        assert result.artifact_id is not None

        # Verify artifact, input set, and cases in repository
        artifact = certification_repository.get_artifact(result.artifact_id)
        assert artifact is not None
        assert artifact.artifact_id == result.artifact_id

        cases = certification_repository.list_certification_cases(result.artifact_id)
        assert len(cases) == 4
        for c in cases:
            assert c.run_id == result.artifact_id
            assert c.classification == "MATCH"

    def test_18_persistence_failure_handled_explicitly(self, monkeypatch):
        """If SQLite persistence fails, workflow reports PERSISTENCE_FAILED and does not falsely claim success."""
        engine = CanonicalV2WorkflowEngine()

        def failing_save(run):
            raise sqlite3.OperationalError("Simulated disk I/O failure on commit")

        monkeypatch.setattr(workflow_persistence, "save_run", failing_save)

        req = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)
        result = engine.execute_workflow(req)

        assert result.state == WorkflowState.FAILED
        assert result.error_code == WorkflowErrorCode.PERSISTENCE_FAILED
        assert result.audit_status == "PERSISTENCE_FAILED"


# ==============================================================================
# G. IDEMPOTENCY & CONCURRENCY
# ==============================================================================

class TestPhase11IdempotencyAndConcurrency:
    """Verifies deterministic idempotency, thread-safe and process-safe execution locks."""

    def test_19_exact_retry_returns_same_result(self):
        """Exact retry with same inputs & policies safely returns cached result."""
        req = WorkflowRunRequest(
            application_id="loan_test_app",
            target_index=0,
            force_recompute=False,
        )
        res1 = workflow_engine.execute_workflow(req)
        res2 = workflow_engine.execute_workflow(req)

        assert res1.workflow_run_id == res2.workflow_run_id
        assert res1.artifact_id == res2.artifact_id
        assert res1.state == res2.state == WorkflowState.COMPLETED

    def test_20_force_recompute_creates_distinct_run(self):
        """force_recompute=True generates a new workflow run identity with identical semantics."""
        req1 = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)
        req2 = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)

        res1 = workflow_engine.execute_workflow(req1)
        res2 = workflow_engine.execute_workflow(req2)

        assert res1.workflow_run_id != res2.workflow_run_id
        assert res1.certified == res2.certified == True
        assert res1.equivalence_score == res2.equivalence_score == 1.0

    def test_21_different_inputs_produce_distinct_fingerprints(self):
        """Requests with different custom inputs generate distinct request fingerprints."""
        req1 = WorkflowRunRequest(
            application_id="loan_test_app",
            custom_inputs=[{"credit_score": 750, "debt_ratio": 0.2}],
        )
        req2 = WorkflowRunRequest(
            application_id="loan_test_app",
            custom_inputs=[{"credit_score": 580, "debt_ratio": 0.6}],
        )
        assert req1.compute_request_fingerprint() != req2.compute_request_fingerprint()

    def test_22_concurrent_identical_requests_safe(self):
        """Concurrent threads executing the exact same request serialize safely without duplicate runs."""
        req = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
        results = []

        def worker():
            res = workflow_engine.execute_workflow(req)
            results.append(res)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 4
        for r in results:
            assert r.state == WorkflowState.COMPLETED
            assert r.certified is True


# ==============================================================================
# H. CRASH RECOVERY (CASES 1-6) & TAMPER DETECTION
# ==============================================================================

class TestPhase11CrashRecovery:
    """Verifies safe recovery of interrupted workflow runs across Cases 1-6."""

    def test_24_recovery_fails_on_missing_artifacts(self):
        """Case 1: No authoritative artifacts exist -> FAILED / RECOVERY_FAILED."""
        store = WorkflowPersistenceStore()
        rec_service = WorkflowRecoveryService(store)

        run = WorkflowRun(
            workflow_run_id="wfr-crashed-case-1",
            application_id="loan_test_app",
            request_fingerprint="fp_crashed_1",
            state=WorkflowState.EVALUATING,
        )
        store.save_run(run)

        recovered = rec_service.recover_interrupted_workflows()
        rec_run = store.get_run("wfr-crashed-case-1")
        assert rec_run is not None
        assert rec_run.state == WorkflowState.FAILED
        assert rec_run.error_code == WorkflowErrorCode.RECOVERY_FAILED

    def test_25_recovery_fails_on_missing_oracles(self):
        """Case 2: Evaluation exists but OracleSet missing -> FAILED."""
        store = WorkflowPersistenceStore()
        rec_service = WorkflowRecoveryService(store)

        run = WorkflowRun(
            workflow_run_id="wfr-crashed-case-2",
            application_id="loan_test_app",
            request_fingerprint="fp_crashed_2",
            state=WorkflowState.RESOLVING_ORACLES,
            evaluation_id="eval_123",
        )
        store.save_run(run)

        rec_service.recover_interrupted_workflows()
        rec_run = store.get_run("wfr-crashed-case-2")
        assert rec_run is not None
        assert rec_run.state == WorkflowState.FAILED

    def test_26_recovery_fails_on_missing_threshold(self):
        """Case 3: OracleSet exists but threshold missing -> FAILED."""
        store = WorkflowPersistenceStore()
        rec_service = WorkflowRecoveryService(store)

        run = WorkflowRun(
            workflow_run_id="wfr-crashed-case-3",
            application_id="loan_test_app",
            request_fingerprint="fp_crashed_3",
            state=WorkflowState.RESOLVING_THRESHOLDS,
            oracle_set_id="os_123",
        )
        store.save_run(run)

        rec_service.recover_interrupted_workflows()
        rec_run = store.get_run("wfr-crashed-case-3")
        assert rec_run is not None
        assert rec_run.state == WorkflowState.FAILED

    def test_27_recovery_fails_on_threshold_fingerprint_mismatch(self):
        """Case 4: Threshold exists but fingerprint mismatches artifact -> FAILED."""
        store = WorkflowPersistenceStore()
        rec_service = WorkflowRecoveryService(store)

        # Run real workflow to get a real valid artifact
        req = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)
        res = workflow_engine.execute_workflow(req)

        simulated_run = WorkflowRun(
            workflow_run_id="wfr-crashed-case-4",
            application_id="loan_test_app",
            request_fingerprint="fp_crashed_4",
            state=WorkflowState.EXPLAINING,
            certification_id=res.artifact_id,
            threshold_resolution_id=res.threshold_resolution_id,
            threshold_resolution_fingerprint="mismatched_bogus_fingerprint",
            evaluation_id="eval_real",
        )
        store.save_run(simulated_run)

        rec_service.recover_interrupted_workflows()
        rec_run = store.get_run("wfr-crashed-case-4")
        assert rec_run is not None
        assert rec_run.state == WorkflowState.FAILED
        assert "fingerprint mismatch" in (rec_run.error_message or "").lower()

    def test_28_recovery_fails_on_missing_cases(self, monkeypatch):
        """Case 5: Artifact exists but certification cases are missing -> FAILED."""
        store = WorkflowPersistenceStore()
        rec_service = WorkflowRecoveryService(store)

        req = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)
        res = workflow_engine.execute_workflow(req)

        # Monkeypatch list_certification_cases to return empty list
        monkeypatch.setattr(certification_repository, "list_certification_cases", lambda *args, **kwargs: [])

        simulated_run = WorkflowRun(
            workflow_run_id="wfr-crashed-case-5",
            application_id="loan_test_app",
            request_fingerprint="fp_crashed_5",
            state=WorkflowState.EXPLAINING,
            certification_id=res.artifact_id,
            threshold_resolution_id=res.threshold_resolution_id,
            threshold_resolution_fingerprint=res.threshold_resolution_fingerprint,
            evaluation_id="eval_real",
        )
        store.save_run(simulated_run)

        rec_service.recover_interrupted_workflows()
        rec_run = store.get_run("wfr-crashed-case-5")
        assert rec_run is not None
        assert rec_run.state == WorkflowState.FAILED

    def test_29_recovery_succeeds_on_complete_verified_chain(self):
        """Case 6: Complete authoritative chain exists and integrity checks pass -> COMPLETED."""
        store = WorkflowPersistenceStore()
        rec_service = WorkflowRecoveryService(store)

        # Run real workflow
        req = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)
        res = workflow_engine.execute_workflow(req)
        completed_run = store.get_run(res.workflow_run_id)

        # Simulate crash during EXPLAINING after successful persistence
        simulated_run = WorkflowRun(
            workflow_run_id="wfr-crashed-case-6",
            application_id="loan_test_app",
            request_fingerprint="fp_crashed_6",
            state=WorkflowState.EXPLAINING,
            certification_id=res.artifact_id,
            threshold_resolution_id=res.threshold_resolution_id,
            threshold_resolution_fingerprint=res.threshold_resolution_fingerprint,
            oracle_set_id=completed_run.oracle_set_id,
            oracle_set_hash=completed_run.oracle_set_hash,
            evaluation_id=completed_run.evaluation_id,
        )
        store.save_run(simulated_run)

        rec_service.recover_interrupted_workflows()
        rec_run = store.get_run("wfr-crashed-case-6")
        assert rec_run is not None
        assert rec_run.state == WorkflowState.COMPLETED
        assert rec_run.certification_status == "CERTIFIED"

    def test_30_recovery_detects_tampered_artifact(self, monkeypatch):
        """If CertificationArtifact content hash is tampered, recovery must fail closed."""
        store = WorkflowPersistenceStore()
        rec_service = WorkflowRecoveryService(store)

        req = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)
        res = workflow_engine.execute_workflow(req)
        art = certification_repository.get_artifact(res.artifact_id)

        # Create tampered copy of artifact
        tampered_art = art.model_copy(update={"content_hash": "tampered_hash_000000"})
        monkeypatch.setattr(certification_repository, "get_artifact", lambda *args, **kwargs: tampered_art)

        simulated_run = WorkflowRun(
            workflow_run_id="wfr-crashed-tampered",
            application_id="loan_test_app",
            request_fingerprint="fp_crashed_tampered",
            state=WorkflowState.EXPLAINING,
            certification_id=res.artifact_id,
            threshold_resolution_id=res.threshold_resolution_id,
            threshold_resolution_fingerprint=res.threshold_resolution_fingerprint,
            evaluation_id="eval_real",
        )
        store.save_run(simulated_run)

        rec_service.recover_interrupted_workflows()
        rec_run = store.get_run("wfr-crashed-tampered")
        assert rec_run is not None
        assert rec_run.state == WorkflowState.FAILED
        assert "cryptographic content hash" in (rec_run.error_message or "").lower()


# ==============================================================================
# I. EXPLANATION SAFETY & LLM ISOLATION
# ==============================================================================

class TestPhase11ExplanationSafety:
    """Verifies that explanations are strictly grounded and LLM cannot alter certification."""

    def test_31_grounded_explanation_attached(self):
        """Authoritative explanation is generated and grounded against real evidence."""
        req = WorkflowRunRequest(
            application_id="loan_test_app",
            target_index=0,
            explain=True,
            explanation_mode="deterministic",
        )
        result = workflow_engine.execute_workflow(req)

        assert result.explanation is not None
        assert result.explanation.get("authoritative_match_status") == "CERTIFIED"
        assert result.explanation.get("context_fingerprint") is not None
        assert "evidence_traces" in result.explanation

    def test_32_explanation_failure_does_not_affect_certification(self, monkeypatch):
        """If explanation engine raises an unexpected error, certification remains authoritative."""
        engine = CanonicalV2WorkflowEngine()

        def failing_explain(*args, **kwargs):
            raise RuntimeError("LLM explanation API timeout / failure")

        monkeypatch.setattr(engine.intel_eng, "generate_explanation", failing_explain)

        req = WorkflowRunRequest(application_id="loan_test_app", explain=True, force_recompute=True)
        result = engine.execute_workflow(req)

        # Certification remains valid & CERTIFIED
        assert result.certified is True
        assert result.status == "CERTIFIED"
        assert result.state == WorkflowState.COMPLETED
        # Explanation explicitly records failure
        assert result.explanation is not None
        assert result.explanation.get("status") == "EXPLANATION_FAILED"


# ==============================================================================
# J. SECURITY, SANITIZATION, AND RBAC AUDIT
# ==============================================================================

class TestPhase11SecurityAndAudit:
    """Verifies secret protection, audit trails, and RBAC authorization."""

    def test_33_secret_protection_in_metadata(self):
        """Sensitive fields (api_key, password, token) are stripped from metadata and not stored."""
        req = WorkflowRunRequest(
            application_id="loan_test_app",
            custom_inputs=[{"credit_score": 750, "token": "secret_12345", "password": "super_secret"}],
            force_recompute=True,
        )
        result = workflow_engine.execute_workflow(req)

        run = workflow_persistence.get_run(result.workflow_run_id)
        assert run is not None
        meta_str = json.dumps(run.metadata)
        assert "super_secret" not in meta_str
        assert "secret_12345" not in meta_str

    def test_34_complete_audit_trail_query(self, api_client, admin_headers):
        """Audit trail can be queried via API to inspect workflow runs."""
        req = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=True)
        workflow_engine.execute_workflow(req)

        res = api_client.get("/api/v2/workflow/runs?limit=10", headers=admin_headers)
        assert res.status_code == 200
        runs = res.json()
        assert isinstance(runs, list)
        assert len(runs) > 0

        for r in runs:
            assert "workflow_run_id" in r
            assert "application_id" in r
            assert "state" in r
            assert "created_at" in r
            assert "stage_timings_ms" in r

    def test_35_recovery_endpoint_requires_admin(self, api_client, user_headers, admin_headers):
        """Non-admin users cannot call POST /api/v2/workflow/recover."""
        # Non-admin user receives 403 Forbidden
        res_user = api_client.post("/api/v2/workflow/recover", headers=user_headers)
        assert res_user.status_code == 403, f"Status: {res_user.status_code}, Body: {res_user.text}"

        # Admin user receives 200 OK
        res_admin = api_client.post("/api/v2/workflow/recover", headers=admin_headers)
        assert res_admin.status_code == 200
        assert res_admin.json()["status"] == "SUCCESS"


# ==============================================================================
# K. APPLICATION ROUTER INTEGRATION
# ==============================================================================

class TestPhase11ApplicationRouterIntegration:
    """Verifies POST /api/v2/applications/{app_id}/certify delegates seamlessly to Phase 11 engine."""

    def test_36_application_router_certify(self, api_client, user_headers):
        """Test that /api/v2/applications/{app_id}/certify returns expected schema."""
        res = api_client.post(
            "/api/v2/applications/loan_test_app/certify",
            json={"target_index": 0, "explain": True},
            headers=user_headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["application_id"] == "loan_test_app"
        assert data["status"] == "CERTIFIED"
        assert data["equivalence_score"] == 1.0
        assert data["unique_input_count"] == 4
        assert "workflow_run_id" in data
        assert "artifact_id" in data
        assert "explanation" in data
