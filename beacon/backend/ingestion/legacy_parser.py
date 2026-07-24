"""Stage 1 — legacy source parsing.

For the demo, source is Python (legacy_sample/legacy_loan_approval.py), so we
just read it as text — the candidate generator (Stage 2a) gets the raw source
directly and the LLM does the structural reasoning itself.

For a real COBOL/Java target, this is where a tree-sitter grammar would parse
the source into an AST and extract conditionals/branches/call graph
structurally, feeding that structure alongside the trace log into Stage 2a
instead of raw text. Left as a TODO since setting up a COBOL grammar is out of
scope for the demo (architecture doc Section 5, 'Legacy parsing' row).
"""

from pathlib import Path


def load_source(path: str | Path) -> str:
    return Path(path).read_text()


def extract_ast_structure(path: str | Path) -> dict:
    """TODO: real implementation would use tree-sitter to extract conditionals,
    control flow, and call graph. Returns a placeholder for now — Stage 2a
    works fine on raw source text alone for the demo's scope."""
    return {"note": "AST structure extraction not implemented for demo scope; see docstring."}
