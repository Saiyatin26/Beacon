"""Phase 13 — Production-Grade Certification Workflow, Hardening & Idempotency Test Suite.

Validates the complete hardened Phase 13 workflow:
1. Step 1 & 2: Benchmark Catalog Retrieval, Dataset Specifications & Truthful Provenance
2. Step 6: Comprehensive Pre-Flight Validation with Complete Configuration & Fingerprinting
3. Step 6: Invalidation of Validation on any Configuration Change
4. Backend Idempotency: Duplicate Identical Requests Return Completed Artifact Without Artifact Duplication
5. Backend Idempotency: Legitimately Changed Configuration Creates Distinct Runs
6. Step 7 & 8: Retail Clean Variant Produces CERTIFIED (100% Equivalence, Zero Regressions)
7. Step 7 & 8: Retail Buggy Variant Produces NOT_CERTIFIED (Pinpointed Counterexamples)
8. Step 7 & 8: Retail FULL_BEACON Clean Workflow Evaluates Oracles with Provenance
9. Step 9: Per-Oracle Breakdown, Case Explorer Filters, and Concrete Counterexamples
10. Step 9: 8-Point Cryptographic Integrity Verification & Secret Freedom
11. Step 9: Export Dossier Consistency (JSON, Markdown, CSV)
12. Tab 2: Benchmark-Aware Certification History Isolation
13. Tab 5: Isolated Legacy Loan Demo Sandbox
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
from benchmarks.models import DiscoveryMode, ProvenanceCategory
from benchmarks.registry import benchmark_registry
from certification.repository import certification_repository


@pytest.fixture(autouse=True)
def clean_state():
    certification_repository.clear()
    yield
    certification_repository.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_step1_and_2_benchmark_catalog_and_dataset_provenance(client):
    """Verifies Step 1 & 2: Benchmark catalog retrieval, dataset specifications, and truthful provenance."""
    res = client.get("/api/v1/benchmarks")
    assert res.status_code == 200
    data = res.json()
    assert "benchmarks" in data
    benchmarks = data["benchmarks"]
    assert len(benchmarks) >= 4

    # Retail Benchmark
    retail = next((b for b in benchmarks if b["benchmark_id"] == "retail_discount_pricing"), None)
    assert retail is not None
    assert retail["provenance_category"] == "REALISTIC_SYNTHETIC"
    assert retail["dataset_checksum"] != ""
    assert len(retail["dataset_checksum"]) == 64
    assert "clean_v2" in retail["modernized_adapters"]
    assert "buggy_threshold_v2" in retail["modernized_adapters"]

    # Payroll Benchmark
    payroll = next((b for b in benchmarks if b["benchmark_id"] == "payroll_tax_calculator"), None)
    assert payroll is not None
    assert payroll["provenance_category"] == "REALISTIC_SYNTHETIC"
    assert payroll["dataset_checksum"] != ""

    # Medical Benchmark
    medical = next((b for b in benchmarks if b["benchmark_id"] == "medical_triage"), None)
    assert medical is not None
    assert medical["provenance_category"] == "CONTROLLED"


def test_step6_preflight_validation_complete_configuration(client):
    """Verifies Step 6: Pre-flight validation receives complete configuration and returns config_fingerprint."""
    # 1. Valid Retail Clean in CONTROLLED mode
    res_valid = client.post(
        "/api/v1/benchmarks/retail_discount_pricing/validate",
        json={
            "benchmark_id": "retail_discount_pricing",
            "evaluation_mode": "CONTROLLED",
            "target_variant": "clean_v2",
            "preferred_provider": "auto",
            "dataset_name": "default",
        },
    )
    assert res_valid.status_code == 200
    val_data = res_valid.json()
    assert val_data["is_valid"] is True
    assert val_data["benchmark_id"] == "retail_discount_pricing"
    assert val_data["evaluation_mode"] == "CONTROLLED"
    assert val_data["target_variant"] == "clean_v2"
    assert val_data["config_fingerprint"] != ""
    assert len(val_data["config_fingerprint"]) == 64
    assert val_data["dataset_record_count"] > 0
    assert val_data["legacy_adapter_status"] == "OK"
    assert val_data["target_variant_adapter_status"] == "OK"
    assert len(val_data["errors"]) == 0

    # 2. Invalid Mode
    res_inv_mode = client.post(
        "/api/v1/benchmarks/retail_discount_pricing/validate",
        json={
            "benchmark_id": "retail_discount_pricing",
            "evaluation_mode": "INVALID_MODE_XYZ",
            "target_variant": "clean_v2",
        },
    )
    assert res_inv_mode.status_code == 200
    inv_data = res_inv_mode.json()
    assert inv_data["is_valid"] is False
    assert any("Invalid evaluation mode" in e for e in inv_data["errors"])

    # 3. Invalid Target Variant
    res_inv_var = client.post(
        "/api/v1/benchmarks/retail_discount_pricing/validate",
        json={
            "benchmark_id": "retail_discount_pricing",
            "evaluation_mode": "CONTROLLED",
            "target_variant": "nonexistent_variant_v99",
        },
    )
    assert res_inv_var.status_code == 200
    inv_var_data = res_inv_var.json()
    assert inv_var_data["is_valid"] is False
    assert any("not available" in e for e in inv_var_data["errors"])

    # 4. Nonexistent Benchmark
    res_nonexistent = client.post("/api/v1/benchmarks/nonexistent_project_123/validate")
    assert res_nonexistent.status_code == 404 or not res_nonexistent.json().get("is_valid")


def test_config_fingerprint_uniqueness(client):
    """Verifies that changing any certification configuration parameter alters the deterministic config fingerprint."""
    res1 = client.post(
        "/api/v1/benchmarks/retail_discount_pricing/validate",
        json={
            "benchmark_id": "retail_discount_pricing",
            "evaluation_mode": "CONTROLLED",
            "target_variant": "clean_v2",
            "preferred_provider": "auto",
        },
    )
    fp1 = res1.json()["config_fingerprint"]

    res2 = client.post(
        "/api/v1/benchmarks/retail_discount_pricing/validate",
        json={
            "benchmark_id": "retail_discount_pricing",
            "evaluation_mode": "FULL_BEACON",
            "target_variant": "clean_v2",
            "preferred_provider": "auto",
        },
    )
    fp2 = res2.json()["config_fingerprint"]

    res3 = client.post(
        "/api/v1/benchmarks/retail_discount_pricing/validate",
        json={
            "benchmark_id": "retail_discount_pricing",
            "evaluation_mode": "CONTROLLED",
            "target_variant": "buggy_threshold_v2",
            "preferred_provider": "auto",
        },
    )
    fp3 = res3.json()["config_fingerprint"]

    assert fp1 != fp2
    assert fp1 != fp3
    assert fp2 != fp3


def test_backend_idempotency_duplicate_request_protection(client):
    """Verifies that duplicate identical certification requests return existing completed runs without creating duplicate artifacts."""
    # First execution
    res1 = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "preferred_provider": "auto",
        },
    )
    assert res1.status_code == 200
    art1 = res1.json()
    cert_id1 = art1["certification_id"]

    # History count after first run
    res_hist1 = client.get("/api/v1/certification/artifacts?benchmark_id=retail_discount_pricing")
    count1 = len(res_hist1.json()["artifacts"])

    # Second execution with identical configuration
    res2 = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "preferred_provider": "auto",
        },
    )
    assert res2.status_code == 200
    art2 = res2.json()
    cert_id2 = art2["certification_id"]

    # Must return exact same artifact ID
    assert cert_id1 == cert_id2
    assert art1["content_hash"] == art2["content_hash"]

    # History count must not duplicate
    res_hist2 = client.get("/api/v1/certification/artifacts?benchmark_id=retail_discount_pricing")
    count2 = len(res_hist2.json()["artifacts"])
    assert count1 == count2


def test_backend_idempotency_different_idempotency_key_creates_new_run(client):
    """Verifies that submitting the same configuration with a different idempotency key creates a new run."""
    res_alpha1 = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "idempotency_key": "custom-key-alpha-123",
        },
    )
    assert res_alpha1.status_code == 200
    art_alpha1 = res_alpha1.json()
    id_alpha1 = art_alpha1["certification_id"]

    # Same idempotency key returns identical run
    res_alpha2 = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "idempotency_key": "custom-key-alpha-123",
        },
    )
    assert res_alpha2.status_code == 200
    assert res_alpha2.json()["certification_id"] == id_alpha1

    # Different idempotency key creates distinct new run
    res_beta = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "idempotency_key": "custom-key-beta-456",
        },
    )
    assert res_beta.status_code == 200
    art_beta = res_beta.json()
    assert art_beta["certification_id"] != id_alpha1


def test_backend_idempotency_force_recompute_creates_new_run(client):
    """Verifies that force_recompute=True explicitly bypasses reuse and creates a new run with is_forced_recompute recorded."""
    res_initial = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "payroll_tax_calculator",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
        },
    )
    assert res_initial.status_code == 200
    art_initial = res_initial.json()
    initial_id = art_initial["certification_id"]

    # Forced recompute
    res_forced = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "payroll_tax_calculator",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "force_recompute": True,
        },
    )
    assert res_forced.status_code == 200
    art_forced = res_forced.json()
    assert art_forced["certification_id"] != initial_id
    assert art_forced["is_forced_recompute"] is True or art_forced.get("context", {}).get("is_forced_recompute") is True


def test_backend_idempotency_changed_config_creates_distinct_run(client):
    """Verifies that legitimately changing configuration parameters creates a distinct run."""
    res_clean = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "preferred_provider": "auto",
        },
    )
    art_clean = res_clean.json()

    res_buggy = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "buggy_threshold_v2",
            "discovery_mode": "CONTROLLED",
            "preferred_provider": "auto",
        },
    )
    art_buggy = res_buggy.json()

    assert art_clean["certification_id"] != art_buggy["certification_id"]
    assert art_clean["status"] in ("CERTIFIED", "CERTIFIED_WITH_WARNINGS")
    assert art_buggy["status"] == "NOT_CERTIFIED"


def test_step7_and_8_retail_clean_certified_workflow(client):
    """Verifies Step 7 & 8: Retail Clean variant produces CERTIFIED with 100% equivalence and 0 regressions."""
    res_run = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "preferred_provider": "auto",
        },
    )
    assert res_run.status_code == 200
    art = res_run.json()

    assert art["status"] in ("CERTIFIED", "CERTIFIED_WITH_WARNINGS")
    assert art["score"] == 1.0
    assert art["metrics"]["regression_case_count"] == 0
    assert art["metrics"]["matching_case_count"] > 0
    assert art["metrics"]["unique_input_count"] > 0
    assert art["metrics"]["certification_case_count"] == art["metrics"]["unique_input_count"]
    assert len(art["regressions"]) == 0
    assert art["context"]["benchmark_id"] == "retail_discount_pricing"
    assert art["context"]["modernization_variant_id"] == "clean_v2"


def test_step7_and_8_retail_buggy_not_certified_workflow(client):
    """Verifies Step 7 & 8: Retail Buggy variant produces NOT_CERTIFIED with pinpointed counterexamples."""
    res_run = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "buggy_threshold_v2",
            "discovery_mode": "CONTROLLED",
            "preferred_provider": "auto",
            "force_recompute": True,
        },
    )
    assert res_run.status_code == 200
    art = res_run.json()

    assert art["status"] == "NOT_CERTIFIED"
    assert art["metrics"]["regression_case_count"] > 0
    assert len(art["regressions"]) > 0
    for reg in art["regressions"]:
        assert reg["input_id"] != ""
        assert reg["input_values"] is not None
        assert reg["legacy_output"] != reg["modern_output"]
        assert reg["oracle_id"] != ""


def test_step7_and_8_retail_full_beacon_clean_workflow(client):
    """Verifies Step 7 & 8: Retail in FULL_BEACON mode discovers and validates oracles with truthful provenance."""
    res_run = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "FULL_BEACON",
            "preferred_provider": "offline",
        },
    )
    assert res_run.status_code == 200
    art = res_run.json()

    assert art["context"]["evaluation_mode"] == "FULL_BEACON"
    assert art["status"] in ("CERTIFIED", "CERTIFIED_WITH_WARNINGS", "INCONCLUSIVE", "INSUFFICIENT_COVERAGE")
    assert art["oracle_source_type"] in ("FULL_BEACON_DISCOVERED", "FULL_BEACON_OFFLINE_FALLBACK")


def test_step9_per_oracle_breakdown_and_counterexamples(client):
    """Verifies Step 9: Per-Oracle drill-down summaries and counterexamples endpoints."""
    res_run = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "payroll_tax_calculator",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
        },
    )
    cert_id = res_run.json()["certification_id"]

    # Oracles summary endpoint
    res_orc = client.get(f"/api/v1/certification/{cert_id}/oracles")
    assert res_orc.status_code == 200
    orc_data = res_orc.json()
    assert "oracle_summaries" in orc_data
    assert len(orc_data["oracle_summaries"]) > 0
    for orc in orc_data["oracle_summaries"]:
        assert "oracle_id" in orc
        assert "condition_str" in orc
        assert "applicable_probes" in orc
        assert "oracle_status" in orc


def test_step9_case_explorer_filters(client):
    """Verifies Step 9: Execution Case Explorer filtering by classification."""
    res_run = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "buggy_operator_v2",
            "discovery_mode": "CONTROLLED",
        },
    )
    cert_id = res_run.json()["certification_id"]

    # 1. Filter ALL
    res_all = client.get(f"/api/v1/certification/{cert_id}/cases?classification=ALL")
    assert res_all.status_code == 200
    cases_all = res_all.json()["cases"]
    assert len(cases_all) > 0

    # 2. Filter MODERN_REGRESSION
    res_reg = client.get(f"/api/v1/certification/{cert_id}/cases?classification=MODERN_REGRESSION")
    assert res_reg.status_code == 200
    cases_reg = res_reg.json()["cases"]
    assert len(cases_reg) > 0
    for c in cases_reg:
        assert c["classification"] == "MODERN_REGRESSION"
        assert len(c["input_hash"]) in (64, 16)


def test_step9_cryptographic_verification_report(client):
    """Verifies Step 9: Cryptographic 8-point integrity report."""
    res_run = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
        },
    )
    cert_id = res_run.json()["certification_id"]

    res_ver = client.post(f"/api/v1/certification/{cert_id}/verify")
    assert res_ver.status_code == 200
    ver = res_ver.json()
    assert ver["status"] == "PASS"
    assert ver["checks"]["artifact_integrity_valid"] is True
    assert ver["checks"]["case_count_valid"] is True
    assert ver["checks"]["input_set_integrity_valid"] is True
    assert ver["checks"]["oracle_set_integrity_valid"] is True
    assert ver["checks"]["policy_integrity_valid"] is True
    assert ver["checks"]["implementation_hashes_valid"] is True
    assert ver["checks"]["dataset_checksum_valid"] is True
    assert ver["checks"]["secret_freedom_valid"] is True


def test_step9_export_dossier_consistency(client):
    """Verifies Step 9: Export dossier alignment across JSON, Markdown, and CSV."""
    res_run = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "payroll_tax_calculator",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
        },
    )
    cert_id = res_run.json()["certification_id"]

    # JSON export
    res_json = client.get(f"/api/v1/certification/{cert_id}/export?format=json")
    assert res_json.status_code == 200
    json_dossier = res_json.json()
    assert json_dossier["certification_id"] == cert_id
    assert json_dossier["benchmark_id"] == "payroll_tax_calculator"

    # Markdown export
    res_md = client.get(f"/api/v1/certification/{cert_id}/export?format=markdown")
    assert res_md.status_code == 200
    assert cert_id in res_md.text

    # CSV export
    res_csv = client.get(f"/api/v1/certification/{cert_id}/export?format=csv")
    assert res_csv.status_code == 200
    assert "case_id" in res_csv.text


def test_tab2_certification_history_benchmark_filtering(client):
    """Verifies Tab 2: Historical artifacts are benchmark-aware and isolated."""
    # Run Retail
    client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
        },
    )
    # Run Medical
    client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "medical_triage",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
        },
    )

    # Query Retail history
    res_ret = client.get("/api/v1/certification/artifacts?benchmark_id=retail_discount_pricing")
    assert res_ret.status_code == 200
    ret_arts = res_ret.json()["artifacts"]
    assert all(a.get("benchmark_id") == "retail_discount_pricing" or a.get("project_id") == "benchmark_retail_discount_pricing" for a in ret_arts)
    assert not any(a.get("benchmark_id") == "medical_triage" for a in ret_arts)

    # Query Medical history
    res_med = client.get("/api/v1/certification/artifacts?benchmark_id=medical_triage")
    assert res_med.status_code == 200
    med_arts = res_med.json()["artifacts"]
    assert all(a.get("benchmark_id") == "medical_triage" or a.get("project_id") == "benchmark_medical_triage" for a in med_arts)


def test_tab5_legacy_loan_demo_isolation(client):
    """Verifies Tab 5: Legacy Loan Demo sandbox operates cleanly and remains isolated."""
    res_eq = client.post("/demo/run", json={"implementation": "equivalent"})
    assert res_eq.status_code == 200
    data_eq = res_eq.json()
    assert data_eq["run"]["equivalence_score"] >= 0.80
    assert data_eq["run"]["total_violated"] == 0

    res_buggy = client.post("/demo/run", json={"implementation": "buggy"})
    assert res_buggy.status_code == 200
    data_buggy = res_buggy.json()
    assert data_buggy["run"]["total_violated"] > 0
