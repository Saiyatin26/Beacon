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
    IdempotencyManager,
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


# ==============================================================================
# 8. Phase 19 Master Regression Tests (Timeout, Retry, Concurrency, Duration)
# ==============================================================================

def test_with_timeout_does_not_block_caller_on_slow_worker():
    """Verifies that the caller returns near the configured deadline and does NOT block
    waiting for the slow worker thread to finish executing during executor shutdown.
    """
    import threading

    worker_finished = threading.Event()

    def slow_worker():
        time.sleep(0.6)
        worker_finished.set()
        return "FINISHED_LATE"

    start_mono = time.monotonic()
    with pytest.raises(OperationTimeoutError) as exc_info:
        # Configured timeout is 0.05s (50ms), slow worker takes 0.6s (600ms)
        with_timeout(slow_worker, timeout_seconds=0.05, operation_name="slow_worker_shutdown_test")

    caller_elapsed = time.monotonic() - start_mono
    # Caller should return within ~0.25s, well before the 0.6s slow worker finishes
    assert caller_elapsed < 0.35, f"Caller was blocked for {caller_elapsed:.3f}s (expected < 0.35s)"
    assert exc_info.value.category == ErrorCategory.TIMEOUT


def test_with_timeout_cooperative_cancellation():
    """Verifies that cooperative cancellation event is signaled when deadline is exceeded."""
    import threading

    cancel_event = threading.Event()

    def cancellable_task(evt):
        for _ in range(50):
            if evt.is_set():
                return "CANCELLED_EARLY"
            time.sleep(0.01)
        return "COMPLETED"

    with pytest.raises(OperationTimeoutError):
        with_timeout(
            cancellable_task,
            timeout_seconds=0.04,
            operation_name="cancellable_task_test",
            cancellation_event=cancel_event,
            evt=cancel_event,
        )

    assert cancel_event.is_set() is True


def test_timeout_stale_worker_cannot_write_success():
    """Verifies that a timed-out operation cannot later overwrite FAILED state to COMPLETED."""
    job = certification_job_tracker.create_job(project_id="proj_timeout_test")
    certification_job_tracker.update_state(job.job_id, JobState.RUNNING)

    # Simulate timeout handler transitioning the job to FAILED
    certification_job_tracker.update_state(
        job.job_id,
        JobState.FAILED,
        current_step="Execution timed out",
        error_category=ErrorCategory.TIMEOUT.value,
        error_message="Operation timed out after deadline",
    )

    # A delayed worker thread trying to commit COMPLETED must be strictly rejected
    with pytest.raises(StateTransitionError):
        certification_job_tracker.update_state(
            job.job_id,
            JobState.COMPLETED,
            current_step="Late worker completed",
        )

    # Persisted job state remains FAILED
    reloaded = certification_job_tracker.get_job(job.job_id)
    assert reloaded.state == JobState.FAILED
    assert reloaded.error_category == ErrorCategory.TIMEOUT.value


def test_concurrent_idempotency_same_key_single_execution(client, member_token_proj_a):
    """Verifies that two concurrent requests with the same idempotency key execute exactly
    one certification run, and do not execute duplicate background work.
    Asserts deterministically that execution_count == 1.
    """
    import concurrent.futures
    import threading
    from certification import certification_engine

    original_certify = certification_engine.certify

    execution_count = 0
    exec_lock = threading.Lock()

    first_started = threading.Event()
    allow_first_to_finish = threading.Event()

    def instrumented_certify(*args, **kwargs):
        nonlocal execution_count
        with exec_lock:
            execution_count += 1
        first_started.set()
        # Hold execution until the second request has definitely reached the idempotency check
        allow_first_to_finish.wait(timeout=5.0)
        return original_certify(*args, **kwargs)

    run_payload = {
        "benchmark_id": "loan_demo",
        "evaluation_mode": "CONTROLLED",
        "target_variant": "clean",
        "idempotency_key": "CONCURRENT-EXEC-ONCE-KEY",
        "force_recompute": False,
    }

    def make_req_a():
        return client.post(
            "/api/v1/certification/run?project_id=proj_a",
            json=run_payload,
            headers={"Authorization": f"Bearer {member_token_proj_a}"},
        )

    def make_req_b():
        # Ensure Request A is actively holding the IN_PROGRESS state in database
        first_started.wait(timeout=5.0)
        res = client.post(
            "/api/v1/certification/run?project_id=proj_a",
            json=run_payload,
            headers={"Authorization": f"Bearer {member_token_proj_a}"},
        )
        allow_first_to_finish.set()
        return res

    try:
        certification_engine.certify = instrumented_certify
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(make_req_a)
            f2 = executor.submit(make_req_b)
            r1 = f1.result(timeout=15.0)
            r2 = f2.result(timeout=15.0)
    finally:
        allow_first_to_finish.set()
        certification_engine.certify = original_certify

    # Both requests must return valid status (200 OK or 202 In-Progress)
    assert r1.status_code in (200, 202)
    assert r2.status_code in (200, 202)

    # CRITICAL INVARIANT: The underlying certification execution happened EXACTLY ONCE
    assert execution_count == 1, f"Expected certify() to be called exactly once, but was called {execution_count} times."


def test_failed_idempotency_record_not_treated_as_in_progress(client, member_token_proj_a):
    """Verifies that a previously failed operation is explicitly returned as FAILED
    and is NEVER incorrectly treated as IN_PROGRESS.
    """
    key = "FAILED-IDEM-TEST-KEY-001"
    run_payload = {
        "benchmark_id": "loan_demo",
        "evaluation_mode": "CONTROLLED",
        "target_variant": "clean",
        "idempotency_key": key,
        "force_recompute": False,
    }

    # 1. Simulate an initial operation that records a failure
    idempotency_manager.check_or_reserve(
        project_id="proj_a",
        endpoint="/api/v1/certification/run",
        idempotency_key=key,
        request_payload=run_payload,
    )
    idempotency_manager.record_failed(
        project_id="proj_a",
        endpoint="/api/v1/certification/run",
        idempotency_key=key,
        request_payload=run_payload,
        error_message="Simulated dependency failure during probe execution",
        status_code=500,
    )

    # 2. Second request with the same idempotency key and same payload
    cached_data, cached_status = idempotency_manager.check_or_reserve(
        project_id="proj_a",
        endpoint="/api/v1/certification/run",
        idempotency_key=key,
        request_payload=run_payload,
    )

    # Must return the stored failure and status code 500
    assert cached_status == 500
    assert cached_data is not None
    assert cached_data.get("status") == "FAILED"
    assert cached_data.get("status") != "IN_PROGRESS"
    assert "Simulated dependency failure" in cached_data.get("detail", "")


def test_failed_idempotency_different_payload_returns_409(client, member_token_proj_a):
    """Verifies that reusing a failed operation's idempotency key with a DIFFERENT payload
    is still rejected with HTTP 409 Conflict.
    """
    key = "FAILED-IDEM-CONFLICT-KEY-002"
    payload_1 = {"benchmark_id": "loan_demo", "target_variant": "clean"}
    payload_2 = {"benchmark_id": "loan_demo", "target_variant": "buggy_rate"}

    idempotency_manager.check_or_reserve(
        project_id="proj_a",
        endpoint="/api/v1/certification/run",
        idempotency_key=key,
        request_payload=payload_1,
    )
    idempotency_manager.record_failed(
        project_id="proj_a",
        endpoint="/api/v1/certification/run",
        idempotency_key=key,
        request_payload=payload_1,
        error_message="Failure 1",
    )

    # Reusing the same key with different payload must raise IdempotencyConflictError (409)
    with pytest.raises(IdempotencyConflictError):
        idempotency_manager.check_or_reserve(
            project_id="proj_a",
            endpoint="/api/v1/certification/run",
            idempotency_key=key,
            request_payload=payload_2,
        )


def test_database_atomic_reservation_prevents_duplicate_ownership():
    """Verifies that SQLite unique constraint on PRIMARY KEY prevents two concurrent callers
    from both becoming the reservation owner, without relying on in-process threading locks.
    """
    import tempfile
    import os

    # Create a temporary SQLite database to test raw DB-level isolation
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as tf:
        temp_db = tf.name

    try:
        mgr1 = IdempotencyManager(db_path=temp_db)
        mgr2 = IdempotencyManager(db_path=temp_db)

        # mgr1 clears its in-memory cache to force pure DB check
        mgr1._memory_cache.clear()
        mgr2._memory_cache.clear()

        payload = {"data": "test_atomic_reservation"}

        # First reservation: mgr1 becomes owner
        res1, status1 = mgr1.check_or_reserve(
            project_id="proj_atomic",
            endpoint="/api/v1/test",
            idempotency_key="ATOMIC-KEY-1",
            request_payload=payload,
        )
        assert res1 is None and status1 is None  # Winner/owner receives (None, None)

        # Clear mgr2's in-memory cache to simulate an independent OS process
        mgr2._memory_cache.clear()

        # Second reservation: mgr2 attempts to reserve same key -> DB conflict detected
        res2, status2 = mgr2.check_or_reserve(
            project_id="proj_atomic",
            endpoint="/api/v1/test",
            idempotency_key="ATOMIC-KEY-1",
            request_payload=payload,
            wait_timeout=0.2,
        )

        # mgr2 must NOT become owner; receives IN_PROGRESS (202) rather than (None, None)
        assert status2 == 202
        assert res2["status"] == "IN_PROGRESS"

        # Verify the database row was NOT replaced or corrupted
        with sqlite3.connect(temp_db) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM operations_idempotency WHERE idempotency_key = 'ATOMIC-KEY-1'")
            row = cursor.fetchone()
            assert row["cnt"] == 1
    finally:
        if os.path.exists(temp_db):
            try:
                os.remove(temp_db)
            except Exception:
                pass


def test_real_dependency_transient_retry_success():
    """Verifies that a real transient dependency failure (HTTP 503) retries and succeeds."""
    import urllib.error

    attempts = 0

    def transient_service():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise urllib.error.HTTPError(
                url="https://api.example.com/generate",
                code=503,
                msg="Service Unavailable",
                hdrs=None,
                fp=None,
            )
        return {"status": "SUCCESS", "data": "recovered"}

    res = execute_with_retry(
        transient_service,
        max_attempts=4,
        base_delay_ms=5.0,
        jitter=False,
        operation_name="test_transient_service",
    )

    assert attempts == 3
    assert res["status"] == "SUCCESS"


def test_real_dependency_permanent_failure_no_retry():
    """Verifies that a permanent dependency failure (HTTP 401 Unauthorized) fails immediately without retry."""
    import urllib.error

    attempts = 0

    def permanent_fail_service():
        nonlocal attempts
        attempts += 1
        raise urllib.error.HTTPError(
            url="https://api.example.com/generate",
            code=401,
            msg="Unauthorized: Invalid API Key",
            hdrs=None,
            fp=None,
        )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        execute_with_retry(
            permanent_fail_service,
            max_attempts=5,
            base_delay_ms=5.0,
            jitter=False,
            operation_name="test_permanent_service",
        )

    assert attempts == 1
    assert exc_info.value.code == 401



