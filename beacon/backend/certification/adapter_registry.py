"""BEACON V2 — Implementation Adapter Registry.

Provides safe registration, resolution, and querying of ImplementationAdapter
instances for generic cross-version equivalence certification without hardcoding
application-specific logic into certification endpoints.
"""

from common.contracts import (
    AdapterRegistration,
    AdapterRegistry,
    adapter_registry,
)
from .adapters import (
    AdapterRole,
    ImplementationAdapter,
    LegacyAdapter,
    ModernizedAdapter,
    ReferenceAdapter,
    TargetAdapter,
)

__all__ = [
    "AdapterRegistration",
    "AdapterRegistry",
    "adapter_registry",
]


