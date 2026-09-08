"""BEACON V2 — Phase 5 Business Rule Validator.

Performs static validation of rule schemas, condition AST syntax, operator semantics,
type compatibility, and behavior-specific expectation requirements.
"""

from typing import Any, Union
from .models import (
    BusinessRule,
    CompoundRuleCondition,
    ExpectedBehavior,
    ExpectedBehaviorType,
    RuleConditionNode,
    RuleOperator,
    RulePredicate,
    UnaryRuleCondition,
)


class RuleValidationError(ValueError):
    """Raised when a business rule fails static validation."""
    pass


class RuleValidator:
    """Validates structural and semantic correctness of BusinessRules and condition ASTs."""

    def validate_rule(self, rule: Union[BusinessRule, dict[str, Any]]) -> tuple[bool, list[str]]:
        """Validates a complete BusinessRule object or dictionary representation.

        Returns:
            (is_valid, list_of_error_messages)
        """
        errors: list[str] = []

        if isinstance(rule, dict):
            rule_id = rule.get("rule_id")
            name = rule.get("name")
            condition = rule.get("condition")
            expected_behavior = rule.get("expected_behavior")
        else:
            rule_id = rule.rule_id
            name = rule.name
            condition = rule.condition
            expected_behavior = rule.expected_behavior

        if not rule_id or not str(rule_id).strip():
            errors.append("Rule 'rule_id' is required and cannot be blank.")

        if not name or not str(name).strip():
            errors.append("Rule 'name' is required and cannot be blank.")

        # Validate condition AST
        if condition is None:
            errors.append("Rule 'condition' is required.")
        else:
            cond_errors = self.validate_condition(condition)
            errors.extend(cond_errors)

        # Validate expected behavior
        if expected_behavior is None:
            errors.append("Rule 'expected_behavior' is required.")
        else:
            exp_errors = self.validate_expected_behavior(expected_behavior)
            errors.extend(exp_errors)

        return len(errors) == 0, errors

    def validate_condition(self, node: Any) -> list[str]:
        """Recursively validates condition AST node."""
        errors: list[str] = []

        if isinstance(node, RulePredicate) or (isinstance(node, dict) and "operator" in node and "operands" not in node):
            field = getattr(node, "field", None) if isinstance(node, RulePredicate) else node.get("field")
            op = getattr(node, "operator", None) if isinstance(node, RulePredicate) else node.get("operator")
            val = getattr(node, "value", None) if isinstance(node, RulePredicate) else node.get("value")

            if not field or not str(field).strip():
                errors.append("Condition predicate must specify a non-empty 'field'.")

            # Check operator validity
            op_enum = None
            if isinstance(op, RuleOperator):
                op_enum = op
            elif isinstance(op, str):
                try:
                    op_enum = RuleOperator[op.upper()] if op.upper() in RuleOperator.__members__ else RuleOperator(op)
                except Exception:
                    errors.append(f"Invalid condition operator: '{op}'.")
            else:
                errors.append("Condition predicate must specify a valid operator.")

            # Validate operator value requirements
            if op_enum in (RuleOperator.IN, RuleOperator.NOT_IN):
                if not isinstance(val, (list, tuple, set)) and val is not None:
                    errors.append(f"Operator '{op_enum.value}' requires a list/collection value, got {type(val).__name__}.")
            elif op_enum in (RuleOperator.GT, RuleOperator.GTE, RuleOperator.LT, RuleOperator.LTE):
                if val is not None and not isinstance(val, (int, float, str)):
                    errors.append(f"Relational operator '{op_enum.value}' requires comparable numeric or string value.")

        elif isinstance(node, CompoundRuleCondition) or (isinstance(node, dict) and "operands" in node):
            log_op = getattr(node, "logical_op", None) if isinstance(node, CompoundRuleCondition) else node.get("logical_op")
            operands = getattr(node, "operands", None) if isinstance(node, CompoundRuleCondition) else node.get("operands")

            if log_op not in ("AND", "OR"):
                errors.append(f"Compound condition logical_op must be 'AND' or 'OR', got '{log_op}'.")

            if not operands or not isinstance(operands, list) or len(operands) == 0:
                errors.append(f"Compound condition '{log_op}' must have at least one operand.")
            else:
                for idx, op_node in enumerate(operands):
                    sub_errors = self.validate_condition(op_node)
                    for err in sub_errors:
                        errors.append(f"Operand [{idx}]: {err}")

        elif isinstance(node, UnaryRuleCondition) or (isinstance(node, dict) and "operand" in node and "operands" not in node):
            log_op = getattr(node, "logical_op", None) if isinstance(node, UnaryRuleCondition) else node.get("logical_op")
            operand = getattr(node, "operand", None) if isinstance(node, UnaryRuleCondition) else node.get("operand")

            if log_op != "NOT":
                errors.append(f"Unary condition logical_op must be 'NOT', got '{log_op}'.")

            if operand is None:
                errors.append("Unary NOT condition must specify an 'operand'.")
            else:
                sub_errors = self.validate_condition(operand)
                errors.extend(sub_errors)
        else:
            errors.append(f"Unrecognized condition node structure: {type(node)}.")

        return errors

    def validate_expected_behavior(self, exp: Any) -> list[str]:
        """Validates ExpectedBehavior specification with behavior-specific requirements."""
        errors: list[str] = []
        if isinstance(exp, ExpectedBehavior):
            b_type = exp.behavior_type
            status_code = exp.expected_status_code
            target_field = exp.target_field
            expected_val = exp.expected_value
            workflow_event = exp.expected_workflow_event
        elif isinstance(exp, dict):
            b_type = exp.get("behavior_type")
            status_code = exp.get("expected_status_code")
            target_field = exp.get("target_field")
            expected_val = exp.get("expected_value")
            workflow_event = exp.get("expected_workflow_event")
        else:
            return ["Expected behavior must be an ExpectedBehavior model or dictionary."]

        # Check behavior type enum
        b_type_enum = None
        if isinstance(b_type, ExpectedBehaviorType):
            b_type_enum = b_type
        elif isinstance(b_type, str):
            if b_type.upper() in ExpectedBehaviorType.__members__:
                b_type_enum = ExpectedBehaviorType[b_type.upper()]
            else:
                errors.append(f"Invalid expected behavior type: '{b_type}'.")
        elif b_type is None:
            errors.append("Expected behavior must specify 'behavior_type'.")

        if status_code is not None and not isinstance(status_code, int):
            errors.append(f"Expected status code must be an integer, got {type(status_code).__name__}.")

        # Behavior-specific requirement validation
        if b_type_enum == ExpectedBehaviorType.RETURN_VALUE:
            if not target_field or not str(target_field).strip():
                errors.append("Expected behavior RETURN_VALUE requires a non-empty 'target_field'.")
            if expected_val is None:
                errors.append("Expected behavior RETURN_VALUE requires 'expected_value' to be specified.")

        elif b_type_enum == ExpectedBehaviorType.RETURN_STATUS:
            if status_code is None:
                errors.append("Expected behavior RETURN_STATUS requires 'expected_status_code' to be specified.")

        elif b_type_enum == ExpectedBehaviorType.WORKFLOW_STEP:
            if not workflow_event or not str(workflow_event).strip():
                errors.append("Expected behavior WORKFLOW_STEP requires a non-empty 'expected_workflow_event'.")

        return errors


rule_validator = RuleValidator()
