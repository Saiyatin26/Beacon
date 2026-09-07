"""BEACON V2 -- Phase 4 Evidence Compatibility Layer.

Provides test-compatible payload models and simplified EvidenceBundle/EvidenceManifest/EvidenceRecord
wrappers that the Phase 4 evaluation test suite imports from ``execution.evidence``.

The canonical Phase 3 models live in ``execution.evidence_models``.  This module
re-exports them under the names expected by Phase 4 tests and adds lightweight
typed payload wrappers (OutputEvidencePayload, ErrorEvidencePayload,
TraceEvidencePayload) that map cleanly onto the underlying evidence records.
"""

from __future__ import annotations

from typing import Any, Optional, Union
from pydantic import BaseModel, Field

from .evidence_models import (
    # Re-export canonical evidence models
    DatabaseEvidence,
    ErrorEvidence,
    EvidenceCaptureStatus,
    EvidenceConfiguration,
    EvidenceManifest as _CanonicalEvidenceManifest,
    EvidenceManifestItem,
    EvidencePersistenceStatus,
    EvidenceRecord as _CanonicalEvidenceRecord,
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

# Re-export EvidenceBundle from canonical module (it's the same model)
from .evidence_models import EvidenceBundle


# ---------------------------------------------------------------------------
# Typed payload wrappers for Phase 4 tests
# ---------------------------------------------------------------------------

class OutputEvidencePayload(BaseModel):
    """Typed output payload wrapper used in Phase 4 evaluation tests.

    Maps to ``OutputEvidence`` but uses test-friendly field names.
    """
    status_code: Optional[int] = 200
    raw_output: Optional[Any] = None
    normalized_output: Optional[Any] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
    duration_ms: float = 0.0
    evidence_id: Optional[str] = None


class ErrorEvidencePayload(BaseModel):
    """Typed error payload wrapper used in Phase 4 evaluation tests.

    Maps to ``ErrorEvidence`` but exposes test-friendly fields
    (error_message, error_category, status_code, error_code).
    """
    error_message: str = ""
    error_category: str = "APPLICATION_ERROR"
    status_code: Optional[int] = None
    error_code: Optional[str] = None
    exception_type: Optional[str] = None
    stack_trace: Optional[str] = None
    evidence_id: Optional[str] = None


class TraceEvidencePayload(BaseModel):
    """Typed trace payload wrapper used in Phase 4 evaluation tests.

    Exposes a ``call_sequence`` list of operation names and a ``span_count``
    in addition to a compatible ``events`` property for WorkflowEvaluator.
    """
    call_sequence: list[str] = Field(default_factory=list)
    span_count: int = 0
    evidence_id: Optional[str] = None

    @property
    def events(self) -> list[str]:
        """Expose call_sequence as ``events`` for WorkflowEvaluator compatibility."""
        return self.call_sequence


# ---------------------------------------------------------------------------
# Lightweight EvidenceRecord that accepts AdapterRole enum for ``role``
# ---------------------------------------------------------------------------

class EvidenceRecord(_CanonicalEvidenceRecord):
    """Phase 4 EvidenceRecord that accepts both string and AdapterRole enum values for
    the ``role`` field, and exposes ``payload_hash`` as an alias for ``content_hash``
    to support tamper-detection tests.
    """

    @property
    def payload_hash(self) -> str:
        """Alias for content_hash used in tamper-detection tests."""
        return self.content_hash

    @payload_hash.setter
    def payload_hash(self, value: str) -> None:
        """Allow tests to tamper with the payload hash."""
        object.__setattr__(self, "content_hash", value)

    def model_post_init(self, __context: Any) -> None:
        # Normalise AdapterRole enum to string for the canonical model
        role_val = self.role
        if hasattr(role_val, "value"):
            object.__setattr__(self, "role", role_val.value)
        super().model_post_init(__context)


# ---------------------------------------------------------------------------
# Simplified EvidenceManifest compatible with test construction pattern:
#   EvidenceManifest(session_id=..., application_id=..., records=[...])
# ---------------------------------------------------------------------------

class EvidenceManifest(BaseModel):
    """Simplified EvidenceManifest for Phase 4 test usage.

    The canonical Phase 3 EvidenceManifest requires ``correlation_id``,
    ``input_set_id``, and ``input_set_hash``.  This simplified version is
    constructed from just session_id, application_id, and a records list,
    making it suitable for Phase 4 unit tests that don't need full Phase 3
    plumbing.
    """
    session_id: str
    application_id: str = ""
    records: list[Any] = Field(default_factory=list)
    bundle_hash: str = ""
    total_evidence_count: int = 0

    def compute_bundle_hash(self) -> str:
        """Compute a deterministic hash over the manifest records."""
        import hashlib
        import json
        ordered = [
            {
                "evidence_id": r.evidence_id,
                "evidence_type": r.evidence_type.value if hasattr(r.evidence_type, "value") else str(r.evidence_type),
                "role": r.role if isinstance(r.role, str) else getattr(r.role, "value", str(r.role)),
                "input_id": r.input_id,
                "content_hash": r.content_hash,
            }
            for r in sorted(self.records, key=lambda x: x.evidence_id)
        ]
        payload = {
            "session_id": self.session_id,
            "application_id": self.application_id,
            "records": ordered,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def model_post_init(self, __context: Any) -> None:
        if not self.total_evidence_count:
            object.__setattr__(self, "total_evidence_count", len(self.records))
        if not self.bundle_hash:
            object.__setattr__(self, "bundle_hash", self.compute_bundle_hash())


# ---------------------------------------------------------------------------
# Phase 4 EvidenceBundle that works with the simplified EvidenceManifest
# ---------------------------------------------------------------------------

class EvidenceBundle(BaseModel):
    """Phase 4 EvidenceBundle that accepts the simplified EvidenceManifest
    and populates the bundle_hash from the manifest.

    Compatible with both test construction and BehavioralEvaluationEngine.
    """
    bundle_id: str
    session_id: str
    application_id: str = ""
    manifest: Any  # accepts both canonical and simplified EvidenceManifest
    records: list[Any] = Field(default_factory=list)
    bundle_hash: str = ""
    created_at: str = ""
    is_partial: bool = False
    persistence_status: Any = None
    persistence_error: Optional[str] = None
    error_summary: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        if not self.bundle_hash and self.manifest:
            bh = getattr(self.manifest, "bundle_hash", None)
            if not bh and hasattr(self.manifest, "compute_bundle_hash"):
                bh = self.manifest.compute_bundle_hash()
            object.__setattr__(self, "bundle_hash", bh or "")


__all__ = [
    # Canonical re-exports
    "DatabaseEvidence",
    "ErrorEvidence",
    "EvidenceCaptureStatus",
    "EvidenceConfiguration",
    "EvidenceManifestItem",
    "EvidencePersistenceStatus",
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
    # Phase 4 models
    "EvidenceBundle",
    "EvidenceManifest",
    "EvidenceRecord",
    "OutputEvidencePayload",
    "ErrorEvidencePayload",
    "TraceEvidencePayload",
]
