"""Phase 9 — Implementation Adapter Abstraction and Output Normalization.

Wraps legacy and modernized implementations behind a generic execution interface,
producing structured Observations with raw and normalized inputs/outputs.
"""

from abc import ABC, abstractmethod
import logging
import time
from typing import Any, Callable, Optional

from .models import Observation

logger = logging.getLogger(__name__)


def default_output_normalizer(raw_output: Any) -> dict[str, Any]:
    """Normalizes output dictionary or scalar into a standardized dictionary representation.
    Preserves raw semantics while normalizing string casing/whitespace.
    """
    if isinstance(raw_output, dict):
        normalized: dict[str, Any] = {}
        for k, v in raw_output.items():
            if isinstance(v, str):
                normalized[k] = v.strip().upper()
            else:
                normalized[k] = v
        return normalized
    elif raw_output is not None:
        # Wrap scalar output as {"decision": normalized_value}
        val = raw_output.strip().upper() if isinstance(raw_output, str) else raw_output
        return {"decision": val}
    else:
        return {}


def default_input_normalizer(raw_inputs: dict[str, Any]) -> dict[str, Any]:
    """Normalizes input variables into standard formats."""
    normalized: dict[str, Any] = {}
    for k, v in raw_inputs.items():
        if isinstance(v, (int, float, bool)):
            normalized[k] = v
        elif isinstance(v, str):
            # Try parsing integer or float if appropriate
            v_clean = v.strip()
            if v_clean.isdigit():
                normalized[k] = int(v_clean)
            else:
                try:
                    normalized[k] = float(v_clean)
                except ValueError:
                    normalized[k] = v_clean
        else:
            normalized[k] = v
    return normalized


class ImplementationAdapter(ABC):
    """Abstract Base Class for implementation target runners (Python, Java, Rust, REST, etc.)."""

    name: str = "base_adapter"
    version: str = "1.0.0"
    role: str = "target"

    @abstractmethod
    def execute(self, inputs: dict[str, Any], input_id: str = "") -> Observation:
        """Executes the implementation on the provided inputs and returns a structured Observation."""
        pass


class FunctionAdapter(ImplementationAdapter):
    """Executes a Python callable function with latency tracking and exception isolation."""

    def __init__(
        self,
        target_fn: Callable[..., Any],
        name: str = "python_function",
        version: str = "1.0.0",
        role: str = "target",
        input_normalizer: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
        output_normalizer: Optional[Callable[[Any], dict[str, Any]]] = None,
    ):
        self.target_fn = target_fn
        self.name = name
        self.version = version
        self.role = role
        self.input_normalizer = input_normalizer or default_input_normalizer
        self.output_normalizer = output_normalizer or default_output_normalizer

    def execute(self, inputs: dict[str, Any], input_id: str = "") -> Observation:
        raw_inputs = dict(inputs)
        norm_inputs = self.input_normalizer(raw_inputs)

        start_time = time.perf_counter()
        try:
            raw_output = self.target_fn(**norm_inputs)
            latency_ms = round((time.perf_counter() - start_time) * 1000, 3)

            raw_out_dict = raw_output if isinstance(raw_output, dict) else {"decision": raw_output}
            norm_out_dict = self.output_normalizer(raw_output)

            return Observation(
                input_id=input_id,
                raw_inputs=raw_inputs,
                normalized_inputs=norm_inputs,
                raw_outputs=raw_out_dict,
                normalized_outputs=norm_out_dict,
                execution_status="SUCCESS",
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=latency_ms,
                provenance={"role": self.role},
            )

        except Exception as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 3)
            logger.warning(f"Adapter '{self.name}' exception on input #{input_id}: {exc}")
            return Observation(
                input_id=input_id,
                raw_inputs=raw_inputs,
                normalized_inputs=norm_inputs,
                raw_outputs={},
                normalized_outputs={},
                execution_status="EXCEPTION",
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=latency_ms,
                error_message=str(exc),
                provenance={"role": self.role},
            )


class LegacyAdapter(FunctionAdapter):
    """Specialized adapter for legacy reference implementation."""

    def __init__(self, target_fn: Callable[..., Any], name: str = "legacy_reference", version: str = "1.0.0", **kwargs):
        super().__init__(target_fn=target_fn, name=name, version=version, role="legacy", **kwargs)


class ModernizedAdapter(FunctionAdapter):
    """Specialized adapter for modernized candidate implementation."""

    def __init__(self, target_fn: Callable[..., Any], name: str = "modernized_candidate", version: str = "2.0.0", **kwargs):
        super().__init__(target_fn=target_fn, name=name, version=version, role="modernized", **kwargs)
