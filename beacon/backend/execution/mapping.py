"""BEACON V2 — Configuration-Driven Input & Output Mapping.

Provides generic, domain-agnostic translation between CanonicalInput/CanonicalObservation
and runtime-specific invocation payloads (arguments, JSON payloads, query parameters,
CLI flags, and stdout/stderr).
"""

import json
from typing import Any, Callable, Optional, Union
from pydantic import BaseModel, Field

from certification.models import CanonicalInput, Observation


class InputMapperConfig(BaseModel):
    """Configuration driving how CanonicalInput maps to application arguments."""
    field_mappings: dict[str, str] = Field(default_factory=dict)
    # e.g. {"customer_age": "payload.customer.age", "user_id": "metadata.user_id"}
    nested_output_structure: Optional[dict[str, Any]] = None
    # template for nested dictionary payloads
    constants: dict[str, Any] = Field(default_factory=dict)
    # static constant values to inject
    type_conversions: dict[str, str] = Field(default_factory=dict)
    # e.g. {"amount": "float", "count": "int", "is_active": "bool"}
    argument_order: list[str] = Field(default_factory=list)
    # positional argument ordering for CLI / callables
    cli_format: str = "flags"  # "flags" (--key value), "positional", "json_stdin", "json_arg"


class OutputMapperConfig(BaseModel):
    """Configuration driving how raw application outputs map to canonical observations."""
    field_extractions: dict[str, str] = Field(default_factory=dict)
    # e.g. {"status": "body.result.status", "total": "body.summary.amount"}
    status_code_mapping: dict[int, str] = Field(default_factory=dict)
    # e.g. {200: "SUCCESS", 400: "VALIDATION_ERROR", 500: "APP_EXECUTION_ERROR"}
    stdout_format: str = "json"  # "json", "text", "regex"
    stdout_regex: Optional[str] = None
    strip_whitespace: bool = True
    preserve_casing: bool = True


def resolve_dot_path(data: Any, path: str, default: Any = None) -> Any:
    """Extracts a nested value from a dictionary or object using dot-notation (e.g. 'payload.user.id')."""
    if not path:
        return data

    parts = path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                return default
        elif hasattr(current, part):
            current = getattr(current, part)
        elif isinstance(current, (list, tuple)):
            try:
                idx = int(part)
                current = current[idx]
            except (ValueError, IndexError):
                return default
        else:
            return default
    return current


class InputMapper:
    """Transforms a CanonicalInput into application-specific invocation structures."""

    def __init__(self, config: Optional[InputMapperConfig] = None):
        self.config = config or InputMapperConfig()

    def map_to_kwargs(self, canonical_input: Union[CanonicalInput, dict[str, Any]]) -> dict[str, Any]:
        """Maps canonical input to keyword arguments for Python callables or HTTP JSON bodies."""
        raw_data = canonical_input.get_data() if isinstance(canonical_input, CanonicalInput) else dict(canonical_input)
        
        # If no explicit field mappings, pass raw data merged with constants
        if not self.config.field_mappings and not self.config.nested_output_structure:
            res = dict(raw_data)
            res.update(self.config.constants)
            return self._apply_type_conversions(res)

        context = {
            "payload": raw_data,
            "values": raw_data,
            **(raw_data if isinstance(raw_data, dict) else {}),
        }
        if isinstance(canonical_input, CanonicalInput):
            context["metadata"] = canonical_input.metadata
            context["provenance"] = canonical_input.provenance
            context["input_id"] = canonical_input.input_id

        result: dict[str, Any] = {}

        # 1. Apply field mappings from dot paths
        if self.config.field_mappings:
            for target_key, source_path in self.config.field_mappings.items():
                val = resolve_dot_path(context, source_path)
                if val is None and isinstance(raw_data, dict):
                    val = resolve_dot_path(raw_data, source_path)
                if val is not None:
                    result[target_key] = val
        else:
            result = dict(raw_data)

        # 2. Inject static constants
        for k, v in self.config.constants.items():
            if k not in result:
                result[k] = v

        # 3. Apply type conversions
        return self._apply_type_conversions(result)

    def map_to_cli_args(self, canonical_input: Union[CanonicalInput, dict[str, Any]]) -> list[str]:
        """Maps canonical input to a list of CLI argument strings."""
        kwargs = self.map_to_kwargs(canonical_input)

        if self.config.cli_format == "json_arg":
            return [json.dumps(kwargs)]

        if self.config.cli_format == "positional":
            args = []
            keys = self.config.argument_order or list(kwargs.keys())
            for k in keys:
                if k in kwargs:
                    args.append(str(kwargs[k]))
            return args

        # Default: --key value flags
        args = []
        for k, v in kwargs.items():
            if isinstance(v, bool):
                if v:
                    args.append(f"--{k}")
            elif v is not None:
                args.extend([f"--{k}", str(v)])
        return args

    def _apply_type_conversions(self, data: dict[str, Any]) -> dict[str, Any]:
        converted = dict(data)
        for field, target_type in self.config.type_conversions.items():
            if field in converted and converted[field] is not None:
                val = converted[field]
                try:
                    if target_type == "int":
                        converted[field] = int(val)
                    elif target_type == "float":
                        converted[field] = float(val)
                    elif target_type == "str":
                        converted[field] = str(val)
                    elif target_type == "bool":
                        converted[field] = str(val).lower() in ("true", "1", "yes")
                    elif target_type == "json":
                        converted[field] = json.loads(val) if isinstance(val, str) else val
                except (ValueError, TypeError):
                    pass
        return converted


class OutputMapper:
    """Transforms raw application outputs, process stdout, and HTTP responses into Canonical Observations."""

    def __init__(self, config: Optional[OutputMapperConfig] = None):
        self.config = config or OutputMapperConfig()

    def map_output(
        self,
        raw_output: Any,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
        exit_code: Optional[int] = None,
        status_code: Optional[int] = None,
    ) -> dict[str, Any]:
        """Normalizes and maps output data into a structured output dictionary."""
        extracted: dict[str, Any] = {}

        # 1. Parse stdout if provided
        if stdout:
            clean_stdout = stdout.strip() if self.config.strip_whitespace else stdout
            if self.config.stdout_format == "json":
                try:
                    parsed = json.loads(clean_stdout)
                    if isinstance(parsed, dict):
                        extracted.update(parsed)
                    else:
                        extracted["output"] = parsed
                except Exception:
                    extracted["stdout"] = clean_stdout
            else:
                extracted["stdout"] = clean_stdout

        # 2. Extract from raw_output if dict
        if isinstance(raw_output, dict):
            extracted.update(raw_output)
        elif raw_output is not None and not stdout:
            extracted["decision"] = raw_output

        # 3. Apply field extractions if configured
        if self.config.field_extractions:
            final_dict: dict[str, Any] = {}
            for target_field, source_path in self.config.field_extractions.items():
                val = resolve_dot_path(extracted, source_path)
                if val is not None:
                    final_dict[target_field] = val
            return final_dict if final_dict else extracted

        return extracted
