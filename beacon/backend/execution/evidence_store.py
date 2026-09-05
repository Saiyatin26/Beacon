"""BEACON V2 — Phase 3 Evidence & Session Persistence Layer (EvidenceStore).

Provides dual storage (authoritative SQLite tables + local filesystem artifacts) for
paired execution sessions, immutable input sets, individual evidence records, and cryptographic
evidence bundles with tamper-detection verification.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Optional, Union


from common.config import settings
from .evidence_models import (
    EvidenceBundle,
    EvidenceManifest,
    EvidencePersistenceStatus,
    EvidenceRecord,
    EvidenceType,
    compute_content_hash,
)

from .input_set import InputSet
from .paired_models import PairedExecutionSession, PairedExecutionStatus

logger = logging.getLogger("beacon.execution.evidence_store")


class EvidenceStore:
    """Manages dual persistence and retrieval of Phase 3 execution evidence and sessions."""

    def __init__(
        self,
        db_path: Optional[Union[Path, str]] = None,
        storage_root: Optional[Union[Path, str]] = None,
    ):
        self._db_path = Path(db_path) if db_path else Path(settings.database_path)
        self._storage_root = Path(storage_root) if storage_root else Path("data") / "evidence"
        self._memory_sessions: dict[str, PairedExecutionSession] = {}
        self._memory_input_sets: dict[str, InputSet] = {}
        self._memory_records: dict[str, EvidenceRecord] = {}
        self._memory_bundles: dict[str, EvidenceBundle] = {}
        self._init_storage()

    def _init_storage(self) -> None:
        """Initializes SQLite schema and filesystem directories."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._storage_root.mkdir(parents=True, exist_ok=True)

            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS paired_execution_sessions (
                        session_id TEXT PRIMARY KEY,
                        correlation_id TEXT NOT NULL,
                        application_id TEXT NOT NULL,
                        reference_adapter TEXT NOT NULL,
                        target_adapter TEXT NOT NULL,
                        input_set_id TEXT NOT NULL,
                        input_set_hash TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        completed_at TEXT,
                        total_inputs INTEGER NOT NULL DEFAULT 0,
                        executed_inputs INTEGER NOT NULL DEFAULT 0,
                        bundle_id TEXT,
                        bundle_hash TEXT,
                        session_json TEXT NOT NULL,
                        session_hash TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_paired_sess_app ON paired_execution_sessions(application_id);")

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS paired_input_sets (
                        input_set_id TEXT PRIMARY KEY,
                        source TEXT NOT NULL,
                        input_count INTEGER NOT NULL,
                        content_hash TEXT NOT NULL,
                        input_set_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)


                conn.execute("""
                    CREATE TABLE IF NOT EXISTS evidence_records (
                        evidence_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        execution_id TEXT,
                        application_id TEXT,
                        role TEXT NOT NULL,
                        input_id TEXT,
                        evidence_type TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        capture_status TEXT NOT NULL,
                        persistence_status TEXT NOT NULL DEFAULT 'PERSISTED',
                        record_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_evid_rec_sess ON evidence_records(session_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_evid_rec_inp ON evidence_records(session_id, input_id);")

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS evidence_bundles (
                        bundle_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL UNIQUE,
                        correlation_id TEXT NOT NULL,
                        application_id TEXT NOT NULL,
                        input_set_id TEXT NOT NULL,
                        bundle_hash TEXT NOT NULL,
                        persistence_status TEXT NOT NULL DEFAULT 'PERSISTED',
                        persistence_error TEXT,
                        manifest_json TEXT NOT NULL,
                        bundle_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                self._ensure_column(conn, "evidence_records", "persistence_status", "TEXT NOT NULL DEFAULT 'PERSISTED'")
                self._ensure_column(conn, "evidence_bundles", "persistence_status", "TEXT NOT NULL DEFAULT 'PERSISTED'")
                self._ensure_column(conn, "evidence_bundles", "persistence_error", "TEXT")
                conn.commit()
        except Exception as exc:
            logger.warning(f"Could not initialize evidence SQLite schema: {exc}")

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_def: str) -> None:
        try:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table});")
            existing = {row[1] for row in cursor.fetchall()}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def};")
        except Exception:
            pass


    # ==========================================================================
    # Session Persistence
    # ==========================================================================

    def save_session(self, session: PairedExecutionSession) -> PairedExecutionSession:
        """Persists a PairedExecutionSession to SQLite and in-memory cache."""
        self._memory_sessions[session.session_id] = session
        sess_hash = session.compute_session_hash()
        sess_json = session.model_dump_json()

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    INSERT INTO paired_execution_sessions (
                        session_id, correlation_id, application_id, reference_adapter, target_adapter,
                        input_set_id, input_set_hash, status, created_at, completed_at,
                        total_inputs, executed_inputs, bundle_id, bundle_hash, session_json, session_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        status=excluded.status,
                        completed_at=excluded.completed_at,
                        total_inputs=excluded.total_inputs,
                        executed_inputs=excluded.executed_inputs,
                        bundle_id=excluded.bundle_id,
                        bundle_hash=excluded.bundle_hash,
                        session_json=excluded.session_json,
                        session_hash=excluded.session_hash
                """, (
                    session.session_id,
                    session.correlation_id,
                    session.application_id,
                    session.reference_adapter_name,
                    session.target_adapter_name,
                    session.input_set_id,
                    session.input_set_hash,
                    session.status.value,
                    session.created_at,
                    session.completed_at,
                    session.total_inputs,
                    session.executed_inputs,
                    session.bundle_id,
                    session.bundle_hash,
                    sess_json,
                    sess_hash,
                ))
                conn.commit()
        except Exception as exc:
            logger.warning(f"Failed to persist paired session '{session.session_id}' to SQLite: {exc}")

        return session

    def get_session(self, session_id: str) -> Optional[PairedExecutionSession]:
        """Retrieves a PairedExecutionSession by ID."""
        if session_id in self._memory_sessions:
            return self._memory_sessions[session_id]

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT session_json FROM paired_execution_sessions WHERE session_id = ?",
                    (session_id,),
                )
                row = cursor.fetchone()
                if row:
                    data = json.loads(row[0])
                    sess = PairedExecutionSession(**data)
                    self._memory_sessions[session_id] = sess
                    return sess
        except Exception as exc:
            logger.warning(f"Error reading paired session '{session_id}' from SQLite: {exc}")

        return None

    def list_sessions(self, application_id: Optional[str] = None, limit: int = 50) -> list[PairedExecutionSession]:
        """Lists paired execution sessions with optional application filter."""
        sessions: list[PairedExecutionSession] = []
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                if application_id:
                    cursor.execute(
                        "SELECT session_json FROM paired_execution_sessions WHERE application_id = ? ORDER BY created_at DESC LIMIT ?",
                        (application_id, limit),
                    )
                else:
                    cursor.execute(
                        "SELECT session_json FROM paired_execution_sessions ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    )
                for row in cursor.fetchall():
                    data = json.loads(row[0])
                    sessions.append(PairedExecutionSession(**data))
        except Exception as exc:
            logger.warning(f"Error querying paired sessions: {exc}")
            # Fallback to memory
            sessions = [
                s for s in self._memory_sessions.values()
                if not application_id or s.application_id == application_id
            ][:limit]

        return sessions

    # ==========================================================================
    # InputSet Persistence
    # ==========================================================================

    def save_input_set(self, input_set: InputSet) -> InputSet:
        """Persists an immutable InputSet."""
        self._memory_input_sets[input_set.input_set_id] = input_set
        set_json = input_set.model_dump_json()

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    INSERT INTO paired_input_sets (input_set_id, source, input_count, content_hash, input_set_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(input_set_id) DO UPDATE SET
                        content_hash=excluded.content_hash,
                        input_set_json=excluded.input_set_json
                """, (
                    input_set.input_set_id,
                    input_set.source,
                    input_set.input_count,
                    input_set.content_hash,
                    set_json,
                    input_set.created_at,
                ))
                conn.commit()
        except Exception as exc:
            logger.warning(f"Failed to persist input set '{input_set.input_set_id}' to SQLite: {exc}")

        return input_set

    def get_input_set(self, input_set_id: str) -> Optional[InputSet]:
        """Retrieves an InputSet by ID."""
        if input_set_id in self._memory_input_sets:
            return self._memory_input_sets[input_set_id]

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT input_set_json FROM paired_input_sets WHERE input_set_id = ?",
                    (input_set_id,),
                )
                row = cursor.fetchone()
                if row:
                    data = json.loads(row[0])
                    iset = InputSet(**data)
                    self._memory_input_sets[input_set_id] = iset
                    return iset
        except Exception as exc:
            logger.warning(f"Error reading input set '{input_set_id}' from SQLite: {exc}")

        return None

    # ==========================================================================
    # Evidence Record Persistence
    # ==========================================================================

    def save_record(self, record: EvidenceRecord) -> EvidenceRecord:
        """Persists an atomic EvidenceRecord with explicit persistence status."""
        rec_json = record.model_dump_json()

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    INSERT INTO evidence_records (
                        evidence_id, session_id, execution_id, application_id, role, input_id,
                        evidence_type, content_hash, size_bytes, capture_status, persistence_status, record_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(evidence_id) DO UPDATE SET
                        record_json=excluded.record_json,
                        content_hash=excluded.content_hash,
                        persistence_status=excluded.persistence_status
                """, (
                    record.evidence_id,
                    record.session_id,
                    record.execution_id,
                    record.application_id,
                    record.role,
                    record.input_id,
                    record.evidence_type.value,
                    record.content_hash,
                    record.size_bytes,
                    record.capture_status.value,
                    EvidencePersistenceStatus.PERSISTED.value,
                    rec_json,
                    record.timestamp,
                ))
                conn.commit()
            record.persistence_status = EvidencePersistenceStatus.PERSISTED
        except Exception as exc:
            record.persistence_status = EvidencePersistenceStatus.FAILED
            logger.error(f"Failed to persist evidence record '{record.evidence_id}' to SQLite: {exc}")

        self._memory_records[record.evidence_id] = record
        return record

    def get_record(self, evidence_id: str) -> Optional[EvidenceRecord]:
        """Retrieves an EvidenceRecord by ID."""
        if evidence_id in self._memory_records:
            return self._memory_records[evidence_id]

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT record_json FROM evidence_records WHERE evidence_id = ?",
                    (evidence_id,),
                )
                row = cursor.fetchone()
                if row:
                    data = json.loads(row[0])
                    rec = EvidenceRecord(**data)
                    self._memory_records[evidence_id] = rec
                    return rec
        except Exception as exc:
            logger.warning(f"Error reading evidence record '{evidence_id}' from SQLite: {exc}")

        return None

    def list_records_for_session(self, session_id: str) -> list[EvidenceRecord]:
        """Retrieves all EvidenceRecord items belonging to a session."""
        records: list[EvidenceRecord] = []
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT record_json FROM evidence_records WHERE session_id = ? ORDER BY sequence ASC",
                    (session_id,),
                )
                for row in cursor.fetchall():
                    data = json.loads(row[0])
                    records.append(EvidenceRecord(**data))
        except Exception as exc:
            logger.warning(f"Error querying session evidence records: {exc}")
            records = [r for r in self._memory_records.values() if r.session_id == session_id]

        return records

    def get_paired_evidence(
        self, session_id: str, input_id: str
    ) -> tuple[list[EvidenceRecord], list[EvidenceRecord]]:
        """Retrieves paired evidence records segregated by Reference and Target for a specific input."""
        all_recs = self.list_records_for_session(session_id)
        ref_recs = [r for r in all_recs if r.input_id == input_id and r.role in ("reference", "legacy")]
        target_recs = [r for r in all_recs if r.input_id == input_id and r.role in ("target", "modernized")]
        return ref_recs, target_recs

    # ==========================================================================
    # Evidence Bundle & Filesystem Persistence
    # ==========================================================================

    def save_bundle(self, bundle: EvidenceBundle) -> EvidenceBundle:
        """Persists an EvidenceBundle to both SQLite and the filesystem artifact store."""
        bundle_json = bundle.model_dump_json(indent=2)
        manifest_json = bundle.manifest.model_dump_json(indent=2)
        errors: list[str] = []

        # 1. SQLite Persistence
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    INSERT INTO evidence_bundles (
                        bundle_id, session_id, correlation_id, application_id, input_set_id,
                        bundle_hash, persistence_status, persistence_error, manifest_json, bundle_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        bundle_id=excluded.bundle_id,
                        bundle_hash=excluded.bundle_hash,
                        persistence_status=excluded.persistence_status,
                        persistence_error=excluded.persistence_error,
                        manifest_json=excluded.manifest_json,
                        bundle_json=excluded.bundle_json
                """, (
                    bundle.bundle_id,
                    bundle.session_id,
                    bundle.correlation_id,
                    bundle.application_id,
                    bundle.input_set_id,
                    bundle.bundle_hash,
                    EvidencePersistenceStatus.PERSISTED.value,
                    None,
                    manifest_json,
                    bundle_json,
                    bundle.created_at,
                ))
                conn.commit()
        except Exception as exc:
            err_msg = f"SQLite save failed: {exc}"
            errors.append(err_msg)
            logger.error(f"Failed to persist bundle '{bundle.bundle_id}' to SQLite: {exc}")

        # 2. Filesystem Artifact Persistence
        try:
            sess_dir = self._storage_root / bundle.session_id
            sess_dir.mkdir(parents=True, exist_ok=True)

            bundle_file = sess_dir / "bundle.json"
            manifest_file = sess_dir / "manifest.json"

            with open(bundle_file, "w", encoding="utf-8") as f:
                f.write(bundle_json)

            with open(manifest_file, "w", encoding="utf-8") as f:
                f.write(manifest_json)
        except Exception as exc:
            err_msg = f"Filesystem save failed: {exc}"
            errors.append(err_msg)
            logger.error(f"Failed to write bundle artifact to filesystem: {exc}")

        if not errors:
            bundle.persistence_status = EvidencePersistenceStatus.PERSISTED
            bundle.persistence_error = None
        elif len(errors) == 2:
            bundle.persistence_status = EvidencePersistenceStatus.FAILED
            bundle.persistence_error = "; ".join(errors)
        else:
            bundle.persistence_status = EvidencePersistenceStatus.PARTIAL
            bundle.persistence_error = "; ".join(errors)

        self._memory_bundles[bundle.session_id] = bundle
        return bundle


    def get_bundle(self, session_id: str) -> Optional[EvidenceBundle]:
        """Retrieves an EvidenceBundle by session ID from memory, filesystem, or SQLite."""
        if session_id in self._memory_bundles:
            return self._memory_bundles[session_id]

        # Try filesystem first
        bundle_file = self._storage_root / session_id / "bundle.json"
        if bundle_file.exists():
            try:
                with open(bundle_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    bndl = EvidenceBundle(**data)
                    self._memory_bundles[session_id] = bndl
                    return bndl
            except Exception as exc:
                logger.warning(f"Failed to load bundle from filesystem '{bundle_file}': {exc}")

        # Try SQLite
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT bundle_json FROM evidence_bundles WHERE session_id = ?",
                    (session_id,),
                )
                row = cursor.fetchone()
                if row:
                    data = json.loads(row[0])
                    bndl = EvidenceBundle(**data)
                    self._memory_bundles[session_id] = bndl
                    return bndl
        except Exception as exc:
            logger.warning(f"Error reading bundle from SQLite: {exc}")

        return None

    # ==========================================================================
    # Cryptographic Integrity Verification
    # ==========================================================================

    def verify_evidence_integrity(self, evidence_id: str) -> tuple[bool, str]:
        """Verifies that an EvidenceRecord's payload matches its registered SHA-256 content_hash."""
        rec = self.get_record(evidence_id)
        if not rec:
            return False, f"Evidence record '{evidence_id}' not found."

        canonical = json.dumps(rec.payload, sort_keys=True, separators=(",", ":"), default=str)
        recomputed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        if recomputed == rec.content_hash:
            return True, f"Integrity verified (SHA-256: {rec.content_hash[:16]}...)"
        else:
            return False, (
                f"TAMPER DETECTED: Hash mismatch for evidence '{evidence_id}'! "
                f"Expected: {rec.content_hash}, Recomputed: {recomputed}"
            )

    def verify_bundle_integrity(self, session_id: str) -> tuple[bool, str]:
        """Verifies that an EvidenceBundle's manifest items hash matches its bundle_hash."""
        bundle = self.get_bundle(session_id)
        if not bundle:
            return False, f"Evidence bundle for session '{session_id}' not found."

        recomputed = bundle.manifest.compute_bundle_hash()
        if recomputed == bundle.bundle_hash:
            return True, f"Bundle integrity verified (bundle_hash: {bundle.bundle_hash[:16]}...)"
        else:
            return False, (
                f"TAMPER DETECTED: Bundle hash mismatch for session '{session_id}'! "
                f"Expected: {bundle.bundle_hash}, Recomputed: {recomputed}"
            )


evidence_store = EvidenceStore()
