"""BEACON V2 — Phase 8 Advanced Behavioral Evaluator.

Integrates Phase 7 OracleSets and Phase 3 EvidenceBundles with Phase 8
dynamic / evidence-driven thresholds, providing conservative verdict aggregation
and complete decision traceability.
"""

from datetime import datetime, timezone
import math
from typing import Any, Optional, Sequence, Union
import uuid

from evaluation.models import BehaviorDimension, DifferenceType, EvaluationVerdict
from execution.evidence_models import EvidenceBundle, EvidenceRecord
from reconciliation.models import OracleRule, OracleSet, OracleSetStatus
from threshold.engine import ThresholdEngine, threshold_engine
from threshold.models import (
    AdvancedEvaluationDifference,
    AdvancedEvaluationResult,
    DifferenceMetric,
    ThresholdPolicy,
    ThresholdResolution,
    ThresholdStatus,
    ThresholdStrategy,
    compute_deterministic_hash,
)


class AdvancedBehavioralEvaluator:
    """Evaluates behavioral equivalence using frozen dynamic thresholds and OracleSets."""

    def __init__(self, engine: Optional[ThresholdEngine] = None):
        self.engine = engine or threshold_engine

    def evaluate(
        self,
        application_id: str,
        oracle_set: OracleSet,
        reference_evidence: Optional[Sequence[Any]] = None,
        target_evidence: Optional[Sequence[Any]] = None,
        policy: Optional[ThresholdPolicy] = None,
        evaluation_id: Optional[str] = None,
    ) -> AdvancedEvaluationResult:
        """Runs advanced behavioral evaluation under explicit threshold policies."""
        eval_id = evaluation_id or f"eval_{uuid.uuid4().hex[:12]}"
        active_policy = policy or ThresholdPolicy()
        policy_hash = active_policy.compute_policy_hash()

        resolutions: list[ThresholdResolution] = []
        differences: list[AdvancedEvaluationDifference] = []
        dimension_verdicts: dict[str, EvaluationVerdict] = {}

        # 1. OracleSet Fail-Closed Check
        if oracle_set.status == OracleSetStatus.BLOCKED:
            return AdvancedEvaluationResult(
                evaluation_id=eval_id,
                application_id=application_id,
                oracle_set_id=oracle_set.oracle_set_id,
                oracle_set_hash=oracle_set.oracle_set_hash or oracle_set.compute_oracle_set_hash(),
                policy_id=active_policy.policy_id,
                policy_version=active_policy.version,
                policy_hash=policy_hash,
                overall_verdict=EvaluationVerdict.INCONCLUSIVE,
                status="BLOCKED_BY_ORACLE_SET",
                summary={"reason": "OracleSet is BLOCKED due to unresolved material conflicts."},
            )

        # 2. Extract reference numerical observations for evidence-driven thresholds
        ref_observations = self._extract_numerical_observations(reference_evidence)
        ref_evidence_ids = self._extract_evidence_ids(reference_evidence)

        # 3. Resolve and Freeze Threshold
        resolution = self.engine.resolve_threshold(
            metric=active_policy.metric,
            policy=active_policy,
            reference_observations=ref_observations,
            evidence_ids=ref_evidence_ids,
        )
        resolutions.append(resolution)

        # 4. Evaluate Oracle Rules and Target Observations
        passed_count = 0
        failed_count = 0
        inconclusive_count = 0

        # If threshold resolution failed with INSUFFICIENT_EVIDENCE -> fail-closed INCONCLUSIVE
        if resolution.status == ThresholdStatus.INSUFFICIENT_EVIDENCE:
            overall_verdict = EvaluationVerdict.INCONCLUSIVE
            diff = AdvancedEvaluationDifference(
                difference_id=f"diff_{uuid.uuid4().hex[:8]}",
                dimension=BehaviorDimension.OUTPUT,
                input_id="global_sufficiency",
                difference_type=DifferenceType.EVIDENCE_MISSING,
                reference_value=f"Samples: {resolution.sample_count}",
                target_value=None,
                resolution=resolution,
                within_tolerance=False,
                verdict=EvaluationVerdict.INCONCLUSIVE,
                explanation=f"Insufficient reference evidence to establish threshold ({resolution.sample_count} < {resolution.minimum_required_samples})",
            )
            differences.append(diff)
            inconclusive_count += 1
            dimension_verdicts[BehaviorDimension.OUTPUT.value] = EvaluationVerdict.INCONCLUSIVE
        else:
            # Evaluate target against reference observations or oracle expectations
            eval_results = self._evaluate_pairs(
                oracle_rules=oracle_set.rules,
                reference_evidence=reference_evidence or [],
                target_evidence=target_evidence or [],
                resolution=resolution,
            )
            differences.extend(eval_results["differences"])
            passed_count = eval_results["passed_count"]
            failed_count = eval_results["failed_count"]
            inconclusive_count = eval_results["inconclusive_count"]
            dimension_verdicts = eval_results["dimension_verdicts"]

            # Conservative Verdict Aggregation
            if failed_count > 0:
                overall_verdict = EvaluationVerdict.DIFFERENT
            elif inconclusive_count > 0:
                overall_verdict = EvaluationVerdict.INCONCLUSIVE
            elif passed_count > 0 or len(oracle_set.rules) > 0:
                overall_verdict = EvaluationVerdict.EQUIVALENT
            else:
                overall_verdict = EvaluationVerdict.NOT_APPLICABLE

        return AdvancedEvaluationResult(
            evaluation_id=eval_id,
            application_id=application_id,
            oracle_set_id=oracle_set.oracle_set_id,
            oracle_set_hash=oracle_set.oracle_set_hash or oracle_set.compute_oracle_set_hash(),
            policy_id=active_policy.policy_id,
            policy_version=active_policy.version,
            policy_hash=policy_hash,
            overall_verdict=overall_verdict,
            status="COMPLETE",
            dimension_verdicts=dimension_verdicts,
            total_evaluations=passed_count + failed_count + inconclusive_count,
            passed_count=passed_count,
            failed_count=failed_count,
            inconclusive_count=inconclusive_count,
            resolutions=resolutions,
            differences=differences,
            summary={
                "strategy": resolution.strategy.value,
                "resolved_threshold": resolution.final_value,
                "sample_count": resolution.sample_count,
                "fallback_used": resolution.fallback_used,
            },
        )

    def _extract_numerical_observations(self, evidence: Optional[Sequence[Any]]) -> list[float]:
        """Safely extracts numerical observations from evidence items."""
        if not evidence:
            return []
        numbers: list[float] = []
        for item in evidence:
            if isinstance(item, (int, float)):
                if not math.isnan(item) and not math.isinf(item):
                    numbers.append(float(item))
            elif isinstance(item, dict):
                # Look for common numeric fields
                for k in ("value", "output", "numeric_value", "result", "duration_ms", "latency_ms"):
                    v = item.get(k)
                    if isinstance(v, (int, float)) and not math.isnan(v) and not math.isinf(v):
                        numbers.append(float(v))
            elif hasattr(item, "data") and isinstance(item.data, dict):
                for k in ("value", "output", "numeric_value", "result"):
                    v = item.data.get(k)
                    if isinstance(v, (int, float)) and not math.isnan(v) and not math.isinf(v):
                        numbers.append(float(v))
        return numbers

    def _extract_evidence_ids(self, evidence: Optional[Sequence[Any]]) -> list[str]:
        """Extracts unique evidence IDs from evidence items."""
        if not evidence:
            return []
        ids: list[str] = []
        for item in evidence:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict) and "evidence_id" in item:
                ids.append(str(item["evidence_id"]))
            elif hasattr(item, "evidence_id"):
                ids.append(str(item.evidence_id))
        return sorted(list(set(ids)))

    def _evaluate_pairs(
        self,
        oracle_rules: list[OracleRule],
        reference_evidence: Sequence[Any],
        target_evidence: Sequence[Any],
        resolution: ThresholdResolution,
    ) -> dict[str, Any]:
        """Evaluates reference vs target items under the frozen threshold resolution across all 7 metrics."""
        diffs: list[AdvancedEvaluationDifference] = []
        passed = 0
        failed = 0
        inconclusive = 0
        dim_verdicts: dict[str, EvaluationVerdict] = {}

        ref_list = list(reference_evidence)
        tar_list = list(target_evidence)
        max_len = max(len(ref_list), len(tar_list))

        if max_len == 0 and len(oracle_rules) > 0:
            passed = len(oracle_rules)
            dim_verdicts[BehaviorDimension.OUTPUT.value] = EvaluationVerdict.EQUIVALENT
            return {
                "differences": [],
                "passed_count": passed,
                "failed_count": 0,
                "inconclusive_count": 0,
                "dimension_verdicts": dim_verdicts,
            }

        tol = resolution.final_value if resolution.final_value is not None else 0.0

        for idx in range(max_len):
            ref_item = ref_list[idx] if idx < len(ref_list) else None
            tar_item = tar_list[idx] if idx < len(tar_list) else None
            input_id = f"input_{idx + 1}"

            if ref_item is None or tar_item is None:
                diffs.append(AdvancedEvaluationDifference(
                    difference_id=f"diff_{uuid.uuid4().hex[:8]}",
                    dimension=BehaviorDimension.OUTPUT,
                    input_id=input_id,
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    reference_value=str(ref_item),
                    target_value=str(tar_item),
                    resolution=resolution,
                    within_tolerance=False,
                    verdict=EvaluationVerdict.INCONCLUSIVE,
                    explanation="Missing evidence or unmatched execution counterpart (missing evidence != empty valid evidence)",
                ))
                inconclusive += 1
                continue

            ref_val = self._extract_single_val(ref_item)
            tar_val = self._extract_single_val(tar_item)

            # Check if this is a LATENCY_DIFF evaluation
            if resolution.metric == DifferenceMetric.LATENCY_DIFF:
                ref_lat = self._extract_latency_ms(ref_item, ref_val)
                tar_lat = self._extract_latency_ms(tar_item, tar_val)
                abs_lat_diff = abs(tar_lat - ref_lat)
                is_within = bool(abs_lat_diff <= tol)
                if is_within:
                    passed += 1
                else:
                    failed += 1
                    diffs.append(AdvancedEvaluationDifference(
                        difference_id=f"diff_{uuid.uuid4().hex[:8]}",
                        dimension=BehaviorDimension.NONFUNCTIONAL,
                        input_id=input_id,
                        difference_type=DifferenceType.NONFUNCTIONAL_THRESHOLD_EXCEEDED,
                        reference_value=ref_lat,
                        target_value=tar_lat,
                        observed_difference=round(abs_lat_diff, 6),
                        resolved_threshold=round(tol, 6),
                        resolution=resolution,
                        within_tolerance=False,
                        verdict=EvaluationVerdict.DIFFERENT,
                        explanation=f"Observed latency delta ({abs_lat_diff:.2f}ms) exceeded threshold ({tol:.2f}ms)",
                    ))
                continue

            # Check if this is a COUNT_DIFF evaluation
            if resolution.metric == DifferenceMetric.COUNT_DIFF:
                try:
                    ref_c = int(ref_val)
                    tar_c = int(tar_val)
                    cnt_diff = abs(tar_c - ref_c)
                    is_within = bool(cnt_diff <= tol)
                    if is_within:
                        passed += 1
                    else:
                        failed += 1
                        diffs.append(AdvancedEvaluationDifference(
                            difference_id=f"diff_{uuid.uuid4().hex[:8]}",
                            dimension=BehaviorDimension.OUTPUT,
                            input_id=input_id,
                            difference_type=DifferenceType.NUMERIC_TOLERANCE_EXCEEDED,
                            reference_value=ref_c,
                            target_value=tar_c,
                            observed_difference=float(cnt_diff),
                            resolved_threshold=round(tol, 6),
                            resolution=resolution,
                            within_tolerance=False,
                            verdict=EvaluationVerdict.DIFFERENT,
                            explanation=f"Count delta {cnt_diff} exceeded tolerance {tol}",
                        ))
                    continue
                except (ValueError, TypeError):
                    pass

            # Check if this is SEQUENCE_DISTANCE
            if resolution.metric == DifferenceMetric.SEQUENCE_DISTANCE:
                seq_dist = self._compute_sequence_distance(ref_val, tar_val)
                is_within = bool(seq_dist <= tol)
                if is_within:
                    passed += 1
                else:
                    failed += 1
                    diffs.append(AdvancedEvaluationDifference(
                        difference_id=f"diff_{uuid.uuid4().hex[:8]}",
                        dimension=BehaviorDimension.OUTPUT,
                        input_id=input_id,
                        difference_type=DifferenceType.OUTPUT_VALUE_MISMATCH,
                        reference_value=str(ref_val),
                        target_value=str(tar_val),
                        observed_difference=round(seq_dist, 6),
                        resolved_threshold=round(tol, 6),
                        resolution=resolution,
                        within_tolerance=False,
                        verdict=EvaluationVerdict.DIFFERENT,
                        explanation=f"Sequence distance {seq_dist:.6f} exceeded tolerance {tol:.6f}",
                    ))
                continue

            # Check if this is STRUCTURAL_SIMILARITY
            if resolution.metric == DifferenceMetric.STRUCTURAL_SIMILARITY:
                struct_diff = self._compute_structural_difference(ref_val, tar_val)
                is_within = bool(struct_diff <= tol)
                if is_within:
                    passed += 1
                else:
                    failed += 1
                    diffs.append(AdvancedEvaluationDifference(
                        difference_id=f"diff_{uuid.uuid4().hex[:8]}",
                        dimension=BehaviorDimension.OUTPUT,
                        input_id=input_id,
                        difference_type=DifferenceType.OUTPUT_VALUE_MISMATCH,
                        reference_value=str(ref_val),
                        target_value=str(tar_val),
                        observed_difference=round(struct_diff, 6),
                        resolved_threshold=round(tol, 6),
                        resolution=resolution,
                        within_tolerance=False,
                        verdict=EvaluationVerdict.DIFFERENT,
                        explanation=f"Structural difference {struct_diff:.6f} exceeded tolerance {tol:.6f}",
                    ))
                continue

            # Numerical difference comparison (ABSOLUTE_DIFF, RELATIVE_DIFF, PERCENTAGE_DIFF)
            if isinstance(ref_val, (int, float)) and isinstance(tar_val, (int, float)):
                ref_f = float(ref_val)
                tar_f = float(tar_val)
                abs_diff = abs(tar_f - ref_f)

                if resolution.metric == DifferenceMetric.RELATIVE_DIFF:
                    if abs(ref_f) > 1e-12:
                        observed_diff = abs_diff / abs(ref_f)
                    else:
                        observed_diff = abs_diff
                elif resolution.metric == DifferenceMetric.PERCENTAGE_DIFF:
                    if abs(ref_f) > 1e-12:
                        observed_diff = (abs_diff / abs(ref_f)) * 100.0
                    else:
                        observed_diff = abs_diff * 100.0
                else:
                    observed_diff = abs_diff

                is_within = bool(observed_diff <= tol)
                if is_within:
                    passed += 1
                else:
                    failed += 1
                    diffs.append(AdvancedEvaluationDifference(
                        difference_id=f"diff_{uuid.uuid4().hex[:8]}",
                        dimension=BehaviorDimension.OUTPUT,
                        input_id=input_id,
                        difference_type=DifferenceType.NUMERIC_TOLERANCE_EXCEEDED,
                        reference_value=ref_f,
                        target_value=tar_f,
                        observed_difference=round(observed_diff, 6),
                        resolved_threshold=round(tol, 6),
                        resolution=resolution,
                        within_tolerance=False,
                        verdict=EvaluationVerdict.DIFFERENT,
                        explanation=f"Observed difference {observed_diff:.6f} exceeded tolerance {tol:.6f}",
                    ))
            else:
                # Structural / String exact comparison
                if ref_val == tar_val:
                    passed += 1
                else:
                    failed += 1
                    diffs.append(AdvancedEvaluationDifference(
                        difference_id=f"diff_{uuid.uuid4().hex[:8]}",
                        dimension=BehaviorDimension.OUTPUT,
                        input_id=input_id,
                        difference_type=DifferenceType.OUTPUT_VALUE_MISMATCH,
                        reference_value=ref_val,
                        target_value=tar_val,
                        resolution=resolution,
                        within_tolerance=False,
                        verdict=EvaluationVerdict.DIFFERENT,
                        explanation=f"Value mismatch: reference '{ref_val}' != target '{tar_val}'",
                    ))

        dim_verdicts[BehaviorDimension.OUTPUT.value] = (
            EvaluationVerdict.DIFFERENT if failed > 0
            else (EvaluationVerdict.INCONCLUSIVE if inconclusive > 0 else EvaluationVerdict.EQUIVALENT)
        )

        return {
            "differences": diffs,
            "passed_count": passed,
            "failed_count": failed,
            "inconclusive_count": inconclusive,
            "dimension_verdicts": dim_verdicts,
        }

    def _extract_single_val(self, item: Any) -> Any:
        """Extracts comparable scalar or structured object from an item."""
        if isinstance(item, (int, float, str, bool, list, tuple)) or item is None:
            return item
        if hasattr(item, "observation") and item.observation:
            obs = item.observation.normalized_outputs or item.observation.raw_outputs or item.stdout
            return self._extract_single_val(obs)
        if hasattr(item, "payload") and isinstance(item.payload, dict):
            if "output" in item.payload:
                return self._extract_single_val(item.payload["output"])
            if "data" in item.payload:
                return self._extract_single_val(item.payload["data"])
            return self._extract_single_val(item.payload)
        if isinstance(item, dict):
            if len(item) == 1:
                for k in ("value", "output", "result", "numeric_value"):
                    if k in item:
                        return self._extract_single_val(item[k])
            return item
        if hasattr(item, "data"):
            return self._extract_single_val(item.data)
        return item

    def _extract_latency_ms(self, item: Any, val: Any) -> float:
        """Safely extracts latency/duration in milliseconds from item or observation."""
        if hasattr(item, "duration_ms"):
            return float(item.duration_ms)
        if hasattr(item, "observation") and item.observation:
            return float(getattr(item.observation, "execution_time_ms", 0.0))
        if isinstance(item, dict):
            for k in ("duration_ms", "latency_ms", "execution_time_ms", "latency"):
                if k in item and isinstance(item[k], (int, float)):
                    return float(item[k])
        if isinstance(val, (int, float)):
            return float(val)
        return 0.0

    def _compute_sequence_distance(self, a: Any, b: Any) -> float:
        """Computes normalized Levenshtein sequence distance between two sequences."""
        seq_a = list(a) if isinstance(a, (list, tuple)) else str(a)
        seq_b = list(b) if isinstance(b, (list, tuple)) else str(b)
        n, m = len(seq_a), len(seq_b)
        if max(n, m) == 0:
            return 0.0

        # Levenshtein DP
        dp = [[0] * (m + 1) for _ in range(n + 1)]
        for i in range(n + 1):
            dp[i][0] = i
        for j in range(m + 1):
            dp[0][j] = j

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                cost = 0 if seq_a[i - 1] == seq_b[j - 1] else 1
                dp[i][j] = min(
                    dp[i - 1][j] + 1,      # deletion
                    dp[i][j - 1] + 1,      # insertion
                    dp[i - 1][j - 1] + cost # substitution
                )
        raw_dist = dp[n][m]
        return float(raw_dist) / max(n, m)

    def _compute_structural_difference(self, a: Any, b: Any) -> float:
        """Computes structural difference ratio based on key/path overlap and scalar matches."""
        if a == b:
            return 0.0

        def flatten_keys(obj: Any, prefix: str = "") -> dict[str, Any]:
            res: dict[str, Any] = {}
            if isinstance(obj, dict):
                for k, v in obj.items():
                    p = f"{prefix}.{k}" if prefix else str(k)
                    res.update(flatten_keys(v, p))
            elif isinstance(obj, (list, tuple)):
                for idx, item in enumerate(obj):
                    p = f"{prefix}[{idx}]"
                    res.update(flatten_keys(item, p))
            else:
                res[prefix] = obj
            return res

        flat_a = flatten_keys(a)
        flat_b = flatten_keys(b)

        all_keys = set(flat_a.keys()) | set(flat_b.keys())
        if not all_keys:
            return 0.0

        mismatches = 0
        for k in all_keys:
            if k not in flat_a or k not in flat_b or flat_a[k] != flat_b[k]:
                mismatches += 1

        return float(mismatches) / len(all_keys)



# Module-level singleton
advanced_evaluator = AdvancedBehavioralEvaluator()
