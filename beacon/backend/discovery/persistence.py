"""BEACON V2 — Phase 6 Discovery Persistence.

Provides explicit SQLite persistence and audit retrieval for Phase 6 discovery runs and candidate rules.
"""

import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Optional

from .models import DiscoveredCandidate, DiscoveryPolicy, DiscoveryResult

logger = logging.getLogger("beacon.discovery.persistence")


class DiscoveryPersistenceError(RuntimeError):
    """Raised when discovery result persistence fails."""
    pass


class DiscoveryPersistenceStore:
    """Manages SQLite storage for Phase 6 discovery results and candidate rules."""

    def __init__(self, db_path: str = "beacon.sqlite3"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initializes tables for discovery results and candidates."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS discoveries (
                    discovery_id TEXT PRIMARY KEY,
                    application_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    policy_hash TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    observation_count INTEGER NOT NULL,
                    generated_count INTEGER NOT NULL,
                    validated_count INTEGER NOT NULL,
                    contradicted_count INTEGER NOT NULL,
                    inconclusive_count INTEGER NOT NULL,
                    result_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
            """)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(discovered_candidates)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            if existing_cols and "candidate_instance_id" not in existing_cols:
                logger.info("Migrating discovered_candidates table to support candidate_instance_id while preserving historical data...")
                conn.execute("ALTER TABLE discovered_candidates RENAME TO discovered_candidates_old")
                conn.execute("""
                    CREATE TABLE discovered_candidates (
                        candidate_instance_id TEXT PRIMARY KEY,
                        candidate_id TEXT NOT NULL,
                        discovery_id TEXT NOT NULL,
                        fingerprint TEXT NOT NULL,
                        rule_type TEXT NOT NULL,
                        canonical_expression TEXT NOT NULL,
                        role_scope TEXT NOT NULL,
                        support_count INTEGER NOT NULL,
                        contradiction_count INTEGER NOT NULL,
                        confidence REAL NOT NULL,
                        validation_status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        FOREIGN KEY (discovery_id) REFERENCES discoveries(discovery_id)
                    )
                """)
                conn.execute("""
                    INSERT INTO discovered_candidates (
                        candidate_instance_id, candidate_id, discovery_id, fingerprint, rule_type,
                        canonical_expression, role_scope, support_count, contradiction_count,
                        confidence, validation_status, created_at, payload_json
                    )
                    SELECT
                        discovery_id || '_' || candidate_id || '_' || rowid,
                        candidate_id, discovery_id, fingerprint, rule_type,
                        canonical_expression, role_scope, support_count, contradiction_count,
                        confidence, validation_status, created_at, payload_json
                    FROM discovered_candidates_old
                """)
                conn.execute("DROP TABLE discovered_candidates_old")
                logger.info("Successfully migrated historical discovered_candidates data without loss.")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS discovered_candidates (
                    candidate_instance_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    discovery_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    rule_type TEXT NOT NULL,
                    canonical_expression TEXT NOT NULL,
                    role_scope TEXT NOT NULL,
                    support_count INTEGER NOT NULL,
                    contradiction_count INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    validation_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (discovery_id) REFERENCES discoveries(discovery_id)
                )
            """)
            conn.commit()

    def save_discovery_result(self, result: DiscoveryResult) -> None:
        """Persists a complete DiscoveryResult into SQLite without overwriting candidate history."""
        try:
            with self._get_conn() as conn:
                policy_json = json.dumps(result.policy.model_dump(), default=str)
                payload_json = json.dumps(result.model_dump(), default=str)

                conn.execute("""
                    INSERT OR REPLACE INTO discoveries (
                        discovery_id, application_id, session_id, policy_hash, policy_json,
                        observation_count, generated_count, validated_count, contradicted_count,
                        inconclusive_count, result_hash, created_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    result.discovery_id,
                    result.application_id,
                    result.session_id,
                    result.policy_hash,
                    policy_json,
                    result.observation_count,
                    result.generated_count,
                    result.validated_count,
                    result.contradicted_count,
                    result.inconclusive_count,
                    result.result_hash,
                    result.created_at,
                    payload_json,
                ))

                for idx, cand in enumerate(result.candidates):
                    instance_id = f"{result.discovery_id}_{cand.candidate_id}_{idx}"
                    cand_payload = json.dumps(cand.model_dump(), default=str)
                    conn.execute("""
                        INSERT OR REPLACE INTO discovered_candidates (
                            candidate_instance_id, candidate_id, discovery_id, fingerprint, rule_type,
                            canonical_expression, role_scope, support_count, contradiction_count,
                            confidence, validation_status, created_at, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        instance_id,
                        cand.candidate_id,
                        result.discovery_id,
                        cand.fingerprint,
                        cand.rule_type.value,
                        cand.canonical_expression,
                        cand.role_scope,
                        cand.support_count,
                        cand.contradiction_count,
                        cand.confidence,
                        cand.validation_status.value,
                        cand.created_at,
                        cand_payload,
                    ))

                conn.commit()
                logger.info(f"Persisted discovery result '{result.discovery_id}' with {len(result.candidates)} candidates.")
        except Exception as exc:
            logger.error(f"Failed to persist discovery result '{result.discovery_id}': {exc}")
            raise DiscoveryPersistenceError(f"Discovery persistence failure: {exc}") from exc

    def get_discovery_result(self, discovery_id: str) -> Optional[DiscoveryResult]:
        """Retrieves a persisted DiscoveryResult by ID."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT payload_json FROM discoveries WHERE discovery_id = ?", (discovery_id,))
            row = cursor.fetchone()
            if not row:
                return None
            data = json.loads(row["payload_json"])
            return DiscoveryResult(**data)

    def list_discoveries(self, application_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Lists summary metadata of stored discoveries."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if application_id:
                cursor.execute("""
                    SELECT discovery_id, application_id, session_id, policy_hash,
                           observation_count, validated_count, result_hash, created_at
                    FROM discoveries WHERE application_id = ? ORDER BY created_at DESC
                """, (application_id,))
            else:
                cursor.execute("""
                    SELECT discovery_id, application_id, session_id, policy_hash,
                           observation_count, validated_count, result_hash, created_at
                    FROM discoveries ORDER BY created_at DESC
                """)
            return [dict(r) for r in cursor.fetchall()]


discovery_persistence = DiscoveryPersistenceStore()
