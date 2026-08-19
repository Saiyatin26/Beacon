"""Phase 8 — Language-Independent Oracle Compiler / Synthesizer.

Compiles validated CandidateInvariants into canonical, language-independent
executable Oracle ASTs and JSON representations.
"""

import ast
from datetime import datetime, timezone
import logging
from typing import Any, Optional, Union

from common.config import settings
from common.models import CandidateInvariant
from mining.normalizer import normalize_condition
from .models import (
    CompoundCondition,
    OracleConditionNode,
    OracleConsequence,
    OracleDefinition,
    OracleInputSchema,
    OracleOutputSchema,
    OraclePredicate,
    OracleProvenance,
    OracleStatus,
    OracleVariable,
    UnaryCondition,
)
from .serializer import compute_content_hash, serialize_canonical_oracle

logger = logging.getLogger(__name__)


class OracleCompilationError(ValueError):
    """Raised when candidate invariant fails validation gates or contains unsupported syntax."""
    pass


# Map Python AST comparison operators to canonical DSL operator strings
CMP_OP_MAP: dict[type, str] = {
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.GtE: ">=",
    ast.Gt: ">",
}


def _extract_constant_value(node: ast.AST) -> Union[int, float, str, bool]:
    """Extracts scalar constant from an AST node."""
    if isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        val = node.operand.value
        return -val if isinstance(val, (int, float)) else val
    raise OracleCompilationError(f"Unsupported non-constant value in condition: {ast.dump(node)}")


def _parse_ast_node(node: ast.AST) -> OracleConditionNode:
    """Recursively converts a Python AST node into an OracleConditionNode AST."""
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise OracleCompilationError("Chained comparisons (e.g. 10 < x < 20) must be expanded to AND expressions.")
        
        op_type = type(node.ops[0])
        if op_type not in CMP_OP_MAP:
            raise OracleCompilationError(f"Unsupported comparison operator: {op_type.__name__}")
        
        op_str = CMP_OP_MAP[op_type]

        # Case 1: variable <operator> constant (e.g., credit_score < 600)
        if isinstance(node.left, ast.Name) and (isinstance(node.comparators[0], ast.Constant) or isinstance(node.comparators[0], ast.UnaryOp)):
            var_name = node.left.id
            val = _extract_constant_value(node.comparators[0])
            return OraclePredicate(variable=var_name, operator=op_str, value=val)

        # Case 2: constant <operator> variable (e.g., 600 > credit_score)
        elif (isinstance(node.left, ast.Constant) or isinstance(node.left, ast.UnaryOp)) and isinstance(node.comparators[0], ast.Name):
            var_name = node.comparators[0].id
            val = _extract_constant_value(node.left)
            # Invert operator
            inverted_ops = {"<": ">", "<=": ">=", "==": "==", "!=": "!=", ">=": "<=", ">": "<"}
            return OraclePredicate(variable=var_name, operator=inverted_ops[op_str], value=val)

        else:
            raise OracleCompilationError(f"Comparison must be between a variable and a constant literal. Found: {ast.dump(node)}")

    elif isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            operands = [_parse_ast_node(val) for val in node.values]
            return CompoundCondition(type="AND", operands=operands)
        elif isinstance(node.op, ast.Or):
            operands = [_parse_ast_node(val) for val in node.values]
            return CompoundCondition(type="OR", operands=operands)
        else:
            raise OracleCompilationError(f"Unsupported boolean operator: {type(node.op).__name__}")

    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        operand = _parse_ast_node(node.operand)
        return UnaryCondition(type="NOT", operand=operand)

    else:
        raise OracleCompilationError(
            f"Unsupported language syntax or expression form in oracle condition: {type(node).__name__} ({ast.dump(node)})"
        )


def parse_condition_to_ast(condition_str: str) -> OracleConditionNode:
    """Parses a condition string into a canonical language-independent Oracle AST."""
    if not condition_str or not condition_str.strip():
        raise OracleCompilationError("Condition expression cannot be empty.")

    try:
        parsed_ast = ast.parse(condition_str.strip(), mode="eval")
    except SyntaxError as exc:
        raise OracleCompilationError(f"Syntax error in condition '{condition_str}': {exc}")

    return _parse_ast_node(parsed_ast.body)


def parse_consequence_to_ast(consequence_str: str) -> OracleConsequence:
    """Parses a consequence string into an OracleConsequence AST node."""
    raw = str(consequence_str).strip()
    if not raw:
        raise OracleCompilationError("Consequence cannot be empty.")

    # Handle formats like "decision == 'REJECT'", "decision = REJECT", "REJECT"
    if "==" in raw:
        parts = raw.split("==", 1)
        var_name = parts[0].strip()
        val_raw = parts[1].strip().strip("'\"")
        val: Union[str, int, float, bool] = val_raw
        if val_raw.isdigit():
            val = int(val_raw)
        elif val_raw.lower() in ("true", "false"):
            val = val_raw.lower() == "true"
        return OracleConsequence(variable=var_name, operator="==", value=val)
    elif "=" in raw and not raw.startswith("="):
        parts = raw.split("=", 1)
        var_name = parts[0].strip()
        val_raw = parts[1].strip().strip("'\"")
        return OracleConsequence(variable=var_name, operator="==", value=val_raw)
    else:
        # Simple scalar consequence e.g. "REJECT", "APPROVE"
        val_clean = raw.strip("'\"")
        return OracleConsequence(variable="decision", operator="==", value=val_clean)


def _collect_variables_from_ast(node: OracleConditionNode) -> list[OracleVariable]:
    """Extracts referenced variables and infers primitive types from condition AST."""
    var_dict: dict[str, OracleVariable] = {}

    def _traverse(n: OracleConditionNode):
        if isinstance(n, OraclePredicate):
            v_name = n.variable
            v_type: str = "unknown"
            if isinstance(n.value, bool):
                v_type = "bool"
            elif isinstance(n.value, int):
                v_type = "int"
            elif isinstance(n.value, float):
                v_type = "float"
            elif isinstance(n.value, str):
                v_type = "str"

            if v_name not in var_dict:
                var_dict[v_name] = OracleVariable(name=v_name, var_type=v_type)
            elif var_dict[v_name].var_type == "unknown" and v_type != "unknown":
                var_dict[v_name].var_type = v_type
        elif isinstance(n, CompoundCondition):
            for child in n.operands:
                _traverse(child)
        elif isinstance(n, UnaryCondition):
            _traverse(n.operand)

    _traverse(node)
    return [var_dict[k] for k in sorted(var_dict.keys())]


def compile_candidate_to_oracle(
    candidate: CandidateInvariant,
    confidence_threshold: Optional[float] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> OracleDefinition:
    """Compiles a validated CandidateInvariant into a canonical language-independent Oracle.

    Enforces:
    1. Strict Validation Gating: Candidate must be 'graduated' / 'VALIDATED'.
    2. Confidence Gating: Candidate confidence must satisfy the threshold (default 0.8).
    3. Counterexample Check: Rejects candidates that failed validation.
    4. Canonical AST Parsing: Compiles to language-independent AST nodes.
    5. Provenance & SHA-256 Content Hashing.
    """
    threshold = confidence_threshold if confidence_threshold is not None else settings.confidence_threshold

    # Gating checks
    cand_status = getattr(candidate, "status", "").lower()
    cand_confidence = getattr(candidate, "confidence", 0.0)

    if cand_status in ("unconfirmed", "invalidated", "grounding_failed"):
        raise OracleCompilationError(
            f"Cannot compile candidate #{candidate.invariant_id} with unvalidated status '{candidate.status}'."
        )

    if cand_confidence < threshold:
        raise OracleCompilationError(
            f"Candidate #{candidate.invariant_id} confidence ({cand_confidence:.2f}) is below certification threshold ({threshold:.2f})."
        )

    val_res = getattr(candidate, "validation_result", None)
    if val_res:
        ces = val_res.get("counterexamples", []) if isinstance(val_res, dict) else getattr(val_res, "counterexamples", [])
        if ces:
            raise OracleCompilationError(
                f"Candidate #{candidate.invariant_id} contains active counterexamples refuting the invariant."
            )

    # 1. Parse Condition & Consequence into canonical AST
    condition_ast = parse_condition_to_ast(candidate.condition)
    consequence_ast = parse_consequence_to_ast(candidate.consequence)

    # 2. Extract and infer Input & Output Schemas
    input_vars = _collect_variables_from_ast(condition_ast)
    input_schema = OracleInputSchema(variables=input_vars)
    output_schema = OracleOutputSchema(
        variable=consequence_ast.variable,
        var_type="str" if isinstance(consequence_ast.value, str) else type(consequence_ast.value).__name__,
        allowed_values=[consequence_ast.value],
    )

    # 3. Canonical Condition & Raw Condition strings
    canonical_cond_str = normalize_condition(candidate.condition)
    raw_cond_str = candidate.raw_condition or candidate.condition

    # 4. Construct Audit Provenance
    validation_run_id = None
    if val_res:
        validation_run_id = val_res.get("validation_run_id") if isinstance(val_res, dict) else getattr(val_res, "validation_run_id", None)

    cand_domain = getattr(candidate, "domain", "business_logic")

    provenance = OracleProvenance(
        invariant_id=candidate.invariant_id,
        source_file=candidate.source_file,
        source_lines=candidate.source_lines,
        evidence_ids=candidate.evidence_ids,
        execution_ids=candidate.execution_ids,
        validation_run_id=validation_run_id,
        confidence=cand_confidence,
        severity=candidate.severity,
        domain=cand_domain,
        generation_method=candidate.generation_method,
        generation_timestamp=candidate.timestamp or datetime.now(timezone.utc).isoformat(),
        reproducibility=candidate.reproducibility or {},
    )

    # 5. Deterministic Canonical Serialization & SHA-256 Content Hash
    canonical_json = serialize_canonical_oracle(
        condition_dict=condition_ast.model_dump(mode="json"),
        consequence_dict=consequence_ast.model_dump(mode="json"),
        input_schema_dict=input_schema.model_dump(mode="json"),
        output_schema_dict=output_schema.model_dump(mode="json"),
        domain=cand_domain,
    )
    content_hash = compute_content_hash(canonical_json)
    oracle_id = f"ORC-{content_hash[:8]}"

    # Backward compatibility properties
    property_expr = f"({canonical_cond_str}) implies (decision == '{str(consequence_ast.value).upper()}')"
    inputs_list = [v.name for v in input_vars]

    return OracleDefinition(
        oracle_id=oracle_id,
        version=1,
        invariant_id=candidate.invariant_id,
        name=name or f"Oracle-{candidate.invariant_id}",
        description=description or candidate.rationale or f"Behavioral Oracle for rule {canonical_cond_str}",
        domain=cand_domain,
        severity=candidate.severity,
        condition=condition_ast,
        consequence=consequence_ast,
        input_schema=input_schema,
        output_schema=output_schema,
        provenance=provenance,
        raw_condition=raw_cond_str,
        canonical_condition=canonical_cond_str,
        canonical_json=canonical_json,
        content_hash=content_hash,
        status=OracleStatus.ACTIVE,
        created_at=datetime.now(timezone.utc).isoformat(),
        property=property_expr,
        inputs=inputs_list,
        tolerance=0.0,
        confidence=candidate.confidence,
    )
