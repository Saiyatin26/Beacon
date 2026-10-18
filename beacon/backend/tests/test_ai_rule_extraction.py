from types import SimpleNamespace

from application.input_discovery import InputDiscoveryEngine, InputDiscoveryStatus
from application.repository_service import RepositoryAnalysisReport, RepositoryProvenance


class FakeProviderManager:
    def __init__(self, *, alignment_status="MATCH", generated_cases=None, provider="openrouter"):
        self.alignment_status = alignment_status
        self.generated_cases = generated_cases or [
            {"rule_id": "EDABC-001", "values": {"STATUS": "Y"}}
        ]
        self.provider = provider
        self.prompts = []

    def generate(self, prompt, json_mode=True, preferred_provider=None, allow_fallback=True):
        self.prompts.append((prompt, json_mode, preferred_provider, allow_fallback))
        if "Analyze the legacy/reference implementation independently" in prompt:
            parsed = {
                "rules": [
                    {
                        "rule_id": "LEGACY-1",
                        "description": "A Y status sets the message to approved.",
                        "observable_effect": "MESSAGE is APPROVED when STATUS is Y.",
                        "input_fields": ["STATUS"],
                        "source_path": "program.cbl",
                        "source_line": 2,
                        "source_excerpt": "IF STATUS = 'Y'",
                        "effect_source_path": "program.cbl",
                        "effect_source_line": 3,
                        "effect_source_excerpt": "    MOVE 'APPROVED' TO MESSAGE",
                        "input_condition": {"field": "STATUS", "operator": "==", "value": "Y"},
                        "expected_output": {"field": "MESSAGE", "value": "APPROVED"},
                    }
                ],
                "gaps": [],
            }
        elif "Analyze the modern/target implementation independently" in prompt:
            parsed = {
                "rules": [
                    {
                        "rule_id": "MODERN-1",
                        "description": "A Y status sets the message to approved.",
                        "observable_effect": "MESSAGE is APPROVED when STATUS is Y.",
                        "input_fields": ["STATUS"],
                        "source_path": "modern.py",
                        "source_line": 2,
                        "source_excerpt": 'if inputs.get("STATUS") == "Y":',
                        "effect_source_path": "modern.py",
                        "effect_source_line": 3,
                        "effect_source_excerpt": '        return {"MESSAGE": "APPROVED"}',
                        "input_condition": {"field": "STATUS", "operator": "==", "value": "Y"},
                        "expected_output": {"field": "MESSAGE", "value": "APPROVED"},
                    }
                ],
                "gaps": [],
            }
        elif "Align independently extracted" in prompt:
            if self.alignment_status == "MATCH":
                alignment = {
                    "legacy_rule_id": "LEGACY-1",
                    "modern_rule_id": "MODERN-1",
                    "status": "MATCH",
                    "rationale": "Both source excerpts express the same status condition.",
                }
            else:
                alignment = {
                    "legacy_rule_id": "LEGACY-1",
                    "modern_rule_id": None,
                    "status": "LEGACY_ONLY",
                    "rationale": "No matching rule exists in the modern source.",
                }
            parsed = {"alignments": [alignment]}
        else:
            parsed = {"test_cases": self.generated_cases}

        return SimpleNamespace(
            requested_provider=preferred_provider,
            provider_name=self.provider,
            model_name="test-model",
            fallback_occurred=False,
            error_category=None,
            success=True,
            parsed_json=parsed,
        )


def _report(repo_id, root, language):
    return RepositoryAnalysisReport(
        repository_id=repo_id,
        provenance=RepositoryProvenance(
            source_url=str(root),
            source_type="directory",
            resolved_revision="test",
            content_hash=f"{repo_id}-hash",
            retrieval_timestamp="test",
            local_path=str(root),
        ),
        languages=[language],
    )


def _paired_sources(tmp_path):
    legacy_root = tmp_path / "legacy"
    modern_root = tmp_path / "modern"
    legacy_root.mkdir()
    modern_root.mkdir()
    legacy_source = legacy_root / "program.cbl"
    legacy_source.write_text(
        "PROCEDURE DIVISION.\n"
        "IF STATUS = 'Y'\n"
        "    MOVE 'APPROVED' TO MESSAGE\n"
        "END-IF.\n",
        encoding="utf-8",
    )
    modern_source = modern_root / "modern.py"
    modern_source.write_text(
        'def run(inputs):\n'
        '    if inputs.get("STATUS") == "Y":\n'
        '        return {"MESSAGE": "APPROVED"}\n'
        '    return {"MESSAGE": "REJECTED"}\n',
        encoding="utf-8",
    )
    return (
        _report("legacy", legacy_root, "cobol"),
        _report("modern", modern_root, "python"),
        legacy_source,
        modern_source,
    )


def _discover(tmp_path, monkeypatch, manager):
    monkeypatch.setattr(
        "application.input_discovery.settings",
        SimpleNamespace(llm_provider="openrouter"),
    )
    monkeypatch.setattr("llm.manager.get_provider_manager", lambda: manager)
    legacy_report, modern_report, legacy_source, modern_source = _paired_sources(tmp_path)
    result = InputDiscoveryEngine().discover_inputs(
        legacy_report,
        modern_report,
        legacy_entrypoint_file=legacy_source,
        modern_entrypoint_file=modern_source,
    )
    return result, manager


def test_full_beacon_extracts_both_sides_and_records_source_and_provider_provenance(
    tmp_path, monkeypatch
):
    result, manager = _discover(tmp_path, monkeypatch, FakeProviderManager())

    assert result.status == InputDiscoveryStatus.SUCCESS
    assert result.discovery_method == "DUAL_SOURCE_RULE_DIRECTED_TESTING"
    assert len(result.test_inputs) == 1
    assert result.test_inputs[0].values == {"STATUS": "Y"}
    assert result.test_inputs[0].origin == "ai_generated"
    assert result.test_inputs[0].provenance["condition_provenance"] == "EDABC-001"

    rule = result.provenance["ai_mined_rules"][0]
    assert rule["source_evidence"]["legacy"]["path"] == "program.cbl"
    assert rule["source_evidence"]["modern"]["path"] == "modern.py"
    assert rule["expected_behavior"]["legacy"]["expected_output"] == {
        "field": "MESSAGE",
        "value": "APPROVED",
    }
    assert rule["alignment_status"] == "MATCH"
    assert set(result.provenance["llm_provider"]["provider_calls"]) == {
        "legacy",
        "modern",
        "alignment",
        "test_generation",
    }
    assert len(manager.prompts) == 4
    assert all(call[2:] == ("openrouter", False) for call in manager.prompts)


def test_ungrounded_test_fields_are_rejected_without_losing_valid_cases(tmp_path, monkeypatch):
    manager = FakeProviderManager(
        generated_cases=[
            {"rule_id": "EDABC-001", "values": {"STATUS": "Y"}},
            {"rule_id": "EDABC-001", "values": {"INVENTED-FIELD": "x"}},
        ]
    )
    result, _ = _discover(tmp_path, monkeypatch, manager)

    assert result.status == InputDiscoveryStatus.SUCCESS
    assert [item.values for item in result.test_inputs] == [{"STATUS": "Y"}]


def test_duplicate_rule_directed_inputs_are_deduplicated(tmp_path, monkeypatch):
    manager = FakeProviderManager(
        generated_cases=[
            {"rule_id": "EDABC-001", "values": {"STATUS": "Y"}},
            {"rule_id": "EDABC-001", "values": {"STATUS": "Y"}},
        ]
    )
    result, _ = _discover(tmp_path, monkeypatch, manager)

    assert result.status == InputDiscoveryStatus.SUCCESS
    assert result.inputs_count == 1


def test_unmatched_rules_block_full_beacon_discovery(tmp_path, monkeypatch):
    result, manager = _discover(
        tmp_path,
        monkeypatch,
        FakeProviderManager(alignment_status="LEGACY_ONLY"),
    )

    assert result.status == InputDiscoveryStatus.INSUFFICIENT_COVERAGE
    assert result.test_inputs == []
    assert result.provenance["rule_alignments"][0]["status"] == "LEGACY_ONLY"
    assert len(manager.prompts) == 3


def test_ai_provider_fallback_is_not_accepted_as_rule_evidence(tmp_path, monkeypatch):
    result, _ = _discover(
        tmp_path,
        monkeypatch,
        FakeProviderManager(provider="offline"),
    )

    assert result.status == InputDiscoveryStatus.FAILED
    assert result.provenance["rule_extraction_status"] == "SOURCE_RULE_EXTRACTION_FAILED"
    assert "did not return an accepted JSON response" in result.diagnostic_message
