"""BEACON V2 — Phase 7 Rule Normalizer.

Provides canonical AST and expression normalization across Phase 5 BusinessRules
and Phase 6 DiscoveredCandidates for deterministic comparison, deduplication, and fingerprinting.
"""

import re
from typing import Any, Optional, Union
from pydantic import BaseModel

from discovery.models import DiscoveredCandidate
from rules.models import (
    BusinessRule,
    CompoundRuleCondition,
    ExpectedBehavior,
    RuleConditionNode,
    RuleOperator,
    RulePredicate,
    UnaryRuleCondition,
)
from .models import OracleRule, ResolutionState, RuleProvenanceSource, compute_deterministic_hash


class NormalizedRuleRepresentation(BaseModel):
    """Internal canonicalized representation of a candidate or business rule."""
    source_id: str
    source_type: RuleProvenanceSource
    rule_type: str
    name: str
    description: str
    canonical_expression: str
    normalized_conditions: dict[str, Any]
    normalized_expected_behavior: dict[str, Any]
    role_scope: str
    confidence: float
    support_count: int
    contradiction_count: int
    unknown_count: int
    applicable_count: int
    evidence_ids: list[str]
    input_ids: list[str]
    candidate_fingerprints: list[str]
    source_rule_ids: list[str]
    source_candidate_ids: list[str]
    fingerprint: str


class RuleNormalizer:
    """Normalizes rules from disparate sources into deterministic, canonical structures."""

    def normalize_user_rule(self, rule: BusinessRule, role_scope: str = "reference") -> NormalizedRuleRepresentation:
        """Normalizes a Phase 5 user-defined BusinessRule."""
        cond_dict = self._normalize_condition_node(rule.condition)
        exp_dict = self._normalize_expected_behavior(rule.expected_behavior)
        canonical_expr = self._construct_canonical_expression_from_user_rule(rule, cond_dict, exp_dict)
        clean_expr = self.clean_expression(canonical_expr)

        payload = {
            "canonical_expression": clean_expr,
            "conditions": cond_dict,
            "expected_behavior": exp_dict,
            "role_scope": role_scope,
        }
        fingerprint = compute_deterministic_hash(payload)

        return NormalizedRuleRepresentation(
            source_id=rule.rule_id,
            source_type=RuleProvenanceSource.USER_DEFINED,
            rule_type="BUSINESS_RULE",
            name=rule.name or rule.rule_id,
            description=rule.description or "",
            canonical_expression=clean_expr,
            normalized_conditions=cond_dict,
            normalized_expected_behavior=exp_dict,
            role_scope=role_scope,
            confidence=1.0,
            support_count=1,
            contradiction_count=0,
            unknown_count=0,
            applicable_count=1,
            evidence_ids=[],
            input_ids=[],
            candidate_fingerprints=[],
            source_rule_ids=[rule.rule_id],
            source_candidate_ids=[],
            fingerprint=fingerprint,
        )

    def normalize_discovered_candidate(self, cand: DiscoveredCandidate) -> NormalizedRuleRepresentation:
        """Normalizes a Phase 6 DiscoveredCandidate."""
        norm_expr = self.clean_expression(cand.canonical_expression)
        cond_dict, exp_dict = self._parse_candidate_expression(cand.canonical_expression, cand.rule_type.value)

        payload = {
            "canonical_expression": norm_expr,
            "conditions": cond_dict,
            "expected_behavior": exp_dict,
            "role_scope": cand.role_scope,
        }
        fingerprint = compute_deterministic_hash(payload)

        return NormalizedRuleRepresentation(
            source_id=cand.candidate_id or cand.fingerprint[:16],
            source_type=RuleProvenanceSource.DISCOVERED,
            rule_type=cand.rule_type.value,
            name=cand.candidate_id or f"discovered_{cand.fingerprint[:8]}",
            description=cand.description or "",
            canonical_expression=norm_expr,
            normalized_conditions=cond_dict,
            normalized_expected_behavior=exp_dict,
            role_scope=cand.role_scope,
            confidence=cand.confidence,
            support_count=cand.support_count,
            contradiction_count=cand.contradiction_count,
            unknown_count=cand.unknown_count,
            applicable_count=cand.applicable_count,
            evidence_ids=list(cand.evidence_ids),
            input_ids=list(cand.input_ids),
            candidate_fingerprints=[cand.fingerprint] if cand.fingerprint else [],
            source_rule_ids=[],
            source_candidate_ids=[cand.candidate_id] if cand.candidate_id else [],
            fingerprint=fingerprint,
        )

    def clean_expression(self, expression: str) -> str:
        """Standardizes whitespace, quotes, operator spacing, and literal casing in a canonical expression."""
        if not expression:
            return ""
        s = expression.strip()
        s = re.sub(r"\s+", " ", s)
        # Normalize operator spacing: ' == ', ' != ', ' <= ', ' >= ', ' < ', ' > '
        s = re.sub(r"\s*==\s*", " == ", s)
        s = re.sub(r"\s*!=\s*", " != ", s)
        s = re.sub(r"\s*<=\s*", " <= ", s)
        s = re.sub(r"\s*>=\s*", " >= ", s)
        s = re.sub(r"(?<!<)\s*<\s*(?!=)", " < ", s)
        s = re.sub(r"(?<!>)\s*>\s*(?!=)", " > ", s)
        s = re.sub(r"\s*->\s*", " -> ", s)

        # Canonicalize boolean and null literal casing
        s = re.sub(r"\b(true|True|TRUE)\b", "true", s)
        s = re.sub(r"\b(false|False|FALSE)\b", "false", s)
        s = re.sub(r"\b(null|Null|NULL|none|None|NONE)\b", "null", s)
        return s.strip()

    def _normalize_condition_node(self, node: RuleConditionNode) -> dict[str, Any]:
        """Recursively converts a Phase 5 condition AST into a deterministic canonical dictionary."""
        if isinstance(node, RulePredicate):
            op = node.operator.value if isinstance(node.operator, RuleOperator) else str(node.operator)
            op_sym = {
                "EQ": "==", "NE": "!=", "GT": ">", "GTE": ">=",
                "LT": "<", "LTE": "<=", "IS_NULL": "IS_NULL", "IS_NOT_NULL": "IS_NOT_NULL"
            }.get(op, op)
            val = node.value
            if isinstance(val, float) and val.is_integer():
                val = int(val)
            return {
                "type": "predicate",
                "field": node.field.strip(),
                "operator": op_sym,
                "value": val,
                "field_source": "auto",
            }
        elif isinstance(node, CompoundRuleCondition):
            norm_ops = [self._normalize_condition_node(op) for op in node.operands]
            norm_ops.sort(key=lambda x: compute_deterministic_hash(x))
            return {
                "type": "compound",
                "logical_op": node.logical_op,
                "operands": norm_ops,
            }
        elif isinstance(node, UnaryRuleCondition):
            return {
                "type": "unary",
                "logical_op": node.logical_op,
                "operand": self._normalize_condition_node(node.operand),
            }
        elif isinstance(node, dict):
            return node
        return {"raw": str(node)}

    def _normalize_expected_behavior(self, eb: ExpectedBehavior) -> dict[str, Any]:
        """Normalizes a Phase 5 ExpectedBehavior specification."""
        val = eb.expected_value
        if isinstance(val, float) and val.is_integer():
            val = int(val)
        return {
            "behavior_type": eb.behavior_type.value if hasattr(eb.behavior_type, "value") else str(eb.behavior_type),
            "target_field": eb.target_field or "",
            "expected_value": val,
            "expected_status_code": eb.expected_status_code,
            "expected_error_code": eb.expected_error_code,
            "expected_state_mutation": eb.expected_state_mutation,
            "expected_workflow_event": eb.expected_workflow_event,
        }

    def _construct_canonical_expression_from_user_rule(
        self,
        rule: BusinessRule,
        cond_dict: dict[str, Any],
        exp_dict: dict[str, Any],
    ) -> str:
        """Constructs a deterministic canonical expression string from a Phase 5 user rule."""
        cond_str = self._condition_dict_to_str(cond_dict)
        exp_str = self._expected_behavior_dict_to_str(exp_dict)
        if cond_str and exp_str:
            return f"IF {cond_str} THEN {exp_str}"
        elif exp_str:
            return exp_str
        return rule.natural_language_text or rule.name

    def _condition_dict_to_str(self, d: dict[str, Any]) -> str:
        if not d:
            return ""
        t = d.get("type")
        if t == "predicate":
            f = d.get("field", "")
            op = d.get("operator", "==")
            v = d.get("value")
            if op in ("IS_NULL", "IS_NOT_NULL"):
                return f"{f} {op}"
            return f"{f} {op} {v}"
        elif t == "compound":
            lop = d.get("logical_op", "AND")
            ops = [self._condition_dict_to_str(op) for op in d.get("operands", [])]
            return f"({f' {lop} '.join(ops)})"
        elif t == "unary":
            return f"NOT ({self._condition_dict_to_str(d.get('operand', {}))})"
        return str(d)

    def _expected_behavior_dict_to_str(self, d: dict[str, Any]) -> str:
        if not d:
            return ""
        b_type = d.get("behavior_type", "")
        if b_type == "RETURN_VALUE":
            tf = d.get("target_field", "output")
            ev = d.get("expected_value")
            return f"{tf} == {ev}"
        elif b_type == "ACCEPT":
            return "status == ACCEPT"
        elif b_type == "REJECT":
            return "status == REJECT"
        elif b_type == "ERROR":
            ec = d.get("expected_error_code")
            return f"error == {ec}" if ec else "has_error == true"
        elif b_type == "STATE_CHANGE":
            return "state.mutated == true"
        elif b_type == "NO_STATE_CHANGE":
            return "state.mutated == false"
        return f"behavior == {b_type}"

    def _parse_candidate_expression(self, expr: str, rule_type: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Parses a candidate expression into condition and expected behavior dictionaries."""
        cond_dict: dict[str, Any] = {}
        exp_dict: dict[str, Any] = {}

        s = self.clean_expression(expr)
        # Check for IF ... THEN ...
        m_if = re.match(r"^IF\s+(.+?)\s+THEN\s+(.+)$", s, re.IGNORECASE)
        if m_if:
            cond_str, then_str = m_if.groups()
            cond_dict = self._parse_single_condition_str(cond_str)
            exp_dict = self._parse_single_consequence_str(then_str)
            return cond_dict, exp_dict

        # Handle simple pattern: output.x == y
        m_eq = re.match(r"^([\w\.]+)\s*(==|!=|<=|>=|<|>)\s*(.+)$", s)
        if m_eq:
            field, op, val_str = m_eq.groups()
            val = self._parse_val(val_str)
            if field.startswith("input."):
                cond_dict = {"type": "predicate", "field": field, "operator": op, "value": val, "field_source": "auto"}
            else:
                exp_dict = {
                    "behavior_type": "RETURN_VALUE",
                    "target_field": field,
                    "expected_value": val,
                    "expected_status_code": None,
                    "expected_error_code": None,
                    "expected_state_mutation": None,
                    "expected_workflow_event": None,
                }
        else:
            exp_dict = {
                "behavior_type": "EXPRESSION",
                "target_field": "",
                "expected_value": None,
                "expected_status_code": None,
                "expected_error_code": None,
                "expected_state_mutation": None,
                "expected_workflow_event": None,
                "expression": s,
            }

        return cond_dict, exp_dict

    def _parse_single_condition_str(self, s: str) -> dict[str, Any]:
        """Parses condition string (atomic or compound) into condition dictionary."""
        s = s.strip().strip("()")
        if " AND " in s:
            parts = s.split(" AND ")
            operands = [self._parse_single_condition_str(p) for p in parts]
            operands.sort(key=lambda x: compute_deterministic_hash(x))
            return {
                "type": "compound",
                "logical_op": "AND",
                "operands": operands,
            }
        if " OR " in s:
            parts = s.split(" OR ")
            operands = [self._parse_single_condition_str(p) for p in parts]
            operands.sort(key=lambda x: compute_deterministic_hash(x))
            return {
                "type": "compound",
                "logical_op": "OR",
                "operands": operands,
            }
        m = re.match(r"^([\w\.]+)\s*(==|!=|<=|>=|<|>)\s*(.+)$", s)
        if m:
            field, op, val_str = m.groups()
            return {
                "type": "predicate",
                "field": field.strip(),
                "operator": op.strip(),
                "value": self._parse_val(val_str),
                "field_source": "auto",
            }
        return {"raw": s}


    def _parse_single_consequence_str(self, s: str) -> dict[str, Any]:
        """Parses consequence string into expected behavior dictionary."""
        s = s.strip()
        m = re.match(r"^([\w\.]+)\s*(==|!=|<=|>=|<|>)\s*(.+)$", s)
        if m:
            field, op, val_str = m.groups()
            return {
                "behavior_type": "RETURN_VALUE",
                "target_field": field.strip(),
                "expected_value": self._parse_val(val_str),
                "expected_status_code": None,
                "expected_error_code": None,
                "expected_state_mutation": None,
                "expected_workflow_event": None,
            }
        return {
            "behavior_type": "EXPRESSION",
            "target_field": "",
            "expected_value": None,
            "expected_status_code": None,
            "expected_error_code": None,
            "expected_state_mutation": None,
            "expected_workflow_event": None,
            "expression": s,
        }


    def _parse_val(self, val_str: str) -> Any:
        v = val_str.strip()
        if v.lower() == "true":
            return True
        elif v.lower() == "false":
            return False
        elif v.lower() == "null":
            return None
        try:
            if "." in v:
                f_val = float(v)
                return int(f_val) if f_val.is_integer() else f_val
            return int(v)
        except ValueError:
            return v.strip('"\'')


rule_normalizer = RuleNormalizer()

