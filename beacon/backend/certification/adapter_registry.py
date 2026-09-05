"""BEACON V2 — Implementation Adapter Registry.

Provides safe registration, resolution, and querying of ImplementationAdapter
instances for generic cross-version equivalence certification without hardcoding
application-specific logic into certification endpoints.
"""

from enum import Enum
import logging
from typing import Any, Optional, Union
from pydantic import BaseModel, Field

from .adapters import (
    AdapterRole,
    ImplementationAdapter,
    LegacyAdapter,
    ModernizedAdapter,
    ReferenceAdapter,
    TargetAdapter,
)

logger = logging.getLogger("beacon.certification.registry")


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
        # (target_name, version) -> ImplementationAdapter
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
        """Resolves an ImplementationAdapter by name, and optionally version.
        If version is omitted, returns the latest registered version matching target_name.
        """
        if version is not None:
            if (target_name, version) in self._adapters:
                return self._adapters[(target_name, version)]

        # Find matching adapters and select the latest registered
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

    def list_adapters(self) -> list[dict[str, Any]]:
        """Lists all registered adapters and their metadata."""
        items = []
        for a in self._adapters.values():
            caps = getattr(a, "capabilities", None)
            caps_dict = caps.model_dump() if hasattr(caps, "model_dump") else (caps if isinstance(caps, dict) else {})
            items.append({
                "name": a.name,
                "version": a.version,
                "role": str(getattr(a, "role", "target")),
                "adapter_type": getattr(a, "adapter_type", type(a).__name__),
                "type": type(a).__name__,
                "implementation_hash": getattr(a, "implementation_hash", ""),
                "capabilities": caps_dict,
                "input_schema": getattr(a, "input_schema", {}),
                "output_schema": getattr(a, "output_schema", {}),
            })
        return items

    def clear(self, reinit_benchmarks: bool = True):
        """Clears all registered adapters (for test isolation)."""
        self._adapters.clear()
        self._registrations.clear()
        if reinit_benchmarks:
            try:
                from benchmarks import benchmark_registry
                benchmark_registry.refresh()
            except Exception:
                pass


# Default singleton instance
adapter_registry = AdapterRegistry()

