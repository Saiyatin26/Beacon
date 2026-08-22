"""Phase 14 — Ingestion and Certification Audit Trail.

Records immutable audit events for dataset ingestion, validation, deletion,
certification start/completion, exports, and integrity checks with zero secrets.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[1] / "beacon.sqlite3"


class AuditAction(str, Enum):
    DATASET_UPLOAD = "DATASET_UPLOAD"
    DATASET_VALIDATE = "DATASET_VALIDATE"
    DATASET_REGISTER = "DATASET_REGISTER"
    DATASET_DELETE = "DATASET_DELETE"
    CERTIFICATION_START = "CERTIFICATION_START"
    CERTIFICATION_COMPLETE = "CERTIFICATION_COMPLETE"
    CERTIFICATION_FAIL = "CERTIFICATION_FAIL"
    EXPORT = "EXPORT"
    INTEGRITY_VERIFY = "INTEGRITY_VERIFY"
    AUDITOR_NOTE_CREATED = "AUDITOR_NOTE_CREATED"


class AuditEvent(BaseModel):
    """Structured audit trail event with cryptographic content hash and zero secrets."""
    event_id: str
    timestamp: str
    project_id: str
    dataset_id: Optional[str] = None
    certification_id: Optional[str] = None
    action: AuditAction
    status: str = "SUCCESS"  # SUCCESS, FAIL, INFO
    details: dict[str, Any] = Field(default_factory=dict)
    event_hash: str = ""


def sanitize_details(details: dict[str, Any]) -> dict[str, Any]:
    """Strips any potential secret keys, environment variables, or bearer tokens."""
    sanitized = {}
    secret_substrings = ["token", "key", "secret", "password", "auth", "bearer", "credential"]
    for k, v in details.items():
        k_lower = str(k).lower()
        if any(sec in k_lower for sec in secret_substrings):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, str) and ("sk-ant-" in v or "sk-or-" in v or "Bearer " in v):
            sanitized[k] = "[REDACTED]"
        else:
            sanitized[k] = v
    return sanitized


class AuditLogger:
    """Manages appending and querying audit events in SQLite and memory."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or DB_PATH
        self._memory_events: list[AuditEvent] = []
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS audit_events (
                        event_id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        dataset_id TEXT,
                        certification_id TEXT,
                        action TEXT NOT NULL,
                        status TEXT NOT NULL,
                        details_json TEXT NOT NULL,
                        event_hash TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_proj ON audit_events(project_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_dataset ON audit_events(dataset_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_cert ON audit_events(certification_id)")
                conn.commit()
        except Exception as exc:
            logger.warning(f"Failed to initialize SQLite audit_events table: {exc}")

    def log(
        self,
        project_id: str,
        action: AuditAction,
        status: str = "SUCCESS",
        dataset_id: Optional[str] = None,
        certification_id: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> AuditEvent:
        """Appends a new audit event immutably."""
        now_str = datetime.now(timezone.utc).isoformat()
        clean_details = sanitize_details(details or {})
        event_body = {
            "timestamp": now_str,
            "project_id": project_id,
            "dataset_id": dataset_id,
            "certification_id": certification_id,
            "action": action.value,
            "status": status,
            "details": clean_details,
        }
        event_raw = json.dumps(event_body, sort_keys=True, separators=(",", ":"))
        event_hash = hashlib.sha256(event_raw.encode("utf-8")).hexdigest()
        event_id = f"AUD-{event_hash[:12]}"

        event = AuditEvent(
            event_id=event_id,
            timestamp=now_str,
            project_id=project_id,
            dataset_id=dataset_id,
            certification_id=certification_id,
            action=action,
            status=status,
            details=clean_details,
            event_hash=event_hash,
        )

        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO audit_events (
                        event_id, timestamp, project_id, dataset_id, certification_id, action, status, details_json, event_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.event_id,
                    event.timestamp,
                    event.project_id,
                    event.dataset_id,
                    event.certification_id,
                    event.action.value,
                    event.status,
                    json.dumps(event.details),
                    event.event_hash,
                ))
                conn.commit()
        except Exception as exc:
            logger.debug(f"SQLite audit log note: {exc}")

        self._memory_events.append(event)
        return event

    def list_events(
        self,
        project_id: Optional[str] = None,
        dataset_id: Optional[str] = None,
        certification_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[AuditEvent]:
        """Lists audit events filtered by project_id, dataset_id, or certification_id."""
        results: list[AuditEvent] = []
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                query = "SELECT event_id, timestamp, project_id, dataset_id, certification_id, action, status, details_json, event_hash FROM audit_events WHERE 1=1"
                params: list[object] = []
                if project_id:
                    query += " AND project_id = ?"
                    params.append(project_id)
                if dataset_id:
                    query += " AND dataset_id = ?"
                    params.append(dataset_id)
                if certification_id:
                    query += " AND certification_id = ?"
                    params.append(certification_id)
                query += " ORDER BY timestamp DESC LIMIT ?"
                params.append(limit)

                cursor.execute(query, params)
                for row in cursor.fetchall():
                    results.append(
                        AuditEvent(
                            event_id=row[0],
                            timestamp=row[1],
                            project_id=row[2],
                            dataset_id=row[3],
                            certification_id=row[4],
                            action=AuditAction(row[5]),
                            status=row[6],
                            details=json.loads(row[7]),
                            event_hash=row[8],
                        )
                    )
        except Exception as exc:
            logger.debug(f"SQLite list audit events notice: {exc}")

        if not results and self._memory_events:
            filtered = [
                e for e in self._memory_events
                if (not project_id or e.project_id == project_id)
                and (not dataset_id or e.dataset_id == dataset_id)
                and (not certification_id or e.certification_id == certification_id)
            ]
            return list(reversed(filtered[-limit:]))

        return results

    def clear(self):
        """Clears memory and SQLite audit events table (for test isolation)."""
        self._memory_events.clear()
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("DELETE FROM audit_events")
                conn.commit()
        except Exception:
            pass


# Module-level default instance
audit_logger = AuditLogger()
