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
        """Computes deterministic SHA-256 fingerprint for a certification request."""
        return request.compute_request_fingerprint()

    def check_existing_completed_run(self, request: WorkflowRunRequest) -> Optional[WorkflowRun]:
        """Returns existing completed run matching request fingerprint unless force_recompute is set."""
        if request.force_recompute:
            return None
        fp = self.get_request_fingerprint(request)
        return self.persistence.find_run_by_fingerprint(fp, completed_only=True)

    @contextmanager
    def acquire_execution_lock(self, fingerprint: str):
        """Acquires a per-fingerprint execution lock to prevent concurrent redundant runs."""
        with self._global_lock:
            if fingerprint not in self._active_locks:
                self._active_locks[fingerprint] = threading.Lock()
            lock = self._active_locks[fingerprint]

        acquired = lock.acquire(timeout=60.0)
        if not acquired:
            raise TimeoutError(f"Timed out acquiring workflow execution lock for fingerprint '{fingerprint[:12]}'")

        try:
            yield
        finally:
            lock.release()
            with self._global_lock:
                if fingerprint in self._active_locks:
                    # Clean up unused locks
                    del self._active_locks[fingerprint]


workflow_idempotency = WorkflowIdempotencyManager()
