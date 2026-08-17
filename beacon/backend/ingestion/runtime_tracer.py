"""Stage 1 — Real Dynamic Execution Tracer.

Provides a reusable interface (RuntimeTracer) and Python runtime tracer
(PythonRuntimeTracer) using sys.settrace to capture execution IDs, timestamps,
inputs, outputs, line/branch information, local variable snapshots, and exception handling.
All condition extraction is generic and AST-driven — no hardcoded domain fields.
"""

from abc import ABC, abstractmethod
import ast
from datetime import datetime, timezone
import inspect
import sys
import uuid
from typing import Any, Callable, Optional

from common.dsl_eval import eval_condition
from common.models import TraceEvent


def _extract_function_conditions(func: Callable) -> list[str]:
    """Extract boolean condition and comparison expressions from func's AST without hardcoding domain fields."""
    try:
        source = inspect.getsource(func)
        tree = ast.parse(source)
        conditions: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Compare, ast.BoolOp)):
                expr = ast.unparse(node)
                if expr and expr not in conditions:
                    conditions.append(expr)
        return conditions
    except Exception:
        return []


class RuntimeTracer(ABC):
    """Abstract base class for language-specific runtime execution tracers."""

    @abstractmethod
    def trace_execution(
        self, func: Callable, inputs: dict, execution_id: Optional[str] = None
    ) -> TraceEvent:
        """Trace a single execution of a target function with given inputs."""
        pass

    @abstractmethod
    def trace_batch(
        self, func: Callable, batch_inputs: list[dict]
    ) -> list[TraceEvent]:
        """Trace a batch of executions across multiple input dicts."""
        pass


class PythonRuntimeTracer(RuntimeTracer):
    """Python dynamic tracer using `sys.settrace` to record execution events."""

    def __init__(
        self,
        capture_variables: bool = True,
        capture_branches: bool = True,
        monitored_conditions: Optional[list[str]] = None,
    ):
        self.capture_variables = capture_variables
        self.capture_branches = capture_branches
        self.monitored_conditions = monitored_conditions
        self._execution_count = 0

    def trace_execution(
        self, func: Callable, inputs: dict, execution_id: Optional[str] = None
    ) -> TraceEvent:
        self._execution_count += 1
        exec_id = execution_id or f"EX-{self._execution_count:03d}"
        timestamp = datetime.now(timezone.utc).isoformat()
        func_name = getattr(func, "__name__", "unknown_func")

        branch_path: list[str] = []
        executed_branches: list[dict] = []
        variable_states: list[dict] = []
        output_res: dict = {}
        exception_str: Optional[str] = None

        target_code = getattr(func, "__code__", None)
        target_conditions = (
            self.monitored_conditions
            if self.monitored_conditions is not None
            else _extract_function_conditions(func)
        )

        def trace_func(frame, event, arg):
            # Only trace code executing inside the target function body
            if target_code and frame.f_code is not target_code:
                return trace_func

            line_no = frame.f_lineno
            branch_path.append(f"line_{line_no}")

            # Capture variable state snapshot
            if self.capture_variables:
                local_vars = {
                    k: v for k, v in frame.f_locals.items()
                    if isinstance(v, (int, float, str, bool, dict, list, type(None)))
                }
                variable_states.append({
                    "function": func_name,
                    "line": line_no,
                    "variables": dict(local_vars),
                })

                # Evaluated branch condition checking based on discovered AST conditions
                if self.capture_branches and target_conditions:
                    branch_info: dict[str, Any] = {"line": line_no}
                    for cond_expr in target_conditions:
                        try:
                            res = eval_condition(cond_expr, local_vars)
                            branch_info[cond_expr] = res
                        except Exception:
                            pass

                    # Store structural branch record if non-empty evaluations exist
                    if len(branch_info) > 1:
                        if not executed_branches or executed_branches[-1].get("line") != line_no:
                            executed_branches.append(branch_info)

            return trace_func

        old_trace = sys.gettrace()
        try:
            sys.settrace(trace_func)
            raw_output = func(**inputs)
            if isinstance(raw_output, dict):
                output_res = raw_output
            else:
                output_res = {"result": raw_output}
        except Exception as exc:
            exception_str = f"{type(exc).__name__}: {str(exc)}"
            output_res = {"error": exception_str}
        finally:
            sys.settrace(old_trace)

        return TraceEvent(
            execution_id=exec_id,
            timestamp=timestamp,
            function=func_name,
            inputs=inputs,
            output=output_res,
            branch_path=branch_path,
            executed_branches=executed_branches,
            variable_states=variable_states,
            exception=exception_str,
        )

    def trace_batch(
        self, func: Callable, batch_inputs: list[dict]
    ) -> list[TraceEvent]:
        return [self.trace_execution(func, inp) for inp in batch_inputs]
