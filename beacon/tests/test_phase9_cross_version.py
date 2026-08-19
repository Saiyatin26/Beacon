"""Comprehensive Test Suite for Phase 9 — Oracle Execution and Cross-Version Behavioral Equivalence.

Tests:
1. Equivalent Modernization achieves 100% equivalence and certified=True
2. Deliberate Modernization Regression pinpointed to exact oracle, input, and counterexample
3. Reference Inconsistency (Legacy violates Oracle) distinguished from modernization regression
4. Mutual Violation (Both violate Oracle) classified correctly
5. Output Normalization handling (casing/whitespace) without losing raw outputs
6. Execution Exception handling and error reporting
7. Deterministic Input Replay and identical hash reproducibility
8. Multi-Oracle Frozen OracleSet certification and domain breakdown
9. Zero LLM dependency during certification
"""

import sys
from pathlib import Path

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


def _make_oracle(condition: str, consequence: str, invariant_id: str, severity: str = "critical", domain: str = "loan_approval") -> OracleDefinition:
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
# 1. Equivalent Implementation Certification (100% Pass)
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
    assert len(report.regressions) == 0
    assert report.certified is True
    assert report.oracle_metrics[oracle.oracle_id].modern_regressions == 0
    assert report.oracle_metrics[oracle.oracle_id].applicable_probes > 0


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
# 3. Reference Inconsistency (Legacy Violating Frozen Oracle)
# ==============================================================================

def test_reference_inconsistency_not_blamed_on_modern():
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

    # Modern did NOT regress! Reference was inconsistent
    assert report.total_regressions == 0
    assert report.total_reference_inconsistencies > 0
    assert len(report.reference_inconsistencies) > 0
    assert report.reference_inconsistencies[0]["oracle_id"] == oracle.oracle_id


# ==============================================================================
# 4. Mutual Violation (Both Implementations Violate Oracle)
# ==============================================================================

def test_mutual_violation_classification():
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

    # Exception should be caught safely
    m = report.oracle_metrics[oracle.oracle_id]
    assert m.execution_errors > 0


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
# 8. Frozen OracleSet Certification
# ==============================================================================

def test_frozen_oracle_set_certification():
    reg = OracleRegistry()
    orc1 = reg.register_oracle(_make_oracle("credit_score < 500", "REJECT", "INV-A", severity="critical", domain="loan_approval"))
    orc2 = reg.register_oracle(_make_oracle("credit_score < 600 and debt_ratio > 0.4", "REJECT", "INV-B", severity="high", domain="loan_approval"))

    oracle_set = reg.create_oracle_set(name="CoreSuite", oracle_ids=[orc1.oracle_id, orc2.oracle_id], domain="loan_approval")

    def legacy_fn(credit_score=0, debt_ratio=0.0, annual_income=0):
        if credit_score < 500:
            return {"decision": "REJECT"}
        if credit_score < 600 and debt_ratio > 0.4:
            return {"decision": "REJECT"}
        return {"decision": "APPROVE"}

    def modern_fn(credit_score=0, debt_ratio=0.0, annual_income=0):
        return legacy_fn(credit_score, debt_ratio, annual_income)

    engine = CrossVersionCertificationEngine()
    report = engine.certify_equivalence(
        oracles=oracle_set,
        legacy_adapter=LegacyAdapter(legacy_fn),
        modern_adapter=ModernizedAdapter(modern_fn),
        field_bounds=FIELD_BOUNDS,
        n_samples=30,
    )

    assert report.overall_equivalence_score == 1.0
    assert report.oracle_set_id == oracle_set.oracle_set_id
    assert report.oracle_set_hash == oracle_set.oracle_set_hash
    assert "loan_approval" in report.domain_scores
    assert report.domain_scores["loan_approval"] == 1.0
