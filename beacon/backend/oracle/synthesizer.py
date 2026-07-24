"""Stage 3 — Oracle synthesis.

Compiles a ValidatedInvariant into an Oracle: a language-agnostic schema
({invariant_id, inputs, property, tolerance, confidence, severity}) rather
than code tied to one target language (architecture doc Section 3, Stage 3).

For the demo, 'property' is the same condition/consequence DSL string used in
Stage 2, evaluated directly by oracle/interpreter.py against both legacy and
modernized implementations — this is the [MOCKED] simplification noted in the
architecture doc in place of full per-target-language codegen.
"""

import re
from common.models import ValidatedInvariant, Oracle


def synthesize_oracle(invariant: ValidatedInvariant) -> Oracle:
    input_fields = sorted(set(re.findall(r"[a-zA-Z_]\w*", invariant.condition)) - {"and", "or", "not"})
    property_expr = f"({invariant.condition}) implies (decision == '{invariant.consequence.upper()}')"

    return Oracle(
        invariant_id=invariant.invariant_id,
        inputs=input_fields,
        property=property_expr,
        tolerance=0.0,
        confidence=invariant.confidence,
        severity=invariant.severity,
    )
