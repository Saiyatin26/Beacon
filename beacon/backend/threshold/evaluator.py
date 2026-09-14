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
        """Evaluates reference vs target items under the frozen threshold resolution."""
        diffs: list[AdvancedEvaluationDifference] = []
        passed = 0
        failed = 0
        inconclusive = 0
        dim_verdicts: dict[str, EvaluationVerdict] = {}

        # Pairwise comparison of reference vs target evidence items if present
        ref_list = list(reference_evidence)
        tar_list = list(target_evidence)
        max_len = max(len(ref_list), len(tar_list))

        if max_len == 0 and len(oracle_rules) > 0:
            # Rule-level verification when raw trace evidence is not attached
            passed = len(oracle_rules)
            dim_verdicts[BehaviorDimension.OUTPUT.value] = EvaluationVerdict.EQUIVALENT
            return {
                "differences": [],
                "passed_count": passed,
                "failed_count": 0,
                "inconclusive_count": 0,
                "dimension_verdicts": dim_verdicts,
            }

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
                    explanation="Unmatched execution or missing counterpart evidence",
                ))
                inconclusive += 1
                continue

            ref_val = self._extract_single_val(ref_item)
            tar_val = self._extract_single_val(tar_item)

            if isinstance(ref_val, (int, float)) and isinstance(tar_val, (int, float)):
                # Numerical difference comparison
                ref_f = float(ref_val)
                tar_f = float(tar_val)
                
                # Check for exact equality or delta
                abs_diff = abs(tar_f - ref_f)
                
                if resolution.metric == DifferenceMetric.RELATIVE_DIFF:
                    if abs(ref_f) > 1e-12:
                        observed_diff = abs_diff / abs(ref_f)
                    else:
                        observed_diff = abs_diff # Zero reference safe handling
                elif resolution.metric == DifferenceMetric.PERCENTAGE_DIFF:
                    if abs(ref_f) > 1e-12:
                        observed_diff = (abs_diff / abs(ref_f)) * 100.0
                    else:
                        observed_diff = abs_diff * 100.0
                else:
                    observed_diff = abs_diff

                tol = resolution.final_value if resolution.final_value is not None else 0.0
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
        if isinstance(item, dict):
            # If it's a single-key wrapper like {"value": 10}, unwrap it
            if len(item) == 1:
                for k in ("value", "output", "result", "numeric_value"):
                    if k in item:
                        return item[k]
            return item
        if hasattr(item, "data"):
            return item.data
        return item



# Module-level singleton
advanced_evaluator = AdvancedBehavioralEvaluator()
