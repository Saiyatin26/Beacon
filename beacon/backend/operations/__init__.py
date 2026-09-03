"""Phase 16 — Production Readiness, Observability, Reliability & Performance Subsystem."""

from .health import check_liveness, check_readiness, check_dependency_health, get_version_info, VersionInfoResponse
from .startup import validate_startup_configuration
from .logging_config import (
    setup_structured_logging,
    get_logger,
    log_operational_event,
    execution_step,
    StructuredJsonFormatter,
    BeaconConsoleFormatter,
    HumanReadableConsoleFilter,
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
    StateTransitionError,
    IdempotencyConflictError,
    OperationTimeoutError,
    register_error_handlers,
)
from .job_lifecycle import (
    JobState,
    CertificationJob,
    certification_job_tracker,
    VALID_JOB_TRANSITIONS,
)
from .metrics import (
    operational_metrics,
    MetricsSnapshot,
)
from .workload import WorkloadProtector, workload_protector
from .resilience import (
    classify_failure,
    execute_with_retry,
    with_timeout,
)
from .idempotency import (
    idempotency_manager,
    IdempotencyManager,
    compute_canonical_request_hash,
)
from .startup import recover_interrupted_operations

__all__ = [
    "check_liveness",
    "check_readiness",
    "check_dependency_health",
    "get_version_info",
    "VersionInfoResponse",
    "validate_startup_configuration",
    "recover_interrupted_operations",
    "setup_structured_logging",
    "get_logger",
    "log_operational_event",
    "execution_step",
    "StructuredJsonFormatter",
    "BeaconConsoleFormatter",
    "HumanReadableConsoleFilter",
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
    "StateTransitionError",
    "IdempotencyConflictError",
    "OperationTimeoutError",
    "register_error_handlers",
    "JobState",
    "CertificationJob",
    "certification_job_tracker",
    "VALID_JOB_TRANSITIONS",
    "operational_metrics",
    "MetricsSnapshot",
    "WorkloadProtector",
    "workload_protector",
    "classify_failure",
    "execute_with_retry",
    "with_timeout",
    "idempotency_manager",
    "IdempotencyManager",
    "compute_canonical_request_hash",
]

