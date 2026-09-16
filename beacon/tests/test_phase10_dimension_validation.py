"""BEACON V2 — Phase 10 Dimension & Status Validation Tests.

Verifies:
1. Invalid dimensions (e.g. MAGIC_DIMENSION) are strictly rejected and NEVER coerced into OUTPUT.
2. Missing dimension statuses are NOT defaulted to PASS. They are derived from authoritative context or marked UNKNOWN.
"""

import pytest
from evaluation.models import BehaviorDimension
from intelligence.models import (
    ExplanationContext,
    GenerationMetadata,
    MissingEvidence,
)
from intelligence.validation import ExplanationValidator


def test_invalid_dimension_is_rejected_without_coercion():
    """Verify that an invalid dimension is rejected and never converted to OUTPUT."""
    context = ExplanationContext(
        certification_id="CERT-DIM-001",
        application_id="app_dim_test",
        authoritative_verdict="CERTIFIED",
        equivalence_score=1.0,
        unique_inputs_count=5,
        matching_cases_count=5,
        regression_cases_count=0,
        dimensions_evaluated=[BehaviorDimension.OUTPUT],
        valid_evidence_ids=[],
        valid_rule_ids=[],
        valid_input_ids=[],
    )

    validator = ExplanationValidator()
    metadata = GenerationMetadata(provider="test", model="mock", generation_mode="LLM")

    raw_payload = {
        "executive_summary": "Summary",
        "behavioral_summary": "Summary",
        "dimension_explanations": [
            {
                "dimension": "MAGIC_COSMIC_DIMENSION",  # INVALID!
                "status": "PASS",
                "reference_summary": "...",
            }
        ],
    }

    is_valid, errors, exp = validator.validate_and_sanitize_explanation(
        raw_payload=raw_payload,
        context=context,
        metadata=metadata,
    )

    assert is_valid is True
    assert exp is not None
    # Dimension explanations must NOT contain MAGIC_COSMIC_DIMENSION or coerced OUTPUT
    assert len(exp.dimension_explanations) == 0
    assert any("Invalid dimension 'MAGIC_COSMIC_DIMENSION' rejected" in e for e in errors)


def test_missing_status_does_not_default_to_pass_when_differences_exist():
    """Verify that when status is omitted on a differing dimension, it becomes DIFFERENT, never PASS."""
    context = ExplanationContext(
        certification_id="CERT-DIM-002",
        application_id="app_dim_test",
        authoritative_verdict="NOT_CERTIFIED",
        equivalence_score=0.8,
        unique_inputs_count=5,
        matching_cases_count=4,
        regression_cases_count=1,
        dimensions_evaluated=[BehaviorDimension.OUTPUT],
        differences_summary=[
            {
                "input_id": "INP-1",
                "dimension": "OUTPUT",
                "reference_value": "A",
                "target_value": "B",
            }
        ],
        valid_evidence_ids=[],
        valid_rule_ids=[],
        valid_input_ids=["INP-1"],
    )

    validator = ExplanationValidator()
    metadata = GenerationMetadata(provider="test", model="mock", generation_mode="LLM")

    raw_payload = {
        "executive_summary": "Summary",
        "behavioral_summary": "Summary",
        "dimension_explanations": [
            {
                "dimension": "OUTPUT",
                # "status" is omitted!
                "reference_summary": "...",
            }
        ],
    }

    is_valid, errors, exp = validator.validate_and_sanitize_explanation(
        raw_payload=raw_payload,
        context=context,
        metadata=metadata,
    )

    assert is_valid is True
    assert exp is not None
    assert len(exp.dimension_explanations) == 1
    # Because differences exist in OUTPUT dimension, status must derive to DIFFERENT, never PASS
    assert exp.dimension_explanations[0].status == "DIFFERENT"
