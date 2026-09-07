"""BEACON V2 — Phase 5 Rule Normalizer and Fingerprint Generator.

Transforms BusinessRule definitions and condition ASTs into canonical, deterministic
JSON representations for reproducible SHA-256 fingerprinting.
"""

import hashlib
import json
from typing import Any, Union
from .models import (
    BusinessRule,
    CompoundRuleCondition,
    ExpectedBehavior,
    RuleConditionNode,
    RulePredicate,
    UnaryRuleCondition,
)


class RuleNormalizer:
    """Normalizes rules and AST nodes into canonical structures for deterministic hashing."""

    def canonicalize_condition(self, node: RuleConditionNode) -> dict[str, Any]:
        """Recursively canonicalizes a condition AST node."""
        if isinstance(node, RulePredicate):
            return {
                "type": "predicate",
                "field": str(node.field).strip(),
                "field_source": node.field_source,
                "operator": node.operator.value if hasattr(node.operator, "value") else str(node.operator),
                "value": self._canonicalize_value(node.value),
            }
        elif isinstance(node, CompoundRuleCondition):
            # Canonicalize operands and sort them by deterministic string representation
            canonical_operands = [self.canonicalize_condition(op) for op in node.operands]
            canonical_operands.sort(key=lambda op: json.dumps(op, sort_keys=True, separators=(",", ":")))
            return {
                "type": "compound",
                "logical_op": node.logical_op,
                "operands": canonical_operands,
            }
        elif isinstance(node, UnaryRuleCondition):
            return {
                "type": "unary",
                "logical_op": node.logical_op,
                "operand": self.canonicalize_condition(node.operand),
            }
        elif isinstance(node, dict):
            # Duck-typed dict condition
            if "logical_op" in node and "operands" in node:
                ops = [self.canonicalize_condition(op) for op in node["operands"]]
                ops.sort(key=lambda op: json.dumps(op, sort_keys=True, separators=(",", ":")))
                return {
                    "type": "compound",
                    "logical_op": node["logical_op"],
                    "operands": ops,
                }
            elif "logical_op" in node and "operand" in node:
                return {
                    "type": "unary",
                    "logical_op": node["logical_op"],
                    "operand": self.canonicalize_condition(node["operand"]),
                }
            else:
                return {
                    "type": "predicate",
                    "field": str(node.get("field", "")).strip(),
                    "field_source": node.get("field_source", "auto"),
                    "operator": str(node.get("operator", "EQ")),
                    "value": self._canonicalize_value(node.get("value")),
                }
        else:
            raise ValueError(f"Unsupported condition node type: {type(node)}")

    def canonicalize_expected_behavior(self, exp: ExpectedBehavior) -> dict[str, Any]:
        """Canonicalizes ExpectedBehavior specification."""
        b_type = exp.behavior_type.value if hasattr(exp.behavior_type, "value") else str(exp.behavior_type)
        return {
            "behavior_type": b_type,
            "target_field": exp.target_field,
            "expected_value": self._canonicalize_value(exp.expected_value),
            "expected_status_code": exp.expected_status_code,
            "expected_error_code": exp.expected_error_code,
            "expected_state_mutation": exp.expected_state_mutation,
            "expected_workflow_event": exp.expected_workflow_event,
            "details": {k: self._canonicalize_value(v) for k, v in sorted(exp.details.items())} if exp.details else {},
        }

    def canonicalize_rule(self, rule: BusinessRule) -> dict[str, Any]:
        """Transforms a BusinessRule into a canonical dictionary without timestamps or ephemeral IDs."""
        referenced_dims = [
            d.value if hasattr(d, "value") else str(d)
            for d in rule.referenced_dimensions
        ]
        referenced_dims.sort()

        referenced_fields = sorted(list(set(rule.referenced_fields or self.extract_fields(rule.condition))))

        sev = rule.severity.value if hasattr(rule.severity, "value") else str(rule.severity)
        src = rule.source.value if hasattr(rule.source, "value") else str(rule.source)

        return {
            "name": str(rule.name).strip(),
            "description": str(rule.description or "").strip(),
            "source": src,
            "condition": self.canonicalize_condition(rule.condition),
            "expected_behavior": self.canonicalize_expected_behavior(rule.expected_behavior),
            "scope": rule.scope or "global",
            "referenced_fields": referenced_fields,
            "referenced_dimensions": referenced_dims,
            "severity": sev,
        }

    def compute_rule_fingerprint(self, rule: BusinessRule) -> str:
        """Computes deterministic SHA-256 fingerprint over canonical rule representation."""
        canonical_dict = self.canonicalize_rule(rule)
        canonical_str = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    def extract_fields(self, node: RuleConditionNode) -> list[str]:
        """Extracts all referenced field names from condition AST."""
        fields: set[str] = set()
        if isinstance(node, RulePredicate):
            if node.field:
                fields.add(node.field)
        elif isinstance(node, CompoundRuleCondition):
            for op in node.operands:
                fields.update(self.extract_fields(op))
        elif isinstance(node, UnaryRuleCondition):
            fields.update(self.extract_fields(node.operand))
        elif isinstance(node, dict):
            if "field" in node and node["field"]:
                fields.add(node["field"])
            if "operands" in node and isinstance(node["operands"], list):
                for op in node["operands"]:
                    fields.update(self.extract_fields(op))
            if "operand" in node:
                fields.update(self.extract_fields(node["operand"]))
        return sorted(fields)

    def _canonicalize_value(self, val: Any) -> Any:
        """Recursively canonicalizes primitives and collections."""
        if val is None:
            return None
        if isinstance(val, (int, float, str, bool)):
            return val
        if isinstance(val, (list, tuple, set)):
            return [self._canonicalize_value(item) for item in val]
        if isinstance(val, dict):
            return {k: self._canonicalize_value(v) for k, v in sorted(val.items())}
        return str(val)


rule_normalizer = RuleNormalizer()
