"""Stage 1 — Static Source Code Analyzer.

Provides an extensible language-neutral interface (StaticAnalyzer) and concrete
parsers (PythonAnalyzer using built-in AST) to extract functions, conditionals,
comparisons, boolean operations, assignments, returns, function calls, and
precise source line/column locations.
"""

from abc import ABC, abstractmethod
import ast
from pathlib import Path
from typing import Any, Optional

from common.models import (
    AssignmentFact,
    ComparisonFact,
    ConditionFact,
    FunctionCallFact,
    FunctionFact,
    ReturnFact,
    SourceLocation,
    StaticAnalysisResult,
)


class StaticAnalyzer(ABC):
    """Abstract base class for language-specific static analyzers."""

    @abstractmethod
    def analyze(self, source_code: str, file_name: str = "") -> StaticAnalysisResult:
        """Analyze source code text and return a structured StaticAnalysisResult."""
        pass


class PythonAnalyzer(StaticAnalyzer):
    """Python static analyzer using Python's built-in `ast` module."""

    _CMP_OPS = {
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
        ast.In: "in",
        ast.NotIn: "not in",
        ast.Is: "is",
        ast.IsNot: "is not",
    }

    def analyze(self, source_code: str, file_name: str = "") -> StaticAnalysisResult:
        tree = ast.parse(source_code)
        visitor = _PythonASTVisitor(file_name=file_name, source_code=source_code)
        visitor.visit(tree)
        return visitor.result


class _PythonASTVisitor(ast.NodeVisitor):
    _CMP_OPS = {
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
        ast.In: "in",
        ast.NotIn: "not in",
        ast.Is: "is",
        ast.IsNot: "is not",
    }

    def __init__(self, file_name: str, source_code: str):
        self.file_name = file_name
        self.source_code = source_code
        self.current_function: Optional[str] = None

        self.functions: list[FunctionFact] = []
        self.conditions: list[ConditionFact] = []
        self.comparisons: list[ComparisonFact] = []
        self.assignments: list[AssignmentFact] = []
        self.returns: list[ReturnFact] = []
        self.calls: list[FunctionCallFact] = []


    @property
    def result(self) -> StaticAnalysisResult:
        return StaticAnalysisResult(
            file=self.file_name,
            language="python",
            functions=self.functions,
            conditions=self.conditions,
            comparisons=self.comparisons,
            assignments=self.assignments,
            returns=self.returns,
            calls=self.calls,
        )

    def _loc(self, node: ast.AST) -> SourceLocation:
        return SourceLocation(
            file=self.file_name,
            line=getattr(node, "lineno", 0),
            column=getattr(node, "col_offset", None),
            function=self.current_function,
        )

    def _eval_value(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        try:
            return ast.literal_eval(node)
        except Exception:
            return ast.unparse(node)

    def _extract_comparison(self, node: ast.Compare) -> list[ComparisonFact]:
        facts = []
        left_str = ast.unparse(node.left)
        loc = self._loc(node)

        for op_node, comp_node in zip(node.ops, node.comparators):
            op_str = self._CMP_OPS.get(type(op_node), type(op_node).__name__)
            right_val = self._eval_value(comp_node)
            fact = ComparisonFact(
                left=left_str,
                operator=op_str,
                right=right_val,
                location=loc,
            )
            facts.append(fact)
            left_str = ast.unparse(comp_node)

        return facts

    def _extract_condition_fact(self, node: ast.AST) -> ConditionFact:
        loc = self._loc(node)
        expr_str = ast.unparse(node)

        if isinstance(node, ast.BoolOp):
            op_name = "AND" if isinstance(node.op, ast.And) else ("OR" if isinstance(node.op, ast.Or) else type(node.op).__name__)
            sub_facts = [self._extract_condition_fact(val) for val in node.values]
            all_comps = []
            for sub in sub_facts:
                all_comps.extend(sub.comparisons)
            return ConditionFact(
                expression=expr_str,
                logical_operator=op_name,
                comparisons=all_comps,
                sub_conditions=sub_facts,
                location=loc,
            )
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            sub_fact = self._extract_condition_fact(node.operand)
            return ConditionFact(
                expression=expr_str,
                logical_operator="NOT",
                comparisons=sub_fact.comparisons,
                sub_conditions=[sub_fact],
                location=loc,
            )
        elif isinstance(node, ast.Compare):
            comps = self._extract_comparison(node)
            return ConditionFact(
                expression=expr_str,
                logical_operator=None,
                comparisons=comps,
                sub_conditions=[],
                location=loc,
            )
        else:
            return ConditionFact(
                expression=expr_str,
                logical_operator=None,
                comparisons=[],
                sub_conditions=[],
                location=loc,
            )

    def _extract_outcome_from_body(self, body: list[ast.stmt]) -> Optional[str]:
        for stmt in body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == "decision":
                        if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                            return stmt.value.value.upper()
        return None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        prev_func = self.current_function
        self.current_function = node.name
        params = [arg.arg for arg in node.args.args]
        self.functions.append(
            FunctionFact(name=node.name, parameters=params, location=self._loc(node))
        )
        self.generic_visit(node)
        self.current_function = prev_func

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        prev_func = self.current_function
        self.current_function = node.name
        params = [arg.arg for arg in node.args.args]
        self.functions.append(
            FunctionFact(name=node.name, parameters=params, location=self._loc(node))
        )
        self.generic_visit(node)
        self.current_function = prev_func

    def visit_If(self, node: ast.If) -> None:
        cond_fact = self._extract_condition_fact(node.test)
        cond_fact.outcome = self._extract_outcome_from_body(node.body)
        self.conditions.append(cond_fact)

        # Collect top-level comparisons
        for comp in cond_fact.comparisons:
            if comp not in self.comparisons:
                self.comparisons.append(comp)

        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        cond_fact = self._extract_condition_fact(node.test)
        self.conditions.append(cond_fact)
        for comp in cond_fact.comparisons:
            if comp not in self.comparisons:
                self.comparisons.append(comp)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        loc = self._loc(node)
        for target in node.targets:
            target_str = ast.unparse(target)
            val = self._eval_value(node.value)
            self.assignments.append(
                AssignmentFact(target=target_str, value=val, location=loc)
            )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        loc = self._loc(node)
        target_str = ast.unparse(node.target)
        val = self._eval_value(node.value) if node.value else None
        self.assignments.append(
            AssignmentFact(target=target_str, value=val, location=loc)
        )
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        loc = self._loc(node)
        val_str = ast.unparse(node.value) if node.value else "None"
        self.returns.append(ReturnFact(value=val_str, location=loc))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        loc = self._loc(node)
        func_name = ast.unparse(node.func)
        args_strs = [ast.unparse(arg) for arg in node.args]
        self.calls.append(
            FunctionCallFact(function_name=func_name, arguments=args_strs, location=loc)
        )
        self.generic_visit(node)


class CobolAnalyzer(StaticAnalyzer):
    """Static analyzer for COBOL source programs extracting paragraphs and conditional rules."""

    def analyze(self, source_code: str, file_name: str = "") -> StaticAnalysisResult:
        import re
        functions: list[FunctionFact] = []
        conditions: list[ConditionFact] = []
        comparisons: list[ComparisonFact] = []

        current_paragraph: Optional[str] = None
        lines = source_code.splitlines()

        for line_no, raw_line in enumerate(lines, start=1):
            # Clean comments (column 7 '*' or general '*')
            if len(raw_line) >= 7 and raw_line[6] in ("*", "/"):
                continue
            line = raw_line.strip()
            if not line or line.startswith("*"):
                continue

            # Check paragraph header (e.g. 0001-PROCESS-PAYMENT. or PROCESS-PAYMENT.)
            para_match = re.match(r"^([A-Z0-9\-]+)\.\s*$", line, re.IGNORECASE)
            if para_match:
                name = para_match.group(1).upper()
                if not any(div in name for div in ["DIVISION", "SECTION"]):
                    current_paragraph = name
                    functions.append(
                        FunctionFact(
                            name=name,
                            location=SourceLocation(file=file_name, line=line_no, function=name),
                            arguments=[],
                            docstring=None,
                        )
                    )
                continue

            # Check conditionals: IF, EVALUATE, WHEN
            cond_match = re.search(r"\b(IF|EVALUATE|WHEN)\s+(.+?)(?:\s+THEN|\s+ALSO|\.|$)", line, re.IGNORECASE)
            if cond_match:
                keyword = cond_match.group(1).upper()
                expr = cond_match.group(2).strip()
                loc = SourceLocation(file=file_name, line=line_no, function=current_paragraph)
                cond_fact = ConditionFact(
                    expression=expr,
                    logical_operator="AND" if " AND " in expr.upper() else ("OR" if " OR " in expr.upper() else keyword),
                    location=loc,
                )
                conditions.append(cond_fact)

                # Split comparisons if recognizable
                cmp_match = re.search(r"([A-Z0-9\-]+)\s*(=|<|>|<=|>=|EQUAL|GREATER|LESS)\s*([A-Z0-9\-'\"]+)", expr, re.IGNORECASE)
                if cmp_match:
                    comparisons.append(
                        ComparisonFact(
                            left=cmp_match.group(1),
                            operator=cmp_match.group(2),
                            right=cmp_match.group(3),
                            location=loc,
                        )
                    )

        return StaticAnalysisResult(
            file=file_name,
            language="cobol",
            functions=functions,
            conditions=conditions,
            comparisons=comparisons,
            assignments=[],
            returns=[],
            calls=[],
        )


def get_analyzer(language: str = "python") -> StaticAnalyzer:
    """Factory function to get appropriate StaticAnalyzer instance by language name."""
    lang_lower = language.lower()
    if lang_lower in ("python", "py"):
        return PythonAnalyzer()
    if lang_lower in ("cobol", "cbl", "cob", "cpy"):
        return CobolAnalyzer()
    raise NotImplementedError(
        f"Static analyzer for '{language}' is not implemented yet. Supported: 'python', 'cobol'."
    )
