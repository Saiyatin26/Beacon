"""BEACON V2 — Phase 8 Threshold Resolution Engine.

Implements deterministic, evidence-driven, bounded threshold resolution
with strict anti-target-contamination guarantees and mathematical estimators.
"""

from datetime import datetime, timezone
import math
from typing import Any, Optional, Sequence, Union
import uuid

from threshold.models import (
    DifferenceMetric,
    EstimatorType,
    OutlierPolicy,
    ThresholdPolicy,
    ThresholdResolution,
    ThresholdStatus,
    ThresholdStrategy,
    compute_deterministic_hash,
)


class TargetContaminationError(ValueError):
    """Raised when target observations are improperly supplied to reference threshold calculation."""
    pass


class ThresholdEngine:
    """Core engine for resolving dynamic and evidence-driven tolerance thresholds."""

    def __init__(self, default_policy: Optional[ThresholdPolicy] = None):
        self.default_policy = default_policy or ThresholdPolicy()

    def resolve_threshold(
        self,
        metric: DifferenceMetric,
        policy: Optional[ThresholdPolicy] = None,
        reference_observations: Optional[Sequence[Union[int, float]]] = None,
        evidence_ids: Optional[Sequence[str]] = None,
        target_observations: Optional[Sequence[Any]] = None,
    ) -> ThresholdResolution:
        """Resolves and freezes a deterministic tolerance threshold.

        ANTI-TARGET-CONTAMINATION GUARANTEE:
        Target observations MUST NOT be supplied to calculate reference-derived thresholds.
        If target_observations is provided, an error or strict rejection is enforced.
        """
        if target_observations is not None and len(target_observations) > 0:
            raise TargetContaminationError(
                "Target observations cannot be used to compute evaluation thresholds (anti-target-contamination invariant)."
            )

        active_policy = policy or self.default_policy
        policy_hash = active_policy.compute_policy_hash()
        evidence_ids_canonical = sorted(list(set(evidence_ids or [])))

        clean_observations: list[float] = []
        if reference_observations:
            for obs in reference_observations:
                if obs is None:
                    continue
                try:
                    f_val = float(obs)
                    if math.isnan(f_val) or math.isinf(f_val):
                        continue
                    clean_observations.append(f_val)
                except (ValueError, TypeError):
                    continue

        resolution_id = f"res_{compute_deterministic_hash([metric.value, policy_hash, evidence_ids_canonical, clean_observations])[:12]}"

        # 1. FIXED Strategy
        if active_policy.strategy == ThresholdStrategy.FIXED:
            fixed_val = float(active_policy.parameters.get("value", active_policy.parameters.get("tolerance", 0.0)))
            return ThresholdResolution(
                resolution_id=resolution_id,
                metric=metric,
                strategy=ThresholdStrategy.FIXED,
                status=ThresholdStatus.FIXED,
                raw_value=fixed_val,
                final_value=fixed_val,
                minimum_bound=active_policy.minimum_bound,
                maximum_bound=active_policy.maximum_bound,
                sample_count=len(clean_observations),
                minimum_required_samples=0,
                evidence_ids=evidence_ids_canonical,
                policy_id=active_policy.policy_id,
                policy_version=active_policy.version,
                policy_hash=policy_hash,
            )

        # 2. ABSOLUTE Strategy (Configured static absolute tolerance)
        if active_policy.strategy == ThresholdStrategy.ABSOLUTE:
            val = float(active_policy.parameters.get("tolerance", active_policy.parameters.get("value", 0.0)))
            return ThresholdResolution(
                resolution_id=resolution_id,
                metric=metric,
                strategy=ThresholdStrategy.ABSOLUTE,
                status=ThresholdStatus.RESOLVED,
                raw_value=val,
                final_value=val,
                minimum_bound=active_policy.minimum_bound,
                maximum_bound=active_policy.maximum_bound,
                sample_count=len(clean_observations),
                minimum_required_samples=0,
                evidence_ids=evidence_ids_canonical,
                policy_id=active_policy.policy_id,
                policy_version=active_policy.version,
                policy_hash=policy_hash,
            )

        # 3. RELATIVE Strategy (Configured static relative ratio tolerance)
        if active_policy.strategy == ThresholdStrategy.RELATIVE:
            val = float(active_policy.parameters.get("tolerance", active_policy.parameters.get("value", 0.0)))
            return ThresholdResolution(
                resolution_id=resolution_id,
                metric=metric,
                strategy=ThresholdStrategy.RELATIVE,
                status=ThresholdStatus.RESOLVED,
                raw_value=val,
                final_value=val,
                minimum_bound=active_policy.minimum_bound,
                maximum_bound=active_policy.maximum_bound,
                sample_count=len(clean_observations),
                minimum_required_samples=0,
                evidence_ids=evidence_ids_canonical,
                policy_id=active_policy.policy_id,
                policy_version=active_policy.version,
                policy_hash=policy_hash,
            )

        # 4. PERCENTAGE Strategy (Configured static percentage tolerance e.g. 5.0 -> 5%)
        if active_policy.strategy == ThresholdStrategy.PERCENTAGE:
            val = float(active_policy.parameters.get("tolerance", active_policy.parameters.get("value", 0.0)))
            return ThresholdResolution(
                resolution_id=resolution_id,
                metric=metric,
                strategy=ThresholdStrategy.PERCENTAGE,
                status=ThresholdStatus.RESOLVED,
                raw_value=val,
                final_value=val,
                minimum_bound=active_policy.minimum_bound,
                maximum_bound=active_policy.maximum_bound,
                sample_count=len(clean_observations),
                minimum_required_samples=0,
                evidence_ids=evidence_ids_canonical,
                policy_id=active_policy.policy_id,
                policy_version=active_policy.version,
                policy_hash=policy_hash,
            )

        # 5. EVIDENCE_DERIVED / STATISTICAL Strategy
        sample_count = len(clean_observations)
        ev_ids = evidence_ids_canonical

        # Check Sample Sufficiency
        if sample_count < active_policy.minimum_samples:
            # Insufficient samples: Check explicit fallback
            if active_policy.fallback_strategy and active_policy.fallback_value is not None:
                fb_val = float(active_policy.fallback_value)
                return ThresholdResolution(
                    resolution_id=resolution_id,
                    metric=metric,
                    strategy=active_policy.fallback_strategy,
                    status=ThresholdStatus.RESOLVED,
                    raw_value=fb_val,
                    final_value=fb_val,
                    minimum_bound=active_policy.minimum_bound,
                    maximum_bound=active_policy.maximum_bound,
                    sample_count=sample_count,
                    minimum_required_samples=active_policy.minimum_samples,
                    evidence_ids=ev_ids,
                    estimator=active_policy.estimator,
                    fallback_used=True,
                    fallback_reason=f"Insufficient reference samples ({sample_count} < {active_policy.minimum_samples})",
                    policy_id=active_policy.policy_id,
                    policy_version=active_policy.version,
                    policy_hash=policy_hash,
                )
            else:
                # No valid fallback -> Fail-Closed INSUFFICIENT_EVIDENCE
                return ThresholdResolution(
                    resolution_id=resolution_id,
                    metric=metric,
                    strategy=active_policy.strategy,
                    status=ThresholdStatus.INSUFFICIENT_EVIDENCE,
                    raw_value=None,
                    final_value=None,
                    minimum_bound=active_policy.minimum_bound,
                    maximum_bound=active_policy.maximum_bound,
                    sample_count=sample_count,
                    minimum_required_samples=active_policy.minimum_samples,
                    evidence_ids=ev_ids,
                    estimator=active_policy.estimator,
                    fallback_used=False,
                    policy_id=active_policy.policy_id,
                    policy_version=active_policy.version,
                    policy_hash=policy_hash,
                )

        # Apply Outlier Policy
        filtered_observations, outliers_count = self._apply_outlier_policy(
            clean_observations, active_policy.outlier_policy
        )

        # Apply Estimator
        raw_threshold = self._compute_estimator_threshold(
            filtered_observations, active_policy.estimator, active_policy.parameters
        )

        # Apply Minimum and Maximum Bounds
        final_threshold = raw_threshold
        if active_policy.minimum_bound is not None:
            final_threshold = max(final_threshold, active_policy.minimum_bound)
        if active_policy.maximum_bound is not None:
            final_threshold = min(final_threshold, active_policy.maximum_bound)

        return ThresholdResolution(
            resolution_id=resolution_id,
            metric=metric,
            strategy=active_policy.strategy,
            status=ThresholdStatus.RESOLVED,
            raw_value=round(raw_threshold, 6),
            final_value=round(final_threshold, 6),
            minimum_bound=active_policy.minimum_bound,
            maximum_bound=active_policy.maximum_bound,
            sample_count=sample_count,
            minimum_required_samples=active_policy.minimum_samples,
            evidence_ids=ev_ids,
            estimator=active_policy.estimator,
            outlier_policy=active_policy.outlier_policy,
            outliers_detected=outliers_count,
            fallback_used=False,
            policy_id=active_policy.policy_id,
            policy_version=active_policy.version,
            policy_hash=policy_hash,
        )

    def _apply_outlier_policy(
        self, values: list[float], policy: OutlierPolicy
    ) -> tuple[list[float], int]:
        """Applies deterministic outlier handling to numerical observations."""
        if policy == OutlierPolicy.NONE or len(values) < 4:
            return list(values), 0

        sorted_vals = sorted(values)
        n = len(sorted_vals)
        q1 = sorted_vals[n // 4]
        q3 = sorted_vals[(3 * n) // 4]
        iqr = q3 - q1

        if iqr == 0.0:
            return list(values), 0

        lower_fence = q1 - 1.5 * iqr
        upper_fence = q3 + 1.5 * iqr

        if policy == OutlierPolicy.ROBUST:
            filtered = [x for x in values if lower_fence <= x <= upper_fence]
            outliers_count = len(values) - len(filtered)
            return filtered if len(filtered) >= 2 else values, outliers_count

        elif policy == OutlierPolicy.CLIPPED:
            clipped = [min(max(x, lower_fence), upper_fence) for x in values]
            outliers_count = sum(1 for x in values if x < lower_fence or x > upper_fence)
            return clipped, outliers_count

        return list(values), 0

    def _compute_estimator_threshold(
        self, values: list[float], estimator: EstimatorType, params: dict[str, Any]
    ) -> float:
        """Computes raw mathematical spread/threshold using deterministic statistical formulas."""
        n = len(values)
        if n == 0:
            return 0.0

        mean = sum(values) / n

        if estimator == EstimatorType.MEAN_STDDEV:
            k = float(params.get("k", 2.0))
            if n < 2:
                return 0.0
            variance = sum((x - mean) ** 2 for x in values) / (n - 1)
            stddev = math.sqrt(variance)
            return k * stddev

        elif estimator == EstimatorType.IQR_ROBUST:
            k = float(params.get("k", 1.5))
            sorted_vals = sorted(values)
            q1 = sorted_vals[n // 4]
            q3 = sorted_vals[(3 * n) // 4]
            iqr = q3 - q1
            return k * iqr

        elif estimator == EstimatorType.MAX_OBSERVED_DELTA:
            return max(abs(x - mean) for x in values)

        elif estimator == EstimatorType.PERCENTILE_95:
            deltas = sorted(abs(x - mean) for x in values)
            idx = int(0.95 * len(deltas))
            idx = min(idx, len(deltas) - 1)
            return deltas[idx]

        elif estimator == EstimatorType.RANGE_FRACTION:
            k = float(params.get("k", 0.5))
            span = max(values) - min(values)
            return k * span

        return 0.0


# Module-level singletons
threshold_engine = ThresholdEngine()
threshold_resolver = threshold_engine
ThresholdResolver = ThresholdEngine
