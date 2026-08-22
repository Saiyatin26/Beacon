"""Phase 13 — Production-Grade Certification Workflow & UI Verification Test Suite.

Validates the complete 9-step production workflow:
1. Step 1: Benchmark Selection & Specification Retrieval
2. Step 2: Dataset Specifications & Truthful Provenance
3. Step 3: Evaluation Mode Selection (CONTROLLED vs FULL_BEACON)
4. Step 4: Provider Hierarchy Configuration
5. Step 5: Target Variant Selection (Clean vs Buggy)
6. Step 6: Pre-Flight Validation (dataset & adapter checks)
7. Step 7: Certification Execution & Duplicate Protection
8. Step 8: Authoritative Result Presentation (CERTIFIED / NOT_CERTIFIED)
9. Step 9: Evidence Drill-Down, Case Explorer, Cryptographic Verification & Exports
10. Tab 2: Benchmark-Aware Certification History Isolation
11. Tab 5: Isolated Legacy Loan Demo Sandbox
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

    # Medical & Loan Benchmarks
    medical = next((b for b in benchmarks if b["benchmark_id"] == "medical_triage"), None)
    assert medical is not None
    assert medical["provenance_category"] == "CONTROLLED"


def test_step6_preflight_validation(client):
    """Verifies Step 6: Pre-flight validation on valid and invalid benchmark configurations."""
    # 1. Valid Benchmark
    res_valid = client.post("/api/v1/benchmarks/retail_discount_pricing/validate")
    assert res_valid.status_code == 200
    val_data = res_valid.json()
    assert val_data["is_valid"] is True
    assert val_data["dataset_record_count"] > 0
    assert val_data["legacy_adapter_status"] in ("VALID", "OK", "UNKNOWN")
    assert len(val_data["errors"]) == 0

    # 2. Invalid / Nonexistent Benchmark
    res_invalid = client.post("/api/v1/benchmarks/nonexistent_project_xyz/validate")
    assert res_invalid.status_code == 404 or (res_invalid.status_code == 200 and not res_invalid.json().get("is_valid"))


def test_step7_and_8_retail_clean_certified_workflow(client):
    """Verifies Step 7 & 8: Retail Clean variant produces CERTIFIED with 100% equivalence and 0 regressions."""
    res_run = client.post("/api/v1/certification/run", json={
        "benchmark_id": "retail_discount_pricing",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
        "preferred_provider": "auto",
    })
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
    res_run = client.post("/api/v1/certification/run", json={
        "benchmark_id": "retail_discount_pricing",
        "benchmark_variant": "buggy_threshold_v2",
        "discovery_mode": "CONTROLLED",
        "preferred_provider": "auto",
    })
    assert res_run.status_code == 200
    art = res_run.json()

    assert art["status"] == "NOT_CERTIFIED"
    assert art["metrics"]["regression_case_count"] > 0
    assert len(art["regressions"]) > 0
    # Verify counterexamples contain required fields
    for reg in art["regressions"]:
        assert reg["input_id"] != ""
        assert reg["input_values"] is not None
        assert reg["legacy_output"] != reg["modern_output"]
        assert reg["oracle_id"] != ""


def test_step9_per_oracle_breakdown_and_counterexamples(client):
    """Verifies Step 9: Per-Oracle drill-down summaries and counterexamples endpoints."""
    res_run = client.post("/api/v1/certification/run", json={
        "benchmark_id": "payroll_tax_calculator",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
    })
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
    res_run = client.post("/api/v1/certification/run", json={
        "benchmark_id": "retail_discount_pricing",
        "benchmark_variant": "buggy_operator_v2",
        "discovery_mode": "CONTROLLED",
    })
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
    res_run = client.post("/api/v1/certification/run", json={
        "benchmark_id": "retail_discount_pricing",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
    })
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
    res_run = client.post("/api/v1/certification/run", json={
        "benchmark_id": "payroll_tax_calculator",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
    })
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
    client.post("/api/v1/certification/run", json={
        "benchmark_id": "retail_discount_pricing",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
    })
    # Run Medical
    client.post("/api/v1/certification/run", json={
        "benchmark_id": "medical_triage",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
    })

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
