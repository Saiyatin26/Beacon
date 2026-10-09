from types import SimpleNamespace

from application.input_discovery import InputDiscoveryEngine


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
