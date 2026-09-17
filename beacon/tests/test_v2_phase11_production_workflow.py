"""
BEACON V2 — Phase 11 Production Readiness & End-to-End Workflow Test Suite

Comprehensive test suite verifying:
- Canonical V2 Workflow Engine execution across Phase 1-11
- Stable workflow run identity & request fingerprinting
- Exact Phase 8 ThresholdResolution authority enforcement
- Deterministic idempotency & concurrency locking
- Transactional persistence in SQLite WAL & audit trail
- Fail-closed crash recovery without lossy reconstruction
- REST API (/api/v2/workflow/certify) & CLI contracts
- Grounded explanation integration & LLM authority isolation
- Security, log sanitization, and secret protection
"""

import copy
import hashlib
import json
import logging
import sqlite3
import threading
import time
from typing import Any
import pytest
from fastapi.testclient import TestClient

from api.main import app
from auth.models import User, UserRole, ProjectMembership
from auth.security import create_access_token
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
from certification.models import CertificationStatus, CertificationArtifact
from certification.certification_engine import certification_engine
from certification.repository import certification_repository
from threshold.engine import ThresholdEngine
from threshold.models import ThresholdResolution, DifferenceMetric, ThresholdPolicy, ThresholdStrategy
from threshold.persistence import threshold_persistence
from oracle.models import OracleSet
from oracle.registry import registry as oracle_registry
from evaluation.models import EvaluationResult, BehaviorDifference


# --- TEST FIXTURES ---

@pytest.fixture(scope="module")
def api_client():
    """TestClient for FastAPI app with auth token."""
    client = TestClient(app)
    return client


@pytest.fixture(scope="module")
def admin_headers():
    user = User(user_id="admin_user", username="admin_user", email="admin@beacon.local", password_hash="mock_hash", is_system_admin=True)
    token = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def user_headers():
    user = User(user_id="dev_user", username="dev_user", email="dev@beacon.local", password_hash="mock_hash", is_system_admin=False)
    memberships = [ProjectMembership(membership_id="m1", user_id="dev_user", project_id="loan_test_app", role=UserRole.PROJECT_ADMIN)]
    token = create_access_token(user, memberships=memberships)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def setup_test_environment(tmp_path):
    """Ensure clean test data environment."""
    # Ensure sample application is registered
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
# B. INPUT VALIDATION & FAIL-CLOSED PREFLIGHT TESTS
# ==============================================================================

class TestPhase11InputValidation:
    """Verifies that invalid or missing inputs fail closed immediately."""

    def test_05_unknown_application_fails_closed(self):
        """Test workflow request with nonexistent application fails closed with APPLICATION_NOT_FOUND."""
        req = WorkflowRunRequest(
            application_id="nonexistent_app_999",
            target_index=0,
        )
        result = workflow_engine.execute_workflow(req)

        assert result.state == WorkflowState.FAILED
        assert result.certified is False
        assert result.error_code == WorkflowErrorCode.APPLICATION_NOT_FOUND
        assert "not found" in (result.error_message or "").lower()

    def test_06_invalid_target_index_fails_closed(self):
        """Test invalid target index fails closed with ADAPTER_RESOLUTION_FAILED."""
        req = WorkflowRunRequest(
            application_id="loan_test_app",
            target_index=99,  # out of bounds
        )
        result = workflow_engine.execute_workflow(req)

        assert result.state == WorkflowState.FAILED
        assert result.certified is False
        assert result.error_code in (WorkflowErrorCode.ADAPTER_RESOLUTION_FAILED, WorkflowErrorCode.INVALID_INPUT)

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

    def test_09_missing_threshold_resolution_fails_closed(self, monkeypatch):
        """If threshold resolution is None, must fail closed without calculating status."""
        engine = CanonicalV2WorkflowEngine()
        monkeypatch.setattr(engine, "_stage_resolve_thresholds", lambda *args, **kwargs: None)

        req = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)
        result = engine.execute_workflow(req)

        assert result.certified is False
        assert result.state in (WorkflowState.FAILED, WorkflowState.INCONCLUSIVE)
        assert result.error_code == WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING

    def test_10_missing_oracle_set_fails_closed(self, monkeypatch):
        """If OracleSet resolution fails, must fail closed."""
        engine = CanonicalV2WorkflowEngine()
        monkeypatch.setattr(engine, "_stage_resolve_oracles", lambda *args, **kwargs: None)

        req = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)
        result = engine.execute_workflow(req)

        assert result.certified is False
        assert result.state == WorkflowState.FAILED
        assert result.error_code == WorkflowErrorCode.ORACLE_AUTHORITY_MISSING

    def test_11_missing_evaluation_result_fails_closed(self, monkeypatch):
        """If EvaluationResult is missing, workflow fails closed without defaults."""
        engine = CanonicalV2WorkflowEngine()
        monkeypatch.setattr(engine, "_stage_evaluate_behavior", lambda *args, **kwargs: None)

        req = WorkflowRunRequest(application_id="loan_test_app", force_recompute=True)
        result = engine.execute_workflow(req)

        assert result.certified is False
        assert result.state == WorkflowState.FAILED
        assert result.error_code == WorkflowErrorCode.EVALUATION_FAILED


# ==============================================================================
# D. PERSISTENCE INTEGRITY & TRANSACTIONAL ROBUSTNESS
# ==============================================================================

class TestPhase11PersistenceIntegrity:
    """Verifies SQLite WAL persistence, error recovery, and audit completeness."""

    def test_12_workflow_run_saved_and_retrieved(self):
        """Test creating, updating, and querying WorkflowRun in persistence store."""
        store = WorkflowPersistenceStore()
        run = WorkflowRun(
            workflow_run_id="wfr-test-12345",
            application_id="loan_test_app",
            request_fingerprint="fingerprint_abc",
            state=WorkflowState.VALIDATING,
        )
        store.save_run(run)

        fetched = store.get_run("wfr-test-12345")
        assert fetched is not None
        assert fetched.workflow_run_id == "wfr-test-12345"
        assert fetched.state == WorkflowState.VALIDATING

        # Update state
        run.state = WorkflowState.COMPLETED
        run.certification_status = "CERTIFIED"
        run.certification_score = 1.0
        store.save_run(run)

        updated = store.get_run("wfr-test-12345")
        assert updated is not None
        assert updated.state == WorkflowState.COMPLETED
        assert updated.certification_status == "CERTIFIED"
        assert updated.certification_score == 1.0

    def test_13_persistence_failure_handled_explicitly(self, monkeypatch):
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
# E. IDEMPOTENCY & CONCURRENCY
# ==============================================================================

class TestPhase11IdempotencyAndConcurrency:
    """Verifies deterministic idempotency and thread-safe execution locks."""

    def test_14_exact_retry_returns_same_result(self):
        """Case B: Exact retry with same inputs & policies safely returns cached result."""
        req = WorkflowRunRequest(
            application_id="loan_test_app",
            target_index=0,
            policy_min_equivalence_score=0.99,
        )
        res1 = workflow_engine.execute_workflow(req)
        res2 = workflow_engine.execute_workflow(req)

        assert res1.workflow_run_id == res2.workflow_run_id
        assert res1.artifact_id == res2.artifact_id
        assert res1.certified == res2.certified
        assert res1.status == res2.status

    def test_15_force_recompute_creates_distinct_run(self):
        """Case E: Force recompute creates a new authoritative run."""
        req1 = WorkflowRunRequest(application_id="loan_test_app", target_index=0)
        res1 = workflow_engine.execute_workflow(req1)

        req2 = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=True)
        res2 = workflow_engine.execute_workflow(req2)

        assert res1.workflow_run_id != res2.workflow_run_id
        assert res2.certified is True

    def test_16_different_inputs_produce_distinct_fingerprints(self):
        """Different custom inputs do not incorrectly collide in cache."""
        req1 = WorkflowRunRequest(
            application_id="loan_test_app",
            custom_inputs=[{"credit_score": 700, "debt_ratio": 0.3}],
        )
        req2 = WorkflowRunRequest(
            application_id="loan_test_app",
            custom_inputs=[{"credit_score": 500, "debt_ratio": 0.8}],
        )

        fp1 = req1.compute_request_fingerprint()
        fp2 = req2.compute_request_fingerprint()

        assert fp1 != fp2

    def test_17_concurrent_identical_requests_safe(self):
        """Concurrent requests with identical fingerprint run safely through per-fingerprint lock."""
        req = WorkflowRunRequest(
            application_id="loan_test_app",
            target_index=0,
            force_recompute=True,
        )

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
        # All returned valid completed results
        for r in results:
            assert r.state == WorkflowState.COMPLETED
            assert r.certified is True


# ==============================================================================
# F. RECOVERY & PROCESS RESTART SIMULATION
# ==============================================================================

class TestPhase11CrashRecovery:
    """Verifies safe recovery of interrupted workflow runs."""

    def test_18_recovery_service_marks_interrupted_runs_inconclusive(self):
        """Test recovering interrupted runs without lost state."""
        store = WorkflowPersistenceStore()
        rec_service = WorkflowRecoveryService(store)

        # Create an interrupted run in EVALUATING state
        interrupted_run = WorkflowRun(
            workflow_run_id="wfr-crashed-at-eval",
            application_id="loan_test_app",
            request_fingerprint="fp_crashed_1",
            state=WorkflowState.EVALUATING,
        )
        store.save_run(interrupted_run)

        # Trigger recovery
        recovered = rec_service.recover_interrupted_workflows()
        assert len(recovered) >= 1

        rec_run = store.get_run("wfr-crashed-at-eval")
        assert rec_run is not None
        assert rec_run.state in (WorkflowState.INCONCLUSIVE, WorkflowState.FAILED)
        assert rec_run.error_code == WorkflowErrorCode.RECOVERY_FAILED
        assert "interrupted" in (rec_run.error_message or "").lower()

    def test_19_recovery_with_persisted_artifact_completes_safely(self):
        """If certification artifact was already persisted before crash during explanation, recovery marks completed."""
        store = WorkflowPersistenceStore()
        rec_service = WorkflowRecoveryService(store)

        # First run a full workflow to get a real valid artifact
        req = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=True)
        res = workflow_engine.execute_workflow(req)

        # Simulate a crash right after certification during EXPLAINING
        simulated_run = WorkflowRun(
            workflow_run_id="wfr-crashed-during-explaining",
            application_id="loan_test_app",
            request_fingerprint="fp_crashed_during_explaining",
            state=WorkflowState.EXPLAINING,
            certification_id=res.artifact_id,
            threshold_resolution_id=res.threshold_resolution_id,
            threshold_resolution_fingerprint=res.threshold_resolution_fingerprint,
        )
        store.save_run(simulated_run)

        # Run recovery
        rec_service.recover_interrupted_workflows()

        rec_run = store.get_run("wfr-crashed-during-explaining")
        assert rec_run is not None
        assert rec_run.state == WorkflowState.COMPLETED
        assert rec_run.certification_status == "CERTIFIED"


# ==============================================================================
# G. EXPLANATION GROUNDING & LLM ISOLATION
# ==============================================================================

class TestPhase11ExplanationSafety:
    """Verifies that explanations are strictly grounded and LLM cannot alter certification."""

    def test_20_grounded_explanation_attached(self):
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

    def test_21_explanation_failure_does_not_affect_certification(self, monkeypatch):
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
# H. SECURITY, SANITIZATION, AND AUDIT
# ==============================================================================

class TestPhase11SecurityAndAudit:
    """Verifies secret protection, audit trails, and input sanitization."""

    def test_22_secret_protection_in_metadata(self):
        """Sensitive fields (api_key, password, token) are stripped from metadata and not stored."""
        req = WorkflowRunRequest(
            application_id="loan_test_app",
            custom_inputs=[{"credit_score": 750, "token": "secret_12345", "password": "super_secret"}],
            force_recompute=True,
        )
        result = workflow_engine.execute_workflow(req)

        run = workflow_persistence.get_run(result.workflow_run_id)
        assert run is not None
        # Check run metadata does not contain raw secrets
        meta_str = json.dumps(run.metadata)
        assert "super_secret" not in meta_str
        assert "secret_12345" not in meta_str

    def test_23_complete_audit_trail_query(self, api_client, admin_headers):
        """Audit trail can be queried via API to inspect workflow runs."""
        # Ensure at least one workflow run exists
        req = WorkflowRunRequest(application_id="loan_test_app", target_index=0, force_recompute=True)
        workflow_engine.execute_workflow(req)

        res = api_client.get("/api/v2/workflow/runs?limit=10", headers=admin_headers)
        assert res.status_code == 200
        runs = res.json()
        assert isinstance(runs, list)
        assert len(runs) > 0

        # Verify audit properties on each run
        for r in runs:
            assert "workflow_run_id" in r
            assert "application_id" in r
            assert "state" in r
            assert "created_at" in r
            assert "stage_timings_ms" in r


# ==============================================================================
# I. APPLICATION ROUTER BACKWARD COMPATIBILITY
# ==============================================================================

class TestPhase11ApplicationRouterIntegration:
    """Verifies POST /api/v2/applications/{app_id}/certify delegates seamlessly to Phase 11 engine."""

    def test_24_application_router_certify(self, api_client, user_headers):
        """Test that legacy /api/v2/applications/{app_id}/certify returns expected schema."""
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
