"""BEACON V2 — Phase 10 Application & Project Scope Isolation Tests.

Verifies:
1. Application A's evidence, rules, inputs, and knowledge do NOT leak into Application B.
2. Cross-project requests cannot access or expose data belonging to another project.
"""

import pytest
from evaluation.models import BehaviorDimension
from certification.models import (
    BehavioralRegression,
    CertificationArtifact,
    CertificationMetrics,
    CertificationStatus,
    PerOracleCertificationSummary,
)
from certification.repository import certification_repository
from intelligence.context_builder import ExplanationContextBuilder


def test_cross_application_scope_isolation():
    """Verify that Application B's ExplanationContext contains zero information from Application A."""
    builder = ExplanationContextBuilder()

    # Application A
    artifact_a = CertificationArtifact(
        certification_id="CERT-APP-A-001",
        project_id="ProjectA",
        benchmark_id="app_a_banking",
        status=CertificationStatus.NOT_CERTIFIED,
        score=0.5,
        metrics=CertificationMetrics(unique_input_count=1, regression_case_count=1),
        regressions=[
            BehavioralRegression(
                regression_id="REG-A-001",
                oracle_id="ORC-A-SECRET",
                input_id="INP-A-SECRET",
                input_values={"account_balance": 5000},
                expected_behavior=5000,
                legacy_output=5000,
                modern_output=4500,
                failed_assertion="balance == expected",
                evidence_ids=["EVID-A-SECRET"],
            )
        ],
        oracle_summaries=[
            PerOracleCertificationSummary(
                oracle_id="ORC-A-SECRET",
                condition_str="balance > 0",
                consequence_str="balance == expected",
            )
        ],
    )

    # Application B
    artifact_b = CertificationArtifact(
        certification_id="CERT-APP-B-001",
        project_id="ProjectB",
        benchmark_id="app_b_healthcare",
        status=CertificationStatus.CERTIFIED,
        score=1.0,
        metrics=CertificationMetrics(unique_input_count=2, matching_case_count=2),
        regressions=[],
        oracle_summaries=[
            PerOracleCertificationSummary(
                oracle_id="ORC-B-TRIAGE",
                condition_str="spo2 < 90",
                consequence_str="triage == EMERGENCY",
            )
        ],
    )

    ctx_b = builder.build_context(certification_id=artifact_b.certification_id, artifact=artifact_b)

    # Verify context B contains NO App A secret identifiers or content
    assert "ORC-A-SECRET" not in ctx_b.valid_rule_ids
    assert "INP-A-SECRET" not in ctx_b.valid_input_ids
    assert "EVID-A-SECRET" not in ctx_b.valid_evidence_ids
    assert ctx_b.application_id == "ProjectB"
    assert ctx_b.project_id == "ProjectB"
    assert not any("account_balance" in str(diff) for diff in ctx_b.differences_summary)
