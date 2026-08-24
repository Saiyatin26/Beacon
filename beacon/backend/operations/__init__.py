"""Phase 16 — Production Readiness, Observability, Reliability & Performance Subsystem."""

from .health import check_liveness, check_readiness, check_dependency_health, get_version_info, VersionInfoResponse
from .startup import validate_startup_configuration
from .logging_config import (
    setup_structured_logging,
    get_logger,
    log_operational_event,
    StructuredJsonFormatter,
    scrub_secrets,
    sanitize_log_string,
)
from .middleware import RequestCorrelationMiddleware, WorkloadLimiterMiddleware, get_correlation_id
from .errors import (
    StandardErrorResponse,
    ErrorCategory,
    BeaconOperationalError,
    ResourceLimitError,
    DependencyUnavailableError,
    register_error_handlers,
)
from .job_lifecycle import (
    JobState,
    CertificationJob,
    certification_job_tracker,
)
from .metrics import (
    operational_metrics,
    MetricsSnapshot,
)
from .workload import WorkloadProtector, workload_protector

__all__ = [
    "check_liveness",
    "check_readiness",
    "check_dependency_health",
    "get_version_info",
    "VersionInfoResponse",
    "validate_startup_configuration",
    "setup_structured_logging",
    "get_logger",
    "log_operational_event",
    "StructuredJsonFormatter",
    "scrub_secrets",
    "sanitize_log_string",
    "RequestCorrelationMiddleware",
    "WorkloadLimiterMiddleware",
    "get_correlation_id",
    "StandardErrorResponse",
    "ErrorCategory",
    "BeaconOperationalError",
    "ResourceLimitError",
    "DependencyUnavailableError",
    "register_error_handlers",
    "JobState",
    "CertificationJob",
    "certification_job_tracker",
    "operational_metrics",
    "MetricsSnapshot",
    "WorkloadProtector",
    "workload_protector",
]
