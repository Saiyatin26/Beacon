"""BEACON V2 — Phase 10 Verdict Protection & Hallucination Guard Tests.

Verifies authoritative verdict immutability, evidence/rule ID whitelist enforcement,
and deterministic fallback resilience.
"""

import pytest
from evaluation.models import BehaviorDimension
from intelligence.deterministic_generator import deterministic_generator
from intelligence.models import (
    ExplanationContext,
    GenerationMetadata,
)
from intelligence.validation import explanation_validator


class TestPhase10VerdictProtectionAndGuards:
    """Test suite for verdict protection, hallucination rejection, and fallback."""

    def test_authoritative_verdict_cannot_be_overridden_by_llm(self):
        """Verify that even if LLM attempts to claim PASS for a NOT_CERTIFIED run, verdict remains NOT_CERTIFIED."""
        ctx = ExplanationContext(
            certification_id="CERT-DIFF-001",
            application_id="loan_service",
            authoritative_verdict="NOT_CERTIFIED",
            equivalence_score=0.60,
            valid_evidence_ids=["EVID-101"],
            valid_rule_ids=["RULE-101"],
            valid_input_ids=["INP-101"],
        )

        malicious_llm_payload = {
            "executive_summary": "I have reviewed the code and in my opinion it looks good enough, so CERTIFIED.",
            "overall_verdict": "CERTIFIED", # Attempted override
            "dimension_explanations": [
                {
                    "dimension": "OUTPUT",
                    "status": "PASS", # Attempted override
                    "evidence_ids": ["EVID-101"],
                }
            ],
            "rule_impacts": [
                {
                    "rule_id": "RULE-101",
                    "status": "COMPLIANT",
                    "supporting_evidence_ids": ["EVID-101"],
                }
            ],
        }

        meta = GenerationMetadata(provider="openrouter", model="claude-3.5-sonnet", generation_mode="LLM")
        is_valid, errors, explanation = explanation_validator.validate_and_sanitize_explanation(
            raw_payload=malicious_llm_payload,
            context=ctx,
            metadata=meta,
        )

        assert is_valid
        assert explanation is not None
        assert explanation.overall_verdict == "NOT_CERTIFIED", "Overall verdict must remain immutable and locked to authoritative result."
        assert explanation.is_authoritative_match is False
        assert explanation.authoritative_match_status == "NOT_CERTIFIED"

    def test_hallucinated_evidence_and_rule_ids_are_filtered_out(self):
        """Verify hallucinated evidence IDs (e.g. EVID-999) and rule IDs (e.g. RULE-999) are filtered."""
        ctx = ExplanationContext(
            certification_id="CERT-002",
            valid_evidence_ids=["EVID-1", "EVID-2"],
            valid_rule_ids=["RULE-A", "RULE-B"],
            authoritative_verdict="NOT_CERTIFIED",
        )

        llm_payload = {
            "executive_summary": "Summary of findings.",
            "dimension_explanations": [
                {
                    "dimension": "OUTPUT",
                    "evidence_ids": ["EVID-1", "EVID-999_HALLUCINATED", "EVID-FAKE"],
                }
            ],
            "rule_impacts": [
                {
                    "rule_id": "RULE-A",
                    "rule_description": "Valid rule",
                    "supporting_evidence_ids": ["EVID-1", "EVID-UNKNOWN"],
                },
                {
                    "rule_id": "RULE-999_HALLUCINATED", # Nonexistent rule
                    "rule_description": "Invented rule",
                }
            ],
        }

        meta = GenerationMetadata(provider="openrouter", model="test-model", generation_mode="LLM")
        is_valid, errors, explanation = explanation_validator.validate_and_sanitize_explanation(
            raw_payload=llm_payload,
            context=ctx,
            metadata=meta,
        )

        assert is_valid
        assert explanation is not None

        # Check dimension evidence IDs
        dim_exp = explanation.dimension_explanations[0]
        assert "EVID-1" in dim_exp.evidence_ids
        assert "EVID-999_HALLUCINATED" not in dim_exp.evidence_ids
        assert "EVID-FAKE" not in dim_exp.evidence_ids

        # Check rule impacts
        rule_ids = [r.rule_id for r in explanation.rule_impacts]
        assert "RULE-A" in rule_ids
        assert "RULE-999_HALLUCINATED" not in rule_ids, "Hallucinated rule IDs must be filtered out."

    def test_deterministic_generator_produces_complete_explanation(self):
        """Verify deterministic fallback generator produces comprehensive, valid explanation."""
        ctx = ExplanationContext(
            certification_id="CERT-DET-001",
            application_id="pricing_engine",
            authoritative_verdict="NOT_CERTIFIED",
            equivalence_score=0.85,
            unique_inputs_count=20,
            matching_cases_count=17,
            regression_cases_count=3,
            dimensions_evaluated=[BehaviorDimension.OUTPUT, BehaviorDimension.ERROR],
            differences_summary=[
                {
                    "input_id": "INP-001",
                    "reference_value": 100.0,
                    "target_value": 95.0,
                    "reference_evidence_id": "EVID-REF-1",
                    "target_evidence_id": "EVID-TGT-1",
                    "violated_oracle_ids": ["ORC-101"],
                }
            ],
            valid_evidence_ids=["EVID-REF-1", "EVID-TGT-1"],
            valid_rule_ids=["ORC-101"],
            valid_input_ids=["INP-001"],
        )

        explanation = deterministic_generator.generate_explanation(ctx, fallback_reason="Offline mode")
        assert explanation.overall_verdict == "NOT_CERTIFIED"
        assert len(explanation.executive_summary) > 20
        assert len(explanation.dimension_explanations) == 2
        assert len(explanation.evidence_traces) >= 1
        assert len(explanation.affected_inputs) >= 1
        assert len(explanation.investigation_recommendations) >= 1
        assert explanation.generation_metadata.generation_mode == "DETERMINISTIC"
        assert explanation.generation_metadata.fallback_occurred is True
