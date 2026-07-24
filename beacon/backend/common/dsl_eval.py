"""Restricted evaluator for invariant condition strings like
'credit_score < 600 and debt_ratio > 0.4'. Used by both Stage 2 (validation)
and Stage 3/4 (oracle interpreter) so a condition means exactly the same thing
everywhere in the pipeline.

Deliberately not a general-purpose eval: only the given input names are
available, no builtins, no attribute access.
"""

_ALLOWED_NAMES = {"and", "or", "not", "in", "True", "False", "None"}


def eval_condition(condition: str, inputs: dict) -> bool:
    """Evaluate a boolean condition string against an inputs dict.

    Example: eval_condition("credit_score < 600 and debt_ratio > 0.4",
                             {"credit_score": 580, "debt_ratio": 0.5}) -> True
    """
    code = compile(condition, "<invariant-condition>", "eval")
    for name in code.co_names:
        if name not in inputs and name not in _ALLOWED_NAMES:
            raise ValueError(f"Condition references unknown name: {name}")
    return bool(eval(code, {"__builtins__": {}}, dict(inputs)))
