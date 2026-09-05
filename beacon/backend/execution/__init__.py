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
from .input_set import (
    CanonicalInputItem,
    InputSet,
    compute_input_set_hash,
    compute_payload_hash,
)
from .readiness import (
    ReadinessChecker,
    ReadinessConfig,
    ReadinessResult,
    ReadinessStrategy,
)
from .evidence_models import (
    DatabaseEvidence,
    ErrorEvidence,
    EvidenceBundle,
    EvidenceCaptureStatus,
    EvidenceConfiguration,
    EvidenceManifest,
    EvidenceManifestItem,
    EvidenceRecord,
    EvidenceType,
    FileEvidence,
    FileStateSnapshot,
    HttpEvidence,
    LogEvidence,
    MetadataEvidence,
    OutputEvidence,
    RuntimeEvidence,
    TraceEvent,
    TraceEvidence,
    compute_content_hash,
)
from .evidence_providers import (
    DatabaseEvidenceProvider,
    EvidenceProvider,
    FileEvidenceProvider,
    HttpEvidenceProvider,
    LogEvidenceProvider,
    OutputEvidenceProvider,
    RuntimeEvidenceProvider,
    TraceEvidenceProvider,
)
from .evidence_normalizer import EvidenceNormalizer, evidence_normalizer
from .evidence_store import EvidenceStore, evidence_store
from .paired_models import (
    PairedExecutionItemResult,
    PairedExecutionRequest,
    PairedExecutionSession,
    PairedExecutionStatus,
)
from .paired_runner import PairedExecutionCoordinator, paired_execution_coordinator

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
    # Phase 3
    "CanonicalInputItem",
    "InputSet",
    "compute_input_set_hash",
    "compute_payload_hash",
    "ReadinessChecker",
    "ReadinessConfig",
    "ReadinessResult",
    "ReadinessStrategy",
    "DatabaseEvidence",
    "ErrorEvidence",
    "EvidenceBundle",
    "EvidenceCaptureStatus",
    "EvidenceConfiguration",
    "EvidenceManifest",
    "EvidenceManifestItem",
    "EvidenceRecord",
    "EvidenceType",
    "FileEvidence",
    "FileStateSnapshot",
    "HttpEvidence",
    "LogEvidence",
    "MetadataEvidence",
    "OutputEvidence",
    "RuntimeEvidence",
    "TraceEvent",
    "TraceEvidence",
    "compute_content_hash",
    "DatabaseEvidenceProvider",
    "EvidenceProvider",
    "FileEvidenceProvider",
    "HttpEvidenceProvider",
    "LogEvidenceProvider",
    "OutputEvidenceProvider",
    "RuntimeEvidenceProvider",
    "TraceEvidenceProvider",
    "EvidenceNormalizer",
    "evidence_normalizer",
    "EvidenceStore",
    "evidence_store",
    "PairedExecutionItemResult",
    "PairedExecutionRequest",
    "PairedExecutionSession",
    "PairedExecutionStatus",
    "PairedExecutionCoordinator",
    "paired_execution_coordinator",
]

