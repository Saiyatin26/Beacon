"""Certification Job Lifecycle Manager for BEACON.

Provides explicit, validated state tracking and SQLite persistence for operational certification runs:
ACCEPTED -> QUEUED -> VALIDATING -> PREFLIGHT -> RUNNING -> EVIDENCE_GENERATION -> PERSISTING -> COMPLETED / FAILED / CANCELLED

Enforces strict state-machine transition validation and thread-safe persistence.
"""

from datetime import datetime, timezone
from enum import Enum
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from typing import Any, Optional
from pydantic import BaseModel, Field

from common.config import settings
from .errors import StateTransitionError
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


# Formal State Transition Validation Matrix
VALID_JOB_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.ACCEPTED: {
        JobState.ACCEPTED,
        JobState.QUEUED,
        JobState.VALIDATING,
        JobState.PREFLIGHT,
        JobState.RUNNING,
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.CANCELLED,
    },


    JobState.QUEUED: {
        JobState.QUEUED,
        JobState.VALIDATING,
        JobState.PREFLIGHT,
        JobState.RUNNING,
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.CANCELLED,
    },
    JobState.VALIDATING: {
        JobState.VALIDATING,
        JobState.PREFLIGHT,
        JobState.RUNNING,
        JobState.FAILED,
        JobState.CANCELLED,
    },
    JobState.PREFLIGHT: {
        JobState.PREFLIGHT,
        JobState.RUNNING,
        JobState.FAILED,
        JobState.CANCELLED,
    },
    JobState.RUNNING: {
        JobState.RUNNING,
        JobState.EVIDENCE_GENERATION,
        JobState.PERSISTING,
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.CANCELLED,
    },
    JobState.EVIDENCE_GENERATION: {
        JobState.EVIDENCE_GENERATION,
        JobState.PERSISTING,
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.CANCELLED,
    },
    JobState.PERSISTING: {
        JobState.PERSISTING,
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.CANCELLED,
    },
    # Terminal States: No outgoing transitions allowed
    JobState.COMPLETED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}


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
    """Thread-safe and SQLite-persisted tracker for operational certification jobs."""

    def __init__(self, db_path: Optional[str] = None):
        self._lock = threading.RLock()
        self._jobs: dict[str, CertificationJob] = {}
        if db_path is None:
            self._db_path = str(settings.database_path)
        else:
            self._db_path = str(db_path)
        self._init_db()
        self._load_active_jobs_from_db()

    def _init_db(self) -> None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS certification_jobs (
                        job_id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        certification_id TEXT,
                        benchmark_id TEXT,
                        dataset_id TEXT,
                        evaluation_mode TEXT NOT NULL,
                        target_variant TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        state TEXT NOT NULL,
                        progress_pct INTEGER NOT NULL,
                        current_step TEXT,
                        certification_status TEXT,
                        equivalence_score REAL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        start_time_epoch REAL NOT NULL,
                        duration_ms REAL,
                        error_category TEXT,
                        error_message TEXT
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_project_id ON certification_jobs(project_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_state ON certification_jobs(state)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON certification_jobs(created_at)")
                conn.commit()
        except Exception as exc:
            logger.warning(f"Could not initialize certification_jobs table: {exc}")

    def _load_active_jobs_from_db(self) -> None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM certification_jobs ORDER BY created_at DESC LIMIT 100")
                for row in cursor.fetchall():
                    job_data = dict(row)
                    job_data["state"] = JobState(job_data["state"])
                    job = CertificationJob(**job_data)
                    self._jobs[job.job_id] = job
        except Exception as exc:
            logger.warning(f"Could not load jobs from database: {exc}")

    def _persist_job(self, job: CertificationJob) -> None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO certification_jobs (
                        job_id, project_id, certification_id, benchmark_id, dataset_id,
                        evaluation_mode, target_variant, provider, state, progress_pct,
                        current_step, certification_status, equivalence_score, created_at,
                        updated_at, start_time_epoch, duration_ms, error_category, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job.job_id, job.project_id, job.certification_id, job.benchmark_id, job.dataset_id,
                    job.evaluation_mode, job.target_variant, job.provider, job.state.value, job.progress_pct,
                    job.current_step, job.certification_status, job.equivalence_score, job.created_at,
                    job.updated_at, job.start_time_epoch, job.duration_ms, job.error_category, job.error_message
                ))
                conn.commit()
        except Exception as exc:
            logger.warning(f"Could not persist certification job '{job.job_id}': {exc}")

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
            self._persist_job(job)

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
        allow_forced: bool = False,
    ) -> Optional[CertificationJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None

            # State Transition Validation
            current_state = job.state
            if not allow_forced and state != current_state:
                valid_next_states = VALID_JOB_TRANSITIONS.get(current_state, set())
                if state not in valid_next_states:
                    err_msg = (
                        f"Illegal state transition for job '{job_id}' from '{current_state.value}' "
                        f"to '{state.value}'. Permitted transitions: {[s.value for s in valid_next_states]}."
                    )
                    logger.warning(err_msg)
                    log_operational_event(
                        event="job_state_transition_rejected",
                        project_id=job.project_id,
                        level=logging.WARNING,
                        logger_name="beacon.lifecycle",
                        outcome="REJECTED",
                        error_category="STATE_TRANSITION_ERROR",
                        message=err_msg,
                        extra={
                            "job_id": job_id,
                            "current_state": current_state.value,
                            "requested_state": state.value,
                        },
                    )
                    raise StateTransitionError(
                        message=err_msg,
                        details={
                            "job_id": job_id,
                            "current_state": current_state.value,
                            "requested_state": state.value,
                        },
                    )

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

            self._persist_job(job)

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
                # Try loading from DB
                try:
                    with sqlite3.connect(self._db_path) as conn:
                        conn.row_factory = sqlite3.Row
                        cursor = conn.cursor()
                        cursor.execute("SELECT * FROM certification_jobs WHERE job_id = ?", (job_id,))
                        row = cursor.fetchone()
                        if row:
                            job_data = dict(row)
                            job_data["state"] = JobState(job_data["state"])
                            job = CertificationJob(**job_data)
                            self._jobs[job.job_id] = job
                except Exception as exc:
                    logger.warning(f"Error querying job from DB: {exc}")

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

    def list_interrupted_or_stale_jobs(self) -> list[CertificationJob]:
        """Returns all jobs currently in a non-terminal state across the database."""
        non_terminal_states = (
            JobState.ACCEPTED.value,
            JobState.QUEUED.value,
            JobState.VALIDATING.value,
            JobState.PREFLIGHT.value,
            JobState.RUNNING.value,
            JobState.EVIDENCE_GENERATION.value,
            JobState.PERSISTING.value,
        )
        results: list[CertificationJob] = []
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    placeholders = ",".join("?" for _ in non_terminal_states)
                    cursor.execute(
                        f"SELECT * FROM certification_jobs WHERE state IN ({placeholders})",
                        non_terminal_states,
                    )
                    for row in cursor.fetchall():
                        job_data = dict(row)
                        job_data["state"] = JobState(job_data["state"])
                        results.append(CertificationJob(**job_data))
            except Exception as exc:
                logger.warning(f"Error querying non-terminal jobs: {exc}")
        return results

    def clear(self) -> None:
        """Clears all jobs (used for test isolation)."""
        with self._lock:
            self._jobs.clear()
            try:
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute("DELETE FROM certification_jobs")
                    conn.commit()
            except Exception as exc:
                logger.warning(f"Error clearing certification_jobs: {exc}")


# Module-level singleton
certification_job_tracker = CertificationJobTracker()
