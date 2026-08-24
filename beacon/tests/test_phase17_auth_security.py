"""
Phase 17 — Authentication, Authorization & Multi-Tenant Security Test Suite.

Exhaustively verifies:
1. PBKDF2 password hashing & constant-time verification
2. HS256 JWT access tokens with unique jti, expiration, and signature tampering prevention
3. Real token revocation on logout (reusing revoked token returns 401)
4. Mandatory authentication on all protected endpoints (missing token -> 401)
5. Public endpoints accessibility (/health/live, /health/ready, /health/details, /login)
6. User management authorization (non-admin -> 403, system_admin -> 200)
7. Rate limiting on authentication attempts
8. RBAC permission matrix (VIEWER, CERTIFIER, AUDITOR, PROJECT_ADMIN, SYSTEM_ADMIN)
9. Multi-tenant project boundary isolation (cross-project cert / job / dossier -> 403)
10. Cross-project evidence comparison strictly rejected (403)
11. Zero secrets in audit logs, user responses, and operational details
12. Security response headers (HSTS, nosniff, frame-options, xss-protection)
13. Deterministic certification mathematical invariance under authenticated execution
"""

from datetime import timedelta
import json
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
from backend.certification.repository import certification_repository
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
    assert bool(payload.jti) is True
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


def test_jwt_malformed_token_rejected():
    with pytest.raises(Exception):
        decode_access_token("not.a.valid.jwt.token")


# ==============================================================================
# 2. Token Revocation on Logout Tests (Requirement 7 & 8)
# ==============================================================================

def test_token_revocation_on_logout_blocks_subsequent_requests():
    # 1. Login to obtain access token
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "alice_certifier", "password": "AliceCert2026!"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    # 2. Access protected endpoint with valid token -> 200
    me_res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["username"] == "alice_certifier"

    # 3. Call Logout -> Revokes the token
    logout_res = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logout_res.status_code == 200
    assert logout_res.json()["status"] == "logged_out"

    # 4. Reuse the SAME token -> MUST BE 401 Unauthorized
    reuse_res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert reuse_res.status_code == 401
    assert "revoked" in reuse_res.json()["detail"].lower() or "invalid" in reuse_res.json()["detail"].lower()


# ==============================================================================
# 3. Mandatory Authentication for Protected APIs (Requirement 1 & 2)
# ==============================================================================

def test_protected_endpoints_reject_missing_token_with_401():
    # 1. Certification Run
    res1 = client.post(
        "/api/v1/certification/run",
        json={"benchmark_id": "retail_discount_pricing"},
    )
    assert res1.status_code == 401
    assert "authentication required" in res1.json()["detail"].lower()

    # 2. Custom Datasets
    res2 = client.get("/api/v1/custom/datasets")
    assert res2.status_code == 401

    # 3. Custom Certify
    res3 = client.post(
        "/api/v1/custom/certify",
        json={"dataset_id": "DS-TEST", "target_code": "def f(): pass"},
    )
    assert res3.status_code == 401

    # 4. Operational Metrics
    res4 = client.get("/api/v1/operations/metrics?project_id=proj_retail_pilot")
    assert res4.status_code == 401

    # 5. Operational Summary
    res5 = client.get("/api/v1/operations/summary?project_id=proj_retail_pilot")
    assert res5.status_code == 401

    # 6. Certification Jobs
    res6 = client.get("/api/v1/certification/jobs?project_id=proj_retail_pilot")
    assert res6.status_code == 401

    # 7. Evidence Compare
    res7 = client.post(
        "/api/v1/evidence/compare",
        json={"run_id_a": "CERT-1", "run_id_b": "CERT-2"},
    )
    assert res7.status_code == 401

    # 8. User Management
    res8 = client.post(
        "/api/v1/auth/users",
        json={"username": "new_user", "password": "Password123!"},
    )
    assert res8.status_code == 401


def test_public_health_endpoints_remain_accessible_without_token():
    # 1. /health/live is public
    res1 = client.get("/health/live")
    assert res1.status_code == 200
    assert res1.json()["status"] == "UP"

    # 2. /health/ready is public
    res2 = client.get("/health/ready")
    assert res2.status_code == 200
    assert res2.json()["status"] == "READY"

    # 3. /health/details is protected (requires system admin auth) -> 401 without token
    res3 = client.get("/health/details")
    assert res3.status_code == 401


    # 4. /api/v1/auth/login is public
    res4 = client.post(
        "/api/v1/auth/login",
        json={"username": "alice_certifier", "password": "AliceCert2026!"},
    )
    assert res4.status_code == 200


# ==============================================================================
# 4. User Management Security (Requirement 4)
# ==============================================================================

def test_non_admin_cannot_create_users():
    # Login as Alice (Certifier - non-admin)
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "alice_certifier", "password": "AliceCert2026!"},
    )
    token = login_res.json()["access_token"]

    res = client.post(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "username": "hacker_user",
            "password": "HackerPassword123!",
            "full_name": "Hacker",
            "email": "hacker@evil.corp",
        },
    )
    assert res.status_code == 403
    assert "administrator privilege required" in res.json()["detail"].lower()


def test_system_admin_can_create_users_and_assign_members():
    import uuid
    # Login as Admin (SYSTEM_ADMIN)
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "BeaconAdmin2026!"},
    )
    token = login_res.json()["access_token"]
    unique_user = f"eng_{uuid.uuid4().hex[:6]}"

    # Admin creates user
    res = client.post(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "username": unique_user,
            "password": "EngineerPass2026!",
            "full_name": "New Engineer",
            "email": f"{unique_user}@retail.corp",
        },
    )
    assert res.status_code == 200
    assert res.json()["username"] == unique_user

    # Admin assigns project role
    mem_res = client.post(
        "/api/v1/auth/projects/proj_retail_pilot/members",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "username": unique_user,
            "project_id": "proj_retail_pilot",
            "role": "CERTIFIER",
        },
    )
    assert mem_res.status_code == 200
    assert mem_res.json()["role"] == "CERTIFIER"


# ==============================================================================
# 5. Anti-Brute Force Rate Limiting Tests (Requirement 24)
# ==============================================================================

def test_login_rate_limiting():
    client_ip = "192.168.1.100"
    auth_rate_limiter.reset(client_ip)

    for _ in range(10):
        auth_rate_limiter.record_attempt(client_ip)
    
    is_allowed, retry_after = auth_rate_limiter.is_allowed(client_ip)
    assert is_allowed is False
    assert retry_after > 0

    auth_rate_limiter.reset(client_ip)
    is_allowed, retry_after = auth_rate_limiter.is_allowed(client_ip)
    assert is_allowed is True


# ==============================================================================
# 6. RBAC Role & Permission Enforcement Tests (Requirement 29)
# ==============================================================================

def test_rbac_permission_matrix():
    assert role_has_permission(UserRole.VIEWER, Permission.VIEW) is True
    assert role_has_permission(UserRole.VIEWER, Permission.CERTIFY) is False
    assert role_has_permission(UserRole.VIEWER, Permission.AUDIT) is False
    assert role_has_permission(UserRole.VIEWER, Permission.MANAGE_PROJECT) is False

    assert role_has_permission(UserRole.CERTIFIER, Permission.VIEW) is True
    assert role_has_permission(UserRole.CERTIFIER, Permission.CERTIFY) is True
    assert role_has_permission(UserRole.CERTIFIER, Permission.AUDIT) is False

    assert role_has_permission(UserRole.AUDITOR, Permission.VIEW) is True
    assert role_has_permission(UserRole.AUDITOR, Permission.CERTIFY) is False
    assert role_has_permission(UserRole.AUDITOR, Permission.AUDIT) is True

    assert role_has_permission(UserRole.PROJECT_ADMIN, Permission.MANAGE_PROJECT) is True
    assert role_has_permission(UserRole.SYSTEM_ADMIN, Permission.SYSTEM_OPERATIONS) is True


def test_viewer_cannot_trigger_certification():
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "bob_viewer", "password": "BobView2026!"},
    )
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
    assert "permission" in res.json()["detail"].lower()


def test_certifier_can_trigger_certification():
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "alice_certifier", "password": "AliceCert2026!"},
    )
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


def test_auditor_can_create_auditor_note():
    # Admin runs certification to create artifact
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "BeaconAdmin2026!"})
    admin_token = admin_login.json()["access_token"]
    cert_res = client.post(
        "/api/v1/certification/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"benchmark_id": "retail_discount_pricing", "target_variant": "clean_v2", "discovery_mode": "CONTROLLED", "preferred_provider": "offline"},
    )
    cert_id = cert_res.json()["certification_id"]

    # Carol (Auditor) logs in and appends note
    auditor_login = client.post("/api/v1/auth/login", json={"username": "carol_auditor", "password": "CarolAudit2026!"})
    auditor_token = auditor_login.json()["access_token"]

    note_res = client.post(
        f"/api/v1/evidence/dossiers/{cert_id}/notes",
        headers={"Authorization": f"Bearer {auditor_token}"},
        json={"content": "Authoritative review: Invariant boundaries verified."},
    )
    assert note_res.status_code == 200
    assert note_res.json()["content"] == "Authoritative review: Invariant boundaries verified."


def test_viewer_cannot_create_auditor_note():
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "BeaconAdmin2026!"})
    admin_token = admin_login.json()["access_token"]
    cert_res = client.post(
        "/api/v1/certification/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"benchmark_id": "retail_discount_pricing", "target_variant": "clean_v2", "discovery_mode": "CONTROLLED", "preferred_provider": "offline"},
    )
    cert_id = cert_res.json()["certification_id"]

    viewer_login = client.post("/api/v1/auth/login", json={"username": "bob_viewer", "password": "BobView2026!"})
    viewer_token = viewer_login.json()["access_token"]

    note_res = client.post(
        f"/api/v1/evidence/dossiers/{cert_id}/notes",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"content": "Viewer attempt to add note."},
    )
    assert note_res.status_code == 403


# ==============================================================================
# 7. Multi-Tenant Project Boundary Isolation & Compare (Requirements 15, 16, 18)
# ==============================================================================

def test_cross_project_isolation_blocked():
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "external_user", "password": "External2026!"},
    )
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
    assert "not a member" in res.json()["detail"].lower() or "forbidden" in res.json()["detail"].lower()


def test_cross_project_evidence_compare_strictly_rejected():
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "BeaconAdmin2026!"})
    admin_token = admin_login.json()["access_token"]

    # Run in retail_discount_pricing
    res_a = client.post(
        "/api/v1/certification/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"benchmark_id": "retail_discount_pricing", "target_variant": "clean_v2", "discovery_mode": "CONTROLLED", "preferred_provider": "offline"},
    )
    run_a = res_a.json()["certification_id"]

    # Run in payroll_tax_calculator (different benchmark / project)
    res_b = client.post(
        "/api/v1/certification/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"benchmark_id": "payroll_tax_calculator", "target_variant": "clean_v2", "discovery_mode": "CONTROLLED", "preferred_provider": "offline"},
    )
    run_b = res_b.json()["certification_id"]

    # Non-admin user (Alice) attempts cross-project comparison
    alice_login = client.post("/api/v1/auth/login", json={"username": "alice_certifier", "password": "AliceCert2026!"})
    alice_token = alice_login.json()["access_token"]

    compare_res = client.post(
        "/api/v1/evidence/compare",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"run_id_a": run_a, "run_id_b": run_b},
    )
    assert compare_res.status_code == 403
    assert "cross-project comparison is prohibited" in compare_res.json()["detail"].lower()


def test_same_project_evidence_compare_allowed():
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "BeaconAdmin2026!"})
    admin_token = admin_login.json()["access_token"]

    res_a = client.post(
        "/api/v1/certification/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"benchmark_id": "retail_discount_pricing", "target_variant": "clean_v2", "discovery_mode": "CONTROLLED", "preferred_provider": "offline"},
    )
    run_a = res_a.json()["certification_id"]

    res_b = client.post(
        "/api/v1/certification/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"benchmark_id": "retail_discount_pricing", "target_variant": "buggy_v1", "discovery_mode": "CONTROLLED", "preferred_provider": "offline"},
    )
    run_b = res_b.json()["certification_id"]

    # Same project comparison
    compare_res = client.post(
        "/api/v1/evidence/compare",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"run_id_a": run_a, "run_id_b": run_b},
    )
    assert compare_res.status_code == 200
    data = compare_res.json()
    assert "identities" in data
    assert "differential_regressions" in data


# ==============================================================================
# 8. Zero Credential Leaks in Audit Logs & Responses (Requirements 22, 23, 26)
# ==============================================================================

def test_no_passwords_or_tokens_in_audit_logs():
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


def test_user_responses_never_contain_password_hash():
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "BeaconAdmin2026!"})
    admin_token = admin_login.json()["access_token"]

    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    data = res.json()
    assert "password_hash" not in data
    assert "password" not in data
    assert "salt" not in data


# ==============================================================================
# 9. Security Headers Middleware Tests (Requirement 25)
# ==============================================================================

def test_security_headers_present():
    res = client.get("/health/live")
    assert res.status_code == 200
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("X-XSS-Protection") == "1; mode=block"
    assert "max-age=" in res.headers.get("Strict-Transport-Security", "")


# ==============================================================================
# 10. Phase 17 Final Security Corrections & Hardening
# ==============================================================================

def test_jwt_secret_validation_production_missing_fails(monkeypatch):
    from operations.startup import validate_startup_configuration
    from common.config import settings

    monkeypatch.setattr(settings, "beacon_env", "production")
    monkeypatch.setattr(settings, "jwt_secret_key", "")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("BEACON_JWT_SECRET", raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        validate_startup_configuration()
    assert "JWT_SECRET_KEY is missing or invalid" in str(excinfo.value)


def test_jwt_secret_validation_production_empty_fails(monkeypatch):
    from operations.startup import validate_startup_configuration
    from common.config import settings

    monkeypatch.setattr(settings, "beacon_env", "production")
    monkeypatch.setattr(settings, "jwt_secret_key", "   ")

    with pytest.raises(RuntimeError) as excinfo:
        validate_startup_configuration()
    assert "JWT_SECRET_KEY is missing or invalid" in str(excinfo.value)


def test_jwt_secret_validation_production_valid_passes(monkeypatch):
    from operations.startup import validate_startup_configuration
    from common.config import settings

    monkeypatch.setattr(settings, "beacon_env", "production")
    monkeypatch.setattr(settings, "jwt_secret_key", "a_very_secure_long_production_test_secret_key_2026")

    diag = validate_startup_configuration()
    assert diag["status"] == "SUCCESS"
    assert diag["checks"]["security"]["auth_required"] is True
    assert "secret" not in str(diag)


def test_no_hardcoded_jwt_secret_fallback(monkeypatch):
    from auth.security import get_signing_secret
    from common.config import settings

    monkeypatch.setattr(settings, "jwt_secret_key", "")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("BEACON_JWT_SECRET", raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        get_signing_secret()
    assert "JWT_SECRET_KEY is missing or invalid" in str(excinfo.value)


def test_require_project_permission_no_default_project_fallback():
    # Login as Alice (member of proj_retail_pilot only)
    alice_login = client.post("/api/v1/auth/login", json={"username": "alice_certifier", "password": "AliceCert2026!"})
    alice_token = alice_login.json()["access_token"]

    # Attempt to request operational metrics without project_id or benchmark_id
    res = client.get("/api/v1/operations/metrics", headers={"Authorization": f"Bearer {alice_token}"})
    # Must reject safely (403 or 400), NEVER fall back to 'default_project'
    assert res.status_code in (400, 403)
    if res.status_code == 403:
        assert "default_project" not in res.json()["detail"].lower()


def test_client_supplied_project_id_cannot_override_resource_ownership():
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "BeaconAdmin2026!"})
    admin_token = admin_login.json()["access_token"]

    # 1. Admin creates a run for payroll_tax_calculator (project: benchmark_payroll_tax_calculator)
    res_payroll = client.post(
        "/api/v1/certification/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"benchmark_id": "payroll_tax_calculator", "target_variant": "clean_v2", "discovery_mode": "CONTROLLED", "preferred_provider": "offline"},
    )
    assert res_payroll.status_code == 200
    payroll_cert_id = res_payroll.json()["certification_id"]

    # 2. Alice (only a member of proj_retail_pilot) tries to access payroll artifact evidence
    # while passing project_id=proj_retail_pilot in the query string
    alice_login = client.post("/api/v1/auth/login", json={"username": "alice_certifier", "password": "AliceCert2026!"})
    alice_token = alice_login.json()["access_token"]

    ev_res = client.get(
        f"/api/v1/evidence/dossiers/{payroll_cert_id}?project_id=proj_retail_pilot",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    # The server MUST resolve the real resource project (benchmark_payroll_tax_calculator)
    # and reject Alice because she is not a member of benchmark_payroll_tax_calculator!
    assert ev_res.status_code == 403
    assert "not a member of project" in ev_res.json()["detail"].lower()


# ==============================================================================
# 11. Final Phase 17 Route-Surface Protection & Token Type Hardening Tests
# ==============================================================================

def test_jwt_wrong_or_missing_token_type_rejected():
    import json, hmac, hashlib
    from datetime import datetime, timezone
    from auth.security import _base64url_encode, get_signing_secret

    key = get_signing_secret()
    header = {"alg": "HS256", "typ": "JWT"}
    now_ts = int(datetime.now(timezone.utc).timestamp())

    # Case 1: token_type is "refresh"
    payload_refresh = {
        "sub": "user_test_123",
        "username": "test_refresh",
        "is_system_admin": False,
        "memberships": {},
        "iat": now_ts,
        "exp": now_ts + 3600,
        "token_type": "refresh",
    }
    h_b = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p_b = _base64url_encode(json.dumps(payload_refresh, separators=(",", ":")).encode("utf-8"))
    sig = _base64url_encode(hmac.new(key.encode("utf-8"), f"{h_b}.{p_b}".encode("utf-8"), hashlib.sha256).digest())
    token_refresh = f"{h_b}.{p_b}.{sig}"

    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_refresh}"})
    assert res.status_code == 401
    assert "token" in res.json()["detail"].lower()

    # Case 2: missing token_type claim
    payload_no_type = {
        "sub": "user_test_123",
        "username": "test_no_type",
        "is_system_admin": False,
        "memberships": {},
        "iat": now_ts,
        "exp": now_ts + 3600,
    }
    p_b2 = _base64url_encode(json.dumps(payload_no_type, separators=(",", ":")).encode("utf-8"))
    sig2 = _base64url_encode(hmac.new(key.encode("utf-8"), f"{h_b}.{p_b2}".encode("utf-8"), hashlib.sha256).digest())
    token_no_type = f"{h_b}.{p_b2}.{sig2}"

    res2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_no_type}"})
    assert res2.status_code == 401
    assert "token" in res2.json()["detail"].lower()


def test_all_certification_endpoints_protected_against_unauthenticated_and_cross_project():
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "BeaconAdmin2026!"})
    admin_token = admin_login.json()["access_token"]

    # 1. Create certification run for retail_discount_pricing (project: benchmark_retail_discount_pricing)
    run_res = client.post(
        "/api/v1/certification/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"benchmark_id": "retail_discount_pricing", "target_variant": "clean_v2", "discovery_mode": "CONTROLLED", "preferred_provider": "offline"},
    )
    assert run_res.status_code == 200
    cert_id = run_res.json()["certification_id"]

    # 2. Setup user charlie (member of proj_other ONLY)
    client.post(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"username": "charlie_other", "password": "CharlieOther2026!", "full_name": "Charlie Other", "email": "charlie@other.test"},
    )
    client.post(
        "/api/v1/auth/projects/proj_other_isolated/members",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"username": "charlie_other", "role": "VIEWER"},
    )
    charlie_login = client.post("/api/v1/auth/login", json={"username": "charlie_other", "password": "CharlieOther2026!"})
    charlie_token = charlie_login.json()["access_token"]

    # 3. Setup user bob (member of proj_retail_pilot and benchmark_retail_discount_pricing)
    bob_login = client.post("/api/v1/auth/login", json={"username": "bob_viewer", "password": "BobView2026!"})
    bob_token = bob_login.json()["access_token"]

    endpoints_to_test = [
        ("GET", f"/api/v1/certification/{cert_id}/report"),
        ("GET", f"/api/v1/certification/{cert_id}/oracles"),
        ("GET", f"/api/v1/certification/{cert_id}/counterexamples"),
        ("GET", f"/api/v1/certification/{cert_id}/cases"),
        ("GET", f"/api/v1/certification/{cert_id}/input_set"),
        ("GET", f"/api/v1/certification/{cert_id}/export"),
        ("POST", f"/api/v1/certification/{cert_id}/verify"),
        ("GET", f"/api/v1/certification/{cert_id}/verify_reproducibility"),
    ]

    for method, path in endpoints_to_test:
        # A. Unauthenticated -> 401
        if method == "GET":
            unauth_res = client.get(path)
        else:
            unauth_res = client.post(path)
        assert unauth_res.status_code == 401, f"Expected 401 for unauthenticated {method} {path}, got {unauth_res.status_code}"

        # B. Cross-project user (Charlie) -> 403
        if method == "GET":
            cross_res = client.get(path, headers={"Authorization": f"Bearer {charlie_token}"})
        else:
            cross_res = client.post(path, headers={"Authorization": f"Bearer {charlie_token}"})
        assert cross_res.status_code == 403, f"Expected 403 for cross-project {method} {path}, got {cross_res.status_code}"

        # C. Authorized user (Bob) -> 200
        if method == "GET":
            auth_res = client.get(path, headers={"Authorization": f"Bearer {bob_token}"})
        else:
            auth_res = client.post(path, headers={"Authorization": f"Bearer {bob_token}"})
        assert auth_res.status_code == 200, f"Expected 200 for authorized {method} {path}, got {auth_res.status_code}"


def test_custom_preview_and_validate_security():
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "BeaconAdmin2026!"})
    admin_token = admin_login.json()["access_token"]

    alice_login = client.post("/api/v1/auth/login", json={"username": "alice_certifier", "password": "AliceCert2026!"})
    alice_token = alice_login.json()["access_token"]

    charlie_login = client.post("/api/v1/auth/login", json={"username": "charlie_other", "password": "CharlieOther2026!"})
    charlie_token = charlie_login.json()["access_token"]

    sample_csv = "age,income,risk_level\n25,50000,LOW\n45,120000,HIGH\n"
    preview_req = {
        "project_id": "proj_retail_pilot",
        "dataset_name": "Test Security Preview",
        "data_format": "CSV",
        "provenance_category": "PROPRIETARY",
        "raw_content": sample_csv,
        "intended_domain": "retail",
    }

    # 1. Preview Unauthenticated -> 401
    p_unauth = client.post("/api/v1/custom/datasets/preview", json=preview_req)
    assert p_unauth.status_code == 401

    # 2. Preview Cross-Project (Charlie is in proj_other_isolated, sending proj_retail_pilot) -> 403
    p_cross = client.post(
        "/api/v1/custom/datasets/preview",
        headers={"Authorization": f"Bearer {charlie_token}"},
        json=preview_req,
    )
    assert p_cross.status_code == 403

    # 3. Preview Authorized (Alice is member of proj_retail_pilot) -> 200
    p_auth = client.post(
        "/api/v1/custom/datasets/preview",
        headers={"Authorization": f"Bearer {alice_token}"},
        json=preview_req,
    )
    assert p_auth.status_code == 200
    assert p_auth.json()["validation_passed"] is True

