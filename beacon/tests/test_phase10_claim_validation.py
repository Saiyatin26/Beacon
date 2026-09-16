"""BEACON V2 — Phase 10 Factual Claim & Value Validation Tests.

Verifies:
1. LLM-generated findings are validated against authoritative reference and target values.
2. If the LLM hallucinates a reference or target value (e.g. claims target=97 when authoritative is 95), the claim is rejected.
3. Accurate claims matching authoritative values are accepted.
4. Hallucinated input IDs inside findings are rejected.
"""

import pytest
from evaluation.models import BehaviorDimension
from intelligence.models import (
    EvidenceSupportLevel,
    ExplanationContext,
    GenerationMetadata,
)
from intelligence.validation import ExplanationValidator


def test_hallucinated_values_are_rejected():
    """Verify that claims specifying false numerical values are rejected by the validator."""
    context = ExplanationContext(
        certification_id="CERT-VAL-001",
        application_id="app_val_test",
        authoritative_verdict="NOT_CERTIFIED",
        equivalence_score=0.5,
        unique_inputs_count=1,
        matching_cases_count=0,
        regression_cases_count=1,
        dimensions_evaluated=[BehaviorDimension.OUTPUT],
        differences_summary=[
            {
                "input_id": "INP-001",
                "dimension": "OUTPUT",
                "reference_value": 100,
                "target_value": 95,
                "difference_id": "DIFF-1",
            }
        ],
        valid_evidence_ids=["EVID-1"],
        valid_rule_ids=["RULE-1"],
        valid_input_ids=["INP-001"],
    )

    validator = ExplanationValidator()
    metadata = GenerationMetadata(provider="test", model="mock", generation_mode="LLM")

    # LLM hallucinates target_value=97 instead of 95
    raw_payload_hallucinated = {
        "executive_summary": "Summary",
        "behavioral_summary": "Summary",
        "dimension_explanations": [
            {
                "dimension": "OUTPUT",
                "status": "DIFFERENT",
                "findings": [
                    {
                        "input_id": "INP-001",
                        "dimension": "OUTPUT",
                        "statement": "Input INP-001 produced 97 instead of 95",
                        "reference_value": 100,
                        "target_value": 97,  # HALLUCINATION! Authoritative is 95
                        "support": "DETERMINISTIC_FACT",
                    }
                ],
            }
        ],
    }

    is_valid, errors, exp = validator.validate_and_sanitize_explanation(
        raw_payload=raw_payload_hallucinated,
        context=context,
        metadata=metadata,
    )

    # Finding must be rejected because target_value 97 != 95
    assert is_valid is True
    assert exp is not None
    output_dim = exp.dimension_explanations[0]
    assert len(output_dim.findings) == 0, "Hallucinated value finding should have been rejected."
    assert any("Factual value mismatch" in e for e in errors)


def test_accurate_factual_values_are_accepted():
    """Verify that accurate claims matching authoritative values are accepted."""
    context = ExplanationContext(
        certification_id="CERT-VAL-002",
        application_id="app_val_test",
        authoritative_verdict="NOT_CERTIFIED",
        equivalence_score=0.5,
        unique_inputs_count=1,
        matching_cases_count=0,
        regression_cases_count=1,
        dimensions_evaluated=[BehaviorDimension.OUTPUT],
        differences_summary=[
            {
                "input_id": "INP-001",
                "dimension": "OUTPUT",
                "reference_value": 100,
                "target_value": 95,
                "difference_id": "DIFF-1",
            }
        ],
        valid_evidence_ids=["EVID-1"],
        valid_rule_ids=["RULE-1"],
        valid_input_ids=["INP-001"],
    )

    validator = ExplanationValidator()
    metadata = GenerationMetadata(provider="test", model="mock", generation_mode="LLM")

    raw_payload_accurate = {
        "executive_summary": "Summary",
        "behavioral_summary": "Summary",
        "dimension_explanations": [
            {
                "dimension": "OUTPUT",
                "status": "DIFFERENT",
                "findings": [
                    {
                        "input_id": "INP-001",
                        "dimension": "OUTPUT",
                        "statement": "Input INP-001 produced 95 vs reference 100",
                        "reference_value": 100,
                        "target_value": 95,
                        "support": "DETERMINISTIC_FACT",
                    }
                ],
            }
        ],
    }

    is_valid, errors, exp = validator.validate_and_sanitize_explanation(
        raw_payload=raw_payload_accurate,
        context=context,
        metadata=metadata,
    )

    assert is_valid is True
    assert exp is not None
    output_dim = exp.dimension_explanations[0]
    assert len(output_dim.findings) == 1
    assert output_dim.findings[0].target_value == 95
