"""BEACON V2 — Phase 8 SQLite Persistence Store for Dynamic Thresholds.

Provides durable, non-destructive persistence for threshold policies,
frozen threshold resolutions, and advanced behavioral evaluation runs.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Optional, Union

from common.config import settings
from threshold.models import (
    AdvancedEvaluationResult,
    ThresholdPolicy,
    ThresholdResolution,
)

logger = logging.getLogger("beacon.threshold.persistence")


class ThresholdPersistenceError(RuntimeError):
    """Raised when a threshold database persistence operation fails."""
    pass


class ThresholdPersistenceStore:
    """SQLite persistence repository for Phase 8 threshold entities."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        self.db_path = Path(db_path or settings.database_path).resolve()
        self._ensure_schema()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=OFF;")
        return conn

    def _ensure_schema(self) -> None:
        """Additive non-destructive schema migration for Phase 8 tables."""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS threshold_policies (
                        policy_id TEXT PRIMARY KEY,
                        version TEXT NOT NULL,
                        strategy TEXT NOT NULL,
                        metric TEXT NOT NULL,
                        policy_json TEXT NOT NULL,
                        policy_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_thresh_pol_strat ON threshold_policies(strategy);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_thresh_pol_hash ON threshold_policies(policy_hash);")

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS threshold_resolutions (
                        resolution_id TEXT PRIMARY KEY,
                        policy_id TEXT NOT NULL,
                        metric TEXT NOT NULL,
                        strategy TEXT NOT NULL,
                        status TEXT NOT NULL,
                        final_value REAL,
                        sample_count INTEGER NOT NULL DEFAULT 0,
                        resolution_json TEXT NOT NULL,
                        fingerprint TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_thresh_res_pol ON threshold_resolutions(policy_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_thresh_res_fp ON threshold_resolutions(fingerprint);")

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS advanced_evaluation_runs (
                        evaluation_id TEXT PRIMARY KEY,
                        application_id TEXT NOT NULL,
                        oracle_set_id TEXT NOT NULL,
                        policy_id TEXT NOT NULL,
                        verdict TEXT NOT NULL,
                        result_json TEXT NOT NULL,
                        result_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_adv_eval_app ON advanced_evaluation_runs(application_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_adv_eval_hash ON advanced_evaluation_runs(result_hash);")
                conn.commit()
        except Exception as exc:
            logger.error(f"Failed to initialize Phase 8 threshold tables: {exc}")
            raise ThresholdPersistenceError(f"Database schema initialization failed: {exc}") from exc

    def save_policy(self, policy: ThresholdPolicy) -> str:
        """Persists or updates a threshold policy."""
        now = datetime.now(timezone.utc).isoformat()
        policy_hash = policy.compute_policy_hash()
        policy_json = policy.model_dump_json()

        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO threshold_policies (
                        policy_id, version, strategy, metric, policy_json, policy_hash, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(policy_id) DO UPDATE SET
                        version = excluded.version,
                        strategy = excluded.strategy,
                        metric = excluded.metric,
                        policy_json = excluded.policy_json,
                        policy_hash = excluded.policy_hash,
                        updated_at = excluded.updated_at
                """, (
                    policy.policy_id,
                    policy.version,
                    policy.strategy.value,
                    policy.metric.value,
                    policy_json,
                    policy_hash,
                    now,
                    now,
                ))
                conn.commit()
            return policy.policy_id
        except Exception as exc:
            logger.error(f"Failed to save threshold policy {policy.policy_id}: {exc}")
            raise ThresholdPersistenceError(f"Failed to save policy: {exc}") from exc

    def get_policy(self, policy_id: str) -> Optional[ThresholdPolicy]:
        """Retrieves a threshold policy by ID."""
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT policy_json FROM threshold_policies WHERE policy_id = ?",
                    (policy_id,),
                ).fetchone()
                if row:
                    return ThresholdPolicy.model_validate_json(row["policy_json"])
                return None
        except Exception as exc:
            logger.error(f"Failed to get threshold policy {policy_id}: {exc}")
            raise ThresholdPersistenceError(f"Failed to get policy: {exc}") from exc

    def list_policies(self) -> list[ThresholdPolicy]:
        """Lists all registered threshold policies."""
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT policy_json FROM threshold_policies ORDER BY created_at DESC"
                ).fetchall()
                return [ThresholdPolicy.model_validate_json(r["policy_json"]) for r in rows]
        except Exception as exc:
            logger.error(f"Failed to list threshold policies: {exc}")
            raise ThresholdPersistenceError(f"Failed to list policies: {exc}") from exc

    def save_resolution(self, resolution: ThresholdResolution) -> str:
        """Persists a frozen threshold resolution."""
        now = datetime.now(timezone.utc).isoformat()
        res_json = resolution.model_dump_json()

        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO threshold_resolutions (
                        resolution_id, policy_id, metric, strategy, status, final_value, sample_count, resolution_json, fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(resolution_id) DO UPDATE SET
                        resolution_json = excluded.resolution_json,
                        fingerprint = excluded.fingerprint
                """, (
                    resolution.resolution_id,
                    resolution.policy_id,
                    resolution.metric.value,
                    resolution.strategy.value,
                    resolution.status.value,
                    resolution.final_value,
                    resolution.sample_count,
                    res_json,
                    resolution.fingerprint,
                    now,
                ))
                conn.commit()
            return resolution.resolution_id
        except Exception as exc:
            logger.error(f"Failed to save threshold resolution {resolution.resolution_id}: {exc}")
            raise ThresholdPersistenceError(f"Failed to save resolution: {exc}") from exc

    def get_resolution(self, resolution_id: str) -> Optional[ThresholdResolution]:
        """Retrieves a threshold resolution by ID."""
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT resolution_json FROM threshold_resolutions WHERE resolution_id = ?",
                    (resolution_id,),
                ).fetchone()
                if row:
                    return ThresholdResolution.model_validate_json(row["resolution_json"])
                return None
        except Exception as exc:
            logger.error(f"Failed to get threshold resolution {resolution_id}: {exc}")
            raise ThresholdPersistenceError(f"Failed to get resolution: {exc}") from exc

    def save_evaluation_result(self, result: AdvancedEvaluationResult) -> str:
        """Persists an advanced behavioral evaluation run."""
        now = datetime.now(timezone.utc).isoformat()
        res_json = result.model_dump_json()

        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO advanced_evaluation_runs (
                        evaluation_id, application_id, oracle_set_id, policy_id, verdict, result_json, result_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(evaluation_id) DO UPDATE SET
                        verdict = excluded.verdict,
                        result_json = excluded.result_json,
                        result_hash = excluded.result_hash
                """, (
                    result.evaluation_id,
                    result.application_id,
                    result.oracle_set_id,
                    result.policy_id,
                    result.overall_verdict.value,
                    res_json,
                    result.result_hash,
                    now,
                ))
                conn.commit()
            return result.evaluation_id
        except Exception as exc:
            logger.error(f"Failed to save evaluation result {result.evaluation_id}: {exc}")
            raise ThresholdPersistenceError(f"Failed to save evaluation result: {exc}") from exc

    def get_evaluation_result(self, evaluation_id: str) -> Optional[AdvancedEvaluationResult]:
        """Retrieves an advanced evaluation result by ID."""
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT result_json FROM advanced_evaluation_runs WHERE evaluation_id = ?",
                    (evaluation_id,),
                ).fetchone()
                if row:
                    return AdvancedEvaluationResult.model_validate_json(row["result_json"])
                return None
        except Exception as exc:
            logger.error(f"Failed to get evaluation result {evaluation_id}: {exc}")
            raise ThresholdPersistenceError(f"Failed to get evaluation result: {exc}") from exc


# Module-level singleton
threshold_persistence = ThresholdPersistenceStore()
ThresholdResolutionStore = ThresholdPersistenceStore
