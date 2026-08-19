"""Comprehensive Regression & Hardening Test Suite for Phases 1–7.

Tests:
1. Grounding: Evidence ID exists but does not support candidate condition -> GROUNDING_FAILED
2. Grounding: Unsupported threshold -> GROUNDING_FAILED
3. Consequence Grounding: Unsupported output -> GROUNDING_FAILED
4. Grounding: Source-line mismatch -> GROUNDING_FAILED
5. Normalization-Aware Provenance: Reordered AND conditions recover evidence and execution IDs
6. Separated Metrics: Boundary pass rate uses strictly boundary probes
7. Safety Gate: Invalidated candidate cannot graduate even with high raw evidence
8. Reproducibility Metadata: Complete run and environment metadata preserved
9. Primary End-to-End Regression: True invariant graduates, invalid invariant refuted with counterexample
10. Full Audit Provenance Chain: Complete trace from raw condition to final status
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

import legacy_loan_approval
from common.models import CandidateInvariant, EvidenceReport, ValidatedInvariant
from evidence.builder import build_evidence_package
from generate_traces import generate_traces
from ingestion.legacy_parser import extract_ast_structure
from mining.candidate_generator import LLMCandidateGenerator
from mining.confidence_scorer import score_confidence
from mining.grounding_checker import check_candidate_grounding, filter_grounded_candidates
from mining.pipeline import run_mining_pipeline
from mining.validator import validate_candidate

FIELD_BOUNDS = {
    "credit_score": (400, 820),
    "debt_ratio": (0.0, 0.9),
    "annual_income": (10_000, 150_000),
}


def _get_sample_evidence_package():
    legacy_file = str(ROOT / "legacy_sample" / "legacy_loan_approval.py")
    static_result = extract_ast_structure(legacy_file)
    trace_dicts = generate_traces(n_random=300)
    from common.models import TraceEvent
    traces = [TraceEvent(**t) for t in trace_dicts]
    return build_evidence_package(static_result, traces)


# ==============================================================================
# 1. Grounding: Evidence ID exists but does not support candidate condition
# ==============================================================================

def test_grounding_rejects_mismatched_evidence_id():
    pkg = _get_sample_evidence_package()
    # Find static item for annual_income
    income_ev = next(
        (s for s in pkg.static_evidence_items if "annual_income" in (s.condition or "")),
        pkg.static_evidence_items[0]
    )

    # Candidate claims credit_score < 600, but cites annual_income static evidence ID
    mismatched_cand = CandidateInvariant(
        invariant_id="cand-mismatch",
        condition="credit_score < 600",
        consequence="REJECT",
        evidence_ids=[income_ev.evidence_id],
    )

    res = check_candidate_grounding(mismatched_cand, pkg)
    assert res.is_grounded is False
    assert "does not semantically support" in res.rejection_reason


# ==============================================================================
# 2. Grounding: Unsupported threshold
# ==============================================================================

def test_grounding_rejects_unsupported_threshold():
    pkg = _get_sample_evidence_package()
    cand = CandidateInvariant(
        invariant_id="cand-thresh",
        condition="credit_score < 650",
        consequence="REJECT",
    )
    res = check_candidate_grounding(cand, pkg)
    assert res.is_grounded is False
    assert "Unsupported / invented numerical threshold" in res.rejection_reason


# ==============================================================================
# 3. Consequence Grounding: Unsupported output
# ==============================================================================

def test_grounding_rejects_unsupported_consequence():
    pkg = _get_sample_evidence_package()
    # In legacy loan approval, credit_score < 600 and debt_ratio > 0.4 always produces REJECT
    cand = CandidateInvariant(
        invariant_id="cand-bad-consequence",
        condition="credit_score < 600 and debt_ratio > 0.4",
        consequence="APPROVE",
    )
    res = check_candidate_grounding(cand, pkg)
    assert res.is_grounded is False
    assert "Unsupported consequence 'APPROVE'" in res.rejection_reason


# ==============================================================================
# 4. Grounding: Source line mismatch
# ==============================================================================

def test_grounding_rejects_source_line_mismatch():
    pkg = _get_sample_evidence_package()
    static_ev = pkg.static_evidence_items[0]

    cand = CandidateInvariant(
        invariant_id="cand-line-mismatch",
        condition=static_ev.condition or "credit_score < 500",
        consequence="REJECT",
        evidence_ids=[static_ev.evidence_id],
        source_lines=[999],  # Blatantly incorrect source line
    )
    res = check_candidate_grounding(cand, pkg)
    assert res.is_grounded is False
    assert "Source line mismatch" in res.rejection_reason


# ==============================================================================
# 5. Normalization-Aware Provenance Matching
# ==============================================================================

@patch("llm.manager.ProviderManager.generate")
def test_normalization_aware_provenance_recovers_evidence(mock_generate):
    pkg = _get_sample_evidence_package()

    # Raw condition with inverted operand order: debt_ratio > 0.4 and credit_score < 600
    mock_generate.return_value = MagicMock(
        success=True,
        provider_name="openrouter",
        model_name="anthropic/claude-3.5-sonnet",
        latency_ms=100.0,
        fallback_occurred=False,
        fallback_chain=["openrouter"],
        parsed_json=[{"condition": "debt_ratio > 0.4 and credit_score < 600", "consequence": "REJECT", "severity": "critical"}],
        error=None,
    )

    generator = LLMCandidateGenerator()
    candidates = generator.propose_candidates(pkg)

    assert len(candidates) == 1
    cand = candidates[0]
    # Verify canonical normalized condition
    assert cand.condition == "credit_score < 600 and debt_ratio > 0.4"
    # Verify raw condition preserved
    assert cand.raw_condition == "debt_ratio > 0.4 and credit_score < 600"
    # Verify execution IDs and dynamic evidence recovered via normalized matching
    assert len(cand.execution_ids) > 0
    assert len(cand.evidence_ids) > 0


# ==============================================================================
# 6. Separated Metrics: Boundary Pass Rate Uses Strictly Boundary Probes
# ==============================================================================

def test_separated_validation_metrics():
    cand = CandidateInvariant(
        invariant_id="cand-metrics",
        condition="credit_score < 600 and debt_ratio > 0.4",
        consequence="REJECT",
    )

    report = validate_candidate(
        candidate=cand,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        already_validated=[],
    )

    # Verify separated probe counts and pass rates
    assert report.boundary_probes_total > 0
    assert report.diverse_probes_total > 0
    assert report.boundary_probes_true > 0
    assert report.boundary_pass_rate == (report.boundary_probes_passed / report.boundary_probes_true)
    if report.diverse_probes_true > 0:
        assert report.diverse_input_pass_rate == (report.diverse_probes_passed / report.diverse_probes_true)
    else:
        assert report.diverse_input_pass_rate == 0.0


# ==============================================================================
# 7. Safety Gate: Invalidated Candidate Cannot Graduate Even With High Evidence
# ==============================================================================

def test_invalidated_candidate_refuses_graduation():
    cand = CandidateInvariant(
        invariant_id="cand-invalid-gate",
        condition="credit_score < 600",
        consequence="APPROVE",
    )

    report = validate_candidate(
        candidate=cand,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        already_validated=[],
    )

    assert report.status == "INVALIDATED"
    assert report.failed_probes > 0

    # Provide high evidence score
    ev_report = EvidenceReport(
        invariant_id="cand-invalid-gate",
        evidence_count=1000,
        evidence_count_norm=1.0,
        input_diversity=1.0,
    )

    scored = score_confidence(cand, ev_report, report)
    assert scored.graduated is False
    assert scored.status == "INVALIDATED"
    assert not isinstance(scored, ValidatedInvariant)


# ==============================================================================
# 8. Reproducibility Metadata
# ==============================================================================

def test_reproducibility_metadata_presence():
    cand = CandidateInvariant(
        invariant_id="cand-repro",
        condition="credit_score < 600 and debt_ratio > 0.4",
        consequence="REJECT",
        generation_method="offline",
    )

    report = validate_candidate(
        candidate=cand,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        already_validated=[],
    )

    repro = report.reproducibility
    assert "validation_run_id" in repro
    assert "candidate_id" in repro
    assert "python_version" in repro
    assert "timestamp" in repro


# ==============================================================================
# 9. Primary End-to-End Regression
# ==============================================================================

def test_end_to_end_hardening_pipeline():
    pkg = _get_sample_evidence_package()

    graduated, unconfirmed = run_mining_pipeline(
        evidence_package=pkg,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        already_validated=[],
        use_atlas=False,
        use_llm=False,
    )

    assert len(graduated) >= 2
    for inv in graduated:
        assert inv.graduated is True
        assert inv.confidence >= 0.80
        assert inv.validation_result["status"] == "VALIDATED"
        assert inv.validation_result["boundary_pass_rate"] == 1.0


# ==============================================================================
# 10. Full Audit Provenance Chain
# ==============================================================================

def test_full_audit_provenance_chain():
    cand = CandidateInvariant(
        invariant_id="cand-audit",
        condition="credit_score < 600 and debt_ratio > 0.4",
        consequence="REJECT",
        source_file="legacy_sample/legacy_loan_approval.py",
        source_lines=[14],
        evidence_ids=["EV-S-001", "EV-D-001"],
        execution_ids=["EX-001"],
    )

    report = validate_candidate(
        candidate=cand,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        already_validated=[],
    )

    ev_report = EvidenceReport(
        invariant_id="cand-audit",
        evidence_count=50,
        evidence_count_norm=1.0,
        input_diversity=0.9,
    )

    scored = score_confidence(cand, ev_report, report)

    # Verify complete audit chain
    assert scored.invariant_id == "cand-audit"
    assert scored.source_file == "legacy_sample/legacy_loan_approval.py"
    assert scored.source_lines == [14]
    assert scored.evidence_ids == ["EV-S-001", "EV-D-001"]
    assert scored.execution_ids == ["EX-001"]
    assert scored.validation_result is not None
    assert "boundary_pass_rate" in scored.confidence_components
    assert "overall_property_pass_rate" in scored.confidence_components
    assert scored.confidence >= 0.80
