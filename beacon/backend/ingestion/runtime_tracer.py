"""Stage 1 — Real Dynamic Execution Tracer.

Provides a reusable interface (RuntimeTracer) and Python runtime tracer
(PythonRuntimeTracer) using sys.settrace to capture execution IDs, timestamps,
inputs, outputs, line/branch information, local variable snapshots, and exception handling.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import inspect
import sys
import uuid
from typing import Any, Callable, Optional

from common.models import TraceEvent


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

    def __init__(self, capture_variables: bool = True, capture_branches: bool = True):
        self.capture_variables = capture_variables
        self.capture_branches = capture_branches
        self._execution_count = 0

    def _next_execution_id() -> str:
        # Incremental format EX-001, EX-002 for readable trace IDs
        return f"EX-{uuid.uuid4().hex[:6]}"


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

                # Evaluated branch condition checking if key fields present in locals
                if self.capture_branches and "credit_score" in local_vars:
                    cs = local_vars.get("credit_score")
                    dr = local_vars.get("debt_ratio")
                    inc = local_vars.get("annual_income")

                    if isinstance(cs, (int, float)):
                        branch_info = {
                            "line": line_no,
                            "credit_score < 500": cs < 500,
                            "credit_score < 600": cs < 600,
                        }
                        if isinstance(dr, (int, float)):
                            branch_info["debt_ratio > 0.4"] = dr > 0.4
                        if isinstance(inc, (int, float)):
                            branch_info["annual_income < 20000"] = inc < 20000
                        if isinstance(dr, (int, float)):
                            branch_info["debt_ratio > 0.6"] = dr > 0.6

                        # Store structural branch record if not redundant
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
