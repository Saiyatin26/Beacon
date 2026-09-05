"""BEACON V2 — Application Execution & Adapter Framework Package."""

from .models import (
    AdapterCapabilities,
    AdapterHealth,
    AdapterHealthStatus,
    AdapterType,
    ExecutionRequest,
    ExecutionResult,
    ExecutionSession,
    ExecutionStatus,
)
from .mapping import (
    InputMapper,
    InputMapperConfig,
    OutputMapper,
    OutputMapperConfig,
    resolve_dot_path,
)
from .security import (
    SandboxedPathValidator,
    SecretRedactor,
    SSRFValidator,
)
from .process_adapter import CliAdapter, ProcessAdapter
from .http_adapter import HttpAdapter
from .container_adapter import ContainerAdapter
from .preflight import (
    PreFlightCheck,
    PreFlightResult,
    PreFlightValidator,
    preflight_validator,
)
from .repository import ExecutionRepository, execution_repository
from .runner import ApplicationExecutor, application_executor

__all__ = [
    "AdapterCapabilities",
    "AdapterHealth",
    "AdapterHealthStatus",
    "AdapterType",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionSession",
    "ExecutionStatus",
    "InputMapper",
    "InputMapperConfig",
    "OutputMapper",
    "OutputMapperConfig",
    "resolve_dot_path",
    "SandboxedPathValidator",
    "SecretRedactor",
    "SSRFValidator",
    "ProcessAdapter",
    "CliAdapter",
    "HttpAdapter",
    "ContainerAdapter",
    "PreFlightCheck",
    "PreFlightResult",
    "PreFlightValidator",
    "preflight_validator",
    "ExecutionRepository",
    "execution_repository",
    "ApplicationExecutor",
    "application_executor",
]
