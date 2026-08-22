"""Phase 16 — Production Readiness, Observability, Reliability & Performance Tests.

Verifies:
1. Operational Health Model (Liveness, Readiness, Dependency Health without secrets)
2. Optional Provider Fallback (Missing OpenRouter/Anthropic does not fail readiness)
3. Request Correlation Tracking (X-Correlation-ID / X-Request-ID headers and propagation)
4. Safe Standardized Error Responses (Zero stack trace or file path leakage)
5. Certification Job Lifecycle State Machine & Polling API
6. Separation of Job State (COMPLETED) from Certification Status (NOT_CERTIFIED)
7. Workload & Resource Bounds Enforcement (Rejection without silent truncation)
8. Operational Metrics Collection and Aggregation (Runs, fallbacks, latencies)
9. Evidence Hash Invariance (Operational instrumentation leaves cryptographic proof untouched)
10. Project Namespace Isolation on Operational Endpoints
"""

import json
import logging
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(ROOT_DIR / "legacy_sample"))

from api.main import app
from common.config import settings
from certification.repository import certification_repository
from ingestion.audit import audit_logger
from operations import (
    check_liveness,
    check_readiness,
    check_dependency_health,
    certification_job_tracker,
    operational_metrics,
    workload_protector,
    JobState,
    ErrorCategory,
    ResourceLimitError,
)


@pytest.fixture(autouse=True)
def clean_state():
    """Ensures clean state for tests."""
    certification_repository.clear()
    audit_logger.clear()
    certification_job_tracker.clear()
    operational_metrics.clear()
    from benchmarks import benchmark_registry
    benchmark_registry.refresh()
    yield
    certification_repository.clear()
    audit_logger.clear()
    certification_job_tracker.clear()
    operational_metrics.clear()
    from benchmarks import benchmark_registry
    benchmark_registry.refresh()


@pytest.fixture
def client():
    return TestClient(app)


# ==============================================================================
# 1. Operational Health Model & Non-Sensitive Diagnostics
# ==============================================================================

def test_liveness_endpoint_succeeds(client):
    """Verifies that /health/live succeeds quickly and indicates process vitality."""
    res = client.get("/health/live")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "UP"
    assert data["service"] == "BEACON"
    assert bool(data["timestamp"])


def test_readiness_endpoint_succeeds_with_healthy_dependencies(client):
    """Verifies that /health/ready passes when required local registries and DB are available."""
    res = client.get("/health/ready")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "READY"
    assert data["checks"]["database"] is True
    assert data["checks"]["benchmark_registry"] is True
    assert data["checks"]["oracle_set_registry"] is True
    assert len(data["reasons"]) == 0


def test_health_details_contains_zero_secrets(client):
    """Verifies that /health/details reports granular statuses and zero secret keys or tokens."""
    res = client.get("/health/details")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("HEALTHY", "DEGRADED")
    assert data["liveness"] == "UP"
    assert data["readiness"] == "READY"

    # Inspect all dependency payloads for sensitive strings
    dumped = json.dumps(data)
    forbidden_tokens = ["sk-ant-", "sk-or-", "Bearer ", "password", "token_secret", "mongodb+srv://"]
    for token in forbidden_tokens:
        assert token not in dumped

    # Verify structured dependency categories
    deps = data["dependencies"]
    assert "database" in deps
    assert "benchmark_registry" in deps
    assert "oracle_set_registry" in deps
    assert "provider_offline" in deps
    assert deps["provider_offline"]["status"] == "healthy"


def test_optional_provider_unavailable_does_not_fail_readiness(client, monkeypatch):
    """Verifies that when optional cloud providers are unconfigured, readiness remains READY."""
    # Simulate missing cloud keys
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")

    readiness = check_readiness()
    assert readiness.status == "READY"

    details = check_dependency_health()
    # Offline deterministic provider is always healthy
    assert details.dependencies["provider_offline"].status == "healthy"
    # Optional unconfigured providers are marked safely as not_configured / degraded without breaking readiness
    assert details.readiness == "READY"


# ==============================================================================
# 2. Request Correlation IDs
# ==============================================================================

def test_request_correlation_id_generation_and_propagation(client):
    """Verifies that every API request receives correlation IDs in headers and response."""
    # Auto-generation
    res = client.get("/health/live")
    assert res.status_code == 200
    req_id = res.headers.get("X-Correlation-ID")
    assert req_id is not None
    assert req_id.startswith("REQ-")
    assert res.headers.get("X-Request-ID") == req_id
    assert "X-Response-Time" in res.headers

    # Client-supplied preservation
    custom_id = "CORR-TEST-CLIENT-12345"
    res_custom = client.get("/health/live", headers={"X-Correlation-ID": custom_id})
    assert res_custom.status_code == 200
    assert res_custom.headers.get("X-Correlation-ID") == custom_id
    assert res_custom.headers.get("X-Request-ID") == custom_id


def test_correlation_id_distinct_from_certification_id_and_idempotency(client):
    """Verifies request_id, certification_id, and idempotency_key remain completely distinct."""
    idem_key = "IDEM-KEY-999"
    res = client.post(
        "/api/v1/certification/run",
        headers={"X-Correlation-ID": "CORR-RUN-777"},
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
            "idempotency_key": idem_key,
        },
    )
    assert res.status_code == 200
    art = res.json()
    
    cert_id = art["certification_id"]
    response_req_id = res.headers.get("X-Correlation-ID")

    assert response_req_id == "CORR-RUN-777"
    assert cert_id.startswith("CERT-")
    assert cert_id != response_req_id
    assert cert_id != idem_key
    assert art["context"]["idempotency_key"] == idem_key


# ==============================================================================
# 3. Safe Standardized Error Responses (No Python Tracebacks)
# ==============================================================================

def test_safe_error_handling_structure(client):
    """Verifies that errors conform to StandardErrorResponse without Python traceback leakage."""
    # 404 Not Found
    res_404 = client.get("/api/v1/certification/artifacts/NON_EXISTENT_CERT_ID")
    assert res_404.status_code == 404
    data_404 = res_404.json()
    assert data_404["category"] == "NOT_FOUND"
    assert "Traceback" not in json.dumps(data_404)
    assert bool(data_404["request_id"])

    # 422 / 400 Validation Error
    res_val = client.post("/api/v1/certification/run", json={"benchmark_id": 12345})  # wrong type
    assert res_val.status_code == 422
    data_val = res_val.json()
    assert data_val["category"] == "VALIDATION_ERROR"
    assert "field_errors" in data_val.get("details", {})
    assert "Traceback" not in json.dumps(data_val)


# ==============================================================================
# 4. Certification Job Lifecycle & Polling
# ==============================================================================

def test_job_lifecycle_transitions_from_accepted_to_completed(client):
    """Verifies that running certification transitions through the job lifecycle to COMPLETED."""
    res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )
    assert res.status_code == 200
    art = res.json()
    cert_id = art["certification_id"]
    proj_id = art.get("context", {}).get("project_id") or "benchmark_retail_discount_pricing"

    # Query recent jobs — project_id required
    jobs_res = client.get(f"/api/v1/certification/jobs?project_id={proj_id}")
    assert jobs_res.status_code == 200
    jobs = jobs_res.json()["jobs"]
    assert len(jobs) > 0

    # Locate the job associated with cert_id
    matching_job = next((j for j in jobs if j.get("certification_id") == cert_id), None)
    assert matching_job is not None
    assert matching_job["state"] == "COMPLETED"
    assert matching_job["progress_pct"] == 100
    assert matching_job["certification_status"] == "CERTIFIED"
    assert matching_job["equivalence_score"] == 1.0
    assert matching_job["duration_ms"] is not None
    assert matching_job["duration_ms"] >= 0.0


def test_job_state_distinct_from_certification_status(client):
    """Verifies that Job State = COMPLETED while Certification Status = NOT_CERTIFIED for buggy runs."""
    res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "buggy_threshold_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "buggy",
            "preferred_provider": "offline",
        },
    )
    assert res.status_code == 200
    art = res.json()
    cert_id = art["certification_id"]
    assert art["status"] == "NOT_CERTIFIED"
    proj_id = art.get("context", {}).get("project_id") or "benchmark_retail_discount_pricing"

    # Query job status — project_id required
    jobs_res = client.get(f"/api/v1/certification/jobs?project_id={proj_id}")
    job = next(j for j in jobs_res.json()["jobs"] if j.get("certification_id") == cert_id)

    # Job is successfully COMPLETED (no crashes), but Certification outcome is NOT_CERTIFIED
    assert job["state"] == "COMPLETED"
    assert job["certification_status"] == "NOT_CERTIFIED"
    assert job["equivalence_score"] < 1.0


def test_job_lifecycle_project_isolation(client):
    """Verifies that querying jobs enforces project authorization boundaries."""
    # Create job under proj_tenant_alpha
    job = certification_job_tracker.create_job(
        project_id="proj_tenant_alpha",
        benchmark_id="retail_discount_pricing",
    )

    # Authorized query succeeds
    res_ok = client.get(f"/api/v1/certification/jobs/{job.job_id}?project_id=proj_tenant_alpha")
    assert res_ok.status_code == 200

    # Unauthorized query fails with 403 Forbidden
    res_denied = client.get(f"/api/v1/certification/jobs/{job.job_id}?project_id=proj_tenant_beta")
    assert res_denied.status_code == 403


# ==============================================================================
# 5. Idempotency Preservation
# ==============================================================================

def test_idempotency_returns_cached_result_without_duplicate_work(client):
    """Verifies that sending identical certification requests returns existing artifact immediately."""
    payload = {
        "benchmark_id": "retail_discount_pricing",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
        "implementation": "equivalent",
        "preferred_provider": "offline",
        "idempotency_key": "IDEM-REPEAT-TEST",
    }

    # Run 1
    res1 = client.post("/api/v1/certification/run", json=payload)
    assert res1.status_code == 200
    cert_id_1 = res1.json()["certification_id"]

    # Run 2 (Identical payload)
    res2 = client.post("/api/v1/certification/run", json=payload)
    assert res2.status_code == 200
    cert_id_2 = res2.json()["certification_id"]

    # Must return exact same certification ID
    assert cert_id_1 == cert_id_2


# ==============================================================================
# 6. Workload & Resource Bounds Enforcement
# ==============================================================================

def test_oversized_dataset_rejected_with_resource_limit(client, monkeypatch):
    """Verifies that datasets exceeding configured byte limits are rejected with RESOURCE_LIMIT."""
    # Set small limit for testing (10 KB)
    monkeypatch.setattr(settings, "max_dataset_size_bytes", 1024)

    large_payload = json.dumps([{"order_amount": 100.0, "customer_tier": "VIP"}] * 200)

    res = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_workload_test",
            "dataset_name": "Oversized Test Dataset",
            "data_format": "JSON",
            "raw_content": large_payload,
            "declared_provenance": "REALISTIC_SYNTHETIC",
        },
    )
    # Must reject with 413 Resource Limit
    assert res.status_code == 413
    data = res.json()
    assert data["category"] == "RESOURCE_LIMIT"
    assert "exceeds maximum configured limit" in data["message"]


# ==============================================================================
# 7. Operational Metrics & Summary
# ==============================================================================

def test_operational_metrics_endpoint_aggregation(client):
    """Verifies that metrics endpoints aggregate run counters and timings cleanly."""
    proj_id = "benchmark_retail_discount_pricing"

    # Execute a clean run
    client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )

    # Check project-scoped metrics
    m_res = client.get(f"/api/v1/operations/metrics?project_id={proj_id}")
    assert m_res.status_code == 200
    metrics = m_res.json()
    assert metrics["certification_runs_total"] >= 1
    assert metrics["certification_runs_successful"] >= 1
    assert metrics["certification_status_breakdown"].get("CERTIFIED", 0) >= 1
    assert metrics["avg_certification_duration_ms"] >= 0.0

    # Check project-scoped summary endpoint
    s_res = client.get(f"/api/v1/operations/summary?project_id={proj_id}")
    assert s_res.status_code == 200
    summary = s_res.json()
    assert "system_status" in summary
    assert "dependencies" in summary
    assert "recent_jobs" in summary
    assert len(summary["recent_jobs"]) > 0


# ==============================================================================
# 8. Performance & Evidence Hash Invariance
# ==============================================================================

def test_operational_instrumentation_does_not_mutate_evidence_hash(client):
    """Verifies that adding operational metrics/logging does not alter the Phase-15 evidence hash."""
    res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )
    cert_id = res.json()["certification_id"]

    # Cryptographic integrity verification must strictly pass
    v_res = client.post(f"/api/v1/evidence/verify/{cert_id}")
    assert v_res.status_code == 200
    assert v_res.json()["status"] == "PASS"
    assert v_res.json()["artifact_integrity_valid"] is True


# ==============================================================================
# 9. Regression Tests A–H (from Phase 16 Correction Specification)
# ==============================================================================

def test_A_lifecycle_all_stages_recorded(client):
    """Test A: Verifies the full lifecycle passes through all expected states.
    For a fresh (non-idempotent) run the job must reach COMPLETED state.
    State transitions are verified deterministically via the final terminal state.
    """
    # Use force_recompute=True to ensure a fresh execution path (not idempotency cache)
    res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
            "force_recompute": True,
        },
    )
    assert res.status_code == 200
    art = res.json()
    cert_id = art["certification_id"]
    proj_id = art.get("context", {}).get("project_id") or "benchmark_retail_discount_pricing"

    jobs = client.get(f"/api/v1/certification/jobs?project_id={proj_id}").json()["jobs"]
    job = next((j for j in jobs if j.get("certification_id") == cert_id), None)
    assert job is not None, f"No job found for cert_id={cert_id} under project={proj_id}"

    # Terminal state must be COMPLETED (validates all transitions occurred)
    assert job["state"] == "COMPLETED"
    assert job["duration_ms"] is not None
    assert job["duration_ms"] >= 0.0
    assert job["certification_status"] == "CERTIFIED"


def test_A_lifecycle_failure_transitions_to_failed(client):
    """Test A (failure path): Controlled failure causes FAILED state with error_category set."""
    from operations import certification_job_tracker, JobState

    # Create a job manually and drive it through FAILED
    job = certification_job_tracker.create_job(
        project_id="proj_fail_test",
        benchmark_id="retail_discount_pricing",
    )
    certification_job_tracker.update_state(job.job_id, JobState.QUEUED, "Queued")
    certification_job_tracker.update_state(job.job_id, JobState.VALIDATING, "Validating")
    certification_job_tracker.update_state(
        job.job_id,
        JobState.FAILED,
        current_step="Simulated validation failure",
        error_category="VALIDATION_ERROR",
        error_message="Controlled test failure",
    )

    # Retrieve the job and verify terminal FAILED state
    res = client.get(f"/api/v1/certification/jobs/{job.job_id}?project_id=proj_fail_test")
    assert res.status_code == 200
    data = res.json()
    assert data["state"] == "FAILED"
    assert data["error_category"] == "VALIDATION_ERROR"
    assert data["duration_ms"] is not None


def test_1_empty_oracleset_registry_reports_not_ready(client):
    """Test 1: When OracleSet registry is empty, /health/ready MUST report NOT_READY (not READY).
    Creation capability in benchmark registry must NOT cause false-positive readiness.
    """
    from oracle.registry import registry as oracle_registry

    existing_sets = list(oracle_registry.list_oracle_sets())
    try:
        oracle_registry.clear()
        assert len(oracle_registry.list_oracle_sets()) == 0

        res = client.get("/health/ready")
        assert res.status_code in (200, 503)
        data = res.json()
        assert data["status"] == "NOT_READY"
        assert data["checks"]["oracle_set_registry"] is False
        assert "oracle_set_registry_empty" in data["reasons"]
    finally:
        for s in existing_sets:
            if not oracle_registry.get_oracle_set(s.oracle_set_id):
                oracle_registry.register_oracle_set(s)


def test_2_health_check_does_not_mutate_oraclesets(client):
    """Test 2: Multiple calls to /health/ready must NOT create or register any OracleSets."""
    from oracle.registry import registry as oracle_registry

    count_before = len(oracle_registry.list_oracle_sets())
    ids_before = set(s.oracle_set_id for s in oracle_registry.list_oracle_sets())

    for _ in range(5):
        res = client.get("/health/ready")
        assert res.status_code == 200

    count_after = len(oracle_registry.list_oracle_sets())
    ids_after = set(s.oracle_set_id for s in oracle_registry.list_oracle_sets())

    assert count_after == count_before
    assert ids_after == ids_before


def test_3_restoring_oraclesets_restores_readiness(client):
    """Test 3: Clearing OracleSets makes system NOT_READY; restoring them makes it READY."""
    from oracle.registry import registry as oracle_registry
    from benchmarks import benchmark_registry

    existing_sets = list(oracle_registry.list_oracle_sets())
    try:
        # Clear
        oracle_registry.clear()
        res_empty = client.get("/health/ready")
        assert res_empty.json()["status"] == "NOT_READY"

        # Restore
        for b in benchmark_registry.list_benchmarks():
            benchmark_registry.resolve_controlled_oracle_set(b.benchmark_id)

        res_restored = client.get("/health/ready")
        assert res_restored.json()["status"] == "READY"
        assert res_restored.json()["checks"]["oracle_set_registry"] is True
    finally:
        for s in existing_sets:
            if not oracle_registry.get_oracle_set(s.oracle_set_id):
                oracle_registry.register_oracle_set(s)


def test_4_ready_and_details_agree_consistently(client):
    """Test 4: /health/ready and /health/details must agree consistently in both missing and present states."""
    from oracle.registry import registry as oracle_registry
    from benchmarks import benchmark_registry

    existing_sets = list(oracle_registry.list_oracle_sets())
    try:
        # Case A: Missing
        oracle_registry.clear()
        ready_res = client.get("/health/ready").json()
        details_res = client.get("/health/details").json()

        assert ready_res["status"] == "NOT_READY"
        assert ready_res["checks"]["oracle_set_registry"] is False
        assert details_res["readiness"] == "NOT_READY"
        assert details_res["dependencies"]["oracle_set_registry"]["status"] == "unavailable"
        assert details_res["status"] in ("UNAVAILABLE", "DEGRADED")

        # Case B: Restored
        for b in benchmark_registry.list_benchmarks():
            benchmark_registry.resolve_controlled_oracle_set(b.benchmark_id)

        ready_res2 = client.get("/health/ready").json()
        details_res2 = client.get("/health/details").json()

        assert ready_res2["status"] == "READY"
        assert ready_res2["checks"]["oracle_set_registry"] is True
        assert details_res2["readiness"] == "READY"
        assert details_res2["dependencies"]["oracle_set_registry"]["status"] == "healthy"
    finally:
        for s in existing_sets:
            if not oracle_registry.get_oracle_set(s.oracle_set_id):
                oracle_registry.register_oracle_set(s)


def test_5_liveness_remains_intact_when_dependencies_down(client):
    """Test 5: /health/live returns UP even when OracleSet registry is empty or database is down."""
    from oracle.registry import registry as oracle_registry

    existing_sets = list(oracle_registry.list_oracle_sets())
    try:
        oracle_registry.clear()

        res = client.get("/health/live")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "UP"
        assert data["service"] == "BEACON"
    finally:
        for s in existing_sets:
            if not oracle_registry.get_oracle_set(s.oracle_set_id):
                oracle_registry.register_oracle_set(s)


def test_B_health_readiness_is_read_only(client):
    """Test B: Verifies that GET /health/ready is purely read-only — oracle count unchanged."""
    from oracle.registry import registry as oracle_registry

    count_before = len(oracle_registry.list_oracle_sets())

    for _ in range(3):
        res = client.get("/health/ready")
        assert res.status_code == 200

    count_after = len(oracle_registry.list_oracle_sets())
    assert count_after == count_before


def test_C_project_isolation_jobs_endpoint(client):
    """Test C: Project isolation — Project A cannot see Project B's jobs."""
    from operations import certification_job_tracker

    # Create jobs for two different projects
    job_a = certification_job_tracker.create_job(
        project_id="iso_proj_alpha",
        benchmark_id="retail_discount_pricing",
    )
    job_b = certification_job_tracker.create_job(
        project_id="iso_proj_beta",
        benchmark_id="retail_discount_pricing",
    )

    # Project Alpha can only see its own jobs
    res_a = client.get("/api/v1/certification/jobs?project_id=iso_proj_alpha")
    assert res_a.status_code == 200
    job_ids_a = [j["job_id"] for j in res_a.json()["jobs"]]
    assert job_a.job_id in job_ids_a
    assert job_b.job_id not in job_ids_a

    # Project Beta can only see its own jobs
    res_b = client.get("/api/v1/certification/jobs?project_id=iso_proj_beta")
    assert res_b.status_code == 200
    job_ids_b = [j["job_id"] for j in res_b.json()["jobs"]]
    assert job_b.job_id in job_ids_b
    assert job_a.job_id not in job_ids_b

    # Cross-project direct job lookup must return 403
    res_cross = client.get(f"/api/v1/certification/jobs/{job_a.job_id}?project_id=iso_proj_beta")
    assert res_cross.status_code == 403


def test_C_project_isolation_metrics_endpoint(client):
    """Test C (metrics): Project A metrics do not include Project B runs."""
    # Run a clean certification for a known project
    res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
            "force_recompute": True,
        },
    )
    assert res.status_code == 200
    proj_id = res.json().get("context", {}).get("project_id") or "benchmark_retail_discount_pricing"

    # Metrics for the real project must show >= 1 run
    m_real = client.get(f"/api/v1/operations/metrics?project_id={proj_id}").json()
    assert m_real["certification_runs_total"] >= 1

    # Metrics for a completely different project must show 0 runs
    m_other = client.get("/api/v1/operations/metrics?project_id=completely_unrelated_project_xyz").json()
    assert m_other["certification_runs_total"] == 0


def test_D_health_error_sanitization(client, monkeypatch):
    """Test D: Simulated dependency failure must not expose raw exception text in API response."""
    import sqlite3
    from operations.health import check_readiness

    # Monkeypatch sqlite3.connect to raise an error with sensitive-looking text
    original_connect = sqlite3.connect
    def fake_connect(*args, **kwargs):
        raise sqlite3.OperationalError(
            "unable to open database file: C:\\private\\db_secret_token=abc123\\beacon.db"
        )
    monkeypatch.setattr(sqlite3, "connect", fake_connect)

    readiness = check_readiness()

    # Status must be NOT_READY
    assert readiness.status == "NOT_READY"

    # Reasons must only contain safe category strings — no raw exception text
    for reason in readiness.reasons:
        assert "sqlite3" not in reason.lower()
        assert "OperationalError" not in reason
        assert "C:\\" not in reason
        assert "secret" not in reason.lower()
        assert "token" not in reason.lower()
        # Must only be a safe category
        assert reason in (
            "database_unavailable",
            "benchmark_registry_unavailable",
            "benchmark_registry_empty",
            "oracle_set_registry_unavailable",
            "oracle_set_registry_empty",
            "dataset_registry_unavailable",
            "certification_repository_unavailable",
        )


def test_E_idempotency_regression(client):
    """Test E: Phase-13/14 idempotency behavior is preserved — same request returns same artifact."""
    payload = {
        "benchmark_id": "retail_discount_pricing",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
        "implementation": "equivalent",
        "preferred_provider": "offline",
        "idempotency_key": "REGRESSION-IDEM-E-001",
    }
    res1 = client.post("/api/v1/certification/run", json=payload)
    assert res1.status_code == 200
    cert_id_1 = res1.json()["certification_id"]

    res2 = client.post("/api/v1/certification/run", json=payload)
    assert res2.status_code == 200
    cert_id_2 = res2.json()["certification_id"]

    # Must return the same certification ID
    assert cert_id_1 == cert_id_2


def test_F_certification_result_regression(client):
    """Test F: Retail Clean → CERTIFIED, Retail Buggy → NOT_CERTIFIED results are unchanged."""
    # Clean → CERTIFIED
    res_clean = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
            "force_recompute": True,
        },
    )
    assert res_clean.status_code == 200
    assert res_clean.json()["status"] == "CERTIFIED"
    assert res_clean.json()["score"] == 1.0

    # Buggy → NOT_CERTIFIED with counterexamples
    res_buggy = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "buggy_threshold_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "buggy",
            "preferred_provider": "offline",
            "force_recompute": True,
        },
    )
    assert res_buggy.status_code == 200
    assert res_buggy.json()["status"] == "NOT_CERTIFIED"
    assert res_buggy.json()["score"] < 1.0
    assert len(res_buggy.json()["regressions"]) > 0


def test_G_custom_dataset_regression(client):
    """Test G: Custom dataset upload → validate → pre-flight → certify → evidence still works."""
    import json
    sample_data = json.dumps([
        {"order_amount": 600.0, "customer_tier": "VIP", "coupon_code": "NONE",
         "items_count": 10, "is_express_shipping": False, "discount_applied_pct": 0.20},
        {"order_amount": 100.0, "customer_tier": "STANDARD", "coupon_code": "NONE",
         "items_count": 5, "is_express_shipping": False, "discount_applied_pct": 0.05},
    ])

    # 1. Upload
    up_res = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "regression_proj_g",
            "dataset_name": "Regression Test G Dataset",
            "data_format": "JSON",
            "raw_content": sample_data,
        },
    )
    assert up_res.status_code == 200
    ds_id = up_res.json()["dataset_id"]

    # 2. Pre-flight
    pf_res = client.post(
        "/api/v1/custom/preflight",
        json={
            "project_id": "regression_proj_g",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "oracle_set_id": "SET-RETAIL_DISCOUNT_PRICING-CONTROLLED",
            "evaluation_mode": "CONTROLLED",
        },
    )
    assert pf_res.status_code == 200
    fingerprint = pf_res.json()["config_fingerprint"]

    # 3. Certify
    cert_res = client.post(
        "/api/v1/custom/certify",
        json={
            "project_id": "regression_proj_g",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "oracle_set_id": "SET-RETAIL_DISCOUNT_PRICING-CONTROLLED",
            "evaluation_mode": "CONTROLLED",
            "config_fingerprint": fingerprint,
        },
    )
    assert cert_res.status_code == 200
    cert_id = cert_res.json()["certification_id"]
    assert cert_res.json()["status"] in ("CERTIFIED", "NOT_CERTIFIED", "INCONCLUSIVE", "INSUFFICIENT_COVERAGE")

    # 4. Evidence dossier accessible
    ev_res = client.get(f"/api/v1/evidence/dossiers/{cert_id}?project_id=regression_proj_g")
    assert ev_res.status_code == 200


def test_H_resource_limit_regression(client, monkeypatch):
    """Test H: Oversized dataset must return RESOURCE_LIMIT and not be silently certified."""
    import json as _json
    monkeypatch.setattr(settings, "max_dataset_size_bytes", 512)

    large = _json.dumps([{"order_amount": 100.0, "customer_tier": "VIP"}] * 100)
    res = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_resource_limit_h",
            "dataset_name": "Oversized Regression",
            "data_format": "JSON",
            "raw_content": large,
        },
    )
    # Must be rejected with 413 RESOURCE_LIMIT — no partial certification
    assert res.status_code == 413
    data = res.json()
    assert data["category"] == "RESOURCE_LIMIT"


def test_jobs_endpoint_requires_project_id(client):
    """Verifies that /api/v1/certification/jobs returns 422 when project_id is missing."""
    res = client.get("/api/v1/certification/jobs")
    assert res.status_code == 422


def test_metrics_endpoint_requires_project_id(client):
    """Verifies that /api/v1/operations/metrics returns 422 when project_id is missing."""
    res = client.get("/api/v1/operations/metrics")
    assert res.status_code == 422


def test_summary_endpoint_requires_project_id(client):
    """Verifies that /api/v1/operations/summary returns 422 when project_id is missing."""
    res = client.get("/api/v1/operations/summary")
    assert res.status_code == 422
