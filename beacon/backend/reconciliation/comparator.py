"""BEACON V2 — Phase 7 Semantic Rule Comparator.

Performs pairwise semantic comparison between normalized rules to classify relationships:
EQUIVALENT, DUPLICATE, COMPATIBLE, SPECIALIZATION, GENERALIZATION, CONFLICT, INDEPENDENT.
"""

from typing import Any, Optional
from .models import RuleRelationship
from .normalizer import NormalizedRuleRepresentation, compute_deterministic_hash


class RuleComparator:
    """Evaluates semantic compatibility and conflict between normalized behavioral rules."""

    def compare_rules(
        self,
        rule_a: NormalizedRuleRepresentation,
        rule_b: NormalizedRuleRepresentation,
    ) -> tuple[RuleRelationship, str]:
        """Compares two normalized rules and returns their relationship classification and detailed rationale."""
        # 1. Exact canonical expression match & exact role match
        if rule_a.canonical_expression == rule_b.canonical_expression and rule_a.role_scope == rule_b.role_scope:
            return RuleRelationship.EQUIVALENT, "Exact match of canonical expression, rule type, and role scope."

        # 2. Check for Role Scope isolation
        if rule_a.role_scope != rule_b.role_scope and rule_a.role_scope != "both" and rule_b.role_scope != "both":
            # Different application scopes (e.g. reference vs target)
            if rule_a.canonical_expression == rule_b.canonical_expression:
                return RuleRelationship.COMPATIBLE, "Identical behavioral rule applying to different role scopes (Reference vs Target)."

        # 3. Analyze condition overlap and consequence consistency
        cond_rel = self._compare_conditions(rule_a.normalized_conditions, rule_b.normalized_conditions)
        exp_rel = self._compare_expected_behaviors(rule_a.normalized_expected_behavior, rule_b.normalized_expected_behavior)

        # 4. Same condition context with conflicting outcomes -> CONFLICT
        if cond_rel in ("SAME", "EQUIVALENT") and exp_rel == "CONFLICT":
            reason = (
                f"Conflicting outcomes for identical condition: "
                f"Rule '{rule_a.source_id}' expects {rule_a.normalized_expected_behavior} whereas "
                f"Rule '{rule_b.source_id}' expects {rule_b.normalized_expected_behavior}."
            )
            return RuleRelationship.CONFLICT, reason

        # 5. One rule is a specialization (narrower condition) with distinct or compatible outcome
        if cond_rel == "A_SPECIALIZES_B":
            return RuleRelationship.SPECIALIZATION, (
                f"Rule '{rule_a.source_id}' specializes Rule '{rule_b.source_id}' with additional constraints."
            )
        if cond_rel == "B_SPECIALIZES_A":
            return RuleRelationship.GENERALIZATION, (
                f"Rule '{rule_a.source_id}' generalizes Rule '{rule_b.source_id}' with broader applicability."
            )

        # 6. Equivalent conditions and compatible outcomes
        if cond_rel in ("SAME", "EQUIVALENT") and exp_rel in ("SAME", "EQUIVALENT", "COMPATIBLE"):
            return RuleRelationship.EQUIVALENT, "Semantically equivalent condition and expected behavior."

        # 7. Disjoint / Independent rules
        if cond_rel == "DISJOINT":
            return RuleRelationship.INDEPENDENT, "Rules operate on disjoint condition fields."

        return RuleRelationship.COMPATIBLE, "Rules operate on compatible, non-conflicting behavioral scopes."

    def _compare_conditions(self, cond_a: dict[str, Any], cond_b: dict[str, Any]) -> str:
        """Determines if condition A and B are SAME, A_SPECIALIZES_B, B_SPECIALIZES_A, or DISJOINT."""
        if not cond_a and not cond_b:
            return "SAME"
        if not cond_a and cond_b:
            return "B_SPECIALIZES_A"  # B has constraints, A has none (universal)
        if cond_a and not cond_b:
            return "A_SPECIALIZES_B"  # A has constraints, B has none (universal)

        # Hash comparison
        if compute_deterministic_hash(cond_a) == compute_deterministic_hash(cond_b):
            return "SAME"

        # Check atomic predicates
        pred_a = self._extract_predicates(cond_a)
        pred_b = self._extract_predicates(cond_b)

        set_a = {(p.get("field"), p.get("operator"), str(p.get("value"))) for p in pred_a}
        set_b = {(p.get("field"), p.get("operator"), str(p.get("value"))) for p in pred_b}

        if set_a == set_b:
            return "SAME"
        if set_a.issuperset(set_b) and len(set_a) > len(set_b):
            return "A_SPECIALIZES_B"
        if set_b.issuperset(set_a) and len(set_b) > len(set_a):
            return "B_SPECIALIZES_A"

        fields_a = {p.get("field") for p in pred_a if p.get("field")}
        fields_b = {p.get("field") for p in pred_b if p.get("field")}

        if not fields_a.intersection(fields_b):
            return "DISJOINT"

        return "OVERLAPPING"

    def _extract_predicates(self, cond: dict[str, Any]) -> list[dict[str, Any]]:
        """Flattens compound condition trees into list of atomic predicates."""
        if not cond:
            return []
        t = cond.get("type")
        if t == "predicate":
            return [cond]
        elif t == "compound":
            res: list[dict[str, Any]] = []
            for op in cond.get("operands", []):
                res.extend(self._extract_predicates(op))
            return res
        elif t == "unary":
            return self._extract_predicates(cond.get("operand", {}))
        return [cond]

    def _compare_expected_behaviors(self, exp_a: dict[str, Any], exp_b: dict[str, Any]) -> str:
        """Determines if expected behaviors are SAME, CONFLICT, or COMPATIBLE."""
        if not exp_a and not exp_b:
            return "SAME"
        if compute_deterministic_hash(exp_a) == compute_deterministic_hash(exp_b):
            return "SAME"

        btype_a = exp_a.get("behavior_type")
        btype_b = exp_b.get("behavior_type")

        # Check for direct conflict on same target field
        if btype_a == "RETURN_VALUE" and btype_b == "RETURN_VALUE":
            tf_a = exp_a.get("target_field")
            tf_b = exp_b.get("target_field")
            if tf_a == tf_b:
                val_a = exp_a.get("expected_value")
                val_b = exp_b.get("expected_value")
                if val_a != val_b:
                    return "CONFLICT"
                return "SAME"

        # Check status conflicts (ACCEPT vs REJECT)
        if {btype_a, btype_b} == {"ACCEPT", "REJECT"}:
            return "CONFLICT"

        # Check state mutation conflicts
        if exp_a.get("expected_state_mutation") is not None and exp_b.get("expected_state_mutation") is not None:
            if exp_a["expected_state_mutation"] != exp_b["expected_state_mutation"]:
                return "CONFLICT"

        return "COMPATIBLE"


rule_comparator = RuleComparator()
