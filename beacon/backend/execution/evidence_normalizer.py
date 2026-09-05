"""BEACON V2 — Phase 3 Evidence Normalization & Hashing Layer.

Normalizes raw execution observations and provider telemetry into canonical, secret-redacted,
content-addressed EvidenceRecord items with distinct occurrence identities, and compiles
tamper-evident EvidenceManifests with aggregate bundle hashes.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Optional
from pydantic import BaseModel

from common.contracts import Observation
from .evidence_models import (
    EvidenceBundle,
    EvidenceCaptureStatus,
    EvidenceConfiguration,
    EvidenceManifest,
    EvidenceManifestItem,
    EvidencePersistenceStatus,
    EvidenceRecord,
    EvidenceType,
    compute_content_hash,
)
from .security import SecretRedactor

logger = logging.getLogger("beacon.execution.evidence_normalizer")


class EvidenceNormalizer:
    """Standardizes heterogeneous evidence into canonical, tamper-evident records."""

    @classmethod
    def normalize_record(
        cls,
        evidence_type: EvidenceType,
        payload: Any,
        session_id: str,
        execution_id: str = "",
        application_id: str = "",
        role: str = "target",
        input_id: Optional[str] = None,
        sequence: int = 0,
        source: str = "adapter",
        capture_status: EvidenceCaptureStatus = EvidenceCaptureStatus.CAPTURED,
        persistence_status: EvidencePersistenceStatus = EvidencePersistenceStatus.NOT_AVAILABLE,
        provenance: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
        evidence_id: Optional[str] = None,
    ) -> EvidenceRecord:
        """Sanitizes, hashes, and canonicalizes a single evidence item into an EvidenceRecord.
        
        Guarantees:
        - Evidence Identity is separated from Content Integrity.
        - Two distinct evidence occurrences never collide in ID just because payloads match.
        """
        raw_dict = payload.model_dump() if hasattr(payload, "model_dump") else (
            dict(payload) if isinstance(payload, dict) else {"content": payload}
        )

        # 1. Apply Secret Redaction
        safe_payload = SecretRedactor.redact(raw_dict)
        if not isinstance(safe_payload, dict):
            safe_payload = {"content": safe_payload}

        # 2. Canonical JSON Serialization for deterministic content hashing
        canonical_str = json.dumps(safe_payload, sort_keys=True, separators=(",", ":"), default=str)
        content_hash = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
        size_bytes = len(canonical_str.encode("utf-8"))

        # 3. Unique Occurrence Evidence ID (Distinct from Content Hash)
        if not evidence_id:
            role_tag = (role or "tgt")[:3].lower()
            type_tag = evidence_type.value[:3].lower()
            occurrence_raw = f"{session_id}:{execution_id}:{role}:{input_id or ''}:{evidence_type.value}:{sequence}"
            occurrence_digest = hashlib.sha256(occurrence_raw.encode("utf-8")).hexdigest()[:12]
            ev_id = f"EVID-{role_tag}-{type_tag}-{sequence:03d}-{occurrence_digest}"
        else:
            ev_id = evidence_id

        now_iso = datetime.now(timezone.utc).isoformat()
        prov = SecretRedactor.redact(provenance or {})
        meta = SecretRedactor.redact(metadata or {})

        return EvidenceRecord(
            evidence_id=ev_id,
            session_id=session_id,
            execution_id=execution_id,
            application_id=application_id,
            role=role,
            input_id=input_id,
            evidence_type=evidence_type,
            timestamp=now_iso,
            sequence=sequence,
            source=source,
            payload=safe_payload,
            content_hash=content_hash,
            size_bytes=size_bytes,
            capture_status=capture_status,
            persistence_status=persistence_status,
            provenance=prov if isinstance(prov, dict) else {},
            metadata=meta if isinstance(meta, dict) else {},
        )

    @classmethod
    def compile_manifest(
        cls,
        session_id: str,
        correlation_id: str,
        application_id: str,
        input_set_id: str,
        input_set_hash: str,
        records: list[EvidenceRecord],
    ) -> EvidenceManifest:
        """Constructs an EvidenceManifest and computes the aggregate SHA-256 bundle hash."""
        manifest_items: list[EvidenceManifestItem] = []
        for r in records:
            manifest_items.append(
                EvidenceManifestItem(
                    evidence_id=r.evidence_id,
                    evidence_type=r.evidence_type,
                    role=r.role,
                    input_id=r.input_id,
                    content_hash=r.content_hash,
                    size_bytes=r.size_bytes,
                    capture_status=r.capture_status,
                    persistence_status=r.persistence_status,
                )
            )

        manifest = EvidenceManifest(
            session_id=session_id,
            correlation_id=correlation_id,
            application_id=application_id,
            input_set_id=input_set_id,
            input_set_hash=input_set_hash,
            items=manifest_items,
            total_evidence_count=len(manifest_items),
        )
        return manifest

    @classmethod
    def build_bundle(
        cls,
        session_id: str,
        correlation_id: str,
        application_id: str,
        input_set_id: str,
        input_set_hash: str,
        records: list[EvidenceRecord],
        reference_execution_ids: Optional[list[str]] = None,
        target_execution_ids: Optional[list[str]] = None,
        is_partial: bool = False,
        persistence_status: EvidencePersistenceStatus = EvidencePersistenceStatus.NOT_AVAILABLE,
        persistence_error: Optional[str] = None,
        error_summary: Optional[str] = None,
    ) -> EvidenceBundle:
        """Assembles and signs a complete EvidenceBundle."""
        manifest = cls.compile_manifest(
            session_id=session_id,
            correlation_id=correlation_id,
            application_id=application_id,
            input_set_id=input_set_id,
            input_set_hash=input_set_hash,
            records=records,
        )

        bundle_id = f"BNDL-{manifest.bundle_hash[:12]}"
        return EvidenceBundle(
            bundle_id=bundle_id,
            session_id=session_id,
            correlation_id=correlation_id,
            application_id=application_id,
            input_set_id=input_set_id,
            reference_execution_ids=reference_execution_ids or [],
            target_execution_ids=target_execution_ids or [],
            manifest=manifest,
            bundle_hash=manifest.bundle_hash,
            records=records,
            is_partial=is_partial,
            persistence_status=persistence_status,
            persistence_error=persistence_error,
            error_summary=error_summary,
        )


evidence_normalizer = EvidenceNormalizer()
