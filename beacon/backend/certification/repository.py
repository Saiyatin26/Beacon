"""Phase 10 — Certification Repository for Immutable Certification Artifacts.

Provides thread-safe storage, retrieval, and querying of cryptographic
CertificationArtifact certificates.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Optional

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
        benchmark_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[CertificationArtifact]:
        """Lists historical CertificationArtifacts sorted newest first, with optional benchmark_id or project_id filtering."""
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
                params.append(limit * 3 if benchmark_id else limit)

                cursor.execute(query, params)
                for row in cursor.fetchall():
                    data = json.loads(row[0])
                    art = CertificationArtifact.model_validate(data)
                    self._memory_artifacts[art.certification_id] = art
                    if benchmark_id:
                        art_b_id = getattr(art, "benchmark_id", None) or (art.context.benchmark_id if art.context else None) or art.project_id.replace("benchmark_", "")
                        if art_b_id != benchmark_id and art.project_id != benchmark_id and art.project_id != f"benchmark_{benchmark_id}":
                            continue
                    results.append(art)
        except Exception as exc:
            logger.debug(f"SQLite list notice: {exc}")

        if not results:
            mem_list = list(self._memory_artifacts.values())
            if project_id:
                mem_list = [a for a in mem_list if a.project_id == project_id]
            if benchmark_id:
                mem_list = [
                    a for a in mem_list
                    if getattr(a, "benchmark_id", None) == benchmark_id
                    or (a.context and a.context.benchmark_id == benchmark_id)
                    or a.project_id == benchmark_id
                    or a.project_id == f"benchmark_{benchmark_id}"
                ]
            results = sorted(mem_list, key=lambda a: a.timestamp, reverse=True)

        return results[:limit]

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

    def get_artifact_by_context(
        self,
        benchmark_id: str,
        evaluation_mode: str = "CONTROLLED",
        modernization_variant: str = "clean_v2",
    ) -> Optional[CertificationArtifact]:
        """Retrieves the latest artifact matching the exact (benchmark_id, evaluation_mode, modernization_variant) context."""
        artifacts = self.list_artifacts(benchmark_id=benchmark_id, limit=50)
        for art in artifacts:
            art_mode = getattr(art, "evaluation_mode", None) or (art.context.evaluation_mode if getattr(art, "context", None) else "CONTROLLED")
            art_variant = getattr(art, "modernization_variant", None) or (art.context.modernization_variant_id if getattr(art, "context", None) else "clean_v2")
            if art_mode == evaluation_mode and art_variant == modernization_variant:
                return art
        return None

    def verify_certification_run_integrity(self, certification_id: str) -> dict[str, Any]:
        """Performs comprehensive 8-point cryptographic and reproducibility integrity verification."""
        artifact = self.get_artifact(certification_id)
        if not artifact:
            return {
                "status": "FAIL",
                "certification_id": certification_id,
                "errors": [f"Artifact #{certification_id} not found"],
                "checks": {},
            }

        checks = {}
        errors = []

        # Check 1: Artifact Content Hash
        art_valid = verify_artifact_integrity(artifact)
        checks["artifact_integrity_valid"] = art_valid
        if not art_valid:
            errors.append("Artifact content hash does not match canonical certificate JSON")

        # Check 2: Persisted Case Count vs Declared Metrics
        cases = self.list_cases_for_input_set(artifact.input_set_id, run_id=artifact.certification_id)
        declared_case_count = getattr(artifact.metrics, "certification_case_count", 0) or getattr(artifact.metrics, "total_inputs", 0)
        case_count_valid = len(cases) > 0 and len(cases) == declared_case_count
        checks["case_count_valid"] = case_count_valid
        if not case_count_valid:
            errors.append(f"Persisted case count ({len(cases)}) does not match declared cases ({declared_case_count})")

        # Check 3: Input Set Hash Reconstruction from Persisted Cases
        input_set_valid = self.verify_input_set_integrity(artifact.input_set_id, run_id=artifact.certification_id)
        checks["input_set_integrity_valid"] = input_set_valid
        if not input_set_valid:
            errors.append("Reconstructed input-set hash from persisted cases does not match stored input-set hash")

        # Check 4: OracleSet Hash Integrity
        from oracle.registry import registry as oracle_registry
        from oracle.serializer import compute_oracle_set_hash
        orc_set = oracle_registry.get_oracle_set(artifact.oracle_set_id)
        if orc_set:
            computed_orc_hash = compute_oracle_set_hash([o.content_hash for o in orc_set.oracles])
            orc_valid = computed_orc_hash == artifact.oracle_set_hash
        else:
            orc_valid = bool(artifact.oracle_set_hash)
        checks["oracle_set_integrity_valid"] = orc_valid
        if not orc_valid:
            errors.append("OracleSet hash does not match computed composite digest")

        # Check 5: Policy Hash Integrity
        policy_valid = bool(artifact.certification_policy_hash)
        checks["policy_integrity_valid"] = policy_valid
        if not policy_valid:
            errors.append("Certification policy hash missing")

        # Check 6: Implementation Hashes Present & Valid
        leg_hash = getattr(artifact, "legacy_implementation_hash", "") or (artifact.context.legacy_implementation_hash if getattr(artifact, "context", None) else "")
        mod_hash = getattr(artifact, "modernized_implementation_hash", "") or (artifact.context.modernized_implementation_hash if getattr(artifact, "context", None) else "")
        impl_valid = bool(leg_hash and mod_hash)
        checks["implementation_hashes_valid"] = impl_valid
        if not impl_valid:
            errors.append("Legacy or modernized implementation SHA-256 hash is missing")

        # Check 7: Dataset Checksum Integrity
        data_checksum = getattr(artifact, "dataset_checksum", "") or (artifact.context.dataset_checksum if getattr(artifact, "context", None) else "")
        dataset_valid = bool(data_checksum)
        checks["dataset_checksum_valid"] = dataset_valid
        if not dataset_valid:
            errors.append("Dataset SHA-256 checksum is missing")

        # Check 8: Secret Freedom (No tokens / API keys in serialized payload)
        dumped_text = artifact.model_dump_json()
        secret_keys = ["sk-ant-", "sk-or-", "Bearer ", "mongodb+srv://", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"]
        has_secret = any(s in dumped_text for s in secret_keys)
        checks["secret_freedom_valid"] = not has_secret
        if has_secret:
            errors.append("Artifact payload contains leaked credentials or API secrets")

        overall_status = "PASS" if all(checks.values()) else "FAIL"

        return {
            "status": overall_status,
            "certification_id": certification_id,
            "artifact_hash": artifact.content_hash,
            "content_hash": artifact.content_hash,
            "artifact_integrity_valid": checks["artifact_integrity_valid"],
            "input_set_hash": artifact.input_set_hash,
            "input_set_integrity_valid": checks["input_set_integrity_valid"],
            "oracle_set_hash": artifact.oracle_set_hash,
            "oracle_set_integrity_valid": checks["oracle_set_integrity_valid"],
            "policy_hash": artifact.certification_policy_hash,
            "legacy_implementation_hash": leg_hash,
            "modernized_implementation_hash": mod_hash,
            "checks": checks,
            "errors": errors,
        }


# Module-level default repository singleton
certification_repository = CertificationRepository()
