"""BEACON V2 — Phase 4 Evaluation Persistence Store.

Provides durable, atomic SQLite storage and retrieval for authoritative EvaluationResult records.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any, Optional, Union

from common.config import settings
from .models import EvaluationResult, compute_evaluation_result_hash, verify_evaluation_result_integrity

logger = logging.getLogger("beacon.evaluation.persistence")


class EvaluationPersistenceError(RuntimeError):
    """Raised when writing or querying EvaluationResults in SQLite fails."""
    pass


class EvaluationPersistenceStore:
    """Atomic SQLite persistence repository for Phase 4 EvaluationResults."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
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
                CREATE TABLE IF NOT EXISTS evaluation_results (
                    evaluation_id TEXT PRIMARY KEY,
                    application_id TEXT NOT NULL,
                    bundle_id TEXT,
                    verdict TEXT NOT NULL,
                    evaluation_hash TEXT NOT NULL,
                    total_inputs INTEGER NOT NULL,
                    total_differences INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_eval_app ON evaluation_results(application_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_eval_bundle ON evaluation_results(bundle_id);"
            )
            conn.commit()

    def save_evaluation_result(self, result: EvaluationResult) -> EvaluationResult:
        """Atomically saves an EvaluationResult with computed canonical content hash."""
        eval_hash = compute_evaluation_result_hash(result)
        result.evaluation_hash = eval_hash
        payload_json = json.dumps(result.model_dump(mode="json"), default=str)
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock, self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                """
                INSERT INTO evaluation_results (
                    evaluation_id, application_id, bundle_id, verdict,
                    evaluation_hash, total_inputs, total_differences, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evaluation_id) DO UPDATE SET
                    application_id = excluded.application_id,
                    bundle_id = excluded.bundle_id,
                    verdict = excluded.verdict,
                    evaluation_hash = excluded.evaluation_hash,
                    total_inputs = excluded.total_inputs,
                    total_differences = excluded.total_differences,
                    payload_json = excluded.payload_json;
                """,
                (
                    result.evaluation_id,
                    result.application_id or "",
                    result.bundle_id or "",
                    result.verdict.value if hasattr(result.verdict, "value") else str(result.verdict),
                    eval_hash,
                    result.summary.total_inputs,
                    result.summary.total_differences,
                    now_iso,
                    payload_json,
                ),
            )
            conn.commit()
        return result

    def get_evaluation_result(self, evaluation_id: str) -> Optional[EvaluationResult]:
        """Retrieves a persisted EvaluationResult by ID."""
        if not evaluation_id:
            return None
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT payload_json FROM evaluation_results WHERE evaluation_id = ?",
                (evaluation_id,),
            ).fetchone()
            if not row:
                return None
            try:
                data = json.loads(row["payload_json"])
                return EvaluationResult.model_validate(data)
            except Exception as exc:
                logger.error(f"Failed to deserialize EvaluationResult '{evaluation_id}': {exc}")
                return None

    def list_evaluation_results(self, application_id: Optional[str] = None, limit: int = 50) -> list[EvaluationResult]:
        """Lists stored EvaluationResults."""
        with self._lock, self._get_connection() as conn:
            if application_id:
                rows = conn.execute(
                    "SELECT payload_json FROM evaluation_results WHERE application_id = ? ORDER BY created_at DESC LIMIT ?",
                    (application_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT payload_json FROM evaluation_results ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            results = []
            for r in rows:
                try:
                    results.append(EvaluationResult.model_validate(json.loads(r["payload_json"])))
                except Exception:
                    pass
            return results

    def clear(self) -> None:
        """Clears all stored evaluation records (for testing)."""
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM evaluation_results;")
            conn.commit()


evaluation_persistence = EvaluationPersistenceStore()
