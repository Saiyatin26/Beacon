"""Comprehensive Unit & Integration Test Suite for Phase 6 (AI-Assisted Candidate Mining).

Tests:
1. Evidence Relevance Selection & Scoring
2. Prompt & Context Builder
3. Structured Candidate Parsing (1 to 5 candidates)
4. Expression Normalization (Commutative Conjunction Canonicalization)
5. Candidate Deduplication & Provenance Merging
6. Strict Evidence Grounding & Hallucination Rejection
7. LLM Failure & Exception Handling (RateLimit, API errors, Invalid JSON)
8. Offline / LLM Generator Swappability & End-to-End Pipeline Integration
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from anthropic import APIConnectionError, APIStatusError, RateLimitError

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

import legacy_loan_approval
from common.models import CandidateInvariant, TraceEvent, ValidatedInvariant
from evidence.builder import build_evidence_package
from generate_traces import generate_traces
from ingestion.legacy_parser import extract_ast_structure
from mining.base_generator import CandidateGenerator
from mining.candidate_generator import LLMCandidateGenerator, deduplicate_candidates
from mining.evidence_selector import score_evidence_relevance, select_relevant_evidence
from mining.grounding_checker import check_candidate_grounding, filter_grounded_candidates
from mining.normalizer import normalize_candidate, normalize_condition
from mining.offline_miner import OfflineCandidateGenerator
from mining.pipeline import run_mining_pipeline
from mining.prompt_builder import build_mining_prompt

FIELD_BOUNDS = {
    "credit_score": (400, 820),
    "debt_ratio": (0.0, 0.9),
    "annual_income": (10_000, 150_000),
}


def _get_sample_evidence_package():
    legacy_file = str(ROOT / "legacy_sample" / "legacy_loan_approval.py")
    static_result = extract_ast_structure(legacy_file)
    trace_dicts = generate_traces(n_random=300)
    traces = [TraceEvent(**t) for t in trace_dicts]
    return build_evidence_package(static_result, traces)


# ==============================================================================
# 1. Evidence Relevance Selection & Scoring
# ==============================================================================

def test_evidence_relevance_scoring_and_selection():
    pkg = _get_sample_evidence_package()
    assert len(pkg.correlated_conditions) > 0

    for corr in pkg.correlated_conditions:
        score = score_evidence_relevance(corr)
        assert 0.0 <= score <= 1.0

    selected = select_relevant_evidence(pkg, max_correlated=3, max_static=5, max_dynamic=10)
    assert len(selected.correlated_conditions) <= 3
    assert len(selected.static_items) <= 5
    assert len(selected.dynamic_items) <= 10
    assert selected.source_file == pkg.source_file
    assert selected.language == "python"


# ==============================================================================
# 2. Prompt & Context Builder
# ==============================================================================

def test_prompt_builder_construction():
    pkg = _get_sample_evidence_package()
    selected = select_relevant_evidence(pkg)
    prompt = build_mining_prompt(selected)

    assert "CRITICAL INSTRUCTIONS & GUARDRAILS" in prompt
    assert "EVIDENCE PACKAGE SUMMARY:" in prompt
    assert "JSON Array Output Schema:" in prompt
    assert "correlated_business_rules" in prompt
    assert selected.source_file in prompt


# ==============================================================================
# 3. Normalization & Commutative Equivalence
# ==============================================================================

def test_condition_normalization():
    cond1 = "credit_score < 600 and debt_ratio > 0.4"
    cond2 = "debt_ratio > 0.4 and credit_score < 600"
    cond3 = "credit_score < 600 AND debt_ratio > 0.4"

    norm1 = normalize_condition(cond1)
    norm2 = normalize_condition(cond2)
    norm3 = normalize_condition(cond3)

    # Both commutative orders must produce the exact same canonical string
    assert norm1 == norm2
    assert norm1 == norm3
    assert "and" in norm1


def test_candidate_normalization():
    c = CandidateInvariant(
        invariant_id="cand-1",
        condition="debt_ratio > 0.4 AND credit_score < 600",
        consequence="reject",
        source_lines=[14, 12, 14],
    )
    normalized = normalize_candidate(c)
    assert normalized.consequence == "REJECT"
    assert normalized.source_lines == [12, 14]
    assert normalized.condition == "credit_score < 600 and debt_ratio > 0.4"


# ==============================================================================
# 4. Candidate Deduplication & Provenance Merging
# ==============================================================================

def test_candidate_deduplication_merges_evidence():
    c1 = CandidateInvariant(
        invariant_id="cand-1",
        condition="credit_score < 600 and debt_ratio > 0.4",
        consequence="REJECT",
        evidence_ids=["EV-S-001", "EV-D-001"],
        execution_ids=["EX-001"],
        source_lines=[14],
    )
    c2 = CandidateInvariant(
        invariant_id="cand-2",
        condition="credit_score < 600 and debt_ratio > 0.4",
        consequence="REJECT",
        evidence_ids=["EV-S-001", "EV-D-002"],
        execution_ids=["EX-002"],
        source_lines=[15],
    )

    deduped = deduplicate_candidates([c1, c2])
    assert len(deduped) == 1
    merged = deduped[0]
    assert merged.condition == "credit_score < 600 and debt_ratio > 0.4"
    assert "EV-D-001" in merged.evidence_ids
    assert "EV-D-002" in merged.evidence_ids
    assert "EX-001" in merged.execution_ids
    assert "EX-002" in merged.execution_ids
    assert merged.source_lines == [14, 15]


# ==============================================================================
# 5. Strict Evidence Grounding & Hallucination Rejection
# ==============================================================================

def test_grounding_checker_accepts_valid_candidate():
    pkg = _get_sample_evidence_package()
    static_id = pkg.static_evidence_items[0].evidence_id if pkg.static_evidence_items else "EV-S-001"

    valid_cand = CandidateInvariant(
        invariant_id="test-valid",
        condition="credit_score < 600 and debt_ratio > 0.4",
        consequence="REJECT",
        evidence_ids=[static_id],
    )
    res = check_candidate_grounding(valid_cand, pkg)
    assert res.is_grounded is True


def test_grounding_checker_rejects_hallucinated_variable():
    pkg = _get_sample_evidence_package()

    bad_cand = CandidateInvariant(
        invariant_id="test-bad-var",
        condition="fico_score < 600 and debt_ratio > 0.4",
        consequence="REJECT",
    )
    res = check_candidate_grounding(bad_cand, pkg)
    assert res.is_grounded is False
    assert "Hallucinated / unknown variables" in res.rejection_reason


def test_grounding_checker_rejects_unsupported_threshold():
    pkg = _get_sample_evidence_package()

    bad_cand = CandidateInvariant(
        invariant_id="test-bad-thresh",
        condition="credit_score < 650 and debt_ratio > 0.4",
        consequence="REJECT",
    )
    res = check_candidate_grounding(bad_cand, pkg)
    assert res.is_grounded is False
    assert "Unsupported / invented numerical threshold" in res.rejection_reason


def test_grounding_checker_rejects_hallucinated_evidence_id():
    pkg = _get_sample_evidence_package()

    bad_cand = CandidateInvariant(
        invariant_id="test-bad-ev-id",
        condition="credit_score < 600 and debt_ratio > 0.4",
        consequence="REJECT",
        evidence_ids=["EV-S-999"],
    )
    res = check_candidate_grounding(bad_cand, pkg)
    assert res.is_grounded is False
    assert "Nonexistent / hallucinated evidence ID" in res.rejection_reason


def test_filter_grounded_candidates():
    pkg = _get_sample_evidence_package()
    static_id = pkg.static_evidence_items[0].evidence_id if pkg.static_evidence_items else "EV-S-001"

    c1 = CandidateInvariant(
        invariant_id="c1",
        condition="credit_score < 600 and debt_ratio > 0.4",
        consequence="REJECT",
        evidence_ids=[static_id],
    )
    c2 = CandidateInvariant(
        invariant_id="c2",
        condition="unseen_var > 100",
        consequence="REJECT",
    )

    grounded, rejected = filter_grounded_candidates([c1, c2], pkg)
    assert len(grounded) == 1
    assert grounded[0].invariant_id == "c1"
    assert len(rejected) == 1
    assert rejected[0].status == "GROUNDING_FAILED"


# ==============================================================================
# 6. LLM Failure & Exception Handling
# ==============================================================================

@patch("llm.manager.ProviderManager.generate")
def test_llm_generator_handles_api_errors_gracefully(mock_generate):
    pkg = _get_sample_evidence_package()
    generator = LLMCandidateGenerator()

    # 1. API Error
    mock_generate.return_value = MagicMock(success=False, error="Rate limited", parsed_json=None)
    assert generator.propose_candidates(pkg) == []

    # 2. Connection Error
    mock_generate.return_value = MagicMock(success=False, error="Connection timeout", parsed_json=None)
    assert generator.propose_candidates(pkg) == []

    # 3. Invalid JSON Output
    mock_generate.return_value = MagicMock(success=True, parsed_json=None, raw_text="Sorry, not JSON")
    assert generator.propose_candidates(pkg) == []


# ==============================================================================
# 7. LLM Multiple Candidates Generation & Swappability
# ==============================================================================

@patch("llm.manager.ProviderManager.generate")
def test_llm_generator_proposes_multiple_grounded_candidates(mock_generate):
    pkg = _get_sample_evidence_package()
    static_id_12 = next((s.evidence_id for s in pkg.static_evidence_items if getattr(s, "line", None) == 12), "EV-S-001")
    static_id_14 = next((s.evidence_id for s in pkg.static_evidence_items if getattr(s, "line", None) == 14), "EV-S-002")

    mock_generate.return_value = MagicMock(
        success=True,
        provider_name="openrouter",
        model_name="anthropic/claude-3.5-sonnet",
        latency_ms=120.0,
        fallback_occurred=False,
        fallback_chain=["openrouter"],
        parsed_json=[
            {
                "condition": "credit_score < 500",
                "consequence": "REJECT",
                "severity": "critical",
                "rationale": "Direct static reject branch.",
                "supporting_evidence_ids": [static_id_12],
                "source_lines": [12],
            },
            {
                "condition": "credit_score < 600 and debt_ratio > 0.4",
                "consequence": "REJECT",
                "severity": "critical",
                "rationale": "Correlated branch rejection.",
                "supporting_evidence_ids": [static_id_14],
                "source_lines": [14],
            },
        ],
        error=None,
    )

    generator = LLMCandidateGenerator()
    candidates = generator.propose_candidates(pkg)

    assert len(candidates) == 2
    for c in candidates:
        assert isinstance(c, CandidateInvariant)
        assert c.generation_method == "llm"
        assert c.status == "candidate"
        assert c.source_file == pkg.source_file


# ==============================================================================
# 8. End-to-End Pipeline Swappability (Offline vs LLM)
# ==============================================================================

@patch("llm.manager.ProviderManager.generate")
def test_end_to_end_pipeline_swappability(mock_generate):
    pkg = _get_sample_evidence_package()
    static_id_14 = next((s.evidence_id for s in pkg.static_evidence_items if getattr(s, "line", None) == 14), "EV-S-002")

    # Setup mocked LLM returning valid candidates
    mock_generate.return_value = MagicMock(
        success=True,
        provider_name="openrouter",
        model_name="anthropic/claude-3.5-sonnet",
        latency_ms=110.0,
        fallback_occurred=False,
        fallback_chain=["openrouter"],
        parsed_json=[{
            "condition": "debt_ratio > 0.4 and credit_score < 600",  # Tests normalization
            "consequence": "REJECT",
            "severity": "critical",
            "rationale": "Undocumented rejection rule.",
            "supporting_evidence_ids": [static_id_14],
            "source_lines": [14],
        }],
        error=None,
    )

    # Run Offline
    offline_grad, offline_unconf = run_mining_pipeline(
        evidence_package=pkg,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        already_validated=[],
        use_atlas=False,
        use_llm=False,
    )

    # Run LLM
    llm_grad, llm_unconf = run_mining_pipeline(
        evidence_package=pkg,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        already_validated=[],
        use_atlas=False,
        use_llm=True,
    )

    # Both generators feed into the exact same validation & confidence pipeline
    assert len(offline_grad) > 0
    assert len(llm_grad) > 0

    assert isinstance(offline_grad[0], ValidatedInvariant)
    assert isinstance(llm_grad[0], ValidatedInvariant)

    assert offline_grad[0].confidence >= 0.80
    assert llm_grad[0].confidence >= 0.80

    assert offline_grad[0].generation_method == "offline"
    assert llm_grad[0].generation_method == "llm"
