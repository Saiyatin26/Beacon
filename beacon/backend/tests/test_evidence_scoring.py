import pytest

from certification.scorer import evidence_adjusted_score


def _integrity_bound_evaluation(*, error_inputs: int = 0):
    """Build a real, hash-verified evaluation result for evidence-gate tests."""
    from evaluation.models import EvaluationResult, EvaluationSummary, compute_evaluation_result_hash

    result = EvaluationResult(
        application_id="inventive-step-gate-test",
        evaluation_id=f"eval-gate-{error_inputs}",
        summary=EvaluationSummary(
            total_inputs=10,
            evaluated_inputs=10,
            equivalent_inputs=10 - error_inputs,
            different_inputs=0,
            error_inputs=error_inputs,
            behavioral_score=1.0,
            observed_deviation=0.0,
            coverage=1.0,
        ),
        input_results=[],
        differences=[],
    )
    return result.model_copy(update={"evaluation_hash": compute_evaluation_result_hash(result)})


def test_evidence_adjusted_score_uses_available_factor_weights():
    factors = {
        "oracle_coverage": 1.0,
        "input_coverage": 0.5,
        "execution_reliability": 1.0,
        "oracle_confidence": 1.0,
        "input_set_integrity": 1.0,
        "source_hash_integrity": 1.0,
    }

    adjusted, quality, used_factors = evidence_adjusted_score(0.8, factors)

    assert quality == 0.9
    assert adjusted == 0.72
    assert used_factors == factors


def test_evidence_adjusted_score_renormalizes_only_available_factors():
    adjusted, quality, used_factors = evidence_adjusted_score(
        0.75,
        {"oracle_coverage": 0.5, "source_hash_integrity": None},
    )

    assert adjusted == 0.375
    assert quality == 0.5
    assert used_factors == {"oracle_coverage": 0.5}


@pytest.mark.parametrize("score", [-0.1, 1.1, float("nan"), float("inf")])
def test_evidence_adjusted_score_rejects_invalid_behavioral_scores(score):
    with pytest.raises(ValueError, match="behavioral_score"):
        evidence_adjusted_score(score, {"oracle_coverage": 1.0})


def test_evidence_adjusted_score_rejects_out_of_range_factors():
    with pytest.raises(ValueError, match="oracle_coverage"):
        evidence_adjusted_score(1.0, {"oracle_coverage": 1.1})


def test_reliability_gate_blocks_even_when_adjusted_score_would_pass():
    from certification.certification_engine import CertificationEngine
    from certification.models import CertificationContext, CertificationPolicy, CertificationStatus
    from threshold.models import DifferenceMetric, ThresholdResolution, ThresholdStrategy, ThresholdStatus

    artifact = CertificationEngine().certify(
        application_id="inventive-step-gate-test",
        evaluation_result=_integrity_bound_evaluation(error_inputs=2),
        context=CertificationContext(
            legacy_implementation_hash="legacy-source-hash",
            modernized_implementation_hash="modern-source-hash",
        ),
        policy=CertificationPolicy(min_equivalence_score=0.80, min_oracle_coverage=0.80),
        threshold_resolution=ThresholdResolution(
            resolution_id="reliability-gate", metric=DifferenceMetric.ABSOLUTE_DIFF,
            strategy=ThresholdStrategy.FIXED, status=ThresholdStatus.RESOLVED,
            final_value=0.05, policy_id="policy", policy_version="1",
        ),
    )

    assert artifact.status == CertificationStatus.NOT_CERTIFIED
    assert artifact.certified is False
    assert artifact.metrics.evidence_gate_results["execution_reliability"] is False
    assert any("Execution reliability" in reason for reason in artifact.blocking_reasons)


def test_full_beacon_requires_recorded_provider_provenance():
    from certification.certification_engine import CertificationEngine
    from certification.models import CertificationContext, CertificationPolicy, CertificationStatus
    from threshold.models import DifferenceMetric, ThresholdResolution, ThresholdStrategy, ThresholdStatus

    artifact = CertificationEngine().certify(
        application_id="inventive-step-full-mode-test",
        evaluation_result=_integrity_bound_evaluation(),
        context=CertificationContext(
            evaluation_mode="FULL_BEACON",
            legacy_implementation_hash="legacy-source-hash",
            modernized_implementation_hash="modern-source-hash",
            provider="",
        ),
        policy=CertificationPolicy(min_equivalence_score=0.80, min_oracle_coverage=0.80),
        threshold_resolution=ThresholdResolution(
            resolution_id="provider-gate", metric=DifferenceMetric.ABSOLUTE_DIFF,
            strategy=ThresholdStrategy.FIXED, status=ThresholdStatus.RESOLVED,
            final_value=0.05, policy_id="policy", policy_version="1",
        ),
    )

    assert artifact.status == CertificationStatus.NOT_CERTIFIED
    assert artifact.metrics.evidence_gate_results["full_beacon_provider_provenance"] is False
    assert any("provider provenance" in reason.lower() for reason in artifact.blocking_reasons)


def test_experiment_1_raw_vs_adjusted():
    from scripts.run_inventive_step_experiments import run_experiment_1_raw_vs_adjusted
    res = run_experiment_1_raw_vs_adjusted()
    assert res["passed"] is True


def test_experiment_2_one_factor_sensitivity():
    from scripts.run_inventive_step_experiments import run_experiment_2_one_factor_sensitivity
    res = run_experiment_2_one_factor_sensitivity()
    assert res["passed"] is True


def test_experiment_3_missing_evidence_and_renormalization():
    from scripts.run_inventive_step_experiments import run_experiment_3_missing_evidence
    res = run_experiment_3_missing_evidence()
    assert res["passed"] is True


def test_experiment_4_zero_inputs_fail_closed():
    from scripts.run_inventive_step_experiments import run_experiment_4_zero_inputs
    res = run_experiment_4_zero_inputs()
    assert res["passed"] is True
    assert res["scorer_returned"] == 0.0
    assert res["cert_certified"] is False


def test_experiment_5_genuine_mismatch_detection():
    from scripts.run_inventive_step_experiments import run_experiment_5_genuine_mismatch
    res = run_experiment_5_genuine_mismatch()
    assert res["passed"] is True
    assert res["certified"] is False
    assert res["regressions_detected"] > 0


def test_experiment_6_unreliable_execution_degradation():
    from scripts.run_inventive_step_experiments import run_experiment_6_unreliable_execution
    res = run_experiment_6_unreliable_execution()
    assert res["passed"] is True
    assert res["execution_reliability_factor"] == 0.50
    assert res["certified"] is False


def test_experiment_7_certificate_tamper_detection():
    from scripts.run_inventive_step_experiments import run_experiment_7_integrity_tampering
    res = run_experiment_7_integrity_tampering()
    assert res["passed"] is True
    assert res["initial_verification"] is True
    assert res["score_tamper_detected"] is True
    assert res["version_tamper_detected"] is True
    assert res["status_tamper_detected"] is True


def test_experiment_8_deterministic_reproducibility():
    from scripts.run_inventive_step_experiments import run_experiment_8_reproducibility
    res = run_experiment_8_reproducibility()
    assert res["passed"] is True
    assert res["bitwise_identical"] is True
