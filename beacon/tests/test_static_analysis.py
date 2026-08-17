"""Unit tests for Phase 3 static analysis engine."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))

from ingestion.legacy_parser import extract_ast_structure
from ingestion.static_analyzer import PythonAnalyzer, get_analyzer
from common.models import StaticAnalysisResult


def test_simple_comparison_extraction():
    code = """
def check(credit_score):
    if credit_score < 500:
        return "REJECT"
"""
    analyzer = PythonAnalyzer()
    res = analyzer.analyze(code, "test.py")

    assert len(res.functions) == 1
    assert res.functions[0].name == "check"

    assert len(res.conditions) == 1
    cond = res.conditions[0]
    assert cond.logical_operator is None
    assert len(cond.comparisons) == 1

    comp = cond.comparisons[0]
    assert comp.left == "credit_score"
    assert comp.operator == "<"
    assert comp.right == 500
    assert comp.location.line == 3
    assert comp.location.function == "check"


def test_and_condition_extraction():
    code = """
def evaluate(credit_score, debt_ratio):
    if credit_score < 600 and debt_ratio > 0.4:
        decision = "REJECT"
"""
    analyzer = PythonAnalyzer()
    res = analyzer.analyze(code, "test.py")

    assert len(res.conditions) == 1
    cond = res.conditions[0]
    assert cond.logical_operator == "AND"
    assert len(cond.sub_conditions) == 2

    # Check extracted sub-comparisons
    lefts = [c.left for c in cond.comparisons]
    ops = [c.operator for c in cond.comparisons]
    rights = [c.right for c in cond.comparisons]

    assert "credit_score" in lefts
    assert "debt_ratio" in lefts
    assert "<" in ops
    assert ">" in ops
    assert 600 in rights
    assert 0.4 in rights
    assert cond.outcome == "REJECT"


def test_or_condition_extraction():
    code = """
def check_income(annual_income, debt_ratio):
    if annual_income < 20000 or debt_ratio > 0.6:
        return "REJECT"
"""
    analyzer = PythonAnalyzer()
    res = analyzer.analyze(code, "test.py")

    assert len(res.conditions) == 1
    cond = res.conditions[0]
    assert cond.logical_operator == "OR"
    assert len(cond.sub_conditions) == 2


def test_not_condition_extraction():
    code = """
def validate(credit_score):
    if not (credit_score >= 600):
        decision = "REJECT"
"""
    analyzer = PythonAnalyzer()
    res = analyzer.analyze(code, "test.py")

    assert len(res.conditions) == 1
    cond = res.conditions[0]
    assert cond.logical_operator == "NOT"
    assert len(cond.sub_conditions) == 1


def test_nested_condition_extraction():
    code = """
def outer(a, b):
    if a > 10:
        if b < 5:
            return True
"""
    analyzer = PythonAnalyzer()
    res = analyzer.analyze(code, "test.py")

    assert len(res.conditions) == 2
    assert res.conditions[0].comparisons[0].left == "a"
    assert res.conditions[1].comparisons[0].left == "b"


def test_assignment_extraction():
    code = """
x = 100
decision = "APPROVE"
"""
    analyzer = PythonAnalyzer()
    res = analyzer.analyze(code, "test.py")

    targets = [a.target for a in res.assignments]
    values = [a.value for a in res.assignments]

    assert "x" in targets
    assert 100 in values
    assert "decision" in targets
    assert "APPROVE" in values


def test_return_statement_extraction():
    code = """
def fn():
    return {"decision": "REJECT"}
"""
    analyzer = PythonAnalyzer()
    res = analyzer.analyze(code, "test.py")

    assert len(res.returns) == 1
    assert "decision" in res.returns[0].value
    assert res.returns[0].location.line == 3


def test_function_call_extraction():
    code = """
def process():
    result = evaluate_loan(598, 0.45, 50000)
"""
    analyzer = PythonAnalyzer()
    res = analyzer.analyze(code, "test.py")

    assert len(res.calls) == 1
    call = res.calls[0]
    assert call.function_name == "evaluate_loan"
    assert call.arguments == ["598", "0.45", "50000"]


def test_multiple_functions_extraction():
    code = """
def helper(x):
    return x * 2

def main_fn(y):
    return helper(y)
"""
    analyzer = PythonAnalyzer()
    res = analyzer.analyze(code, "test.py")

    assert len(res.functions) == 2
    names = [f.name for f in res.functions]
    assert "helper" in names
    assert "main_fn" in names


def test_source_line_tracking():
    code = """line1 = 1
line2 = 2
if line1 < line2:
    pass
"""
    analyzer = PythonAnalyzer()
    res = analyzer.analyze(code, "sample.py")

    assert res.assignments[0].location.line == 1
    assert res.assignments[1].location.line == 2
    assert res.conditions[0].location.line == 3


def test_legacy_loan_approval_extraction_acceptance():
    """Phase 3 Acceptance Test: extract all mandatory comparisons from legacy_loan_approval.py."""
    sample_path = ROOT / "legacy_sample" / "legacy_loan_approval.py"
    ast_dict = extract_ast_structure(sample_path)

    # Validate output is structured data matching StaticAnalysisResult model
    parsed_res = StaticAnalysisResult.model_validate(ast_dict)
    assert parsed_res.language == "python"
    assert len(parsed_res.functions) == 1
    assert parsed_res.functions[0].name == "evaluate_loan"

    # Verify extracted comparisons
    all_comps = parsed_res.comparisons
    extracted_patterns = [(c.left, c.operator, c.right) for c in all_comps]

    # Required extractions:
    # 1. credit_score < 500
    # 2. credit_score < 600
    # 3. debt_ratio > 0.4
    # 4. annual_income < 20000
    # 5. debt_ratio > 0.6
    assert ("credit_score", "<", 500) in extracted_patterns
    assert ("credit_score", "<", 600) in extracted_patterns
    assert ("debt_ratio", ">", 0.4) in extracted_patterns
    assert ("annual_income", "<", 20000) in extracted_patterns
    assert ("debt_ratio", ">", 0.6) in extracted_patterns

    # Check logical relationships in extracted conditions
    and_conditions = [cond for cond in parsed_res.conditions if cond.logical_operator == "AND"]
    assert len(and_conditions) >= 2  # (credit_score < 600 and debt_ratio > 0.4) & (annual_income < 20000 and debt_ratio > 0.6)
