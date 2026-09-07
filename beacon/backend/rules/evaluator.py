"""BEACON V2 — Phase 5 Deterministic Rule Condition & Behavior Evaluator.

Provides safe, data-driven AST evaluation of rule conditions and expected behaviors
against execution observations without using eval() or exec().
"""

import math
from typing import Any, Optional, Union
from .models import (
    CompoundRuleCondition,
    ExpectedBehavior,
    ExpectedBehaviorType,
    RuleConditionNode,
    RuleOperator,
    RulePredicate,
    UnaryRuleCondition,
)

# Sentinel object to strictly distinguish missing fields from None / False / 0 / ""
_MISSING = object()


class RuleConditionEvaluator:
    """Evaluates rule condition AST nodes against structured observation contexts."""

    def extract_field_value(self, context: dict[str, Any], field_path: str) -> Any:
        """Safely extracts a nested field path (e.g. 'user.age' or 'items[0].id') from context.

        Returns _MISSING if the field is absent.
        """
        if not field_path or not isinstance(context, dict):
            return _MISSING

        # Support direct dot-notation paths
        parts = field_path.split(".")
        current = context

        for part in parts:
            if current is _MISSING or current is None:
                return _MISSING

            # Handle array index if present (e.g. 'items[0]')
            if "[" in part and part.endswith("]"):
                name, idx_str = part[:-1].split("[", 1)
                if isinstance(current, dict):
                    if name not in current:
                        return _MISSING
                    current = current[name]
                else:
                    return _MISSING

                try:
                    idx = int(idx_str)
                    if isinstance(current, (list, tuple)) and 0 <= idx < len(current):
                        current = current[idx]
                    else:
                        return _MISSING
                except ValueError:
                    return _MISSING
            else:
                if isinstance(current, dict):
                    if part in current:
                        current = current[part]
                    else:
                        return _MISSING
                elif hasattr(current, part):
                    current = getattr(current, part)
                else:
                    return _MISSING

        return current

    def evaluate_condition(
        self, node: RuleConditionNode, context: dict[str, Any]
    ) -> tuple[bool, str, dict[str, Any]]:
        """Evaluates condition AST against observation context.

        Returns:
            (is_satisfied: bool, explanation: str, observed_values: dict)
        """
        observed: dict[str, Any] = {}

        if isinstance(node, RulePredicate) or (isinstance(node, dict) and "operator" in node and "operands" not in node):
            field = getattr(node, "field", None) if isinstance(node, RulePredicate) else node.get("field")
            op_raw = getattr(node, "operator", None) if isinstance(node, RulePredicate) else node.get("operator")
            target_val = getattr(node, "value", None) if isinstance(node, RulePredicate) else node.get("value")

            if isinstance(op_raw, RuleOperator):
                op = op_raw
            else:
                try:
                    op = RuleOperator[str(op_raw).upper()]
                except Exception:
                    op = RuleOperator(op_raw)

            actual_val = self.extract_field_value(context, field)
            observed[field] = None if actual_val is _MISSING else actual_val

            sat, expl = self._evaluate_predicate(field, op, target_val, actual_val)
            return sat, expl, observed

        elif isinstance(node, CompoundRuleCondition) or (isinstance(node, dict) and "operands" in node):
            log_op = getattr(node, "logical_op", None) if isinstance(node, CompoundRuleCondition) else node.get("logical_op")
            operands = getattr(node, "operands", None) if isinstance(node, CompoundRuleCondition) else node.get("operands")

            if log_op == "AND":
                all_sat = True
                explanations = []
                for idx, child in enumerate(operands):
                    child_sat, child_expl, child_obs = self.evaluate_condition(child, context)
                    observed.update(child_obs)
                    explanations.append(child_expl)
                    if not child_sat:
                        all_sat = False
                        break
                return all_sat, "; AND ".join(explanations), observed

            elif log_op == "OR":
                any_sat = False
                explanations = []
                for idx, child in enumerate(operands):
                    child_sat, child_expl, child_obs = self.evaluate_condition(child, context)
                    observed.update(child_obs)
                    explanations.append(child_expl)
                    if child_sat:
                        any_sat = True
                        break
                return any_sat, "; OR ".join(explanations), observed

            else:
                return False, f"Unknown logical operator '{log_op}'", observed

        elif isinstance(node, UnaryRuleCondition) or (isinstance(node, dict) and "operand" in node and "operands" not in node):
            operand = getattr(node, "operand", None) if isinstance(node, UnaryRuleCondition) else node.get("operand")
            child_sat, child_expl, child_obs = self.evaluate_condition(operand, context)
            observed.update(child_obs)
            return (not child_sat), f"NOT ({child_expl})", observed

        else:
            return False, f"Unsupported condition node type: {type(node)}", observed

    def _evaluate_predicate(
        self, field: str, op: RuleOperator, target_val: Any, actual_val: Any
    ) -> tuple[bool, str]:
        """Evaluates an atomic predicate against the extracted actual value."""
        # 1. Existence operators
        if op == RuleOperator.EXISTS:
            is_present = actual_val is not _MISSING
            return is_present, f"Field '{field}' exists: {is_present}"

        if op == RuleOperator.NOT_EXISTS:
            is_absent = actual_val is _MISSING
            return is_absent, f"Field '{field}' absent: {is_absent}"

        # If field is missing for value-based operators, condition cannot be satisfied
        if actual_val is _MISSING:
            return False, f"Field '{field}' is missing from observation context"

        # 2. Nullity operators
        if op == RuleOperator.IS_NULL:
            is_null = actual_val is None
            return is_null, f"Field '{field}' is null: {is_null}"

        if op == RuleOperator.IS_NOT_NULL:
            is_not_null = actual_val is not None
            return is_not_null, f"Field '{field}' is not null: {is_not_null}"

        # If actual_val is None but operator requires a value
        if actual_val is None and target_val is not None:
            if op == RuleOperator.NE:
                return True, f"Field '{field}' (null) != {target_val}"
            return False, f"Field '{field}' is null, cannot satisfy {op.value} {target_val}"

        # 3. Equality / Inequality
        if op == RuleOperator.EQ:
            # Handle strict boolean vs int (in Python True == 1, but in rules we check types strictly)
            if isinstance(actual_val, bool) or isinstance(target_val, bool):
                is_eq = (type(actual_val) is type(target_val)) and (actual_val == target_val)
            else:
                is_eq = (actual_val == target_val)
            return is_eq, f"Field '{field}' ({actual_val}) == {target_val}: {is_eq}"

        if op == RuleOperator.NE:
            if isinstance(actual_val, bool) or isinstance(target_val, bool):
                is_ne = (type(actual_val) is not type(target_val)) or (actual_val != target_val)
            else:
                is_ne = (actual_val != target_val)
            return is_ne, f"Field '{field}' ({actual_val}) != {target_val}: {is_ne}"

        # 4. Relational comparisons (GT, GTE, LT, LTE)
        if op in (RuleOperator.GT, RuleOperator.GTE, RuleOperator.LT, RuleOperator.LTE):
            # Numeric comparisons
            if isinstance(actual_val, (int, float)) and isinstance(target_val, (int, float)) and not isinstance(actual_val, bool) and not isinstance(target_val, bool):
                a_num, t_num = float(actual_val), float(target_val)
                if op == RuleOperator.GT:
                    sat = a_num > t_num
                elif op == RuleOperator.GTE:
                    sat = a_num >= t_num
                elif op == RuleOperator.LT:
                    sat = a_num < t_num
                else:
                    sat = a_num <= t_num
                return sat, f"Field '{field}' ({actual_val}) {op.value} {target_val}: {sat}"
            elif isinstance(actual_val, str) and isinstance(target_val, str):
                if op == RuleOperator.GT:
                    sat = actual_val > target_val
                elif op == RuleOperator.GTE:
                    sat = actual_val >= target_val
                elif op == RuleOperator.LT:
                    sat = actual_val < target_val
                else:
                    sat = actual_val <= target_val
                return sat, f"Field '{field}' ('{actual_val}') {op.value} '{target_val}': {sat}"
            else:
                return False, f"Incompatible types for {op.value} on field '{field}': {type(actual_val).__name__} vs {type(target_val).__name__}"

        # 5. Collection operators (IN, NOT_IN, CONTAINS, NOT_CONTAINS)
        if op == RuleOperator.IN:
            if isinstance(target_val, (list, tuple, set)):
                sat = actual_val in target_val
                return sat, f"Field '{field}' ({actual_val}) IN {target_val}: {sat}"
            return False, f"Target value for IN operator on '{field}' must be a collection"

        if op == RuleOperator.NOT_IN:
            if isinstance(target_val, (list, tuple, set)):
                sat = actual_val not in target_val
                return sat, f"Field '{field}' ({actual_val}) NOT IN {target_val}: {sat}"
            return False, f"Target value for NOT_IN operator on '{field}' must be a collection"

        if op == RuleOperator.CONTAINS:
            if isinstance(actual_val, (list, tuple, set, str)):
                sat = target_val in actual_val
                return sat, f"Field '{field}' ({actual_val}) CONTAINS {target_val}: {sat}"
            return False, f"Field '{field}' ({type(actual_val).__name__}) is not a collection or string"

        if op == RuleOperator.NOT_CONTAINS:
            if isinstance(actual_val, (list, tuple, set, str)):
                sat = target_val not in actual_val
                return sat, f"Field '{field}' ({actual_val}) NOT CONTAINS {target_val}: {sat}"
            return False, f"Field '{field}' ({type(actual_val).__name__}) is not a collection or string"

        return False, f"Unsupported operator '{op}'"


rule_condition_evaluator = RuleConditionEvaluator()
