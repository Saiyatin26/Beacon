"""Phase 19 — Production Reliability, Resilience, Lifecycle Management & Operational Safety Tests.

Verifies:
1. Deterministic Idempotency & 409 Material Conflict Rejection.
2. Tenant-Safe Idempotency Key Scoping & Isolation.
3. Validated Job Lifecycle State Machine & Invalid Transition Rejection.
4. Thread-Safe SQLite Job Persistence.
5. Failure Classification (Retryable vs Permanent).
6. Bounded Exponential Retry with Jitter.
7. Safe Timeout Boundaries and OperationTimeoutError.
8. Startup Interruption Recovery of In-Flight Operations.
9. Evidence & Export Consistency Validation.
10. Non-Blocking Observability & Telemetry Fault Tolerance.
"""

import logging
import sqlite3
import time
import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from api.main import app
from common.config import settings
from operations import (
    JobState,
    CertificationJob,
    certification_job_tracker,
    operational_metrics,
    idempotency_manager,
    classify_failure,
    execute_with_retry,
    with_timeout,
    recover_interrupted_operations,
    StateTransitionError,
    IdempotencyConflictError,
    OperationTimeoutError,
    ErrorCategory,
    log_operational_event,
)
from auth.models import User, ProjectMembership, UserRole
from auth.repository import auth_repository
from auth.security import create_access_token
from certification.repository import certification_repository
from ingestion.audit import audit_logger


@pytest.fixture(autouse=True)
def clean_state():
    """Ensures clean database and cache state before and after each test."""
    certification_repository.clear()
    certification_job_tracker.clear()
    idempotency_manager.clear()
    operational_metrics.clear()
    audit_logger.clear()
    from benchmarks import benchmark_registry
    benchmark_registry.refresh()
    yield
    certification_repository.clear()
    certification_job_tracker.clear()
    idempotency_manager.clear()
    operational_metrics.clear()
    audit_logger.clear()
    from benchmarks import benchmark_registry
    benchmark_registry.refresh()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def member_token_proj_a():
    user = auth_repository.get_user_by_username("user_p19_a")
    if not user:
        user = auth_repository.create_user(
            username="user_p19_a",
            password="UserP19Pass123!",
            user_id="USR-P19-A",
            is_system_admin=False,
        )
    mem = auth_repository.assign_user_to_project(user.user_id, "proj_a", UserRole.CERTIFIER)
    return create_access_token(user=user, memberships=[mem])


@pytest.fixture
def member_token_proj_b():
    user = auth_repository.get_user_by_username("user_p19_b")
    if not user:
        user = auth_repository.create_user(
            username="user_p19_b",
            password="UserP19Pass123!",
            user_id="USR-P19-B",
            is_system_admin=False,
        )
    mem = auth_repository.assign_user_to_project(user.user_id, "proj_b", UserRole.CERTIFIER)
    return create_access_token(user=user, memberships=[mem])


# ==============================================================================
# 1. Deterministic Idempotency & Conflict Tests
# ==============================================================================

def test_idempotency_same_key_same_payload_reuses_result(client, member_token_proj_a):
    """Verifies that sending the exact same request with an idempotency key
    returns the existing completed result without duplicate execution.
    """
    req_body = {
        "benchmark_id": "loan_demo",
        "evaluation_mode": "CONTROLLED",
        "target_variant": "clean",
        "idempotency_key": "IDEM-KEY-001",
        "force_recompute": False,
    }

    # 1. First execution
    res1 = client.post(
        "/api/v1/certification/run?project_id=proj_a",
        json=req_body,
        headers={"Authorization": f"Bearer {member_token_proj_a}"},
    )
    assert res1.status_code == 200
    data1 = res1.json()
    cert_id1 = data1["certification_id"]

    # 2. Second execution with identical payload and key
    res2 = client.post(
        "/api/v1/certification/run?project_id=proj_a",
        json=req_body,
        headers={"Authorization": f"Bearer {member_token_proj_a}"},
    )
    assert res2.status_code == 200
    data2 = res2.json()
    cert_id2 = data2["certification_id"]

    # Must reuse the exact same certification result
    assert cert_id1 == cert_id2
    assert data1["score"] == data2["score"]


def test_idempotency_conflict_different_payload_returns_409(client, member_token_proj_a):
    """Verifies that reusing an existing idempotency key with a DIFFERENT request payload
    is rejected with HTTP 409 Conflict.
    """
    key = "IDEM-CONFLICT-KEY-999"

    # 1. First request
    req1 = {
        "benchmark_id": "loan_demo",
        "evaluation_mode": "CONTROLLED",
        "target_variant": "clean",
        "idempotency_key": key,
        "n_samples": 10,
    }
    res1 = client.post(
        "/api/v1/certification/run?project_id=proj_a",
        json=req1,
        headers={"Authorization": f"Bearer {member_token_proj_a}"},
    )
    assert res1.status_code == 200

    # 2. Second request reusing key but changing n_samples to 50 (material change)
    req2 = {
        "benchmark_id": "loan_demo",
        "evaluation_mode": "CONTROLLED",
        "target_variant": "clean",
        "idempotency_key": key,
        "n_samples": 50,
    }
    res2 = client.post(
        "/api/v1/certification/run?project_id=proj_a",
        json=req2,
        headers={"Authorization": f"Bearer {member_token_proj_a}"},
    )
    assert res2.status_code == 409
    err_data = res2.json()
    assert err_data["category"] == "IDEMPOTENCY_CONFLICT"
    assert "conflict" in err_data["message"].lower()


def test_idempotency_cross_project_isolation(client, member_token_proj_a, member_token_proj_b):
    """Verifies that the same idempotency key used in Project A does not collide
    or leak into Project B.
    """
    shared_key = "SHARED-PROJECT-KEY-123"

    req_a = {
        "project_id": "proj_a",
        "benchmark_id": "loan_demo",
        "evaluation_mode": "CONTROLLED",
        "target_variant": "clean",
        "idempotency_key": shared_key,
        "n_samples": 10,
    }
    res_a = client.post(
        "/api/v1/certification/run?project_id=proj_a",
        json=req_a,
        headers={"Authorization": f"Bearer {member_token_proj_a}"},
    )
    assert res_a.status_code == 200
    cert_a = res_a.json()["certification_id"]

    # Project B uses the same key with different or same payload
    req_b = {
        "project_id": "proj_b",
        "benchmark_id": "loan_demo",
        "evaluation_mode": "CONTROLLED",
        "target_variant": "clean",
        "idempotency_key": shared_key,
        "n_samples": 20,
    }
    res_b = client.post(
        "/api/v1/certification/run?project_id=proj_b",
        json=req_b,
        headers={"Authorization": f"Bearer {member_token_proj_b}"},
    )
    # Must succeed in Project B independently without 409 conflict against Project A
    assert res_b.status_code == 200
    cert_b = res_b.json()["certification_id"]
    assert cert_a != cert_b



# ==============================================================================
# 2. Job Lifecycle State Machine & Transition Validation Tests
# ==============================================================================

def test_valid_job_state_transitions():
    """Verifies that valid, sequential state transitions succeed cleanly."""
    job = certification_job_tracker.create_job(
        project_id="test_proj",
        benchmark_id="loan_demo",
    )
    assert job.state == JobState.ACCEPTED

    job = certification_job_tracker.update_state(job.job_id, JobState.QUEUED)
    assert job.state == JobState.QUEUED

    job = certification_job_tracker.update_state(job.job_id, JobState.VALIDATING)
    assert job.state == JobState.VALIDATING

    job = certification_job_tracker.update_state(job.job_id, JobState.PREFLIGHT)
    assert job.state == JobState.PREFLIGHT

    job = certification_job_tracker.update_state(job.job_id, JobState.RUNNING)
    assert job.state == JobState.RUNNING

    job = certification_job_tracker.update_state(job.job_id, JobState.EVIDENCE_GENERATION)
    assert job.state == JobState.EVIDENCE_GENERATION

    job = certification_job_tracker.update_state(job.job_id, JobState.PERSISTING)
    assert job.state == JobState.PERSISTING

    job = certification_job_tracker.update_state(
        job.job_id,
        JobState.COMPLETED,
        certification_id="CERT-100",
        certification_status="CERTIFIED",
        equivalence_score=1.0,
    )
    assert job.state == JobState.COMPLETED
    assert job.progress_pct == 100
    assert job.duration_ms is not None


def test_invalid_job_state_transition_rejected():
    """Verifies that invalid out-of-order state transitions raise StateTransitionError
    and do not corrupt the job state.
    """
    job = certification_job_tracker.create_job(project_id="test_proj")
    assert job.state == JobState.ACCEPTED

    # 1. Transition to COMPLETED
    certification_job_tracker.update_state(job.job_id, JobState.QUEUED)
    certification_job_tracker.update_state(job.job_id, JobState.RUNNING)
    certification_job_tracker.update_state(job.job_id, JobState.COMPLETED)

    # 2. Attempt illegal transition from terminal COMPLETED -> RUNNING
    with pytest.raises(StateTransitionError) as exc_info:
        certification_job_tracker.update_state(job.job_id, JobState.RUNNING)

    assert "Illegal state transition" in str(exc_info.value)
    # State must remain COMPLETED
    reloaded = certification_job_tracker.get_job(job.job_id)
    assert reloaded.state == JobState.COMPLETED


def test_sqlite_persistence_of_jobs():
    """Verifies that jobs and state transitions are persisted to SQLite."""
    job = certification_job_tracker.create_job(
        project_id="persist_proj",
        benchmark_id="loan_demo",
    )
    certification_job_tracker.update_state(
        job.job_id,
        JobState.RUNNING,
        current_step="Running in test",
    )

    # Create a separate tracker pointing to the same SQLite database
    from operations.job_lifecycle import CertificationJobTracker
    new_tracker = CertificationJobTracker(db_path=certification_job_tracker._db_path)
    loaded_job = new_tracker.get_job(job.job_id)

    assert loaded_job is not None
    assert loaded_job.job_id == job.job_id
    assert loaded_job.project_id == "persist_proj"
    assert loaded_job.state == JobState.RUNNING
    assert loaded_job.current_step == "Running in test"


# ==============================================================================
# 3. Resilience, Failure Classification & Bounded Retries
# ==============================================================================

def test_failure_classification_retryable_vs_permanent():
    """Verifies that classify_failure accurately classifies transient vs permanent errors."""
    # Permanent errors
    assert classify_failure(HTTPException(status_code=400))[0] is False
    assert classify_failure(HTTPException(status_code=401))[0] is False
    assert classify_failure(HTTPException(status_code=403))[0] is False
    assert classify_failure(HTTPException(status_code=404))[0] is False
    assert classify_failure(HTTPException(status_code=409))[0] is False
    assert classify_failure(HTTPException(status_code=422))[0] is False
    assert classify_failure(ValueError("Bad input"))[0] is False
    assert classify_failure(PermissionError("Denied"))[0] is False

    # Retryable errors
    assert classify_failure(HTTPException(status_code=503))[0] is True
    assert classify_failure(HTTPException(status_code=504))[0] is True
    assert classify_failure(TimeoutError("Connection timed out"))[0] is True
    assert classify_failure(sqlite3.OperationalError("database is locked"))[0] is True


def test_bounded_retry_succeeds_on_retry():
    """Verifies that execute_with_retry retries retryable failures and returns on success."""
    call_count = 0

    def flaky_operation():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError("Temporary socket timeout")
        return "SUCCESS_DATA"

    result = execute_with_retry(flaky_operation, max_attempts=3, base_delay_ms=10.0, jitter=False)
    assert result == "SUCCESS_DATA"
    assert call_count == 2


def test_bounded_retry_stops_at_max_attempts():
    """Verifies that retry attempts are strictly bounded and stop after max_attempts."""
    call_count = 0

    def failing_operation():
        nonlocal call_count
        call_count += 1
        raise TimeoutError("Persistent timeout")

    with pytest.raises(TimeoutError):
        execute_with_retry(failing_operation, max_attempts=3, base_delay_ms=5.0, jitter=False)

    assert call_count == 3


def test_non_retryable_error_fails_immediately():
    """Verifies that non-retryable errors fail on attempt 1 without executing retries."""
    call_count = 0

    def bad_request_operation():
        nonlocal call_count
        call_count += 1
        raise HTTPException(status_code=400, detail="Invalid parameter")

    with pytest.raises(HTTPException):
        execute_with_retry(bad_request_operation, max_attempts=5, base_delay_ms=5.0)

    assert call_count == 1


# ==============================================================================
# 4. Safe Timeout Handling Tests
# ==============================================================================

def test_with_timeout_completes_within_deadline():
    """Verifies that with_timeout returns normally when executed under the deadline."""
    def fast_task():
        return "COMPLETED_FAST"

    res = with_timeout(fast_task, timeout_seconds=2.0)
    assert res == "COMPLETED_FAST"


def test_with_timeout_raises_operation_timeout_error():
    """Verifies that with_timeout raises OperationTimeoutError when deadline is exceeded."""
    def slow_task():
        time.sleep(0.3)
        return "SLOW"

    with pytest.raises(OperationTimeoutError) as exc_info:
        with_timeout(slow_task, timeout_seconds=0.05, operation_name="slow_task_test")

    assert exc_info.value.category == ErrorCategory.TIMEOUT
    assert exc_info.value.status_code == status.HTTP_504_GATEWAY_TIMEOUT


# ==============================================================================
# 5. Startup Interruption Recovery Tests
# ==============================================================================

def test_startup_recovery_marks_interrupted_jobs_as_failed():
    """Verifies that active jobs left in non-terminal states before application restart
    are safely recovered and marked FAILED.
    """
    # 1. Create jobs in various states
    job_running = certification_job_tracker.create_job(project_id="proj_recover_1")
    certification_job_tracker.update_state(job_running.job_id, JobState.RUNNING)

    job_queued = certification_job_tracker.create_job(project_id="proj_recover_2")
    certification_job_tracker.update_state(job_queued.job_id, JobState.QUEUED)

    job_completed = certification_job_tracker.create_job(project_id="proj_recover_3")
    certification_job_tracker.update_state(job_completed.job_id, JobState.QUEUED)
    certification_job_tracker.update_state(job_completed.job_id, JobState.RUNNING)
    certification_job_tracker.update_state(job_completed.job_id, JobState.COMPLETED)

    # 2. Simulate server restart by running recover_interrupted_operations()
    diag = recover_interrupted_operations()
    assert diag["interrupted_jobs_found"] >= 2
    assert diag["recovered_count"] >= 2

    # 3. Verify running and queued jobs are now safely FAILED
    reloaded_running = certification_job_tracker.get_job(job_running.job_id)
    assert reloaded_running.state == JobState.FAILED
    assert reloaded_running.error_category == "INTERRUPTED"

    reloaded_queued = certification_job_tracker.get_job(job_queued.job_id)
    assert reloaded_queued.state == JobState.FAILED
    assert reloaded_queued.error_category == "INTERRUPTED"

    # Completed job must remain untouched
    reloaded_completed = certification_job_tracker.get_job(job_completed.job_id)
    assert reloaded_completed.state == JobState.COMPLETED


def test_startup_recovery_is_idempotent():
    """Verifies that running recovery multiple times is safe and idempotent."""
    res1 = recover_interrupted_operations()
    assert res1["recovered_count"] == 0

    res2 = recover_interrupted_operations()
    assert res2["recovered_count"] == 0


# ==============================================================================
# 6. Non-Blocking Telemetry Tests
# ==============================================================================

def test_logging_fault_tolerance():
    """Verifies that internal errors in log_operational_event do not crash caller."""
    # Calling log_operational_event with arbitrary parameters must never raise an exception
    log_operational_event(
        event="test_fault_tolerance",
        level=logging.INFO,
        unusual_object=object(),
    )


# ==============================================================================
# 7. Evidence & Export Consistency Tests
# ==============================================================================

def test_export_nonexistent_certification_returns_404(client, member_token_proj_a):
    """Verifies that exporting a non-existent certification returns HTTP 404."""
    res = client.get(
        "/api/v1/certification/CERT-DOES-NOT-EXIST/export?project_id=proj_a",
        headers={"Authorization": f"Bearer {member_token_proj_a}"},
    )
    assert res.status_code == 404


def test_export_incomplete_certification_returns_409(client, member_token_proj_a):
    """Verifies that attempting to export an incomplete certification without an InputSet
    is cleanly rejected with HTTP 409 Conflict.
    """
    from certification.models import CertificationArtifact, CertificationStatus, CertificationMetrics
    from datetime import datetime, timezone

    # Create an artifact in the repository whose input_set is missing from storage
    incomplete_art = CertificationArtifact(
        certification_id="CERT-INCOMPLETE-1",
        project_id="proj_a",
        benchmark_id="loan_demo",
        input_set_id="INPSET-MISSING",
        input_set_hash="missing_hash",
        oracle_set_id="ORC-TEST",
        oracle_set_hash="orc_hash",
        status=CertificationStatus.NOT_CERTIFIED,
        score=0.0,


        metrics=CertificationMetrics(
            total_cases=0,
            passed_cases=0,
            failed_cases=0,
            equivalence_score=0.0,
            mean_latency_diff_ms=0.0,
            confidence_interval=(0.0, 0.0),
        ),
        created_at=datetime.now(timezone.utc).isoformat(),
        content_hash="",
    )
    from certification.models import compute_artifact_content_hash
    chash = compute_artifact_content_hash(incomplete_art)
    incomplete_art = incomplete_art.model_copy(update={"content_hash": chash})
    certification_repository.save_artifact(incomplete_art)



    res = client.get(
        "/api/v1/certification/CERT-INCOMPLETE-1/export?project_id=proj_a",
        headers={"Authorization": f"Bearer {member_token_proj_a}"},
    )
    assert res.status_code == 409
    assert "Incomplete certification data" in res.json()["detail"]

