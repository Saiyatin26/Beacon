"""BEACON V2 — Application Layer Package.

Provides generic, domain-agnostic application models, specifications,
persistence, registry, and resolution capabilities.
"""

from .models import (
    ApplicationRole,
    ApplicationSpec,
    DatasetConfig,
    EvidenceConfig,
    ExecutionConfig,
    ImplementationTarget,
    ImplementationType,
    InputContract,
    OutputContract,
    RuleConfig,
    RuntimeConfig,
    compute_application_spec_hash,
)
from .registry import ApplicationRegistry, application_registry
from .repository import ApplicationRepository, application_repository
from .resolver import ApplicationResolutionError, ApplicationResolver

__all__ = [
    "ApplicationRole",
    "ApplicationSpec",
    "DatasetConfig",
    "EvidenceConfig",
    "ExecutionConfig",
    "ImplementationTarget",
    "ImplementationType",
    "InputContract",
    "OutputContract",
    "RuleConfig",
    "RuntimeConfig",
    "compute_application_spec_hash",
    "ApplicationRegistry",
    "application_registry",
    "ApplicationRepository",
    "application_repository",
    "ApplicationResolutionError",
    "ApplicationResolver",
]
