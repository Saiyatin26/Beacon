"""Unit tests for the pieces that don't need Atlas/Claude: the DSL evaluator
and the equivalence scoring formula (architecture doc Section 7.3)."""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "backend"))

from common.dsl_eval import eval_condition
from common.models import Oracle
from certification.scorer import equivalence_score


def test_eval_condition_true():
    assert eval_condition("credit_score < 600 and debt_ratio > 0.4",
                           {"credit_score": 580, "debt_ratio": 0.5}) is True


def test_eval_condition_false():
    assert eval_condition("credit_score < 600 and debt_ratio > 0.4",
                           {"credit_score": 700, "debt_ratio": 0.5}) is False


def test_eval_condition_rejects_unknown_name():
    import pytest
    with pytest.raises(ValueError):
        eval_condition("os.system('rm -rf /')", {"credit_score": 1})


def test_equivalence_score_all_pass():
    oracle = Oracle(invariant_id="1", inputs=["x"], property="x", confidence=0.9, severity="critical")
    results = [{"invariant_id": "1", "pass_i": 1}]
    assert equivalence_score(results, {"1": oracle}) == 1.0


def test_equivalence_score_all_fail():
    oracle = Oracle(invariant_id="1", inputs=["x"], property="x", confidence=0.9, severity="critical")
    results = [{"invariant_id": "1", "pass_i": 0}]
    assert equivalence_score(results, {"1": oracle}) == 0.0


def test_equivalence_score_low_confidence_dampens_impact():
    """A failing low-confidence invariant should pull the score down less than
    a failing high-confidence one, given the same severity."""
    high_conf = Oracle(invariant_id="a", inputs=["x"], property="x", confidence=0.95, severity="high")
    low_conf = Oracle(invariant_id="b", inputs=["x"], property="x", confidence=0.30, severity="high")

    score_high_fails = equivalence_score(
        [{"invariant_id": "a", "pass_i": 0}, {"invariant_id": "c", "pass_i": 1}],
        {"a": high_conf, "c": Oracle(invariant_id="c", inputs=["x"], property="x",
                                      confidence=0.95, severity="high")},
    )
    score_low_fails = equivalence_score(
        [{"invariant_id": "b", "pass_i": 0}, {"invariant_id": "c", "pass_i": 1}],
        {"b": low_conf, "c": Oracle(invariant_id="c", inputs=["x"], property="x",
                                      confidence=0.95, severity="high")},
    )
    assert score_low_fails > score_high_fails
