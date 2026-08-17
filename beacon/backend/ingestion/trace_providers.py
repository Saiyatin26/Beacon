"""Stage 1 — Trace Providers.

Establishes the TraceProvider interface with SyntheticTraceProvider and
RuntimeTraceProvider, allowing deterministic synthetic traces and real execution
runtime traces to coexist seamlessly behind a unified interface.
"""

from abc import ABC, abstractmethod
import json
from pathlib import Path
from typing import Callable, Optional

from common.models import TraceEvent
from ingestion.trace_loader import load_traces
from ingestion.runtime_tracer import PythonRuntimeTracer, RuntimeTracer


DEFAULT_BOUNDARY_INPUTS = [
    {"credit_score": 450, "debt_ratio": 0.20, "annual_income": 50000.0},
    {"credit_score": 499, "debt_ratio": 0.50, "annual_income": 45000.0},
    {"credit_score": 550, "debt_ratio": 0.50, "annual_income": 50000.0},
    {"credit_score": 580, "debt_ratio": 0.47, "annual_income": 50000.0},
    {"credit_score": 599, "debt_ratio": 0.41, "annual_income": 45000.0},
    {"credit_score": 600, "debt_ratio": 0.50, "annual_income": 45000.0},
    {"credit_score": 601, "debt_ratio": 0.50, "annual_income": 45000.0},
    {"credit_score": 650, "debt_ratio": 0.30, "annual_income": 60000.0},
    {"credit_score": 750, "debt_ratio": 0.20, "annual_income": 90000.0},
    {"credit_score": 520, "debt_ratio": 0.45, "annual_income": 15000.0},
]


class TraceProvider(ABC):
    """Abstract base class for trace providers."""

    @abstractmethod
    def get_traces(self) -> list[TraceEvent]:
        """Return a list of uniform TraceEvent objects."""
        pass


class SyntheticTraceProvider(TraceProvider):
    """Loads or generates deterministic synthetic trace records."""

    def __init__(self, trace_file_path: Optional[str | Path] = None):
        self.trace_file_path = Path(trace_file_path) if trace_file_path else None

    def get_traces(self) -> list[TraceEvent]:
        if self.trace_file_path and self.trace_file_path.exists():
            return load_traces(self.trace_file_path)
        else:
            # Fallback to generating traces dynamically
            from generate_traces import generate_traces
            raw_traces = generate_traces()
            return [TraceEvent(inputs=r["inputs"], output=r["output"]) for r in raw_traces]


class RuntimeTraceProvider(TraceProvider):
    """Executes target Python function dynamically and records runtime execution traces."""

    def __init__(
        self,
        target_func: Callable,
        inputs_batch: Optional[list[dict]] = None,
        tracer: Optional[RuntimeTracer] = None,
    ):
        self.target_func = target_func
        self.inputs_batch = inputs_batch if inputs_batch is not None else DEFAULT_BOUNDARY_INPUTS
        self.tracer = tracer or PythonRuntimeTracer()

    def get_traces(self) -> list[TraceEvent]:
        return self.tracer.trace_batch(self.target_func, self.inputs_batch)
