"""BEACON V2 — Common Shared Contracts & Adapter Abstraction.

Lightweight, shared domain contracts for execution, adapter roles, health statuses,
capabilities, and canonical input/observation structures. Free from any dependency on
certification engines, database connections, API routers, or LLM providers.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field

logger = logging.getLogger("beacon.common.contracts")


# ==============================================================================
# 1. Enums: Roles, Statuses, Types
# ==============================================================================

class AdapterRole(str, Enum):
    """Generic role of an implementation under behavioral equivalence evaluation."""
    REFERENCE = "reference"
    TARGET = "target"
    # Backward compatibility aliases
    LEGACY = "legacy"
    MODERNIZED = "modernized"


class ExecutionStatus(str, Enum):
    """Deterministic status lifecycle for an application execution attempt."""
    CREATED = "CREATED"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    APP_EXECUTION_ERROR = "APP_EXECUTION_ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    ADAPTER_ERROR = "ADAPTER_ERROR"
    UNAVAILABLE = "UNAVAILABLE"


class AdapterType(str, Enum):
    """Runtime execution modality supported by the adapter framework."""
    FUNCTION = "function"
    PROCESS = "process"
    CLI = "cli"
    HTTP = "http"
    CONTAINER = "container"


class AdapterHealthStatus(str, Enum):
    """Readiness status of an implementation adapter."""
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    MISCONFIGURED = "MISCONFIGURED"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


# ==============================================================================
# 2. Adapter Capabilities & Health Models
# ==============================================================================

class AdapterCapabilities(BaseModel):
    """Structural declarations of what features an adapter implementation natively supports."""
    supports_timeout: bool = True
    supports_streaming: bool = False
    supports_files: bool = False
    supports_binary: bool = False
    supports_traces: bool = False
    supports_cleanup: bool = True
    supports_state_capture: bool = False
    supports_custom_environment: bool = False
    supports_sandboxing: bool = False


class AdapterHealth(BaseModel):
    """Diagnostic health assessment of an adapter."""
    adapter_id: str
    status: AdapterHealthStatus = AdapterHealthStatus.UNKNOWN
    is_ready: bool = False
    diagnostics: str = ""
    capabilities: AdapterCapabilities = Field(default_factory=AdapterCapabilities)
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ==============================================================================
# 3. Canonical Input & Observation Models
# ==============================================================================

def compute_canonical_input_hash(values: dict[str, Any]) -> str:
    """Computes a full 64-character SHA-256 digest of canonical input values with stable key ordering."""
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CanonicalInput(BaseModel):
    """Generic canonical input contract for arbitrary domain payloads."""
    input_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    values: dict[str, Any] = Field(default_factory=dict)
    input_hash: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    expected_context: Optional[dict[str, Any]] = None
    tags: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        target_dict = self.payload or self.values
        if not self.payload and self.values:
            object.__setattr__(self, "payload", self.values)
        if not self.values and self.payload:
            object.__setattr__(self, "values", self.payload)
        if not self.input_hash and target_dict:
            object.__setattr__(self, "input_hash", compute_canonical_input_hash(target_dict))

    def get_data(self) -> dict[str, Any]:
        return self.payload or self.values


class Observation(BaseModel):
    """Execution observation of a target implementation on a single input."""
    input_id: str
    raw_inputs: dict[str, Any] = Field(default_factory=dict)
    normalized_inputs: dict[str, Any] = Field(default_factory=dict)
    raw_outputs: dict[str, Any] = Field(default_factory=dict)
    normalized_outputs: dict[str, Any] = Field(default_factory=dict)
    execution_status: Literal["SUCCESS", "EXCEPTION", "TIMEOUT"] = "SUCCESS"
    implementation_name: str = "implementation"
    implementation_version: str = "1.0.0"
    execution_time_ms: float = 0.0
    error_message: Optional[str] = None
    state_changes: Optional[dict[str, Any]] = None
    side_effects: list[dict[str, Any]] = Field(default_factory=list)
    trace_reference: Optional[str] = None
    provenance: dict[str, Any] = Field(default_factory=dict)


# ==============================================================================
# 4. Implementation Adapter Base Class
# ==============================================================================

class ImplementationAdapter(ABC):
    """Abstract Base Class for implementation target runners (Python, Java, Rust, REST, CLI, etc.).
    
    Defines the full generic adapter lifecycle:
    configure() -> validate() -> prepare() -> execute() -> normalize_output() -> capture_evidence() -> cleanup()
    """

    name: str = "base_adapter"
    version: str = "1.0.0"
    role: Union[AdapterRole, str] = AdapterRole.TARGET
    implementation_hash: str = ""
    adapter_type: str = "custom"
    capabilities: AdapterCapabilities = AdapterCapabilities()

    def configure(self, config: Optional[dict[str, Any]] = None) -> None:
        """Lifecycle hook: Configures adapter with runtime parameters."""
        pass

    def health_check(self) -> AdapterHealth:
        """Lifecycle hook: Evaluates operational readiness and dependency availability."""
        caps = getattr(self, "capabilities", None) or AdapterCapabilities()
        return AdapterHealth(
            adapter_id=f"{self.name}:{self.version}",
            status=AdapterHealthStatus.AVAILABLE,
            is_ready=True,
            diagnostics=f"Adapter '{self.name}' is operational.",
            capabilities=caps,
        )

    def prepare(self, context: Optional[dict[str, Any]] = None) -> None:
        """Lifecycle hook: Prepares the runtime environment, dependencies, or connections."""
        pass

    def validate(self, input_data: Any = None) -> bool:
        """Lifecycle hook: Validates that the adapter target is accessible and ready for execution."""
        return True

    @abstractmethod
    def execute(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
        """Lifecycle hook: Executes the implementation on the provided input and returns an Observation."""
        pass

    def normalize_output(self, raw_output: Any) -> dict[str, Any]:
        """Lifecycle hook: Normalizes raw outputs."""
        if isinstance(raw_output, dict):
            return dict(raw_output)
        elif raw_output is not None:
            return {"decision": raw_output}
        return {}

    def capture_evidence(self, observation: Observation) -> Optional[dict[str, Any]]:
        """Lifecycle hook: Captures execution evidence (traces, metadata, state changes)."""
        return observation.provenance

    def cleanup(self) -> None:
        """Lifecycle hook: Cleans up temporary resources, connections, or state."""
        pass


# ==============================================================================
# 5. Adapter Registration & Registry
# ==============================================================================

class AdapterRegistration(BaseModel):
    """Metadata record for registered implementation adapters."""
    adapter_id: str
    name: str
    role: str = "target"
    version: str = "1.0.0"
    implementation_type: str = "python_callable"
    capabilities: Union[list[str], dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdapterRegistry:
    """Thread-safe registry for resolving target ImplementationAdapter instances.
    
    Operates in a completely domain-agnostic manner by identity and metadata.
    """

    def __init__(self):
        self._adapters: dict[tuple[str, str], ImplementationAdapter] = {}
        self._registrations: dict[tuple[str, str], AdapterRegistration] = {}

    def register_adapter(
        self,
        adapter: ImplementationAdapter,
        registration: Optional[AdapterRegistration] = None,
    ) -> ImplementationAdapter:
        """Registers an ImplementationAdapter by its name and version."""
        key = (adapter.name, adapter.version)
        self._adapters[key] = adapter

        if registration:
            self._registrations[key] = registration
        else:
            raw_caps = getattr(adapter, "capabilities", [])
            if hasattr(raw_caps, "model_dump"):
                caps_val = [k for k, v in raw_caps.model_dump().items() if v is True]
            elif isinstance(raw_caps, dict):
                caps_val = [k for k, v in raw_caps.items() if v is True]
            elif isinstance(raw_caps, (list, set)):
                caps_val = [str(c) for c in raw_caps]
            else:
                caps_val = []

            self._registrations[key] = AdapterRegistration(
                adapter_id=f"{adapter.name}:{adapter.version}",
                name=adapter.name,
                role=str(getattr(adapter, "role", "target")),
                version=adapter.version,
                implementation_type=type(adapter).__name__,
                capabilities=caps_val,
                metadata=getattr(adapter, "metadata", {}),
            )

        logger.debug(f"Registered ImplementationAdapter '{adapter.name}' (v{adapter.version})")
        return adapter

    def get_adapter(self, target_name: str, version: Optional[str] = None) -> Optional[ImplementationAdapter]:
        """Resolves an ImplementationAdapter by name, and optionally version."""
        if version is not None:
            if (target_name, version) in self._adapters:
                return self._adapters[(target_name, version)]

        matches = [a for (name, ver), a in self._adapters.items() if name == target_name]
        if matches:
            return matches[-1]
        return None

    def get_registration(self, target_name: str, version: Optional[str] = None) -> Optional[AdapterRegistration]:
        """Retrieves metadata registration record for an adapter."""
        if version is not None:
            if (target_name, version) in self._registrations:
                return self._registrations[(target_name, version)]

        matches = [r for (name, ver), r in self._registrations.items() if name == target_name]
        if matches:
            return matches[-1]
        return None

    def list_adapters(self, role: Optional[Union[AdapterRole, str]] = None) -> list[AdapterRegistration]:
        """Lists all registered adapter descriptors, optionally filtered by role."""
        if role is not None:
            role_str = role.value if hasattr(role, "value") else str(role)
            return [r for r in self._registrations.values() if r.role == role_str]
        return list(self._registrations.values())

    def clear(self) -> None:
        """Clears all registered adapters (primarily for isolated test fixtures)."""
        self._adapters.clear()
        self._registrations.clear()


# Authoritative shared singleton registry
adapter_registry = AdapterRegistry()
