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


class TraceProvider(ABC):
    """Abstract base class for trace providers."""

    @abstractmethod
    def get_traces(self) -> list[TraceEvent]:
        """Return a list of uniform TraceEvent objects."""
        pass


class SyntheticTraceProvider(TraceProvider):
    """Loads verifiable trace records from a provided trace file."""

    def __init__(self, trace_file_path: Optional[str | Path] = None):
        self.trace_file_path = Path(trace_file_path) if trace_file_path else None

    def get_traces(self) -> list[TraceEvent]:
        if self.trace_file_path and self.trace_file_path.exists():
            return load_traces(self.trace_file_path)
        raise FileNotFoundError(f"Trace file not found: {self.trace_file_path}")


class RuntimeTraceProvider(TraceProvider):
    """Executes target Python function dynamically and records runtime execution traces."""

    def __init__(
        self,
        target_func: Callable,
        inputs_batch: Optional[list[dict]] = None,
        tracer: Optional[RuntimeTracer] = None,
    ):
        self.target_func = target_func
        self.inputs_batch = inputs_batch or []
        self.tracer = tracer or PythonRuntimeTracer()

    def get_traces(self) -> list[TraceEvent]:
        if not self.inputs_batch:
            return []
        return self.tracer.trace_batch(self.target_func, self.inputs_batch)
