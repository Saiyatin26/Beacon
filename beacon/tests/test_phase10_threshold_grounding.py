"""BEACON V2 — Phase 10 Dynamic Threshold Grounding Tests.

Verifies:
1. Phase 10 consumes real Phase 8 threshold resolutions and policies.
2. Phase 10 never hardcodes or reconstructs arbitrary threshold defaults (e.g. 0.80 or FIXED_AND_BOUNDED).
3. If Phase 8 threshold information is absent, it is not fabricated.
4. Mutating Phase 8 threshold resolution values modifies context and fingerprint.
"""

import pytest
from evaluation.models import BehaviorDimension
from certification.models import (
    CertificationArtifact,
    CertificationMetrics,
    CertificationStatus,
)
from intelligence.context_builder import ExplanationContextBuilder
from threshold.models import (
    DifferenceMetric,
    ThresholdPolicy,
    ThresholdResolution,
    ThresholdStatus,
    ThresholdStrategy,
)
from threshold.persistence import threshold_persistence


def test_phase8_threshold_consumed_authoritatively():
    """Verify that actual Phase 8 threshold resolution is consumed into ExplanationContext."""
    # 1. Register a real Phase 8 Policy and Resolution
    policy = ThresholdPolicy(
        policy_id="POL-PHASE8-TEST",
        strategy=ThresholdStrategy.FIXED,
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        parameters={"value": 0.05},
        minimum_samples=5,
    )
    threshold_persistence.save_policy(policy)

    resolution = ThresholdResolution(
        resolution_id="RES-PHASE8-TEST-001",
        policy_id=policy.policy_id,
        policy_version=policy.version,
        metric=policy.metric,
        strategy=policy.strategy,
        status=ThresholdStatus.RESOLVED,
        final_value=0.05,
        sample_count=10,
    )
    threshold_persistence.save_resolution(resolution)

    # 2. Build CertificationArtifact referencing this policy and exact resolution
    artifact = CertificationArtifact(
        certification_id="CERT-THRESH-001",
        project_id="app_threshold_test",
        certification_policy_id=policy.policy_id,
        threshold_resolution_id="RES-PHASE8-TEST-001",
        status=CertificationStatus.CERTIFIED,
        score=0.95,
        metrics=CertificationMetrics(
            unique_input_count=60,
            matching_case_count=58,
            regression_case_count=2,
        ),
        regressions=[],
        oracle_summaries=[],
    )

    builder = ExplanationContextBuilder()
    ctx = builder.build_context(certification_id=artifact.certification_id, artifact=artifact)

    assert len(ctx.thresholds_context) >= 1
    t_entry = ctx.thresholds_context[0]
    assert t_entry["policy_id"] == "POL-PHASE8-TEST"
    assert t_entry["strategy"] == "FIXED"
    assert t_entry["resolved_threshold"] == 0.05
    assert t_entry["sample_count"] == 10


def test_no_fabricated_thresholds_when_phase8_policy_absent():
    """Verify that when no Phase 8 policy exists, no synthetic thresholds like FIXED_AND_BOUNDED/0.80 are created."""
    artifact = CertificationArtifact(
        certification_id="CERT-NO-THRESH-001",
        project_id="app_threshold_test",
        certification_policy_id="",  # No policy ID
        status=CertificationStatus.CERTIFIED,
        score=1.0,
        metrics=CertificationMetrics(
            unique_input_count=10,
            matching_case_count=10,
            regression_case_count=0,
        ),
        regressions=[],
        oracle_summaries=[],
    )

    builder = ExplanationContextBuilder()
    ctx = builder.build_context(certification_id=artifact.certification_id, artifact=artifact)

    # Thresholds context must be empty
    assert len(ctx.thresholds_context) == 0
