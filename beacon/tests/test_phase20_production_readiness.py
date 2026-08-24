"""Phase 20 — Production Readiness, Configuration Hardening, Lifecycle Management & Release Validation Tests.

Tests configuration validation, environment separation, fail-closed security,
lifespan startup/shutdown, health and readiness probes, and release invariants.
"""

import pytest
import sqlite3
from unittest import mock
from fastapi.testclient import TestClient

from common.config import Settings, ConfigurationError, BEACON_VERSION, settings
from api.main import app, lifespan
from operations.errors import StandardErrorResponse, ErrorCategory
from operations.health import check_readiness, check_liveness



@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


# ==============================================================================
# 1. Configuration Validation & Fail-Closed Security Tests
# ==============================================================================

def test_config_validation_valid_development_and_test():
    """Verifies that development and test environments pass validation with safe defaults."""
    cfg = Settings()
    cfg.beacon_env = "development"
    cfg.jwt_secret_key = "beacon-dev-test-secret-key-do-not-use-in-production-12345"
    errors = cfg.validate(raise_on_error=True)
    assert errors == []


def test_config_validation_production_missing_secret_fails_closed():
    """Verifies that production environment strictly fails closed when JWT_SECRET_KEY is empty or placeholder."""
    cfg = Settings()
    cfg.beacon_env = "production"
    cfg.jwt_secret_key = ""
    with pytest.raises(ConfigurationError) as exc_info:
        cfg.validate(raise_on_error=True)
    assert "JWT_SECRET_KEY is required" in str(exc_info.value)

    cfg.jwt_secret_key = "CHANGE_ME"
    with pytest.raises(ConfigurationError) as exc_info:
        cfg.validate(raise_on_error=True)
    assert "JWT_SECRET_KEY is required" in str(exc_info.value)


def test_config_validation_production_short_secret_fails_closed():
    """Verifies that production requires at least 32 characters for JWT_SECRET_KEY."""
    cfg = Settings()
    cfg.beacon_env = "production"
    cfg.jwt_secret_key = "short-secret-under-32-chars"
    with pytest.raises(ConfigurationError) as exc_info:
        cfg.validate(raise_on_error=True)
    assert "at least 32 characters" in str(exc_info.value)

    # 32+ characters secret passes
    cfg.jwt_secret_key = "valid-production-secret-key-32-chars-long"
    errors = cfg.validate(raise_on_error=True)
    assert errors == []


def test_config_validation_production_wildcard_cors_rejected():
    """Verifies that wildcard '*' CORS origin is rejected in production."""
    cfg = Settings()
    cfg.beacon_env = "production"
    cfg.jwt_secret_key = "valid-production-secret-key-32-chars-long"
    cfg.cors_origins = ["*"]
    with pytest.raises(ConfigurationError) as exc_info:
        cfg.validate(raise_on_error=True)
    assert "CORS_ORIGINS must not contain wildcard" in str(exc_info.value)


def test_config_validation_invalid_bounds_rejected():
    """Verifies that invalid numeric bounds (negative timeouts, retry limits) are rejected."""
    cfg = Settings()
    cfg.beacon_env = "development"
    cfg.operation_timeout_seconds = -1.0
    cfg.max_retry_attempts = 50
    cfg.max_dataset_size_bytes = -100
    cfg.confidence_threshold = 2.5
    
    with pytest.raises(ConfigurationError) as exc_info:
        cfg.validate(raise_on_error=True)
    
    err_str = str(exc_info.value)
    assert "OPERATION_TIMEOUT_SECONDS must be positive" in err_str
    assert "MAX_RETRY_ATTEMPTS must be between 0 and 20" in err_str
    assert "MAX_DATASET_SIZE_BYTES must be positive" in err_str
    assert "CONFIDENCE_THRESHOLD must be between 0.0 and 1.0" in err_str


def test_config_validation_mongodb_uri_format():
    """Verifies MongoDB URI validation when optional URI is provided."""
    cfg = Settings()
    cfg.beacon_env = "development"
    cfg.mongodb_atlas_uri = "invalid-uri-without-mongo-prefix"
    with pytest.raises(ConfigurationError) as exc_info:
        cfg.validate(raise_on_error=True)
    assert "MONGODB_ATLAS_URI must start with" in str(exc_info.value)


# ==============================================================================
# 2. Modern Lifespan Management Tests
# ==============================================================================

import asyncio

def test_lifespan_startup_and_shutdown_execution():
    """Verifies that FastAPI lifespan context manager completes startup and graceful shutdown cleanly."""
    async def _run():
        async with lifespan(app):
            # Inside lifespan: application is fully initialized and operational
            live_res = check_liveness()
            assert live_res.status == "UP"
            assert live_res.version == BEACON_VERSION
    asyncio.run(_run())


# ==============================================================================
# 3. Health, Liveness & Readiness Endpoint Tests
# ==============================================================================

def test_liveness_endpoint_returns_200_and_version(client):
    """Verifies that liveness probes (/health/live, /live, /api/v1/health/live) return 200 and version."""
    for path in ("/health/live", "/live", "/api/v1/health/live"):
        res = client.get(path)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "UP"
        assert data["service"] == "BEACON"
        assert data["version"] == BEACON_VERSION


def test_readiness_endpoint_healthy_database_returns_200(client):
    """Verifies that readiness probes (/health/ready, /ready, /api/v1/health/ready) return 200 when ready."""
    for path in ("/health/ready", "/ready", "/api/v1/health/ready"):
        res = client.get(path)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "READY"
        assert data["checks"]["database"] is True


def test_readiness_endpoint_unreachable_database_returns_503(client):
    """Verifies that readiness probe returns 503 Service Unavailable when the database is unreachable."""
    with mock.patch("sqlite3.connect", side_effect=sqlite3.OperationalError("Database disk I/O error")):
        res = client.get("/health/ready")
        assert res.status_code == 503
        data = res.json()
        assert data["status"] == "NOT_READY"
        assert "database_unavailable" in data["reasons"]


def test_standard_health_endpoint(client):
    """Verifies public /health endpoint exposes only safe status and version."""
    for path in ("/health", "/api/v1/health"):
        res = client.get(path)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] in ("ok", "degraded")
        assert data["version"] == BEACON_VERSION
        assert "storage" not in data
        assert "environment" not in data


# ==============================================================================
# 4. Response Headers, Conditional HSTS & Security Hardening
# ==============================================================================

def test_response_headers_contain_version_and_security_headers(client):
    """Verifies that all HTTP responses include X-Beacon-Version and security headers."""
    res = client.get("/health/live")
    assert res.status_code == 200
    assert res.headers.get("X-Beacon-Version") == BEACON_VERSION
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("X-XSS-Protection") == "1; mode=block"


def test_hsts_header_conditional_on_https(client, monkeypatch):
    """Verifies that HSTS header is conditionally attached only on HTTPS in production/staging."""
    # 1. Dev mode (HTTP) -> No HSTS
    monkeypatch.setattr(settings, "beacon_env", "development")
    res = client.get("/health/live")
    assert "Strict-Transport-Security" not in res.headers

    # 2. Production mode (HTTP) -> No HSTS
    monkeypatch.setattr(settings, "beacon_env", "production")
    res = client.get("/health/live")
    assert "Strict-Transport-Security" not in res.headers

    # 3. Production mode (HTTPS via header) -> HSTS present
    res_https = client.get("/health/live", headers={"x-forwarded-proto": "https"})
    assert "Strict-Transport-Security" in res_https.headers
    assert "max-age=31536000" in res_https.headers["Strict-Transport-Security"]


# ==============================================================================
# 5. Safe Standard Error Formatting & Secret Redaction
# ==============================================================================

def test_standard_error_response_structure():
    """Verifies StandardErrorResponse model structure and secret scrubbing."""
    err = StandardErrorResponse(
        error_code="VALIDATION_ERROR",
        category=ErrorCategory.VALIDATION_ERROR,
        message="Invalid token Bearer eyJhbGciOiJIUzI1NiJ9.secret",
        request_id="REQ-12345",
    )
    dump = err.model_dump(mode="json")
    assert dump["error_code"] == "VALIDATION_ERROR"
    assert dump["category"] == "VALIDATION_ERROR"
    assert dump["request_id"] == "REQ-12345"
    assert "[REDACTED_SECRET]" in dump["message"]
    assert "eyJhbGciOiJIUzI1NiJ9" not in dump["message"]


# ==============================================================================
# 6. Versioning, Upload Safety & Oracle Compilation Protection
# ==============================================================================

def test_version_endpoints_metadata(client):
    """Verifies safe version and build metadata on /version and /api/v1/operations/version."""
    for path in ("/version", "/api/v1/operations/version"):
        res = client.get(path)
        assert res.status_code == 200
        data = res.json()
        assert data["service"] == "BEACON"
        assert data["version"] == BEACON_VERSION
        assert data["api_version"] == "v1"
        assert "timestamp" in data


def test_compile_oracle_endpoint_authorization_protection(client):
    """Verifies that /api/oracles/compile requires authentication / CERTIFY permissions."""
    candidate_payload = {
        "invariant_id": "inv-test-1",
        "condition": "credit_score < 580",
        "consequence": "REJECT",
        "status": "candidate",
        "confidence": 0.95,
        "grounding_result": {"grounded": True, "verdict": "VERIFIED"},
        "validation_result": {"passed": True, "passed_all": True},
    }
    # Unauthenticated call without credentials
    res = client.post("/api/oracles/compile", json=candidate_payload)
    assert res.status_code in (401, 403)



def test_oversized_dataset_upload_rejected_by_workload_protector(client, monkeypatch):
    """Verifies that dataset upload payload exceeding max_dataset_size_bytes is rejected."""
    monkeypatch.setattr(settings, "max_dataset_size_bytes", 50)
    oversized_csv = "feature_a,feature_b\n" + "12345,67890\n" * 20
    
    res = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "dataset_name": "Oversized Test Dataset",
            "project_id": "proj-default",
            "data_format": "csv",
            "raw_content": oversized_csv,
            "declared_provenance": "SYNTHETIC_GENERATION",
        },
        headers={"Authorization": "Bearer test-admin-token"} if settings.auth_required else {},
    )
    assert res.status_code in (413, 401, 403, 422)


def test_dataset_upload_prohibited_secrets_rejected(client):
    """Verifies that user datasets containing raw API keys/tokens are rejected during preview/upload."""
    leaked_secret_csv = "user_id,api_key\n101,sk-ant-api03-abcdef123456789\n102,sk-or-v1-abcdef123456789"
    res = client.post(
        "/api/v1/custom/datasets/preview",
        json={
            "dataset_name": "Prohibited Secret Dataset",
            "project_id": "proj-default",
            "data_format": "csv",
            "raw_content": leaked_secret_csv,
            "declared_provenance": "PRODUCTION_TELEMETRY",
        },
        headers={"Authorization": "Bearer test-admin-token"} if settings.auth_required else {},
    )
    if res.status_code == 200:
        data = res.json()
        assert data["validation_passed"] is False
        assert any("prohibited secret" in err.lower() for err in data.get("errors", []))
    else:
        assert res.status_code in (400, 401, 403, 422)


# ==============================================================================
# 7. Endpoint Authorization & Security Classification Regression Tests
# ==============================================================================

def test_drift_evaluate_endpoint_requires_auth(client):
    """Verifies POST /api/v1/drift/evaluate requires valid authentication/permissions."""
    payload = {
        "observation_id": "obs-001",
        "oracle_set_id": "set-loan-approval",
        "inputs": {"credit_score": 720, "loan_amount": 250000},
        "outputs": {"approved": True},
    }
    res = client.post("/api/v1/drift/evaluate", json=payload)
    assert res.status_code in (401, 403)


def test_demo_endpoints_disabled_in_production(client, monkeypatch):
    """Verifies demo endpoints (/demo/run, /drift/demo, /demo/invariants) are disabled in production."""
    monkeypatch.setattr(settings, "beacon_env", "production")
    
    # 1. POST /demo/run
    res_run = client.post("/demo/run", json={"implementation": "buggy"})
    assert res_run.status_code in (401, 403)
    
    # 2. POST /drift/demo
    res_drift = client.post("/drift/demo", json={"baseline_run_id": "run-1", "implementation": "buggy"})
    assert res_drift.status_code in (401, 403)
    
    # 3. GET /demo/invariants
    res_inv = client.get("/demo/invariants")
    assert res_inv.status_code in (401, 403)


def test_benchmark_validate_endpoint_requires_auth(client):
    """Verifies POST /api/v1/benchmarks/{id}/validate requires authentication."""
    res = client.post("/api/v1/benchmarks/loan_approval/validate")
    assert res.status_code in (401, 403)


def test_runs_and_drift_endpoints_require_auth(client):
    """Verifies /runs and /drift endpoints require authentication."""
    # Unauthenticated /runs
    res_runs = client.get("/runs")
    assert res_runs.status_code in (401, 403)

    # Unauthenticated /runs/{id}
    res_run = client.get("/runs/run-test-id")
    assert res_run.status_code in (401, 403)

    # Unauthenticated /drift
    res_drift = client.get("/drift")
    assert res_drift.status_code in (401, 403)


def test_llm_status_and_oracle_catalog_require_auth(client):
    """Verifies /api/llm/status and oracle catalog endpoints require authentication."""
    # /api/llm/status
    res_llm = client.get("/api/llm/status")
    assert res_llm.status_code in (401, 403)

    # /api/oracles
    res_orc = client.get("/api/oracles")
    assert res_orc.status_code in (401, 403)

    # /api/oracle-sets
    res_sets = client.get("/api/oracle-sets")
    assert res_sets.status_code in (401, 403)


def test_root_endpoint_safe_metadata(client):
    """Verifies that GET / returns safe public API metadata and does not disclose storage/environment/paths."""
    import json
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "BEACON API"
    assert data["status"] == "ok"
    assert data["health"] == "/health"
    assert data["live"] == "/health/live"
    assert data["ready"] == "/health/ready"
    assert data["details"] == "/health/details"
    assert data["version"] == "/api/v1/operations/version"

    # Strict non-disclosure assertions
    dump_str = json.dumps(data).lower()
    assert "storage" not in data
    assert "sqlite" not in dump_str
    assert "mongodb" not in dump_str
    assert "database" not in dump_str
    assert "secret" not in dump_str
    assert "password" not in dump_str


def test_runs_project_scoping_and_cross_project_isolation(client, tmp_path, monkeypatch):
    """Verifies that /runs and /runs/{run_id} enforce strict project scoping and cross-project isolation."""
    from common.local_store import LocalStore
    from common.models import CertificationRun
    from auth import (
        User,
        UserRole,
        auth_repository,
        create_access_token,
        ProjectMembership,
    )
    import uuid

    # Isolated local store
    db_file = tmp_path / "test_runs_scope.sqlite3"
    store = LocalStore(db_file)
    monkeypatch.setattr("api.main.local_store", store)

    # 1. Create User A with membership in Project A
    user_a = auth_repository.create_user(
        user_id=f"usr-a-{uuid.uuid4().hex[:6]}",
        username=f"user_a_{uuid.uuid4().hex[:6]}",
        email="user_a@example.com",
        password="UserAPassword2026!",
        full_name="User A",
    )
    auth_repository.assign_user_to_project(user_a.user_id, "proj-alpha", UserRole.VIEWER)
    token_a = create_access_token(user=user_a)
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # 2. Create User B with membership in Project B
    user_b = auth_repository.create_user(
        user_id=f"usr-b-{uuid.uuid4().hex[:6]}",
        username=f"user_b_{uuid.uuid4().hex[:6]}",
        email="user_b@example.com",
        password="UserBPassword2026!",
        full_name="User B",
    )
    auth_repository.assign_user_to_project(user_b.user_id, "proj-beta", UserRole.VIEWER)
    token_b = create_access_token(user=user_b)
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 3. Seed runs into LocalStore
    run_a = CertificationRun(
        run_id="run-alpha-001",
        timestamp="2026-08-24T00:00:00Z",
        equivalence_score=1.0,
        total_checked=10,
        total_violated=0,
        results=[],
    )
    store.save_run(run_a, project_id="proj-alpha")

    run_b = CertificationRun(
        run_id="run-beta-001",
        timestamp="2026-08-24T00:00:00Z",
        equivalence_score=0.75,
        total_checked=10,
        total_violated=3,
        results=[],
    )
    store.save_run(run_b, project_id="proj-beta")

    # 4. Unauthenticated -> 401
    assert client.get("/runs").status_code == 401
    assert client.get("/runs/run-alpha-001").status_code == 401

    # 5. User A queries Project A -> receives only Run A
    res_a = client.get("/runs?project_id=proj-alpha", headers=headers_a)
    assert res_a.status_code == 200
    runs_a = res_a.json()["runs"]
    assert len(runs_a) == 1
    assert runs_a[0]["run_id"] == "run-alpha-001"
    assert runs_a[0]["project_id"] == "proj-alpha"

    # 6. User A querying Project B (unauthorized) -> 403 / 404
    res_a_on_b = client.get("/runs?project_id=proj-beta", headers=headers_a)
    assert res_a_on_b.status_code in (403, 404)

    # 7. User A accesses Run A -> 200; accesses Run B -> 403 / 404
    res_run_a = client.get("/runs/run-alpha-001", headers=headers_a)
    assert res_run_a.status_code == 200
    assert res_run_a.json()["run_id"] == "run-alpha-001"

    res_run_b = client.get("/runs/run-beta-001", headers=headers_a)
    assert res_run_b.status_code in (403, 404)

    # 8. User B queries Project B -> receives only Run B
    res_b = client.get("/runs?project_id=proj-beta", headers=headers_b)
    assert res_b.status_code == 200
    runs_b = res_b.json()["runs"]
    assert len(runs_b) == 1
    assert runs_b[0]["run_id"] == "run-beta-001"





