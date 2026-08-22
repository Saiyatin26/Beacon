"""Phase 15 — Auditor Notes and Human Review Storage.

Stores human reviewer annotations, comments, and audit sign-offs in an
isolated annotation layer strictly decoupled from immutable certification
artifacts and cryptographic hashes.
"""

from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
import sqlite3
from typing import Optional
import uuid

from .dossier_models import AuditorNote
from ingestion.audit import audit_logger, AuditAction, sanitize_details

logger = logging.getLogger(__name__)
DB_PATH = Path(__file__).resolve().parents[1] / "beacon.sqlite3"


class AuditorNotesStore:
    """Manages appending and querying human reviewer notes in SQLite and memory."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or DB_PATH
        self._memory_notes: list[AuditorNote] = []
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS auditor_notes (
                        note_id TEXT PRIMARY KEY,
                        certification_id TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        author TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_cert ON auditor_notes(certification_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_proj ON auditor_notes(project_id)")
                conn.commit()
        except Exception as exc:
            logger.warning(f"Failed to initialize SQLite auditor_notes table: {exc}")

    def add_note(
        self,
        certification_id: str,
        project_id: str,
        content: str,
        author: str = "Auditor",
    ) -> AuditorNote:
        """Appends an immutable auditor note and logs an audit trail event."""
        clean_content = content.strip()
        sanitized_author = author.strip() or "Auditor"
        now_str = datetime.now(timezone.utc).isoformat()
        
        # Secret sanitization
        redacted = sanitize_details({"content": clean_content})["content"]
        
        note_id = f"NOTE-{uuid.uuid4().hex[:12]}"
        note = AuditorNote(
            note_id=note_id,
            certification_id=certification_id,
            project_id=project_id,
            author=sanitized_author,
            content=redacted,
            timestamp=now_str,
        )

        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT INTO auditor_notes (note_id, certification_id, project_id, author, content, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (note.note_id, note.certification_id, note.project_id, note.author, note.content, note.timestamp))
                conn.commit()
        except Exception as exc:
            logger.debug(f"SQLite note save note: {exc}")

        self._memory_notes.append(note)

        # Log audit trail event (read-only audit event, does NOT alter certification artifact)
        audit_logger.log(
            project_id=project_id,
            action=AuditAction.AUDITOR_NOTE_CREATED,
            status="INFO",
            certification_id=certification_id,
            details={"note_id": note.note_id, "author": note.author, "note_length": len(note.content)},
        )

        return note

    def list_notes(
        self,
        certification_id: str,
        project_id: Optional[str] = None,
    ) -> list[AuditorNote]:
        """Lists all auditor notes for a certification run with optional project scoping."""
        results: list[AuditorNote] = []
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                if project_id:
                    cursor.execute("""
                        SELECT note_id, certification_id, project_id, author, content, timestamp
                        FROM auditor_notes
                        WHERE certification_id = ? AND project_id = ?
                        ORDER BY timestamp ASC
                    """, (certification_id, project_id))
                else:
                    cursor.execute("""
                        SELECT note_id, certification_id, project_id, author, content, timestamp
                        FROM auditor_notes
                        WHERE certification_id = ?
                        ORDER BY timestamp ASC
                    """, (certification_id,))
                
                for row in cursor.fetchall():
                    results.append(
                        AuditorNote(
                            note_id=row[0],
                            certification_id=row[1],
                            project_id=row[2],
                            author=row[3],
                            content=row[4],
                            timestamp=row[5],
                        )
                    )
        except Exception as exc:
            logger.debug(f"SQLite note query note: {exc}")

        # Fallback to memory if SQLite yielded nothing
        if not results:
            for n in self._memory_notes:
                if n.certification_id == certification_id:
                    if project_id is None or n.project_id == project_id:
                        results.append(n)

        return results


auditor_notes_store = AuditorNotesStore()
