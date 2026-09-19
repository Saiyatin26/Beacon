"""BEACON V2 — Phase 11 Workflow Recovery & Restart Service.

Provides safe recovery from process interruptions with strict, end-to-end
cryptographic authority chain verification and zero lossy reconstruction.
"""

from datetime import datetime, timezone
import logging
from typing import Optional

from certification.models import verify_artifact_integrity
from certification.repository import CertificationRepository, certification_repository
from evaluation.models import verify_evaluation_result_integrity
from evaluation.persistence import EvaluationPersistenceStore, evaluation_persistence
from ingestion.audit import AuditAction, audit_logger
from reconciliation.persistence import ReconciliationPersistenceStore, reconciliation_persistence
from threshold.persistence import ThresholdPersistenceStore, threshold_persistence
from .idempotency import workflow_idempotency
from .models import FinalizationState, WorkflowErrorCode, WorkflowRun, WorkflowState, transition_workflow_state
from .persistence import WorkflowPersistenceStore, workflow_persistence

logger = logging.getLogger("beacon.workflow.recovery")


class WorkflowRecoveryService:
    """Recovers interrupted workflow runs safely and deterministically by validating the complete authority chain."""

    def __init__(
        self,
        persistence: Optional[WorkflowPersistenceStore] = None,
        cert_repo: Optional[CertificationRepository] = None,
        eval_persistence: Optional[EvaluationPersistenceStore] = None,
        rec_persistence: Optional[ReconciliationPersistenceStore] = None,
        thresh_persistence: Optional[ThresholdPersistenceStore] = None,
    ):
        self.persistence = persistence or workflow_persistence
        self.cert_repo = cert_repo or certification_repository
        self.eval_persistence = eval_persistence or evaluation_persistence
        self.rec_persistence = rec_persistence or reconciliation_persistence
        self.thresh_persistence = thresh_persistence or threshold_persistence

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
                run.certification_status = status_str
                run.certification_score = art.score
                run.metadata["audit_persisted"] = True
                run.metadata["recovery_note"] = "Recovered after full cryptographic authority chain and audit verification."

                # Authoritative Stage-B Idempotency Finalization
                try:
                    workflow_idempotency.finalize_stage_b(
                        execution_fingerprint=run.execution_fingerprint,
                        run_id=run.workflow_run_id,
                        status="COMPLETED",
                        finalization_state="IDEMPOTENCY_FINALIZED",
                        request_fingerprint=run.request_fingerprint,
                    )
                    run.finalization_state = FinalizationState.IDEMPOTENCY_FINALIZED
                except Exception as idemp_err:
                    logger.error(f"Recovery Stage-B finalization failed for '{run.workflow_run_id}': {idemp_err}", exc_info=True)
                    run.error_code = WorkflowErrorCode.PERSISTENCE_FAILED
                    run.error_message = f"Recovery Stage-B finalization failed: {str(idemp_err)}"
                    run.metadata["persistence_failure"] = str(idemp_err)
                    updated = self.persistence.save_run(run)
                    resolved_runs.append(updated)
                    continue

                if run.state != WorkflowState.PERSISTING:
                    transition_workflow_state(
                        run,
                        WorkflowState.PERSISTING,
                        reason="Recovery advancing verified execution to PERSISTING before finalization",
                        is_recovery=True,
                    )

                transition_workflow_state(
                    run,
                    WorkflowState.COMPLETED,
                    reason="Recovered after full cryptographic authority verification",
                    is_recovery=True,
                )
                run.finalization_state = FinalizationState.COMPLETED
                logger.info(f"Recovered workflow run '{run.workflow_run_id}' as COMPLETED (status: {status_str}).")
            else:
                # Incomplete or broken authority chain: mark as FAILED (Fail-Closed)
                run.error_code = WorkflowErrorCode.RECOVERY_FAILED
                run.error_message = f"Recovery failed-closed: {failure_reason}"
                transition_workflow_state(
                    run,
                    WorkflowState.FAILED,
                    reason=f"Recovery failed-closed: {failure_reason}",
                    is_recovery=True,
                )
                run.finalization_state = FinalizationState.NOT_STARTED
                try:
                    workflow_idempotency.finalize_stage_b(
                        execution_fingerprint=run.execution_fingerprint or run.request_fingerprint,
                        run_id=run.workflow_run_id,
                        status="FAILED",
                        finalization_state="FAILED",
                        request_fingerprint=run.request_fingerprint,
                    )
                except Exception as idemp_err:
                    logger.error(f"Recovery Stage-B failure finalization failed for '{run.workflow_run_id}': {idemp_err}", exc_info=True)
                    run.metadata["persistence_failure"] = str(idemp_err)
                logger.warning(f"Marked incomplete workflow run '{run.workflow_run_id}' as FAILED: {failure_reason}")

            updated = self.persistence.save_run(run)
            resolved_runs.append(updated)

        return resolved_runs

    def verify_authority_chain(self, run: WorkflowRun) -> tuple[bool, str]:
        """Verifies the complete unbroken cryptographic authority chain for a workflow run."""
        # 1. Stage-B Execution Identity must be present
        if not run.execution_fingerprint:
            return False, "Missing Stage-B execution_fingerprint in workflow run."

        # 2. Certification ID must be present
        if not run.certification_id:
            return False, "Missing certification_id (workflow interrupted before certification)."

        # 3. Certification Artifact must exist in repository
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

        try:
            persisted_thresh = self.thresh_persistence.get_resolution(run.threshold_resolution_id)
            if not persisted_thresh:
                return False, f"ThresholdResolution '{run.threshold_resolution_id}' not found in persistence store."
            if persisted_thresh.compute_fingerprint() != run.threshold_resolution_fingerprint:
                return False, f"ThresholdResolution '{run.threshold_resolution_id}' computed fingerprint mismatch."
        except Exception as exc:
            return False, f"Failed to verify persisted ThresholdResolution: {str(exc)}"

        # 5. Oracle Set identity and hash verification
        if run.oracle_set_id and art.oracle_set_id and run.oracle_set_id != art.oracle_set_id:
            return False, f"OracleSet ID mismatch between run and artifact ('{run.oracle_set_id}' vs '{art.oracle_set_id}')."

        if run.oracle_set_hash and art.oracle_set_hash and run.oracle_set_hash != art.oracle_set_hash:
            return False, f"OracleSet hash mismatch between run and artifact."

        if run.oracle_set_id:
            try:
                persisted_oset = self.rec_persistence.get_oracle_set(run.oracle_set_id)
                if not persisted_oset:
                    return False, f"OracleSet '{run.oracle_set_id}' not found in persistence store."
                if run.oracle_set_hash and persisted_oset.oracle_set_hash != run.oracle_set_hash:
                    return False, f"OracleSet '{run.oracle_set_id}' hash mismatch in persistence."
                if persisted_oset.application_id and run.application_id and persisted_oset.application_id != run.application_id:
                    return False, f"OracleSet application '{persisted_oset.application_id}' mismatch with run '{run.application_id}'."
                rules_count = len(getattr(persisted_oset, "rules", [])) + len(getattr(persisted_oset, "oracles", []))
                if rules_count == 0:
                    return False, f"OracleSet '{run.oracle_set_id}' contains zero rules (empty oracle authority forbidden)."
            except Exception as exc:
                return False, f"Failed to verify persisted OracleSet: {str(exc)}"

        # 6. Evaluation result identity and cryptographic verification
        if not run.evaluation_id:
            return False, "Missing evaluation_id in workflow run."

        try:
            persisted_eval = self.eval_persistence.get_evaluation_result(run.evaluation_id)
            if not persisted_eval:
                return False, f"EvaluationResult '{run.evaluation_id}' not found in persistence store."
            if not verify_evaluation_result_integrity(persisted_eval):
                return False, f"EvaluationResult '{run.evaluation_id}' failed cryptographic integrity verification."
            if persisted_eval.application_id and run.application_id and persisted_eval.application_id != run.application_id:
                return False, f"EvaluationResult application '{persisted_eval.application_id}' mismatch with run '{run.application_id}'."
        except Exception as exc:
            return False, f"Failed to verify persisted EvaluationResult: {str(exc)}"

        # 7. Certification cases verification
        try:
            cases = self.cert_repo.list_certification_cases(run.certification_id)
            if not cases or len(cases) == 0:
                return False, f"No persisted CertificationCase records found for certificate '{run.certification_id}'."
        except Exception as exc:
            return False, f"Failed to verify persisted CertificationCase records: {str(exc)}"

        # 8. Mandatory audit trail verification
        try:
            audit_events = audit_logger.list_events(certification_id=run.certification_id)
            if not audit_events or len(audit_events) == 0:
                return False, f"No persisted audit trail records found for certificate '{run.certification_id}'."
        except Exception as exc:
            return False, f"Failed to query audit trail: {str(exc)}"

        return True, "Authority chain verified."


workflow_recovery = WorkflowRecoveryService()
