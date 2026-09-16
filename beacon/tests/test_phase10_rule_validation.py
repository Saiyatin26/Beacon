"""BEACON V2 — Phase 10 Rule Validation & Anti-Fabrication Tests.

Verifies:
1. LLM inventing a non-existent rule (e.g. RULE-999) is rejected by validation.
2. System never manufactures fallback pseudo-rules like RULE-OBSERVED or RULE-UNKNOWN.
3. Only verified Phase 5/6/7 rules are accepted in rule impacts.
"""

import pytest
from evaluation.models import BehaviorDimension
from intelligence.models import (
    ExplanationContext,
    GenerationMetadata,
)
from intelligence.validation import ExplanationValidator


def test_hallucinated_rule_id_is_rejected():
    """Verify that a hallucinated rule ID not in the OracleSet/context is rejected."""
    context = ExplanationContext(
        certification_id="CERT-RULE-001",
        application_id="app_rule_test",
        authoritative_verdict="NOT_CERTIFIED",
        equivalence_score=0.8,
        unique_inputs_count=5,
        matching_cases_count=4,
        regression_cases_count=1,
        dimensions_evaluated=[BehaviorDimension.OUTPUT],
        valid_evidence_ids=[],
        valid_rule_ids=["RULE-REAL-101", "RULE-REAL-102"],
        valid_input_ids=["INP-1"],
    )

    validator = ExplanationValidator()
    metadata = GenerationMetadata(provider="test", model="mock", generation_mode="LLM")

    raw_payload = {
        "executive_summary": "Summary",
        "behavioral_summary": "Summary",
        "rule_impacts": [
            {
                "rule_id": "RULE-HALLUCINATED-999",  # NOT in valid_rule_ids
                "rule_description": "Fake invariant",
                "status": "VIOLATED",
                "observed_behavior": "...",
            },
            {
                "rule_id": "RULE-REAL-101",  # VALID
                "rule_description": "Valid invariant",
                "status": "VIOLATED",
                "observed_behavior": "...",
            },
        ],
    }

    is_valid, errors, exp = validator.validate_and_sanitize_explanation(
        raw_payload=raw_payload,
        context=context,
        metadata=metadata,
    )

    assert is_valid is True
    assert exp is not None
    # Only the valid rule should be kept
    assert len(exp.rule_impacts) == 1
    assert exp.rule_impacts[0].rule_id == "RULE-REAL-101"
    assert any("Hallucinated rule_id 'RULE-HALLUCINATED-999' rejected" in e for e in errors)
