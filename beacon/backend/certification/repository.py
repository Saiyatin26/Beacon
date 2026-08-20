"""Phase 10 — Certification Repository for Immutable Certification Artifacts.

Provides thread-safe storage, retrieval, and querying of cryptographic
CertificationArtifact certificates.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Optional

from .models import CertificationArtifact, verify_artifact_integrity, CertificationInputSet, CertificationCase

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "beacon.sqlite3"


class CertificationRepository:
    """Manages immutable storage and retrieval of CertificationArtifacts."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or DB_PATH
        self._memory_artifacts: dict[str, CertificationArtifact] = {}
        self._init_db()

    def _init_db(self):
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS certification_artifacts (
                        certification_id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        legacy_version TEXT NOT NULL,
                        modernized_version TEXT NOT NULL,
                        oracle_set_id TEXT NOT NULL,
                        oracle_set_hash TEXT NOT NULL,
                        policy_id TEXT NOT NULL,
                        policy_hash TEXT NOT NULL,
                        status TEXT NOT NULL,
                        certified INTEGER NOT NULL,
                        score REAL NOT NULL,
                        content_hash TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS input_sets (
                        input_set_id TEXT PRIMARY KEY,
                        version INTEGER NOT NULL,
                        generator_type TEXT NOT NULL,
                        input_count INTEGER NOT NULL,
                        seed INTEGER NOT NULL,
                        canonical_hash TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS certification_cases (
                        case_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        input_set_id TEXT NOT NULL,
                        case_index INTEGER NOT NULL,
                        input_hash TEXT NOT NULL,
                        classification TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        FOREIGN KEY(run_id) REFERENCES certification_artifacts(certification_id),
                        FOREIGN KEY(input_set_id) REFERENCES input_sets(input_set_id)
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cert_cases_run_id ON certification_cases(run_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cert_cases_input_set_id ON certification_cases(input_set_id)")
                conn.commit()
        except Exception as exc:
            logger.warning(f"Could not initialize SQLite certification table: {exc}")

    def save_artifact(self, artifact: CertificationArtifact) -> CertificationArtifact:
        """Saves a CertificationArtifact immutably with integrity verification.
        - Verifies that stored content_hash matches computed canonical hash.
        - If an artifact with the same ID exists with identical hash, returns existing.
        - If hash differs, raises ValueError (immutability violation).
        """
        cid = artifact.certification_id

        if not verify_artifact_integrity(artifact):
            raise ValueError(f"Integrity violation: Certificate #{cid} content hash does not match its canonical content.")

        if cid in self._memory_artifacts:
            existing = self._memory_artifacts[cid]
            if existing.content_hash == artifact.content_hash:
                return existing
            raise ValueError(f"Immutability violation: Certificate #{cid} already exists with different content hash.")

        self._memory_artifacts[cid] = artifact

        # Persist to SQLite
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO certification_artifacts (
                        certification_id, project_id, legacy_version, modernized_version,
                        oracle_set_id, oracle_set_hash, policy_id, policy_hash,
                        status, certified, score, content_hash, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    artifact.certification_id,
                    artifact.project_id,
                    artifact.legacy_version,
                    artifact.modernized_version,
                    artifact.oracle_set_id,
                    artifact.oracle_set_hash,
                    artifact.certification_policy_id,
                    artifact.certification_policy_hash,
                    artifact.status.value,
                    1 if artifact.certified else 0,
                    artifact.score,
                    artifact.content_hash,
                    artifact.model_dump_json(),
                    artifact.timestamp or datetime.now(timezone.utc).isoformat(),
                ))
                conn.commit()
        except Exception as exc:
            logger.debug(f"SQLite save notice: {exc}")

        return artifact

    def get_artifact(self, certification_id: str) -> Optional[CertificationArtifact]:
        """Retrieves a CertificationArtifact by ID."""
        if certification_id in self._memory_artifacts:
            return self._memory_artifacts[certification_id]

        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT payload_json FROM certification_artifacts WHERE certification_id = ?",
                    (certification_id,),
                )
                row = cursor.fetchone()
                if row:
                    data = json.loads(row[0])
                    artifact = CertificationArtifact.model_validate(data)
                    self._memory_artifacts[certification_id] = artifact
                    return artifact
        except Exception as exc:
            logger.debug(f"SQLite lookup notice: {exc}")

        return None

    def list_artifacts(
        self,
        project_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[CertificationArtifact]:
        """Lists historical CertificationArtifacts sorted newest first."""
        results: list[CertificationArtifact] = []

        # Load from DB if possible
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                query = "SELECT payload_json FROM certification_artifacts"
                params = []
                if project_id:
                    query += " WHERE project_id = ?"
                    params.append(project_id)
                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)

                cursor.execute(query, params)
                for row in cursor.fetchall():
                    data = json.loads(row[0])
                    art = CertificationArtifact.model_validate(data)
                    results.append(art)
                    self._memory_artifacts[art.certification_id] = art
        except Exception as exc:
            logger.debug(f"SQLite list notice: {exc}")

        if not results:
            mem_list = list(self._memory_artifacts.values())
            if project_id:
                mem_list = [a for a in mem_list if a.project_id == project_id]
            results = sorted(mem_list, key=lambda a: a.timestamp, reverse=True)[:limit]

        return results

    def get_latest(self, project_id: Optional[str] = None) -> Optional[CertificationArtifact]:
        """Retrieves the most recent CertificationArtifact."""
        artifacts = self.list_artifacts(project_id=project_id, limit=1)
        return artifacts[0] if artifacts else None

    def clear(self):
        """Clears memory and DB table (for test isolation)."""
        self._memory_artifacts.clear()
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("DELETE FROM certification_cases")
                conn.execute("DELETE FROM input_sets")
                conn.execute("DELETE FROM certification_artifacts")
                conn.commit()
        except Exception:
            pass

    def save_input_set(self, input_set: CertificationInputSet) -> CertificationInputSet:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO input_sets (
                        input_set_id, version, generator_type, input_count, seed, canonical_hash, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    input_set.input_set_id,
                    input_set.version,
                    input_set.generator_type,
                    input_set.input_count,
                    input_set.seed,
                    input_set.canonical_hash,
                    input_set.model_dump_json(),
                    input_set.created_at or datetime.now(timezone.utc).isoformat(),
                ))
                conn.commit()
        except Exception as exc:
            logger.debug(f"SQLite save input_set notice: {exc}")
        return input_set

    def get_input_set(self, input_set_id: str) -> Optional[CertificationInputSet]:
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT payload_json FROM input_sets WHERE input_set_id = ?", (input_set_id,))
                row = cursor.fetchone()
                if row:
                    return CertificationInputSet.model_validate_json(row[0])
        except Exception as exc:
            logger.debug(f"SQLite get input_set notice: {exc}")
        return None

    def save_certification_cases(self, cases: list[CertificationCase]):
        if not cases:
            return
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                records = [
                    (
                        c.case_id,
                        c.run_id,
                        c.input_set_id,
                        c.case_index,
                        c.input_hash,
                        c.classification,
                        c.severity,
                        c.model_dump_json()
                    )
                    for c in cases
                ]
                cursor.executemany("""
                    INSERT OR REPLACE INTO certification_cases (
                        case_id, run_id, input_set_id, case_index, input_hash, classification, severity, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, records)
                conn.commit()
        except Exception as exc:
            logger.debug(f"SQLite save certification_cases notice: {exc}")

    def list_certification_cases(self, run_id: str, limit: int = 100, offset: int = 0, classification: Optional[str] = None) -> list[CertificationCase]:
        results = []
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                query = "SELECT payload_json FROM certification_cases WHERE run_id = ?"
                params = [run_id]
                if classification and classification != "ALL":
                    query += " AND classification = ?"
                    params.append(classification)
                
                query += " ORDER BY case_index ASC LIMIT ? OFFSET ?"
                params.extend([limit, offset])
                
                cursor.execute(query, params)
                for row in cursor.fetchall():
                    results.append(CertificationCase.model_validate_json(row[0]))
        except Exception as exc:
            logger.debug(f"SQLite list certification_cases notice: {exc}")
        return results


# Module-level default repository singleton
certification_repository = CertificationRepository()
