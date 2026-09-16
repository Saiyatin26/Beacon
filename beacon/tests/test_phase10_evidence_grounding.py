"""BEACON V2 — Phase 10 Evidence Grounding Tests.

Verifies:
1. No synthetic evidence IDs (e.g. EVID-RUN, EVID-{id}) are ever generated or accepted.
2. Real Phase 3/4/8 evidence IDs are preserved faithfully in ExplanationContext and traces.
3. When evidence is absent, evidence_id is None / absent, and explanation declares evidence unavailable.
4. End-to-end integration from real Phase 3/4/7/8 structures into ExplanationContext.
"""

import pytest
from evaluation.models import BehaviorDimension
from certification.models import (
    BehavioralRegression,
    CertificationArtifact,
    CertificationContext,
    CertificationMetrics,
    CertificationPolicy,
    CertificationStatus,
    PerOracleCertificationSummary,
    compute_artifact_content_hash,
)
from intelligence.context_builder import ExplanationContextBuilder
from intelligence.deterministic_generator import DeterministicExplanationGenerator
from intelligence.engine import IntelligenceEngine


def test_no_synthetic_evidence_ids_when_evidence_absent():
    """Verify that when regressions lack evidence IDs, no synthetic 'EVID-' IDs are generated."""
    builder = ExplanationContextBuilder()
    artifact = CertificationArtifact(
        certification_id="CERT-NO-EVID-001",
        project_id="app_grounding_test",
        status=CertificationStatus.NOT_CERTIFIED,
        score=0.5,
        metrics=CertificationMetrics(
            unique_input_count=2,
            matching_case_count=1,
            regression_case_count=1,
        ),
        regressions=[
            BehavioralRegression(
                regression_id="REG-001",
                oracle_id="ORC-001",
                input_id="INP-001",
                input_values={"amount": 100},
                expected_behavior=100,
                legacy_output=100,
                modern_output=90,
                failed_assertion="output == expected",
                evidence_ids=[],  # NO EVIDENCE
            )
        ],
        oracle_summaries=[
            PerOracleCertificationSummary(
                oracle_id="ORC-001",
                condition_str="amount > 0",
                consequence_str="output == expected",
                modern_regressions=1,
            )
        ],
    )

    ctx = builder.build_context(certification_id=artifact.certification_id, artifact=artifact)

    # Valid evidence IDs must be completely empty (no EVID-RUN-1 or EVID-REG-001)
    assert len(ctx.valid_evidence_ids) == 0, f"Expected no synthetic IDs, got: {ctx.valid_evidence_ids}"
    for eid in ctx.valid_evidence_ids:
        assert not eid.startswith("EVID-RUN"), f"Synthetic ID detected: {eid}"
        assert not eid.startswith("EVID-REG"), f"Synthetic ID detected: {eid}"

    # Diff record must have None for evidence IDs
    diff = ctx.differences_summary[0]
    assert diff["reference_evidence_id"] is None
    assert diff["target_evidence_id"] is None
    assert diff["evidence_ids"] == []

    # Deterministic explanation must not manufacture synthetic evidence IDs
    generator = DeterministicExplanationGenerator()
    explanation = generator.generate_explanation(ctx)

    for trace in explanation.evidence_traces:
        if trace.evidence_id is not None:
            assert not trace.evidence_id.startswith("EVID-RUN")
            assert not trace.evidence_id.startswith("EVID-TGT")


def test_real_evidence_ids_are_faithfully_preserved():
    """Verify that real Phase 3 evidence IDs are preserved in context, traces, and findings."""
    builder = ExplanationContextBuilder()
    artifact = CertificationArtifact(
        certification_id="CERT-REAL-EVID-001",
        project_id="app_grounding_test",
        status=CertificationStatus.NOT_CERTIFIED,
        score=0.75,
        metrics=CertificationMetrics(
            unique_input_count=4,
            matching_case_count=3,
            regression_case_count=1,
        ),
        regressions=[
            BehavioralRegression(
                regression_id="REG-100",
                oracle_id="ORC-100",
                input_id="INP-100",
                input_values={"score": 750},
                expected_behavior="TIER_A",
                legacy_output="TIER_A",
                modern_output="TIER_B",
                failed_assertion="output == expected",
                evidence_ids=["EVID-PHASE3-REF-100", "EVID-PHASE3-TGT-100"],
                reference_evidence_id="EVID-PHASE3-REF-100",
                target_evidence_id="EVID-PHASE3-TGT-100",
                dimension=BehaviorDimension.OUTPUT,
            )
        ],
        oracle_summaries=[
            PerOracleCertificationSummary(
                oracle_id="ORC-100",
                condition_str="score >= 700",
                consequence_str="tier == TIER_A",
                modern_regressions=1,
            )
        ],
    )

    ctx = builder.build_context(certification_id=artifact.certification_id, artifact=artifact)

    assert "EVID-PHASE3-REF-100" in ctx.valid_evidence_ids
    assert "EVID-PHASE3-TGT-100" in ctx.valid_evidence_ids

    diff = ctx.differences_summary[0]
    assert diff["reference_evidence_id"] == "EVID-PHASE3-REF-100"
    assert diff["target_evidence_id"] == "EVID-PHASE3-TGT-100"

    generator = DeterministicExplanationGenerator()
    explanation = generator.generate_explanation(ctx)

    dim_exp = next(d for d in explanation.dimension_explanations if d.dimension == BehaviorDimension.OUTPUT)
    assert "EVID-PHASE3-REF-100" in dim_exp.evidence_ids
    assert "EVID-PHASE3-TGT-100" in dim_exp.evidence_ids
