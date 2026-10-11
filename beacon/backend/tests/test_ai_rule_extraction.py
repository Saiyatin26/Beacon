from types import SimpleNamespace

from application.input_discovery import InputDiscoveryEngine
from application.repository_service import RepositoryAnalysisReport, RepositoryProvenance


class FakeProviderManager:
    def __init__(self, response):
        self.response = response

    def generate(self, prompt, json_mode=True):
        return self.response


def test_rule_extraction_keeps_only_deduplicated_source_anchored_ai_rules(tmp_path, monkeypatch):
    source = tmp_path / "program.cbl"
    source.write_text(
        "       PROCEDURE DIVISION.\n"
        "           IF WS-STATUS = 'Y'\n"
        "               MOVE 'APPROVED' TO WS-MESSAGE\n"
        "           END-IF.\n",
        encoding="utf-8",
    )
    response = SimpleNamespace(
        requested_provider="openrouter",
        provider_name="openrouter",
        model_name="test-model",
        fallback_occurred=False,
        fallback_reason=None,
        success=True,
        parsed_json={
            "rules": [
                {
                    "description": "A Y status produces an approval message.",
                    "source_location": "Line 2",
                    "source_excerpt": "IF WS-STATUS = 'Y'",
                },
                {
                    "description": "A Y status produces an approval message.",
                    "source_location": "Line 2",
                    "source_excerpt": "IF WS-STATUS = 'Y'",
                },
                {
                    "description": "Invented behavior.",
                    "source_location": "Line 2",
                    "source_excerpt": "IF THIS-IS-NOT-IN-SOURCE",
                },
            ],
            "test_cases": [
                {"WS-STATUS": "Y", "__condition_provenance": "candidate-1"},
                {"UNDECLARED-FIELD": "Y", "__condition_provenance": "candidate-1"},
            ],
        },
    )
    monkeypatch.setattr("llm.manager.get_provider_manager", lambda: FakeProviderManager(response))

    cases, rules, metadata = InputDiscoveryEngine()._mine_cobol_conditions_with_ai(source)
    repeated_cases, repeated_rules, _ = InputDiscoveryEngine()._mine_cobol_conditions_with_ai(source)

    assert [rule["rule_id"] for rule in rules] == ["AI-RULE-001"]
    assert rules[0]["source"] == "AI_CANDIDATE_SOURCE_VALIDATED"
    assert cases == [{"WS-STATUS": "Y", "__condition_provenance": "candidate-1"}]
    assert repeated_rules == rules
    assert repeated_cases == cases
    assert metadata["rule_extraction_status"] == "SUCCESS"
    assert metadata["validated_rule_count"] == 1


def test_offline_rule_discovery_does_not_fabricate_ast_rules_or_inputs(tmp_path, monkeypatch):
    source = tmp_path / "program.cbl"
    source.write_text(
        "       PROCEDURE DIVISION.\n"
        "           IF WS-STATUS = 'Y'\n"
        "               MOVE 'APPROVED' TO WS-MESSAGE\n"
        "           END-IF.\n",
        encoding="utf-8",
    )
    response = SimpleNamespace(
        requested_provider="auto",
        provider_name="offline",
        model_name="deterministic",
        fallback_occurred=True,
        fallback_reason="No remote provider succeeded.",
        success=True,
        parsed_json={
            "rules": [{"description": "Offline fallback must not be used."}],
            "test_cases": [{"WS-STATUS": "Y", "__condition_provenance": "RULE-001"}],
        },
    )
    monkeypatch.setattr("llm.manager.get_provider_manager", lambda: FakeProviderManager(response))

    cases, rules, metadata = InputDiscoveryEngine()._mine_cobol_conditions_with_ai(source)

    assert cases == []
    assert rules == []
    assert metadata["rule_extraction_status"] == "AI_PROVIDER_UNAVAILABLE"


def test_discovery_uses_resolved_entrypoints_for_ai_generated_test_inputs(tmp_path, monkeypatch):
    legacy_root = tmp_path / "legacy"
    modern_root = tmp_path / "modern"
    legacy_root.mkdir()
    modern_root.mkdir()
    copybook = legacy_root / "AAA.CPY"
    copybook.write_text("       01 COPYBOOK-FIELD PIC X.\n", encoding="utf-8")
    helper_source = modern_root / "aaa_helper.py"
    helper_source.write_text("def helper():\n    return True\n", encoding="utf-8")
    legacy_source = legacy_root / "TESTPROG.cbl"
    legacy_source.write_text(
        "       PROGRAM-ID. TESTPROG.\n"
        "       PROCEDURE DIVISION.\n"
        "           IF ACCT-STATUS = 'Y'\n"
        "               MOVE 'APPROVED' TO WS-MESSAGE\n"
        "           END-IF.\n",
        encoding="utf-8",
    )
    modern_source = modern_root / "run_vector.py"
    modern_source.write_text(
        "def run_vector(inputs):\n"
        "    return {'SCENARIO': inputs.get('SCENARIO')}\n",
        encoding="utf-8",
    )
    response = SimpleNamespace(
        requested_provider="openrouter",
        provider_name="openrouter",
        model_name="test-model",
        fallback_occurred=False,
        fallback_reason=None,
        success=True,
        parsed_json={
            "rules": [
                {
                    "description": "A Y account status produces an approval message.",
                    "source_location": "Line 3",
                    "source_excerpt": "IF ACCT-STATUS = 'Y'",
                }
            ],
            "test_cases": [
                {
                    "ACCT-STATUS": "Y",
                    "SCENARIO": "LOOKUP_ACCOUNT",
                    "__condition_provenance": "candidate-1",
                }
            ],
        },
    )
    fake_manager = FakeProviderManager(response)
    monkeypatch.setattr("llm.manager.get_provider_manager", lambda: fake_manager)

    def make_report(repo_id, root, language):
        return RepositoryAnalysisReport(
            repository_id=repo_id,
            provenance=RepositoryProvenance(
                source_url=str(root),
                source_type="directory",
                resolved_revision="test",
                content_hash=repo_id,
                retrieval_timestamp="test",
                local_path=str(root),
            ),
            languages=[language],
        )

    result = InputDiscoveryEngine().discover_inputs(
        make_report("legacy", legacy_root, "cobol"),
        make_report("modern", modern_root, "python"),
        legacy_entrypoint_file=legacy_source,
        modern_entrypoint_file=modern_source,
    )

    assert result.status.value == "SUCCESS"
    assert result.discovery_method == "AI_PROPOSED_INPUTS_SOURCE_VALIDATED"
    assert result.inputs_count == 1
    assert result.test_inputs[0].values == {
        "ACCT-STATUS": "Y",
        "SCENARIO": "LOOKUP_ACCOUNT",
    }
    assert result.test_inputs[0].origin == "ai_generated"
    assert result.test_inputs[0].provenance["condition_provenance"] == "candidate-1"
    assert result.provenance["ai_mined_rule_count"] == 1
