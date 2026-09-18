"""BEACON V2 — Phase 11 Workflow Idempotency & Concurrency Manager.

Ensures deterministic execution, safe duplicate handling, and concurrent execution serialization.
"""

from contextlib import contextmanager
import logging
import threading
from typing import Optional

from .models import WorkflowRun, WorkflowRunRequest
from .persistence import WorkflowPersistenceStore, workflow_persistence

logger = logging.getLogger("beacon.workflow.idempotency")


class WorkflowIdempotencyManager:
    """Manages request idempotency, fingerprinting, and concurrent execution locks."""

    def __init__(self, persistence: Optional[WorkflowPersistenceStore] = None):
        self.persistence = persistence or workflow_persistence
        self._global_lock = threading.Lock()
        self._active_locks: dict[str, threading.Lock] = {}

    def get_request_fingerprint(self, request: WorkflowRunRequest) -> str:
        """Computes deterministic SHA-256 fingerprint for a Stage-A certification request."""
        return request.compute_request_fingerprint()

    def check_existing_completed_run(self, request: WorkflowRunRequest) -> Optional[WorkflowRun]:
        """Returns candidate completed run matching Stage-A request fingerprint (for discovery only)."""
        if request.force_recompute:
            return None
        fp = self.get_request_fingerprint(request)
        return self.persistence.find_run_by_fingerprint(fp, completed_only=True)

    def find_completed_execution(self, execution_fingerprint: str) -> Optional[WorkflowRun]:
        """Finds completed run matching authoritative Stage-B execution fingerprint."""
        if not execution_fingerprint:
            return None
        return self.persistence.find_run_by_execution_fingerprint(execution_fingerprint, completed_only=True)

    def bind_execution_identity(
        self,
        request_fingerprint: str,
        execution_fingerprint: str,
        workflow_run_id: str,
        force_recompute: bool = False,
    ) -> tuple[bool, Optional[str], str]:
        """Atomically binds Stage-B execution identity to an in-progress Stage-A reservation."""
        return self.persistence.bind_execution_identity(
            request_fingerprint=request_fingerprint,
            execution_fingerprint=execution_fingerprint,
            workflow_run_id=workflow_run_id,
            force_recompute=force_recompute,
        )

    @contextmanager
    def acquire_execution_lock(self, fingerprint: str, run_id: Optional[str] = None, force_recompute: bool = False):
        """Acquires a Stage-A execution lock (thread-safe and persistent across processes) to prevent duplicate initialization."""
        with self._global_lock:
            if fingerprint not in self._active_locks:
                self._active_locks[fingerprint] = threading.Lock()
            lock = self._active_locks[fingerprint]

        acquired = lock.acquire(timeout=60.0)
        if not acquired:
            raise TimeoutError(f"Timed out acquiring workflow execution lock for fingerprint '{fingerprint[:12]}'")

        res_ok = True
        existing_id = None
        existing_status = "UNKNOWN"
        try:
            if run_id:
                res_ok, existing_id, existing_status = self.persistence.acquire_persistent_reservation(fingerprint, run_id, force_recompute=force_recompute)
            yield (res_ok, existing_id, existing_status)
        finally:
            lock.release()

    def finalize_run(
        self,
        fingerprint: str,
        run_id: str,
        status: str = "COMPLETED",
        execution_fingerprint: Optional[str] = None,
        finalization_state: Optional[str] = None,
    ) -> None:
        """Finalizes the persistent reservation for a completed or failed run, enforcing ownership safety."""
        self.persistence.finalize_persistent_reservation(
            request_fingerprint=fingerprint,
            workflow_run_id=run_id,
            status=status,
            execution_fingerprint=execution_fingerprint,
            finalization_state=finalization_state,
        )

    def finalize_stage_b(
        self,
        execution_fingerprint: str,
        run_id: str,
        status: str = "COMPLETED",
        finalization_state: Optional[str] = None,
        request_fingerprint: Optional[str] = None,
    ) -> None:
        """Finalizes the authoritative Stage-B execution reservation, enforcing ownership safety."""
        self.persistence.finalize_persistent_reservation(
            request_fingerprint=request_fingerprint or execution_fingerprint,
            workflow_run_id=run_id,
            status=status,
            execution_fingerprint=execution_fingerprint,
            finalization_state=finalization_state,
        )


workflow_idempotency = WorkflowIdempotencyManager()
