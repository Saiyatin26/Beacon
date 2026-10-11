import pytest

from certification.scorer import evidence_adjusted_score


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
