"""BEACON V2 — Phase 8 Adversarial & Anti-Contamination Validation Tests.

Focused adversarial test suite ensuring:
- Target observations cannot influence their own evaluation threshold (anti-self-justification).
- Insufficient evidence cannot fabricate certainty or permissive tolerances.
- Min / Max bounds cannot be bypassed.
- Outlier handling remains explicit, deterministic, and auditable.
- Shuffled evidence inputs produce byte-for-byte deterministic fingerprints.
"""

from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from evaluation.models import EvaluationVerdict
from reconciliation.models import OracleSet, OracleSetStatus
from threshold.engine import TargetContaminationError, ThresholdEngine
from threshold.evaluator import AdvancedBehavioralEvaluator
from threshold.models import (
    DifferenceMetric,
    EstimatorType,
    OutlierPolicy,
    ThresholdPolicy,
    ThresholdResolution,
    ThresholdStatus,
    ThresholdStrategy,
)


class TestPhase8AdversarialValidation:
    """Adversarial security and anti-contamination validation suite for Phase 8."""

    def test_target_contamination_is_strictly_prevented(self):
        """ADVERSARIAL TEST 1: Target observations cannot be supplied to calculate reference thresholds."""
        engine = ThresholdEngine()
        policy = ThresholdPolicy(
            strategy=ThresholdStrategy.EVIDENCE_DERIVED,
            minimum_samples=3,
        )
        # Attempting to supply target observations to threshold calculation MUST raise TargetContaminationError
        with pytest.raises(TargetContaminationError) as exc_info:
            engine.resolve_threshold(
                metric=DifferenceMetric.ABSOLUTE_DIFF,
                policy=policy,
                reference_observations=[100.0, 101.0, 99.0],
                target_observations=[105.0, 110.0],  # Forbidden!
            )
        assert "Target observations cannot be used" in str(exc_info.value)

    def test_target_cannot_inflate_tolerance_in_evaluator(self):
        """ADVERSARIAL TEST 2: Target difference cannot inflate tolerance to force PASS."""
        evaluator = AdvancedBehavioralEvaluator()
        oracle = OracleSet(oracle_set_id="os_adv_target", application_id="app_adv")
        
        # Historical reference evidence with low variance: stddev ~ 0.5 -> threshold ~ 1.0
        ref_samples = [100.0, 100.5, 99.5, 100.0, 100.2, 99.8]
        
        # Target has a massive deviation: target = 150.0 (delta = 50.0)
        policy = ThresholdPolicy(
            strategy=ThresholdStrategy.EVIDENCE_DERIVED,
            estimator=EstimatorType.MEAN_STDDEV,
            parameters={"k": 2.0},
            minimum_samples=5,
            maximum_bound=5.0,  # Max allowable tolerance is 5.0
        )

        res = evaluator.evaluate(
            application_id="app_adv",
            oracle_set=oracle,
            reference_evidence=ref_samples,
            target_evidence=[150.0],
            policy=policy,
        )

        # Verdict MUST be DIFFERENT (FAIL), target cannot alter frozen threshold
        assert res.overall_verdict == EvaluationVerdict.DIFFERENT
        assert res.failed_count == 1
        assert res.resolutions[0].final_value <= 5.0
        assert res.differences[0].within_tolerance is False

    def test_insufficient_reference_cannot_create_permissive_threshold(self):
        """ADVERSARIAL TEST 3: Zero or insufficient reference data cannot default to permissive infinity."""
        engine = ThresholdEngine()
        policy = ThresholdPolicy(
            strategy=ThresholdStrategy.EVIDENCE_DERIVED,
            minimum_samples=10,
        )
        # Only 1 sample
        res = engine.resolve_threshold(
            metric=DifferenceMetric.ABSOLUTE_DIFF,
            policy=policy,
            reference_observations=[100.0],
        )
        assert res.status == ThresholdStatus.INSUFFICIENT_EVIDENCE
        assert res.final_value is None

    def test_min_max_bounds_cannot_be_bypassed_by_extreme_evidence(self):
        """ADVERSARIAL TEST 4: Extreme outlier evidence cannot push tolerance beyond maximum_bound."""
        engine = ThresholdEngine()
        # Wildly fluctuating reference samples: range = 1000
        extreme_samples = [0.0, 1000.0, 500.0, 200.0, 800.0]
        policy = ThresholdPolicy(
            strategy=ThresholdStrategy.EVIDENCE_DERIVED,
            minimum_samples=3,
            maximum_bound=10.0,  # Strict upper limit
        )
        res = engine.resolve_threshold(
            metric=DifferenceMetric.ABSOLUTE_DIFF,
            policy=policy,
            reference_observations=extreme_samples,
        )
        assert res.raw_value > 100.0
        assert res.final_value == 10.0  # Clamped strictly to maximum_bound

    def test_outlier_handling_transparency_and_robustness(self):
        """ADVERSARIAL TEST 5: Outlier handling records exact detected count and preserves auditability."""
        engine = ThresholdEngine()
        # 10 normal samples around 10.0, and 1 massive outlier at 1000.0
        samples = [10.0, 10.1, 9.9, 10.2, 9.8, 10.0, 10.1, 9.9, 10.0, 1000.0]
        
        # Policy with ROBUST outlier handling
        policy_robust = ThresholdPolicy(
            strategy=ThresholdStrategy.EVIDENCE_DERIVED,
            estimator=EstimatorType.IQR_ROBUST,
            outlier_policy=OutlierPolicy.ROBUST,
            minimum_samples=5,
        )
        res_robust = engine.resolve_threshold(
            metric=DifferenceMetric.ABSOLUTE_DIFF,
            policy=policy_robust,
            reference_observations=samples,
        )
        assert res_robust.outliers_detected >= 1
        assert res_robust.final_value < 5.0  # Outlier was filtered safely

    def test_evidence_permutation_invariance(self):
        """ADVERSARIAL TEST 6: Shuffling evidence items produces identical mathematical threshold and fingerprint."""
        engine = ThresholdEngine()
        policy = ThresholdPolicy(
            strategy=ThresholdStrategy.EVIDENCE_DERIVED,
            estimator=EstimatorType.MEAN_STDDEV,
            minimum_samples=5,
            minimum_bound=0.01,
            maximum_bound=1.0,
        )
        samples_original = [12.0, 14.5, 11.2, 13.8, 15.0, 12.4]
        samples_reversed = list(reversed(samples_original))
        
        res1 = engine.resolve_threshold(DifferenceMetric.ABSOLUTE_DIFF, policy, samples_original)
        res2 = engine.resolve_threshold(DifferenceMetric.ABSOLUTE_DIFF, policy, samples_reversed)
        
        assert res1.final_value == pytest.approx(res2.final_value, abs=1e-6)
        assert res1.fingerprint == res2.fingerprint
