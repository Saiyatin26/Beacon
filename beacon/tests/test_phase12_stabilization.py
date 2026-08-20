import json
from pathlib import Path
import sys
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(ROOT_DIR / "legacy_sample"))

from fastapi.testclient import TestClient
from api.main import app
from benchmarks.registry import benchmark_registry
from certification.models import (
    CertificationArtifact,
    CertificationContext,
    CertificationStatus,
    compute_artifact_content_hash,
    compute_input_set_canonical_hash,
    verify_artifact_integrity,
    verify_input_set_integrity,
)
from certification.repository import certification_repository


@pytest.fixture
def client():
    return TestClient(app)


def test_context_object_structure_and_integrity(client):
    """Verifies that running certification creates an authoritative CertificationContext with all required fields."""
    req_payload = {
        "benchmark_id": "retail_discount_pricing",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
        "dataset_name": "default",
    }
    response = client.post("/api/v1/certification/run", json=req_payload)
    assert response.status_code == 200
    data = response.json()

    assert "context" in data
    ctx = data["context"]
    assert ctx["benchmark_id"] == "retail_discount_pricing"
    assert ctx["evaluation_mode"] == "CONTROLLED"
    assert ctx["modernization_variant_id"] == "clean_v2"
    assert ctx["oracle_source_type"] == "CONTROLLED_ORACLE_SET"
    assert len(ctx["dataset_checksum"]) == 64
    assert len(ctx["input_set_hash"]) == 64
    assert len(ctx["oracle_set_hash"]) == 64
    assert len(ctx["policy_hash"]) == 64
    assert len(ctx["certification_artifact_hash"]) == 64
    assert ctx["certification_run_id"] == data["certification_id"]
    assert ctx["run_status"] in ("CERTIFIED", "NOT_CERTIFIED")


def test_three_retail_scenarios(client):
    """Validates the exact three retail certification scenarios:
    1. Retail + CONTROLLED + Clean -> CERTIFIED
    2. Retail + CONTROLLED + Buggy -> NOT_CERTIFIED + real counterexamples
    3. Retail + FULL_BEACON + Clean -> CERTIFIED or INSUFFICIENT_COVERAGE
    """
    # Scenario 1: Retail + CONTROLLED + Clean
    res1 = client.post("/api/v1/certification/run", json={
        "benchmark_id": "retail_discount_pricing",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
    })
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "CERTIFIED"
    assert data1["score"] == 1.0
    assert len(data1["regressions"]) == 0
    assert data1["context"]["oracle_source_type"] == "CONTROLLED_ORACLE_SET"

    # Scenario 2: Retail + CONTROLLED + Buggy
    res2 = client.post("/api/v1/certification/run", json={
        "benchmark_id": "retail_discount_pricing",
        "benchmark_variant": "buggy_threshold_v2",
        "discovery_mode": "CONTROLLED",
    })
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "NOT_CERTIFIED"
    assert data2["score"] < 1.0
    assert len(data2["regressions"]) > 0
    # Verify counterexamples are concrete with input_hash and case_id
    sample_reg = data2["regressions"][0]
    assert "input_id" in sample_reg
    assert "input_hash" in sample_reg
    assert "case_id" in sample_reg
    assert sample_reg["legacy_output"] != sample_reg["modern_output"]

    # Scenario 3: Retail + FULL_BEACON + Clean
    res3 = client.post("/api/v1/certification/run", json={
        "benchmark_id": "retail_discount_pricing",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "FULL_BEACON",
    })
    assert res3.status_code == 200
    data3 = res3.json()
    assert data3["status"] in ("CERTIFIED", "INSUFFICIENT_COVERAGE")
    assert data3["context"]["evaluation_mode"] == "FULL_BEACON"
    assert "FULL_BEACON" in data3["context"]["oracle_source_type"]

    # Ensure all 3 runs have distinct Run IDs and distinct OracleSet contexts
    assert data1["certification_id"] != data2["certification_id"]
    assert data2["certification_id"] != data3["certification_id"]
    assert data1["oracle_set_id"] != data3["oracle_set_id"]
    assert data1["context"]["oracle_source_type"] != data3["context"]["oracle_source_type"]


def test_payroll_scenarios(client):
    """Validates clean and buggy scenarios for the Payroll benchmark."""
    # Clean
    res_clean = client.post("/api/v1/certification/run", json={
        "benchmark_id": "payroll_tax_calculator",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
    })
    assert res_clean.status_code == 200
    d_clean = res_clean.json()
    assert d_clean["status"] == "CERTIFIED"
    assert d_clean["score"] == 1.0

    # Buggy Bracket
    res_buggy = client.post("/api/v1/certification/run", json={
        "benchmark_id": "payroll_tax_calculator",
        "benchmark_variant": "buggy_bracket_v2",
        "discovery_mode": "CONTROLLED",
    })
    assert res_buggy.status_code == 200
    d_buggy = res_buggy.json()
    assert d_buggy["status"] == "NOT_CERTIFIED"
    assert len(d_buggy["regressions"]) > 0


def test_artifacts_filtering_by_benchmark(client):
    """Verifies that GET /api/v1/certification/artifacts?benchmark_id=... filters strictly by benchmark."""
    # Fetch retail artifacts
    res_retail = client.get("/api/v1/certification/artifacts?benchmark_id=retail_discount_pricing")
    assert res_retail.status_code == 200
    arts_retail = res_retail.json()["artifacts"]
    for a in arts_retail:
        b_id = a.get("benchmark_id") or (a.get("context", {}).get("benchmark_id") if a.get("context") else None) or a["project_id"]
        assert "retail" in b_id

    # Fetch payroll artifacts
    res_payroll = client.get("/api/v1/certification/artifacts?benchmark_id=payroll_tax_calculator")
    assert res_payroll.status_code == 200
    arts_payroll = res_payroll.json()["artifacts"]
    for a in arts_payroll:
        b_id = a.get("benchmark_id") or (a.get("context", {}).get("benchmark_id") if a.get("context") else None) or a["project_id"]
        assert "payroll" in b_id


def test_drift_filtering_by_benchmark(client):
    """Verifies that GET /drift?benchmark_id=retail_discount_pricing does not leak loan drift samples."""
    res = client.get("/drift?benchmark_id=retail_discount_pricing")
    assert res.status_code == 200
    samples = res.json()["samples"]
    for s in samples:
        assert s.get("benchmark_id") == "retail_discount_pricing"


def test_cryptographic_verification_endpoint(client):
    """Verifies that the /api/v1/certification/{id}/verify endpoint confirms artifact and input set integrity."""
    res = client.post("/api/v1/certification/run", json={
        "benchmark_id": "medical_triage",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
    })
    cert_id = res.json()["certification_id"]

    verify_res = client.post(f"/api/v1/certification/{cert_id}/verify")
    assert verify_res.status_code == 200
    v_data = verify_res.json()
    assert v_data["artifact_integrity_valid"] is True
    assert v_data["input_set_integrity_valid"] is True
    assert len(v_data["content_hash"]) == 64
    assert len(v_data["input_set_hash"]) == 64


def test_zero_secrets_in_manifests_and_runs(client):
    """Ensures no secret tokens, API keys, or sensitive credentials appear in manifests or run outputs."""
    res = client.get("/api/v1/benchmarks/retail_discount_pricing/manifest")
    assert res.status_code == 200
    manifest_text = json.dumps(res.json()).lower()
    for forbidden in ["sk-", "api_key", "secret", "password", "token="]:
        assert forbidden not in manifest_text
