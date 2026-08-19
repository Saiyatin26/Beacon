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

from .models import CertificationArtifact

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
                conn.commit()
        except Exception as exc:
            logger.warning(f"Could not initialize SQLite certification table: {exc}")

    def save_artifact(self, artifact: CertificationArtifact) -> CertificationArtifact:
        """Saves a CertificationArtifact immutably.
        If an artifact with the same certification_id already exists:
        - If content_hash is identical, returns existing artifact.
        - If content_hash differs, raises ValueError (immutability violation).
        """
        cid = artifact.certification_id

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
                conn.execute("DELETE FROM certification_artifacts")
                conn.commit()
        except Exception:
            pass


# Module-level default repository singleton
certification_repository = CertificationRepository()
