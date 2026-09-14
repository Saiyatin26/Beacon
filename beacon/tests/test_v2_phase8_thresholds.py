"""BEACON V2 — Phase 8 Dynamic / Evidence-Driven Thresholds Test Suite.

Comprehensive tests for threshold strategies, statistical estimators,
numeric edge cases, evidence sufficiency, bounds, fallbacks, determinism,
OracleSet integration, SQLite persistence, and REST API routing.
"""

from datetime import datetime, timezone
import math
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api.main import app
from auth import create_access_token
from auth.repository import auth_repository
from common.contracts import AdapterRole, Observation
from evaluation.models import BehaviorDimension, DifferenceType, EvaluationVerdict
from execution.models import ExecutionResult, ExecutionSession, ExecutionStatus
from execution.repository import execution_repository
from reconciliation.models import (
    EvidenceMetricBasis,
    OracleRule,
    OracleSet,
    OracleSetStatus,
    RuleProvenanceSource,
)
from threshold.engine import TargetContaminationError, ThresholdEngine, threshold_engine
from threshold.evaluator import AdvancedBehavioralEvaluator, advanced_evaluator
from threshold.models import (
    AdvancedEvaluationRequest,
    AdvancedEvaluationResult,
    DifferenceMetric,
    EstimatorType,
    OutlierPolicy,
    ThresholdPolicy,
    ThresholdResolution,
    ThresholdStatus,
    ThresholdStrategy,
)
from threshold.persistence import ThresholdPersistenceStore, threshold_persistence


class TestPhase8DynamicThresholds:
    """Comprehensive test suite for Phase 8 Dynamic Thresholds & Advanced Behavioral Evaluation."""

    # --------------------------------------------------------------------------
    # 1. Fixed Threshold Strategy
    # --------------------------------------------------------------------------
    def test_fixed_threshold_resolution(self):
        engine = ThresholdEngine()
        policy = ThresholdPolicy(
            policy_id="pol_fixed_1",
            strategy=ThresholdStrategy.FIXED,
            parameters={"value": 0.05},
        )
        res = engine.resolve_threshold(metric=DifferenceMetric.ABSOLUTE_DIFF, policy=policy)
        assert res.strategy == ThresholdStrategy.FIXED
        assert res.status == ThresholdStatus.FIXED
        assert res.final_value == 0.05
        assert res.sample_count == 0

    # --------------------------------------------------------------------------
    # 2. Absolute Difference Threshold Strategy
    # --------------------------------------------------------------------------
    def test_absolute_difference_threshold(self):
        engine = ThresholdEngine()
        policy = ThresholdPolicy(
            policy_id="pol_abs_1",
            strategy=ThresholdStrategy.ABSOLUTE,
            parameters={"tolerance": 0.10},
        )
        res = engine.resolve_threshold(metric=DifferenceMetric.ABSOLUTE_DIFF, policy=policy)
        assert res.strategy == ThresholdStrategy.ABSOLUTE
        assert res.status == ThresholdStatus.RESOLVED
        assert res.final_value == 0.10

    # --------------------------------------------------------------------------
    # 3. Relative Difference Threshold Strategy
    # --------------------------------------------------------------------------
    def test_relative_difference_threshold(self):
        engine = ThresholdEngine()
        policy = ThresholdPolicy(
            policy_id="pol_rel_1",
            strategy=ThresholdStrategy.RELATIVE,
            parameters={"tolerance": 0.02},  # 2% relative
        )
        res = engine.resolve_threshold(metric=DifferenceMetric.RELATIVE_DIFF, policy=policy)
        assert res.strategy == ThresholdStrategy.RELATIVE
        assert res.status == ThresholdStatus.RESOLVED
        assert res.final_value == 0.02

    # --------------------------------------------------------------------------
    # 4. Percentage Difference Threshold Strategy
    # --------------------------------------------------------------------------
    def test_percentage_difference_threshold(self):
        engine = ThresholdEngine()
        policy = ThresholdPolicy(
            policy_id="pol_pct_1",
            strategy=ThresholdStrategy.PERCENTAGE,
            parameters={"tolerance": 5.0},  # 5%
        )
        res = engine.resolve_threshold(metric=DifferenceMetric.PERCENTAGE_DIFF, policy=policy)
        assert res.strategy == ThresholdStrategy.PERCENTAGE
        assert res.status == ThresholdStatus.RESOLVED
        assert res.final_value == 5.0

    # --------------------------------------------------------------------------
    # 5. Evidence-Derived Threshold (Mean + StdDev Estimator)
    # --------------------------------------------------------------------------
    def test_evidence_derived_mean_stddev(self):
        engine = ThresholdEngine()
        # Reference observations: 100, 101, 99, 100, 102, 99, 101 (N=7, mean=100.2857)
        samples = [100.0, 101.0, 99.0, 100.0, 102.0, 99.0, 101.0]
        policy = ThresholdPolicy(
            policy_id="pol_ev_1",
            strategy=ThresholdStrategy.EVIDENCE_DERIVED,
            estimator=EstimatorType.MEAN_STDDEV,
            parameters={"k": 2.0},
            minimum_samples=5,
        )
        res = engine.resolve_threshold(
            metric=DifferenceMetric.ABSOLUTE_DIFF,
            policy=policy,
            reference_observations=samples,
            evidence_ids=["e1", "e2", "e3", "e4", "e5", "e6", "e7"],
        )
        assert res.status == ThresholdStatus.RESOLVED
        assert res.strategy == ThresholdStrategy.EVIDENCE_DERIVED
        assert res.sample_count == 7
        assert res.final_value > 0.0
        assert len(res.evidence_ids) == 7

    # --------------------------------------------------------------------------
    # 6. Statistical Estimators: IQR, Max Observed Delta, Percentile 95, Range Fraction
    # --------------------------------------------------------------------------
    def test_all_statistical_estimators(self):
        engine = ThresholdEngine()
        samples = [10.0, 10.5, 9.5, 10.2, 10.8, 9.2, 10.1, 10.4, 9.8, 10.0]

        for est in [
            EstimatorType.MEAN_STDDEV,
            EstimatorType.IQR_ROBUST,
            EstimatorType.MAX_OBSERVED_DELTA,
            EstimatorType.PERCENTILE_95,
            EstimatorType.RANGE_FRACTION,
        ]:
            policy = ThresholdPolicy(
                policy_id=f"pol_{est.value.lower()}",
                strategy=ThresholdStrategy.EVIDENCE_DERIVED,
                estimator=est,
                minimum_samples=5,
            )
            res = engine.resolve_threshold(
                metric=DifferenceMetric.ABSOLUTE_DIFF,
                policy=policy,
                reference_observations=samples,
            )
            assert res.status == ThresholdStatus.RESOLVED
            assert res.final_value > 0.0
            assert res.estimator == est

    # --------------------------------------------------------------------------
    # 7. Numeric Edge Cases: Zero Reference, Zero Target, Negative, Very Large/Small
    # --------------------------------------------------------------------------
    def test_numeric_edge_cases_in_evaluation(self):
        evaluator = AdvancedBehavioralEvaluator()
        oracle = OracleSet(oracle_set_id="os_num_edge", application_id="app_edge")
        policy = ThresholdPolicy(
            strategy=ThresholdStrategy.RELATIVE,
            parameters={"tolerance": 0.05},
        )

        # Reference = 0, Target = 0 (Relative diff must not divide by zero)
        res = evaluator.evaluate(
            application_id="app_edge",
            oracle_set=oracle,
            reference_evidence=[0.0],
            target_evidence=[0.0],
            policy=policy,
        )
        assert res.overall_verdict == EvaluationVerdict.EQUIVALENT
        assert res.failed_count == 0

        # Negative values: ref = -100.0, target = -100.5 (abs diff = 0.5 <= tol 1.0)
        policy_abs = ThresholdPolicy(strategy=ThresholdStrategy.ABSOLUTE, parameters={"tolerance": 1.0})
        res_neg = evaluator.evaluate(
            application_id="app_edge",
            oracle_set=oracle,
            reference_evidence=[-100.0],
            target_evidence=[-100.5],
            policy=policy_abs,
        )
        assert res_neg.overall_verdict == EvaluationVerdict.EQUIVALENT

        # Very small values: ref = 1e-8, target = 1.01e-8
        res_small = evaluator.evaluate(
            application_id="app_edge",
            oracle_set=oracle,
            reference_evidence=[1e-8],
            target_evidence=[1.01e-8],
            policy=ThresholdPolicy(strategy=ThresholdStrategy.RELATIVE, parameters={"tolerance": 0.05}),
        )
        assert res_small.overall_verdict == EvaluationVerdict.EQUIVALENT

    # --------------------------------------------------------------------------
    # 8. Evidence Sufficiency: Insufficient Samples -> INSUFFICIENT_EVIDENCE
    # --------------------------------------------------------------------------
    def test_insufficient_evidence_fails_closed(self):
        engine = ThresholdEngine()
        policy = ThresholdPolicy(
            policy_id="pol_suff_1",
            strategy=ThresholdStrategy.EVIDENCE_DERIVED,
            minimum_samples=10,  # Requires 10
        )
        # Only 3 samples supplied
        res = engine.resolve_threshold(
            metric=DifferenceMetric.ABSOLUTE_DIFF,
            policy=policy,
            reference_observations=[1.0, 2.0, 3.0],
        )
        assert res.status == ThresholdStatus.INSUFFICIENT_EVIDENCE
        assert res.raw_value is None
        assert res.final_value is None
        assert res.sample_count == 3
        assert res.minimum_required_samples == 10

    # --------------------------------------------------------------------------
    # 9. Explicit Fallback Handling on Insufficient Evidence
    # --------------------------------------------------------------------------
    def test_explicit_fallback_on_insufficient_evidence(self):
        engine = ThresholdEngine()
        policy = ThresholdPolicy(
            policy_id="pol_fb_1",
            strategy=ThresholdStrategy.EVIDENCE_DERIVED,
            minimum_samples=10,
            fallback_strategy=ThresholdStrategy.FIXED,
            fallback_value=0.15,
        )
        res = engine.resolve_threshold(
            metric=DifferenceMetric.ABSOLUTE_DIFF,
            policy=policy,
            reference_observations=[1.0, 2.0],  # 2 < 10
        )
        assert res.status == ThresholdStatus.RESOLVED
        assert res.strategy == ThresholdStrategy.FIXED
        assert res.final_value == 0.15
        assert res.fallback_used is True
        assert "Insufficient reference samples" in res.fallback_reason

    # --------------------------------------------------------------------------
    # 10. Minimum and Maximum Bounds Clamping
    # --------------------------------------------------------------------------
    def test_minimum_and_maximum_bounds_clamping(self):
        engine = ThresholdEngine()
        # Case A: Derived raw variance is very small (0.0001), but minimum_bound = 0.05
        samples_tight = [10.0, 10.0001, 10.0, 10.0001, 10.0]
        policy_min = ThresholdPolicy(
            strategy=ThresholdStrategy.EVIDENCE_DERIVED,
            minimum_samples=3,
            minimum_bound=0.05,
            maximum_bound=0.20,
        )
        res_min = engine.resolve_threshold(
            metric=DifferenceMetric.ABSOLUTE_DIFF,
            policy=policy_min,
            reference_observations=samples_tight,
        )
        assert res_min.raw_value < 0.05
        assert res_min.final_value == 0.05

        # Case B: Derived raw variance is very large (5.0), but maximum_bound = 0.50
        samples_loose = [10.0, 20.0, 30.0, 40.0, 50.0]
        policy_max = ThresholdPolicy(
            strategy=ThresholdStrategy.EVIDENCE_DERIVED,
            minimum_samples=3,
            minimum_bound=0.05,
            maximum_bound=0.50,
        )
        res_max = engine.resolve_threshold(
            metric=DifferenceMetric.ABSOLUTE_DIFF,
            policy=policy_max,
            reference_observations=samples_loose,
        )
        assert res_max.raw_value > 0.50
        assert res_max.final_value == 0.50

    # --------------------------------------------------------------------------
    # 11. Determinism and Policy Hashing
    # --------------------------------------------------------------------------
    def test_policy_hash_determinism_and_evidence_shuffling(self):
        engine = ThresholdEngine()
        policy = ThresholdPolicy(
            policy_id="pol_det_1",
            strategy=ThresholdStrategy.EVIDENCE_DERIVED,
            minimum_samples=4,
            minimum_bound=0.01,
            maximum_bound=0.30,
        )
        hash1 = policy.compute_policy_hash()
        hash2 = policy.compute_policy_hash()
        assert hash1 == hash2

        samples_a = [100.0, 101.0, 99.0, 100.5, 99.5]
        samples_b = [99.5, 100.5, 100.0, 99.0, 101.0]  # Shuffled order

        res_a = engine.resolve_threshold(DifferenceMetric.ABSOLUTE_DIFF, policy, samples_a)
        res_b = engine.resolve_threshold(DifferenceMetric.ABSOLUTE_DIFF, policy, samples_b)

        assert res_a.final_value == pytest.approx(res_b.final_value, abs=1e-6)
        assert res_a.fingerprint == res_b.fingerprint

    # --------------------------------------------------------------------------
    # 12. OracleSet Fail-Closed BLOCKED Integration
    # --------------------------------------------------------------------------
    def test_blocked_oracleset_yields_inconclusive(self):
        evaluator = AdvancedBehavioralEvaluator()
        blocked_oracle = OracleSet(
            oracle_set_id="os_blocked",
            application_id="app_blk",
            status=OracleSetStatus.BLOCKED,
        )
        res = evaluator.evaluate(
            application_id="app_blk",
            oracle_set=blocked_oracle,
            reference_evidence=[100.0],
            target_evidence=[100.0],
        )
        assert res.overall_verdict == EvaluationVerdict.INCONCLUSIVE
        assert res.status == "BLOCKED_BY_ORACLE_SET"

    # --------------------------------------------------------------------------
    # 13. Multi-Dimension Conservative Verdict Aggregation
    # --------------------------------------------------------------------------
    def test_conservative_verdict_aggregation(self):
        evaluator = AdvancedBehavioralEvaluator()
        oracle = OracleSet(oracle_set_id="os_agg", application_id="app_agg")
        policy = ThresholdPolicy(strategy=ThresholdStrategy.ABSOLUTE, parameters={"tolerance": 0.1})

        # Test pair 1 is within tolerance (100.0 vs 100.05, diff=0.05 <= 0.1) -> PASS
        # Test pair 2 exceeds tolerance (200.0 vs 200.5, diff=0.5 > 0.1) -> FAIL
        # Overall verdict MUST be DIFFERENT (FAIL)
        res = evaluator.evaluate(
            application_id="app_agg",
            oracle_set=oracle,
            reference_evidence=[100.0, 200.0],
            target_evidence=[100.05, 200.5],
            policy=policy,
        )
        assert res.overall_verdict == EvaluationVerdict.DIFFERENT
        assert res.passed_count == 1
        assert res.failed_count == 1

    # --------------------------------------------------------------------------
    # 14. Persistence Store (SQLite)
    # --------------------------------------------------------------------------
    def test_sqlite_persistence_roundtrip(self):
        policy = ThresholdPolicy(
            policy_id="pol_persist_test",
            strategy=ThresholdStrategy.EVIDENCE_DERIVED,
            minimum_samples=5,
            minimum_bound=0.02,
        )
        threshold_persistence.save_policy(policy)
        retrieved_pol = threshold_persistence.get_policy("pol_persist_test")
        assert retrieved_pol is not None
        assert retrieved_pol.policy_id == "pol_persist_test"
        assert retrieved_pol.minimum_bound == 0.02

        resolution = ThresholdResolution(
            resolution_id="res_persist_test",
            metric=DifferenceMetric.ABSOLUTE_DIFF,
            strategy=ThresholdStrategy.FIXED,
            status=ThresholdStatus.RESOLVED,
            final_value=0.05,
            policy_id="pol_persist_test",
            policy_version="1.0.0",
        )
        threshold_persistence.save_resolution(resolution)

        res_eval = AdvancedEvaluationResult(
            evaluation_id="eval_persist_test",
            application_id="app_persist",
            oracle_set_id="os_persist",
            policy_id="pol_persist_test",
            policy_version="1.0.0",
            overall_verdict=EvaluationVerdict.EQUIVALENT,
            status="COMPLETE",
        )
        threshold_persistence.save_evaluation_result(res_eval)
        retrieved_eval = threshold_persistence.get_evaluation_result("eval_persist_test")
        assert retrieved_eval is not None
        assert retrieved_eval.overall_verdict == EvaluationVerdict.EQUIVALENT

    # --------------------------------------------------------------------------
    # 15. REST API Endpoints
    # --------------------------------------------------------------------------
    def test_rest_api_threshold_endpoints(self):
        token = create_access_token({"sub": "admin", "is_admin": True})
        headers = {"Authorization": f"Bearer {token}"}
        client = TestClient(app)

        # 1. Create policy via API
        pol_payload = {
            "policy_id": "api_test_policy",
            "version": "1.0.0",
            "strategy": "FIXED",
            "metric": "ABSOLUTE_DIFF",
            "parameters": {"value": 0.08},
            "enabled": True,
        }
        r_post = client.post("/api/v2/threshold/policies", json=pol_payload, headers=headers)
        assert r_post.status_code == 200
        assert r_post.json()["policy_id"] == "api_test_policy"

        # 2. Get policy
        r_get = client.get("/api/v2/threshold/policies/api_test_policy", headers=headers)
        assert r_get.status_code == 200
        assert r_get.json()["parameters"]["value"] == 0.08

        # 3. Resolve threshold via API
        resolve_req = {
            "metric": "ABSOLUTE_DIFF",
            "policy_id": "api_test_policy",
            "reference_observations": [10.0, 10.1, 9.9],
        }
        r_res = client.post("/api/v2/threshold/resolve", json=resolve_req, headers=headers)
        assert r_res.status_code == 200
        assert r_res.json()["final_value"] == 0.08

        # 4. Run Advanced Evaluation via API
        eval_req = {
            "application_id": "app_api_test",
            "policy_id": "api_test_policy",
            "persist": True,
        }
        r_eval = client.post("/api/v2/evaluation/advanced", json=eval_req, headers=headers)
        assert r_eval.status_code == 200
        data = r_eval.json()
        assert "evaluation_id" in data
        assert data["overall_verdict"] in ["EQUIVALENT", "INCONCLUSIVE", "NOT_APPLICABLE"]

    # --------------------------------------------------------------------------
    # 16. Structured Value Comparison & Object Key Invariance
    # --------------------------------------------------------------------------
    def test_structured_value_comparison_and_object_keys(self):
        evaluator = AdvancedBehavioralEvaluator()
        oracle = OracleSet(oracle_set_id="os_struct", application_id="app_struct")
        
        # Identical dictionary contents in different key insertion order -> EQUIVALENT
        dict_a = {"b": 2, "a": 1, "nested": {"y": "yes", "x": 10}}
        dict_b = {"a": 1, "b": 2, "nested": {"x": 10, "y": "yes"}}
        
        res = evaluator.evaluate(
            application_id="app_struct",
            oracle_set=oracle,
            reference_evidence=[dict_a],
            target_evidence=[dict_b],
        )
        assert res.overall_verdict == EvaluationVerdict.EQUIVALENT
        assert res.failed_count == 0

    # --------------------------------------------------------------------------
    # 17. Missing vs Null vs Empty Differentiation
    # --------------------------------------------------------------------------
    def test_missing_vs_null_vs_empty(self):
        evaluator = AdvancedBehavioralEvaluator()
        oracle = OracleSet(oracle_set_id="os_null_test", application_id="app_null")

        # Ref has key with None, Target has empty string -> DIFFERENT
        res_null = evaluator.evaluate(
            application_id="app_null",
            oracle_set=oracle,
            reference_evidence=[{"key": None}],
            target_evidence=[{"key": ""}],
        )
        assert res_null.overall_verdict == EvaluationVerdict.DIFFERENT

    # --------------------------------------------------------------------------
    # 18. OracleSet Immutability (Phase 7 Specification Untouched)
    # --------------------------------------------------------------------------
    def test_oracleset_immutability_during_evaluation(self):
        evaluator = AdvancedBehavioralEvaluator()
        rule = OracleRule(
            rule_id="o_immut",
            rule_type="BUSINESS_RULE",
            canonical_expression="IF x > 10 THEN y == true",
            source=RuleProvenanceSource.USER_DEFINED,
            support_count=10,
        )
        oracle = OracleSet(
            oracle_set_id="os_immut_test",
            application_id="app_immut",
            rules=[rule],
        )
        hash_before = oracle.compute_oracle_set_hash()

        evaluator.evaluate(
            application_id="app_immut",
            oracle_set=oracle,
            reference_evidence=[100.0],
            target_evidence=[100.0],
        )

        hash_after = oracle.compute_oracle_set_hash()
        assert hash_before == hash_after
        assert len(oracle.rules) == 1
        assert oracle.rules[0].rule_id == "o_immut"

    # --------------------------------------------------------------------------
    # 19. Policy Versioning & Hash Sensitivity
    # --------------------------------------------------------------------------
    def test_policy_versioning_and_hash_sensitivity(self):
        p1 = ThresholdPolicy(policy_id="pol_v", version="1.0.0", strategy=ThresholdStrategy.FIXED, parameters={"value": 0.05})
        p2 = ThresholdPolicy(policy_id="pol_v", version="2.0.0", strategy=ThresholdStrategy.FIXED, parameters={"value": 0.05})
        p3 = ThresholdPolicy(policy_id="pol_v", version="1.0.0", strategy=ThresholdStrategy.FIXED, parameters={"value": 0.10})

        # Version change alters policy hash
        assert p1.compute_policy_hash() != p2.compute_policy_hash()
        # Parameter change alters policy hash
        assert p1.compute_policy_hash() != p3.compute_policy_hash()

    # --------------------------------------------------------------------------
    # 20. NaN and Infinity Sanitization in Reference Evidence
    # --------------------------------------------------------------------------
    def test_nan_and_infinity_sanitization(self):
        engine = ThresholdEngine()
        policy = ThresholdPolicy(
            strategy=ThresholdStrategy.EVIDENCE_DERIVED,
            minimum_samples=3,
        )
        # 3 valid numbers and 3 invalid (NaN, Inf, None)
        dirty_samples = [10.0, float("nan"), 10.2, float("inf"), None, 9.8]
        res = engine.resolve_threshold(
            metric=DifferenceMetric.ABSOLUTE_DIFF,
            policy=policy,
            reference_observations=dirty_samples,
        )
        assert res.status == ThresholdStatus.RESOLVED
        assert res.sample_count == 3  # Only the 3 clean numbers counted
        assert not math.isnan(res.final_value)
        assert not math.isinf(res.final_value)

    # --------------------------------------------------------------------------
    # 21. ISSUE A: Real Phase 3 Evidence Loading via API
    # --------------------------------------------------------------------------
    def test_api_loads_real_phase3_evidence_from_sessions(self):
        token = create_access_token({"sub": "admin", "is_admin": True})
        headers = {"Authorization": f"Bearer {token}"}
        client = TestClient(app)

        # 1. Create and persist real reference session with execution records
        ref_sess = ExecutionSession(
            session_id="sess_ref_real_001",
            application_id="app_phase3_test",
            adapter_id="ref_adapter",
            role=AdapterRole.REFERENCE,
            status=ExecutionStatus.SUCCEEDED,
        )
        execution_repository.save_session(ref_sess)

        res1 = ExecutionResult(
            execution_id="exec_ref_1",
            session_id="sess_ref_real_001",
            application_id="app_phase3_test",
            role=AdapterRole.REFERENCE,
            status=ExecutionStatus.SUCCEEDED,
            stdout='{"value": 100.0}',
            observation=Observation(
                input_id="inp_1",
                raw_inputs={},
                raw_outputs={"value": 100.0},
                normalized_outputs={"value": 100.0},
            ),
        )
        execution_repository.save_result(res1)

        # 2. Create and persist real target session with execution records
        tar_sess = ExecutionSession(
            session_id="sess_tar_real_001",
            application_id="app_phase3_test",
            adapter_id="tar_adapter",
            role=AdapterRole.TARGET,
            status=ExecutionStatus.SUCCEEDED,
        )
        execution_repository.save_session(tar_sess)

        res2 = ExecutionResult(
            execution_id="exec_tar_1",
            session_id="sess_tar_real_001",
            application_id="app_phase3_test",
            role=AdapterRole.TARGET,
            status=ExecutionStatus.SUCCEEDED,
            stdout='{"value": 100.02}',
            observation=Observation(
                input_id="inp_1",
                raw_inputs={},
                raw_outputs={"value": 100.02},
                normalized_outputs={"value": 100.02},
            ),
        )
        execution_repository.save_result(res2)

        # 3. Call Advanced Evaluation with real session IDs
        eval_req = {
            "application_id": "app_phase3_test",
            "reference_session_id": "sess_ref_real_001",
            "target_session_id": "sess_tar_real_001",
            "custom_policy": {
                "strategy": "ABSOLUTE",
                "metric": "ABSOLUTE_DIFF",
                "parameters": {"tolerance": 0.05},
            },
            "persist": False,
        }

        resp = client.post("/api/v2/evaluation/advanced", json=eval_req, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_verdict"] == "EQUIVALENT"
        assert data["total_evaluations"] == 1
        assert data["passed_count"] == 1

    # --------------------------------------------------------------------------
    # 22. ISSUE A: Session Role Confusion & Missing Session Rejection
    # --------------------------------------------------------------------------
    def test_api_rejects_session_role_confusion_and_missing_session(self):
        token = create_access_token({"sub": "admin", "is_admin": True})
        headers = {"Authorization": f"Bearer {token}"}
        client = TestClient(app)

        # A. Wrong role: supply target session as reference_session_id
        eval_req_wrong_role = {
            "application_id": "app_phase3_test",
            "reference_session_id": "sess_tar_real_001",  # Has role 'target'
            "target_session_id": "sess_tar_real_001",
        }
        r_role = client.post("/api/v2/evaluation/advanced", json=eval_req_wrong_role, headers=headers)
        assert r_role.status_code == 400
        assert "expected REFERENCE" in r_role.json()["detail"]

        # B. Missing session: supply non-existent session ID
        eval_req_missing = {
            "application_id": "app_phase3_test",
            "reference_session_id": "sess_non_existent_999",
            "target_session_id": "sess_tar_real_001",
        }
        r_miss = client.post("/api/v2/evaluation/advanced", json=eval_req_missing, headers=headers)
        assert r_miss.status_code == 404
        assert "not found" in r_miss.json()["detail"]

    # --------------------------------------------------------------------------
    # 23. ISSUE C: Resolution Identity Tied to Canonical Evidence IDs
    # --------------------------------------------------------------------------
    def test_resolution_identity_sensitive_to_evidence_ids(self):
        engine = ThresholdEngine()
        policy = ThresholdPolicy(
            strategy=ThresholdStrategy.EVIDENCE_DERIVED,
            minimum_samples=3,
        )
        samples = [10.0, 11.0, 9.0]

        # Resolution with evidence set A
        res_a = engine.resolve_threshold(
            DifferenceMetric.ABSOLUTE_DIFF, policy, samples, evidence_ids=["e1", "e2", "e3"]
        )
        # Resolution with evidence set B (different IDs, identical values & count)
        res_b = engine.resolve_threshold(
            DifferenceMetric.ABSOLUTE_DIFF, policy, samples, evidence_ids=["e7", "e8", "e9"]
        )
        # Resolution with evidence set A in different order
        res_a_shuffled = engine.resolve_threshold(
            DifferenceMetric.ABSOLUTE_DIFF, policy, samples, evidence_ids=["e3", "e1", "e2"]
        )

        assert res_a.fingerprint != res_b.fingerprint
        assert res_a.resolution_id != res_b.resolution_id
        assert res_a.fingerprint == res_a_shuffled.fingerprint
        assert res_a.resolution_id == res_a_shuffled.resolution_id

    # --------------------------------------------------------------------------
    # 24. ISSUE D: End-to-End Metrics (COUNT_DIFF, LATENCY_DIFF, SEQUENCE, STRUCTURAL)
    # --------------------------------------------------------------------------
    def test_all_advertised_metrics_end_to_end(self):
        evaluator = AdvancedBehavioralEvaluator()
        oracle = OracleSet(oracle_set_id="os_metrics", application_id="app_metrics")

        # 1. COUNT_DIFF
        pol_count = ThresholdPolicy(metric=DifferenceMetric.COUNT_DIFF, strategy=ThresholdStrategy.FIXED, parameters={"tolerance": 2})
        res_count_pass = evaluator.evaluate(
            application_id="app_m", oracle_set=oracle, reference_evidence=[10], target_evidence=[12], policy=pol_count
        )
        assert res_count_pass.overall_verdict == EvaluationVerdict.EQUIVALENT

        res_count_fail = evaluator.evaluate(
            application_id="app_m", oracle_set=oracle, reference_evidence=[10], target_evidence=[15], policy=pol_count
        )
        assert res_count_fail.overall_verdict == EvaluationVerdict.DIFFERENT

        # 2. LATENCY_DIFF
        pol_lat = ThresholdPolicy(metric=DifferenceMetric.LATENCY_DIFF, strategy=ThresholdStrategy.FIXED, parameters={"tolerance": 50.0})
        res_lat_pass = evaluator.evaluate(
            application_id="app_m", oracle_set=oracle,
            reference_evidence=[{"duration_ms": 100.0}], target_evidence=[{"duration_ms": 140.0}], policy=pol_lat
        )
        assert res_lat_pass.overall_verdict == EvaluationVerdict.EQUIVALENT

        res_lat_fail = evaluator.evaluate(
            application_id="app_m", oracle_set=oracle,
            reference_evidence=[{"duration_ms": 100.0}], target_evidence=[{"duration_ms": 200.0}], policy=pol_lat
        )
        assert res_lat_fail.overall_verdict == EvaluationVerdict.DIFFERENT

        # 3. SEQUENCE_DISTANCE
        pol_seq = ThresholdPolicy(metric=DifferenceMetric.SEQUENCE_DISTANCE, strategy=ThresholdStrategy.FIXED, parameters={"tolerance": 0.25})
        res_seq_pass = evaluator.evaluate(
            application_id="app_m", oracle_set=oracle,
            reference_evidence=[["a", "b", "c", "d"]], target_evidence=[["a", "b", "c", "e"]], policy=pol_seq
        )
        # 1 edit in 4 items = 0.25 <= 0.25 -> EQUIVALENT
        assert res_seq_pass.overall_verdict == EvaluationVerdict.EQUIVALENT

        res_seq_fail = evaluator.evaluate(
            application_id="app_m", oracle_set=oracle,
            reference_evidence=[["a", "b", "c", "d"]], target_evidence=[["w", "x", "y", "z"]], policy=pol_seq
        )
        assert res_seq_fail.overall_verdict == EvaluationVerdict.DIFFERENT

        # 4. STRUCTURAL_SIMILARITY
        pol_struct = ThresholdPolicy(metric=DifferenceMetric.STRUCTURAL_SIMILARITY, strategy=ThresholdStrategy.FIXED, parameters={"tolerance": 0.2})
        obj_a = {"user": "Alice", "role": "admin", "settings": {"theme": "dark", "lang": "en"}}
        obj_b = {"user": "Alice", "role": "admin", "settings": {"theme": "dark", "lang": "fr"}} # 1 key diff out of 4
        res_struct_pass = evaluator.evaluate(
            application_id="app_m", oracle_set=oracle,
            reference_evidence=[obj_a], target_evidence=[obj_b], policy=pol_struct
        )
        # 1 mismatch out of 4 flattened keys = 0.25 > 0.20 -> DIFFERENT
        assert res_struct_pass.overall_verdict == EvaluationVerdict.DIFFERENT

    # --------------------------------------------------------------------------
    # 25. ISSUE E: Strict Threshold Policy Validation
    # --------------------------------------------------------------------------
    def test_strict_policy_validation(self):
        # 1. Negative tolerance rejected
        with pytest.raises(ValueError) as exc_neg_tol:
            ThresholdPolicy(strategy=ThresholdStrategy.RELATIVE, parameters={"tolerance": -0.05})
        assert "cannot be negative" in str(exc_neg_tol.value)

        # 2. minimum_bound > maximum_bound rejected
        with pytest.raises(ValueError) as exc_bounds:
            ThresholdPolicy(minimum_bound=10.0, maximum_bound=5.0)
        assert "cannot exceed maximum_bound" in str(exc_bounds.value)

        # 3. Negative minimum_samples rejected
        with pytest.raises(ValueError) as exc_samples:
            ThresholdPolicy(minimum_samples=-3)
        assert "cannot be negative" in str(exc_samples.value)

        # 4. NaN / Inf bounds rejected
        with pytest.raises(ValueError) as exc_nan:
            ThresholdPolicy(minimum_bound=float("nan"))
        assert "cannot be NaN" in str(exc_nan.value)

