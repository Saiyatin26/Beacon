"""BEACON V2 — Phase 6 Observation Matrix Builder.

Transforms Phase 3 EvidenceBundle records into a strongly typed, role-partitioned ObservationMatrix
for consumption by candidate rule and invariant generators.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Optional

from evaluation.input_adapter import CorrelatedInputItem, evaluation_input_adapter
from execution.evidence_models import (
    EvidenceBundle,
    EvidenceCaptureStatus,
    EvidenceType,
)
from rules.engine import _is_valid_db_snapshots, _is_valid_db_row_counts
from .models import ObservationFact, ObservationMatrix

logger = logging.getLogger("beacon.discovery.matrix")


class ObservationMatrixBuilder:
    """Extracts and normalizes behavioral facts across Reference and Target execution evidence."""

    def build_matrix(
        self,
        bundle: EvidenceBundle,
        phase4_result: Optional[Any] = None,
    ) -> ObservationMatrix:
        """Constructs an ObservationMatrix from a tamper-evident EvidenceBundle.

        Args:
            bundle: Phase 3 EvidenceBundle.
            phase4_result: Optional Phase 4 EvaluationResult.

        Returns:
            ObservationMatrix with partitioned reference and target facts.
        """
        correlated_items, _ = evaluation_input_adapter.adapt_bundle(bundle=bundle, verify_integrity=False)

        ref_facts: list[ObservationFact] = []
        tgt_facts: list[ObservationFact] = []

        for item in correlated_items:
            ref_fact = self._extract_fact(item, is_reference=True)
            tgt_fact = self._extract_fact(item, is_reference=False)

            if ref_fact is not None:
                ref_facts.append(ref_fact)
            if tgt_fact is not None:
                tgt_facts.append(tgt_fact)

        # Sort facts deterministically by input_id
        ref_facts.sort(key=lambda x: x.input_id)
        tgt_facts.sort(key=lambda x: x.input_id)

        session_id = getattr(bundle, "session_id", "default_session")
        app_id = getattr(bundle, "application_id", "default_app")

        return ObservationMatrix(
            session_id=session_id,
            application_id=app_id,
            reference_facts=ref_facts,
            target_facts=tgt_facts,
            total_inputs=len(correlated_items),
        )

    def _extract_fact(
        self,
        item: CorrelatedInputItem,
        is_reference: bool,
    ) -> Optional[ObservationFact]:
        """Extracts an ObservationFact for a given role from a correlated input item."""
        role_str = "reference" if is_reference else "target"
        recs = item.reference_records if is_reference else item.target_records

        if not recs and not is_reference:
            # If target records are missing entirely
            return None
        if not recs and is_reference:
            return None

        evidence_ids = [getattr(r, "evidence_id", "") for r in recs if getattr(r, "evidence_id", "")]

        # 1. Canonical Input Data
        input_data: dict[str, Any] = {}
        if hasattr(item, "input_data") and isinstance(item.input_data, dict):
            input_data.update(item.input_data)

        # 2. Output Data
        out = item.reference_output if is_reference else item.target_output
        output_data: dict[str, Any] = {}
        raw_output = None
        exit_code = None
        http_status = None

        if out is not None:
            raw_output = getattr(out, "raw_output", None)
            exit_code = getattr(out, "exit_code", None)
            http_status = getattr(out, "http_status", None)
            norm = getattr(out, "normalized_output", {})
            if isinstance(norm, dict):
                output_data.update(norm)
            if isinstance(raw_output, dict):
                output_data.update(raw_output)

        # 3. Error Data
        err = item.reference_error if is_reference else item.target_error
        has_error = False
        error_data: dict[str, Any] = {}

        if err is not None:
            has_error = True
            error_data["category"] = getattr(err, "category", "APPLICATION_ERROR")
            error_data["message"] = getattr(err, "message", "")
            error_data["exception_type"] = getattr(err, "exception_type", None)
        elif exit_code is not None and exit_code != 0:
            has_error = True
            error_data["category"] = "PROCESS_ERROR"
            error_data["exit_code"] = exit_code
        elif http_status is not None and http_status >= 400:
            has_error = True
            error_data["category"] = "HTTP_ERROR"
            error_data["http_status"] = http_status

        # 4. Database & Filesystem State (Strict Phase 3 contract)
        db = item.reference_database if is_reference else item.target_database
        fs = item.reference_file if is_reference else item.target_file

        state_before: Optional[dict[str, Any]] = None
        state_after: Optional[dict[str, Any]] = None
        state_mutated = False
        state_valid = False

        if db is not None:
            b_db = getattr(db, "snapshot_before", None)
            a_db = getattr(db, "snapshot_after", None)
            if _is_valid_db_snapshots(b_db, a_db):
                state_valid = True
                state_before = b_db
                state_after = a_db
                if b_db != a_db:
                    state_mutated = True
            elif _is_valid_db_row_counts(getattr(db, "table_row_counts_before", None), getattr(db, "table_row_counts_after", None)):
                state_valid = True
                state_before = getattr(db, "table_row_counts_before", {})
                state_after = getattr(db, "table_row_counts_after", {})
                if state_before != state_after:
                    state_mutated = True

        if fs is not None and not state_valid:
            b_fs = getattr(fs, "before_state", None)
            a_fs = getattr(fs, "after_state", None)
            if b_fs is not None and a_fs is not None and (b_fs or a_fs):
                state_valid = True
                state_before = b_fs if isinstance(b_fs, dict) else {}
                state_after = a_fs if isinstance(a_fs, dict) else {}
                if state_before != state_after:
                    state_mutated = True

        # Check raw database records if not populated by typed model
        if not state_valid:
            for r in recs:
                if getattr(r, "evidence_type", None) == EvidenceType.DATABASE and isinstance(r.payload, dict):
                    p = r.payload
                    b_raw = p.get("snapshot_before")
                    a_raw = p.get("snapshot_after")
                    if _is_valid_db_snapshots(b_raw, a_raw):
                        state_valid = True
                        state_before = b_raw
                        state_after = a_raw
                        if b_raw != a_raw:
                            state_mutated = True
                        break

        # 5. Workflow Trace Events
        tr = item.reference_trace if is_reference else item.target_trace
        workflow_events: list[str] = []
        if tr is not None:
            evs = getattr(tr, "events", [])
            for e in evs:
                et = getattr(e, "event_type", None) or (e.get("event_type") if isinstance(e, dict) else None)
                if et:
                    workflow_events.append(str(et))

        # Check raw trace records
        if not workflow_events:
            for r in recs:
                if getattr(r, "evidence_type", None) == EvidenceType.TRACE and isinstance(r.payload, dict):
                    raw_evs = r.payload.get("events", [])
                    if isinstance(raw_evs, list):
                        for e in raw_evs:
                            et = e.get("event_type") if isinstance(e, dict) else getattr(e, "event_type", None)
                            if et:
                                workflow_events.append(str(et))

        # 6. Metadata
        metadata_data: dict[str, Any] = {}
        for r in recs:
            if hasattr(r, "metadata") and isinstance(r.metadata, dict):
                metadata_data.update(r.metadata)
            if hasattr(r, "provenance") and isinstance(r.provenance, dict):
                metadata_data.update(r.provenance)

        # 7. Check for adaptation failures or invalid capture status
        adaptation_failure = None
        if hasattr(item, "adaptation_failures") and item.adaptation_failures:
            for af in item.adaptation_failures:
                if getattr(af, "role", "") == role_str:
                    adaptation_failure = getattr(af, "reason", "Adaptation failed")
                    break

        status_val = "CAPTURED"
        for r in recs:
            st = getattr(r, "capture_status", getattr(r, "status", None))
            if st and str(st).upper() in ("FAILED", "PARTIAL", "NOT_SUPPORTED", "NOT_AVAILABLE"):
                status_val = str(st).upper()
                break

        return ObservationFact(
            input_id=item.input_id,
            role=role_str,
            evidence_ids=evidence_ids,
            input_data=input_data,
            output_data=output_data,
            raw_output=raw_output,
            exit_code=exit_code,
            http_status=http_status,
            has_error=has_error,
            error_data=error_data,
            state_before=state_before,
            state_after=state_after,
            state_mutated=state_mutated,
            state_valid=state_valid,
            workflow_events=workflow_events,
            metadata_data=metadata_data,
            capture_status=status_val,
            is_valid=(adaptation_failure is None and status_val == "CAPTURED"),
            adaptation_failure=adaptation_failure,
        )


observation_matrix_builder = ObservationMatrixBuilder()
