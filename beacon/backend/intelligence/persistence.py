"""BEACON V2 — Phase 10 Intelligence Persistence Store.

Provides durable SQLite persistence for structured CertificationExplanations and
audit logs in beacon.sqlite3.
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
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
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
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cert_exp_cert_id ON certification_explanations(certification_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cert_exp_app_id ON certification_explanations(application_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_audit_cert_id ON explanation_audit_log(certification_id)")
                conn.commit()
        except Exception as exc:
            logger.warning(f"Failed to initialize SQLite intelligence persistence tables: {exc}")

    def save_explanation(self, explanation: CertificationExplanation) -> CertificationExplanation:
        """Saves or replaces a CertificationExplanation record."""
        payload_json = explanation.model_dump_json()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO certification_explanations (
                    explanation_id, certification_id, application_id, project_id,
                    context_fingerprint, content_hash, overall_verdict, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                explanation.explanation_id,
                explanation.certification_id,
                explanation.application_id,
                explanation.project_id,
                explanation.context_fingerprint,
                explanation.content_hash,
                explanation.overall_verdict,
                payload_json,
                explanation.generated_at,
            ))
            conn.commit()
        return explanation

    def get_explanation(self, certification_id: str) -> Optional[CertificationExplanation]:
        """Retrieves the latest explanation for a certification run."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT payload_json FROM certification_explanations
                WHERE certification_id = ?
                ORDER BY created_at DESC LIMIT 1
            """, (certification_id,))
            row = cursor.fetchone()
            if row:
                data = json.loads(row["payload_json"])
                return CertificationExplanation.model_validate(data)
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
    ):
        """Logs an explanation generation or Q&A audit event."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO explanation_audit_log (
                        audit_id, user_id, certification_id, application_id,
                        mode, provider, model, context_fingerprint, fallback_used, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    datetime.now(timezone.utc).isoformat(),
                ))
                conn.commit()
        except Exception as exc:
            logger.warning(f"Failed to log explanation audit event: {exc}")


intelligence_persistence = IntelligencePersistenceStore()
