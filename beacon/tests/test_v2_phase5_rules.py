"""BEACON V2 — Phase 5 Business Rule Unit Tests.

Tests domain-agnostic BusinessRule models, condition ASTs, validation, canonical normalization,
deterministic fingerprinting, strict three-valued condition evaluation (TRUE, FALSE, UNKNOWN),
and versioned registry persistence with error propagation.
"""

from pathlib import Path
import sys
from unittest.mock import patch
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from rules.evaluator import TriState, rule_condition_evaluator
from rules.models import (
    BusinessRule,
    CompoundRuleCondition,
    ExpectedBehavior,
    ExpectedBehaviorType,
    RuleComplianceVerdict,
    RuleOperator,
    RulePredicate,
    RuleSeverity,
    RuleSource,
    RuleStatus,
    UnaryRuleCondition,
)
from rules.normalizer import rule_normalizer
from rules.registry import RulePersistenceError, RuleRegistry
from rules.validator import rule_validator


class TestPhase5RuleModelsAndValidation:
    """Tests static validation and schema integrity of BusinessRule models."""

    def test_valid_predicate_rule_passes_validation(self):
        rule = BusinessRule(
            rule_id="R-001",
            name="Minimum Age Requirement",
            description="Applicant must be 18 or older",
            condition=RulePredicate(
                field="age",
                operator=RuleOperator.GTE,
                value=18,
            ),
            expected_behavior=ExpectedBehavior(
                behavior_type=ExpectedBehaviorType.ACCEPT,
            ),
        )
        is_valid, errors = rule_validator.validate_rule(rule)
        assert is_valid is True
        assert len(errors) == 0

    def test_missing_rule_id_and_name_fails_validation(self):
        rule = BusinessRule.model_construct(
            rule_id="",
            name="",
            condition=RulePredicate(field="amount", operator=RuleOperator.GT, value=0),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        is_valid, errors = rule_validator.validate_rule(rule)
        assert is_valid is False
        assert any("rule_id" in err for err in errors)
        assert any("name" in err for err in errors)

    def test_empty_compound_condition_fails_validation(self):
        rule = BusinessRule(
            rule_id="R-002",
            name="Compound Rule",
            condition=CompoundRuleCondition(
                logical_op="AND",
                operands=[],
            ),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        is_valid, errors = rule_validator.validate_rule(rule)
        assert is_valid is False
        assert any("at least one operand" in err for err in errors)

    def test_invalid_operator_for_collection_fails_validation(self):
        # IN operator with non-collection value
        rule = BusinessRule(
            rule_id="R-003",
            name="Collection Rule",
            condition=RulePredicate(
                field="tier",
                operator=RuleOperator.IN,
                value="NOT_A_LIST",
            ),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        is_valid, errors = rule_validator.validate_rule(rule)
        assert is_valid is False
        assert any("collection" in err for err in errors)

    def test_behavior_specific_validation_return_value(self):
        # RETURN_VALUE requires target_field and expected_value
        invalid_rule = BusinessRule(
            rule_id="R-004",
            name="Return Value Rule",
            condition=RulePredicate(field="status", operator=RuleOperator.EQ, value="OK"),
            expected_behavior=ExpectedBehavior(
                behavior_type=ExpectedBehaviorType.RETURN_VALUE,
                target_field="",
                expected_value=None,
            ),
        )
        is_valid, errors = rule_validator.validate_rule(invalid_rule)
        assert is_valid is False
        assert any("target_field" in err for err in errors)

        valid_rule = BusinessRule(
            rule_id="R-004-OK",
            name="Return Value Rule Valid",
            condition=RulePredicate(field="status", operator=RuleOperator.EQ, value="OK"),
            expected_behavior=ExpectedBehavior(
                behavior_type=ExpectedBehaviorType.RETURN_VALUE,
                target_field="order_status",
                expected_value="PROCESSED",
            ),
        )
        is_val, errs = rule_validator.validate_rule(valid_rule)
        assert is_val is True
        assert len(errs) == 0

    def test_behavior_specific_validation_return_status(self):
        invalid_rule = BusinessRule(
            rule_id="R-005",
            name="Status Rule",
            condition=RulePredicate(field="age", operator=RuleOperator.LT, value=18),
            expected_behavior=ExpectedBehavior(
                behavior_type=ExpectedBehaviorType.RETURN_STATUS,
                expected_status_code=None,
            ),
        )
        is_valid, errors = rule_validator.validate_rule(invalid_rule)
        assert is_valid is False
        assert any("expected_status_code" in err for err in errors)

    def test_behavior_specific_validation_workflow_step(self):
        invalid_rule = BusinessRule(
            rule_id="R-006",
            name="Workflow Rule",
            condition=RulePredicate(field="stage", operator=RuleOperator.EQ, value="CHECKOUT"),
            expected_behavior=ExpectedBehavior(
                behavior_type=ExpectedBehaviorType.WORKFLOW_STEP,
                expected_workflow_event="",
            ),
        )
        is_valid, errors = rule_validator.validate_rule(invalid_rule)
        assert is_valid is False
        assert any("expected_workflow_event" in err for err in errors)


class TestPhase5ThreeValuedConditionSemantics:
    """Tests strict 3-valued logic (TRUE, FALSE, UNKNOWN) across single predicates and compound trees."""

    def test_predicate_field_present_true_and_false(self):
        pred = RulePredicate(field="age", operator=RuleOperator.GTE, value=18)

        # age = 25 -> TRUE
        tri, expl, obs = rule_condition_evaluator.evaluate_condition(pred, {"age": 25})
        assert tri == TriState.TRUE
        assert obs["age"] == 25

        # age = 15 -> FALSE
        tri, expl, obs = rule_condition_evaluator.evaluate_condition(pred, {"age": 15})
        assert tri == TriState.FALSE
        assert obs["age"] == 15

    def test_predicate_field_missing_yields_unknown(self):
        pred = RulePredicate(field="age", operator=RuleOperator.GTE, value=18)
        tri, expl, obs = rule_condition_evaluator.evaluate_condition(pred, {})
        assert tri == TriState.UNKNOWN
        assert "missing" in expl

    def test_predicate_missing_vs_null_vs_zero_vs_false_vs_empty(self):
        # 1. IS_NULL operator
        null_pred = RulePredicate(field="data", operator=RuleOperator.IS_NULL)
        # Missing data -> FALSE (missing is not null)
        tri, _, _ = rule_condition_evaluator.evaluate_condition(null_pred, {})
        assert tri == TriState.UNKNOWN  # Missing field evaluated against IS_NULL yields UNKNOWN
        # data = None -> TRUE
        tri, _, _ = rule_condition_evaluator.evaluate_condition(null_pred, {"data": None})
        assert tri == TriState.TRUE
        # data = 0 -> FALSE (0 is not null)
        tri, _, _ = rule_condition_evaluator.evaluate_condition(null_pred, {"data": 0})
        assert tri == TriState.FALSE

        # 2. EXISTS operator
        exists_pred = RulePredicate(field="data", operator=RuleOperator.EXISTS)
        # Missing -> FALSE
        tri, _, _ = rule_condition_evaluator.evaluate_condition(exists_pred, {})
        assert tri == TriState.FALSE
        # Present with None -> TRUE
        tri, _, _ = rule_condition_evaluator.evaluate_condition(exists_pred, {"data": None})
        assert tri == TriState.TRUE
        # Present with 0 -> TRUE
        tri, _, _ = rule_condition_evaluator.evaluate_condition(exists_pred, {"data": 0})
        assert tri == TriState.TRUE
        # Present with False -> TRUE
        tri, _, _ = rule_condition_evaluator.evaluate_condition(exists_pred, {"data": False})
        assert tri == TriState.TRUE

        # 3. ZERO value with EQ operator
        zero_pred = RulePredicate(field="amount", operator=RuleOperator.EQ, value=0)
        tri, _, _ = rule_condition_evaluator.evaluate_condition(zero_pred, {"amount": 0})
        assert tri == TriState.TRUE
        # Missing amount -> UNKNOWN
        tri, _, _ = rule_condition_evaluator.evaluate_condition(zero_pred, {})
        assert tri == TriState.UNKNOWN

        # 4. FALSE value with EQ operator
        false_pred = RulePredicate(field="enabled", operator=RuleOperator.EQ, value=False)
        tri, _, _ = rule_condition_evaluator.evaluate_condition(false_pred, {"enabled": False})
        assert tri == TriState.TRUE
        # Missing enabled -> UNKNOWN
        tri, _, _ = rule_condition_evaluator.evaluate_condition(false_pred, {})
        assert tri == TriState.UNKNOWN

    def test_three_valued_and_truth_table(self):
        pred_age = RulePredicate(field="age", operator=RuleOperator.GTE, value=18)
        pred_active = RulePredicate(field="status", operator=RuleOperator.EQ, value="ACTIVE")
        and_node = CompoundRuleCondition(logical_op="AND", operands=[pred_age, pred_active])

        # TRUE AND TRUE -> TRUE
        tri, _, _ = rule_condition_evaluator.evaluate_condition(and_node, {"age": 20, "status": "ACTIVE"})
        assert tri == TriState.TRUE

        # TRUE AND FALSE -> FALSE
        tri, _, _ = rule_condition_evaluator.evaluate_condition(and_node, {"age": 20, "status": "INACTIVE"})
        assert tri == TriState.FALSE

        # TRUE AND UNKNOWN -> UNKNOWN
        tri, _, _ = rule_condition_evaluator.evaluate_condition(and_node, {"age": 20})
        assert tri == TriState.UNKNOWN

        # FALSE AND UNKNOWN -> FALSE (False dominates)
        tri, _, _ = rule_condition_evaluator.evaluate_condition(and_node, {"age": 15})  # age=15 (FALSE), status missing (UNKNOWN)
        assert tri == TriState.FALSE

        # UNKNOWN AND UNKNOWN -> UNKNOWN
        tri, _, _ = rule_condition_evaluator.evaluate_condition(and_node, {})
        assert tri == TriState.UNKNOWN

    def test_three_valued_or_truth_table(self):
        pred_vip = RulePredicate(field="tier", operator=RuleOperator.EQ, value="VIP")
        pred_promo = RulePredicate(field="has_promo", operator=RuleOperator.EQ, value=True)
        or_node = CompoundRuleCondition(logical_op="OR", operands=[pred_vip, pred_promo])

        # FALSE OR FALSE -> FALSE
        tri, _, _ = rule_condition_evaluator.evaluate_condition(or_node, {"tier": "STANDARD", "has_promo": False})
        assert tri == TriState.FALSE

        # TRUE OR FALSE -> TRUE
        tri, _, _ = rule_condition_evaluator.evaluate_condition(or_node, {"tier": "VIP", "has_promo": False})
        assert tri == TriState.TRUE

        # TRUE OR UNKNOWN -> TRUE (True dominates)
        tri, _, _ = rule_condition_evaluator.evaluate_condition(or_node, {"tier": "VIP"})  # has_promo missing
        assert tri == TriState.TRUE

        # FALSE OR UNKNOWN -> UNKNOWN
        tri, _, _ = rule_condition_evaluator.evaluate_condition(or_node, {"tier": "STANDARD"})  # has_promo missing
        assert tri == TriState.UNKNOWN

        # UNKNOWN OR UNKNOWN -> UNKNOWN
        tri, _, _ = rule_condition_evaluator.evaluate_condition(or_node, {})
        assert tri == TriState.UNKNOWN

    def test_three_valued_not_truth_table(self):
        pred_blocked = RulePredicate(field="is_blocked", operator=RuleOperator.EQ, value=True)
        not_node = UnaryRuleCondition(logical_op="NOT", operand=pred_blocked)

        # NOT TRUE -> FALSE
        tri, _, _ = rule_condition_evaluator.evaluate_condition(not_node, {"is_blocked": True})
        assert tri == TriState.FALSE

        # NOT FALSE -> TRUE
        tri, _, _ = rule_condition_evaluator.evaluate_condition(not_node, {"is_blocked": False})
        assert tri == TriState.TRUE

        # NOT UNKNOWN -> UNKNOWN
        tri, _, _ = rule_condition_evaluator.evaluate_condition(not_node, {})
        assert tri == TriState.UNKNOWN


class TestPhase5RuleNormalizerAndFingerprinting:
    """Tests deterministic canonicalization and SHA-256 fingerprinting."""

    def test_deterministic_fingerprint_generation(self):
        rule1 = BusinessRule(
            rule_id="R-100",
            name="Approval Limit",
            description="Transactions exceeding 5000 require approval",
            condition=RulePredicate(field="amount", operator=RuleOperator.GT, value=5000),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.REJECT),
            version=1,
        )
        rule2 = BusinessRule(
            rule_id="R-100",
            name="Approval Limit",
            description="Transactions exceeding 5000 require approval",
            condition=RulePredicate(field="amount", operator=RuleOperator.GT, value=5000),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.REJECT),
            version=1,
        )

        fp1 = rule_normalizer.compute_rule_fingerprint(rule1)
        fp2 = rule_normalizer.compute_rule_fingerprint(rule2)
        assert fp1 == fp2
        assert len(fp1) == 64

    def test_fingerprint_changes_with_condition_change(self):
        rule1 = BusinessRule(
            rule_id="R-101",
            name="Boundary Rule",
            condition=RulePredicate(field="limit", operator=RuleOperator.LTE, value=100),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        rule2 = BusinessRule(
            rule_id="R-101",
            name="Boundary Rule",
            condition=RulePredicate(field="limit", operator=RuleOperator.LT, value=100),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        fp1 = rule_normalizer.compute_rule_fingerprint(rule1)
        fp2 = rule_normalizer.compute_rule_fingerprint(rule2)
        assert fp1 != fp2


class TestPhase5RuleRegistryAndPersistence:
    """Tests SQLite persistence, versioning, and explicit error propagation."""

    @pytest.fixture
    def test_registry(self, tmp_path):
        db_file = str(tmp_path / "test_beacon_rules.sqlite3")
        return RuleRegistry(db_path=db_file)

    def test_register_and_retrieve_rule(self, test_registry):
        rule = BusinessRule(
            rule_id="R-REG-01",
            name="Registration Rule",
            condition=RulePredicate(field="tier", operator=RuleOperator.EQ, value="GOLD"),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        saved = test_registry.register_rule(rule)
        assert saved.fingerprint != ""

        fetched = test_registry.get_rule("R-REG-01")
        assert fetched is not None
        assert fetched.rule_id == "R-REG-01"
        assert fetched.version == 1

    def test_update_rule_creates_new_version(self, test_registry):
        rule_v1 = BusinessRule(
            rule_id="R-VER-01",
            name="Versioning Test",
            condition=RulePredicate(field="score", operator=RuleOperator.GTE, value=700),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        test_registry.register_rule(rule_v1)

        rule_v2 = test_registry.update_rule(
            rule_id="R-VER-01",
            condition=RulePredicate(field="score", operator=RuleOperator.GTE, value=750),
        )
        assert rule_v2.version == 2

        # Verify both versions exist in history
        v1 = test_registry.get_rule("R-VER-01", version=1)
        v2 = test_registry.get_rule("R-VER-01", version=2)
        latest = test_registry.get_rule("R-VER-01")

        assert v1.version == 1
        assert v2.version == 2
        assert latest.version == 2
        assert v1.fingerprint != v2.fingerprint

    def test_persistence_failure_raises_explicit_error(self, test_registry):
        rule = BusinessRule(
            rule_id="R-FAIL-01",
            name="Fail Rule",
            condition=RulePredicate(field="score", operator=RuleOperator.GTE, value=700),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        with patch.object(test_registry, "_persist_rule_to_db", side_effect=Exception("Disk full / connection failed")):
            with pytest.raises(Exception):
                test_registry.register_rule(rule)


class TestPhase5FieldSourceIsolation:
    """Tests strict source isolation (input, output, state, error, metadata, auto)."""

    def test_field_source_input_only_ignores_output(self):
        """When field_source='input', evaluator searches ONLY input partition (ignoring output)."""
        eval_ctx = {
            "input": {},
            "output": {"age": 25},
            "state": {},
            "error": {},
            "metadata": {},
        }
        pred = RulePredicate(field="age", field_source="input", operator=RuleOperator.GTE, value=18)
        tri, expl, obs = rule_condition_evaluator.evaluate_condition(pred, eval_ctx)

        assert tri == TriState.UNKNOWN
        assert "missing" in expl

    def test_field_source_output_positive(self):
        """When field_source='output', evaluator matches output partition correctly."""
        eval_ctx = {
            "input": {},
            "output": {"result": "APPROVED"},
            "state": {},
            "error": {},
            "metadata": {},
        }
        pred = RulePredicate(field="result", field_source="output", operator=RuleOperator.EQ, value="APPROVED")
        tri, expl, obs = rule_condition_evaluator.evaluate_condition(pred, eval_ctx)

        assert tri == TriState.TRUE
        assert obs["result"] == "APPROVED"

    def test_field_source_state_error_metadata_isolation(self):
        """Evaluator strictly isolates state, error, and metadata sources."""
        eval_ctx = {
            "input": {"id": "1"},
            "output": {"status": "OK"},
            "state": {"row_count": 10},
            "error": {"code": "ERR_01"},
            "metadata": {"env": "production"},
        }
        pred_state = RulePredicate(field="row_count", field_source="state", operator=RuleOperator.GT, value=0)
        tri_s, _, _ = rule_condition_evaluator.evaluate_condition(pred_state, eval_ctx)
        assert tri_s == TriState.TRUE

        # Searching for state field in input yields UNKNOWN
        pred_state_in_input = RulePredicate(field="row_count", field_source="input", operator=RuleOperator.GT, value=0)
        tri_si, _, _ = rule_condition_evaluator.evaluate_condition(pred_state_in_input, eval_ctx)
        assert tri_si == TriState.UNKNOWN

        pred_err = RulePredicate(field="code", field_source="error", operator=RuleOperator.EQ, value="ERR_01")
        tri_e, _, _ = rule_condition_evaluator.evaluate_condition(pred_err, eval_ctx)
        assert tri_e == TriState.TRUE

        pred_meta = RulePredicate(field="env", field_source="metadata", operator=RuleOperator.EQ, value="production")
        tri_m, _, _ = rule_condition_evaluator.evaluate_condition(pred_meta, eval_ctx)
        assert tri_m == TriState.TRUE

    def test_field_source_auto_precedence_order(self):
        """Auto source searches in deterministic order: input -> output -> state -> error -> metadata."""
        eval_ctx = {
            "input": {"flag": "INPUT_VAL"},
            "output": {"flag": "OUTPUT_VAL", "out_only": "OUT_OK"},
            "state": {},
            "error": {},
            "metadata": {},
        }
        # flag exists in both input and output -> auto resolves to input value
        pred_flag = RulePredicate(field="flag", field_source="auto", operator=RuleOperator.EQ, value="INPUT_VAL")
        tri_f, _, obs = rule_condition_evaluator.evaluate_condition(pred_flag, eval_ctx)
        assert tri_f == TriState.TRUE
        assert obs["flag"] == "INPUT_VAL"

        # out_only exists only in output -> auto resolves to output value
        pred_out = RulePredicate(field="out_only", field_source="auto", operator=RuleOperator.EQ, value="OUT_OK")
        tri_o, _, obs_o = rule_condition_evaluator.evaluate_condition(pred_out, eval_ctx)
        assert tri_o == TriState.TRUE
        assert obs_o["out_only"] == "OUT_OK"

