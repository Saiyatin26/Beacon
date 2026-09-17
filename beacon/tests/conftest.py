"""
BEACON Test Suite Configuration and Fixtures.

Configures test environment variables and provides test isolation.
Ensures Phase 1-16 regression suites run reliably while Phase 17
strictly exercises live authentication, RBAC, and multi-tenant security.
"""

import os
import pytest

# Ensure test environment settings
os.environ["BEACON_ENV"] = "test"
os.environ["ENVIRONMENT"] = "test"
os.environ["BEACON_REQUIRE_AUTH"] = "true"
os.environ["JWT_SECRET_KEY"] = "beacon_pytest_secure_test_signing_secret_key_2026"
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""

import sys
from pathlib import Path

# Ensure backend directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from common.config import settings
settings.openrouter_api_key = ""
settings.anthropic_api_key = ""

from api.main import app
from auth import (
    get_current_user,
    get_current_active_user,
    User,
    UserRole,
    auth_repository,
    auth_rate_limiter,
)
from certification.repository import certification_repository
from ingestion.audit import audit_logger


@pytest.fixture(autouse=True)
def configure_test_auth_isolation(request):
    """Provides test harness auth isolation.
    - Phase 17 security test suites run against the live, unmodified auth pipeline.
    - Legacy Phase 1-16 mathematical and operational tests receive a valid test principal.
    """
    test_file_name = request.node.fspath.basename if hasattr(request.node, "fspath") else str(request.node.nodeid)

    if (
        "test_phase9" in test_file_name
        or "test_phase10" in test_file_name
        or "test_phase11" in test_file_name
        or "test_v2_phase11" in test_file_name
        or "test_phase17" in test_file_name
        or "test_phase18" in test_file_name
        or "test_phase20" in test_file_name
        or "test_pre_freeze" in test_file_name
    ):
        # Strict mode: no dependency overrides; evaluate live authentication
        app.dependency_overrides.clear()
        auth_rate_limiter.clear()
        yield
        app.dependency_overrides.clear()
        auth_rate_limiter.clear()

    else:
        # Legacy test harness: provide authenticated test principal
        test_admin = User(
            user_id="USR-TEST-ADMIN",
            username="test_admin",
            password_hash="$pbkdf2-sha256$100000$test$test",
            full_name="Test Administrator",
            email="test_admin@beacon.local",
            is_system_admin=True,
        )
        app.dependency_overrides[get_current_user] = lambda: test_admin
        app.dependency_overrides[get_current_active_user] = lambda: test_admin
        yield
        app.dependency_overrides.clear()
