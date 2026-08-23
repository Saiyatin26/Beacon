"""
Phase 17 — Authentication, Authorization & Multi-Tenant Security Test Suite
Tests:
1. Password hashing with PBKDF2-HMAC-SHA256 & constant time verification
2. JWT generation, decoding, expiration, and signature tampering prevention
3. Authentication endpoints (/login, /logout, /me)
4. Rate limiting on authentication attempts
5. RBAC enforcement (VIEWER, CERTIFIER, AUDITOR, PROJECT_ADMIN, SYSTEM_ADMIN)
6. Multi-tenant project boundary isolation and cross-project access rejection
7. Zero credential leakage in audit trails and error responses
8. Security headers middleware (X-Content-Type-Options, X-Frame-Options, HSTS, XSS Protection)
"""

from datetime import timedelta
import time
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.auth import (
    UserRole,
    Permission,
    ROLE_PERMISSIONS,
    role_has_permission,
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    auth_repository,
    auth_rate_limiter,
    User,
    ProjectMembership,
)
from backend.common.config import settings
from backend.ingestion.audit import audit_logger, AuditAction


client = TestClient(app)


# ==============================================================================
# 1. Cryptography & Token Security Tests
# ==============================================================================

def test_password_hashing_and_verification():
    raw_pw = "SecretP@ssw0rd123!"
    hashed = hash_password(raw_pw)
    assert hashed.startswith("$pbkdf2-sha256$")
    assert verify_password(raw_pw, hashed) is True
    assert verify_password("WrongPassword", hashed) is False
    assert verify_password("", hashed) is False


def test_unique_salts_for_same_password():
    raw_pw = "SamePassword123!"
    hash1 = hash_password(raw_pw)
    hash2 = hash_password(raw_pw)
    assert hash1 != hash2
    assert verify_password(raw_pw, hash1) is True
    assert verify_password(raw_pw, hash2) is True


def test_jwt_generation_and_valid_decoding():
    user = User(
        user_id="USR-ALICE-002",
        username="alice_certifier",
        password_hash="$pbkdf2-sha256$100000$dummy$dummy",
        email="alice@retail.corp",
        full_name="Alice",
        is_system_admin=False,
    )
    memberships = [
        ProjectMembership(
            membership_id="MEM-1",
            user_id="USR-ALICE-002",
            project_id="proj_retail_pilot",
            role=UserRole.CERTIFIER,
        )
    ]
    token = create_access_token(
        user=user,
        memberships=memberships,
        expires_delta=timedelta(minutes=15),
    )
    payload = decode_access_token(token)
    assert payload.username == "alice_certifier"
    assert payload.sub == "USR-ALICE-002"
    assert payload.is_system_admin is False
    assert payload.memberships.get("proj_retail_pilot") == "CERTIFIER"


def test_jwt_tampered_signature_rejected():
    user = User(
        user_id="USR-ALICE-002",
        username="alice_certifier",
        password_hash="$pbkdf2-sha256$100000$dummy$dummy",
        email="alice@retail.corp",
        full_name="Alice",
        is_system_admin=False,
    )
    token = create_access_token(user=user)
    # Tamper with the signature portion of the token
    parts = token.split(".")
    tampered_sig = parts[2][:-4] + "AAAA"
    tampered_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"

    with pytest.raises(Exception):
        decode_access_token(tampered_token)


def test_jwt_expired_token_rejected():
    user = User(
        user_id="USR-ALICE-002",
        username="alice_certifier",
        password_hash="$pbkdf2-sha256$100000$dummy$dummy",
        email="alice@retail.corp",
        full_name="Alice",
        is_system_admin=False,
    )
    token = create_access_token(
        user=user,
        expires_delta=timedelta(seconds=-10),
    )
    with pytest.raises(Exception) as excinfo:
        decode_access_token(token)
    assert "expired" in str(excinfo.value).lower()


# ==============================================================================
# 2. RBAC Permissions Matrix Tests
# ==============================================================================

def test_rbac_permission_matrix():
    # Viewer
    assert role_has_permission(UserRole.VIEWER, Permission.VIEW) is True
    assert role_has_permission(UserRole.VIEWER, Permission.CERTIFY) is False
    assert role_has_permission(UserRole.VIEWER, Permission.AUDIT) is False
    assert role_has_permission(UserRole.VIEWER, Permission.MANAGE_PROJECT) is False

    # Certifier
    assert role_has_permission(UserRole.CERTIFIER, Permission.VIEW) is True
    assert role_has_permission(UserRole.CERTIFIER, Permission.CERTIFY) is True
    assert role_has_permission(UserRole.CERTIFIER, Permission.AUDIT) is False
    assert role_has_permission(UserRole.CERTIFIER, Permission.MANAGE_PROJECT) is False

    # Auditor
    assert role_has_permission(UserRole.AUDITOR, Permission.VIEW) is True
    assert role_has_permission(UserRole.AUDITOR, Permission.CERTIFY) is False
    assert role_has_permission(UserRole.AUDITOR, Permission.AUDIT) is True
    assert role_has_permission(UserRole.AUDITOR, Permission.MANAGE_PROJECT) is False

    # Project Admin
    assert role_has_permission(UserRole.PROJECT_ADMIN, Permission.VIEW) is True
    assert role_has_permission(UserRole.PROJECT_ADMIN, Permission.CERTIFY) is True
    assert role_has_permission(UserRole.PROJECT_ADMIN, Permission.AUDIT) is True
    assert role_has_permission(UserRole.PROJECT_ADMIN, Permission.MANAGE_PROJECT) is True

    # System Admin
    assert role_has_permission(UserRole.SYSTEM_ADMIN, Permission.SYSTEM_OPERATIONS) is True


# ==============================================================================
# 3. Authentication Endpoints Tests
# ==============================================================================

def test_login_endpoint_success():
    res = client.post(
        "/api/v1/auth/login",
        json={"username": "alice_certifier", "password": "AliceCert2026!"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["username"] == "alice_certifier"
    assert len(data["user"]["memberships"]) > 0


def test_login_endpoint_invalid_password():
    res = client.post(
        "/api/v1/auth/login",
        json={"username": "alice_certifier", "password": "WrongPassword!"},
    )
    assert res.status_code == 401
    assert "invalid" in res.json()["detail"].lower()


def test_login_endpoint_nonexistent_user():
    res = client.post(
        "/api/v1/auth/login",
        json={"username": "non_existent_user_999", "password": "SomePassword123!"},
    )
    assert res.status_code == 401
    assert "invalid" in res.json()["detail"].lower()


def test_auth_me_endpoint_with_valid_token():
    # Login first
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "carol_auditor", "password": "CarolAudit2026!"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    # Access /me
    me_res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == 200
    data = me_res.json()
    assert data["username"] == "carol_auditor"
    assert data["email"] == "carol@audit.org"


def test_auth_me_endpoint_unauthorized():
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


def test_auth_logout_endpoint():
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "bob_viewer", "password": "BobView2026!"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    logout_res = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logout_res.status_code == 200
    assert logout_res.json()["status"] == "logged_out"


# ==============================================================================
# 4. Rate Limiting Tests
# ==============================================================================

def test_login_rate_limiting():
    client_ip = "192.168.1.100"
    auth_rate_limiter.reset(client_ip)

    # 10 attempts should succeed
    for _ in range(10):
        auth_rate_limiter.record_attempt(client_ip)
    
    # 11th attempt should be blocked
    is_allowed, retry_after = auth_rate_limiter.is_allowed(client_ip)
    assert is_allowed is False
    assert retry_after > 0

    # Reset
    auth_rate_limiter.reset(client_ip)
    is_allowed, retry_after = auth_rate_limiter.is_allowed(client_ip)
    assert is_allowed is True


# ==============================================================================
# 5. Role-Based Access Control (RBAC) Enforcement Tests
# ==============================================================================

def test_viewer_cannot_trigger_benchmark_certification():
    # Login as Bob (Viewer)
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "bob_viewer", "password": "BobView2026!"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    # Bob attempts to certify (requires CERTIFY permission)
    res = client.post(
        "/api/v1/certification/run",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "benchmark_id": "retail_discount_pricing",
            "target_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "preferred_provider": "offline",
        },
    )
    assert res.status_code == 403
    assert "permission" in res.json()["detail"].lower()


def test_certifier_can_trigger_benchmark_certification():
    # Login as Alice (Certifier)
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "alice_certifier", "password": "AliceCert2026!"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    res = client.post(
        "/api/v1/certification/run",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "benchmark_id": "retail_discount_pricing",
            "target_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "preferred_provider": "offline",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "certification_id" in data
    assert data["status"] in ("CERTIFIED", "NOT_CERTIFIED")


def test_auditor_cannot_trigger_certification():
    # Login as Carol (Auditor)
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "carol_auditor", "password": "CarolAudit2026!"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    res = client.post(
        "/api/v1/certification/run",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "benchmark_id": "retail_discount_pricing",
            "target_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "preferred_provider": "offline",
        },
    )
    assert res.status_code == 403


def test_auditor_can_create_auditor_note():
    # First certify to get an artifact ID
    cert_res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "target_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "preferred_provider": "offline",
        },
    )
    cert_id = cert_res.json()["certification_id"]

    # Login as Carol (Auditor)
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "carol_auditor", "password": "CarolAudit2026!"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    # Carol adds note (requires AUDIT permission)
    note_res = client.post(
        f"/api/v1/evidence/dossiers/{cert_id}/notes",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "Authoritative review: All invariant boundaries preserved."},
    )
    assert note_res.status_code == 200
    assert note_res.json()["content"] == "Authoritative review: All invariant boundaries preserved."


def test_viewer_cannot_create_auditor_note():
    # Certify to get an artifact ID
    cert_res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "target_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "preferred_provider": "offline",
        },
    )
    cert_id = cert_res.json()["certification_id"]

    # Login as Bob (Viewer)
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "bob_viewer", "password": "BobView2026!"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    # Bob tries to add note (should be 403)
    note_res = client.post(
        f"/api/v1/evidence/dossiers/{cert_id}/notes",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "Viewer attempt to add note."},
    )
    assert note_res.status_code == 403


# ==============================================================================
# 6. Multi-Tenant Project Boundary Isolation Tests
# ==============================================================================

def test_cross_project_isolation_blocked():
    # Login as external_user who only has access to 'proj_other_finance'
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "external_user", "password": "External2026!"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    # external_user attempts to access retail_discount_pricing resources
    res = client.post(
        "/api/v1/certification/run",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "benchmark_id": "retail_discount_pricing",
            "target_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "preferred_provider": "offline",
        },
    )
    # Should be 403 Forbidden due to project boundary mismatch
    assert res.status_code == 403
    assert "forbidden" in res.json()["detail"].lower() or "not a member" in res.json()["detail"].lower() or "access denied" in res.json()["detail"].lower()


def test_system_admin_has_universal_access():
    # Login as Admin (SYSTEM_ADMIN)
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "BeaconAdmin2026!"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    # Admin can certify any benchmark/project
    res = client.post(
        "/api/v1/certification/run",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "benchmark_id": "retail_discount_pricing",
            "target_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "preferred_provider": "offline",
        },
    )
    assert res.status_code == 200


# ==============================================================================
# 7. Zero Credential Leaks in Audit Logs Tests
# ==============================================================================

def test_no_passwords_or_tokens_in_audit_logs():
    # Trigger login success, login failure, and access denied events
    client.post(
        "/api/v1/auth/login",
        json={"username": "alice_certifier", "password": "AliceCert2026!"},
    )
    client.post(
        "/api/v1/auth/login",
        json={"username": "alice_certifier", "password": "LeakedPassword123!"},
    )

    events = audit_logger.list_events(limit=50)
    for event in events:
        details_str = str(event.details).lower()
        assert "leakedpassword" not in details_str
        assert "alicecert2026!" not in details_str
        assert "bearer" not in details_str
        assert "secret" not in details_str


# ==============================================================================
# 8. Security Headers Middleware Tests
# ==============================================================================

def test_security_headers_present():
    res = client.get("/health/live")
    assert res.status_code == 200
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("X-XSS-Protection") == "1; mode=block"
    assert "max-age=" in res.headers.get("Strict-Transport-Security", "")
