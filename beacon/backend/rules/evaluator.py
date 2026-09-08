"""BEACON V2 — Phase 5 Deterministic Rule Condition & Behavior Evaluator.

Provides safe, data-driven AST evaluation of rule conditions and expected behaviors
against execution observations without using eval() or exec().
Implements strict three-valued logic (TRUE, FALSE, UNKNOWN), field-source isolation
(input, output, state, error, metadata, auto), and preserves exact distinctions
between MISSING, NULL, EMPTY, ZERO, and FALSE.
"""

from enum import Enum
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

# Sentinel object to strictly distinguish missing fields from None / False / 0 / "" / [] / {}
_MISSING = object()


class TriState(str, Enum):
    """Explicit three-valued logic outcome for condition evaluation."""
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class RuleConditionEvaluator:
    """Evaluates rule condition AST nodes against structured observation contexts using three-valued logic."""

    def _extract_from_single_dict(self, container: dict[str, Any], field_path: str) -> Any:
        """Helper to safely extract nested dot-notation or bracket paths from a single dictionary."""
        if not field_path or not isinstance(container, dict):
            return _MISSING

        if field_path in container:
            return container[field_path]

        parts = field_path.split(".")
        current = container

        for part in parts:
            if current is _MISSING or current is None:
                return _MISSING

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

    def extract_field_value(
        self,
        context: dict[str, Any],
        field_path: str,
        field_source: str = "auto",
    ) -> Any:
        """Safely extracts a field path from an isolated evaluation context partitioned by field_source.

        Sources supported:
        - 'input': searches ONLY context['input']
        - 'output': searches ONLY context['output']
        - 'state': searches ONLY context['state']
        - 'error': searches ONLY context['error']
        - 'metadata': searches ONLY context['metadata']
        - 'auto': searches deterministically in order: input -> output -> state -> error -> metadata

        Returns _MISSING if the field is absent in the designated source.
        Preserves None, False, 0, '', [], {} as valid actual values.
        """
        if not field_path or not isinstance(context, dict):
            return _MISSING

        # Check if context is partitioned with standard source keys
        is_partitioned = any(k in context for k in ("input", "output", "state", "error", "metadata"))

        if is_partitioned:
            src = str(field_source).lower() if field_source else "auto"

            if src == "input":
                sub = context.get("input")
                return self._extract_from_single_dict(sub, field_path) if isinstance(sub, dict) else _MISSING

            elif src == "output":
                sub = context.get("output")
                return self._extract_from_single_dict(sub, field_path) if isinstance(sub, dict) else _MISSING

            elif src == "state":
                sub = context.get("state")
                return self._extract_from_single_dict(sub, field_path) if isinstance(sub, dict) else _MISSING

            elif src == "error":
                sub = context.get("error")
                return self._extract_from_single_dict(sub, field_path) if isinstance(sub, dict) else _MISSING

            elif src == "metadata":
                sub = context.get("metadata")
                return self._extract_from_single_dict(sub, field_path) if isinstance(sub, dict) else _MISSING

            elif src == "auto":
                # Deterministic lookup order: input -> output -> state -> error -> metadata
                for sec in ("input", "output", "state", "error", "metadata"):
                    sub = context.get(sec)
                    if isinstance(sub, dict):
                        val = self._extract_from_single_dict(sub, field_path)
                        if val is not _MISSING:
                            return val
                return _MISSING

            else:
                return _MISSING

        else:
            # Flat context dictionary (used in legacy or unit tests)
            src = str(field_source).lower() if field_source else "auto"
            if src in ("auto", "input"):
                return self._extract_from_single_dict(context, field_path)
            elif src in context:
                sub = context.get(src)
                return self._extract_from_single_dict(sub, field_path) if isinstance(sub, dict) else _MISSING
            else:
                # If specific source requested but flat context doesn't have it
                return _MISSING

    def evaluate_condition(
        self, node: RuleConditionNode, context: dict[str, Any]
    ) -> tuple[TriState, str, dict[str, Any]]:
        """Evaluates condition AST against observation context using deterministic three-valued logic.

        Returns:
            (outcome: TriState, explanation: str, observed_values: dict)
        """
        observed: dict[str, Any] = {}

        if isinstance(node, RulePredicate) or (isinstance(node, dict) and "operator" in node and "operands" not in node):
            field = getattr(node, "field", None) if isinstance(node, RulePredicate) else node.get("field")
            op_raw = getattr(node, "operator", None) if isinstance(node, RulePredicate) else node.get("operator")
            target_val = getattr(node, "value", None) if isinstance(node, RulePredicate) else node.get("value")
            field_source = getattr(node, "field_source", "auto") if isinstance(node, RulePredicate) else node.get("field_source", "auto")

            if isinstance(op_raw, RuleOperator):
                op = op_raw
            else:
                try:
                    op = RuleOperator[str(op_raw).upper()]
                except Exception:
                    op = RuleOperator(op_raw)

            actual_val = self.extract_field_value(context, field, field_source=field_source)
            observed[field] = None if actual_val is _MISSING else actual_val

            tri_state, expl = self._evaluate_predicate(field, op, target_val, actual_val, field_source=field_source)
            return tri_state, expl, observed

        elif isinstance(node, CompoundRuleCondition) or (isinstance(node, dict) and "operands" in node):
            log_op = getattr(node, "logical_op", None) if isinstance(node, CompoundRuleCondition) else node.get("logical_op")
            operands = getattr(node, "operands", None) if isinstance(node, CompoundRuleCondition) else node.get("operands")

            if log_op == "AND":
                # Three-valued AND:
                # - If ANY operand is FALSE -> FALSE (False dominates)
                # - Else if ANY operand is UNKNOWN -> UNKNOWN
                # - Else ALL operands are TRUE -> TRUE
                child_outcomes = []
                explanations = []
                for idx, child in enumerate(operands):
                    child_tri, child_expl, child_obs = self.evaluate_condition(child, context)
                    observed.update(child_obs)
                    child_outcomes.append(child_tri)
                    explanations.append(f"[{child_tri.value}] {child_expl}")

                if any(o == TriState.FALSE for o in child_outcomes):
                    return TriState.FALSE, f"AND failed: {'; '.join(explanations)}", observed
                elif any(o == TriState.UNKNOWN for o in child_outcomes):
                    return TriState.UNKNOWN, f"AND unknown: {'; '.join(explanations)}", observed
                else:
                    return TriState.TRUE, f"AND satisfied: {'; '.join(explanations)}", observed

            elif log_op == "OR":
                # Three-valued OR:
                # - If ANY operand is TRUE -> TRUE (True dominates)
                # - Else if ANY operand is UNKNOWN -> UNKNOWN
                # - Else ALL operands are FALSE -> FALSE
                child_outcomes = []
                explanations = []
                for idx, child in enumerate(operands):
                    child_tri, child_expl, child_obs = self.evaluate_condition(child, context)
                    observed.update(child_obs)
                    child_outcomes.append(child_tri)
                    explanations.append(f"[{child_tri.value}] {child_expl}")

                if any(o == TriState.TRUE for o in child_outcomes):
                    return TriState.TRUE, f"OR satisfied: {'; '.join(explanations)}", observed
                elif any(o == TriState.UNKNOWN for o in child_outcomes):
                    return TriState.UNKNOWN, f"OR unknown: {'; '.join(explanations)}", observed
                else:
                    return TriState.FALSE, f"OR failed: {'; '.join(explanations)}", observed

            else:
                return TriState.UNKNOWN, f"Unknown logical operator '{log_op}'", observed

        elif isinstance(node, UnaryRuleCondition) or (isinstance(node, dict) and "operand" in node and "operands" not in node):
            operand = getattr(node, "operand", None) if isinstance(node, UnaryRuleCondition) else node.get("operand")
            child_tri, child_expl, child_obs = self.evaluate_condition(operand, context)
            observed.update(child_obs)

            # Three-valued NOT:
            # - NOT TRUE = FALSE
            # - NOT FALSE = TRUE
            # - NOT UNKNOWN = UNKNOWN
            if child_tri == TriState.TRUE:
                return TriState.FALSE, f"NOT ({child_expl}) -> FALSE", observed
            elif child_tri == TriState.FALSE:
                return TriState.TRUE, f"NOT ({child_expl}) -> TRUE", observed
            else:
                return TriState.UNKNOWN, f"NOT ({child_expl}) -> UNKNOWN", observed

        else:
            return TriState.UNKNOWN, f"Unsupported condition node type: {type(node)}", observed

    def _evaluate_predicate(
        self,
        field: str,
        op: RuleOperator,
        target_val: Any,
        actual_val: Any,
        field_source: str = "auto",
    ) -> tuple[TriState, str]:
        """Evaluates an atomic predicate against the extracted actual value with 3-valued semantics."""
        source_tag = f" [{field_source}]" if field_source != "auto" else ""

        # 1. Existence operators
        if op == RuleOperator.EXISTS:
            if actual_val is not _MISSING:
                return TriState.TRUE, f"Field '{field}'{source_tag} exists in context (value: {actual_val})"
            return TriState.FALSE, f"Field '{field}'{source_tag} does not exist in context"

        if op == RuleOperator.NOT_EXISTS:
            if actual_val is _MISSING:
                return TriState.TRUE, f"Field '{field}'{source_tag} is absent from context"
            return TriState.FALSE, f"Field '{field}'{source_tag} exists in context (value: {actual_val})"

        # If field is missing for non-existence operators, value is UNKNOWN
        if actual_val is _MISSING:
            return TriState.UNKNOWN, f"Field '{field}'{source_tag} is missing from context"

        # 2. Nullity operators (field is present, so we check if its value is None)
        if op == RuleOperator.IS_NULL:
            if actual_val is None:
                return TriState.TRUE, f"Field '{field}'{source_tag} is null (None)"
            return TriState.FALSE, f"Field '{field}'{source_tag} is not null (value: {actual_val})"

        if op == RuleOperator.IS_NOT_NULL:
            if actual_val is not None:
                return TriState.TRUE, f"Field '{field}'{source_tag} is not null (value: {actual_val})"
            return TriState.FALSE, f"Field '{field}'{source_tag} is null (None)"

        # If actual_val is explicitly None and operator requires a non-null comparison
        if actual_val is None and target_val is not None:
            if op == RuleOperator.NE:
                return TriState.TRUE, f"Field '{field}'{source_tag} (null) != {target_val}"
            elif op == RuleOperator.EQ:
                return TriState.FALSE, f"Field '{field}'{source_tag} (null) == {target_val}: False"
            else:
                return TriState.UNKNOWN, f"Field '{field}'{source_tag} is null, cannot compare {op.value} with {target_val}"

        # 3. Equality / Inequality
        if op == RuleOperator.EQ:
            # Handle strict boolean vs integer equality (in Python True == 1, but in rules boolean and integer are distinct)
            if isinstance(actual_val, bool) or isinstance(target_val, bool):
                is_eq = (type(actual_val) is type(target_val)) and (actual_val == target_val)
            else:
                is_eq = (actual_val == target_val)
            return (TriState.TRUE if is_eq else TriState.FALSE), f"Field '{field}'{source_tag} ({actual_val}) == {target_val}: {is_eq}"

        if op == RuleOperator.NE:
            if isinstance(actual_val, bool) or isinstance(target_val, bool):
                is_ne = (type(actual_val) is not type(target_val)) or (actual_val != target_val)
            else:
                is_ne = (actual_val != target_val)
            return (TriState.TRUE if is_ne else TriState.FALSE), f"Field '{field}'{source_tag} ({actual_val}) != {target_val}: {is_ne}"

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
                return (TriState.TRUE if sat else TriState.FALSE), f"Field '{field}'{source_tag} ({actual_val}) {op.value} {target_val}: {sat}"
            elif isinstance(actual_val, str) and isinstance(target_val, str):
                if op == RuleOperator.GT:
                    sat = actual_val > target_val
                elif op == RuleOperator.GTE:
                    sat = actual_val >= target_val
                elif op == RuleOperator.LT:
                    sat = actual_val < target_val
                else:
                    sat = actual_val <= target_val
                return (TriState.TRUE if sat else TriState.FALSE), f"Field '{field}'{source_tag} ('{actual_val}') {op.value} '{target_val}': {sat}"
            else:
                return TriState.UNKNOWN, f"Incompatible types for {op.value} on field '{field}'{source_tag}: {type(actual_val).__name__} vs {type(target_val).__name__}"

        # 5. Collection operators (IN, NOT_IN, CONTAINS, NOT_CONTAINS)
        if op == RuleOperator.IN:
            if isinstance(target_val, (list, tuple, set)):
                sat = actual_val in target_val
                return (TriState.TRUE if sat else TriState.FALSE), f"Field '{field}'{source_tag} ({actual_val}) IN {target_val}: {sat}"
            return TriState.UNKNOWN, f"Target value for IN operator on '{field}'{source_tag} must be a collection"

        if op == RuleOperator.NOT_IN:
            if isinstance(target_val, (list, tuple, set)):
                sat = actual_val not in target_val
                return (TriState.TRUE if sat else TriState.FALSE), f"Field '{field}'{source_tag} ({actual_val}) NOT IN {target_val}: {sat}"
            return TriState.UNKNOWN, f"Target value for NOT_IN operator on '{field}'{source_tag} must be a collection"

        if op == RuleOperator.CONTAINS:
            if isinstance(actual_val, (list, tuple, set, str)):
                sat = target_val in actual_val
                return (TriState.TRUE if sat else TriState.FALSE), f"Field '{field}'{source_tag} ({actual_val}) CONTAINS {target_val}: {sat}"
            return TriState.UNKNOWN, f"Field '{field}'{source_tag} ({type(actual_val).__name__}) is not a collection or string"

        if op == RuleOperator.NOT_CONTAINS:
            if isinstance(actual_val, (list, tuple, set, str)):
                sat = target_val not in actual_val
                return (TriState.TRUE if sat else TriState.FALSE), f"Field '{field}'{source_tag} ({actual_val}) NOT CONTAINS {target_val}: {sat}"
            return TriState.UNKNOWN, f"Field '{field}'{source_tag} ({type(actual_val).__name__}) is not a collection or string"

        return TriState.UNKNOWN, f"Unsupported operator '{op}'"


rule_condition_evaluator = RuleConditionEvaluator()
