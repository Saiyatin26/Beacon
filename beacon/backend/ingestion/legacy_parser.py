"""Legacy AST parser module."""

from pathlib import Path
from ingestion.static_analyzer import get_analyzer
from common.models import StaticAnalysisResult


def load_source(path: str | Path) -> str:
    return Path(path).read_text()


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
