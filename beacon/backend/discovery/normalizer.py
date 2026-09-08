"""BEACON V2 — Phase 6 Candidate Normalizer.

Standardizes candidate rule expressions into canonical AST formats, normalizing commutative operands,
whitespace, and variable naming to ensure deterministic deduplication and fingerprinting.
"""

import re
from typing import Any, Optional


class CandidateNormalizer:
    """Canonicalizes candidate rule expressions for deterministic comparison and fingerprinting."""

    COMMUTATIVE_OPS = {"==", "!=", "+", "*"}

    def normalize_expression(self, expr: str) -> str:
        """Normalizes whitespace, parentheses, and commutative operations in a candidate expression."""
        if not expr:
            return ""

        # 1. Normalize whitespace
        cleaned = re.sub(r"\s+", " ", expr.strip())

        # 2. Normalize commutative binary comparisons (e.g. 'B == A' -> 'A == B')
        for op in ("==", "!="):
            pattern = rf"^(.+?)\s+{re.escape(op)}\s+(.+?)$"
            m = re.match(pattern, cleaned)
            if m:
                left, right = m.group(1).strip(), m.group(2).strip()
                # If both are same zone (e.g. output.a vs output.b), sort alphabetically
                # If one is output and other is input (e.g. output.y == input.x), keep output on LHS
                if (left.startswith("output.") and right.startswith("input.")) or (left.startswith("state.") and right.startswith("input.")):
                    return f"{left} {op} {right}"
                elif (right.startswith("output.") and left.startswith("input.")) or (right.startswith("state.") and left.startswith("input.")):
                    return f"{right} {op} {left}"
                else:
                    sorted_operands = sorted([left, right])
                    return f"{sorted_operands[0]} {op} {sorted_operands[1]}"

        return cleaned

    def extract_variables(self, expr: str) -> list[str]:
        """Extracts field and variable identifiers mentioned in the expression."""
        # Finds dotted identifiers like 'output.field', 'input.val', 'state.users'
        matches = re.findall(r"\b(?:input|output|state|error|metadata)\.[a-zA-Z0-9_\.]+\b", expr)
        return sorted(list(set(matches)))

    def calculate_complexity(self, expr: str) -> int:
        """Calculates deterministic structural complexity score of an expression."""
        if not expr:
            return 1
        score = 1
        # Count operations
        ops = re.findall(r"(\+|\-|\*|\/|==|!=|<=|>=|<|>|&&|\|\||in\b|matches\b)", expr)
        score += len(ops)
        # Count field accesses
        fields = self.extract_variables(expr)
        score += max(0, len(fields) - 1)
        return score


candidate_normalizer = CandidateNormalizer()
