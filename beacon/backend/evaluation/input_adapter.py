"""BEACON V2 — Phase 4 Evaluation Input Adapter.

Extracts, correlates, validates cryptographic integrity, and normalizes Phase 3
evidence records and bundles for consumption by dimension evaluators.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Optional, Union
from pydantic import BaseModel, Field

from execution.evidence_models import (
    DatabaseEvidence,
    ErrorEvidence,
    EvidenceType,
    FileEvidence,
    HttpEvidence,
    LogEvidence,
    OutputEvidence,
    TraceEvidence,
    compute_content_hash,
)
# Accept any EvidenceBundle/EvidenceRecord-like objects via duck-typing.
# The shim in execution.evidence and canonical execution.evidence_models both work.

logger = logging.getLogger("beacon.evaluation.input_adapter")


class AdaptationFailure(BaseModel):
    """Preserves identity and failure context for evidence records that failed typed adaptation."""
    evidence_id: Optional[str] = None
    input_id: str
    role: str
    evidence_type: str
    capture_status: Optional[str] = None
    reason: str


def normalize_role(role: Any) -> Optional[str]:
    """Normalizes role into 'reference', 'target', or None if invalid/unknown."""
    if role is None:
        return None
    r_str = str(getattr(role, "value", role)).strip().lower()
    if r_str in ("reference", "legacy", "ref", "adapterrole.reference"):
        return "reference"
    if r_str in ("target", "modern", "tgt", "adapterrole.target"):
        return "target"
    return None


class CorrelatedInputItem(BaseModel):
    """Holds correlated Reference and Target evidence records for a specific canonical input_id."""
    input_id: str
    reference_records: list[Any] = Field(default_factory=list)
    target_records: list[Any] = Field(default_factory=list)
    invalid_records: list[Any] = Field(default_factory=list)
    adaptation_failures: list[AdaptationFailure] = Field(default_factory=list)
    invalid_role_records: list[str] = Field(default_factory=list)

    reference_output: Optional[OutputEvidence] = None
    target_output: Optional[OutputEvidence] = None
    reference_output_status: Optional[str] = None
    target_output_status: Optional[str] = None

    reference_error: Optional[ErrorEvidence] = None
    target_error: Optional[ErrorEvidence] = None
    reference_error_status: Optional[str] = None
    target_error_status: Optional[str] = None

    reference_database: Optional[DatabaseEvidence] = None
    target_database: Optional[DatabaseEvidence] = None
    reference_database_status: Optional[str] = None
    target_database_status: Optional[str] = None

    reference_file: Optional[FileEvidence] = None
    target_file: Optional[FileEvidence] = None
    reference_file_status: Optional[str] = None
    target_file_status: Optional[str] = None

    reference_http: Optional[HttpEvidence] = None
    target_http: Optional[HttpEvidence] = None
    reference_http_status: Optional[str] = None
    target_http_status: Optional[str] = None

    reference_trace: Optional[TraceEvidence] = None
    target_trace: Optional[TraceEvidence] = None
    reference_trace_status: Optional[str] = None
    target_trace_status: Optional[str] = None

    boundary_category: Optional[str] = None
    is_matched: bool = True
    has_missing_target: bool = False
    is_extra_target: bool = False
    integrity_valid: bool = True
    integrity_error: Optional[str] = None


class EvaluationInputAdapter:
    """Adapts and correlates Phase 3 EvidenceBundle records by input_id and role."""

    def adapt_bundle(
        self,
        bundle: Any,
        verify_integrity: bool = True,
    ) -> tuple[list[CorrelatedInputItem], list[str]]:
        """Correlates evidence records into matched input pairs, verifying tamper-evidence if requested.

        Returns:
            tuple of (list of CorrelatedInputItem, list of error/warning messages)
        """
        issues: list[str] = []

        # 1. Cryptographic Manifest & Bundle Integrity Verification
        if verify_integrity:
            if bundle.manifest:
                recomputed_bundle_hash = bundle.manifest.compute_bundle_hash()
                if bundle.bundle_hash and bundle.bundle_hash != recomputed_bundle_hash:
                    err = (
                        f"TAMPER DETECTED in bundle '{bundle.bundle_id}'! "
                        f"Expected: {bundle.bundle_hash}, Recomputed: {recomputed_bundle_hash}"
                    )
                    logger.error(err)
                    issues.append(err)

            # Check individual record content hashes (regardless of payload truthiness)
            for rec in bundle.records:
                if rec.content_hash:
                    payload_data = rec.payload if rec.payload is not None else {}
                    canonical = json.dumps(payload_data, sort_keys=True, separators=(",", ":"), default=str)
                    recomputed_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                    if recomputed_hash != rec.content_hash:
                        rec_err = (
                            f"TAMPER DETECTED: Content hash mismatch for record '{rec.evidence_id}' "
                            f"(input: {rec.input_id}, role: {rec.role})!"
                        )
                        logger.error(rec_err)
                        issues.append(rec_err)

        # 2. Segregate records by input_id and role (fail-closed on invalid role)
        input_groups: dict[str, dict[str, list[Any]]] = {}

        for rec in bundle.records:
            inp_id = rec.input_id or "unspecified_input"
            if inp_id not in input_groups:
                input_groups[inp_id] = {"reference": [], "target": [], "invalid": []}

            role_norm = normalize_role(getattr(rec, "role", None))
            if role_norm is None:
                err_msg = (
                    f"INVALID_ROLE: Record '{getattr(rec, 'evidence_id', 'unknown')}' "
                    f"has invalid or unsupported role '{getattr(rec, 'role', None)}' (input: {inp_id})"
                )
                logger.error(err_msg)
                issues.append(err_msg)
                input_groups[inp_id]["invalid"].append(rec)
            else:
                input_groups[inp_id][role_norm].append(rec)

        correlated_items: list[CorrelatedInputItem] = []

        for inp_id, roles in input_groups.items():
            ref_recs = roles["reference"]
            target_recs = roles["target"]
            invalid_recs = roles["invalid"]

            item = CorrelatedInputItem(
                input_id=inp_id,
                reference_records=ref_recs,
                target_records=target_recs,
                invalid_records=invalid_recs,
            )

            # Check if any record in this input has an invalid role
            if invalid_recs:
                item.integrity_valid = False
                for inv_rec in invalid_recs:
                    eid = getattr(inv_rec, "evidence_id", "unknown")
                    item.invalid_role_records.append(eid)
                item.integrity_error = f"Invalid role records detected: {item.invalid_role_records}"

            # Check if any record in this input has an integrity failure reported in issues
            if any(f"(input: {inp_id}" in issue for issue in issues):
                item.integrity_valid = False
                if not item.integrity_error:
                    item.integrity_error = "Record tamper detected for this input"

            # Check matching status
            if ref_recs and not target_recs:
                item.is_matched = False
                item.has_missing_target = True
            elif target_recs and not ref_recs:
                item.is_matched = False
                item.is_extra_target = True

            # Populate typed evidence views
            for rec in ref_recs:
                self._populate_typed_evidence(item, rec, is_reference=True)

            for rec in target_recs:
                self._populate_typed_evidence(item, rec, is_reference=False)

            # Detect boundary category from explicit provenance or metadata only
            for rec in ref_recs + target_recs + invalid_recs:
                category = (
                    rec.metadata.get("boundary_category")
                    or rec.provenance.get("boundary_category")
                    or rec.metadata.get("boundary_type")
                )
                if category and category not in ("diverse_sampling", "standard", "normal"):
                    item.boundary_category = str(category)
                    break

            correlated_items.append(item)

        # Sort by input_id for deterministic order
        correlated_items.sort(key=lambda x: x.input_id)
        return correlated_items, issues

    def _populate_typed_evidence(
        self, item: CorrelatedInputItem, rec: Any, is_reference: bool
    ) -> None:
        """Parses record payload into strongly typed evidence models where available, preserving capture_status and tracking adaptation failures."""
        etype = rec.evidence_type
        payload = dict(rec.payload) if rec.payload else {}

        # Extract Phase 3 capture_status
        status_val = getattr(rec, "capture_status", getattr(rec, "status", None))
        status_str = str(getattr(status_val, "value", status_val)).upper() if status_val is not None else None

        # Handle OutputEvidencePayload field mapping:
        # OutputEvidencePayload uses 'status_code'; OutputEvidence uses 'http_status'
        if etype == EvidenceType.OUTPUT and "status_code" in payload and "http_status" not in payload:
            payload["http_status"] = payload.pop("status_code")

        try:
            if etype == EvidenceType.OUTPUT:
                out = OutputEvidence(**payload)
                if status_val is not None:
                    setattr(out, "capture_status", status_val)
                    setattr(out, "status", status_val)
                if is_reference:
                    item.reference_output = out
                    item.reference_output_status = status_str
                else:
                    item.target_output = out
                    item.target_output_status = status_str
            elif etype == EvidenceType.ERROR:
                err = ErrorEvidence(**payload)
                if status_val is not None:
                    setattr(err, "capture_status", status_val)
                    setattr(err, "status", status_val)
                if is_reference:
                    item.reference_error = err
                    item.reference_error_status = status_str
                else:
                    item.target_error = err
                    item.target_error_status = status_str
            elif etype == EvidenceType.DATABASE:
                if "status" not in payload and status_val is not None:
                    payload["status"] = status_val
                db = DatabaseEvidence(**payload)
                if status_val is not None:
                    setattr(db, "capture_status", status_val)
                    setattr(db, "status", status_val)
                if is_reference:
                    item.reference_database = db
                    item.reference_database_status = status_str
                else:
                    item.target_database = db
                    item.target_database_status = status_str
            elif etype == EvidenceType.FILESYSTEM:
                if "status" not in payload and status_val is not None:
                    payload["status"] = status_val
                fs = FileEvidence(**payload)
                if status_val is not None:
                    setattr(fs, "capture_status", status_val)
                    setattr(fs, "status", status_val)
                if is_reference:
                    item.reference_file = fs
                    item.reference_file_status = status_str
                else:
                    item.target_file = fs
                    item.target_file_status = status_str
            elif etype == EvidenceType.HTTP:
                http_ev = HttpEvidence(**payload)
                if status_val is not None:
                    setattr(http_ev, "capture_status", status_val)
                    setattr(http_ev, "status", status_val)
                if is_reference:
                    item.reference_http = http_ev
                    item.reference_http_status = status_str
                else:
                    item.target_http = http_ev
                    item.target_http_status = status_str
            elif etype == EvidenceType.TRACE:
                tr = TraceEvidence(**payload)
                if status_val is not None:
                    setattr(tr, "capture_status", status_val)
                    setattr(tr, "status", status_val)
                if is_reference:
                    item.reference_trace = tr
                    item.reference_trace_status = status_str
                else:
                    item.target_trace = tr
                    item.target_trace_status = status_str
        except Exception as exc:
            reason = f"Malformed {etype} payload: {exc}"
            logger.warning(
                f"Adaptation failure for record '{getattr(rec, 'evidence_id', 'unknown')}' "
                f"(input: {item.input_id}, role: {'reference' if is_reference else 'target'}): {reason}"
            )
            failure = AdaptationFailure(
                evidence_id=getattr(rec, "evidence_id", None),
                input_id=item.input_id,
                role="reference" if is_reference else "target",
                evidence_type=str(getattr(etype, "value", etype)),
                capture_status=status_str,
                reason=reason,
            )
            item.adaptation_failures.append(failure)


evaluation_input_adapter = EvaluationInputAdapter()

