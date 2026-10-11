"""Unit and integration tests for AI-only input provenance, validation, and tamper detection."""

import hashlib
import json
from pathlib import Path
import pytest

from application.input_discovery import InputDiscoveryEngine, InputDiscoveryStatus
from application.repository_service import (
    RepositoryAnalysisReport,
    DiscoveredInputAsset,
    RepositoryIdentity,
    RepositoryProvenance,
)
from certification.models import (
    CertificationTestInput,
    compute_input_set_canonical_hash,
)
from llm.base import LLMResponse


def make_dummy_analysis_report(repo_path: Path, has_fixtures: bool = False) -> RepositoryAnalysisReport:
    cand_assets = []
    if has_fixtures:
        fixture_file = repo_path / "dataset" / "fixture.json"
        fixture_file.parent.mkdir(parents=True, exist_ok=True)
        fixture_file.write_text(json.dumps([{"acct_id": "999999", "status": "ACTIVE"}]), encoding="utf-8")
        cand_assets.append(
            DiscoveredInputAsset(
                file_path=str(fixture_file),
                relative_path="dataset/fixture.json",
                format="json",
                case_count=1,
                sample_values=[{"acct_id": "999999", "status": "ACTIVE"}],
            )
        )

    prov = RepositoryProvenance(
        source_url=str(repo_path),
        canonical_source_url=str(repo_path),
        source_type="directory",
        local_path=str(repo_path),
        resolved_revision="main",
        retrieval_timestamp="2026-10-11T00:00:00Z",
        content_hash=hashlib.sha256(b"dummy_content").hexdigest(),
        identity=RepositoryIdentity(
            canonical_url=str(repo_path),
            resolved_revision="main",
            content_hash=hashlib.sha256(b"dummy_content").hexdigest(),
        ),
    )
    return RepositoryAnalysisReport(
        repository_id="repo-test",
        provenance=prov,
        languages=["COBOL"],
        frameworks=["CICS"],
        input_candidates=cand_assets,
    )


def test_full_beacon_ignores_fixtures_and_requires_openrouter_inputs(monkeypatch, tmp_path):
    """Verifies that in FULL_BEACON mode, repository fixtures are NOT accepted into the
    authoritative input set, and inputs must originate exclusively from OpenRouter.
    """
    engine = InputDiscoveryEngine()

    cbl_file = tmp_path / "TESTPROG.cbl"
    cbl_file.write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. TESTPROG.\n       PROCEDURE DIVISION.\n           MOVE 100 TO ACCT-NUM.\n           IF ACCT-NUM = 100\n              DISPLAY 'OK'\n           END-IF.\n           GOBACK.\n", encoding="utf-8")

    legacy_analysis = make_dummy_analysis_report(tmp_path, has_fixtures=True)
    modern_analysis = make_dummy_analysis_report(tmp_path, has_fixtures=False)

    # Mock OpenRouter successful generation
    from llm.manager import ProviderManager

    def mock_generate(self, prompt, **kwargs):
        return LLMResponse(
            raw_text='{"rules": [{"rule_id": "RULE-001", "description": "Check account", "source_location": "Line 5", "source_excerpt": "IF ACCT-NUM = 100"}], "test_cases": [{"ACCT-NUM": 100, "__condition_provenance": "RULE-001"}]}',
            parsed_json={
                "rules": [{"rule_id": "RULE-001", "description": "Check account", "source_location": "Line 5", "source_excerpt": "IF ACCT-NUM = 100"}],
                "test_cases": [{"ACCT-NUM": 100, "__condition_provenance": "RULE-001"}],
            },
            provider_name="openrouter",
            model_name="anthropic/claude-3.5-sonnet",
            requested_provider="openrouter",
            success=True,
        )

    monkeypatch.setattr(ProviderManager, "generate", mock_generate)

    result = engine.discover_inputs(
        legacy_analysis=legacy_analysis,
        modern_analysis=modern_analysis,
        legacy_entrypoint_file=cbl_file,
        evaluation_mode="FULL_BEACON",
    )

    assert result.status == InputDiscoveryStatus.SUCCESS
    assert result.inputs_count == 1
    accepted_input = result.test_inputs[0]
    # Authoritative input MUST be AI-generated from OpenRouter, NOT the fixture {"acct_id": "999999"}
    assert accepted_input.origin == "ai_generated"
    assert accepted_input.values == {"ACCT-NUM": 100}
    assert accepted_input.provenance["requested_provider"] == "openrouter"
    assert accepted_input.provenance["actual_provider"] == "openrouter"
    assert accepted_input.provenance["validation_status"] == "ACCEPTED"


def test_ungrounded_fields_are_rejected(monkeypatch, tmp_path):
    """Verifies that candidate fields not present in source vocabulary are rejected."""
    engine = InputDiscoveryEngine()

    cbl_file = tmp_path / "TESTPROG.cbl"
    cbl_file.write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. TESTPROG.\n       PROCEDURE DIVISION.\n           IF VALID-FIELD = 1\n              DISPLAY 'OK'\n           END-IF.\n           GOBACK.\n", encoding="utf-8")

    legacy_analysis = make_dummy_analysis_report(tmp_path)
    modern_analysis = make_dummy_analysis_report(tmp_path)

    from llm.manager import ProviderManager

    def mock_generate(self, prompt, **kwargs):
        return LLMResponse(
            raw_text="{}",
            parsed_json={
                "rules": [{"rule_id": "RULE-001", "description": "Check field", "source_location": "Line 4", "source_excerpt": "IF VALID-FIELD = 1"}],
                "test_cases": [
                    {"VALID-FIELD": 1, "__condition_provenance": "RULE-001"},
                    {"UNGROUNDED-INVENTED-FIELD": "xyz", "__condition_provenance": "RULE-001"},
                ],
            },
            provider_name="openrouter",
            model_name="anthropic/claude-3.5-sonnet",
            requested_provider="openrouter",
            success=True,
        )

    monkeypatch.setattr(ProviderManager, "generate", mock_generate)

    result = engine.discover_inputs(
        legacy_analysis=legacy_analysis,
        modern_analysis=modern_analysis,
        legacy_entrypoint_file=cbl_file,
        evaluation_mode="FULL_BEACON",
    )

    assert result.status == InputDiscoveryStatus.SUCCESS
    # Only the valid candidate was accepted; the ungrounded field candidate was rejected
    assert result.inputs_count == 1
    assert result.test_inputs[0].values == {"VALID-FIELD": 1}
    assert result.provenance["rejected_count"] == 1
    assert "UNGROUNDED_FIELDS" in result.provenance["rejected_details"][0]["reason"]


def test_duplicate_ai_candidates_are_deduplicated(monkeypatch, tmp_path):
    """Verifies that duplicate candidate inputs are deterministically deduplicated."""
    engine = InputDiscoveryEngine()

    cbl_file = tmp_path / "TESTPROG.cbl"
    cbl_file.write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. TESTPROG.\n       PROCEDURE DIVISION.\n           IF FIELD-A = 1\n              DISPLAY 'OK'\n           END-IF.\n           GOBACK.\n", encoding="utf-8")

    legacy_analysis = make_dummy_analysis_report(tmp_path)
    modern_analysis = make_dummy_analysis_report(tmp_path)

    from llm.manager import ProviderManager

    def mock_generate(self, prompt, **kwargs):
        return LLMResponse(
            raw_text="{}",
            parsed_json={
                "rules": [{"rule_id": "RULE-001", "description": "Check field", "source_location": "Line 4", "source_excerpt": "IF FIELD-A = 1"}],
                "test_cases": [
                    {"FIELD-A": 1, "__condition_provenance": "RULE-001"},
                    {"FIELD-A": 1, "__condition_provenance": "RULE-001"}, # duplicate
                ],
            },
            provider_name="openrouter",
            model_name="anthropic/claude-3.5-sonnet",
            requested_provider="openrouter",
            success=True,
        )

    monkeypatch.setattr(ProviderManager, "generate", mock_generate)

    result = engine.discover_inputs(
        legacy_analysis=legacy_analysis,
        modern_analysis=modern_analysis,
        legacy_entrypoint_file=cbl_file,
        evaluation_mode="FULL_BEACON",
    )

    assert result.status == InputDiscoveryStatus.SUCCESS
    assert result.inputs_count == 1
    assert result.provenance["duplicate_count"] == 1


def test_input_set_hash_tamper_detection():
    """Verifies that altering an accepted input case invalidates the input set canonical hash."""
    inp1 = CertificationTestInput(input_id="INP-1", values={"field": "value1"})
    inp2 = CertificationTestInput(input_id="INP-2", values={"field": "value2"})

    canonical_hash = compute_input_set_canonical_hash([inp1, inp2])

    # Tamper with inp1 values
    tampered_inp1 = CertificationTestInput(input_id="INP-1", values={"field": "altered_value"})
    tampered_hash = compute_input_set_canonical_hash([tampered_inp1, inp2])

    assert canonical_hash != tampered_hash
