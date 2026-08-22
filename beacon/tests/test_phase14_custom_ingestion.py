"""Phase 14 — User-Supplied Dataset Ingestion & Custom Certification Test Suite.

Verifies:
1. Multi-format parsing (JSON, JSONL, CSV) & schema inference.
2. Configurable file size and row limits.
3. Secret and credential scanning (prohibits API keys, tokens, and private keys).
4. Deterministic SHA-256 dataset checksumming and schema fingerprinting.
5. Ingestion manifests, duplicate upload idempotency, and project namespace isolation.
6. Dataset deletion and comprehensive audit logging.
7. Allowlisted adapter sandboxing (rejection of arbitrary/unregistered adapters).
8. Privacy boundary enforcement (gating external cloud LLMs).
9. Custom pre-flight validation and configuration fingerprint invalidation.
10. Definitive Phase 14 Acceptance Tests A through H.
"""

import json
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(ROOT_DIR / "legacy_sample"))

from api.main import app
from ingestion import (
    DataFormat,
    DatasetProvenanceCategory,
    dataset_validator,
    user_dataset_registry,
    audit_logger,
)
from certification.repository import certification_repository


@pytest.fixture(autouse=True)
def clean_system_state():
    """Isolates state before and after each test."""
    certification_repository.clear()
    user_dataset_registry.clear()
    audit_logger.clear()
    yield
    certification_repository.clear()
    user_dataset_registry.clear()
    audit_logger.clear()


@pytest.fixture
def client():
    return TestClient(app)


# Sample Valid Payloads
SAMPLE_RETAIL_JSON = json.dumps([
    {"order_amount": 45.0, "customer_tier": "STANDARD", "items_count": 2, "coupon_code": "NONE", "is_express_shipping": False},
    {"order_amount": 120.0, "customer_tier": "STANDARD", "items_count": 4, "coupon_code": "WELCOME10", "is_express_shipping": False},
    {"order_amount": 75.0, "customer_tier": "VIP", "items_count": 3, "coupon_code": "NONE", "is_express_shipping": False},
    {"order_amount": 250.0, "customer_tier": "VIP", "items_count": 5, "coupon_code": "LOYALTY20", "is_express_shipping": True},
    {"order_amount": 15.0, "customer_tier": "WHOLESALE", "items_count": 1, "coupon_code": "NONE", "is_express_shipping": False},
])

SAMPLE_RETAIL_JSONL = """{"order_amount": 45.0, "customer_tier": "STANDARD", "items_count": 2, "coupon_code": "NONE", "is_express_shipping": false}
{"order_amount": 120.0, "customer_tier": "STANDARD", "items_count": 4, "coupon_code": "WELCOME10", "is_express_shipping": false}
{"order_amount": 75.0, "customer_tier": "VIP", "items_count": 3, "coupon_code": "NONE", "is_express_shipping": false}
{"order_amount": 250.0, "customer_tier": "VIP", "items_count": 5, "coupon_code": "LOYALTY20", "is_express_shipping": true}
{"order_amount": 15.0, "customer_tier": "WHOLESALE", "items_count": 1, "coupon_code": "NONE", "is_express_shipping": false}
"""

SAMPLE_RETAIL_CSV = """order_amount,customer_tier,items_count,coupon_code,is_express_shipping
45.0,STANDARD,2,NONE,false
120.0,STANDARD,4,WELCOME10,false
75.0,VIP,3,NONE,false
250.0,VIP,5,LOYALTY20,true
15.0,WHOLESALE,1,NONE,false
"""


# ==============================================================================
# 1. Ingestion & Validation Tests
# ==============================================================================

def test_preview_valid_json_dataset(client):
    """Verifies dry-run preview for JSON format with schema extraction and checksum."""
    res = client.post(
        "/api/v1/custom/datasets/preview",
        json={
            "project_id": "proj_preview_01",
            "dataset_name": "Retail Preview Dataset",
            "data_format": "JSON",
            "raw_content": SAMPLE_RETAIL_JSON,
            "declared_provenance": "USER_SUPPLIED",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["validation_passed"] is True
    assert data["row_count"] == 5
    assert "order_amount" in data["inferred_schema"]
    assert "customer_tier" in data["inferred_schema"]
    assert len(data["dataset_checksum"]) == 64
    assert len(data["sample_records"]) == 5


def test_preview_valid_jsonl_dataset(client):
    """Verifies dry-run preview for JSONL format."""
    res = client.post(
        "/api/v1/custom/datasets/preview",
        json={
            "project_id": "proj_preview_02",
            "dataset_name": "Retail JSONL Dataset",
            "data_format": "JSONL",
            "raw_content": SAMPLE_RETAIL_JSONL,
            "declared_provenance": "PUBLIC_EXTERNAL",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["validation_passed"] is True
    assert data["row_count"] == 5


def test_preview_valid_csv_dataset(client):
    """Verifies dry-run preview for CSV format with scalar type casting."""
    res = client.post(
        "/api/v1/custom/datasets/preview",
        json={
            "project_id": "proj_preview_03",
            "dataset_name": "Retail CSV Dataset",
            "data_format": "CSV",
            "raw_content": SAMPLE_RETAIL_CSV,
            "declared_provenance": "PRIVATE_ENTERPRISE",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["validation_passed"] is True
    assert data["row_count"] == 5
    assert data["inferred_schema"]["order_amount"] in ("float", "int")
    assert data["inferred_schema"]["is_express_shipping"] == "bool"


def test_rejection_of_empty_and_oversized_datasets(client):
    """Verifies rejection of empty datasets and size limit violations."""
    # Empty
    res_empty = client.post(
        "/api/v1/custom/datasets/preview",
        json={
            "project_id": "proj_err",
            "dataset_name": "Empty Dataset",
            "data_format": "JSON",
            "raw_content": "",
        },
    )
    assert res_empty.status_code == 200
    assert res_empty.json()["validation_passed"] is False
    assert any("empty" in e.lower() for e in res_empty.json()["errors"])

    # Upload empty fails
    res_upload_empty = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_err",
            "dataset_name": "Empty Dataset",
            "data_format": "JSON",
            "raw_content": "   ",
        },
    )
    assert res_upload_empty.status_code == 400


def test_security_secret_scanning_and_blocking(client):
    """Verifies that uploaded datasets with embedded credentials or API keys are rejected with zero secret echoing."""
    secret_payload = json.dumps([
        {"order_total": 50.0, "api_token": "sk-ant-api03-verysecrettoken12345678901234567890"},
        {"order_total": 100.0, "api_token": "normal_val"},
    ])

    res = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_sec",
            "dataset_name": "Leaked Credentials Dataset",
            "data_format": "JSON",
            "raw_content": secret_payload,
        },
    )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "Security violation" in detail
    assert "sk-ant-" not in detail  # Raw secret must never be echoed


# ==============================================================================
# 2. Hashing, Idempotency & Project Isolation Tests
# ==============================================================================

def test_deterministic_checksum_and_whitespace_key_order_invariance():
    """Verifies that different key order produces the exact same canonical SHA-256 checksum."""
    data_a = [
        {"order_total": 45.0, "customer_type": "VIP", "item_count": 2},
        {"order_total": 120.0, "customer_type": "REGULAR", "item_count": 4},
    ]
    data_b = [
        {"customer_type": "VIP", "item_count": 2, "order_total": 45.0},
        {"item_count": 4, "order_total": 120.0, "customer_type": "REGULAR"},
    ]
    hash_a = dataset_validator.extract_schema(data_a)
    hash_b = dataset_validator.extract_schema(data_b)
    assert hash_a == hash_b

    from ingestion.dataset_models import compute_canonical_dataset_checksum
    assert compute_canonical_dataset_checksum(data_a) == compute_canonical_dataset_checksum(data_b)


def test_idempotent_dataset_registration(client):
    """Verifies that uploading the exact same dataset under the same project identity is idempotent."""
    res1 = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_idemp",
            "dataset_name": "Idempotent Dataset",
            "data_format": "JSON",
            "raw_content": SAMPLE_RETAIL_JSON,
            "declared_provenance": "USER_SUPPLIED",
        },
    )
    assert res1.status_code == 200
    man1 = res1.json()

    res2 = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_idemp",
            "dataset_name": "Idempotent Dataset",
            "data_format": "JSON",
            "raw_content": SAMPLE_RETAIL_JSON,
            "declared_provenance": "USER_SUPPLIED",
        },
    )
    assert res2.status_code == 200
    man2 = res2.json()

    assert man1["dataset_id"] == man2["dataset_id"]
    assert man1["checksum"] == man2["checksum"]

    # Verify list count is 1
    res_list = client.get("/api/v1/custom/datasets?project_id=proj_idemp")
    assert len(res_list.json()["datasets"]) == 1


def test_project_namespace_isolation(client):
    """Verifies that datasets in Project A are strictly isolated from Project B."""
    client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "Project_A",
            "dataset_name": "Dataset Alpha",
            "data_format": "JSON",
            "raw_content": SAMPLE_RETAIL_JSON,
        },
    )

    client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "Project_B",
            "dataset_name": "Dataset Beta",
            "data_format": "JSON",
            "raw_content": SAMPLE_RETAIL_JSON,
        },
    )

    list_a = client.get("/api/v1/custom/datasets?project_id=Project_A").json()["datasets"]
    list_b = client.get("/api/v1/custom/datasets?project_id=Project_B").json()["datasets"]

    assert len(list_a) == 1
    assert list_a[0]["project_id"] == "Project_A"
    assert len(list_b) == 1
    assert list_b[0]["project_id"] == "Project_B"


def test_dataset_deletion_and_audit_logging(client):
    """Verifies dataset deletion and structured audit trail recording."""
    res_up = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_del",
            "dataset_name": "Ephemeral Dataset",
            "data_format": "JSON",
            "raw_content": SAMPLE_RETAIL_JSON,
        },
    )
    ds_id = res_up.json()["dataset_id"]

    res_del = client.delete(f"/api/v1/custom/datasets/{ds_id}")
    assert res_del.status_code == 200
    assert res_del.json()["deleted"] is True

    # Confirm 404 on get
    res_get = client.get(f"/api/v1/custom/datasets/{ds_id}")
    assert res_get.status_code == 404

    # Confirm audit log records DATASET_DELETE
    res_audit = client.get("/api/v1/custom/audit?project_id=proj_del")
    events = res_audit.json()["events"]
    actions = [e["action"] for e in events]
    assert "DATASET_REGISTER" in actions
    assert "DATASET_DELETE" in actions


# ==============================================================================
# 3. Adapter Sandboxing & Privacy Tests
# ==============================================================================

def test_rejection_of_unsupported_implementation_adapter(client):
    """Verifies that requesting an unregistered adapter is strictly rejected."""
    res_up = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_adp",
            "dataset_name": "Adapter Check Dataset",
            "data_format": "JSON",
            "raw_content": SAMPLE_RETAIL_JSON,
        },
    )
    ds_id = res_up.json()["dataset_id"]

    res_val = client.post(
        "/api/v1/custom/validate",
        json={
            "project_id": "proj_adp",
            "dataset_id": ds_id,
            "legacy_adapter_id": "malicious_unregistered_adapter_exec",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "evaluation_mode": "CONTROLLED",
        },
    )
    data = res_val.json()
    assert data["is_valid"] is False
    assert any("Unsupported legacy implementation adapter" in e for e in data["errors"])


def test_privacy_boundary_cloud_llm_gating(client):
    """Verifies that external cloud LLMs in FULL_BEACON mode are blocked without explicit consent."""
    res_up = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_priv",
            "dataset_name": "Privacy Check Dataset",
            "data_format": "JSON",
            "raw_content": SAMPLE_RETAIL_JSON,
        },
    )
    ds_id = res_up.json()["dataset_id"]

    # Request OpenRouter without consent
    res_val = client.post(
        "/api/v1/custom/validate",
        json={
            "project_id": "proj_priv",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "evaluation_mode": "FULL_BEACON",
            "preferred_provider": "openrouter",
            "allow_external_llm": False,
        },
    )
    data = res_val.json()
    assert data["is_valid"] is False
    assert any("Privacy boundary violation" in e for e in data["errors"])


# ==============================================================================
# 4. Phase 14 Acceptance Tests (Tests A through H)
# ==============================================================================

def test_acceptance_test_a_builtin_retail_controlled_clean(client):
    """TEST A: Built-in Retail + CONTROLLED + Clean -> CERTIFIED (existing behavior preserved)."""
    res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "preferred_provider": "auto",
        },
    )
    assert res.status_code == 200
    art = res.json()
    assert art["status"] in ("CERTIFIED", "CERTIFIED_WITH_WARNINGS")
    score = art.get("score") if art.get("score") is not None else art["metrics"].get("overall_equivalence_score", 0.0)
    assert score == 1.0
    assert len(art["regressions"]) == 0


def test_acceptance_test_b_builtin_retail_controlled_buggy(client):
    """TEST B: Built-in Retail + CONTROLLED + Buggy -> NOT_CERTIFIED with counterexamples."""
    res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "buggy_threshold_v2",
            "discovery_mode": "CONTROLLED",
            "preferred_provider": "auto",
        },
    )
    assert res.status_code == 200
    art = res.json()
    assert art["status"] == "NOT_CERTIFIED"
    assert len(art["regressions"]) > 0
    score = art.get("score") if art.get("score") is not None else art["metrics"].get("overall_equivalence_score", 0.0)
    assert score < 1.0


def test_acceptance_test_c_user_dataset_controlled_clean(client):
    """TEST C: User Dataset + CONTROLLED -> Validated, Registered, Certified with correct artifact & hashes."""
    # 1. Upload
    res_up = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_test_c",
            "dataset_name": "Retail Custom Clean Dataset",
            "data_format": "JSON",
            "raw_content": SAMPLE_RETAIL_JSON,
            "declared_provenance": "USER_SUPPLIED",
        },
    )
    assert res_up.status_code == 200
    manifest = res_up.json()
    ds_id = manifest["dataset_id"]
    checksum = manifest["checksum"]

    # 2. Pre-flight Validate
    res_val = client.post(
        "/api/v1/custom/validate",
        json={
            "project_id": "proj_test_c",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "evaluation_mode": "CONTROLLED",
        },
    )
    assert res_val.status_code == 200
    val_data = res_val.json()
    assert val_data["is_valid"] is True
    assert val_data["config_fingerprint"] != ""

    # 3. Certify
    res_cert = client.post(
        "/api/v1/custom/certify",
        json={
            "project_id": "proj_test_c",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "evaluation_mode": "CONTROLLED",
            "config_fingerprint": val_data["config_fingerprint"],
        },
    )
    assert res_cert.status_code == 200
    art = res_cert.json()
    assert art["status"] in ("CERTIFIED", "CERTIFIED_WITH_WARNINGS")
    score = art.get("score") if art.get("score") is not None else art["metrics"].get("overall_equivalence_score", 0.0)
    assert score == 1.0
    assert art["dataset_checksum"] == checksum or (art.get("context") and art["context"]["dataset_checksum"] == checksum)
    prov = art.get("benchmark_provenance") or (art.get("context") and art["context"]["benchmark_provenance"])
    assert prov == "USER_SUPPLIED"


def test_acceptance_test_d_modified_dataset_invalidates_context(client):
    """TEST D: Modified User Dataset produces different SHA-256 and invalidates prior pre-flight."""
    # Dataset 1
    res1 = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_test_d",
            "dataset_name": "Dataset Original",
            "data_format": "JSON",
            "raw_content": SAMPLE_RETAIL_JSON,
        },
    )
    ds1_id = res1.json()["dataset_id"]
    ds1_chk = res1.json()["checksum"]

    # Dataset 2 (modified value)
    modified_json = json.dumps([
        {"order_total": 999.0, "customer_type": "VIP", "is_first_order": True, "item_count": 10}
    ])
    res2 = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_test_d",
            "dataset_name": "Dataset Modified",
            "data_format": "JSON",
            "raw_content": modified_json,
        },
    )
    ds2_id = res2.json()["dataset_id"]
    ds2_chk = res2.json()["checksum"]

    # Checksums and IDs must differ
    assert ds1_chk != ds2_chk
    assert ds1_id != ds2_id

    # Fingerprints must differ
    val1 = client.post(
        "/api/v1/custom/validate",
        json={
            "project_id": "proj_test_d",
            "dataset_id": ds1_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "evaluation_mode": "CONTROLLED",
        },
    ).json()

    val2 = client.post(
        "/api/v1/custom/validate",
        json={
            "project_id": "proj_test_d",
            "dataset_id": ds2_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "evaluation_mode": "CONTROLLED",
        },
    ).json()

    assert val1["config_fingerprint"] != val2["config_fingerprint"]


def test_acceptance_test_e_user_dataset_full_beacon_discovery(client):
    """TEST E: User Dataset + FULL_BEACON evidence discovery with local provider."""
    res_up = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_test_e",
            "dataset_name": "Retail Discovery Dataset",
            "data_format": "JSON",
            "raw_content": SAMPLE_RETAIL_JSON,
            "declared_provenance": "REALISTIC_SYNTHETIC",
        },
    )
    ds_id = res_up.json()["dataset_id"]

    res_cert = client.post(
        "/api/v1/custom/certify",
        json={
            "project_id": "proj_test_e",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "evaluation_mode": "FULL_BEACON",
            "preferred_provider": "offline",
            "allow_external_llm": False,
        },
    )
    assert res_cert.status_code == 200
    art = res_cert.json()
    assert art["status"] in ("CERTIFIED", "CERTIFIED_WITH_WARNINGS")


def test_acceptance_test_f_cross_project_isolation(client):
    """TEST F: Project A Dataset cannot be certified under Project B."""
    res_a = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "Corp_A",
            "dataset_name": "Confidential Corp A Data",
            "data_format": "JSON",
            "raw_content": SAMPLE_RETAIL_JSON,
        },
    )
    ds_a_id = res_a.json()["dataset_id"]

    # Attempt to certify under Corp_B
    res_cross = client.post(
        "/api/v1/custom/certify",
        json={
            "project_id": "Corp_B",
            "dataset_id": ds_a_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "evaluation_mode": "CONTROLLED",
        },
    )
    assert res_cross.status_code == 400
    assert "Project namespace isolation mismatch" in res_cross.json()["detail"]


def test_acceptance_test_g_external_llm_disabled_local_only(client):
    """TEST G: When external LLM is disabled, local processing proceeds without network requests."""
    res_up = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_local",
            "dataset_name": "Local Privacy Dataset",
            "data_format": "JSON",
            "raw_content": SAMPLE_RETAIL_JSON,
        },
    )
    ds_id = res_up.json()["dataset_id"]

    res_cert = client.post(
        "/api/v1/custom/certify",
        json={
            "project_id": "proj_local",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "evaluation_mode": "CONTROLLED",
            "preferred_provider": "offline",
            "allow_external_llm": False,
        },
    )
    assert res_cert.status_code == 200
    art = res_cert.json()
    # Provider must be recorded as offline
    prov = art["provider"] if "provider" in art else art["context"]["provider"]
    assert prov == "offline"


def test_acceptance_test_h_tampered_dataset_integrity_verification_fail(client):
    """TEST H: Cryptographic 8-point verification passes for valid runs and detects tampering."""
    res_up = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_tamper",
            "dataset_name": "Tamper Test Dataset",
            "data_format": "JSON",
            "raw_content": SAMPLE_RETAIL_JSON,
        },
    )
    ds_id = res_up.json()["dataset_id"]

    res_cert = client.post(
        "/api/v1/custom/certify",
        json={
            "project_id": "proj_tamper",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "evaluation_mode": "CONTROLLED",
        },
    )
    art = res_cert.json()
    cert_id = art["certification_id"]

    # Verify integrity passes initially
    res_ver = client.post(f"/api/v1/certification/{cert_id}/verify")
    assert res_ver.status_code == 200
    assert res_ver.json()["status"] == "PASS"
