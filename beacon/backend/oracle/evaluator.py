"""Phase 8 — Language-Independent Oracle Evaluator.

Evaluates canonical Oracle ASTs directly against generic input/output observations
without executing target implementation code (no eval, no Python runtime dependencies).
"""

import logging
from typing import Any, Optional, Union
from .models import (
    CompoundCondition,
    OracleConditionNode,
    OracleDefinition,
    OracleEvaluationReport,
    OraclePredicate,
    UnaryCondition,
)

logger = logging.getLogger(__name__)


class EvaluationVariableError(ValueError):
    """Raised when an input observation lacks required variables for condition evaluation."""
    pass


def _eval_predicate(predicate: OraclePredicate, inputs: dict[str, Any]) -> bool:
    """Evaluates a single comparison predicate against input values."""
    var_name = predicate.variable
    if var_name not in inputs:
        raise EvaluationVariableError(f"Required input variable '{var_name}' missing from observation.")

    actual_val = inputs[var_name]
    expected_val = predicate.value
    op = predicate.operator

    # Handle numeric comparisons when types might be int vs float
    if isinstance(expected_val, (int, float)) and isinstance(actual_val, (int, float)):
        if op == "<":
            return actual_val < expected_val
        elif op == "<=":
            return actual_val <= expected_val
        elif op == "==":
            return actual_val == expected_val
        elif op == "!=":
            return actual_val != expected_val
        elif op == ">=":
            return actual_val >= expected_val
        elif op == ">":
            return actual_val > expected_val

    # String / Enum / Boolean comparisons
    if op == "==":
        return str(actual_val).strip().upper() == str(expected_val).strip().upper() if isinstance(expected_val, str) else actual_val == expected_val
    elif op == "!=":
        return str(actual_val).strip().upper() != str(expected_val).strip().upper() if isinstance(expected_val, str) else actual_val != expected_val
    elif op == "<":
        return actual_val < expected_val
    elif op == "<=":
        return actual_val <= expected_val
    elif op == ">=":
        return actual_val >= expected_val
    elif op == ">":
        return actual_val > expected_val

    return False


def evaluate_condition(node: OracleConditionNode, inputs: dict[str, Any]) -> bool:
    """Recursively evaluates the OracleConditionNode AST against generic inputs."""
    if isinstance(node, OraclePredicate):
        return _eval_predicate(node, inputs)
    elif isinstance(node, CompoundCondition):
        if node.type == "AND":
            return all(evaluate_condition(child, inputs) for child in node.operands)
        elif node.type == "OR":
            return any(evaluate_condition(child, inputs) for child in node.operands)
    elif isinstance(node, UnaryCondition):
        if node.type == "NOT":
            return not evaluate_condition(node.operand, inputs)

    raise ValueError(f"Unknown condition node type: {type(node)}")


def evaluate_oracle(
    oracle: OracleDefinition,
    inputs: dict[str, Any],
    outputs: Optional[Union[dict[str, Any], Any]] = None,
) -> OracleEvaluationReport:
    """Evaluates an OracleDefinition against a generic observation of inputs and outputs.

    Returns:
    - NOT_APPLICABLE: Condition evaluated to False (antecedent was not satisfied).
    - PASS: Condition evaluated to True and consequence matched observed outputs.
    - FAIL: Condition evaluated to True and consequence was violated.
    - INVALID_INPUT: Required variables were missing or had incompatible types.
    - EVALUATION_ERROR: Unexpected evaluation exception.
    """
    # Normalize inputs dict
    obs_inputs = dict(inputs) if isinstance(inputs, dict) else {}

    # Normalize outputs dict
    obs_outputs: dict[str, Any] = {}
    if isinstance(outputs, dict):
        obs_outputs = dict(outputs)
    elif outputs is not None:
        # Scalar output value assigned to consequence variable
        obs_outputs[oracle.consequence.variable] = outputs
    elif oracle.consequence.variable in obs_inputs:
        # Observation was provided as a flat dictionary containing both inputs and output
        obs_outputs[oracle.consequence.variable] = obs_inputs.pop(oracle.consequence.variable)

    # 1. Condition Evaluation
    try:
        condition_met = evaluate_condition(oracle.condition, obs_inputs)
    except EvaluationVariableError as exc:
        return OracleEvaluationReport(
            oracle_id=oracle.oracle_id,
            status="INVALID_INPUT",
            condition_satisfied=False,
            consequence_satisfied=None,
            inputs_observed=obs_inputs,
            outputs_observed=obs_outputs,
            reason=str(exc),
        )
    except Exception as exc:
        logger.error(f"Oracle #{oracle.oracle_id} condition evaluation error: {exc}")
        return OracleEvaluationReport(
            oracle_id=oracle.oracle_id,
            status="EVALUATION_ERROR",
            condition_satisfied=False,
            consequence_satisfied=None,
            inputs_observed=obs_inputs,
            outputs_observed=obs_outputs,
            reason=f"Condition evaluation error: {exc}",
        )

    # 2. Antecedent not met -> NOT_APPLICABLE
    if not condition_met:
        return OracleEvaluationReport(
            oracle_id=oracle.oracle_id,
            status="NOT_APPLICABLE",
            condition_satisfied=False,
            consequence_satisfied=None,
            inputs_observed=obs_inputs,
            outputs_observed=obs_outputs,
            reason="Condition was not satisfied; consequence not exercised.",
        )

    # 3. Antecedent met -> Evaluate Consequence
    target_var = oracle.consequence.variable
    expected_val = oracle.consequence.value

    if target_var not in obs_outputs:
        return OracleEvaluationReport(
            oracle_id=oracle.oracle_id,
            status="FAIL",
            condition_satisfied=True,
            consequence_satisfied=False,
            inputs_observed=obs_inputs,
            outputs_observed=obs_outputs,
            reason=f"Expected output variable '{target_var}' was missing from observation outputs.",
            counterexample={
                "inputs": obs_inputs,
                "expected": expected_val,
                "actual": None,
                "error": f"Missing '{target_var}' in output",
            },
        )

    actual_val = obs_outputs[target_var]
    match = False

    if isinstance(expected_val, (int, float)) and isinstance(actual_val, (int, float)):
        match = abs(float(actual_val) - float(expected_val)) < 1e-6
    elif isinstance(expected_val, bool) or isinstance(actual_val, bool):
        match = bool(actual_val) == bool(expected_val)
    elif isinstance(expected_val, str) or isinstance(actual_val, str):
        match = str(actual_val).strip().upper() == str(expected_val).strip().upper()
    else:
        match = actual_val == expected_val

    if match:
        return OracleEvaluationReport(
            oracle_id=oracle.oracle_id,
            status="PASS",
            condition_satisfied=True,
            consequence_satisfied=True,
            inputs_observed=obs_inputs,
            outputs_observed=obs_outputs,
        )
    else:
        return OracleEvaluationReport(
            oracle_id=oracle.oracle_id,
            status="FAIL",
            condition_satisfied=True,
            consequence_satisfied=False,
            inputs_observed=obs_inputs,
            outputs_observed=obs_outputs,
            reason=f"Consequence violated: expected {target_var} == '{expected_val}', got '{actual_val}'.",
            counterexample={
                "inputs": obs_inputs,
                "expected": expected_val,
                "actual": actual_val,
            },
        )
