"""BEACON V2 — Phase 11 Workflow Persistence Store.

Provides atomic, thread-safe persistence for workflow run lifecycle tracking, stage milestones,
idempotency lookups, and crash recovery.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any, Optional, Union

from common.config import settings
from .models import WorkflowErrorCode, WorkflowRun, WorkflowState

logger = logging.getLogger("beacon.workflow.persistence")


class WorkflowPersistenceStore:
    """Atomic SQLite persistence for canonical V2 workflow executions."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self.db_path = Path(db_path)
        elif getattr(settings, "database_path", None):
            self.db_path = Path(settings.database_path)
        elif getattr(settings, "sqlite_db_path", None):
            self.db_path = Path(settings.sqlite_db_path)
        else:
            self.db_path = Path(__file__).resolve().parents[1] / "data" / "beacon.sqlite3"

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS v2_workflow_runs (
                    workflow_run_id TEXT PRIMARY KEY,
                    application_id TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    evidence_session_id TEXT,
                    evaluation_id TEXT,
                    oracle_set_id TEXT,
                    oracle_set_hash TEXT,
                    threshold_resolution_id TEXT,
                    threshold_resolution_fingerprint TEXT,
                    certification_id TEXT,
                    certification_status TEXT,
                    certification_score REAL,
                    explanation_id TEXT,
                    stage_timings_json TEXT,
                    metadata_json TEXT
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_v2_wrun_app ON v2_workflow_runs(application_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_v2_wrun_fp ON v2_workflow_runs(request_fingerprint);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_v2_wrun_state ON v2_workflow_runs(state);"
            )
            conn.commit()

    def save_run(self, run: WorkflowRun) -> WorkflowRun:
        """Atomically upserts a WorkflowRun record."""
        run.updated_at = datetime.now(timezone.utc).isoformat()
        timings_str = json.dumps(run.stage_timings_ms, sort_keys=True)
        meta_str = json.dumps(run.metadata, sort_keys=True)

        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO v2_workflow_runs (
                    workflow_run_id, application_id, request_fingerprint, state,
                    error_code, error_message, created_at, updated_at, completed_at,
                    evidence_session_id, evaluation_id, oracle_set_id, oracle_set_hash,
                    threshold_resolution_id, threshold_resolution_fingerprint,
                    certification_id, certification_status, certification_score,
                    explanation_id, stage_timings_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_run_id) DO UPDATE SET
                    application_id = excluded.application_id,
                    request_fingerprint = excluded.request_fingerprint,
                    state = excluded.state,
                    error_code = excluded.error_code,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at,
                    evidence_session_id = excluded.evidence_session_id,
                    evaluation_id = excluded.evaluation_id,
                    oracle_set_id = excluded.oracle_set_id,
                    oracle_set_hash = excluded.oracle_set_hash,
                    threshold_resolution_id = excluded.threshold_resolution_id,
                    threshold_resolution_fingerprint = excluded.threshold_resolution_fingerprint,
                    certification_id = excluded.certification_id,
                    certification_status = excluded.certification_status,
                    certification_score = excluded.certification_score,
                    explanation_id = excluded.explanation_id,
                    stage_timings_json = excluded.stage_timings_json,
                    metadata_json = excluded.metadata_json;
                """,
                (
                    run.workflow_run_id,
                    run.application_id,
                    run.request_fingerprint,
                    run.state.value if hasattr(run.state, "value") else str(run.state),
                    run.error_code.value if hasattr(run.error_code, "value") else (str(run.error_code) if run.error_code else None),
                    run.error_message,
                    run.created_at,
                    run.updated_at,
                    run.completed_at,
                    run.evidence_session_id,
                    run.evaluation_id,
                    run.oracle_set_id,
                    run.oracle_set_hash,
                    run.threshold_resolution_id,
                    run.threshold_resolution_fingerprint,
                    run.certification_id,
                    run.certification_status,
                    run.certification_score,
                    run.explanation_id,
                    timings_str,
                    meta_str,
                ),
            )
            conn.commit()
        return run

    def get_run(self, workflow_run_id: str) -> Optional[WorkflowRun]:
        """Retrieves a WorkflowRun by its unique ID."""
        if not workflow_run_id:
            return None
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM v2_workflow_runs WHERE workflow_run_id = ?",
                (workflow_run_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_model(row)

    def find_run_by_fingerprint(self, fingerprint: str, completed_only: bool = True) -> Optional[WorkflowRun]:
        """Finds the most recent WorkflowRun matching an exact request fingerprint."""
        if not fingerprint:
            return None
        query = "SELECT * FROM v2_workflow_runs WHERE request_fingerprint = ?"
        params = [fingerprint]
        if completed_only:
            query += " AND state = 'COMPLETED'"
        query += " ORDER BY created_at DESC LIMIT 1"

        with self._lock, self._get_connection() as conn:
            row = conn.execute(query, params).fetchone()
            if not row:
                return None
            return self._row_to_model(row)

    def list_runs(
        self,
        application_id: Optional[str] = None,
        state: Optional[Union[WorkflowState, str]] = None,
        limit: int = 50,
    ) -> list[WorkflowRun]:
        """Lists recent workflow runs, optionally filtered by application_id and/or state."""
        with self._lock, self._get_connection() as conn:
            conditions = []
            params = []
            if application_id:
                conditions.append("application_id = ?")
                params.append(application_id)
            if state:
                state_str = state.value if hasattr(state, "value") else str(state)
                conditions.append("state = ?")
                params.append(state_str)

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            query = f"SELECT * FROM v2_workflow_runs {where_clause} ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, tuple(params)).fetchall()
            return [self._row_to_model(r) for r in rows]

    def list_interrupted_runs(self) -> list[WorkflowRun]:
        """Finds workflow runs that were started but never completed or failed."""
        terminal_states = ("COMPLETED", "FAILED", "INCONCLUSIVE")
        placeholders = ",".join("?" for _ in terminal_states)
        with self._lock, self._get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM v2_workflow_runs WHERE state NOT IN ({placeholders}) ORDER BY created_at ASC",
                terminal_states,
            ).fetchall()
            return [self._row_to_model(r) for r in rows]

    def clear(self) -> None:
        """Clears all workflow records (for test isolation)."""
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM v2_workflow_runs;")
            conn.commit()

    def _row_to_model(self, row: sqlite3.Row) -> WorkflowRun:
        timings = {}
        if row["stage_timings_json"]:
            try:
                timings = json.loads(row["stage_timings_json"])
            except Exception:
                pass

        meta = {}
        if row["metadata_json"]:
            try:
                meta = json.loads(row["metadata_json"])
            except Exception:
                pass

        state_val = row["state"]
        try:
            state_enum = WorkflowState(state_val)
        except ValueError:
            state_enum = WorkflowState.FAILED

        err_val = row["error_code"]
        err_enum = None
        if err_val:
            try:
                err_enum = WorkflowErrorCode(err_val)
            except ValueError:
                err_enum = WorkflowErrorCode.INTERNAL_ERROR

        return WorkflowRun(
            workflow_run_id=row["workflow_run_id"],
            application_id=row["application_id"],
            request_fingerprint=row["request_fingerprint"],
            state=state_enum,
            error_code=err_enum,
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            evidence_session_id=row["evidence_session_id"],
            evaluation_id=row["evaluation_id"],
            oracle_set_id=row["oracle_set_id"],
            oracle_set_hash=row["oracle_set_hash"],
            threshold_resolution_id=row["threshold_resolution_id"],
            threshold_resolution_fingerprint=row["threshold_resolution_fingerprint"],
            certification_id=row["certification_id"],
            certification_status=row["certification_status"],
            certification_score=row["certification_score"],
            explanation_id=row["explanation_id"],
            stage_timings_ms=timings,
            metadata=meta,
        )


workflow_persistence = WorkflowPersistenceStore()
