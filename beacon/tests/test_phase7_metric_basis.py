"""BEACON V2 — Phase 7 Evidence Metric Basis & Final Hardening Tests.

Focused tests for:
- MEASURED / DERIVED / UNAVAILABLE metric_basis semantics
- Domain independence (3 unrelated domains)
- Persistence failure -> result_hash changes
- Conservative confidence on DERIVED aggregates
- metric_basis in OracleSet hash sensitivity
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from discovery.models import (
    CandidateValidationStatus,
    DiscoveredCandidate,
    DiscoveredRuleType,
)
from reconciliation.engine import RuleReconciliationEngine, rule_reconciliation_engine
from reconciliation.models import (
    EvidenceMetricBasis,
    OracleRule,
    OracleSet,
    OracleSetStatus,
    RuleProvenanceSource,
)
from reconciliation.normalizer import rule_normalizer
from reconciliation.persistence import (
    ReconciliationPersistenceError,
    reconciliation_persistence,
)
from rules.models import (
    BusinessRule,
    ExpectedBehavior,
    ExpectedBehaviorType,
    RuleOperator,
    RulePredicate,
    RuleStatus,
)


def test_candidate_with_input_ids_yields_measured_basis():
    cand = DiscoveredCandidate(
        candidate_id="c_measured",
        rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
        canonical_expression="output.ok == true",
        normalized_expression="output.ok == true",
        description="Has IDs",
        support_count=5,
        confidence=1.0,
        input_ids=["i1", "i2", "i3"],
        validation_status=CandidateValidationStatus.VALIDATED,
    )
    norm = rule_normalizer.normalize_discovered_candidate(cand)
    assert norm.metric_basis == EvidenceMetricBasis.MEASURED


def test_candidate_without_input_ids_yields_derived_basis():
    cand = DiscoveredCandidate(
        candidate_id="c_derived",
        rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
        canonical_expression="output.status == OK",
        normalized_expression="output.status == OK",
        description="No IDs, only counts",
        support_count=12,
        contradiction_count=1,
        confidence=0.92,
        input_ids=[],
        validation_status=CandidateValidationStatus.VALIDATED,
    )
    norm = rule_normalizer.normalize_discovered_candidate(cand)
    assert norm.metric_basis == EvidenceMetricBasis.DERIVED


def test_user_rule_yields_unavailable_basis():
    pred = RulePredicate(field="x", operator=RuleOperator.EQ, value=1)
    u_rule = BusinessRule(
        rule_id="r_user_basis",
        name="User Rule",
        condition=pred,
        expected_behavior=ExpectedBehavior(
            behavior_type=ExpectedBehaviorType.RETURN_VALUE,
            target_field="y",
            expected_value=True,
        ),
        status=RuleStatus.ACTIVE,
    )
    norm = rule_normalizer.normalize_user_rule(u_rule)
    assert norm.metric_basis == EvidenceMetricBasis.UNAVAILABLE


def test_zero_count_candidate_yields_unavailable_basis():
    cand = DiscoveredCandidate(
        candidate_id="c_zero",
        rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
        canonical_expression="output.empty == true",
        normalized_expression="output.empty == true",
        description="Empty evidence",
        support_count=0,
        contradiction_count=0,
        unknown_count=0,
        confidence=1.0,
        input_ids=[],
        validation_status=CandidateValidationStatus.VALIDATED,
    )
    norm = rule_normalizer.normalize_discovered_candidate(cand)
    assert norm.metric_basis == EvidenceMetricBasis.UNAVAILABLE


def test_measured_basis_preserved_after_merge_with_unique_ids():
    engine = RuleReconciliationEngine()
    cand_a = DiscoveredCandidate(
        candidate_id="cm_a",
        rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
        canonical_expression="output.active == true",
        normalized_expression="output.active == true",
        description="Run A",
        support_count=3,
        confidence=1.0,
        input_ids=["i1", "i2", "i3"],
        validation_status=CandidateValidationStatus.VALIDATED,
    )
    cand_b = DiscoveredCandidate(
        candidate_id="cm_b",
        rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
        canonical_expression="output.active == true",
        normalized_expression="output.active == true",
        description="Run B",
        support_count=3,
        confidence=1.0,
        input_ids=["i3", "i4", "i5"],
        validation_status=CandidateValidationStatus.VALIDATED,
    )
    res = engine.reconcile(application_id="app_mb", discovered_candidates=[cand_a, cand_b], persist=False)
    assert res.approved_count == 1
    rule = res.oracle_set.rules[0]
    assert rule.support_count == 5
    assert rule.metric_basis == EvidenceMetricBasis.MEASURED


def test_derived_basis_when_merging_candidates_without_input_ids():
    engine = RuleReconciliationEngine()
    cand_a = DiscoveredCandidate(
        candidate_id="cd_a",
        rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
        canonical_expression="output.flag == true",
        normalized_expression="output.flag == true",
        description="Aggregate only A",
        support_count=10,
        contradiction_count=1,
        confidence=0.91,
        input_ids=[],
        validation_status=CandidateValidationStatus.VALIDATED,
    )
    cand_b = DiscoveredCandidate(
        candidate_id="cd_b",
        rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
        canonical_expression="output.flag == true",
        normalized_expression="output.flag == true",
        description="Aggregate only B",
        support_count=15,
        contradiction_count=2,
        confidence=0.88,
        input_ids=[],
        validation_status=CandidateValidationStatus.VALIDATED,
    )
    res = engine.reconcile(application_id="app_cd", discovered_candidates=[cand_a, cand_b], persist=False)
    assert res.approved_count == 1
    rule = res.oracle_set.rules[0]
    assert rule.metric_basis == EvidenceMetricBasis.DERIVED
    assert rule.support_count == 15
    assert rule.contradiction_count == 2
    assert rule.confidence == pytest.approx(0.88, abs=1e-6)


def test_metric_basis_changes_oracle_set_hash():
    pred = {"type": "predicate", "field": "x", "operator": "==", "value": 1, "field_source": "auto"}
    exp = {
        "behavior_type": "RETURN_VALUE", "target_field": "y", "expected_value": True,
        "expected_status_code": None, "expected_error_code": None,
        "expected_state_mutation": None, "expected_workflow_event": None,
    }
    rule_measured = OracleRule(
        rule_id="r_hash_m",
        rule_type="BUSINESS_RULE",
        canonical_expression="IF x == 1 THEN y == true",
        conditions=pred,
        expected_behavior=exp,
        source=RuleProvenanceSource.DISCOVERED,
        metric_basis=EvidenceMetricBasis.MEASURED,
        confidence=0.95,
        support_count=10,
    )
    rule_derived = rule_measured.model_copy(update={
        "rule_id": "r_hash_d",
        "metric_basis": EvidenceMetricBasis.DERIVED,
    })
    oracle_a = OracleSet(
        oracle_set_id="os_hash_m",
        application_id="app_hash_basis",
        version=1,
        status=OracleSetStatus.READY,
        rules=[rule_measured],
    )
    oracle_b = OracleSet(
        oracle_set_id="os_hash_d",
        application_id="app_hash_basis",
        version=1,
        status=OracleSetStatus.READY,
        rules=[rule_derived],
    )
    assert oracle_a.compute_oracle_set_hash() != oracle_b.compute_oracle_set_hash()


def test_domain_independence_three_domains():
    engine = RuleReconciliationEngine()
    medical_rule = BusinessRule(
        rule_id="med_r1",
        name="BP threshold",
        condition=RulePredicate(field="blood_pressure", operator=RuleOperator.GTE, value=140),
        expected_behavior=ExpectedBehavior(
            behavior_type=ExpectedBehaviorType.RETURN_VALUE,
            target_field="alert",
            expected_value="HIGH",
        ),
        status=RuleStatus.ACTIVE,
    )
    financial_rule = BusinessRule(
        rule_id="fin_r1",
        name="Credit limit",
        condition=RulePredicate(field="credit_score", operator=RuleOperator.LT, value=600),
        expected_behavior=ExpectedBehavior(
            behavior_type=ExpectedBehaviorType.RETURN_VALUE,
            target_field="loan_approved",
            expected_value=False,
        ),
        status=RuleStatus.ACTIVE,
    )
    logistics_rule = BusinessRule(
        rule_id="log_r1",
        name="Weight limit",
        condition=RulePredicate(field="package_weight_kg", operator=RuleOperator.GT, value=30),
        expected_behavior=ExpectedBehavior(
            behavior_type=ExpectedBehaviorType.RETURN_VALUE,
            target_field="requires_forklift",
            expected_value=True,
        ),
        status=RuleStatus.ACTIVE,
    )
    res = engine.reconcile(
        application_id="app_multi_domain",
        user_rules=[medical_rule, financial_rule, logistics_rule],
        persist=False,
    )
    assert res.approved_count == 3
    assert res.conflict_count == 0
    assert res.oracle_set.status == OracleSetStatus.READY


def test_persistence_failure_changes_status_and_result_hash():
    engine = RuleReconciliationEngine()
    pred = RulePredicate(field="val", operator=RuleOperator.EQ, value=42)
    u_rule = BusinessRule(
        rule_id="r_persist_fail",
        name="Persist Fail Rule",
        condition=pred,
        expected_behavior=ExpectedBehavior(
            behavior_type=ExpectedBehaviorType.RETURN_VALUE,
            target_field="result",
            expected_value=True,
        ),
        status=RuleStatus.ACTIVE,
    )
    res_ok = engine.reconcile(application_id="app_pf_test", user_rules=[u_rule], persist=False)
    hash_ok = res_ok.result_hash
    assert res_ok.overall_status == "COMPLETE"
    with patch.object(
        type(reconciliation_persistence),
        "save_reconciliation_result",
        side_effect=ReconciliationPersistenceError("Simulated DB failure"),
    ):
        res_fail = engine.reconcile(application_id="app_pf_test", user_rules=[u_rule], persist=True)
    assert res_fail.overall_status == "PARTIAL"
    assert res_fail.persistence_status == "FAILED"
    assert res_fail.result_hash != hash_ok


def test_disjoint_evidence_ids_sum_correctly_as_measured():
    engine = RuleReconciliationEngine()
    cand_a = DiscoveredCandidate(
        candidate_id="disj_a",
        rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
        canonical_expression="output.result == pass",
        normalized_expression="output.result == pass",
        description="Set A (disjoint)",
        support_count=3,
        confidence=1.0,
        input_ids=["a1", "a2", "a3"],
        validation_status=CandidateValidationStatus.VALIDATED,
    )
    cand_b = DiscoveredCandidate(
        candidate_id="disj_b",
        rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
        canonical_expression="output.result == pass",
        normalized_expression="output.result == pass",
        description="Set B (disjoint)",
        support_count=4,
        confidence=1.0,
        input_ids=["b1", "b2", "b3", "b4"],
        validation_status=CandidateValidationStatus.VALIDATED,
    )
    res = engine.reconcile(application_id="app_disj", discovered_candidates=[cand_a, cand_b], persist=False)
    assert res.approved_count == 1
    rule = res.oracle_set.rules[0]
    assert rule.support_count == 7
    assert len(rule.input_ids) == 7
    assert rule.metric_basis == EvidenceMetricBasis.MEASURED


def test_unavailable_evidence_does_not_fabricate_confidence():
    """TEST 4: Unavailable evidence does not create fake confidence."""
    cand = DiscoveredCandidate(
        candidate_id="c_unavail_conf",
        rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
        canonical_expression="output.mode == standard",
        normalized_expression="output.mode == standard",
        description="No empirical evidence",
        support_count=0,
        contradiction_count=0,
        unknown_count=0,
        confidence=0.5,
        input_ids=[],
        validation_status=CandidateValidationStatus.VALIDATED,
    )
    norm = rule_normalizer.normalize_discovered_candidate(cand)
    assert norm.metric_basis == EvidenceMetricBasis.UNAVAILABLE


def test_duplicate_unresolved_conflict_references_count_once():
    """TEST 5: Duplicate unresolved conflict references count once."""
    engine = RuleReconciliationEngine()
    pred = RulePredicate(field="status_code", operator=RuleOperator.EQ, value=200)
    u1 = BusinessRule(
        rule_id="u_dup_conf1",
        name="U1",
        condition=pred,
        expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.RETURN_VALUE, target_field="ok", expected_value=True),
        status=RuleStatus.ACTIVE,
    )
    u2 = BusinessRule(
        rule_id="u_dup_conf2",
        name="U2",
        condition=pred,
        expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.RETURN_VALUE, target_field="ok", expected_value=False),
        status=RuleStatus.ACTIVE,
    )
    res = engine.reconcile(application_id="app_dup_conf", user_rules=[u1, u2], persist=False)
    assert res.oracle_set.provenance["total_conflicts"] == 1
    assert res.oracle_set.provenance["unresolved_conflicts"] == 1
    assert res.unresolved_conflict_count == 1


def test_unresolved_material_conflict_always_produces_blocked():
    """TEST 8: Unresolved material conflict always produces OracleSetStatus.BLOCKED."""
    from reconciliation.models import ReconciliationPolicy
    engine = RuleReconciliationEngine()
    pred = RulePredicate(field="rate_tier", operator=RuleOperator.EQ, value="PREMIUM")
    u1 = BusinessRule(
        rule_id="u_blk1",
        name="U1 Premium",
        condition=pred,
        expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.RETURN_VALUE, target_field="discount", expected_value=0.20),
        status=RuleStatus.ACTIVE,
    )
    u2 = BusinessRule(
        rule_id="u_blk2",
        name="U2 Premium",
        condition=pred,
        expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.RETURN_VALUE, target_field="discount", expected_value=0.30),
        status=RuleStatus.ACTIVE,
    )
    # Even if deprecated flag allow_unresolved_conflicts_in_ready is True, status MUST be BLOCKED
    policy = ReconciliationPolicy(allow_unresolved_conflicts_in_ready=True)
    res = engine.reconcile(application_id="app_blocked_test", user_rules=[u1, u2], policy=policy, persist=False)
    assert res.oracle_set.status == OracleSetStatus.BLOCKED
    assert res.approved_count == 0
    assert len(res.oracle_set.rules) == 0
    assert len(res.conflicts) == 1

