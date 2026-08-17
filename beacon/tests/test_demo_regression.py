"""Deterministic integration/regression test for the BEACON demo pipeline.

Verifies end-to-end trace generation, loading, invariant mining, oracle synthesis,
and certification scoring without requiring external AI/API credentials.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

import legacy_loan_approval
import modern_loan_approval
from generate_traces import generate_traces
from ingestion.legacy_parser import load_source
from ingestion.trace_loader import load_traces
from mining.offline_miner import mine_python_decision_rules
from oracle.synthesizer import synthesize_oracle
from certification.runner import certify
from common.models import TraceEvent, ValidatedInvariant, Oracle, CertificationRun


FIELD_BOUNDS = {
    "credit_score": (400, 820),
    "debt_ratio": (0.0, 0.9),
    "annual_income": (10_000, 150_000),
}


def test_trace_generation_and_loading(tmp_path):
    """Test that trace generation produces valid dictionaries and load_traces creates TraceEvent objects."""
    trace_dicts = generate_traces(n_random=50)
    assert len(trace_dicts) > 50

    trace_file = tmp_path / "test_traces.json"
    import json
    trace_file.write_text(json.dumps(trace_dicts))

    traces = load_traces(trace_file)
    assert len(traces) == len(trace_dicts)
    assert isinstance(traces[0], TraceEvent)
    assert "credit_score" in traces[0].inputs
    assert "decision" in traces[0].output


def test_offline_mining_produces_validated_invariants(tmp_path):
    """Test that offline miner extracts the known business rule invariants deterministically."""
    source = load_source(ROOT / "legacy_sample" / "legacy_loan_approval.py")
    trace_dicts = generate_traces(n_random=50)
    trace_file = tmp_path / "traces.json"
    import json
    trace_file.write_text(json.dumps(trace_dicts))
    traces = load_traces(trace_file)

    invariants = mine_python_decision_rules(
        source, traces, legacy_loan_approval.evaluate_loan, FIELD_BOUNDS
    )
    assert len(invariants) > 0
    graduated = [inv for inv in invariants if inv.graduated]
    assert len(graduated) > 0

    # Ensure the key hidden invariant (credit_score < 600 and debt_ratio > 0.4) was mined
    target_conditions = [inv.condition for inv in graduated]
    assert any("credit_score < 600" in cond and "debt_ratio > 0.4" in cond for cond in target_conditions)


def test_buggy_modernization_fails_certification():
    """Regression test: broken modernized app causes BEACON to detect behavioral violations."""
    source = load_source(ROOT / "legacy_sample" / "legacy_loan_approval.py")
    trace_file = ROOT / "legacy_sample" / "trace_log.json"
    if not trace_file.exists():
        import json
        trace_file.write_text(json.dumps(generate_traces(), indent=2))

    traces = load_traces(trace_file)
    invariants = mine_python_decision_rules(
        source, traces, legacy_loan_approval.evaluate_loan, FIELD_BOUNDS
    )
    oracles = [synthesize_oracle(inv) for inv in invariants if inv.graduated]
    assert len(oracles) > 0

    # Run certification against intentionally buggy modernization
    run: CertificationRun = certify(
        oracles=oracles,
        modern_fn=modern_loan_approval.evaluate_loan,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        domain_of={o.invariant_id: "Loan approval" for o in oracles},
    )

    # Conceptual assertion requirements:
    assert run.total_violated > 0, "Buggy modernization must trigger oracle violations"
    assert run.equivalence_score < 1.0, "Equivalence score must be less than 100%"
    assert len(run.violations) > 0, "Violation report details must be generated"

    # Confirm counterexample details exist for the dropped rule
    buggy_violation = next(v for v in run.violations if "credit_score < 600" in v.expected)
    assert buggy_violation.legacy_output == "REJECT"
    assert buggy_violation.modern_output == "APPROVE"
    assert "credit_score" in buggy_violation.counterexample
    assert "debt_ratio" in buggy_violation.counterexample


def test_equivalent_modernization_passes_certification():
    """Regression test: correct modernized app achieves 100% equivalence score."""
    source = load_source(ROOT / "legacy_sample" / "legacy_loan_approval.py")
    trace_file = ROOT / "legacy_sample" / "trace_log.json"
    if not trace_file.exists():
        import json
        trace_file.write_text(json.dumps(generate_traces(), indent=2))

    traces = load_traces(trace_file)
    invariants = mine_python_decision_rules(
        source, traces, legacy_loan_approval.evaluate_loan, FIELD_BOUNDS
    )
    oracles = [synthesize_oracle(inv) for inv in invariants if inv.graduated]

    run: CertificationRun = certify(
        oracles=oracles,
        modern_fn=legacy_loan_approval.evaluate_loan,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
    )

    assert run.total_violated == 0
    assert run.equivalence_score == 1.0
    assert len(run.violations) == 0
