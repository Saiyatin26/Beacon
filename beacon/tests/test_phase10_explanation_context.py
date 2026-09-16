"""BEACON V2 — Phase 10 Explanation Context & Security Tests.

Verifies deterministic context fingerprinting, secret redaction, and multi-tenant data isolation.
"""

import json
import pytest
from evaluation.models import BehaviorDimension
from intelligence.context_builder import ExplanationContextBuilder
from intelligence.models import (
    CompanyKnowledgeContext,
    ExplanationContext,
    MissingEvidence,
    RetrievedKnowledgeCitation,
)
from intelligence.security import (
    DataIsolationChecker,
    redact_sensitive_data,
    redact_sensitive_string,
    sanitize_prompt_input,
    wrap_untrusted_context,
)


class TestPhase10ExplanationContextAndSecurity:
    """Test suite for Phase 10 ExplanationContext determinism and security."""

    def test_deterministic_context_fingerprint_reproducibility(self):
        """Verify identical context produces identical SHA-256 fingerprint."""
        ctx1 = ExplanationContext(
            certification_id="CERT-TEST-001",
            application_id="app_alpha",
            project_id="proj_alpha",
            authoritative_verdict="NOT_CERTIFIED",
            equivalence_score=0.75,
            unique_inputs_count=10,
            matching_cases_count=7,
            regression_cases_count=3,
            dimensions_evaluated=[BehaviorDimension.OUTPUT, BehaviorDimension.ERROR],
            valid_evidence_ids=["EVID-1", "EVID-2"],
            valid_rule_ids=["RULE-101", "RULE-102"],
            valid_input_ids=["INP-1", "INP-2"],
            knowledge_context=CompanyKnowledgeContext(
                retrieval_query="pricing rules",
                retrieval_fingerprint="fp_abc123",
                citations=[],
            ),
        )

        ctx2 = ExplanationContext(
            certification_id="CERT-TEST-001",
            application_id="app_alpha",
            project_id="proj_alpha",
            authoritative_verdict="NOT_CERTIFIED",
            equivalence_score=0.75,
            unique_inputs_count=10,
            matching_cases_count=7,
            regression_cases_count=3,
            dimensions_evaluated=[BehaviorDimension.ERROR, BehaviorDimension.OUTPUT], # Permuted order
            valid_evidence_ids=["EVID-2", "EVID-1"], # Permuted order
            valid_rule_ids=["RULE-102", "RULE-101"], # Permuted order
            valid_input_ids=["INP-2", "INP-1"], # Permuted order
            knowledge_context=CompanyKnowledgeContext(
                retrieval_query="pricing rules",
                retrieval_fingerprint="fp_abc123",
                citations=[],
            ),
        )

        fp1 = ctx1.compute_context_fingerprint()
        fp2 = ctx2.compute_context_fingerprint()
        assert fp1 == fp2, "Context fingerprint must be deterministic regardless of input collection order."
        assert len(fp1) == 64, "Fingerprint must be a valid SHA-256 hexadecimal string."

    def test_different_policy_or_scope_changes_fingerprint(self):
        """Verify changing context parameters changes the fingerprint."""
        ctx1 = ExplanationContext(
            certification_id="CERT-TEST-001",
            application_id="app_alpha",
            authoritative_verdict="NOT_CERTIFIED",
            equivalence_score=0.75,
            valid_evidence_ids=["EVID-1"],
        )
        ctx2 = ExplanationContext(
            certification_id="CERT-TEST-001",
            application_id="app_beta", # Different application
            authoritative_verdict="NOT_CERTIFIED",
            equivalence_score=0.75,
            valid_evidence_ids=["EVID-1"],
        )
        assert ctx1.compute_context_fingerprint() != ctx2.compute_context_fingerprint()

    def test_secret_redaction_masks_credentials_and_tokens(self):
        """Verify passwords, bearer tokens, API keys, and connection strings are deeply redacted."""
        payload = {
            "application_id": "payment_gateway",
            "api_key": "sk-1234567890abcdef1234567890abcdef",
            "db_connection": "postgres://admin:SuperSecretPassword123@db.internal:5432/prod",
            "headers": {
                "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummysecret",
                "Content-Type": "application/json",
            },
            "user_data": {
                "password": "ClearTextPassword!",
                "normal_field": "Normal Value",
            },
        }

        redacted = redact_sensitive_data(payload)

        assert redacted["api_key"] == "[REDACTED_SECRET]"
        assert "SuperSecretPassword123" not in str(redacted)
        assert "dummysecret" not in str(redacted)
        assert redacted["user_data"]["password"] == "[REDACTED_SECRET]"
        assert redacted["user_data"]["normal_field"] == "Normal Value"
        assert redacted["application_id"] == "payment_gateway"

    def test_multi_tenant_cross_application_data_isolation(self):
        """Verify strict isolation checking prevents App A evidence leaking into App B."""
        app_b_context = "Certification for application app_beta completed. Observed evidence EVID-B1."
        is_isolated, violations = DataIsolationChecker.verify_isolation(
            target_application_id="app_beta",
            prohibited_application_ids=["app_alpha", "app_gamma"],
            rendered_context_or_output=app_b_context,
        )
        assert is_isolated
        assert len(violations) == 0

        contaminated_context = "Certification for app_beta with reference to app_alpha secret data."
        is_isolated_bad, violations_bad = DataIsolationChecker.verify_isolation(
            target_application_id="app_beta",
            prohibited_application_ids=["app_alpha", "app_gamma"],
            rendered_context_or_output=contaminated_context,
        )
        assert not is_isolated_bad
        assert "app_alpha" in violations_bad[0]
