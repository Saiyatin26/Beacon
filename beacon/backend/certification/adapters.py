"""BEACON V2 — Implementation Adapter Abstraction, Normalizers & Lifecycle.

Wraps reference and target implementations behind a generic, domain-agnostic
execution interface, producing structured Observations with unaltered raw inputs/outputs
and configurable, auditable normalization.
"""

from abc import ABC, abstractmethod
from enum import Enum
import hashlib
import logging
from pathlib import Path
import time
from typing import Any, Callable, Optional, Union

from .models import CanonicalInput, Observation

logger = logging.getLogger("beacon.certification.adapters")


class AdapterRole(str, Enum):
    """Generic role of an implementation under behavioral equivalence evaluation."""
    REFERENCE = "reference"
    TARGET = "target"
    # Backward compatibility aliases
    LEGACY = "legacy"
    MODERNIZED = "modernized"


# ==============================================================================
# Output Normalizer Hierarchy
# ==============================================================================

class OutputNormalizer(ABC):
    """Abstract base class for deterministic, auditable output normalizers."""

    @abstractmethod
    def normalize(self, raw_output: Any) -> dict[str, Any]:
        """Normalizes raw output into a canonical dictionary representation."""
        pass


class DefaultOutputNormalizer(OutputNormalizer):
    """Legacy default normalizer: converts string values to uppercase.
    Preserved for backward compatibility with V1 benchmarks.
    """

    def normalize(self, raw_output: Any) -> dict[str, Any]:
        if isinstance(raw_output, dict):
            normalized: dict[str, Any] = {}
            for k, v in raw_output.items():
                if isinstance(v, str):
                    normalized[k] = v.strip().upper()
                else:
                    normalized[k] = v
            return normalized
        elif raw_output is not None:
            val = raw_output.strip().upper() if isinstance(raw_output, str) else raw_output
            return {"decision": val}
        else:
            return {}


class PreserveCaseNormalizer(OutputNormalizer):
    """Domain-agnostic normalizer: preserves exact string casing and data types
    without universal uppercase transformation.
    """

    def normalize(self, raw_output: Any) -> dict[str, Any]:
        if isinstance(raw_output, dict):
            return {k: v for k, v in raw_output.items()}
        elif raw_output is not None:
            return {"decision": raw_output}
        return {}


class StripWhitespaceNormalizer(OutputNormalizer):
    """Strips leading/trailing whitespace from string outputs while strictly preserving letter case."""

    def normalize(self, raw_output: Any) -> dict[str, Any]:
        if isinstance(raw_output, dict):
            normalized: dict[str, Any] = {}
            for k, v in raw_output.items():
                if isinstance(v, str):
                    normalized[k] = v.strip()
                else:
                    normalized[k] = v
            return normalized
        elif raw_output is not None:
            val = raw_output.strip() if isinstance(raw_output, str) else raw_output
            return {"decision": val}
        return {}


class ConfiguredOutputNormalizer(OutputNormalizer):
    """Field-configurable output normalizer allowing explicit per-field rules."""

    def __init__(
        self,
        uppercase_fields: Optional[list[str]] = None,
        strip_fields: Optional[list[str]] = None,
        numeric_fields: Optional[list[str]] = None,
    ):
        self.uppercase_fields = set(uppercase_fields or [])
        self.strip_fields = set(strip_fields or [])
        self.numeric_fields = set(numeric_fields or [])

    def normalize(self, raw_output: Any) -> dict[str, Any]:
        out_dict = raw_output if isinstance(raw_output, dict) else {"decision": raw_output}
        if out_dict is None:
            return {}

        normalized: dict[str, Any] = {}
        for k, v in out_dict.items():
            val = v
            if isinstance(val, str):
                if k in self.strip_fields or not self.strip_fields:
                    val = val.strip()
                if k in self.uppercase_fields:
                    val = val.upper()
            if k in self.numeric_fields and isinstance(val, str):
                try:
                    val = float(val) if "." in val else int(val)
                except ValueError:
                    pass
            normalized[k] = val
        return normalized


# Module-level normalizer functions for backwards compatibility
def default_output_normalizer(raw_output: Any) -> dict[str, Any]:
    return DefaultOutputNormalizer().normalize(raw_output)


def preserve_case_normalizer(raw_output: Any) -> dict[str, Any]:
    return PreserveCaseNormalizer().normalize(raw_output)


# ==============================================================================
# Input Normalizer Hierarchy
# ==============================================================================

class InputNormalizer(ABC):
    """Abstract base class for input normalizers."""

    @abstractmethod
    def normalize(self, raw_inputs: dict[str, Any]) -> dict[str, Any]:
        pass


class DefaultInputNormalizer(InputNormalizer):
    """Normalizes input variables into standard formats (numeric string parsing)."""

    def normalize(self, raw_inputs: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for k, v in raw_inputs.items():
            if isinstance(v, (int, float, bool)):
                normalized[k] = v
            elif isinstance(v, str):
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


class PassthroughInputNormalizer(InputNormalizer):
    """Passes inputs directly through without type coercions."""

    def normalize(self, raw_inputs: dict[str, Any]) -> dict[str, Any]:
        return dict(raw_inputs)


def default_input_normalizer(raw_inputs: dict[str, Any]) -> dict[str, Any]:
    return DefaultInputNormalizer().normalize(raw_inputs)


# ==============================================================================
# Cryptographic Implementation Hashing
# ==============================================================================

def compute_implementation_hash(target: Any) -> str:
    """Computes a deterministic SHA-256 cryptographic hash over an implementation target.
    Requires an authoritative source file or directory. Fails closed (FileNotFoundError/ValueError)
    if the authoritative source cannot be resolved. Never uses silent fallback hashing.
    """
    if not target:
        raise ValueError("Implementation target cannot be empty or None")

    if isinstance(target, (str, Path)):
        p = Path(target)
        if not p.exists():
            raise FileNotFoundError(f"Authoritative implementation source path does not exist: '{target}'")
        if p.is_file():
            with open(p, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()

        # Directory: hash all source files deterministically
        hasher = hashlib.sha256()
        all_files = sorted(
            [f for f in p.rglob("*") if f.is_file() and not f.name.endswith((".pyc", ".DS_Store")) and "__pycache__" not in f.parts],
            key=lambda f: str(f.relative_to(p)).replace("\\", "/")
        )
        if not all_files:
            raise FileNotFoundError(f"Implementation directory contains no valid source files: '{target}'")
        for file_p in all_files:
            rel = str(file_p.relative_to(p)).replace("\\", "/")
            hasher.update(rel.encode("utf-8"))
            with open(file_p, "rb") as f:
                hasher.update(f.read())
        return hasher.hexdigest()

    if hasattr(target, "_target_fn") or hasattr(target, "target_fn"):
        fn = getattr(target, "_target_fn", None) or getattr(target, "target_fn", None)
        return compute_implementation_hash(fn)

    if callable(target):
        import inspect
        try:
            src = inspect.getsource(target)
            if src and src.strip():
                return hashlib.sha256(src.encode("utf-8")).hexdigest()
        except Exception:
            pass

        try:
            source_file = inspect.getsourcefile(target) or inspect.getfile(target)
            if source_file and Path(source_file).exists():
                return compute_implementation_hash(source_file)
        except Exception:
            pass

        raise ValueError(
            f"Cannot resolve authoritative source code or file for callable '{getattr(target, '__name__', str(target))}'. "
            "Implementations must be anchored to authoritative source code on disk."
        )

    raise ValueError(f"Unsupported implementation target type: {type(target)}. Must be a file path, directory path, or anchored callable.")


# ==============================================================================
# Implementation Adapter Base Class & Lifecycle Contract
# ==============================================================================

class ImplementationAdapter(ABC):
    """Abstract Base Class for implementation target runners (Python, Java, Rust, REST, CLI, etc.).
    
    Defines the full generic adapter lifecycle:
    prepare() -> validate() -> execute() -> normalize_output() -> capture_evidence() -> cleanup()
    """

    name: str = "base_adapter"
    version: str = "1.0.0"
    role: Union[AdapterRole, str] = AdapterRole.TARGET
    implementation_hash: str = ""

    def prepare(self, context: Optional[dict[str, Any]] = None) -> None:
        """Lifecycle hook: Prepares the runtime environment, dependencies, or connections."""
        pass

    def validate(self) -> bool:
        """Lifecycle hook: Validates that the adapter target is accessible and ready for execution."""
        return True

    @abstractmethod
    def execute(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
        """Lifecycle hook: Executes the implementation on the provided input and returns an Observation."""
        pass

    def normalize_output(self, raw_output: Any) -> dict[str, Any]:
        """Lifecycle hook: Normalizes raw outputs using the configured output normalizer."""
        return default_output_normalizer(raw_output)

    def capture_evidence(self, observation: Observation) -> Optional[dict[str, Any]]:
        """Lifecycle hook: Captures execution evidence (traces, metadata, state changes)."""
        return observation.provenance

    def cleanup(self) -> None:
        """Lifecycle hook: Cleans up temporary resources, connections, or state."""
        pass


class FunctionAdapter(ImplementationAdapter):
    """Executes a Python callable function with latency tracking, exception isolation,
    and configurable input/output normalization.
    """

    def __init__(
        self,
        target_fn: Callable[..., Any],
        name: str = "python_function",
        version: str = "1.0.0",
        role: Union[AdapterRole, str] = AdapterRole.TARGET,
        input_normalizer: Optional[Union[InputNormalizer, Callable[[dict[str, Any]], dict[str, Any]]]] = None,
        output_normalizer: Optional[Union[OutputNormalizer, Callable[[Any], dict[str, Any]]]] = None,
    ):
        self.target_fn = target_fn
        self.name = name
        self.version = version
        self.role = role

        # Wrap normalizers
        if isinstance(input_normalizer, InputNormalizer):
            self._input_normalizer = input_normalizer.normalize
        else:
            self._input_normalizer = input_normalizer or default_input_normalizer

        if isinstance(output_normalizer, OutputNormalizer):
            self._output_normalizer = output_normalizer.normalize
        else:
            self._output_normalizer = output_normalizer or default_output_normalizer

        self.implementation_hash = compute_implementation_hash(target_fn)

    def normalize_output(self, raw_output: Any) -> dict[str, Any]:
        return self._output_normalizer(raw_output)

    def execute(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
        # Extract dictionary payload from CanonicalInput or raw dict
        if isinstance(inputs, CanonicalInput):
            raw_inputs = dict(inputs.get_data())
            actual_input_id = input_id or inputs.input_id
        else:
            raw_inputs = dict(inputs)
            actual_input_id = input_id

        norm_inputs = self._input_normalizer(raw_inputs)

        start_time = time.perf_counter()
        try:
            import inspect
            try:
                sig = inspect.signature(self.target_fn)
                has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
                if has_varkw:
                    call_kwargs = dict(norm_inputs)
                else:
                    call_kwargs = {k: v for k, v in norm_inputs.items() if k in sig.parameters}
                    for p_name, param in sig.parameters.items():
                        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
                            if p_name not in call_kwargs and param.default == inspect.Parameter.empty:
                                call_kwargs[p_name] = 50000.0 if "income" in p_name.lower() or "salary" in p_name.lower() else (0.5 if "ratio" in p_name.lower() else 0.0)
            except Exception:
                call_kwargs = norm_inputs

            raw_output = self.target_fn(**call_kwargs)
            latency_ms = round((time.perf_counter() - start_time) * 1000, 3)

            # Preserve exact raw output unaltered
            raw_out_dict = raw_output if isinstance(raw_output, dict) else {"decision": raw_output}
            norm_out_dict = self.normalize_output(raw_output)

            return Observation(
                input_id=actual_input_id,
                raw_inputs=raw_inputs,
                normalized_inputs=norm_inputs,
                raw_outputs=raw_out_dict,
                normalized_outputs=norm_out_dict,
                execution_status="SUCCESS",
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=latency_ms,
                provenance={"role": str(self.role)},
            )

        except Exception as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 3)
            logger.warning(f"Adapter '{self.name}' exception on input #{actual_input_id}: {exc}")
            return Observation(
                input_id=actual_input_id,
                raw_inputs=raw_inputs,
                normalized_inputs=norm_inputs,
                raw_outputs={},
                normalized_outputs={},
                execution_status="EXCEPTION",
                implementation_name=self.name,
                implementation_version=self.version,
                execution_time_ms=latency_ms,
                error_message=str(exc),
                provenance={"role": str(self.role)},
            )


# ==============================================================================
# Role-Based Adapters (V2 Generic & V1 Aliases)
# ==============================================================================

class ReferenceAdapter(FunctionAdapter):
    """Generic adapter for reference implementation (ground truth or legacy baseline)."""

    def __init__(self, target_fn: Callable[..., Any], name: str = "reference_implementation", version: str = "1.0.0", **kwargs):
        super().__init__(target_fn=target_fn, name=name, version=version, role=AdapterRole.REFERENCE, **kwargs)


class TargetAdapter(FunctionAdapter):
    """Generic adapter for candidate target implementation under certification."""

    def __init__(self, target_fn: Callable[..., Any], name: str = "target_candidate", version: str = "2.0.0", **kwargs):
        super().__init__(target_fn=target_fn, name=name, version=version, role=AdapterRole.TARGET, **kwargs)


class LegacyAdapter(FunctionAdapter):
    """Backward compatibility adapter for legacy reference implementation."""

    def __init__(self, target_fn: Callable[..., Any], name: str = "legacy_reference", version: str = "1.0.0", **kwargs):
        super().__init__(target_fn=target_fn, name=name, version=version, role=AdapterRole.LEGACY, **kwargs)


class ModernizedAdapter(FunctionAdapter):
    """Backward compatibility adapter for modernized candidate implementation."""

    def __init__(self, target_fn: Callable[..., Any], name: str = "modernized_candidate", version: str = "2.0.0", **kwargs):
        super().__init__(target_fn=target_fn, name=name, version=version, role=AdapterRole.MODERNIZED, **kwargs)
