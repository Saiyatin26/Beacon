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
from ingestion.static_analyzer import get_analyzer


def load_source(path: str | Path) -> str:
    return Path(path).read_text()


from common.models import StaticAnalysisResult

def extract_ast_structure(path: str | Path) -> StaticAnalysisResult:
    """Perform real static analysis on source file using static_analyzer module.

    Extracts functions, conditions, comparisons, boolean logic, assignments,
    returns, function calls, and precise source line/column locations.
    """
    file_path = Path(path)
    source_code = file_path.read_text()
    analyzer = get_analyzer("python")
    result = analyzer.analyze(source_code, file_name=file_path.name)
    return result
