"""Phase 12 — Real-World / Public Legacy Application Integration Test Suite.

Verifies:
- Benchmark discovery, metadata schemas, and provenance taxonomy.
- Deterministic dataset loading and SHA-256 checksum verification.
- Clean modernization equivalence certification across multiple external domains.
- Controlled bug detection with concrete, persisted counterexample cases.
- Engine isolation (zero domain-specific imports in CertificationEngine).
- Phase 11 complete case persistence and input-set hash reconstruction for benchmarks.
"""

from pathlib import Path
import sys
import pytest

# Ensure backend and benchmark root are in path
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(ROOT_DIR / "legacy_sample"))

from benchmarks.models import ProvenanceCategory
from benchmarks.registry import benchmark_registry
from benchmarks.dataset_loader import load_dataset_file, compute_file_checksum
from certification import (
    CertificationEngine,
    CertificationPolicy,
    CertificationStatus,
    certification_engine,
    certification_repository,
    verify_input_set_integrity,
)


def test_benchmark_discovery_and_registry():
    """Verifies that all benchmarks (built-in and external) are discovered."""
    benchmarks = benchmark_registry.list_benchmarks()
    ids = [b.benchmark_id for b in benchmarks]
    
    assert "loan_demo" in ids
    assert "medical_triage" in ids
    assert "retail_discount_pricing" in ids
    assert "payroll_tax_calculator" in ids


def test_benchmark_metadata_provenance_and_schema():
    """Verifies provenance categories, licenses, and schema structures."""
    retail = benchmark_registry.get_benchmark("retail_discount_pricing")
    assert retail is not None
    assert retail.provenance_category == ProvenanceCategory.REALISTIC
    assert retail.license == "Apache-2.0"
    assert "order_amount" in retail.input_schema
    assert "final_price" in retail.output_schema
    assert "clean_v2" in retail.modernized_adapters
    assert "buggy_threshold_v2" in retail.modernized_adapters

    payroll = benchmark_registry.get_benchmark("payroll_tax_calculator")
    assert payroll is not None
    assert payroll.provenance_category == ProvenanceCategory.PUBLIC
    assert payroll.license == "MIT"
    assert "gross_salary" in payroll.input_schema
    assert "federal_tax" in payroll.output_schema


def test_dataset_checksum_and_deterministic_loader():
    """Verifies dataset SHA-256 computation and deterministic input creation."""
    retail_spec = benchmark_registry.get_benchmark("retail_discount_pricing")
    dataset_file = ROOT_DIR / "benchmarks" / "retail_discount_pricing" / "dataset" / "validation.json"
    
    inputs, checksum = load_dataset_file(dataset_file, retail_spec.input_schema, benchmark_id="retail_discount_pricing")
    
    assert len(checksum) == 64
    assert len(inputs) == 5
    assert inputs[0].input_id.startswith("INP-RETAIL-000")
    assert inputs[0].values["order_amount"] == 550.0
    assert inputs[0].values["customer_tier"] == "VIP"


def test_benchmark_preflight_validation():
    """Verifies pre-flight validation of adapters, schemas, and datasets."""
    retail_val = benchmark_registry.validate_benchmark("retail_discount_pricing")
    assert retail_val.is_valid is True
    assert retail_val.legacy_adapter_status == "OK"
    assert retail_val.dataset_record_count > 0
    assert len(retail_val.errors) == 0

    payroll_val = benchmark_registry.validate_benchmark("payroll_tax_calculator")
    assert payroll_val.is_valid is True
    assert payroll_val.legacy_adapter_status == "OK"
    assert payroll_val.dataset_record_count > 0
    assert len(payroll_val.errors) == 0


def test_retail_pricing_clean_modernization_certified():
    """Verifies that clean modernized retail pricing engine achieves CERTIFIED status."""
    oracle_set = benchmark_registry.get_or_create_oracle_set("retail_discount_pricing")
    legacy_adp = benchmark_registry.get_legacy_adapter("retail_discount_pricing")
    modern_adp = benchmark_registry.get_modernized_adapter("retail_discount_pricing", variant="clean_v2")
    test_inputs = benchmark_registry.get_input_dataset("retail_discount_pricing", dataset_name="default")

    artifact = certification_engine.certify(
        project_id="test_retail_clean",
        legacy_adapter=legacy_adp,
        modern_adapter=modern_adp,
        oracle_set=oracle_set,
        test_inputs=test_inputs,
    )

    assert artifact.status == CertificationStatus.CERTIFIED
    assert artifact.score >= 0.95
    assert artifact.metrics.modern_regressions == 0
    assert artifact.reproducibility_state == "FULLY_REPRODUCIBLE"


def test_retail_pricing_buggy_threshold_regression_counterexample():
    """Verifies that mutated VIP threshold in retail pricing is detected with concrete counterexamples."""
    oracle_set = benchmark_registry.get_or_create_oracle_set("retail_discount_pricing")
    legacy_adp = benchmark_registry.get_legacy_adapter("retail_discount_pricing")
    modern_adp = benchmark_registry.get_modernized_adapter("retail_discount_pricing", variant="buggy_threshold_v2")
    test_inputs = benchmark_registry.get_input_dataset("retail_discount_pricing", dataset_name="default")

    artifact = certification_engine.certify(
        project_id="test_retail_buggy_threshold",
        legacy_adapter=legacy_adp,
        modern_adapter=modern_adp,
        oracle_set=oracle_set,
        test_inputs=test_inputs,
    )

    assert artifact.status == CertificationStatus.NOT_CERTIFIED
    assert artifact.metrics.modern_regressions > 0

    # Check that a counterexample was captured
    vip_summary = next(s for s in artifact.oracle_summaries if "customer_tier == 'VIP'" in s.condition_str)
    assert vip_summary.oracle_status in ("REGRESSION", "FAIL")
    assert len(vip_summary.counterexamples) > 0

    # Verify counterexample payload
    ce = vip_summary.counterexamples[0]
    assert ce.input_values["customer_tier"] == "VIP"
    legacy_val = float(ce.legacy_output["discount_applied_pct"]) if isinstance(ce.legacy_output, dict) else float(ce.legacy_output)
    modern_val = float(ce.modern_output["discount_applied_pct"]) if isinstance(ce.modern_output, dict) else float(ce.modern_output)
    assert legacy_val >= 0.20
    assert modern_val < 0.20


def test_payroll_clean_modernization_certified():
    """Verifies that clean modernized progressive payroll engine achieves CERTIFIED status."""
    oracle_set = benchmark_registry.get_or_create_oracle_set("payroll_tax_calculator")
    legacy_adp = benchmark_registry.get_legacy_adapter("payroll_tax_calculator")
    modern_adp = benchmark_registry.get_modernized_adapter("payroll_tax_calculator", variant="clean_v2")
    test_inputs = benchmark_registry.get_input_dataset("payroll_tax_calculator", dataset_name="default")

    artifact = certification_engine.certify(
        project_id="test_payroll_clean",
        legacy_adapter=legacy_adp,
        modern_adapter=modern_adp,
        oracle_set=oracle_set,
        test_inputs=test_inputs,
    )

    assert artifact.status == CertificationStatus.CERTIFIED
    assert artifact.score >= 0.95
    assert artifact.metrics.modern_regressions == 0


def test_benchmark_isolation_zero_domain_logic_in_engine():
    """Verifies that CertificationEngine has no domain-specific imports."""
    engine_file = BACKEND_DIR / "certification" / "certification_engine.py"
    content = engine_file.read_text(encoding="utf-8")

    assert "retail_pricing" not in content
    assert "payroll_calculator" not in content
    assert "loan_approval" not in content
    assert "medical_triage" not in content


def test_benchmark_phase11_case_persistence_and_hash_integrity():
    """Verifies that benchmark certification runs are persisted with 100% case-level reproducibility."""
    oracle_set = benchmark_registry.get_or_create_oracle_set("payroll_tax_calculator")
    legacy_adp = benchmark_registry.get_legacy_adapter("payroll_tax_calculator")
    modern_adp = benchmark_registry.get_modernized_adapter("payroll_tax_calculator", variant="clean_v2")
    test_inputs = benchmark_registry.get_input_dataset("payroll_tax_calculator", dataset_name="validation")

    artifact = certification_engine.certify(
        project_id="test_payroll_persistence",
        legacy_adapter=legacy_adp,
        modern_adapter=modern_adp,
        oracle_set=oracle_set,
        test_inputs=test_inputs,
    )

    assert artifact.reproducibility_state == "FULLY_REPRODUCIBLE"
    assert artifact.metrics.total_inputs == len(test_inputs) * len(oracle_set.oracles)

    # Verify input-set reconstruction from persisted cases
    is_valid = certification_repository.verify_input_set_integrity(artifact.input_set_id, artifact.certification_id)
    assert is_valid is True

    cases = certification_repository.list_certification_cases(artifact.certification_id)
    assert len(cases) == len(test_inputs)


def test_payroll_buggy_bracket_regression_counterexample():
    """Verifies that mutated top bracket in payroll engine is detected."""
    oracle_set = benchmark_registry.get_or_create_oracle_set("payroll_tax_calculator")
    legacy_adp = benchmark_registry.get_legacy_adapter("payroll_tax_calculator")
    modern_adp = benchmark_registry.get_modernized_adapter("payroll_tax_calculator", variant="buggy_bracket_v2")
    test_inputs = benchmark_registry.get_input_dataset("payroll_tax_calculator", dataset_name="default")

    artifact = certification_engine.certify(
        project_id="test_payroll_buggy_bracket",
        legacy_adapter=legacy_adp,
        modern_adapter=modern_adp,
        oracle_set=oracle_set,
        test_inputs=test_inputs,
    )

    assert artifact.status == CertificationStatus.NOT_CERTIFIED
    assert artifact.metrics.modern_regressions > 0


def test_payroll_buggy_deduction_regression_counterexample():
    """Verifies that mutated dependent allowance in payroll engine is detected."""
    oracle_set = benchmark_registry.get_or_create_oracle_set("payroll_tax_calculator")
    legacy_adp = benchmark_registry.get_legacy_adapter("payroll_tax_calculator")
    modern_adp = benchmark_registry.get_modernized_adapter("payroll_tax_calculator", variant="buggy_deduction_v2")
    test_inputs = benchmark_registry.get_input_dataset("payroll_tax_calculator", dataset_name="default")

    artifact = certification_engine.certify(
        project_id="test_payroll_buggy_deduction",
        legacy_adapter=legacy_adp,
        modern_adapter=modern_adp,
        oracle_set=oracle_set,
        test_inputs=test_inputs,
    )

    assert artifact.status == CertificationStatus.NOT_CERTIFIED
    assert artifact.metrics.modern_regressions > 0


def test_benchmark_api_endpoints():
    """Verifies the Phase 12 FastAPI benchmark and certification endpoints."""
    from fastapi.testclient import TestClient
    from api.main import app

    client = TestClient(app)

    # 1. GET /api/v1/benchmarks
    res = client.get("/api/v1/benchmarks")
    assert res.status_code == 200
    data = res.json()
    b_ids = [b["benchmark_id"] for b in data["benchmarks"]]
    assert "retail_discount_pricing" in b_ids
    assert "payroll_tax_calculator" in b_ids

    # 2. GET /api/v1/benchmarks/{id}
    res_spec = client.get("/api/v1/benchmarks/retail_discount_pricing")
    assert res_spec.status_code == 200
    spec_data = res_spec.json()
    assert spec_data["provenance_category"] == "REALISTIC"

    # 3. POST /api/v1/benchmarks/{id}/validate
    res_val = client.post("/api/v1/benchmarks/retail_discount_pricing/validate")
    assert res_val.status_code == 200
    val_data = res_val.json()
    assert val_data["is_valid"] is True
    assert val_data["dataset_record_count"] > 0

    # 4. POST /api/v1/certification/run with benchmark_id (clean)
    res_cert_clean = client.post(
        "/api/v1/certification/run",
        json={"benchmark_id": "retail_discount_pricing", "benchmark_variant": "clean_v2"},
    )
    assert res_cert_clean.status_code == 200
    clean_art = res_cert_clean.json()
    assert clean_art["certified"] is True
    assert clean_art["status"] == "CERTIFIED"

    # 5. POST /api/v1/certification/run with benchmark_id (buggy)
    res_cert_buggy = client.post(
        "/api/v1/certification/run",
        json={"benchmark_id": "retail_discount_pricing", "benchmark_variant": "buggy_threshold_v2"},
    )
    assert res_cert_buggy.status_code == 200
    buggy_art = res_cert_buggy.json()
    assert buggy_art["certified"] is False
    assert buggy_art["status"] == "NOT_CERTIFIED"
    assert buggy_art["metrics"]["modern_regressions"] > 0

