"""Certification Job Lifecycle Manager for BEACON.

Provides explicit state tracking for long-running certification runs:
ACCEPTED -> QUEUED -> VALIDATING -> PREFLIGHT -> RUNNING -> EVIDENCE_GENERATION -> PERSISTING -> COMPLETED / FAILED

Separates operational Job State from authoritative Certification Status (CERTIFIED, NOT_CERTIFIED, etc.).
"""

from datetime import datetime, timezone
from enum import Enum
import threading
import time
import uuid
from typing import Any, Optional
from pydantic import BaseModel, Field

from .logging_config import log_operational_event, get_logger

logger = get_logger("beacon.lifecycle")


class JobState(str, Enum):
    ACCEPTED = "ACCEPTED"
    QUEUED = "QUEUED"
    VALIDATING = "VALIDATING"
    PREFLIGHT = "PREFLIGHT"
    RUNNING = "RUNNING"
    EVIDENCE_GENERATION = "EVIDENCE_GENERATION"
    PERSISTING = "PERSISTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CertificationJob(BaseModel):
    """Represents an operational certification execution job."""
    job_id: str
    certification_id: Optional[str] = None
    project_id: str
    benchmark_id: Optional[str] = None
    dataset_id: Optional[str] = None
    evaluation_mode: str = "CONTROLLED"
    target_variant: str = "clean"
    provider: str = "offline"
    
    # Operational Lifecycle
    state: JobState = JobState.ACCEPTED
    progress_pct: int = 0
    current_step: str = "Job accepted into system"
    
    # Authoritative Certification Outcome (populated upon completion)
    certification_status: Optional[str] = None
    equivalence_score: Optional[float] = None
    
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    start_time_epoch: float = Field(default_factory=time.time)
    duration_ms: Optional[float] = None
    
    # Error diagnostics (if failed)
    error_category: Optional[str] = None
    error_message: Optional[str] = None


class CertificationJobTracker:
    """Thread-safe in-memory tracker for operational certification jobs."""

    def __init__(self):
        self._lock = threading.RLock()
        self._jobs: dict[str, CertificationJob] = {}

    def create_job(
        self,
        project_id: str,
        benchmark_id: Optional[str] = None,
        dataset_id: Optional[str] = None,
        evaluation_mode: str = "CONTROLLED",
        target_variant: str = "clean",
        provider: str = "offline",
        job_id: Optional[str] = None,
    ) -> CertificationJob:
        with self._lock:
            jid = job_id or f"JOB-{uuid.uuid4().hex[:10]}"
            job = CertificationJob(
                job_id=jid,
                project_id=project_id,
                benchmark_id=benchmark_id,
                dataset_id=dataset_id,
                evaluation_mode=evaluation_mode,
                target_variant=target_variant,
                provider=provider,
                state=JobState.ACCEPTED,
                progress_pct=5,
                current_step="Request accepted and registered",
            )
            self._jobs[jid] = job

            log_operational_event(
                event="job_accepted",
                project_id=project_id,
                benchmark_id=benchmark_id,
                dataset_id=dataset_id,
                evaluation_mode=evaluation_mode,
                target_variant=target_variant,
                provider=provider,
                message=f"Certification job '{jid}' accepted into lifecycle",
            )
            return job

    def update_state(
        self,
        job_id: str,
        state: JobState,
        current_step: Optional[str] = None,
        progress_pct: Optional[int] = None,
        certification_id: Optional[str] = None,
        certification_status: Optional[str] = None,
        equivalence_score: Optional[float] = None,
        error_category: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[CertificationJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None

            now = datetime.now(timezone.utc).isoformat()
            job.state = state
            job.updated_at = now

            if current_step:
                job.current_step = current_step
            if progress_pct is not None:
                job.progress_pct = max(0, min(100, progress_pct))
            if certification_id:
                job.certification_id = certification_id
            if certification_status:
                job.certification_status = certification_status
            if equivalence_score is not None:
                job.equivalence_score = equivalence_score
            if error_category:
                job.error_category = error_category
            if error_message:
                job.error_message = error_message

            # Calculate duration on terminal state
            if state in (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED):
                job.duration_ms = (time.time() - job.start_time_epoch) * 1000.0
                if state == JobState.COMPLETED:
                    job.progress_pct = 100

            log_operational_event(
                event=f"job_state_{state.value.lower()}",
                project_id=job.project_id,
                certification_run_id=job.certification_id,
                benchmark_id=job.benchmark_id,
                dataset_id=job.dataset_id,
                evaluation_mode=job.evaluation_mode,
                target_variant=job.target_variant,
                provider=job.provider,
                duration_ms=job.duration_ms,
                outcome=job.certification_status,
                error_category=job.error_category,
                message=f"Certification job '{job_id}' transitioned to state '{state.value}': {job.current_step}",
            )
            return job

    def get_job(self, job_id: str, project_id: Optional[str] = None) -> Optional[CertificationJob]:
        """Retrieves a job by ID, enforcing strict project isolation.
        Raises PermissionError if project_id is supplied and does not exactly match the job's project.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if project_id and job.project_id != project_id:
                raise PermissionError(f"Access denied: Job belongs to project '{job.project_id}'.")
            return job

    def list_jobs(self, project_id: Optional[str] = None, limit: int = 50) -> list[CertificationJob]:
        """Lists recent jobs with optional project isolation filtering.
        When project_id is supplied, only jobs belonging to that exact project are returned.
        """
        with self._lock:
            jobs = list(self._jobs.values())
            if project_id:
                jobs = [j for j in jobs if j.project_id == project_id]
            # Sort descending by creation time
            jobs.sort(key=lambda j: j.created_at, reverse=True)
            return jobs[:limit]

    def clear(self) -> None:
        """Clears all jobs (used for test isolation)."""
        with self._lock:
            self._jobs.clear()


# Module-level singleton
certification_job_tracker = CertificationJobTracker()
