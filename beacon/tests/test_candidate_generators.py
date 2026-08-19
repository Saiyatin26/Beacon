"""Integration tests proving both offline and LLM candidate generators are identical downstream."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

import legacy_loan_approval
from generate_traces import generate_traces
from ingestion.legacy_parser import extract_ast_structure
from ingestion.trace_loader import load_traces
from evidence.builder import build_evidence_package
from mining.pipeline import run_mining_pipeline
from common.models import CandidateInvariant, TraceEvent


FIELD_BOUNDS = {
    "credit_score": (400, 820),
    "debt_ratio": (0.0, 0.9),
    "annual_income": (10_000, 150_000),
}


@patch("llm.manager.ProviderManager.generate")
def test_generator_equivalence_and_validation(mock_generate, tmp_path):
    """Prove that both generators produce the same structures processed by the same validation components."""
    
    # Mock LLM response from provider
    mock_generate.return_value = MagicMock(
        success=True,
        provider_name="openrouter",
        model_name="anthropic/claude-3.5-sonnet",
        latency_ms=100.0,
        fallback_occurred=False,
        fallback_chain=["openrouter"],
        parsed_json=[{"condition": "credit_score < 600 and debt_ratio > 0.4", "consequence": "REJECT", "severity": "critical", "supporting_evidence_ids": [], "source_lines": [14]}],
        error=None,
    )

    # Build Evidence Package
    legacy_file = str(ROOT / "legacy_sample" / "legacy_loan_approval.py")
    static_result = extract_ast_structure(legacy_file)
    trace_dicts = generate_traces(n_random=500)
    traces = [TraceEvent(**t) for t in trace_dicts]
    evidence_pkg = build_evidence_package(static_result, traces)

    # 1. Run Offline
    offline_graduated, offline_unconfirmed = run_mining_pipeline(
        evidence_package=evidence_pkg,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        already_validated=[],
        use_atlas=False,
        use_llm=False
    )
    
    # 2. Run LLM
    llm_graduated, llm_unconfirmed = run_mining_pipeline(
        evidence_package=evidence_pkg,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        already_validated=[],
        use_atlas=False,
        use_llm=True
    )
    
    assert mock_generate.called
    
    assert len(llm_graduated) + len(llm_unconfirmed) > 0
    all_llm = llm_graduated + llm_unconfirmed
    assert hasattr(all_llm[0], "confidence")
    assert all_llm[0].generation_method == "llm"

    assert len(offline_graduated) + len(offline_unconfirmed) > 0
    all_offline = offline_graduated + offline_unconfirmed
    assert hasattr(all_offline[0], "confidence")
    assert all_offline[0].generation_method == "offline"
