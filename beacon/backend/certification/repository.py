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

from .models import (
    CertificationArtifact,
    CertificationCase,
    CertificationInputSet,
    ImmutabilityError,
    compute_input_set_canonical_hash,
    verify_artifact_integrity,
)

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "beacon.sqlite3"


class CertificationRepository:
    """Manages immutable storage and retrieval of CertificationArtifacts, InputSets, and Cases."""

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

    def _save_artifact_tx(self, artifact: CertificationArtifact, conn: sqlite3.Connection) -> CertificationArtifact:
        cid = artifact.certification_id
        if not verify_artifact_integrity(artifact):
            raise ValueError(f"Integrity violation: Certificate #{cid} content hash does not match its canonical content.")

        cursor = conn.cursor()
        cursor.execute("SELECT content_hash, payload_json FROM certification_artifacts WHERE certification_id = ?", (cid,))
        row = cursor.fetchone()
        if row:
            existing_hash = row[0]
            if existing_hash == artifact.content_hash:
                return artifact
            raise ImmutabilityError(
                f"Immutability violation: Certificate #{cid} already exists with different content hash "
                f"('{existing_hash}' vs '{artifact.content_hash}'). Overwrite forbidden."
            )

        cursor.execute("""
            INSERT INTO certification_artifacts (
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
        return artifact

    def save_artifact(self, artifact: CertificationArtifact) -> CertificationArtifact:
        """Saves a CertificationArtifact immutably with integrity and duplicate verification."""
        cid = artifact.certification_id
        if not verify_artifact_integrity(artifact):
            raise ValueError(f"Integrity violation: Certificate #{cid} content hash does not match its canonical content.")

        if cid in self._memory_artifacts:
            existing = self._memory_artifacts[cid]
            if existing.content_hash == artifact.content_hash:
                return existing
            raise ImmutabilityError(f"Immutability violation: Certificate #{cid} already exists with different content hash.")

        with sqlite3.connect(self._db_path) as conn:
            self._save_artifact_tx(artifact, conn)
            conn.commit()

        self._memory_artifacts[cid] = artifact
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

    def _save_input_set_tx(self, input_set: CertificationInputSet, conn: sqlite3.Connection) -> CertificationInputSet:
        cursor = conn.cursor()
        cursor.execute("SELECT canonical_hash, payload_json FROM input_sets WHERE input_set_id = ?", (input_set.input_set_id,))
        row = cursor.fetchone()
        if row:
            existing_hash = row[0]
            if existing_hash == input_set.canonical_hash:
                return input_set
            raise ImmutabilityError(
                f"Immutability violation: InputSet '{input_set.input_set_id}' already exists with different canonical hash "
                f"('{existing_hash}' vs '{input_set.canonical_hash}'). Overwrite forbidden."
            )

        cursor.execute("""
            INSERT INTO input_sets (
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
        return input_set

    def save_input_set(self, input_set: CertificationInputSet) -> CertificationInputSet:
        """Saves a CertificationInputSet immutably with integrity and duplicate verification."""
        with sqlite3.connect(self._db_path) as conn:
            self._save_input_set_tx(input_set, conn)
            conn.commit()
        return input_set

    def get_input_set(self, input_set_id: str) -> Optional[CertificationInputSet]:
        """Retrieves a CertificationInputSet by ID."""
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

    def _save_certification_cases_tx(self, cases: list[CertificationCase], conn: sqlite3.Connection):
        if not cases:
            return
        cursor = conn.cursor()
        for c in cases:
            cursor.execute("SELECT payload_json FROM certification_cases WHERE case_id = ?", (c.case_id,))
            row = cursor.fetchone()
            if row:
                existing_payload = json.loads(row[0])
                current_payload = json.loads(c.model_dump_json())
                if existing_payload == current_payload:
                    continue
                raise ImmutabilityError(
                    f"Immutability violation: CertificationCase '{c.case_id}' already exists with different content. Overwrite forbidden."
                )

            cursor.execute("""
                INSERT INTO certification_cases (
                    case_id, run_id, input_set_id, case_index, input_hash, classification, severity, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                c.case_id,
                c.run_id,
                c.input_set_id,
                c.case_index,
                c.input_hash,
                c.classification,
                c.severity,
                c.model_dump_json(),
            ))

    def save_certification_cases(self, cases: list[CertificationCase]):
        """Saves a list of CertificationCase records immutably with integrity checks."""
        if not cases:
            return
        with sqlite3.connect(self._db_path) as conn:
            self._save_certification_cases_tx(cases, conn)
            conn.commit()

    def save_certification_run_atomic(
        self,
        input_set: CertificationInputSet,
        cases: list[CertificationCase],
        artifact: CertificationArtifact,
    ) -> CertificationArtifact:
        """Atomically persists the input set, all certification cases, and the final artifact
        in a single SQLite transaction with strict immutability checks."""
        with sqlite3.connect(self._db_path) as conn:
            try:
                self._save_input_set_tx(input_set, conn)
                self._save_certification_cases_tx(cases, conn)
                self._save_artifact_tx(artifact, conn)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                logger.error(f"Atomic certification persistence failed; transaction rolled back: {exc}")
                raise

        self._memory_artifacts[artifact.certification_id] = artifact
        return artifact

    def list_certification_cases(
        self,
        run_id: str,
        limit: int = 100,
        offset: int = 0,
        classification: Optional[str] = None,
    ) -> list[CertificationCase]:
        """Lists cases associated with a certification run, optionally filtered by classification."""
        results = []
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                query = "SELECT payload_json FROM certification_cases WHERE run_id = ?"
                params: list[object] = [run_id]
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

    def list_cases_for_input_set(
        self,
        input_set_id: str,
        run_id: Optional[str] = None,
    ) -> list[CertificationCase]:
        """Retrieves all persisted CertificationCases for an input set, ordered by case_index."""
        results = []
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                if run_id:
                    cursor.execute(
                        "SELECT payload_json FROM certification_cases WHERE input_set_id = ? AND run_id = ? ORDER BY case_index ASC",
                        (input_set_id, run_id),
                    )
                else:
                    cursor.execute(
                        "SELECT payload_json FROM certification_cases WHERE input_set_id = ? ORDER BY case_index ASC",
                        (input_set_id,),
                    )
                for row in cursor.fetchall():
                    results.append(CertificationCase.model_validate_json(row[0]))
        except Exception as exc:
            logger.debug(f"SQLite list cases for input set notice: {exc}")
        return results

    def verify_input_set_integrity(self, input_set_id: str, run_id: Optional[str] = None) -> bool:
        """Reconstructs the input-set hash from persisted cases and confirms it matches the stored input-set hash."""
        input_set = self.get_input_set(input_set_id)
        if not input_set:
            return False
        cases = self.list_cases_for_input_set(input_set_id, run_id)
        if not cases or len(cases) != input_set.input_count:
            return False
        reconstructed_hash = compute_input_set_canonical_hash(cases)
        return reconstructed_hash == input_set.canonical_hash

# Module-level default repository singleton
certification_repository = CertificationRepository()
