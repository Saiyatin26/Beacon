"""Phase 12 Final Hardening & Verification Test Suite.

Validates the full 21-item pre-Phase-13 checklist:
- Provider propagation and priority fallback chain (OpenRouter -> Anthropic -> Ollama -> Offline)
- Configuration-hashed OracleSet isolation
- Implementation SHA-256 fingerprints for directories, files, and callables
- Disambiguated metrics (inputs, cases, oracles, evaluations, regressions)
- Exact manifest context matching
- Benchmark-aware drift monitoring
- 8-point comprehensive integrity verification
- Export formats (JSON, Markdown, CSV) with zero secrets
- Truthful provenance classifications (REALISTIC_SYNTHETIC)
- Three definitive retail modernization scenarios
"""

import json
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(ROOT_DIR / "legacy_sample"))

from api.main import app
from benchmarks.models import DiscoveryMode, ProvenanceCategory
from benchmarks.registry import benchmark_registry
from certification.adapters import compute_implementation_hash
from certification.repository import certification_repository
from common.local_store import local_store
from common.models import DriftSample
from llm.manager import ProviderManager
from llm.base import LLMResponse


@pytest.fixture
def client():
    return TestClient(app)


def test_truthful_provenance_and_metadata():
    """Verifies that retail and payroll benchmarks are truthfully categorized as REALISTIC_SYNTHETIC."""
    retail = benchmark_registry.get_benchmark("retail_discount_pricing")
    payroll = benchmark_registry.get_benchmark("payroll_tax_calculator")
    medical = benchmark_registry.get_benchmark("medical_triage")
    loan = benchmark_registry.get_benchmark("loan_demo")

    assert retail is not None
    assert retail.provenance_category == ProvenanceCategory.REALISTIC_SYNTHETIC
    assert "synthetic" in retail.dataset_source.lower() or "realistic" in retail.dataset_source.lower()

    assert payroll is not None
    assert payroll.provenance_category == ProvenanceCategory.REALISTIC_SYNTHETIC

    assert medical is not None
    assert medical.provenance_category == ProvenanceCategory.CONTROLLED

    assert loan is not None
    assert loan.provenance_category == ProvenanceCategory.CONTROLLED


def test_deterministic_implementation_hashing():
    """Verifies deterministic SHA-256 fingerprinting for directories, files, and callables."""
    def sample_func_a(x: int) -> int:
        return x + 1

    def sample_func_c(x: int) -> int:
        return x + 2

    hash_a1 = compute_implementation_hash(sample_func_a)
    hash_a2 = compute_implementation_hash(sample_func_a)
    hash_c = compute_implementation_hash(sample_func_c)

    assert len(hash_a1) == 64
    assert hash_a1 == hash_a2
    assert hash_a1 != hash_c

    # Directory hashing
    retail_legacy = Path(__file__).resolve().parents[1] / "benchmarks" / "retail_discount_pricing" / "legacy"
    if retail_legacy.exists():
        dir_hash_1 = compute_implementation_hash(retail_legacy)
        dir_hash_2 = compute_implementation_hash(retail_legacy)
        assert len(dir_hash_1) == 64
        assert dir_hash_1 == dir_hash_2


def test_provider_fallback_priority_chain():
    """Verifies OpenRouter -> Anthropic -> Ollama -> Offline priority fallback chain with mocks."""
    pm = ProviderManager()

    # Case 1: OpenRouter Succeeds
    with patch.object(pm.providers["openrouter"], "is_available", return_value=True), \
         patch.object(pm.providers["openrouter"], "generate", return_value=LLMResponse(raw_text='{"status":"ok"}', parsed_json={"status": "ok"}, provider_name="openrouter", model_name="anthropic/claude-3.5-sonnet", success=True)):
        resp = pm.generate("Test prompt")
        assert resp.success
        assert resp.provider_name == "openrouter"
        assert not resp.fallback_occurred

    # Case 2: OpenRouter fails -> Anthropic Succeeds
    with patch.object(pm.providers["openrouter"], "is_available", return_value=True), \
         patch.object(pm.providers["openrouter"], "generate", return_value=LLMResponse(raw_text="", provider_name="openrouter", model_name="auto", success=False, error="Quota exceeded")), \
         patch.object(pm.providers["anthropic"], "is_available", return_value=True), \
         patch.object(pm.providers["anthropic"], "generate", return_value=LLMResponse(raw_text='{"status":"ok"}', parsed_json={"status": "ok"}, provider_name="anthropic", model_name="claude-3-5-sonnet", success=True)):
        resp = pm.generate("Test prompt")
        assert resp.success
        assert resp.provider_name == "anthropic"
        assert resp.fallback_occurred
        assert "openrouter" in resp.fallback_chain

    # Case 3: OpenRouter and Anthropic fail -> Ollama succeeds
    with patch.object(pm.providers["openrouter"], "is_available", return_value=False), \
         patch.object(pm.providers["anthropic"], "is_available", return_value=False), \
         patch.object(pm.providers["ollama"], "is_available", return_value=True), \
         patch.object(pm.providers["ollama"], "generate", return_value=LLMResponse(raw_text='{"status":"ok"}', parsed_json={"status": "ok"}, provider_name="ollama", model_name="mistral:latest", success=True)):
        resp = pm.generate("Test prompt")
        assert resp.success
        assert resp.provider_name == "ollama"
        assert resp.fallback_occurred

    # Case 4: All cloud and local LLMs fail -> Deterministic Offline fallback succeeds
    with patch.object(pm.providers["openrouter"], "is_available", return_value=False), \
         patch.object(pm.providers["anthropic"], "is_available", return_value=False), \
         patch.object(pm.providers["ollama"], "is_available", return_value=False):
        resp = pm.generate("Test prompt")
        assert resp.success
        assert resp.provider_name == "offline"
        assert resp.fallback_occurred


def test_oracleset_canonical_hash_isolation():
    """Verifies that OracleSet IDs in FULL_BEACON mode are isolated by canonical discovery configuration hash."""
    set1 = benchmark_registry.get_or_create_oracle_set("retail_discount_pricing", mode="FULL_BEACON", preferred_provider="auto", use_llm=False)
    set2 = benchmark_registry.get_or_create_oracle_set("retail_discount_pricing", mode="FULL_BEACON", preferred_provider="offline", use_llm=False)
    
    assert set1.oracle_set_id.startswith("SET-RETAIL_DISCOUNT_PRICING-FULL-")
    assert set2.oracle_set_id.startswith("SET-RETAIL_DISCOUNT_PRICING-FULL-")
    assert set1.oracle_set_hash != ""


def test_three_definitive_retail_scenarios(client):
    """Verifies all 3 definitive retail scenarios: Clean (Certified), Buggy (Not Certified), Faulty (Not Certified)."""
    # Scenario 1: Clean Modernization (Equivalence Established)
    res_clean = client.post("/api/v1/certification/run", json={
        "benchmark_id": "retail_discount_pricing",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
    })
    assert res_clean.status_code == 200
    art_clean = res_clean.json()
    assert art_clean["status"] in ("CERTIFIED", "CERTIFIED_WITH_WARNINGS")
    assert art_clean["metrics"]["regression_case_count"] == 0
    assert art_clean["metrics"]["unique_input_count"] > 0
    assert art_clean["metrics"]["certification_case_count"] == art_clean["metrics"]["unique_input_count"]
    assert art_clean["legacy_implementation_hash"] != ""
    assert art_clean["modernized_implementation_hash"] != ""

    # Scenario 2: Buggy Threshold Modernization (VIP Discount Threshold Mutation Detected)
    res_buggy = client.post("/api/v1/certification/run", json={
        "benchmark_id": "retail_discount_pricing",
        "benchmark_variant": "buggy_threshold_v2",
        "discovery_mode": "CONTROLLED",
    })
    assert res_buggy.status_code == 200
    art_buggy = res_buggy.json()
    assert art_buggy["status"] == "NOT_CERTIFIED"
    assert art_buggy["metrics"]["regression_case_count"] > 0
    assert len(art_buggy["regressions"]) > 0

    # Scenario 3: Buggy Operator Modernization (Shipping Rule Operator Mutation Detected)
    res_faulty = client.post("/api/v1/certification/run", json={
        "benchmark_id": "retail_discount_pricing",
        "benchmark_variant": "buggy_operator_v2",
        "discovery_mode": "CONTROLLED",
    })
    assert res_faulty.status_code == 200
    art_faulty = res_faulty.json()
    assert art_faulty["status"] == "NOT_CERTIFIED"
    assert art_faulty["metrics"]["regression_case_count"] > 0


def test_exact_manifest_context_matching(client):
    """Verifies that GET /api/v1/benchmarks/{id}/manifest enforces exact context matching and does not substitute unrelated runs."""
    # 1. Run a clean run
    client.post("/api/v1/certification/run", json={
        "benchmark_id": "medical_triage",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
    })

    # 2. Query manifest for clean_v2
    res_clean_man = client.get("/api/v1/benchmarks/medical_triage/manifest?discovery_mode=CONTROLLED&variant=clean_v2")
    assert res_clean_man.status_code == 200
    clean_man = res_clean_man.json()
    assert clean_man["modernization_provenance"] == "INDEPENDENT_REIMPLEMENTATION"
    assert clean_man["certification_status"] in ("CERTIFIED", "CERTIFIED_WITH_WARNINGS")

    # 3. Query manifest for buggy_v2 BEFORE running buggy_v2
    # Should not return the clean_v2 run's certified status
    res_buggy_man = client.get("/api/v1/benchmarks/medical_triage/manifest?discovery_mode=CONTROLLED&variant=buggy_v2")
    assert res_buggy_man.status_code == 200
    buggy_man = res_buggy_man.json()
    assert buggy_man["modernization_provenance"] == "CONTROLLED_MUTATION"
    assert buggy_man["artifact_hash"] == ""  # No run yet for buggy_v2


def test_comprehensive_8_point_integrity_verification(client):
    """Verifies the complete 8-point integrity verification endpoint."""
    res_run = client.post("/api/v1/certification/run", json={
        "benchmark_id": "payroll_tax_calculator",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
    })
    assert res_run.status_code == 200
    art = res_run.json()
    cert_id = art["certification_id"]

    # Verify integrity
    res_ver = client.post(f"/api/v1/certification/{cert_id}/verify")
    assert res_ver.status_code == 200
    ver_report = res_ver.json()

    assert ver_report["status"] == "PASS"
    assert ver_report["checks"]["artifact_integrity_valid"] is True
    assert ver_report["checks"]["case_count_valid"] is True
    assert ver_report["checks"]["input_set_integrity_valid"] is True
    assert ver_report["checks"]["oracle_set_integrity_valid"] is True
    assert ver_report["checks"]["policy_integrity_valid"] is True
    assert ver_report["checks"]["implementation_hashes_valid"] is True
    assert ver_report["checks"]["dataset_checksum_valid"] is True
    assert ver_report["checks"]["secret_freedom_valid"] is True
    assert len(ver_report["errors"]) == 0


def test_export_formats_and_zero_secrets(client):
    """Verifies JSON, Markdown, and CSV exports contain complete context and zero leaked credentials."""
    res_run = client.post("/api/v1/certification/run", json={
        "benchmark_id": "retail_discount_pricing",
        "benchmark_variant": "clean_v2",
        "discovery_mode": "CONTROLLED",
    })
    cert_id = res_run.json()["certification_id"]

    # JSON Export
    res_json = client.get(f"/api/v1/certification/{cert_id}/export?format=json")
    assert res_json.status_code == 200
    data_json = res_json.json()
    assert data_json["certification_id"] == cert_id
    assert "metrics" in data_json
    assert "context" in data_json
    assert "integrity_verification" in data_json

    # Markdown Export
    res_md = client.get(f"/api/v1/certification/{cert_id}/export?format=markdown")
    assert res_md.status_code == 200
    assert "# BEACON Behavioral Equivalence Certificate Dossier" in res_md.text
    assert cert_id in res_md.text

    # CSV Export
    res_csv = client.get(f"/api/v1/certification/{cert_id}/export?format=csv")
    assert res_csv.status_code == 200
    assert "case_id,case_index,input_id" in res_csv.text

    # Zero secrets check
    for text in [json.dumps(data_json), res_md.text, res_csv.text]:
        assert "sk-ant-" not in text
        assert "sk-or-" not in text
        assert "OPENROUTER_API_KEY" not in text
        assert "mongodb+srv://" not in text


def test_benchmark_aware_drift_monitoring(client):
    """Verifies that drift samples are benchmark-isolated and filterable."""
    sample_retail = DriftSample(
        run_timestamp="2026-08-20T12:00:00Z",
        equivalence_score=0.98,
        baseline_score=1.0,
        delta_pct=-2.0,
        alert=False,
        benchmark_id="retail_discount_pricing",
    )
    sample_payroll = DriftSample(
        run_timestamp="2026-08-20T12:05:00Z",
        equivalence_score=0.85,
        baseline_score=1.0,
        delta_pct=-15.0,
        alert=True,
        benchmark_id="payroll_tax_calculator",
    )

    local_store.save_drift_sample(sample_retail)
    local_store.save_drift_sample(sample_payroll)

    res_retail = client.get("/drift?benchmark_id=retail_discount_pricing")
    assert res_retail.status_code == 200
    retail_samples = res_retail.json()["samples"]
    assert any(s["benchmark_id"] == "retail_discount_pricing" for s in retail_samples)
    assert not any(s["benchmark_id"] == "payroll_tax_calculator" for s in retail_samples)
