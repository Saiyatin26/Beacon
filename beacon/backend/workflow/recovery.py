"""BEACON V2 — Phase 11 Workflow Recovery & Restart Service.

Provides safe recovery from process interruptions without reconstructing authority from lossy artifacts.
"""

from datetime import datetime, timezone
import logging
from typing import Optional

from certification.repository import CertificationRepository, certification_repository
from .models import WorkflowErrorCode, WorkflowRun, WorkflowState
from .persistence import WorkflowPersistenceStore, workflow_persistence

logger = logging.getLogger("beacon.workflow.recovery")


class WorkflowRecoveryService:
    """Recovers interrupted workflow runs safely and deterministically."""

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
            
            # Check if an authoritative certification artifact was successfully persisted
            art = None
            if run.certification_id:
                try:
                    art = self.cert_repo.get_artifact(run.certification_id)
                except Exception as exc:
                    logger.debug(f"Failed to load artifact '{run.certification_id}': {exc}")

            if art and art.certification_id:
                # Valid authoritative artifact exists; reconcile workflow run status
                status_str = art.status.value if hasattr(art.status, "value") else str(art.status)
                run.state = WorkflowState.COMPLETED
                run.certification_status = status_str
                run.certification_score = art.score
                run.completed_at = datetime.now(timezone.utc).isoformat()
                run.metadata["recovery_note"] = "Recovered from authoritative persisted CertificationArtifact."
                logger.info(f"Recovered workflow run '{run.workflow_run_id}' as COMPLETED (status: {status_str}).")
            else:
                # Incomplete state before artifact creation: mark as FAILED (Fail-Closed)
                run.state = WorkflowState.FAILED
                run.error_code = WorkflowErrorCode.RECOVERY_FAILED
                run.error_message = "Execution was interrupted before authoritative certification artifact could be finalized."
                run.completed_at = datetime.now(timezone.utc).isoformat()
                logger.warning(f"Marked incomplete workflow run '{run.workflow_run_id}' as FAILED (Fail-Closed).")

            updated = self.persistence.save_run(run)
            resolved_runs.append(updated)

        return resolved_runs


workflow_recovery = WorkflowRecoveryService()
