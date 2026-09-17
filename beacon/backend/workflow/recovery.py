"""BEACON V2 — Phase 11 Workflow Recovery & Restart Service.

Provides safe recovery from process interruptions with strict, end-to-end
cryptographic authority chain verification and zero lossy reconstruction.
"""

from datetime import datetime, timezone
import logging
from typing import Optional

from certification.models import verify_artifact_integrity
from certification.repository import CertificationRepository, certification_repository
from .models import WorkflowErrorCode, WorkflowRun, WorkflowState
from .persistence import WorkflowPersistenceStore, workflow_persistence

logger = logging.getLogger("beacon.workflow.recovery")


class WorkflowRecoveryService:
    """Recovers interrupted workflow runs safely and deterministically by validating the complete authority chain."""

    def __init__(
        self,
        persistence: Optional[WorkflowPersistenceStore] = None,
        cert_repo: Optional[CertificationRepository] = None,
    ):
        self.persistence = persistence or workflow_persistence
        self.cert_repo = cert_repo or certification_repository

    def recover_interrupted_workflows(self) -> list[WorkflowRun]:
        """Audits and resolves any inflight/interrupted workflow runs left in unfinalized states."""
        interrupted = self.persistence.list_interrupted_runs()
        resolved_runs: list[WorkflowRun] = []

        for run in interrupted:
            logger.info(f"Auditing interrupted workflow run '{run.workflow_run_id}' (state: {run.state.value})...")
            
            is_valid_chain, failure_reason = self.verify_authority_chain(run)

            if is_valid_chain:
                # Valid unbroken authoritative chain exists; safely finalize run
                art = self.cert_repo.get_artifact(run.certification_id)
                status_str = art.status.value if hasattr(art.status, "value") else str(art.status)
                run.state = WorkflowState.COMPLETED
                run.certification_status = status_str
                run.certification_score = art.score
                run.completed_at = datetime.now(timezone.utc).isoformat()
                run.metadata["recovery_note"] = "Recovered after full cryptographic authority chain verification."
                logger.info(f"Recovered workflow run '{run.workflow_run_id}' as COMPLETED (status: {status_str}).")
            else:
                # Incomplete or broken authority chain: mark as FAILED (Fail-Closed)
                run.state = WorkflowState.FAILED
                run.error_code = WorkflowErrorCode.RECOVERY_FAILED
                run.error_message = f"Recovery failed-closed: {failure_reason}"
                run.completed_at = datetime.now(timezone.utc).isoformat()
                logger.warning(f"Marked incomplete workflow run '{run.workflow_run_id}' as FAILED: {failure_reason}")

            updated = self.persistence.save_run(run)
            resolved_runs.append(updated)

        return resolved_runs

    def verify_authority_chain(self, run: WorkflowRun) -> tuple[bool, str]:
        """Verifies the complete unbroken cryptographic authority chain for a workflow run."""
        # 1. Certification ID must be present
        if not run.certification_id:
            return False, "Missing certification_id (workflow interrupted before certification)."

        # 2. Certification Artifact must exist in repository
        try:
            art = self.cert_repo.get_artifact(run.certification_id)
        except Exception as exc:
            return False, f"Failed to retrieve CertificationArtifact '{run.certification_id}': {str(exc)}"

        if not art or not art.certification_id:
            return False, f"CertificationArtifact '{run.certification_id}' not found in repository."

        # 3. Artifact content hash integrity verification
        if not verify_artifact_integrity(art):
            return False, f"CertificationArtifact '{run.certification_id}' failed cryptographic content hash verification."

        # 4. Threshold Resolution identity and fingerprint verification
        art_thresh_id = art.threshold_resolution_id or (art.context.threshold_resolution_id if art.context else None)
        art_thresh_fp = art.threshold_resolution_fingerprint or (art.context.threshold_resolution_fingerprint if art.context else None)

        if not run.threshold_resolution_id or run.threshold_resolution_id != art_thresh_id:
            return False, f"ThresholdResolution ID mismatch between run and artifact ('{run.threshold_resolution_id}' vs '{art_thresh_id}')."

        if not run.threshold_resolution_fingerprint or run.threshold_resolution_fingerprint != art_thresh_fp:
            return False, f"ThresholdResolution fingerprint mismatch between run and artifact."

        # 5. Oracle Set identity and hash verification
        if run.oracle_set_id and art.oracle_set_id and run.oracle_set_id != art.oracle_set_id:
            return False, f"OracleSet ID mismatch between run and artifact ('{run.oracle_set_id}' vs '{art.oracle_set_id}')."

        if run.oracle_set_hash and art.oracle_set_hash and run.oracle_set_hash != art.oracle_set_hash:
            return False, f"OracleSet hash mismatch between run and artifact."

        # 6. Evaluation result identity verification
        if not run.evaluation_id:
            return False, "Missing evaluation_id in workflow run."

        # 7. Certification cases verification
        try:
            cases = self.cert_repo.list_certification_cases(run.certification_id)
            if not cases or len(cases) == 0:
                return False, f"No persisted CertificationCase records found for certificate '{run.certification_id}'."
        except Exception as exc:
            return False, f"Failed to verify persisted CertificationCase records: {str(exc)}"

        return True, "Authority chain verified."


workflow_recovery = WorkflowRecoveryService()
