"""BEACON V2 — Phase 10 Intelligence Persistence Store.

Provides durable SQLite persistence for structured CertificationExplanations and
audit logs in beacon.sqlite3 with strict failure semantics, audit tracking, and cache isolation.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Optional

from common.config import settings
from .models import CertificationExplanation

logger = logging.getLogger("beacon.intelligence.persistence")


class IntelligencePersistenceStore:
    """Manages SQLite storage for structured certification explanations and audit records."""

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = Path(db_path) if db_path else Path(settings.database_path)
        self.persistence_available: bool = False
        self._init_db()

    def _init_db(self):
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS certification_explanations (
                        explanation_id TEXT PRIMARY KEY,
                        certification_id TEXT NOT NULL,
                        application_id TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        context_fingerprint TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        overall_verdict TEXT NOT NULL,
                        cache_key TEXT,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(certification_explanations)")
                columns = [row[1] for row in cursor.fetchall()]
                if "cache_key" not in columns:
                    conn.execute("ALTER TABLE certification_explanations ADD COLUMN cache_key TEXT")

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS explanation_audit_log (
                        audit_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        certification_id TEXT NOT NULL,
                        application_id TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        model TEXT NOT NULL,
                        context_fingerprint TEXT NOT NULL,
                        fallback_used INTEGER NOT NULL,
                        audit_status TEXT NOT NULL DEFAULT 'PERSISTED',
                        created_at TEXT NOT NULL
                    )
                """)
                cursor.execute("PRAGMA table_info(explanation_audit_log)")
                audit_cols = [row[1] for row in cursor.fetchall()]
                if "audit_status" not in audit_cols:
                    conn.execute("ALTER TABLE explanation_audit_log ADD COLUMN audit_status TEXT NOT NULL DEFAULT 'PERSISTED'")

                conn.execute("CREATE INDEX IF NOT EXISTS idx_cert_exp_cert_id ON certification_explanations(certification_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cert_exp_app_id ON certification_explanations(application_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cert_exp_cache_key ON certification_explanations(cache_key)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_audit_cert_id ON explanation_audit_log(certification_id)")
                conn.commit()
            self.persistence_available = True
        except Exception as exc:
            self.persistence_available = False
            logger.error(f"Failed to initialize SQLite intelligence persistence tables: {exc}", exc_info=True)

    def save_explanation(self, explanation: CertificationExplanation) -> CertificationExplanation:
        """Saves or replaces a CertificationExplanation record with explicit error status tracking."""
        if not self.persistence_available:
            explanation.persistence_status = "FAILED"
            return explanation

        try:
            payload_json = explanation.model_dump_json()
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO certification_explanations (
                        explanation_id, certification_id, application_id, project_id,
                        context_fingerprint, content_hash, overall_verdict, cache_key, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    explanation.explanation_id,
                    explanation.certification_id,
                    explanation.application_id,
                    explanation.project_id,
                    explanation.context_fingerprint,
                    explanation.content_hash,
                    explanation.overall_verdict,
                    explanation.cache_key,
                    payload_json,
                    explanation.generated_at,
                ))
                conn.commit()
            explanation.persistence_status = "SUCCESS"
            return explanation
        except Exception as exc:
            logger.error(f"Failed to persist certification explanation '{explanation.explanation_id}': {exc}", exc_info=True)
            explanation.persistence_status = "FAILED"
            return explanation

    def get_explanation(
        self,
        certification_id: str,
        cache_key: Optional[str] = None,
        context_fingerprint: Optional[str] = None,
    ) -> Optional[CertificationExplanation]:
        """Retrieves the explanation for a certification run matching cache_key or fingerprint if supplied."""
        if not self.persistence_available:
            return None

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                if cache_key:
                    cursor.execute("""
                        SELECT payload_json FROM certification_explanations
                        WHERE certification_id = ? AND cache_key = ?
                        ORDER BY rowid DESC LIMIT 1
                    """, (certification_id, cache_key))
                elif context_fingerprint:
                    cursor.execute("""
                        SELECT payload_json FROM certification_explanations
                        WHERE certification_id = ? AND context_fingerprint = ?
                        ORDER BY rowid DESC LIMIT 1
                    """, (certification_id, context_fingerprint))
                else:
                    cursor.execute("""
                        SELECT payload_json FROM certification_explanations
                        WHERE certification_id = ?
                        ORDER BY rowid DESC LIMIT 1
                    """, (certification_id,))

                row = cursor.fetchone()
                if row:
                    data = json.loads(row["payload_json"])
                    return CertificationExplanation.model_validate(data)
        except Exception as exc:
            logger.error(f"Failed to query certification explanation for '{certification_id}': {exc}", exc_info=True)
        return None

    def log_audit_event(
        self,
        audit_id: str,
        user_id: str,
        certification_id: str,
        application_id: str,
        mode: str,
        provider: str,
        model: str,
        context_fingerprint: str,
        fallback_used: bool,
    ) -> bool:
        """Logs an explanation generation or Q&A audit event without silent failure."""
        if not self.persistence_available:
            return False

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO explanation_audit_log (
                        audit_id, user_id, certification_id, application_id,
                        mode, provider, model, context_fingerprint, fallback_used, audit_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    audit_id,
                    user_id,
                    certification_id,
                    application_id,
                    mode,
                    provider,
                    model,
                    context_fingerprint,
                    1 if fallback_used else 0,
                    "PERSISTED",
                    datetime.now(timezone.utc).isoformat(),
                ))
                conn.commit()
            return True
        except Exception as exc:
            logger.error(f"Failed to log explanation audit event '{audit_id}': {exc}", exc_info=True)
            return False


intelligence_persistence = IntelligencePersistenceStore()
