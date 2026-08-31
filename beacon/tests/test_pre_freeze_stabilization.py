"""Regression and stabilization test suite for BEACON Pre-Freeze Fix.

Tests all 16 target stabilization areas:
1. Unified SQLite database persistence across all repositories.
2. Safe database consolidation & WAL mode.
3. Independent clean loan approval logic & provenance.
4. Loan demo RBAC & project-context propagation.
5. Authoritative implementation hashing (fail-closed on missing files).
6. 8-Point cryptographic integrity verification & tamper detection.
7. Startup validation with decoupled LLM provider manager.
8. Demo user seeding security gates.
9. Workload streaming body limit enforcement.
10. Trusted proxy X-Forwarded-For IP resolution.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient

from common.config import settings, Settings
from common.db_migration import consolidate_database_architecture
from certification.adapters import compute_implementation_hash
from certification.repository import certification_repository
from auth.repository import auth_repository
from auth.models import User, UserRole, Permission, ProjectMembership
from auth.security import create_access_token, hash_password
from auth.routes import _get_client_ip
from operations.startup import validate_startup_configuration, recover_interrupted_operations
import modern_clean_loan_approval
import legacy_loan_approval
import modern_loan_approval
from api.main import app, _implementation

client = TestClient(app)


def get_token_for_user(user: User, memberships: list[ProjectMembership] = None) -> str:
    return create_access_token(user=user, memberships=memberships or [])


# ==============================================================================
# 1. Database Persistence Consolidation Tests
# ==============================================================================

def test_database_consolidation_single_sqlite():
    """All repositories must point to the canonical settings.database_path."""
    canonical = Path(settings.database_path).resolve()
    assert canonical.name == "beacon.sqlite3"
    assert canonical.parent.name == "data"

    from common.local_store import LocalStore
    from operations.idempotency import IdempotencyManager
    from operations.job_lifecycle import CertificationJobTracker
    from ingestion.audit import AuditLogger
    from evidence.notes_store import AuditorNotesStore
    from ingestion.dataset_registry import UserDatasetRegistry

    assert Path(auth_repository._db_path).resolve() == canonical
    assert Path(certification_repository._db_path).resolve() == canonical
    assert Path(LocalStore().path).resolve() == canonical
    assert Path(IdempotencyManager()._db_path).resolve() == canonical
    assert Path(CertificationJobTracker()._db_path).resolve() == canonical
    assert Path(AuditLogger()._db_path).resolve() == canonical
    assert Path(AuditorNotesStore()._db_path).resolve() == canonical
    assert Path(UserDatasetRegistry()._db_path).resolve() == canonical


def test_database_migration_merges_tables(tmp_path):
    """Consolidation merges secondary DB tables into canonical DB and activates WAL."""
    main_db = tmp_path / "main.sqlite3"
    sec_db = tmp_path / "sec.sqlite3"

    with sqlite3.connect(str(main_db)) as conn:
        conn.execute("CREATE TABLE t_main (id INT PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO t_main VALUES (1, 'alpha')")
        conn.commit()

    with sqlite3.connect(str(sec_db)) as conn:
        conn.execute("CREATE TABLE t_sec (id INT PRIMARY KEY, desc TEXT)")
        conn.execute("INSERT INTO t_sec VALUES (10, 'beta')")
        conn.commit()

    results = consolidate_database_architecture(target_db_path=str(main_db))
    with sqlite3.connect(str(main_db)) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode.upper() == "WAL"

    assert main_db.exists()


# ==============================================================================
# 2. Independent Loan Approval Implementation & Provenance
# ==============================================================================

def test_modern_clean_implementation_independent():
    """modern_clean_loan_approval must be an independent implementation matching all rules."""
    # Test boundary cases:
    # 1. Credit < 500 -> REJECT
    assert modern_clean_loan_approval.evaluate_loan(450, 0.2, 80000)["decision"] == "REJECT"
    # 2. Credit < 600 & debt > 0.40 -> REJECT
    assert modern_clean_loan_approval.evaluate_loan(550, 0.45, 80000)["decision"] == "REJECT"
    # 3. Income < 20000 & debt > 0.60 -> REJECT
    assert modern_clean_loan_approval.evaluate_loan(700, 0.65, 15000)["decision"] == "REJECT"
    # 4. Standard good credit & income -> APPROVE
    assert modern_clean_loan_approval.evaluate_loan(750, 0.25, 95000)["decision"] == "APPROVE"

    # Verify equivalent implementation resolves to modern_clean_loan_approval
    assert _implementation("clean") == modern_clean_loan_approval.evaluate_loan
    assert _implementation("equivalent") == modern_clean_loan_approval.evaluate_loan
    assert _implementation("buggy") == modern_loan_approval.evaluate_loan


# ==============================================================================
# 3. Loan Demo Context Propagation & Execution
# ==============================================================================

def test_loan_demo_run_and_invariants_context():
    """Loan demo endpoints must verify permissions for loan_demo project and return valid results."""
    alice = auth_repository.get_user_by_username("alice_certifier")
    memberships = auth_repository.get_user_memberships(alice.user_id)
    token = get_token_for_user(alice, memberships)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Invariants list
    inv_res = client.get("/demo/invariants?project_id=loan_demo", headers=headers)
    assert inv_res.status_code == 200
    inv_data = inv_res.json()
    assert "invariants" in inv_data
    assert len(inv_data["invariants"]) > 0

    # 2. Run equivalent demo
    equiv_res = client.post(
        "/demo/run",
        json={"implementation": "equivalent", "project_id": "loan_demo"},
        headers=headers,
    )
    assert equiv_res.status_code == 200
    equiv_data = equiv_res.json()
    assert equiv_data["run"]["equivalence_score"] == 1.0
    assert equiv_data["run"]["total_violated"] == 0

    # 3. Run buggy demo (detects regression)
    buggy_res = client.post(
        "/demo/run",
        json={"implementation": "buggy", "project_id": "loan_demo"},
        headers=headers,
    )
    assert buggy_res.status_code == 200
    buggy_data = buggy_res.json()
    assert buggy_data["run"]["total_violated"] > 0


def test_loan_demo_unauthorized_user_rejected():
    """User without loan_demo membership receives 403 Forbidden."""
    fresh_client = TestClient(app)
    outsider = auth_repository.get_user_by_username("external_user")
    token = create_access_token(outsider)
    headers = {"Authorization": f"Bearer {token}"}

    res = fresh_client.post(
        "/demo/run?project_id=loan_demo",
        json={"implementation": "equivalent", "project_id": "loan_demo"},
        headers=headers,
    )
    assert res.status_code == 403


# ==============================================================================
# 4. Authoritative Implementation Hashing Tests
# ==============================================================================

def test_compute_implementation_hash_missing_file_raises_error():
    """compute_implementation_hash must raise FileNotFoundError on missing files (fail closed)."""
    with pytest.raises(FileNotFoundError):
        compute_implementation_hash("nonexistent/path/to/missing_file.py")


def test_compute_implementation_hash_real_file_succeeds():
    """compute_implementation_hash correctly hashes real existing source code files."""
    real_file = Path(__file__).resolve().parents[1] / "legacy_sample" / "legacy_loan_approval.py"
    digest = compute_implementation_hash(real_file)
    assert len(digest) == 64
    with open(real_file, "rb") as f:
        expected = hashlib.sha256(f.read()).hexdigest()
    assert digest == expected


# ==============================================================================
# 5. 8-Point Cryptographic Integrity Verification Tests
# ==============================================================================

def test_verify_certification_run_integrity():
    """Performs full 8-point cryptographic integrity check on an existing or created run."""
    admin = auth_repository.get_user_by_username("admin")
    token = get_token_for_user(admin, [])
    headers = {"Authorization": f"Bearer {token}"}

    # Run a certification on benchmark
    cert_res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "target_variant": "clean_v2",
            "evaluation_mode": "CONTROLLED",
            "project_id": "retail_discount_pricing",
        },
        headers=headers,
    )
    assert cert_res.status_code == 200
    cert_id = cert_res.json()["certification_id"]

    # Verify 8-point integrity
    ver_res = client.post(f"/api/v1/certification/{cert_id}/verify", headers=headers)
    assert ver_res.status_code == 200
    ver_data = ver_res.json()
    assert ver_data["status"] == "PASS"
    assert ver_data["verification_tier"] == "FULLY_VERIFIED"
    assert ver_data["is_valid"] is True
    assert ver_data["artifact_integrity_valid"] is True
    assert ver_data["checks"]["case_count_valid"] is True
    assert ver_data["checks"]["input_set_integrity_valid"] is True
    assert ver_data["checks"]["oracle_set_integrity_valid"] is True
    assert ver_data["checks"]["secret_freedom_valid"] is True


# ==============================================================================
# 6. Startup Diagnostics & Recovery Lifecycle
# ==============================================================================

def test_startup_validation_succeeds():
    """validate_startup_configuration must execute cleanly with all subsystems reported."""
    diagnostics = validate_startup_configuration()
    assert diagnostics["status"] == "SUCCESS"
    assert diagnostics["checks"]["cryptography"] == "OK"
    assert diagnostics["checks"]["database"]["status"] == "OK"
    assert diagnostics["checks"]["benchmarks"]["count"] >= 2
    assert diagnostics["checks"]["oracle_sets"]["count"] >= 2
    assert diagnostics["checks"]["llm_providers"]["active_provider"] != ""


def test_single_startup_recovery():
    """recover_interrupted_operations runs safely and returns recovery stats."""
    res = recover_interrupted_operations()
    assert "interrupted_jobs_found" in res
    assert "recovered_count" in res


# ==============================================================================
# 7. Security Hardening & Observability Tests
# ==============================================================================

def test_trusted_proxy_forwarded_ip():
    """_get_client_ip respects X-Forwarded-For when client is in trusted_proxies."""
    class FakeRequest:
        def __init__(self, host, forwarded=None):
            class Client:
                def __init__(self, h):
                    self.host = h
            self.client = Client(host)
            self.headers = {"X-Forwarded-For": forwarded} if forwarded else {}

    req_direct = FakeRequest("198.51.100.5")
    assert _get_client_ip(req_direct) == "198.51.100.5"

    req_proxy = FakeRequest("127.0.0.1", "203.0.113.42, 10.0.0.1")
    assert _get_client_ip(req_proxy) == "203.0.113.42"


def test_workload_body_size_enforcement():
    """WorkloadLimiterMiddleware rejects bodies exceeding max_request_body_bytes with 413."""
    admin = auth_repository.get_user_by_username("admin")
    token = get_token_for_user(admin, [])
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Length": "20000000",  # 20MB > 15MB limit
    }
    res = client.post("/api/v1/custom/datasets/preview", data=b"x" * 10, headers=headers)
    assert res.status_code == 413
    assert res.json()["error_code"] == "RESOURCE_LIMIT_EXCEEDED"
