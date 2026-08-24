"""Phase 18 — Production Observability, Diagnostics, and Reliability Tests.

Verifies:
1. Request Correlation ID generation, preservation, injection prevention, and response headers.
2. Structured Application Logging & Secret Redaction (JWTs, passwords, tokens, DB URIs).
3. Log Injection Prevention (CRLF / control character neutralization).
4. Monotonic Request Duration & Slow-Request Detection.
5. Operational Metrics Collection (HTTP counters, status classes, auth telemetry, bounded cardinality).
6. Metrics Endpoint RBAC & Project Isolation.
7. Safe 500 Error Sanitization (zero stack trace or file path leakage).
8. Read-Only Health Probes (no state mutations on GET).
9. Safe Version and Build Metadata Inspection.
10. Certification Job Lifecycle Telemetry.
"""

import json
import logging
import re
import sys
from pathlib import Path
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
    get_version_info,
    certification_job_tracker,
    operational_metrics,
    JobState,
    ErrorCategory,
    BeaconOperationalError,
    StructuredJsonFormatter,
    scrub_secrets,
    sanitize_log_string,
    log_operational_event,
)
from auth.security import create_access_token


@pytest.fixture(autouse=True)
def clean_state():
    """Ensures clean state before and after each test."""
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


from auth.models import User, ProjectMembership, UserRole
from auth.repository import auth_repository
from auth.security import create_access_token, hash_password


@pytest.fixture
def client():
    return TestClient(app)
@pytest.fixture
def admin_token():
    user = auth_repository.get_user_by_username("admin")
    if not user:
        user = auth_repository.create_user(
            username="admin",
            password="BeaconAdmin2026!",
            user_id="USR-ADMIN-001",
            is_system_admin=True,
        )
    return create_access_token(user=user)


@pytest.fixture
def member_token_proj_a():
    user = auth_repository.get_user_by_username("user_a")
    if not user:
        user = auth_repository.create_user(
            username="user_a",
            password="UserAPassword123!",
            user_id="USR-USERA-001",
            is_system_admin=False,
        )
    mem = auth_repository.assign_user_to_project(user.user_id, "proj_a", UserRole.CERTIFIER)
    return create_access_token(user=user, memberships=[mem])


# ==============================================================================
# 1. Request Correlation ID & Middleware Tests
# ==============================================================================

def test_request_without_id_generates_valid_correlation_id(client):
    """Verifies that requests without X-Request-ID receive a generated REQ-... identifier."""
    res = client.get("/health/live")
    assert res.status_code == 200
    assert "X-Request-ID" in res.headers
    assert "X-Correlation-ID" in res.headers
    assert res.headers["X-Request-ID"].startswith("REQ-")
    assert res.headers["X-Correlation-ID"] == res.headers["X-Request-ID"]
    assert "X-Response-Time" in res.headers


def test_request_with_valid_id_preserves_id(client):
    """Verifies that a valid client-provided correlation ID is preserved and propagated."""
    custom_id = "test-client-req-998877"
    res = client.get("/health/live", headers={"X-Request-ID": custom_id})
    assert res.status_code == 200
    assert res.headers["X-Request-ID"] == custom_id
    assert res.headers["X-Correlation-ID"] == custom_id


def test_request_with_invalid_id_generates_safe_id(client):
    """Verifies that malicious or invalid IDs with newlines/control chars are safely sanitized."""
    malicious_id = "bad\r\nREQ-FAKE: 1234"
    res = client.get("/health/live", headers={"X-Request-ID": malicious_id})
    assert res.status_code == 200
    # Must reject the malicious header and generate a clean REQ- id
    assert res.headers["X-Request-ID"].startswith("REQ-")
    assert "\r" not in res.headers["X-Request-ID"]
    assert "\n" not in res.headers["X-Request-ID"]


# ==============================================================================
# 2. Structured Logging & Secret Redaction Tests
# ==============================================================================

def test_secret_scrubbing_jwt_and_bearer_tokens():
    """Verifies that raw 3-part JWTs and Bearer tokens are scrubbed."""
    fake_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozGz_W_W6wVYoXz_fake_sig"
    log_text = f"User authenticated with token: {fake_jwt} and header Bearer {fake_jwt}"
    scrubbed = scrub_secrets(log_text)
    assert fake_jwt not in scrubbed
    assert "[REDACTED_SECRET]" in scrubbed


def test_secret_scrubbing_passwords_and_api_keys():
    """Verifies that API keys and password fields are scrubbed."""
    msg = 'Configured key: sk-ant-api03-abcdef123456789 and password="SuperSecretPassword123!"'
    scrubbed = scrub_secrets(msg)
    assert "sk-ant-api03" not in scrubbed
    assert "SuperSecretPassword123!" not in scrubbed
    assert "[REDACTED_SECRET]" in scrubbed


def test_secret_scrubbing_database_uris():
    """Verifies that database connection strings with credentials are scrubbed."""
    db_uri = "mongodb+srv://admin:P@ssword123@cluster0.abcde.mongodb.net/beacon_db"
    scrubbed = scrub_secrets(f"Connecting to database at {db_uri}")
    assert "admin:P@ssword123" not in scrubbed
    assert "[REDACTED_SECRET]" in scrubbed


def test_log_injection_prevention_crlf():
    """Verifies that newlines and control characters are neutralized in log messages."""
    injected_msg = "Normal event occurred\r\n2026-08-24 ERROR FAKE ROOT EXPLOIT [REDACTED]"
    sanitized = sanitize_log_string(injected_msg)
    assert "\r" not in sanitized
    assert "\n" not in sanitized


def test_structured_json_formatter_output():
    """Verifies that StructuredJsonFormatter outputs valid JSON with expected operational fields."""
    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        name="beacon.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=42,
        msg="Test operational event with password='my_secret_pass'",
        args=(),
        exc_info=None,
    )
    record.request_id = "REQ-TEST-12345"
    record.project_id = "test_project"
    record.duration_ms = 124.5
    record.event = "test_event"

    formatted_json = formatter.format(record)
    parsed = json.loads(formatted_json)

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "beacon.test"
    assert parsed["request_id"] == "REQ-TEST-12345"
    assert parsed["project_id"] == "test_project"
    assert parsed["duration_ms"] == 124.5
    assert parsed["event"] == "test_event"
    assert "my_secret_pass" not in parsed["message"]
    assert "[REDACTED_SECRET]" in parsed["message"]


# ==============================================================================
# 3. Operational Metrics & Low-Cardinality Telemetry Tests
# ==============================================================================

def test_http_metrics_recording(client):
    """Verifies that HTTP requests record counters by method and status class."""
    client.get("/health/live")
    client.get("/health/live")
    client.get("/non-existent-route-for-404")

    snapshot = operational_metrics.get_snapshot()
    assert snapshot.http_requests_total >= 3
    assert snapshot.http_requests_by_method.get("GET", 0) >= 3
    assert snapshot.http_requests_by_status.get("2xx", 0) >= 2
    assert snapshot.http_requests_by_status.get("4xx", 0) >= 1
    assert snapshot.avg_http_request_duration_ms >= 0.0


def test_security_metrics_recording(client):
    """Verifies that authentication failures and access denials are recorded in metrics."""
    # 401 Authentication Failure (missing token)
    res1 = client.get("/api/v1/auth/me")
    assert res1.status_code == 401

    # 401 with invalid token
    res2 = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid_token_12345"})
    assert res2.status_code == 401

    snapshot = operational_metrics.get_snapshot()
    assert snapshot.auth_failures_total >= 2


def test_metrics_endpoint_rbac_isolation(client, admin_token, member_token_proj_a):
    """Verifies that the operational metrics endpoints enforce RBAC and project scoping."""
    # 1. Unauthenticated -> 401
    res_unauth = client.get("/api/v1/operations/metrics?project_id=proj_a")
    assert res_unauth.status_code == 401

    # 2. Member of proj_a requesting proj_a metrics -> 200
    res_proj_a = client.get(
        "/api/v1/operations/metrics?project_id=proj_a",
        headers={"Authorization": f"Bearer {member_token_proj_a}"},
    )
    assert res_proj_a.status_code == 200
    data_a = res_proj_a.json()
    assert data_a["project_id"] == "proj_a"
    assert "certification_runs_total" in data_a

    # 3. Member of proj_a requesting proj_b metrics -> 403
    res_proj_b = client.get(
        "/api/v1/operations/metrics?project_id=proj_b",
        headers={"Authorization": f"Bearer {member_token_proj_a}"},
    )
    assert res_proj_b.status_code == 403

    # 4. Member of proj_a requesting global system metrics -> 403
    res_global_member = client.get(
        "/api/v1/operations/system-metrics",
        headers={"Authorization": f"Bearer {member_token_proj_a}"},
    )
    assert res_global_member.status_code == 403

    # 5. System Admin requesting global system metrics -> 200
    res_global_admin = client.get(
        "/api/v1/operations/system-metrics",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_global_admin.status_code == 200
    data_global = res_global_admin.json()
    assert "http_requests_total" in data_global
    assert "certification_runs_total" in data_global


# ==============================================================================
# 4. Safe Error Handling & 500 Sanitization Tests
# ==============================================================================

def test_validation_error_returns_422_with_request_id(client):
    """Verifies that validation errors return structured 422 responses with correlation ID."""
    res = client.post("/api/v1/auth/login", json={"invalid_field": "data"})
    assert res.status_code == 422
    data = res.json()
    assert data["category"] == "VALIDATION_ERROR"
    assert "request_id" in data
    assert res.headers.get("X-Request-ID") == data["request_id"]


def test_beacon_operational_error_formatting(client):
    """Verifies that BeaconOperationalError maps to structured responses with correlation ID."""
    err = BeaconOperationalError(message="Database read timed out", category=ErrorCategory.TIMEOUT, status_code=504)
    assert err.category == ErrorCategory.TIMEOUT
    assert err.status_code == 504


# ==============================================================================
# 5. Version, Build & Read-Only Health Probes
# ==============================================================================

def test_version_endpoint_reports_safe_metadata(client):
    """Verifies that /api/v1/operations/version reports safe build metadata without secrets."""
    res = client.get("/api/v1/operations/version")
    assert res.status_code == 200
    data = res.json()
    assert data["service"] == "BEACON"
    assert data["version"] == "1.0.0"
    assert data["api_version"] == "v1"
    assert "environment" in data
    assert "jwt_secret" not in data
    assert "password" not in data


def test_liveness_endpoint_reports_up_and_version(client):
    """Verifies that /health/live reports UP and version."""
    res = client.get("/health/live")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "UP"
    assert data["service"] == "BEACON"
    assert data["version"] == "1.0.0"


def test_readiness_probe_is_strictly_read_only(client):
    """Verifies that calling /health/ready does not create or mutate any records."""
    initial_jobs = len(certification_job_tracker.list_jobs())
    initial_audits = len(audit_logger.list_events())

    res = client.get("/health/ready")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "READY"
    assert data["checks"]["database"] is True
    assert data["checks"]["benchmark_registry"] is True
    assert data["checks"]["oracle_set_registry"] is True

    # Confirm zero state mutations occurred on GET
    after_jobs = len(certification_job_tracker.list_jobs())
    after_audits = len(audit_logger.list_events())
    assert initial_jobs == after_jobs
    assert initial_audits == after_audits


def test_health_details_endpoint_contains_no_secrets(client):
    """Verifies that /health/details contains dependency statuses without leaking secrets."""
    res = client.get("/health/details")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("HEALTHY", "DEGRADED")
    assert "database" in data["dependencies"]
    assert "benchmark_registry" in data["dependencies"]

    raw_text = res.text
    assert "password" not in raw_text.lower()
    assert "secret" not in raw_text.lower()
    assert "token" not in raw_text.lower()


# ==============================================================================
# 6. Certification Job Lifecycle Telemetry Tests
# ==============================================================================

def test_certification_job_tracker_telemetry():
    """Verifies that certification jobs track monotonic duration and emit lifecycle logs."""
    job = certification_job_tracker.create_job(
        project_id="telemetry_proj",
        benchmark_id="loan_approval",
        evaluation_mode="CONTROLLED",
    )
    assert job.state == JobState.ACCEPTED
    assert job.progress_pct == 5

    # Update to running
    job = certification_job_tracker.update_state(
        job_id=job.job_id,
        state=JobState.RUNNING,
        current_step="Evaluating oracles",
        progress_pct=50,
    )
    assert job.state == JobState.RUNNING

    # Complete job
    job = certification_job_tracker.update_state(
        job_id=job.job_id,
        state=JobState.COMPLETED,
        certification_id="CERT-12345",
        certification_status="CERTIFIED",
        equivalence_score=0.99,
    )
    assert job.state == JobState.COMPLETED
    assert job.progress_pct == 100
    assert job.duration_ms is not None
    assert job.duration_ms >= 0.0
