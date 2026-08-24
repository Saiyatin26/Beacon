"""Phase 20 — Production Readiness, Configuration Hardening, Lifecycle Management & Release Validation Tests.

Tests configuration validation, environment separation, fail-closed security,
lifespan startup/shutdown, health and readiness probes, and release invariants.
"""

import pytest
import sqlite3
from unittest import mock
from fastapi.testclient import TestClient

from backend.common.config import Settings, ConfigurationError, BEACON_VERSION, settings
from backend.api.main import app, lifespan
from backend.operations.errors import StandardErrorResponse, ErrorCategory
from backend.operations.health import check_readiness, check_liveness


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
    """Verifies that production requires at least 16 characters for JWT_SECRET_KEY."""
    cfg = Settings()
    cfg.beacon_env = "production"
    cfg.jwt_secret_key = "short-secret"
    with pytest.raises(ConfigurationError) as exc_info:
        cfg.validate(raise_on_error=True)
    assert "at least 16 characters" in str(exc_info.value)


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
    """Verifies unified /health and /api/v1/health endpoints."""
    for path in ("/health", "/api/v1/health"):
        res = client.get(path)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] in ("ok", "degraded")
        assert data["liveness"] == "UP"
        assert data["version"] == BEACON_VERSION


# ==============================================================================
# 4. Response Headers & Security Hardening
# ==============================================================================

def test_response_headers_contain_version_and_security_headers(client):
    """Verifies that all HTTP responses include X-Beacon-Version and security headers."""
    res = client.get("/health/live")
    assert res.status_code == 200
    assert res.headers.get("X-Beacon-Version") == BEACON_VERSION
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("X-XSS-Protection") == "1; mode=block"


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
# 6. Versioning, Upload Safety & CORS Tests
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
    # When auth is disabled/bypassed in tests or with token, must return 413 or 422/400
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


