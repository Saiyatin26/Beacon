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
    yield
    certification_repository.clear()
    audit_logger.clear()
    certification_job_tracker.clear()
    operational_metrics.clear()


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

    # Query recent jobs
    jobs_res = client.get("/api/v1/certification/jobs")
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

    # Query job status
    jobs_res = client.get("/api/v1/certification/jobs")
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

    # Check metrics
    m_res = client.get("/api/v1/operations/metrics")
    assert m_res.status_code == 200
    metrics = m_res.json()
    assert metrics["certification_runs_total"] >= 1
    assert metrics["certification_runs_successful"] >= 1
    assert metrics["certification_status_breakdown"].get("CERTIFIED", 0) >= 1
    assert metrics["avg_certification_duration_ms"] >= 0.0

    # Check summary endpoint
    s_res = client.get("/api/v1/operations/summary")
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
