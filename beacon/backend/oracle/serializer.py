"""Deterministic Canonical Serializer and Cryptographic Hasher for Phase 8 Oracle DSL."""

import hashlib
import json
from typing import Any, Optional


def canonicalize_ast_dict(node: Any) -> Any:
    """Recursively normalizes AST nodes so that commutative operands (AND, OR)
    are sorted canonically, and nested dictionaries are sorted.
    """
    if isinstance(node, dict):
        canonical_dict: dict[str, Any] = {}
        # Special handling for commutative compound conditions
        if node.get("type") in ("AND", "OR") and "operands" in node:
            operands = [canonicalize_ast_dict(op) for op in node["operands"]]
            # Sort operands deterministically by their serialized JSON representation
            operands.sort(key=lambda x: json.dumps(x, sort_keys=True, separators=(",", ":")))
            canonical_dict["type"] = node["type"]
            canonical_dict["operands"] = operands
        else:
            for k in sorted(node.keys()):
                canonical_dict[k] = canonicalize_ast_dict(node[k])
        return canonical_dict
    elif isinstance(node, list):
        return [canonicalize_ast_dict(item) for item in node]
    else:
        return node


def serialize_canonical_oracle(
    condition_dict: dict[str, Any],
    consequence_dict: dict[str, Any],
    input_schema_dict: Optional[dict[str, Any]] = None,
    output_schema_dict: Optional[dict[str, Any]] = None,
    domain: str = "business_logic",
) -> str:
    """Produces a deterministic, whitespace-normalized, sorted JSON representation
    of the canonical oracle definition.
    """
    canonical_payload = {
        "domain": domain,
        "condition": canonicalize_ast_dict(condition_dict),
        "consequence": canonicalize_ast_dict(consequence_dict),
    }
    if input_schema_dict:
        canonical_payload["input_schema"] = canonicalize_ast_dict(input_schema_dict)
    if output_schema_dict:
        canonical_payload["output_schema"] = canonicalize_ast_dict(output_schema_dict)

    return json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))


def compute_content_hash(canonical_json: str) -> str:
    """Computes a SHA-256 cryptographic hash over the canonical JSON string."""
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compute_oracle_set_hash(oracle_hashes: list[str]) -> str:
    """Computes a composite SHA-256 hash over a sorted set of individual oracle hashes."""
    sorted_hashes = sorted(list(set(h.strip() for h in oracle_hashes if h.strip())))
    combined = ":".join(sorted_hashes)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()
