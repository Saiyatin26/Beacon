"""Comprehensive Unit & Integration Test Suite for Phase 7 (Adversarial Behavioral Invariant Validation).

Tests:
1. Condition AST Analysis (Variables, Comparisons, Logical Connectives)
2. Boundary, Near-Boundary, and Combinatorial Truth-Table Input Generation
3. Property Evaluation and Outcome Classification
4. Condition Coverage and Boundary Pass Rate Tracking
5. Counterexample Detection & Minimization (Shrinking)
6. Semantic Contradiction Analysis
7. Structured ValidationReport Generation
8. Primary Acceptance Test: Validating `credit_score < 600 and debt_ratio > 0.4 -> REJECT`
9. Invalidation Test: Refuting Incorrect Candidate `credit_score < 600 -> APPROVE` with Counterexample
10. Unactivated Condition Gate Safety (`boundary_pass_rate == 0.0` when unactivated)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

import legacy_loan_approval
from common.models import CandidateInvariant, EvidenceReport, ValidatedInvariant
from mining.adversarial import (
    analyze_condition,
    generate_adversarial_inputs,
    minimize_counterexample,
    analyze_contradictions,
    run_adversarial_validation,
)
from mining.confidence_scorer import score_confidence
from mining.validator import validate_candidate

FIELD_BOUNDS = {
    "credit_score": (400, 820),
    "debt_ratio": (0.0, 0.9),
    "annual_income": (10_000, 150_000),
}


# ==============================================================================
# 1. Condition AST Analysis
# ==============================================================================

def test_analyze_simple_comparison():
    analysis = analyze_condition("credit_score < 600")
    assert analysis.variables == {"credit_score"}
    assert len(analysis.predicates) == 1
    assert analysis.predicates[0].variable == "credit_score"
    assert analysis.predicates[0].operator == "<"
    assert analysis.predicates[0].threshold == 600.0


def test_analyze_compound_and_condition():
    analysis = analyze_condition("credit_score < 600 and debt_ratio > 0.4")
    assert analysis.variables == {"credit_score", "debt_ratio"}
    assert analysis.logical_connective == "and"
    assert len(analysis.predicates) == 2

    p_names = {p.variable for p in analysis.predicates}
    assert p_names == {"credit_score", "debt_ratio"}


def test_analyze_comparison_operators():
    analysis = analyze_condition("debt_ratio <= 0.45 and annual_income >= 50000")
    assert analysis.logical_connective == "and"
    p_map = {p.variable: p for p in analysis.predicates}
    assert p_map["debt_ratio"].operator == "<="
    assert p_map["debt_ratio"].threshold == 0.45
    assert p_map["annual_income"].operator == ">="
    assert p_map["annual_income"].threshold == 50000.0


# ==============================================================================
# 2. Adversarial Input Generation (Boundaries, Near-Boundaries, Truth-Table)
# ==============================================================================

def test_generate_adversarial_inputs_boundaries():
    cond = "credit_score < 600 and debt_ratio > 0.4"
    boundary_inputs, diverse_inputs = generate_adversarial_inputs(cond, FIELD_BOUNDS, target_count=50)

    assert len(boundary_inputs) > 0
    assert len(diverse_inputs) > 0

    # Verify presence of exact threshold points (599, 600, 601) and (0.39, 0.40, 0.41)
    cs_values = [inp["credit_score"] for inp in boundary_inputs]
    dr_values = [inp["debt_ratio"] for inp in boundary_inputs]

    assert any(abs(cs - 600) <= 1 for cs in cs_values)
    assert any(abs(dr - 0.4) <= 0.02 for dr in dr_values)


def test_generate_combinatorial_truth_table_inputs():
    cond = "credit_score < 600 and debt_ratio > 0.4"
    boundary_inputs, _ = generate_adversarial_inputs(cond, FIELD_BOUNDS)

    # Check that inputs exercise:
    # 1. credit_score < 600 and debt_ratio > 0.4 (T, T)
    # 2. credit_score < 600 and debt_ratio <= 0.4 (T, F)
    # 3. credit_score >= 600 and debt_ratio > 0.4 (F, T)
    # 4. credit_score >= 600 and debt_ratio <= 0.4 (F, F)
    tt = [inp for inp in boundary_inputs if inp["credit_score"] < 600 and inp["debt_ratio"] > 0.4]
    tf = [inp for inp in boundary_inputs if inp["credit_score"] < 600 and inp["debt_ratio"] <= 0.4]
    ft = [inp for inp in boundary_inputs if inp["credit_score"] >= 600 and inp["debt_ratio"] > 0.4]
    ff = [inp for inp in boundary_inputs if inp["credit_score"] >= 600 and inp["debt_ratio"] <= 0.4]

    assert len(tt) > 0, "Truth table (True, True) must be generated"
    assert len(tf) > 0, "Truth table (True, False) must be generated"
    assert len(ft) > 0, "Truth table (False, True) must be generated"
    assert len(ff) > 0, "Truth table (False, False) must be generated"


# ==============================================================================
# 3. Counterexample Detection & Minimization (Shrinking)
# ==============================================================================

def test_counterexample_minimization():
    incorrect_candidate = CandidateInvariant(
        invariant_id="cand-wrong",
        condition="credit_score < 600",
        consequence="APPROVE",
    )

    failing_input = {"credit_score": 420, "debt_ratio": 0.8, "annual_income": 120_000}
    minimized = minimize_counterexample(
        failing_input=failing_input,
        candidate=incorrect_candidate,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
    )

    assert "credit_score" in minimized
    assert minimized["credit_score"] < 600
    actual = legacy_loan_approval.evaluate_loan(**minimized)
    assert actual["decision"] == "REJECT"


# ==============================================================================
# 4. Semantic Contradiction Analysis
# ==============================================================================

def test_contradiction_detection_on_overlapping_rules():
    cand1 = CandidateInvariant(
        invariant_id="inv-1",
        condition="credit_score < 600",
        consequence="REJECT",
    )
    existing_conflicting = ValidatedInvariant(
        invariant_id="inv-2",
        condition="credit_score < 650",
        consequence="APPROVE",
        confidence=1.0,
        graduated=True,
    )

    test_inputs = [
        {"credit_score": 580, "debt_ratio": 0.3, "annual_income": 50000},
        {"credit_score": 700, "debt_ratio": 0.2, "annual_income": 80000},
    ]

    contra_count, details = analyze_contradictions(
        candidate=cand1,
        already_validated=[existing_conflicting],
        field_bounds=FIELD_BOUNDS,
        test_inputs=test_inputs,
    )

    assert contra_count == 1
    assert len(details) == 1
    assert details[0]["conflicting_invariant_id"] == "inv-2"
    assert len(details[0]["overlapping_samples"]) > 0


# ==============================================================================
# 5. Primary Acceptance Test: Validating True Invariant
# ==============================================================================

def test_adversarial_validation_graduates_true_invariant():
    candidate = CandidateInvariant(
        invariant_id="inv-true",
        condition="credit_score < 600 and debt_ratio > 0.4",
        consequence="REJECT",
        evidence_ids=["EV-S-002"],
    )

    report = validate_candidate(
        candidate=candidate,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        already_validated=[],
    )

    assert report.status == "VALIDATED"
    assert report.boundary_pass_rate == 1.0
    assert report.failed_probes == 0
    assert len(report.counterexamples) == 0
    assert report.condition_true_count > 0
    assert report.condition_coverage > 0.0

    # Verify integration with confidence scoring
    ev_report = EvidenceReport(
        invariant_id="inv-true",
        evidence_count=50,
        evidence_count_norm=1.0,
        input_diversity=0.85,
    )
    scored = score_confidence(candidate, ev_report, report)
    assert isinstance(scored, ValidatedInvariant)
    assert scored.graduated is True
    assert scored.confidence >= 0.80


# ==============================================================================
# 6. Invalidation Test: Refuting Incorrect Candidate with Counterexample
# ==============================================================================

def test_adversarial_validation_refutes_incorrect_candidate():
    incorrect_candidate = CandidateInvariant(
        invariant_id="inv-bad",
        condition="credit_score < 600",
        consequence="APPROVE",
    )

    report = validate_candidate(
        candidate=incorrect_candidate,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        already_validated=[],
    )

    assert report.status == "INVALIDATED"
    assert report.failed_probes > 0
    assert report.boundary_pass_rate < 1.0
    assert len(report.counterexamples) > 0

    ce = report.counterexamples[0]
    assert ce["expected_result"] == "APPROVE"
    assert ce["actual_result"] == "REJECT"
    assert ce["failure_type"] == "VIOLATION"

    # Verify confidence scoring marks candidate INVALIDATED and refuses graduation
    ev_report = EvidenceReport(
        invariant_id="inv-bad",
        evidence_count=10,
        evidence_count_norm=0.2,
        input_diversity=0.3,
    )
    scored = score_confidence(incorrect_candidate, ev_report, report)
    assert scored.graduated is False
    assert scored.status == "INVALIDATED"
    assert scored.confidence < 0.80


# ==============================================================================
# 7. Unactivated Condition Safety Gate
# ==============================================================================

def test_unactivated_condition_fails_validation_gate():
    # Condition that is never true within field bounds [400, 820]
    unactivated_candidate = CandidateInvariant(
        invariant_id="inv-unactive",
        condition="credit_score > 900",
        consequence="REJECT",
    )

    report = validate_candidate(
        candidate=unactivated_candidate,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        already_validated=[],
    )

    assert report.condition_true_count == 0
    assert report.boundary_pass_rate == 0.0
    assert report.status == "UNCONFIRMED"

    ev_report = EvidenceReport(
        invariant_id="inv-unactive",
        evidence_count=0,
        evidence_count_norm=0.0,
        input_diversity=0.0,
    )
    scored = score_confidence(unactivated_candidate, ev_report, report)
    assert scored.graduated is False
