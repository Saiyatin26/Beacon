"""BEACON V2 — Phase 5 Business Rule Unit Tests.

Tests domain-agnostic BusinessRule models, condition ASTs, validation, canonical normalization,
deterministic fingerprinting, condition evaluation, and versioned registry persistence.
"""

import pytest

from rules.evaluator import rule_condition_evaluator
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
from rules.registry import RuleRegistry
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


class TestPhase5RuleNormalizerAndFingerprinting:
    """Tests deterministic canonicalization and SHA-256 fingerprinting."""

    def test_deterministic_fingerprint_generation(self):
        rule1 = BusinessRule(
            rule_id="R-100",
            name="Approval Limit",
            description="Transactions exceeding 5000 require approval",
            condition=RulePredicate(field="amount", operator=RuleOperator.GT, value=5000),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
            severity=RuleSeverity.HIGH,
        )
        # Identical rule created with different object identity
        rule2 = BusinessRule(
            rule_id="R-100",
            name="Approval Limit",
            description="Transactions exceeding 5000 require approval",
            condition=RulePredicate(field="amount", operator=RuleOperator.GT, value=5000),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
            severity=RuleSeverity.HIGH,
        )
        fp1 = rule_normalizer.compute_rule_fingerprint(rule1)
        fp2 = rule_normalizer.compute_rule_fingerprint(rule2)
        assert len(fp1) == 64
        assert fp1 == fp2

    def test_compound_condition_operand_order_invariance(self):
        """AND (A, B) and AND (B, A) must produce the exact same fingerprint."""
        cond_a = RulePredicate(field="age", operator=RuleOperator.GTE, value=18)
        cond_b = RulePredicate(field="status", operator=RuleOperator.EQ, value="ACTIVE")

        rule1 = BusinessRule(
            rule_id="R-101",
            name="Eligibility",
            condition=CompoundRuleCondition(logical_op="AND", operands=[cond_a, cond_b]),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        rule2 = BusinessRule(
            rule_id="R-101",
            name="Eligibility",
            condition=CompoundRuleCondition(logical_op="AND", operands=[cond_b, cond_a]),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        fp1 = rule_normalizer.compute_rule_fingerprint(rule1)
        fp2 = rule_normalizer.compute_rule_fingerprint(rule2)
        assert fp1 == fp2


class TestPhase5ConditionEvaluator:
    """Tests safe AST condition evaluation across various data types and edge cases."""

    def test_relational_operators(self):
        evaluator = rule_condition_evaluator
        ctx = {"amount": 1000}

        # Exact boundary: amount > 1000 -> False
        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="amount", operator=RuleOperator.GT, value=1000), ctx)
        assert sat is False

        # amount >= 1000 -> True
        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="amount", operator=RuleOperator.GTE, value=1000), ctx)
        assert sat is True

        # amount < 1000 -> False
        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="amount", operator=RuleOperator.LT, value=1000), ctx)
        assert sat is False

        # amount <= 1000 -> True
        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="amount", operator=RuleOperator.LTE, value=1000), ctx)
        assert sat is True

    def test_collection_operators(self):
        evaluator = rule_condition_evaluator
        ctx = {"role": "admin", "tags": ["fast", "secure"]}

        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="role", operator=RuleOperator.IN, value=["admin", "root"]), ctx)
        assert sat is True

        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="role", operator=RuleOperator.NOT_IN, value=["guest", "anonymous"]), ctx)
        assert sat is True

        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="tags", operator=RuleOperator.CONTAINS, value="secure"), ctx)
        assert sat is True

        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="tags", operator=RuleOperator.NOT_CONTAINS, value="deprecated"), ctx)
        assert sat is True

    def test_missing_vs_null_vs_falsy_distinctions(self):
        evaluator = rule_condition_evaluator
        ctx = {
            "null_field": None,
            "zero_field": 0,
            "empty_str": "",
            "false_field": False,
            "empty_list": [],
        }

        # 1. Missing field check
        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="absent_field", operator=RuleOperator.EXISTS), ctx)
        assert sat is False
        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="absent_field", operator=RuleOperator.NOT_EXISTS), ctx)
        assert sat is True

        # 2. Null field check
        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="null_field", operator=RuleOperator.EXISTS), ctx)
        assert sat is True
        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="null_field", operator=RuleOperator.IS_NULL), ctx)
        assert sat is True
        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="null_field", operator=RuleOperator.IS_NOT_NULL), ctx)
        assert sat is False

        # 3. Falsy distinctions: False != 0
        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="false_field", operator=RuleOperator.EQ, value=False), ctx)
        assert sat is True
        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="false_field", operator=RuleOperator.EQ, value=0), ctx)
        assert sat is False

        # 4. Zero vs Empty string
        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="zero_field", operator=RuleOperator.EQ, value=0), ctx)
        assert sat is True
        sat, _, _ = evaluator.evaluate_condition(RulePredicate(field="zero_field", operator=RuleOperator.EQ, value=""), ctx)
        assert sat is False

    def test_compound_and_unary_conditions(self):
        evaluator = rule_condition_evaluator
        ctx = {"age": 25, "active": True, "country": "US"}

        # AND condition
        cond_and = CompoundRuleCondition(
            logical_op="AND",
            operands=[
                RulePredicate(field="age", operator=RuleOperator.GTE, value=18),
                RulePredicate(field="active", operator=RuleOperator.EQ, value=True),
            ],
        )
        sat, _, _ = evaluator.evaluate_condition(cond_and, ctx)
        assert sat is True

        # NOT condition
        cond_not = UnaryRuleCondition(
            logical_op="NOT",
            operand=RulePredicate(field="country", operator=RuleOperator.EQ, value="CA"),
        )
        sat, _, _ = evaluator.evaluate_condition(cond_not, ctx)
        assert sat is True

    def test_nested_field_and_array_extraction(self):
        evaluator = rule_condition_evaluator
        ctx = {
            "customer": {
                "profile": {
                    "tier": "GOLD",
                    "scores": [10, 20, 30],
                }
            }
        }
        sat, _, obs = evaluator.evaluate_condition(
            RulePredicate(field="customer.profile.tier", operator=RuleOperator.EQ, value="GOLD"), ctx
        )
        assert sat is True
        assert obs["customer.profile.tier"] == "GOLD"

        sat_arr, _, obs_arr = evaluator.evaluate_condition(
            RulePredicate(field="customer.profile.scores[1]", operator=RuleOperator.EQ, value=20), ctx
        )
        assert sat_arr is True
        assert obs_arr["customer.profile.scores[1]"] == 20

    def test_incompatible_type_comparison_fails_closed(self):
        evaluator = rule_condition_evaluator
        ctx = {"age": "eighteen"}  # string instead of int
        sat, expl, _ = evaluator.evaluate_condition(
            RulePredicate(field="age", operator=RuleOperator.GTE, value=18), ctx
        )
        assert sat is False
        assert "Incompatible types" in expl


class TestPhase5RuleRegistry:
    """Tests versioning and lifecycle operations in RuleRegistry."""

    @pytest.fixture
    def registry(self, tmp_path):
        db_file = str(tmp_path / "test_rules.sqlite3")
        reg = RuleRegistry(db_path=db_file)
        reg.clear()
        return reg

    def test_register_and_retrieve_rule(self, registry):
        rule = BusinessRule(
            rule_id="R-200",
            name="Initial Rule",
            condition=RulePredicate(field="x", operator=RuleOperator.EQ, value=1),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        registry.register_rule(rule)

        retrieved = registry.get_rule("R-200")
        assert retrieved is not None
        assert retrieved.rule_id == "R-200"
        assert retrieved.version == 1
        assert retrieved.name == "Initial Rule"

    def test_update_rule_increments_version_preserving_history(self, registry):
        rule_v1 = BusinessRule(
            rule_id="R-201",
            name="Versioned Rule",
            version=1,
            condition=RulePredicate(field="x", operator=RuleOperator.EQ, value=1),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        registry.register_rule(rule_v1)

        # Update rule
        rule_v2 = registry.update_rule(
            rule_id="R-201",
            name="Versioned Rule Updated",
            condition=RulePredicate(field="x", operator=RuleOperator.EQ, value=2),
        )
        assert rule_v2.version == 2
        assert rule_v2.name == "Versioned Rule Updated"

        # Lookup latest version
        latest = registry.get_rule("R-201")
        assert latest.version == 2

        # Historical version lookup
        historical_v1 = registry.get_rule("R-201", version=1)
        assert historical_v1 is not None
        assert historical_v1.version == 1
        assert historical_v1.name == "Versioned Rule"

    def test_list_and_disable_rules(self, registry):
        r1 = BusinessRule(
            rule_id="R-A",
            name="Rule A",
            condition=RulePredicate(field="a", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        r2 = BusinessRule(
            rule_id="R-B",
            name="Rule B",
            condition=RulePredicate(field="b", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        registry.register_rule(r1)
        registry.register_rule(r2)

        all_rules = registry.list_rules()
        assert len(all_rules) == 2

        # Disable r1
        registry.disable_rule("R-A")
        active_rules = registry.list_rules(status=RuleStatus.ACTIVE)
        assert len(active_rules) == 1
        assert active_rules[0].rule_id == "R-B"
