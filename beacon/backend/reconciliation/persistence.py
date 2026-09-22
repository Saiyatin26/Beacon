"""BEACON V2 — Phase 7 Reconciliation Persistence Store.

Provides durable SQLite persistence and query interfaces for reconciliation runs,
versioned OracleSets, individual Oracle rules, and conflict records.
"""

import json
import logging
import sqlite3
from typing import Any, Optional

from .models import OracleSet, ReconciliationPolicy, ReconciliationResult

from common.config import settings

logger = logging.getLogger("beacon.reconciliation.persistence")


class ReconciliationPersistenceError(RuntimeError):
    """Raised when writing or querying reconciliation results in SQLite fails."""
    pass


class ReconciliationPersistenceStore:
    """Manages SQLite storage for Phase 7 reconciliation artifacts with safe non-destructive migration."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path) if db_path and db_path != "beacon.sqlite3" else str(settings.database_path)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initializes tables for reconciliation runs, oracle sets, and conflict records."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reconciliation_runs (
                    run_id TEXT PRIMARY KEY,
                    application_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    policy_hash TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    approved_count INTEGER NOT NULL,
                    rejected_count INTEGER NOT NULL,
                    conflict_count INTEGER NOT NULL,
                    oracle_set_id TEXT NOT NULL,
                    oracle_set_version INTEGER NOT NULL,
                    result_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reconciled_oracle_sets (
                    oracle_set_id TEXT PRIMARY KEY,
                    application_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    oracle_set_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS oracle_set_rules (
                    oracle_rule_instance_id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL,
                    oracle_set_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    rule_type TEXT NOT NULL,
                    canonical_expression TEXT NOT NULL,
                    role_scope TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    support_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (oracle_set_id) REFERENCES reconciled_oracle_sets(oracle_set_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rule_conflicts (
                    conflict_instance_id TEXT PRIMARY KEY,
                    conflict_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    oracle_set_id TEXT NOT NULL,
                    rule_a_id TEXT NOT NULL,
                    rule_b_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    resolution_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES reconciliation_runs(run_id)
                )
            """)
            conn.commit()

    def save_reconciliation_result(self, result: ReconciliationResult) -> None:
        """Persists a complete ReconciliationResult and associated OracleSet into SQLite."""
        try:
            with self._get_conn() as conn:
                policy_json = json.dumps(result.policy.model_dump(), default=str)
                payload_json = json.dumps(result.model_dump(), default=str)

                conn.execute("""
                    INSERT OR REPLACE INTO reconciliation_runs (
                        run_id, application_id, session_id, policy_hash, policy_json,
                        approved_count, rejected_count, conflict_count, oracle_set_id,
                        oracle_set_version, result_hash, created_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    result.run_id,
                    result.application_id,
                    result.session_id,
                    result.policy_hash,
                    policy_json,
                    result.approved_count,
                    result.rejected_count,
                    result.conflict_count,
                    result.oracle_set_id,
                    result.oracle_set_version,
                    result.result_hash,
                    result.created_at,
                    payload_json,
                ))

                if result.oracle_set:
                    self.save_oracle_set(result.oracle_set, conn=conn)

                conn.commit()
                logger.info(f"Successfully persisted reconciliation run '{result.run_id}'.")
        except Exception as exc:
            logger.error(f"Failed to persist reconciliation result '{result.run_id}': {exc}")
            raise ReconciliationPersistenceError(f"Reconciliation persistence failure: {exc}") from exc

    def save_oracle_set(self, oracle_set: OracleSet, conn: Optional[sqlite3.Connection] = None) -> None:
        """Persists a standalone OracleSet and its rules/conflicts into SQLite."""
        def _execute_save(target_conn: sqlite3.Connection) -> None:
            oset_payload = json.dumps(oracle_set.model_dump(), default=str)
            target_conn.execute("""
                INSERT OR REPLACE INTO reconciled_oracle_sets (
                    oracle_set_id, application_id, version, status,
                    oracle_set_hash, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                oracle_set.oracle_set_id,
                oracle_set.application_id,
                oracle_set.version,
                oracle_set.status.value,
                oracle_set.oracle_set_hash,
                oracle_set.created_at,
                oset_payload,
            ))

            for idx, rule in enumerate(oracle_set.rules):
                rule_inst_id = f"{oracle_set.oracle_set_id}_{rule.rule_id}_{idx}"
                rule_payload = json.dumps(rule.model_dump(), default=str)
                target_conn.execute("""
                    INSERT OR REPLACE INTO oracle_set_rules (
                        oracle_rule_instance_id, rule_id, oracle_set_id, fingerprint,
                        rule_type, canonical_expression, role_scope, source,
                        confidence, support_count, created_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rule_inst_id,
                    rule.rule_id,
                    oracle_set.oracle_set_id,
                    rule.fingerprint,
                    rule.rule_type,
                    rule.canonical_expression,
                    rule.role_scope,
                    rule.source.value,
                    rule.confidence,
                    rule.support_count,
                    rule.created_at,
                    rule_payload,
                ))

            for idx, conf in enumerate(oracle_set.conflicts):
                conf_inst_id = f"{oracle_set.oracle_set_id}_{conf.conflict_id}_{idx}"
                conf_payload = json.dumps(conf.model_dump(), default=str)
                target_conn.execute("""
                    INSERT OR REPLACE INTO rule_conflicts (
                        conflict_instance_id, conflict_id, run_id, oracle_set_id,
                        rule_a_id, rule_b_id, fingerprint, resolution_status,
                        created_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    conf_inst_id,
                    conf.conflict_id,
                    oracle_set.oracle_set_id,
                    oracle_set.oracle_set_id,
                    conf.rule_a_id,
                    conf.rule_b_id,
                    conf.fingerprint,
                    conf.resolution_status,
                    conf.created_at,
                    conf_payload,
                ))

        try:
            if conn is not None:
                _execute_save(conn)
            else:
                with self._get_conn() as new_conn:
                    _execute_save(new_conn)
                    new_conn.commit()
            logger.info(f"Successfully persisted OracleSet '{oracle_set.oracle_set_id}'.")
        except Exception as exc:
            logger.error(f"Failed to persist OracleSet '{oracle_set.oracle_set_id}': {exc}")
            raise ReconciliationPersistenceError(f"OracleSet persistence failure: {exc}") from exc

    def get_reconciliation_result(self, run_id: str) -> Optional[ReconciliationResult]:
        """Retrieves a persisted ReconciliationResult by run ID."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT payload_json FROM reconciliation_runs WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            if not row:
                return None
            data = json.loads(row["payload_json"])
            return ReconciliationResult(**data)

    def get_oracle_set(self, oracle_set_id: str) -> Optional[OracleSet]:
        """Retrieves a persisted OracleSet by ID."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT payload_json FROM reconciled_oracle_sets WHERE oracle_set_id = ?", (oracle_set_id,))
            row = cursor.fetchone()
            if not row:
                return None
            data = json.loads(row["payload_json"])
            return OracleSet(**data)

    def list_oracle_sets(self, application_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Lists summary metadata of stored OracleSets."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if application_id:
                cursor.execute("""
                    SELECT oracle_set_id, application_id, version, status, oracle_set_hash, created_at
                    FROM reconciled_oracle_sets WHERE application_id = ? ORDER BY version DESC, created_at DESC
                """, (application_id,))
            else:
                cursor.execute("""
                    SELECT oracle_set_id, application_id, version, status, oracle_set_hash, created_at
                    FROM reconciled_oracle_sets ORDER BY created_at DESC
                """)
            return [dict(r) for r in cursor.fetchall()]

    def list_reconciliation_runs(self, application_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Lists summary metadata of stored reconciliation runs."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if application_id:
                cursor.execute("""
                    SELECT run_id, application_id, session_id, policy_hash, approved_count,
                           rejected_count, conflict_count, oracle_set_id, result_hash, created_at
                    FROM reconciliation_runs WHERE application_id = ? ORDER BY created_at DESC
                """, (application_id,))
            else:
                cursor.execute("""
                    SELECT run_id, application_id, session_id, policy_hash, approved_count,
                           rejected_count, conflict_count, oracle_set_id, result_hash, created_at
                    FROM reconciliation_runs ORDER BY created_at DESC
                """)
            return [dict(r) for r in cursor.fetchall()]


reconciliation_persistence = ReconciliationPersistenceStore()
