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
