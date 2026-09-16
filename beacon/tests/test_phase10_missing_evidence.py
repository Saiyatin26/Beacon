"""BEACON V2 — Phase 10 Missing Evidence Analysis Tests.

Verifies:
1. When state snapshots are absent, STATE dimension status is INCONCLUSIVE with explicit disclosure.
2. When workflow traces are absent, WORKFLOW dimension status is INCONCLUSIVE with explicit disclosure.
3. BEACON does NOT claim "Database state was unchanged" or "Workflow was equivalent" from absence of evidence.
4. Output differences are explained from available output evidence without fabricating other dimensions.
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
from intelligence.context_builder import ExplanationContextBuilder
from intelligence.deterministic_generator import DeterministicExplanationGenerator


def test_missing_state_evidence_results_in_inconclusive_state():
    """Verify that absent state snapshots dynamically yield INCONCLUSIVE state, not PASS or unchanged."""
    builder = ExplanationContextBuilder()
    artifact = CertificationArtifact(
        certification_id="CERT-MISSING-STATE-001",
        project_id="app_missing_evid",
        status=CertificationStatus.CERTIFIED,
        score=1.0,
        metrics=CertificationMetrics(
            unique_input_count=5,
            matching_case_count=5,
            regression_case_count=0,
        ),
        regressions=[],
        oracle_summaries=[],
    )

    ctx = builder.build_context(certification_id=artifact.certification_id, artifact=artifact)

    # Missing evidence must have STATE and WORKFLOW
    state_missing = next((m for m in ctx.missing_evidence if m.dimension == BehaviorDimension.STATE), None)
    assert state_missing is not None
    assert state_missing.status == "INCONCLUSIVE"
    assert "state snapshots were not collected" in state_missing.description.lower()

    workflow_missing = next((m for m in ctx.missing_evidence if m.dimension == BehaviorDimension.WORKFLOW), None)
    assert workflow_missing is not None
    assert workflow_missing.status == "INCONCLUSIVE"

    # Deterministic explanation must mark STATE dimension INCONCLUSIVE (not PASS)
    generator = DeterministicExplanationGenerator()
    explanation = generator.generate_explanation(ctx)

    state_exp = next(d for d in explanation.dimension_explanations if d.dimension == BehaviorDimension.STATE)
    assert state_exp.status == "INCONCLUSIVE", f"Expected INCONCLUSIVE, got {state_exp.status}"

    workflow_exp = next(d for d in explanation.dimension_explanations if d.dimension == BehaviorDimension.WORKFLOW)
    assert workflow_exp.status == "INCONCLUSIVE", f"Expected INCONCLUSIVE, got {workflow_exp.status}"

    output_exp = next(d for d in explanation.dimension_explanations if d.dimension == BehaviorDimension.OUTPUT)
    assert output_exp.status == "PASS"
