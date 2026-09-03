"""Comprehensive Test Suite for BEACON's Decoupled Multi-Provider LLM Layer.

Tests:
1. OpenRouter Provider generation with mocked HTTP response
2. OpenRouter failure -> Anthropic fallback
3. Anthropic failure -> Ollama fallback
4. Ollama failure -> Offline fallback
5. Explicit provider selection and error reporting
6. Missing API key handling
7. Malformed JSON parsing and extraction
8. Provenance & reproducibility metadata recording
9. Keyless operation in offline/local modes
10. Schema consistency across all providers
11. Status endpoint sanitization
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

import legacy_loan_approval
from common.config import settings
from common.models import CandidateInvariant, TraceEvent
from evidence.builder import build_evidence_package
from generate_traces import generate_traces
from ingestion.legacy_parser import extract_ast_structure
from llm.base import extract_json_payload
from llm.manager import ProviderManager, get_provider_manager
from llm.openrouter_provider import OpenRouterProvider
from llm.anthropic_provider import AnthropicProvider
from llm.ollama_provider import OllamaProvider
from llm.offline_provider import OfflineProvider
from mining.candidate_generator import LLMCandidateGenerator
from mining.pipeline import run_mining_pipeline

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
# 1. JSON Extraction Helper Tests
# ==============================================================================

def test_extract_json_payload_variations():
    # Plain JSON
    assert extract_json_payload('[{"a": 1}]') == [{"a": 1}]
    # Markdown json code fence
    assert extract_json_payload('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    # Markdown code fence without language
    assert extract_json_payload('```\n[{"a": 1}]\n```') == [{"a": 1}]
    # Text with surrounding commentary
    assert extract_json_payload('Here is the rule:\n[{"a": 1}]\nHope this helps!') == [{"a": 1}]
    # Malformed text
    assert extract_json_payload('No json here') is None


# ==============================================================================
# 2. OpenRouter Provider Mock Test
# ==============================================================================

@patch("urllib.request.urlopen")
def test_openrouter_provider_generate(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.getcode.return_value = 200
    mock_resp.read.return_value = json.dumps({
        "model": "anthropic/claude-3.5-sonnet",
        "choices": [{
            "message": {
                "content": '[{"condition": "credit_score < 500", "consequence": "REJECT"}]'
            }
        }],
        "usage": {"total_tokens": 120}
    }).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    provider = OpenRouterProvider(api_key="mock-openrouter-key")
    resp = provider.generate("Test prompt")

    assert resp.success is True
    assert resp.provider_name == "openrouter"
    assert resp.model_name == "anthropic/claude-3.5-sonnet"
    assert resp.parsed_json == [{"condition": "credit_score < 500", "consequence": "REJECT"}]


# ==============================================================================
# 3. Automatic Fallback Hierarchy: OpenRouter -> Anthropic -> Ollama -> Offline
# ==============================================================================

def test_fallback_openrouter_to_anthropic():
    manager = ProviderManager()

    # OpenRouter fails, Anthropic succeeds
    manager.providers["openrouter"].generate = MagicMock(
        return_value=MagicMock(success=False, error="Rate limit", parsed_json=None)
    )
    manager.providers["openrouter"].is_available = MagicMock(return_value=True)

    manager.providers["anthropic"].generate = MagicMock(
        return_value=MagicMock(
            success=True,
            provider_name="anthropic",
            model_name="claude-sonnet-4-6",
            parsed_json=[{"condition": "credit_score < 500", "consequence": "REJECT"}],
            error=None,
        )
    )
    manager.providers["anthropic"].is_available = MagicMock(return_value=True)

    resp = manager.generate("Test prompt")
    assert resp.success is True
    assert resp.provider_name == "anthropic"
    assert resp.fallback_occurred is True
    assert resp.fallback_chain == ["openrouter", "anthropic"]


def test_fallback_anthropic_to_ollama():
    manager = ProviderManager()

    # OpenRouter & Anthropic not available
    manager.providers["openrouter"].is_available = MagicMock(return_value=False)
    manager.providers["anthropic"].is_available = MagicMock(return_value=False)

    # Ollama succeeds
    manager.providers["ollama"].is_available = MagicMock(return_value=True)
    manager.providers["ollama"].generate = MagicMock(
        return_value=MagicMock(
            success=True,
            provider_name="ollama",
            model_name="qwen2.5-coder:7b",
            parsed_json=[{"condition": "credit_score < 500", "consequence": "REJECT"}],
            error=None,
        )
    )

    resp = manager.generate("Test prompt")
    assert resp.success is True
    assert resp.provider_name == "ollama"
    assert resp.fallback_occurred is True
    assert "ollama" in resp.fallback_chain


def test_fallback_all_to_offline():
    manager = ProviderManager()

    # All external providers unavailable
    manager.providers["openrouter"].is_available = MagicMock(return_value=False)
    manager.providers["anthropic"].is_available = MagicMock(return_value=False)
    manager.providers["ollama"].is_available = MagicMock(return_value=False)

    prompt = (
        "EVIDENCE PACKAGE SUMMARY:\n"
        "- Rule: credit_score < 600 and debt_ratio > 0.4 -> REJECT (Observations: 48, Evidence IDs: [\"EV-S-002\"], Lines: [14])"
    )
    resp = manager.generate(prompt)

    assert resp.success is True
    assert resp.provider_name == "offline"
    assert resp.fallback_occurred is True
    assert len(resp.parsed_json) > 0


# ==============================================================================
# 4. Explicit Provider Selection & Error Handling
# ==============================================================================

def test_explicit_provider_selection_without_fallback():
    manager = ProviderManager()
    manager.providers["openrouter"].is_available = MagicMock(return_value=False)

    # Explicitly requesting openrouter with fallback disabled
    with patch("common.config.settings.allow_auto_fallback", False):
        resp = manager.generate("Prompt", preferred_provider="openrouter")
        assert resp.success is False
        assert "not configured or available" in (resp.error or "")


# ==============================================================================
# 5. LLMCandidateGenerator Provenance Recording
# ==============================================================================

@patch("llm.manager.ProviderManager.generate")
def test_candidate_generator_provenance_attachment(mock_generate):
    pkg = _get_sample_evidence_package()
    static_id_14 = next((s.evidence_id for s in pkg.static_evidence_items if getattr(s, "line", None) == 14), "EV-S-002")

    mock_generate.return_value = MagicMock(
        success=True,
        provider_name="openrouter",
        model_name="anthropic/claude-3.5-sonnet",
        latency_ms=250.0,
        fallback_occurred=False,
        fallback_chain=["openrouter"],
        parsed_json=[{
            "condition": "credit_score < 600 and debt_ratio > 0.4",
            "consequence": "REJECT",
            "severity": "critical",
            "supporting_evidence_ids": [static_id_14],
            "source_lines": [14],
        }],
        error=None,
    )

    generator = LLMCandidateGenerator()
    candidates = generator.propose_candidates(pkg)

    assert len(candidates) > 0
    cand = candidates[0]
    assert cand.reproducibility["provider"] == "openrouter"
    assert cand.reproducibility["model"] == "anthropic/claude-3.5-sonnet"
    assert cand.reproducibility["generator_type"] == "llm"
    assert cand.confidence_components["provider"] == "openrouter"


# ==============================================================================
# 6. Keyless Operation & Provider Status Endpoint
# ==============================================================================

def test_provider_status_sanitization():
    manager = get_provider_manager()
    status = manager.get_status()

    assert "providers" in status
    assert "openrouter" in status["providers"]
    assert "anthropic" in status["providers"]
    assert "ollama" in status["providers"]
    assert "offline" in status["providers"]
    assert "active_provider" in status

    # Ensure no API keys or secrets are leaked in the status response
    status_str = json.dumps(status)
    assert "api_key" not in status_str.lower()
    assert "secret" not in status_str.lower()


def test_openrouter_missing_key_is_not_configured_or_available():
    provider = OpenRouterProvider(api_key="")

    assert provider.is_configured() is False
    assert provider.check_connectivity() is False


def test_openrouter_configured_but_unreachable_is_not_available():
    provider = OpenRouterProvider(api_key="test-openrouter-key")

    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        assert provider.is_configured() is True
        assert provider.check_connectivity() is False


def test_openrouter_connectivity_success_is_available():
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.read.return_value = b"{\"data\": []}"
    provider = OpenRouterProvider(api_key="test-openrouter-key")

    with patch("urllib.request.urlopen", return_value=mock_response):
        assert provider.is_configured() is True
        assert provider.check_connectivity() is True


def test_openrouter_status_is_sanitized_and_keeps_secret_out_of_logs(caplog):
    secret = "test-openrouter-key"
    with patch.object(settings, "openrouter_api_key", secret), \
         patch.object(OpenRouterProvider, "check_connectivity", return_value=False):
        status = ProviderManager().get_status()

    status_json = json.dumps(status)
    assert status["providers"]["openrouter"]["configured"] is True
    assert status["providers"]["openrouter"]["available"] is False
    assert secret not in status_json
    assert secret not in caplog.text


# ==============================================================================
# 7. Downstream Schema Consistency Across Providers
# ==============================================================================

@patch("llm.manager.ProviderManager.generate")
def test_downstream_schema_consistency_across_providers(mock_generate):
    pkg = _get_sample_evidence_package()
    static_id_14 = next((s.evidence_id for s in pkg.static_evidence_items if getattr(s, "line", None) == 14), "EV-S-002")

    # Test that both OpenRouter and Ollama mock outputs produce identical downstream CandidateInvariants
    for p_name, model_name in [("openrouter", "anthropic/claude-3.5-sonnet"), ("ollama", "qwen2.5-coder:7b")]:
        mock_generate.return_value = MagicMock(
            success=True,
            provider_name=p_name,
            model_name=model_name,
            latency_ms=150.0,
            fallback_occurred=False,
            fallback_chain=[p_name],
            parsed_json=[{
                "condition": "debt_ratio > 0.4 and credit_score < 600",
                "consequence": "REJECT",
                "severity": "critical",
                "supporting_evidence_ids": [static_id_14],
                "source_lines": [14],
            }],
            error=None,
        )

        graduated, unconfirmed = run_mining_pipeline(
            evidence_package=pkg,
            legacy_fn=legacy_loan_approval.evaluate_loan,
            field_bounds=FIELD_BOUNDS,
            already_validated=[],
            use_atlas=False,
            use_llm=True,
        )

        assert len(graduated) > 0
        inv = graduated[0]
        assert inv.condition == "credit_score < 600 and debt_ratio > 0.4"
        assert inv.consequence == "REJECT"
        assert inv.confidence >= 0.80
        assert inv.reproducibility["provider"] == p_name
