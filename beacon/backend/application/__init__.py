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


def __getattr__(name: str):
    if name in ("ApplicationResolver", "ApplicationResolutionError"):
        from .resolver import ApplicationResolutionError, ApplicationResolver
        return ApplicationResolutionError if name == "ApplicationResolutionError" else ApplicationResolver
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


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

