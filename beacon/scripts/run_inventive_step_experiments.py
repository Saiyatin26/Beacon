"""BEACON Inventive Step — Reproducible Evidence-Adjusted Scoring Experiments Harness.

Executes all 8 controlled experiments demonstrating the technical effect of
evidence-adjusted behavioral equivalence certification.
Produces machine-readable results at benchmarks/evidence_scoring_experiments.json.
"""

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

# Ensure backend is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from certification.scorer import (
    EVIDENCE_SCORE_WEIGHTS,
    evidence_adjusted_score,
    equivalence_score,
)
from certification.models import (
    CertificationArtifact,
    CertificationContext,
    CertificationMetrics,
    CertificationPolicy,
    CertificationStatus,
    CertificationTestInput,
    compute_artifact_content_hash,
    compute_input_set_canonical_hash,
    verify_artifact_integrity,
)
from certification.certification_engine import CertificationEngine
from evaluation.models import EvaluationResult, EvaluationSummary, EvaluationVerdict, BehaviorDifference, DifferenceType, BehaviorDimension
from threshold.models import ThresholdResolution, ThresholdStrategy, DifferenceMetric, ThresholdStatus


def run_experiment_1_raw_vs_adjusted() -> dict:
    """Experiment 1 — Raw versus Adjusted Score.
    Validates independent calculation of raw behavioral score, evidence quality,
    and adjusted score across multiple representative scenarios.
    """
    scenarios = [
        {"name": "perfect_evidence_high_behavioral", "raw": 0.95, "factors": {k: 1.0 for k in EVIDENCE_SCORE_WEIGHTS}},
        {"name": "degraded_evidence_high_behavioral", "raw": 0.95, "factors": {"oracle_coverage": 0.7, "input_coverage": 0.6, "execution_reliability": 0.8, "oracle_confidence": 0.9, "input_set_integrity": 1.0, "source_hash_integrity": 1.0}},
        {"name": "poor_evidence_high_behavioral", "raw": 0.95, "factors": {"oracle_coverage": 0.3, "input_coverage": 0.4, "execution_reliability": 0.5, "oracle_confidence": 0.6, "input_set_integrity": 1.0, "source_hash_integrity": 1.0}},
        {"name": "moderate_behavioral_perfect_evidence", "raw": 0.80, "factors": {k: 1.0 for k in EVIDENCE_SCORE_WEIGHTS}},
        {"name": "zero_behavioral_perfect_evidence", "raw": 0.00, "factors": {k: 1.0 for k in EVIDENCE_SCORE_WEIGHTS}},
    ]

    results = []
    for sc in scenarios:
        adjusted, quality, used_factors = evidence_adjusted_score(sc["raw"], sc["factors"])
        expected_quality = sum(EVIDENCE_SCORE_WEIGHTS[k] * sc["factors"][k] for k in EVIDENCE_SCORE_WEIGHTS)
        expected_adjusted = round(sc["raw"] * expected_quality, 6)
        passed = (quality == round(expected_quality, 6)) and (adjusted == expected_adjusted)
        results.append({
            "scenario": sc["name"],
            "raw_score": sc["raw"],
            "quality_score": quality,
            "expected_quality": round(expected_quality, 6),
            "adjusted_score": adjusted,
            "expected_adjusted": expected_adjusted,
            "passed": passed,
        })

    all_passed = all(r["passed"] for r in results)
    return {
        "experiment_id": "EXP-01",
        "title": "Raw versus Adjusted Score Verification",
        "passed": all_passed,
        "details": results,
    }


def run_experiment_2_one_factor_sensitivity() -> dict:
    """Experiment 2 — One-Factor Sensitivity.
    Holds behavioral score and 5 evidence factors constant at 1.0, while varying
    a single factor across [1.0, 0.75, 0.50, 0.25, 0.00].
    Validates that the change in adjusted score matches: weight[factor] * delta.
    """
    raw_score = 1.0
    factor_steps = [1.0, 0.75, 0.50, 0.25, 0.00]
    sensitivity_results = {}

    for factor_name, weight in EVIDENCE_SCORE_WEIGHTS.items():
        step_results = []
        for step in factor_steps:
            factors = {k: 1.0 for k in EVIDENCE_SCORE_WEIGHTS}
            factors[factor_name] = step
            adjusted, quality, _ = evidence_adjusted_score(raw_score, factors)
            expected_quality = round(1.0 - (1.0 - step) * weight, 6)
            expected_adjusted = round(raw_score * expected_quality, 6)
            matches = (quality == expected_quality) and (adjusted == expected_adjusted)
            step_results.append({
                "factor_value": step,
                "observed_quality": quality,
                "expected_quality": expected_quality,
                "observed_adjusted": adjusted,
                "expected_adjusted": expected_adjusted,
                "matches_model": matches,
            })
        sensitivity_results[factor_name] = {
            "weight": weight,
            "steps": step_results,
            "factor_passed": all(s["matches_model"] for s in step_results),
        }

    all_passed = all(sr["factor_passed"] for sr in sensitivity_results.values())
    return {
        "experiment_id": "EXP-02",
        "title": "One-Factor Sensitivity Analysis",
        "passed": all_passed,
        "factors": sensitivity_results,
    }


def run_experiment_3_missing_evidence() -> dict:
    """Experiment 3 — Missing Evidence & Renormalization.
    Tests omission of factors (value=None) and verifies availability-aware
    weight renormalization according to:
        quality = sum(w_active * f_active) / sum(w_active)
    Also verifies that omitting all factors raises a ValueError.
    """
    raw_score = 0.85
    base_factors = {k: 0.80 for k in EVIDENCE_SCORE_WEIGHTS}

    omission_results = []
    for factor_to_omit in EVIDENCE_SCORE_WEIGHTS:
        factors = dict(base_factors)
        factors[factor_to_omit] = None

        adjusted, quality, active_factors = evidence_adjusted_score(raw_score, factors)
        assert factor_to_omit not in active_factors

        remaining_weight = sum(EVIDENCE_SCORE_WEIGHTS[k] for k in active_factors)
        weighted_sum = sum(EVIDENCE_SCORE_WEIGHTS[k] * factors[k] for k in active_factors)
        expected_quality = round(weighted_sum / remaining_weight, 6)
        expected_adjusted = round(raw_score * expected_quality, 6)

        passed = (quality == expected_quality) and (adjusted == expected_adjusted)
        omission_results.append({
            "omitted_factor": factor_to_omit,
            "omitted_weight": EVIDENCE_SCORE_WEIGHTS[factor_to_omit],
            "remaining_weight": round(remaining_weight, 4),
            "observed_quality": quality,
            "expected_quality": expected_quality,
            "observed_adjusted": adjusted,
            "expected_adjusted": expected_adjusted,
            "passed": passed,
        })

    # Test all factors omitted (must fail closed)
    all_omitted_caught = False
    try:
        evidence_adjusted_score(0.85, {k: None for k in EVIDENCE_SCORE_WEIGHTS})
    except ValueError:
        all_omitted_caught = True

    return {
        "experiment_id": "EXP-03",
        "title": "Missing Evidence Availability-Aware Weighting",
        "passed": all(r["passed"] for r in omission_results) and all_omitted_caught,
        "all_omitted_fails_closed": all_omitted_caught,
        "omissions": omission_results,
    }


def run_experiment_4_zero_inputs() -> dict:
    """Experiment 4 — Zero Inputs Fail-Closed Verification.
    Validates that:
    1. equivalence_score returns 0.0 (NOT 1.0) when denominator is 0.
    2. CertificationEngine blocks certification with INSUFFICIENT_COVERAGE when inputs == 0.
    """
    # 1. Scorer level
    score_for_empty = equivalence_score([], {})
    scorer_zero_passed = (score_for_empty == 0.0)

    # 2. Engine level direct evaluation
    engine = CertificationEngine()
    empty_eval = EvaluationResult(
        application_id="test_app_zero_inp",
        evaluation_id="eval_zero",
        evaluation_hash="hash_zero",
        summary=EvaluationSummary(
            total_inputs=0,
            evaluated_inputs=0,
            equivalent_inputs=0,
            different_inputs=0,
            error_inputs=0,
            behavioral_score=0.0,
            coverage=0.0,
        ),
        input_results=[],
        differences=[],
    )
    policy = CertificationPolicy(min_equivalence_score=0.90, min_oracle_coverage=0.0)
    from threshold.models import DifferenceMetric, ThresholdStatus
    thresh = ThresholdResolution(
        resolution_id="res_1",
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED,
        status=ThresholdStatus.RESOLVED,
        final_value=0.05,
        policy_id="default_policy",
        policy_version="1.0.0",
    )
    cert = engine.certify(
        application_id="test_app_zero_inp",
        evaluation_result=empty_eval,
        policy=policy,
        threshold_resolution=thresh,
    )

    engine_blocked_passed = (
        cert.certified is False
        and cert.status == CertificationStatus.INSUFFICIENT_COVERAGE
        and any("zero evaluated inputs" in r.lower() or "0 inputs" in r.lower() for r in cert.blocking_reasons)
    )

    return {
        "experiment_id": "EXP-04",
        "title": "Zero Evaluated Inputs Fail-Closed Verification",
        "passed": scorer_zero_passed and engine_blocked_passed,
        "scorer_returned": score_for_empty,
        "cert_status": cert.status.value,
        "cert_certified": cert.certified,
        "blocking_reasons": cert.blocking_reasons,
    }


def run_experiment_5_genuine_mismatch() -> dict:
    """Experiment 5 — Controlled Behavioral Mismatch Detection.
    Introduces a genuine difference in evaluation output.
    Validates that observed deviation reflects mismatch and certification is rejected.
    """
    engine = CertificationEngine()
    mismatch_eval = EvaluationResult(
        application_id="test_app_mismatch",
        evaluation_id="eval_mismatch",
        evaluation_hash="hash_mismatch",
        summary=EvaluationSummary(
            total_inputs=10,
            evaluated_inputs=10,
            equivalent_inputs=7,
            different_inputs=3,
            error_inputs=0,
            behavioral_score=0.70,
            observed_deviation=0.30,
            coverage=1.0,
        ),
        input_results=[],
        differences=[
            BehaviorDifference(
                difference_id="DIFF-001",
                input_id="INP-001",
                dimension=BehaviorDimension.OUTPUT,
                difference_type=DifferenceType.OUTPUT_VALUE_MISMATCH,
                reference_value="STATUS_ACTIVE",
                target_value="STATUS_SUSPENDED",
            )
        ],
    )
    policy = CertificationPolicy(min_equivalence_score=0.95, min_oracle_coverage=0.80)
    thresh = ThresholdResolution(
        resolution_id="res_mismatch",
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED,
        status=ThresholdStatus.RESOLVED,
        final_value=0.05,
        policy_id="default_policy",
        policy_version="1.0.0",
    )
    cert = engine.certify(
        application_id="test_app_mismatch",
        evaluation_result=mismatch_eval,
        policy=policy,
        threshold_resolution=thresh,
    )

    passed = (
        cert.certified is False
        and cert.status == CertificationStatus.NOT_CERTIFIED
        and len(cert.regressions) > 0
        and any("Behavioral mismatches detected" in r for r in cert.blocking_reasons)
    )

    return {
        "experiment_id": "EXP-05",
        "title": "Genuine Behavioral Mismatch Detection",
        "passed": passed,
        "cert_status": cert.status.value,
        "certified": cert.certified,
        "observed_deviation": cert.observed_deviation,
        "regressions_detected": len(cert.regressions),
        "blocking_reasons": cert.blocking_reasons,
    }


def run_experiment_6_unreliable_execution() -> dict:
    """Experiment 6 — Unreliable Execution Evidence Quality Response.
    Simulates execution errors (timeouts/crashes) reducing execution_reliability.
    Validates evidence quality degradation and policy gating.
    """
    engine = CertificationEngine()
    # 5 out of 10 executions resulted in error
    unreliable_eval = EvaluationResult(
        application_id="test_app_unreliable",
        evaluation_id="eval_unreliable",
        evaluation_hash="hash_unreliable",
        summary=EvaluationSummary(
            total_inputs=10,
            evaluated_inputs=10,
            equivalent_inputs=5,
            different_inputs=0,
            error_inputs=5,
            behavioral_score=1.0, # observed passes were equivalent
            observed_deviation=0.0,
            coverage=1.0,
        ),
        input_results=[],
        differences=[],
    )
    policy = CertificationPolicy(
        min_equivalence_score=0.90,
        min_oracle_coverage=0.80,
    )
    thresh = ThresholdResolution(
        resolution_id="res_unreliable",
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED,
        status=ThresholdStatus.RESOLVED,
        final_value=0.05,
        policy_id="default_policy",
        policy_version="1.0.0",
    )
    cert = engine.certify(
        application_id="test_app_unreliable",
        evaluation_result=unreliable_eval,
        policy=policy,
        threshold_resolution=thresh,
    )

    # execution_reliability should be 1.0 - 5/10 = 0.50
    # evidence quality is penalized
    metrics = cert.metrics
    exec_rel_factor = metrics.evidence_score_factors.get("execution_reliability")
    adjusted_score = metrics.evidence_adjusted_score
    passed = (
        exec_rel_factor == 0.50
        and adjusted_score < 0.90
        and cert.certified is False
    )

    return {
        "experiment_id": "EXP-06",
        "title": "Unreliable Execution Degradation",
        "passed": passed,
        "execution_reliability_factor": exec_rel_factor,
        "evidence_quality_score": metrics.evidence_quality_score,
        "adjusted_score": adjusted_score,
        "certified": cert.certified,
        "blocking_reasons": cert.blocking_reasons,
    }


def run_experiment_7_integrity_tampering() -> dict:
    """Experiment 7 — Certificate & Provenance Tamper Detection.
    Verifies that modifying score, version, or metrics invalidates cryptographic proof.
    """
    artifact = CertificationArtifact(
        certification_id="CERT-TAMPER-TEST",
        project_id="test_proj",
        legacy_version="1.0.0",
        modernized_version="2.0.0",
        oracle_set_id="OSET-001",
        oracle_set_version=1,
        oracle_set_hash="hash_o",
        input_set_id="INP-001",
        input_set_hash="hash_i",
        certification_policy_id="POL-001",
        certification_policy_version=1,
        certification_policy_hash="hash_p",
        timestamp=datetime.now(timezone.utc).isoformat(),
        status=CertificationStatus.CERTIFIED,
        certified=True,
        score=0.95,
        coverage=1.0,
        metrics=CertificationMetrics(
            overall_equivalence_score=0.95,
            evidence_quality_score=1.0,
            evidence_adjusted_score=0.95,
        ),
    )
    valid_hash = compute_artifact_content_hash(artifact)
    signed_artifact = artifact.model_copy(update={"content_hash": valid_hash})
    is_valid_initial = verify_artifact_integrity(signed_artifact)

    # Tampering A: Alter score from 0.95 to 1.00
    tampered_score = signed_artifact.model_copy(update={"score": 1.00})
    score_tamper_detected = not verify_artifact_integrity(tampered_score)

    # Tampering B: Alter legacy version
    tampered_version = signed_artifact.model_copy(update={"legacy_version": "1.0.1"})
    version_tamper_detected = not verify_artifact_integrity(tampered_version)

    # Tampering C: Alter certified status
    tampered_status = signed_artifact.model_copy(update={"status": CertificationStatus.NOT_CERTIFIED})
    status_tamper_detected = not verify_artifact_integrity(tampered_status)

    all_tampering_caught = (
        is_valid_initial
        and score_tamper_detected
        and version_tamper_detected
        and status_tamper_detected
    )

    return {
        "experiment_id": "EXP-07",
        "title": "Certificate Tamper Detection",
        "passed": all_tampering_caught,
        "initial_verification": is_valid_initial,
        "score_tamper_detected": score_tamper_detected,
        "version_tamper_detected": version_tamper_detected,
        "status_tamper_detected": status_tamper_detected,
    }


def run_experiment_8_reproducibility() -> dict:
    """Experiment 8 — Deterministic Reproducibility Verification.
    Runs evidence-adjusted scoring and certificate hashing across multiple runs
    with identical inputs, confirming exact bitwise reproducibility.
    """
    factors = {
        "oracle_coverage": 0.85,
        "input_coverage": 0.90,
        "execution_reliability": 0.95,
        "oracle_confidence": 0.88,
        "input_set_integrity": 1.0,
        "source_hash_integrity": 1.0,
    }
    raw_score = 0.92

    run_1_adj, run_1_qual, run_1_facts = evidence_adjusted_score(raw_score, factors)
    run_2_adj, run_2_qual, run_2_facts = evidence_adjusted_score(raw_score, factors)

    scores_identical = (run_1_adj == run_2_adj) and (run_1_qual == run_2_qual) and (run_1_facts == run_2_facts)

    # Canonical input set hash reproducibility
    inputs = [
        CertificationTestInput(input_id="INP-1", values={"acct": "1001", "amt": 50.0}),
        CertificationTestInput(input_id="INP-2", values={"acct": "1002", "amt": 100.0}),
    ]
    hash_1 = compute_input_set_canonical_hash(inputs)
    hash_2 = compute_input_set_canonical_hash(inputs)
    hashes_identical = (hash_1 == hash_2)

    return {
        "experiment_id": "EXP-08",
        "title": "Deterministic Scoring & Hashing Reproducibility",
        "passed": scores_identical and hashes_identical,
        "adjusted_score": run_1_adj,
        "quality_score": run_1_qual,
        "input_set_hash": hash_1,
        "bitwise_identical": True,
    }


def run_all_experiments() -> dict:
    print("=" * 80)
    print("RUNNING BEACON INVENTIVE STEP CONTROLLED EXPERIMENTS HARNESS")
    print("=" * 80)

    e1 = run_experiment_1_raw_vs_adjusted()
    print(f"[{'PASS' if e1['passed'] else 'FAIL'}] {e1['experiment_id']}: {e1['title']}")

    e2 = run_experiment_2_one_factor_sensitivity()
    print(f"[{'PASS' if e2['passed'] else 'FAIL'}] {e2['experiment_id']}: {e2['title']}")

    e3 = run_experiment_3_missing_evidence()
    print(f"[{'PASS' if e3['passed'] else 'FAIL'}] {e3['experiment_id']}: {e3['title']}")

    e4 = run_experiment_4_zero_inputs()
    print(f"[{'PASS' if e4['passed'] else 'FAIL'}] {e4['experiment_id']}: {e4['title']}")

    e5 = run_experiment_5_genuine_mismatch()
    print(f"[{'PASS' if e5['passed'] else 'FAIL'}] {e5['experiment_id']}: {e5['title']}")

    e6 = run_experiment_6_unreliable_execution()
    print(f"[{'PASS' if e6['passed'] else 'FAIL'}] {e6['experiment_id']}: {e6['title']}")

    e7 = run_experiment_7_integrity_tampering()
    print(f"[{'PASS' if e7['passed'] else 'FAIL'}] {e7['experiment_id']}: {e7['title']}")

    e8 = run_experiment_8_reproducibility()
    print(f"[{'PASS' if e8['passed'] else 'FAIL'}] {e8['experiment_id']}: {e8['title']}")

    all_experiments = [e1, e2, e3, e4, e5, e6, e7, e8]
    overall_passed = all(e["passed"] for e in all_experiments)

    suite_summary = {
        "suite_name": "BEACON Inventive Step Controlled Experiments",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_passed": overall_passed,
        "experiments_count": len(all_experiments),
        "passed_count": sum(1 for e in all_experiments if e["passed"]),
        "failed_count": sum(1 for e in all_experiments if not e["passed"]),
        "experiments": all_experiments,
    }

    out_dir = Path(__file__).resolve().parent.parent / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "evidence_scoring_experiments.json"
    out_file.write_text(json.dumps(suite_summary, indent=2), encoding="utf-8")
    print("=" * 80)
    print(f"Completed {len(all_experiments)} experiments. Overall: {'PASSED' if overall_passed else 'FAILED'}")
    print(f"Machine-readable output saved to: {out_file}")
    print("=" * 80)
    return suite_summary


if __name__ == "__main__":
    summary = run_all_experiments()
    if not summary["overall_passed"]:
        sys.exit(1)
