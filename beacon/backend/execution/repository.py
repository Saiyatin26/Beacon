"""BEACON V2 — Execution Session & Record Repository.

Stores and queries execution session lifecycles, execution records,
and adapter run metadata in the authoritative SQLite database with WAL mode.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Optional, Union

from common.config import settings
from .models import ExecutionRecord, ExecutionResult, ExecutionSession, ExecutionStatus

logger = logging.getLogger("beacon.execution.repository")


class ExecutionRepository:
    """Manages persistent SQLite storage of ExecutionSession and ExecutionResult records."""

    def __init__(self, db_path: Optional[Union[Path, str]] = None):
        self._db_path = Path(db_path) if db_path else Path(settings.database_path)
        self._memory_sessions: dict[str, ExecutionSession] = {}
        self._memory_results: dict[str, ExecutionResult] = {}
        self._init_db()

    def _init_db(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS execution_sessions (
                        session_id TEXT PRIMARY KEY,
                        application_id TEXT NOT NULL,
                        adapter_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        status TEXT NOT NULL,
                        start_time TEXT NOT NULL,
                        end_time TEXT,
                        records_count INTEGER NOT NULL DEFAULT 0,
                        succeeded_count INTEGER NOT NULL DEFAULT 0,
                        failed_count INTEGER NOT NULL DEFAULT 0,
                        timeout_count INTEGER NOT NULL DEFAULT 0,
                        session_json TEXT NOT NULL,
                        session_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_sess_app ON execution_sessions(application_id);")

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS execution_records (
                        execution_id TEXT PRIMARY KEY,
                        session_id TEXT,
                        application_id TEXT,
                        implementation_id TEXT,
                        role TEXT NOT NULL,
                        status TEXT NOT NULL,
                        exit_code INTEGER,
                        duration_ms REAL NOT NULL DEFAULT 0.0,
                        error_message TEXT,
                        result_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (session_id) REFERENCES execution_sessions(session_id)
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_rec_sess ON execution_records(session_id);")
                conn.commit()
        except Exception as exc:
            logger.warning(f"Could not initialize execution SQLite tables: {exc}")

    def save_session(self, session: ExecutionSession) -> ExecutionSession:
        """Persists or updates an ExecutionSession."""
        self._memory_sessions[session.session_id] = session
        sess_hash = session.compute_session_hash()
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            sess_json = session.model_dump_json()
        except Exception:
            sess_json = json.dumps(session.model_dump(mode="python"), default=str)

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    INSERT INTO execution_sessions (
                        session_id, application_id, adapter_id, role, status, start_time, end_time,
                        records_count, succeeded_count, failed_count, timeout_count, session_json, session_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        status=excluded.status,
                        end_time=excluded.end_time,
                        records_count=excluded.records_count,
                        succeeded_count=excluded.succeeded_count,
                        failed_count=excluded.failed_count,
                        timeout_count=excluded.timeout_count,
                        session_json=excluded.session_json,
                        session_hash=excluded.session_hash
                """, (
                    session.session_id,
                    session.application_id,
                    session.adapter_id,
                    str(session.role),
                    session.status.value if hasattr(session.status, "value") else str(session.status),
                    session.start_time,
                    session.end_time,
                    session.records_count,
                    session.succeeded_count,
                    session.failed_count,
                    session.timeout_count,
                    sess_json,
                    sess_hash,
                    now_iso,
                ))
                conn.commit()
        except Exception as exc:
            logger.warning(f"SQLite save_session failed (retained in-memory): {exc}")

        return session

    def get_session(self, session_id: str) -> Optional[ExecutionSession]:
        """Retrieves an ExecutionSession by ID."""
        if session_id in self._memory_sessions:
            return self._memory_sessions[session_id]

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT session_json FROM execution_sessions WHERE session_id = ?", (session_id,))
                row = cursor.fetchone()
                if row:
                    data = json.loads(row[0])
                    sess = ExecutionSession(**data)
                    self._memory_sessions[session_id] = sess
                    return sess
        except Exception as exc:
            logger.warning(f"SQLite get_session error: {exc}")

        return None

    def list_sessions(self, application_id: Optional[str] = None, limit: int = 50) -> list[ExecutionSession]:
        """Lists recent execution sessions."""
        sessions: list[ExecutionSession] = []
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                if application_id:
                    cursor.execute(
                        "SELECT session_json FROM execution_sessions WHERE application_id = ? ORDER BY start_time DESC LIMIT ?",
                        (application_id, limit),
                    )
                else:
                    cursor.execute(
                        "SELECT session_json FROM execution_sessions ORDER BY start_time DESC LIMIT ?",
                        (limit,),
                    )
                rows = cursor.fetchall()
                for row in rows:
                    data = json.loads(row[0])
                    sessions.append(ExecutionSession(**data))
        except Exception as exc:
            logger.warning(f"SQLite list_sessions error: {exc}")
            sessions = list(self._memory_sessions.values())
            if application_id:
                sessions = [s for s in sessions if s.application_id == application_id]

        return sessions

    def save_result(self, result: ExecutionResult) -> ExecutionResult:
        """Persists an ExecutionResult record."""
        self._memory_results[result.execution_id] = result
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            res_json = result.model_dump_json()
        except Exception:
            res_json = json.dumps(result.model_dump(mode="python"), default=str)

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    INSERT INTO execution_records (
                        execution_id, session_id, application_id, implementation_id, role, status,
                        exit_code, duration_ms, error_message, result_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(execution_id) DO UPDATE SET
                        status=excluded.status,
                        exit_code=excluded.exit_code,
                        duration_ms=excluded.duration_ms,
                        error_message=excluded.error_message,
                        result_json=excluded.result_json
                """, (
                    result.execution_id,
                    result.session_id,
                    result.application_id,
                    result.implementation_id,
                    str(result.role),
                    result.status.value if hasattr(result.status, "value") else str(result.status),
                    result.exit_code,
                    result.duration_ms,
                    result.error_message,
                    res_json,
                    now_iso,
                ))
                conn.commit()
        except Exception as exc:
            logger.warning(f"SQLite save_result failed (retained in-memory): {exc}")

        return result

    def get_result(self, execution_id: str) -> Optional[ExecutionResult]:
        """Retrieves an ExecutionResult by ID."""
        if execution_id in self._memory_results:
            return self._memory_results[execution_id]

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT result_json FROM execution_records WHERE execution_id = ?", (execution_id,))
                row = cursor.fetchone()
                if row:
                    data = json.loads(row[0])
                    res = ExecutionResult(**data)
                    self._memory_results[execution_id] = res
                    return res
        except Exception as exc:
            logger.warning(f"SQLite get_result error: {exc}")

        return None

    def list_results_for_session(self, session_id: str) -> list[ExecutionResult]:
        """Retrieves all ExecutionResult records associated with a session."""
        results: list[ExecutionResult] = []
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT result_json FROM execution_records WHERE session_id = ? ORDER BY created_at ASC",
                    (session_id,),
                )
                for row in cursor.fetchall():
                    data = json.loads(row[0])
                    results.append(ExecutionResult(**data))
        except Exception as exc:
            logger.warning(f"SQLite list_results_for_session error: {exc}")
            results = [r for r in self._memory_results.values() if r.session_id == session_id]

        return results

    def clear(self) -> None:
        """Clears memory and tables for test isolation."""
        self._memory_sessions.clear()
        self._memory_results.clear()
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("DELETE FROM execution_records")
                conn.execute("DELETE FROM execution_sessions")
                conn.commit()
        except Exception:
            pass


execution_repository = ExecutionRepository()
