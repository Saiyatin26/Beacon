"""BEACON V2 — Phase 3 Generic Evidence Models, Bundles, Manifests & Integrity Contracts.

Defines canonical evidence structures capturing real application outputs, execution errors,
runtime context, system logs, lifecycle traces, filesystem deltas, database snapshots,
HTTP metrics, explicit persistence status, and cryptographic tamper-evident SHA-256 manifests.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class EvidenceType(str, Enum):
    """Categorization of behavioral evidence items."""
    OUTPUT = "OUTPUT"
    ERROR = "ERROR"
    RUNTIME = "RUNTIME"
    LOG = "LOG"
    TRACE = "TRACE"
    FILESYSTEM = "FILESYSTEM"
    DATABASE = "DATABASE"
    HTTP = "HTTP"
    METADATA = "METADATA"


class EvidenceCaptureStatus(str, Enum):
    """State of an evidence capture attempt."""
    CAPTURED = "CAPTURED"
    PARTIAL = "PARTIAL"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    FAILED = "FAILED"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    CAPTURE_ERROR = "CAPTURE_ERROR"


class EvidencePersistenceStatus(str, Enum):
    """Explicit status of evidence storage in SQLite/filesystem."""
    PERSISTED = "PERSISTED"
    FAILED = "FAILED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    PARTIAL = "PARTIAL"


def compute_content_hash(data: Any) -> str:
    """Computes a deterministic 64-character SHA-256 digest of arbitrary serializable data."""
    if isinstance(data, (dict, list)):
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    elif isinstance(data, str):
        canonical = data
    elif isinstance(data, bytes):
        return hashlib.sha256(data).hexdigest()
    else:
        canonical = str(data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ==============================================================================
# Specific Typed Payloads
# ==============================================================================

class OutputEvidence(BaseModel):
    """Execution output facts: canonical & raw output, exit code, stdout/stderr, latency."""
    raw_output: Optional[Any] = None
    normalized_output: dict[str, Any] = Field(default_factory=dict)
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
    http_status: Optional[int] = None
    headers: Optional[dict[str, str]] = None
    duration_ms: float = 0.0
    execution_status: str = "SUCCESS"
    error_message: Optional[str] = None


class ErrorEvidence(BaseModel):
    """Failure facts: error category, message, execution phase, and provenance."""
    category: str = "APPLICATION_ERROR"
    message: str = ""
    phase: str = "EXECUTION"
    exception_type: Optional[str] = None
    stack_trace: Optional[str] = None
    execution_id: Optional[str] = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class RuntimeEvidence(BaseModel):
    """Operating environment and runtime identification."""
    os: str = ""
    architecture: str = ""
    python_version: str = ""
    hostname: str = "localhost"
    runtime_version: str = ""
    environment_id: str = "default"
    adapter_name: str = ""
    adapter_version: str = "1.0.0"
    adapter_type: str = "function"
    role: str = "target"


class LogEvidence(BaseModel):
    """Standard and application log evidence."""
    stdout_log: Optional[str] = None
    stderr_log: Optional[str] = None
    application_log: Optional[str] = None
    adapter_log: Optional[str] = None
    startup_log: Optional[str] = None
    shutdown_log: Optional[str] = None
    log_status: EvidenceCaptureStatus = EvidenceCaptureStatus.CAPTURED


class TraceEvent(BaseModel):
    """Lightweight lifecycle or invocation event."""
    event_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sequence: int = 0
    event_type: str  # e.g., "START", "READY", "EXECUTE", "COLLECT", "STOP", "CLEANUP"
    source: str = "coordinator"
    details: dict[str, Any] = Field(default_factory=dict)


class TraceEvidence(BaseModel):
    """Sequence of timeline events for a run."""
    events: list[TraceEvent] = Field(default_factory=list)


class FileStateSnapshot(BaseModel):
    """Snapshot of a single filesystem path before or after execution."""
    path: str
    exists: bool = False
    is_file: bool = True
    size_bytes: int = 0
    sha256_hash: Optional[str] = None
    modified_at: Optional[str] = None


class FileEvidence(BaseModel):
    """Filesystem state capture across configured safe paths."""
    configured_paths: list[str] = Field(default_factory=list)
    before_state: dict[str, FileStateSnapshot] = Field(default_factory=dict)
    after_state: dict[str, FileStateSnapshot] = Field(default_factory=dict)
    delta_detected: bool = False
    status: EvidenceCaptureStatus = EvidenceCaptureStatus.CAPTURED


class DatabaseEvidence(BaseModel):
    """Database state snapshot capture before and after execution."""
    provider_name: str = "none"
    connection_target: Optional[str] = None
    configured_tables: list[str] = Field(default_factory=list)
    table_row_counts_before: dict[str, int] = Field(default_factory=dict)
    table_row_counts_after: dict[str, int] = Field(default_factory=dict)
    snapshot_before: Optional[dict[str, Any]] = None
    snapshot_after: Optional[dict[str, Any]] = None
    delta_detected: bool = False
    status: EvidenceCaptureStatus = EvidenceCaptureStatus.NOT_SUPPORTED
    message: str = "Database state capture not configured or not supported."


class HttpEvidence(BaseModel):
    """HTTP transaction evidence with secret-redacted headers and timing."""
    method: str = "GET"
    url_or_endpoint: str = ""
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_body: Optional[Any] = None
    response_status: Optional[int] = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    response_body: Optional[Any] = None
    latency_ms: float = 0.0
    correlation_id: Optional[str] = None


class MetadataEvidence(BaseModel):
    """Reproducibility metadata and execution configuration snapshot."""
    configuration_snapshot: dict[str, Any] = Field(default_factory=dict)
    reproducibility_metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


# ==============================================================================
# Atomic Evidence Record
# ==============================================================================

class EvidenceRecord(BaseModel):
    """Atomic unit of behavioral evidence with deterministic cryptographic hash and unique occurrence identity."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    evidence_id: str
    session_id: str
    execution_id: str = ""
    application_id: str = ""
    role: str = "target"
    input_id: Optional[str] = None
    evidence_type: EvidenceType
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sequence: int = 0
    source: str = "adapter"
    payload: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = ""
    size_bytes: int = 0
    capture_status: EvidenceCaptureStatus = EvidenceCaptureStatus.CAPTURED
    persistence_status: EvidencePersistenceStatus = EvidencePersistenceStatus.NOT_AVAILABLE
    provenance: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if not self.content_hash and self.payload:
            object.__setattr__(self, "content_hash", compute_content_hash(self.payload))
        if not self.size_bytes and self.payload:
            s = json.dumps(self.payload, sort_keys=True, separators=(",", ":"), default=str)
            object.__setattr__(self, "size_bytes", len(s.encode("utf-8")))


# ==============================================================================
# Evidence Manifest & Bundle
# ==============================================================================

class EvidenceManifestItem(BaseModel):
    """Summary item inside the EvidenceManifest."""
    evidence_id: str
    evidence_type: EvidenceType
    role: str
    input_id: Optional[str] = None
    content_hash: str
    size_bytes: int
    capture_status: EvidenceCaptureStatus
    persistence_status: EvidencePersistenceStatus = EvidencePersistenceStatus.PERSISTED


class EvidenceManifest(BaseModel):
    """Cryptographic manifest cataloging all evidence items in an execution bundle."""
    session_id: str
    correlation_id: str
    application_id: str
    input_set_id: str
    input_set_hash: str
    items: list[EvidenceManifestItem] = Field(default_factory=list)
    total_evidence_count: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    bundle_hash: str = ""

    def compute_bundle_hash(self) -> str:
        """Computes deterministic SHA-256 digest over the ordered manifest items."""
        ordered = [
            {
                "evidence_id": item.evidence_id,
                "evidence_type": item.evidence_type.value,
                "role": item.role,
                "input_id": item.input_id,
                "content_hash": item.content_hash,
                "size_bytes": item.size_bytes,
                "capture_status": item.capture_status.value,
                "persistence_status": item.persistence_status.value,
            }
            for item in sorted(self.items, key=lambda x: x.evidence_id)
        ]
        payload = {
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "input_set_id": self.input_set_id,
            "input_set_hash": self.input_set_hash,
            "items": ordered,
        }
        return compute_content_hash(payload)

    def model_post_init(self, __context: Any) -> None:
        if not self.total_evidence_count:
            object.__setattr__(self, "total_evidence_count", len(self.items))
        if not self.bundle_hash:
            object.__setattr__(self, "bundle_hash", self.compute_bundle_hash())


class EvidenceBundle(BaseModel):
    """Complete, self-contained evidence package for an execution session."""
    bundle_id: str
    session_id: str
    correlation_id: str
    application_id: str
    input_set_id: str
    reference_execution_ids: list[str] = Field(default_factory=list)
    target_execution_ids: list[str] = Field(default_factory=list)
    manifest: EvidenceManifest
    bundle_hash: str = ""
    records: list[EvidenceRecord] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_partial: bool = False
    persistence_status: EvidencePersistenceStatus = EvidencePersistenceStatus.NOT_AVAILABLE
    persistence_error: Optional[str] = None
    error_summary: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        if not self.bundle_hash and self.manifest:
            object.__setattr__(self, "bundle_hash", self.manifest.bundle_hash)


class EvidenceConfiguration(BaseModel):
    """Declarative configuration selecting which evidence categories to capture."""
    capture_output: bool = True
    capture_logs: bool = True
    capture_http: bool = True
    capture_filesystem: bool = False
    capture_database: bool = False
    capture_traces: bool = True
    capture_runtime: bool = True
    filesystem_paths: list[str] = Field(default_factory=list)
    database_config: Optional[dict[str, Any]] = None
