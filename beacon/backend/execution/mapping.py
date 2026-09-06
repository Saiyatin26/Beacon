"""BEACON V2 — Configuration-Driven Input & Output Mapping.

Provides generic, domain-agnostic translation between CanonicalInput/CanonicalObservation
and runtime-specific invocation payloads (arguments, JSON payloads, query parameters,
CLI flags, and stdout/stderr).
"""

from enum import Enum
import json
from typing import Any, Callable, Optional, Union
from pydantic import BaseModel, Field
from common.contracts import CanonicalInput, Observation


class MappedInput(BaseModel):
    """Generic internal representation of application input produced by InputMapper.

    Acts as the single unified mapped artifact consumed by:
    - ONE-SHOT: mapped_input.cli_args for process argument execution
    - PERSISTENT: mapped_input.payload for persistent protocol serialization (e.g. JSON-lines)
    """
    payload: dict[str, Any] = Field(default_factory=dict)
    cli_args: list[str] = Field(default_factory=list)
    raw_source: dict[str, Any] = Field(default_factory=dict)
    input_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PersistentProtocol(str, Enum):
    """Supported wire protocols for persistent process communication over stdin."""
    JSON_LINES = "json_lines"
    TEXT_LINES = "text_lines"
    CUSTOM = "custom"


class PersistentInputSerializer:
    """Serializes a MappedInput or payload into wire format for persistent stdin transmission."""

    def __init__(
        self,
        protocol: Union[PersistentProtocol, str] = PersistentProtocol.JSON_LINES,
        custom_serializer: Optional[Callable[[Any], str]] = None,
    ):
        if isinstance(protocol, str):
            try:
                self.protocol = PersistentProtocol(protocol.lower())
            except ValueError:
                self.protocol = PersistentProtocol.JSON_LINES
        else:
            self.protocol = protocol
        self.custom_serializer = custom_serializer

    def serialize(self, input_item: Union[MappedInput, dict[str, Any], Any]) -> str:
        """Serializes input item into the configured wire protocol string with a newline delimiter."""
        data = input_item.payload if isinstance(input_item, MappedInput) else input_item

        if self.protocol == PersistentProtocol.CUSTOM and self.custom_serializer:
            res = self.custom_serializer(data)
            return res if res.endswith("\n") else res + "\n"

        if self.protocol == PersistentProtocol.TEXT_LINES:
            if isinstance(data, dict):
                line = " ".join(f"{k}={v}" for k, v in data.items())
            else:
                line = str(data)
            return line + "\n"

        # Default: JSON_LINES
        if isinstance(data, (dict, list)):
            return json.dumps(data) + "\n"
        return json.dumps({"value": data}) + "\n"



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

    def map_input(self, canonical_input: Union[CanonicalInput, dict[str, Any]], input_id: str = "") -> MappedInput:
        """Canonical mapping entrypoint producing a generic MappedInput representation."""
        if isinstance(canonical_input, CanonicalInput):
            actual_id = input_id or canonical_input.input_id
            raw_source = canonical_input.get_data()
            metadata = canonical_input.metadata
        else:
            actual_id = input_id
            raw_source = dict(canonical_input)
            metadata = {}

        kwargs = self.map_to_kwargs(canonical_input)
        cli_args = self.map_to_cli_args(canonical_input)

        return MappedInput(
            payload=kwargs,
            cli_args=cli_args,
            raw_source=raw_source,
            input_id=actual_id,
            metadata=metadata,
        )

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
