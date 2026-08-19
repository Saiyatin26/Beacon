"""Comprehensive Test Suite for Phase 9 — Oracle Execution and Cross-Version Behavioral Equivalence.

Tests:
1. Equivalent Modernization achieves 100% equivalence, MATCH outcomes, and certified=True
2. Deliberate Modernization Regression pinpointed to exact oracle, input, and counterexample
3. Reference Inconsistency (Legacy violates Oracle) blocks certification (certified=False) and prevents 100% score
4. Mutual Violation (Both violate Oracle) blocks certification (certified=False) and prevents 100% score
5. Output Normalization handling (casing/whitespace) without losing raw outputs
6. Execution Exception handling and error reporting
7. Deterministic Input Replay and identical hash reproducibility
8. Multi-Oracle Frozen OracleSet certification and domain breakdown
9. OracleSet immutability and historical version reproducibility
10. Generic Non-Loan domain execution with pure generic adapters
11. Zero LLM dependency during certification
"""

import sys
from pathlib import Path
import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

from certification import (
    BehavioralRegression,
    CrossVersionCertificationEngine,
    CrossVersionCertificationReport,
    FunctionAdapter,
    LegacyAdapter,
    ModernizedAdapter,
    certify,
    generate_certification_test_suite,
)
from common.models import CandidateInvariant
from oracle import (
    OracleDefinition,
    OracleRegistry,
    compile_candidate_to_oracle,
)


def _make_oracle(
    condition: str,
    consequence: str,
    invariant_id: str,
    severity: str = "critical",
    domain: str = "loan_approval",
) -> OracleDefinition:
    cand = CandidateInvariant(
        invariant_id=invariant_id,
        condition=condition,
        raw_condition=condition,
        consequence=consequence,
        source_file="legacy_loan_approval.py",
        source_lines=[14],
        severity=severity,
        domain=domain,
        confidence=0.95,
        status="graduated",
    )
    return compile_candidate_to_oracle(cand)


FIELD_BOUNDS = {
    "credit_score": (400, 800),
    "debt_ratio": (0.1, 0.8),
    "annual_income": (20000, 100000),
}


# ==============================================================================
# 1. Equivalent Implementation Certification (100% Pass, MATCH Outcomes)
# ==============================================================================

def test_equivalent_modernization_certification():
    # Both legacy and modern implement the rule correctly
    def legacy_fn(credit_score=0, debt_ratio=0.0, annual_income=0):
        if credit_score < 600 and debt_ratio > 0.4:
            return {"decision": "REJECT"}
        return {"decision": "APPROVE"}

    def modern_fn(credit_score=0, debt_ratio=0.0, annual_income=0):
        if credit_score < 600 and debt_ratio > 0.4:
            return {"decision": "REJECT"}
        return {"decision": "APPROVE"}

    oracle = _make_oracle("credit_score < 600 and debt_ratio > 0.4", "REJECT", "INV-001")
    engine = CrossVersionCertificationEngine()

    report: CrossVersionCertificationReport = engine.certify_equivalence(
        oracles=[oracle],
        legacy_adapter=LegacyAdapter(legacy_fn),
        modern_adapter=ModernizedAdapter(modern_fn),
        field_bounds=FIELD_BOUNDS,
        n_samples=50,
    )

    assert report.overall_equivalence_score == 1.0
    assert report.total_regressions == 0
    assert report.total_reference_inconsistencies == 0
    assert report.total_mutual_violations == 0
    assert report.total_matching_probes > 0
    assert len(report.regressions) == 0
    assert report.certified is True
    assert report.oracle_metrics[oracle.oracle_id].matching_probes > 0
    assert report.oracle_metrics[oracle.oracle_id].oracle_equivalence_rate == 1.0


# ==============================================================================
# 2. Deliberate Modernization Regression Pinpointing
# ==============================================================================

def test_modernization_regression_pinpointed():
    # Legacy rejects credit_score < 600 and debt_ratio > 0.4
    def legacy_fn(credit_score=0, debt_ratio=0.0, annual_income=0):
        if credit_score < 600 and debt_ratio > 0.4:
            return {"decision": "REJECT"}
        return {"decision": "APPROVE"}

    # Modern has a bug: only rejects when credit_score < 500 (approves 500-599 with high debt)
    def buggy_modern_fn(credit_score=0, debt_ratio=0.0, annual_income=0):
        if credit_score < 500:
            return {"decision": "REJECT"}
        return {"decision": "APPROVE"}

    oracle = _make_oracle("credit_score < 600 and debt_ratio > 0.4", "REJECT", "INV-001")
    engine = CrossVersionCertificationEngine()

    report: CrossVersionCertificationReport = engine.certify_equivalence(
        oracles=[oracle],
        legacy_adapter=LegacyAdapter(legacy_fn),
        modern_adapter=ModernizedAdapter(buggy_modern_fn),
        field_bounds=FIELD_BOUNDS,
        n_samples=50,
    )

    assert report.total_regressions > 0
    assert report.overall_equivalence_score < 1.0
    assert report.certified is False

    # Check regression counterexample details
    reg: BehavioralRegression = report.regressions[0]
    assert reg.oracle_id == oracle.oracle_id
    assert reg.expected_behavior == "REJECT"
    assert reg.legacy_output == "REJECT"
    assert reg.modern_output == "APPROVE"
    assert reg.input_values["credit_score"] < 600
    assert reg.input_values["debt_ratio"] > 0.4


# ==============================================================================
# 3. Reference Inconsistency Blocks Certification and Lowers Score
# ==============================================================================

def test_reference_inconsistency_blocks_certification():
    # Legacy has a bug violating the oracle: returns APPROVE when credit_score < 500
    def buggy_legacy_fn(credit_score=0, debt_ratio=0.0, annual_income=0):
        return {"decision": "APPROVE"}

    # Modern correctly adheres to the oracle: returns REJECT when credit_score < 500
    def correct_modern_fn(credit_score=0, debt_ratio=0.0, annual_income=0):
        if credit_score < 500:
            return {"decision": "REJECT"}
        return {"decision": "APPROVE"}

    oracle = _make_oracle("credit_score < 500", "REJECT", "INV-002")
    engine = CrossVersionCertificationEngine()

    report: CrossVersionCertificationReport = engine.certify_equivalence(
        oracles=[oracle],
        legacy_adapter=LegacyAdapter(buggy_legacy_fn),
        modern_adapter=ModernizedAdapter(correct_modern_fn),
        field_bounds=FIELD_BOUNDS,
        n_samples=40,
    )

    # Reference inconsistency must prevent certified=True and lower equivalence rate
    assert report.total_regressions == 0
    assert report.total_reference_inconsistencies > 0
    assert report.certified is False
    assert report.overall_equivalence_score < 1.0
    assert len(report.reference_inconsistencies) > 0
    assert report.reference_inconsistencies[0]["oracle_id"] == oracle.oracle_id


# ==============================================================================
# 4. Mutual Violation Blocks Certification and Prevents Perfect Score
# ==============================================================================

def test_mutual_violation_blocks_certification():
    # Both legacy and modern return APPROVE on low credit score
    def legacy_fn(credit_score=0, debt_ratio=0.0, annual_income=0):
        return {"decision": "APPROVE"}

    def modern_fn(credit_score=0, debt_ratio=0.0, annual_income=0):
        return {"decision": "APPROVE"}

    oracle = _make_oracle("credit_score < 500", "REJECT", "INV-003")
    engine = CrossVersionCertificationEngine()

    report: CrossVersionCertificationReport = engine.certify_equivalence(
        oracles=[oracle],
        legacy_adapter=LegacyAdapter(legacy_fn),
        modern_adapter=ModernizedAdapter(modern_fn),
        field_bounds=FIELD_BOUNDS,
        n_samples=30,
    )

    m = report.oracle_metrics[oracle.oracle_id]
    assert m.mutual_violations > 0
    assert report.total_mutual_violations > 0
    assert report.certified is False
    assert report.overall_equivalence_score < 1.0


# ==============================================================================
# 5. Output Normalization Preserving Raw Outputs
# ==============================================================================

def test_output_normalization_with_raw_preservation():
    # Legacy outputs uppercase {"decision": "REJECT"}, modern outputs lowercase {"decision": "reject"}
    def legacy_fn(credit_score=0, debt_ratio=0.0, annual_income=0):
        return {"decision": "REJECT"}

    def modern_fn(credit_score=0, debt_ratio=0.0, annual_income=0):
        return {"decision": "reject"}

    oracle = _make_oracle("credit_score < 500", "REJECT", "INV-004")
    engine = CrossVersionCertificationEngine()

    report: CrossVersionCertificationReport = engine.certify_equivalence(
        oracles=[oracle],
        legacy_adapter=LegacyAdapter(legacy_fn),
        modern_adapter=ModernizedAdapter(modern_fn),
        field_bounds=FIELD_BOUNDS,
        n_samples=20,
    )

    # Output normalizer maps 'reject' -> 'REJECT', so it matches without false alarms
    assert report.total_regressions == 0

    # Ensure raw output values are preserved in observation records
    comp = report.comparison_records[0]
    assert comp.modern_observation.raw_outputs["decision"] == "reject"
    assert comp.modern_observation.normalized_outputs["decision"] == "REJECT"


# ==============================================================================
# 6. Adapter Exception Isolation
# ==============================================================================

def test_adapter_exception_isolation():
    def failing_fn(credit_score=0, debt_ratio=0.0, annual_income=0):
        if credit_score < 500:
            raise RuntimeError("Database connection lost")
        return {"decision": "APPROVE"}

    def normal_legacy_fn(credit_score=0, debt_ratio=0.0, annual_income=0):
        return {"decision": "REJECT" if credit_score < 500 else "APPROVE"}

    oracle = _make_oracle("credit_score < 500", "REJECT", "INV-005")
    engine = CrossVersionCertificationEngine()

    report: CrossVersionCertificationReport = engine.certify_equivalence(
        oracles=[oracle],
        legacy_adapter=LegacyAdapter(normal_legacy_fn),
        modern_adapter=ModernizedAdapter(failing_fn),
        field_bounds=FIELD_BOUNDS,
        n_samples=20,
    )

    # Exception should be caught safely and block certification
    m = report.oracle_metrics[oracle.oracle_id]
    assert m.execution_errors > 0
    assert report.certified is False


# ==============================================================================
# 7. Deterministic Input Replay
# ==============================================================================

def test_deterministic_input_replay():
    oracle = _make_oracle("credit_score < 600 and debt_ratio > 0.4", "REJECT", "INV-006")

    # Generate suite 1
    inputs1 = generate_certification_test_suite(
        oracles=[oracle],
        field_bounds=FIELD_BOUNDS,
        n_diverse_samples=30,
        seed=12345,
    )

    # Generate suite 2 with identical seed
    inputs2 = generate_certification_test_suite(
        oracles=[oracle],
        field_bounds=FIELD_BOUNDS,
        n_diverse_samples=30,
        seed=12345,
    )

    assert len(inputs1) == len(inputs2)
    for inp1, inp2 in zip(inputs1, inputs2):
        assert inp1.input_id == inp2.input_id
        assert inp1.values == inp2.values


# ==============================================================================
# 8. Frozen OracleSet Immutability & Historical Reproducibility
# ==============================================================================

def test_oracle_set_immutability_and_versioning():
    reg = OracleRegistry()
    orc1 = reg.register_oracle(_make_oracle("credit_score < 500", "REJECT", "INV-A", severity="critical", domain="loan_approval"))
    orc2 = reg.register_oracle(_make_oracle("credit_score < 600 and debt_ratio > 0.4", "REJECT", "INV-B", severity="high", domain="loan_approval"))

    oracle_set = reg.create_oracle_set(name="CoreSuite", oracle_ids=[orc1.oracle_id, orc2.oracle_id], domain="loan_approval")

    # 1. Mutating attributes directly must be rejected by frozen Pydantic model
    with pytest.raises((ValidationError, TypeError)):
        oracle_set.name = "MutatedName"

    # 2. Registering an updated oracle with same ID creates a new version and new oracle-set hash
    orc1_mod = compile_candidate_to_oracle(CandidateInvariant(
        invariant_id="INV-A",
        condition="credit_score < 480",  # Changed threshold
        raw_condition="credit_score < 480",
        consequence="REJECT",
        source_file="legacy_loan_approval.py",
        confidence=0.95,
        status="graduated",
    ))
    orc1_mod = orc1_mod.model_copy(update={"oracle_id": orc1.oracle_id})
    orc1_v2 = reg.register_oracle(orc1_mod)
    assert orc1_v2.version == 2

    # Historical oracle v1 is preserved
    hist_orc1 = reg.get_oracle(orc1.oracle_id, version=1)
    assert hist_orc1 is not None
    assert hist_orc1.version == 1

    # Historical oracle set is preserved
    hist_set = reg.get_oracle_set(oracle_set.oracle_set_id)
    assert hist_set is not None
    assert hist_set.oracle_set_hash == oracle_set.oracle_set_hash


# ==============================================================================
# 9. Generic Non-Loan Domain Certification
# ==============================================================================

def test_generic_non_loan_domain_certification():
    """Verifies that Phase 9 operates generically on any business domain (e.g. medical triage)."""
    cand = CandidateInvariant(
        invariant_id="INV-TRIAGE-01",
        condition="heart_rate > 140 and blood_pressure < 90",
        raw_condition="heart_rate > 140 and blood_pressure < 90",
        consequence="RED",
        source_file="triage.py",
        source_lines=[10],
        severity="critical",
        domain="medical_triage",
        confidence=0.98,
        status="graduated",
    )
    triage_oracle = compile_candidate_to_oracle(cand)

    def legacy_triage(heart_rate=0, blood_pressure=0):
        if heart_rate > 140 and blood_pressure < 90:
            return {"decision": "RED"}
        return {"decision": "GREEN"}

    def modern_triage(heart_rate=0, blood_pressure=0):
        return legacy_triage(heart_rate, blood_pressure)

    engine = CrossVersionCertificationEngine()
    report = engine.certify_equivalence(
        oracles=[triage_oracle],
        legacy_adapter=FunctionAdapter(legacy_triage, name="legacy_c_code", version="1.0.0", role="legacy"),
        modern_adapter=FunctionAdapter(modern_triage, name="modern_rust_service", version="2.0.0", role="modernized"),
        field_bounds={"heart_rate": (50, 200), "blood_pressure": (60, 180)},
        n_samples=30,
    )

    assert report.overall_equivalence_score == 1.0
    assert report.certified is True
    assert report.domain_scores.get("medical_triage") == 1.0
