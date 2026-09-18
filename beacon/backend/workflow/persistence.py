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
from .models import FinalizationState, WorkflowErrorCode, WorkflowRun, WorkflowState

logger = logging.getLogger("beacon.workflow.persistence")


class WorkflowPersistenceConflictError(RuntimeError):
    """Raised when an ownership or reservation conflict occurs during workflow persistence."""
    pass


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
                    execution_fingerprint TEXT,
                    finalization_state TEXT,
                    input_set_id TEXT,
                    input_set_hash TEXT,
                    evidence_bundle_id TEXT,
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
                """
                CREATE TABLE IF NOT EXISTS v2_workflow_idempotency (
                    request_fingerprint TEXT PRIMARY KEY,
                    execution_fingerprint TEXT,
                    workflow_run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS v2_stage_b_reservations (
                    execution_fingerprint TEXT PRIMARY KEY,
                    workflow_run_id TEXT NOT NULL,
                    owner_run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    finalization_state TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            # Safe column migrations if existing tables lack Stage-B fields
            cols_runs = {col["name"] for col in conn.execute("PRAGMA table_info(v2_workflow_runs);").fetchall()}
            if "execution_fingerprint" not in cols_runs:
                conn.execute("ALTER TABLE v2_workflow_runs ADD COLUMN execution_fingerprint TEXT;")
            if "finalization_state" not in cols_runs:
                conn.execute("ALTER TABLE v2_workflow_runs ADD COLUMN finalization_state TEXT;")
            if "input_set_id" not in cols_runs:
                conn.execute("ALTER TABLE v2_workflow_runs ADD COLUMN input_set_id TEXT;")
            if "input_set_hash" not in cols_runs:
                conn.execute("ALTER TABLE v2_workflow_runs ADD COLUMN input_set_hash TEXT;")
            if "evidence_bundle_id" not in cols_runs:
                conn.execute("ALTER TABLE v2_workflow_runs ADD COLUMN evidence_bundle_id TEXT;")

            cols_idemp = {col["name"] for col in conn.execute("PRAGMA table_info(v2_workflow_idempotency);").fetchall()}
            if "execution_fingerprint" not in cols_idemp:
                conn.execute("ALTER TABLE v2_workflow_idempotency ADD COLUMN execution_fingerprint TEXT;")

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_v2_wrun_app ON v2_workflow_runs(application_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_v2_wrun_fp ON v2_workflow_runs(request_fingerprint);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_v2_wrun_exec_fp ON v2_workflow_runs(execution_fingerprint);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_v2_wrun_state ON v2_workflow_runs(state);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_v2_idemp_wrun ON v2_workflow_idempotency(workflow_run_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_v2_idemp_exec_fp ON v2_workflow_idempotency(execution_fingerprint);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_v2_stage_b_wrun ON v2_stage_b_reservations(workflow_run_id);"
            )
            conn.commit()

    def acquire_persistent_reservation(
        self,
        request_fingerprint: str,
        workflow_run_id: str,
        force_recompute: bool = False,
    ) -> tuple[bool, Optional[str], str]:
        """Atomically reserves or checks persistent idempotency for a Stage-A request fingerprint across processes.
        
        Uses BEGIN IMMEDIATE transaction to guarantee database-atomic cross-process serialization.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            row = conn.execute(
                "SELECT workflow_run_id, status FROM v2_workflow_idempotency WHERE request_fingerprint = ?",
                (request_fingerprint,),
            ).fetchone()

            if row:
                existing_run_id = row["workflow_run_id"]
                existing_status = row["status"]
                if existing_status == "IN_PROGRESS" and existing_run_id != workflow_run_id and not force_recompute:
                    # Active concurrent execution by another process/worker
                    conn.commit()
                    return False, existing_run_id, "IN_PROGRESS"

            conn.execute(
                """
                INSERT INTO v2_workflow_idempotency (request_fingerprint, workflow_run_id, status, created_at, updated_at)
                VALUES (?, ?, 'IN_PROGRESS', ?, ?)
                ON CONFLICT(request_fingerprint) DO UPDATE SET
                    workflow_run_id = excluded.workflow_run_id,
                    status = 'IN_PROGRESS',
                    updated_at = excluded.updated_at;
                """,
                (request_fingerprint, workflow_run_id, now, now),
            )
            conn.commit()
            return True, workflow_run_id, "IN_PROGRESS"

    def bind_execution_identity(
        self,
        request_fingerprint: str,
        execution_fingerprint: str,
        workflow_run_id: str,
        force_recompute: bool = False,
    ) -> tuple[bool, Optional[str], str]:
        """Atomically binds Stage-B execution identity to an in-progress Stage-A reservation in durable store.
        
        Guarantees that exactly one authoritative execution owns a given Stage-B execution fingerprint.
        Active reservations owned by another execution cannot be stolen or overwritten.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")

            # Check Stage-B table for existing reservation
            row_b = conn.execute(
                "SELECT workflow_run_id, owner_run_id, status, finalization_state FROM v2_stage_b_reservations WHERE execution_fingerprint = ?",
                (execution_fingerprint,),
            ).fetchone()

            if row_b:
                existing_b_owner = row_b["workflow_run_id"]
                existing_b_status = row_b["status"]
                if existing_b_status == "COMPLETED" and not force_recompute:
                    run_row = conn.execute("SELECT state FROM v2_workflow_runs WHERE workflow_run_id = ?", (existing_b_owner,)).fetchone()
                    if run_row and run_row["state"] == "COMPLETED":
                        conn.commit()
                        return False, existing_b_owner, "COMPLETED"
                elif existing_b_status in ("IN_PROGRESS", "PERSISTING", "CERTIFICATION_VERIFIED", "AUDIT_VERIFIED", "FINALIZATION_PENDING") and existing_b_owner != workflow_run_id:
                    # Active reservation owned by another execution cannot be stolen
                    conn.commit()
                    return False, existing_b_owner, existing_b_status
                elif existing_b_owner == workflow_run_id:
                    conn.commit()
                    return True, workflow_run_id, existing_b_status

            # Also check Stage-A idempotency table for any completed run matching this execution_fingerprint
            if not force_recompute:
                row_completed = conn.execute(
                    "SELECT workflow_run_id, status FROM v2_workflow_idempotency WHERE execution_fingerprint = ? AND status = 'COMPLETED'",
                    (execution_fingerprint,),
                ).fetchone()
                if row_completed and row_completed["workflow_run_id"] != workflow_run_id:
                    run_row_a = conn.execute("SELECT state FROM v2_workflow_runs WHERE workflow_run_id = ?", (row_completed["workflow_run_id"],)).fetchone()
                    if run_row_a and run_row_a["state"] == "COMPLETED":
                        conn.commit()
                        return False, row_completed["workflow_run_id"], "COMPLETED"

                # Check if another active in-progress run is currently executing this execution_fingerprint
                row_in_prog = conn.execute(
                    "SELECT workflow_run_id, status FROM v2_workflow_idempotency WHERE execution_fingerprint = ? AND status = 'IN_PROGRESS' AND workflow_run_id != ?",
                    (execution_fingerprint, workflow_run_id),
                ).fetchone()
                if row_in_prog:
                    conn.commit()
                    return False, row_in_prog["workflow_run_id"], "IN_PROGRESS"

            # Claim Stage-B reservation in dedicated table
            conn.execute(
                """
                INSERT INTO v2_stage_b_reservations (execution_fingerprint, workflow_run_id, owner_run_id, status, finalization_state, created_at, updated_at)
                VALUES (?, ?, ?, 'IN_PROGRESS', 'NOT_STARTED', ?, ?)
                ON CONFLICT(execution_fingerprint) DO UPDATE SET
                    workflow_run_id = excluded.workflow_run_id,
                    owner_run_id = excluded.owner_run_id,
                    status = 'IN_PROGRESS',
                    finalization_state = 'NOT_STARTED',
                    updated_at = excluded.updated_at;
                """,
                (execution_fingerprint, workflow_run_id, workflow_run_id, now, now),
            )

            # Update current run's Stage-A idempotency record to bind execution_fingerprint
            conn.execute(
                """
                UPDATE v2_workflow_idempotency
                SET execution_fingerprint = ?, updated_at = ?
                WHERE request_fingerprint = ? AND workflow_run_id = ?;
                """,
                (execution_fingerprint, now, request_fingerprint, workflow_run_id),
            )
            conn.commit()
            return True, workflow_run_id, "IN_PROGRESS"

    def finalize_persistent_reservation(
        self,
        request_fingerprint: str,
        workflow_run_id: str,
        status: str = "COMPLETED",
        execution_fingerprint: Optional[str] = None,
        finalization_state: Optional[str] = None,
    ) -> None:
        """Updates persistent idempotency records upon completion or failure, enforcing ownership safety across Stage-A and Stage-B."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")

            # 1. Finalize Stage-B reservation if execution_fingerprint is provided
            if execution_fingerprint:
                row_b = conn.execute(
                    "SELECT workflow_run_id, owner_run_id, status FROM v2_stage_b_reservations WHERE execution_fingerprint = ?",
                    (execution_fingerprint,),
                ).fetchone()

                if row_b:
                    existing_b_owner = row_b["workflow_run_id"]
                    existing_b_status = row_b["status"]
                    if existing_b_owner != workflow_run_id and existing_b_status == "COMPLETED":
                        if status == "FAILED":
                            pass
                        else:
                            run_row_b = conn.execute("SELECT state FROM v2_workflow_runs WHERE workflow_run_id = ?", (existing_b_owner,)).fetchone()
                            if run_row_b and run_row_b["state"] == "COMPLETED":
                                conn.commit()
                                raise WorkflowPersistenceConflictError(
                                    f"Cannot finalize Stage-B reservation for '{execution_fingerprint[:12]}': owned by run '{existing_b_owner}'"
                                )

                conn.execute(
                    """
                    INSERT INTO v2_stage_b_reservations (execution_fingerprint, workflow_run_id, owner_run_id, status, finalization_state, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(execution_fingerprint) DO UPDATE SET
                        workflow_run_id = excluded.workflow_run_id,
                        owner_run_id = excluded.owner_run_id,
                        status = excluded.status,
                        finalization_state = COALESCE(excluded.finalization_state, v2_stage_b_reservations.finalization_state),
                        updated_at = excluded.updated_at;
                    """,
                    (execution_fingerprint, workflow_run_id, workflow_run_id, status, finalization_state or status, now, now),
                )

            # 2. Finalize Stage-A record
            row_a = conn.execute(
                "SELECT workflow_run_id, status, execution_fingerprint FROM v2_workflow_idempotency WHERE request_fingerprint = ?",
                (request_fingerprint,),
            ).fetchone()

            if row_a:
                existing_owner = row_a["workflow_run_id"]
                existing_status = row_a["status"]
                # Ownership check: if already finalized by another owner as COMPLETED, prevent overwrite
                if existing_owner != workflow_run_id and existing_status == "COMPLETED":
                    if status == "FAILED":
                        pass
                    else:
                        conn.commit()
                        raise WorkflowPersistenceConflictError(
                            f"Cannot finalize reservation for '{request_fingerprint[:12]}': owned by run '{existing_owner}'"
                        )
                exec_fp = execution_fingerprint or row_a["execution_fingerprint"]
            else:
                exec_fp = execution_fingerprint

            conn.execute(
                """
                INSERT INTO v2_workflow_idempotency (request_fingerprint, execution_fingerprint, workflow_run_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_fingerprint) DO UPDATE SET
                    execution_fingerprint = COALESCE(excluded.execution_fingerprint, v2_workflow_idempotency.execution_fingerprint),
                    workflow_run_id = excluded.workflow_run_id,
                    status = excluded.status,
                    updated_at = excluded.updated_at;
                """,
                (request_fingerprint, exec_fp, workflow_run_id, status, now, now),
            )
            conn.commit()

    def get_idempotency_record(self, request_fingerprint: str) -> Optional[dict[str, Any]]:
        """Retrieves persistent Stage-A idempotency reservation record."""
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM v2_workflow_idempotency WHERE request_fingerprint = ?",
                (request_fingerprint,),
            ).fetchone()
            if not row:
                return None
            return dict(row)

    def get_stage_b_reservation(self, execution_fingerprint: str) -> Optional[dict[str, Any]]:
        """Retrieves authoritative Stage-B execution reservation record."""
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM v2_stage_b_reservations WHERE execution_fingerprint = ?",
                (execution_fingerprint,),
            ).fetchone()
            if not row:
                return None
            return dict(row)

    def delete_idempotency_record(self, request_fingerprint: str) -> None:
        """Deletes persistent idempotency reservation record."""
        with self._lock, self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                "DELETE FROM v2_workflow_idempotency WHERE request_fingerprint = ?",
                (request_fingerprint,),
            )
            conn.commit()

    def save_run(self, run: WorkflowRun) -> WorkflowRun:
        """Atomically upserts a WorkflowRun record with complete Stage-B identity and finalization fields."""
        run.updated_at = datetime.now(timezone.utc).isoformat()
        timings_str = json.dumps(run.stage_timings_ms, sort_keys=True)
        meta_str = json.dumps(run.metadata, sort_keys=True)
        fin_state_str = run.finalization_state.value if (run.finalization_state and hasattr(run.finalization_state, "value")) else (str(run.finalization_state) if run.finalization_state else None)

        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO v2_workflow_runs (
                    workflow_run_id, application_id, request_fingerprint, execution_fingerprint,
                    finalization_state, input_set_id, input_set_hash, evidence_bundle_id, state,
                    error_code, error_message, created_at, updated_at, completed_at,
                    evidence_session_id, evaluation_id, oracle_set_id, oracle_set_hash,
                    threshold_resolution_id, threshold_resolution_fingerprint,
                    certification_id, certification_status, certification_score,
                    explanation_id, stage_timings_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_run_id) DO UPDATE SET
                    application_id = excluded.application_id,
                    request_fingerprint = excluded.request_fingerprint,
                    execution_fingerprint = excluded.execution_fingerprint,
                    finalization_state = excluded.finalization_state,
                    input_set_id = excluded.input_set_id,
                    input_set_hash = excluded.input_set_hash,
                    evidence_bundle_id = excluded.evidence_bundle_id,
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
                    run.execution_fingerprint,
                    fin_state_str,
                    run.input_set_id,
                    run.input_set_hash,
                    run.evidence_bundle_id,
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
        """Finds the most recent WorkflowRun matching an exact request fingerprint (Candidate Discovery only)."""
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

    def find_run_by_execution_fingerprint(self, execution_fingerprint: str, completed_only: bool = True) -> Optional[WorkflowRun]:
        """Finds the most recent WorkflowRun matching an exact authoritative Stage-B execution fingerprint."""
        if not execution_fingerprint:
            return None
        query = "SELECT * FROM v2_workflow_runs WHERE execution_fingerprint = ?"
        params = [execution_fingerprint]
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
            conn.execute("DELETE FROM v2_workflow_idempotency;")
            conn.commit()

    def _row_to_model(self, row: sqlite3.Row) -> WorkflowRun:
        keys = row.keys()
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

        fin_val = row["finalization_state"] if "finalization_state" in keys else None
        fin_enum = None
        if fin_val:
            try:
                fin_enum = FinalizationState(fin_val)
            except ValueError:
                fin_enum = None

        return WorkflowRun(
            workflow_run_id=row["workflow_run_id"],
            application_id=row["application_id"],
            request_fingerprint=row["request_fingerprint"],
            execution_fingerprint=row["execution_fingerprint"] if "execution_fingerprint" in keys else None,
            finalization_state=fin_enum,
            input_set_id=row["input_set_id"] if "input_set_id" in keys else None,
            input_set_hash=row["input_set_hash"] if "input_set_hash" in keys else None,
            evidence_bundle_id=row["evidence_bundle_id"] if "evidence_bundle_id" in keys else None,
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

    def find_execution_by_fingerprint(self, execution_fingerprint: str, completed_only: bool = True) -> Optional[WorkflowRun]:
        """Alias for find_run_by_execution_fingerprint."""
        return self.find_run_by_execution_fingerprint(execution_fingerprint, completed_only=completed_only)


workflow_persistence = WorkflowPersistenceStore()
