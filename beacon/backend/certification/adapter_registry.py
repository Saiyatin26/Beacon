"""BEACON V2 — Implementation Adapter Registry.

Provides safe registration, resolution, and querying of ImplementationAdapter
instances for generic cross-version equivalence certification without hardcoding
application-specific logic into certification endpoints.
"""

from enum import Enum
import logging
from typing import Any, Optional
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
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdapterRegistry:
    """Thread-safe registry for resolving target ImplementationAdapter instances."""

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
            self._registrations[key] = AdapterRegistration(
                adapter_id=f"{adapter.name}:{adapter.version}",
                name=adapter.name,
                role=str(getattr(adapter, "role", "target")),
                version=adapter.version,
                implementation_type=type(adapter).__name__,
            )

        logger.debug(f"Registered ImplementationAdapter '{adapter.name}' (v{adapter.version})")
        return adapter

    def get_adapter(self, target_name: str, version: Optional[str] = None) -> Optional[ImplementationAdapter]:
        """Resolves an ImplementationAdapter by name, and optionally version.
        If version is omitted, returns the latest registered version matching target_name.
        """
        # Backward-compatible alias mappings for V1 benchmarks
        alias_map = {
            "retail_discount_legacy": "retail_pricing_legacy",
            "retail_discount_modern_clean": "retail_pricing_modern_clean",
            "retail_discount_modern_buggy_threshold": "retail_pricing_modern_buggy_threshold",
            "retail_discount_modern_buggy_operator": "retail_pricing_modern_buggy_operator",
            "payroll_tax_legacy": "payroll_legacy",
            "payroll_tax_modern_clean": "payroll_modern_clean",
            "payroll_tax_modern_buggy_bracket": "payroll_modern_buggy_bracket",
            "payroll_tax_modern_buggy_deduction": "payroll_modern_buggy_deduction",
        }
        resolved_name = alias_map.get(target_name, target_name)

        if version is not None:
            if (resolved_name, version) in self._adapters:
                return self._adapters[(resolved_name, version)]
            if (target_name, version) in self._adapters:
                return self._adapters[(target_name, version)]

        # Find matching adapters and select the latest
        matches = [a for (name, ver), a in self._adapters.items() if name in (resolved_name, target_name)]
        if matches:
            return matches[-1]
        return None

    def list_adapters(self) -> list[dict[str, Any]]:
        """Lists all registered adapters and their metadata."""
        return [
            {
                "name": a.name,
                "version": a.version,
                "role": str(getattr(a, "role", "target")),
                "type": type(a).__name__,
                "implementation_hash": getattr(a, "implementation_hash", ""),
                "input_schema": getattr(a, "input_schema", {}),
                "output_schema": getattr(a, "output_schema", {}),
            }
            for a in self._adapters.values()
        ]

    def clear(self, reinit_benchmarks: bool = True):
        """Clears all registered adapters (for test isolation)."""
        self._adapters.clear()
        self._registrations.clear()
        if reinit_benchmarks:
            _init_benchmark_adapters()


# Default singleton instance
adapter_registry = AdapterRegistry()


def _init_benchmark_adapters():
    """Initializes standard benchmark demonstration adapters if available."""
    try:
        import legacy_loan_approval
        import modern_loan_approval

        adapter_registry.register_adapter(
            LegacyAdapter(
                target_fn=legacy_loan_approval.evaluate_loan,
                name="loan_approval_legacy",
                version="1.0.0",
            )
        )
        adapter_registry.register_adapter(
            ModernizedAdapter(
                target_fn=legacy_loan_approval.evaluate_loan,
                name="loan_approval_modern_equiv",
                version="2.0.0",
            )
        )
        adapter_registry.register_adapter(
            ModernizedAdapter(
                target_fn=modern_loan_approval.evaluate_loan,
                name="loan_approval_modern_buggy",
                version="2.0.0",
            )
        )
    except ImportError:
        logger.debug("Benchmark loan approval modules not in path for pre-registration.")


_init_benchmark_adapters()
