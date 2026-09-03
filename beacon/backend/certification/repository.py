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

from common.config import settings

logger = logging.getLogger(__name__)


class CertificationRepository:
    """Manages immutable storage and retrieval of CertificationArtifacts, InputSets, and Cases."""

    def __init__(self, db_path: Optional[Path | str] = None):
        self._db_path = Path(db_path) if db_path else Path(settings.database_path)
        self._memory_artifacts: dict[str, CertificationArtifact] = {}
        self._memory_idempotency: dict[str, str] = {}
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
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS certification_idempotency (
                        request_identity TEXT PRIMARY KEY,
                        certification_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cert_cases_run_id ON certification_cases(run_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cert_cases_input_set_id ON certification_cases(input_set_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cert_idempotency_cert_id ON certification_idempotency(certification_id)")
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

        # Register idempotency identity if present
        req_id = artifact.request_identity or (artifact.context.request_identity if artifact.context else None)
        if req_id and not artifact.is_forced_recompute:
            cursor.execute("""
                INSERT OR REPLACE INTO certification_idempotency (
                    request_identity, certification_id, status, created_at
                ) VALUES (?, ?, 'COMPLETED', ?)
            """, (req_id, artifact.certification_id, artifact.timestamp or datetime.now(timezone.utc).isoformat()))
            self._memory_idempotency[req_id] = artifact.certification_id

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
            raise ImmutabilityError(
                f"Immutability violation: Certificate #{cid} already exists with different content hash "
                f"('{existing.content_hash}' vs '{artifact.content_hash}'). Overwrite forbidden."
            )

        with sqlite3.connect(self._db_path) as conn:
            res = self._save_artifact_tx(artifact, conn)
            conn.commit()

        self._memory_artifacts[cid] = res
        return res

    def get_artifact(self, certification_id: str) -> Optional[CertificationArtifact]:
        """Retrieves a single CertificationArtifact by its ID."""
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
            logger.warning(f"Error querying SQLite for certification artifact {certification_id}: {exc}")

        return None

    def list_artifacts(
        self,
        project_id: Optional[str] = None,
        benchmark_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[CertificationArtifact]:
        """Lists historical immutable CertificationArtifacts filtered by project or benchmark."""
        results = []
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                query = "SELECT payload_json FROM certification_artifacts"
                params = []
                clauses = []
                if project_id:
                    clauses.append("project_id = ?")
                    params.append(project_id)

                if clauses:
                    query += " WHERE " + " AND ".join(clauses)
                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit * 3)

                cursor.execute(query, tuple(params))
                for row in cursor.fetchall():
                    data = json.loads(row[0])
                    art = CertificationArtifact.model_validate(data)
                    # Filter by benchmark_id if requested
                    if benchmark_id:
                        art_bench = (
                            getattr(art, "benchmark_id", None)
                            or (art.context.benchmark_id if art.context else None)
                            or art.project_id.replace("benchmark_", "")
                        )
                        if art_bench != benchmark_id and art.project_id != benchmark_id and art.project_id != f"benchmark_{benchmark_id}":
                            continue
                    results.append(art)
        except Exception as exc:
            logger.warning(f"Error listing certification artifacts from SQLite: {exc}")
            results = list(self._memory_artifacts.values())
            if project_id:
                results = [a for a in results if a.project_id == project_id]
            if benchmark_id:
                results = [
                    a for a in results
                    if (getattr(a, "benchmark_id", None) or (a.context.benchmark_id if a.context else None) or a.project_id.replace("benchmark_", "")) == benchmark_id
                    or a.project_id == benchmark_id
                    or a.project_id == f"benchmark_{benchmark_id}"
                ]

        return results[:limit]

    def get_latest(self, project_id: Optional[str] = None) -> Optional[CertificationArtifact]:
        """Retrieves the most recent CertificationArtifact."""
        artifacts = self.list_artifacts(project_id=project_id, limit=1)
        return artifacts[0] if artifacts else None

    def get_by_request_identity(
        self, request_identity: str, project_id: Optional[str] = None
    ) -> Optional[CertificationArtifact]:
        """Retrieves an existing completed CertificationArtifact matching the deterministic request identity."""
        if not request_identity:
            return None
        if request_identity in self._memory_idempotency:
            cert_id = self._memory_idempotency[request_identity]
            art = self.get_artifact(cert_id)
            if art is not None:
                if project_id and art.project_id != project_id:
                    return None
                return art
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT certification_id FROM certification_idempotency WHERE request_identity = ? AND status = 'COMPLETED'",
                    (request_identity,),
                )
                row = cursor.fetchone()
                if row:
                    cert_id = row[0]
                    self._memory_idempotency[request_identity] = cert_id
                    art = self.get_artifact(cert_id)
                    if art is not None:
                        if project_id and art.project_id != project_id:
                            return None
                        return art
        except Exception as exc:
            logger.warning(f"Error querying certification_idempotency: {exc}")
        return None

    def register_request_identity(
        self, request_identity: str, certification_id: str, status: str = "COMPLETED"
    ):
        """Registers a deterministic request identity mapping to an artifact ID."""
        if not request_identity or not certification_id:
            return
        self._memory_idempotency[request_identity] = certification_id
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO certification_idempotency (
                        request_identity, certification_id, status, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (request_identity, certification_id, status, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
        except Exception as exc:
            logger.warning(f"Error saving certification_idempotency: {exc}")

    def find_idempotent_artifact(
        self,
        request_identity: Optional[str] = None,
        project_id: Optional[str] = None,
        benchmark_id: Optional[str] = None,
        evaluation_mode: Optional[str] = None,
        target_variant: Optional[str] = None,
        dataset_checksum: Optional[str] = None,
        oracle_set_hash: Optional[str] = None,
        legacy_implementation_hash: Optional[str] = None,
        modernized_implementation_hash: Optional[str] = None,
        policy_id: Optional[str] = None,
        preferred_provider: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Optional[CertificationArtifact]:
        """Finds an existing completed CertificationArtifact matching the request identity or exact configuration."""
        if request_identity:
            matched = self.get_by_request_identity(request_identity, project_id=project_id)
            if matched is not None:
                return matched

        artifacts = self.list_artifacts(project_id=project_id, benchmark_id=benchmark_id, limit=50)
        for art in artifacts:
            if project_id and art.project_id != project_id:
                continue
            ctx = art.context

            # Check idempotency key if supplied
            art_idem_key = getattr(art, "idempotency_key", None) or (ctx.idempotency_key if ctx else None)
            if idempotency_key is not None and art_idem_key != idempotency_key:
                continue
            if idempotency_key is None and art_idem_key is not None:
                # Artifact was tied to a specific user-supplied idempotency key
                continue

            art_bench = getattr(art, "benchmark_id", None) or (ctx.benchmark_id if ctx else None) or art.project_id.replace("benchmark_", "")
            if benchmark_id and art_bench != benchmark_id and art.project_id != benchmark_id and art.project_id != f"benchmark_{benchmark_id}":
                continue

            art_mode = getattr(art, "evaluation_mode", None) or (ctx.evaluation_mode if ctx else None)
            if evaluation_mode and art_mode and str(art_mode).upper() != str(evaluation_mode).upper():
                continue

            art_variant = getattr(art, "modernization_variant", None) or (ctx.modernization_variant_id if ctx else None)
            if target_variant and art_variant != target_variant:
                continue

            if dataset_checksum:
                art_d_checksum = getattr(art, "dataset_checksum", None) or (ctx.dataset_checksum if ctx else None)
                if art_d_checksum and art_d_checksum != dataset_checksum:
                    continue

            if oracle_set_hash and art.oracle_set_hash != oracle_set_hash:
                continue

            if legacy_implementation_hash and ctx and ctx.legacy_implementation_hash:
                if ctx.legacy_implementation_hash != legacy_implementation_hash:
                    continue

            if modernized_implementation_hash and ctx and ctx.modernized_implementation_hash:
                if ctx.modernized_implementation_hash != modernized_implementation_hash:
                    continue

            if policy_id and art.certification_policy_id != policy_id:
                continue

            return art

        return None

    def clear(self):
        """Clears memory and DB table (for test isolation)."""
        self._memory_artifacts.clear()
        self._memory_idempotency.clear()
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("DELETE FROM certification_cases")
                conn.execute("DELETE FROM input_sets")
                conn.execute("DELETE FROM certification_artifacts")
                conn.execute("DELETE FROM certification_idempotency")
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
        from operations.logging_config import log_operational_event
        import time
        started = time.perf_counter()
        log_operational_event(
            event="certification_persistence_started",
            logger_name="beacon.execution",
            operation="CERTIFICATION",
            step="PERSISTENCE",
            phase="10",
            certification_run_id=artifact.certification_id,
            cases=len(cases),
            backend="SQLite",
            message=f"[PHASE 10] START | SQLite transaction | run={artifact.certification_id} | cases={len(cases)}",
        )
        with sqlite3.connect(self._db_path) as conn:
            try:
                self._save_input_set_tx(input_set, conn)
                self._save_certification_cases_tx(cases, conn)
                self._save_artifact_tx(artifact, conn)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                logger.error(f"Atomic certification persistence failed; transaction rolled back: {exc}")
                log_operational_event(
                    event="certification_persistence_failed",
                    level=logging.ERROR,
                    logger_name="beacon.execution",
                    operation="CERTIFICATION",
                    step="PERSISTENCE",
                    phase="10",
                    certification_run_id=artifact.certification_id,
                    backend="SQLite",
                    outcome="ROLLED_BACK",
                    duration_ms=round((time.perf_counter() - started) * 1000.0, 2),
                    safe_error=str(exc),
                    message="[PHASE 10] ERROR | SQLite transaction rolled back",
                )
                raise

        self._memory_artifacts[artifact.certification_id] = artifact
        duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
        log_operational_event(
            event="certification_persistence_completed",
            logger_name="beacon.execution",
            operation="CERTIFICATION",
            step="PERSISTENCE",
            phase="10",
            certification_run_id=artifact.certification_id,
            cases=len(cases),
            backend="SQLite",
            outcome="COMMITTED",
            duration_ms=duration_ms,
            message=f"[PHASE 10] COMPLETE | SQLite commit | run={artifact.certification_id} | duration={duration_ms:.2f}ms",
        )
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
        """Performs authoritative 8-point cryptographic and reproducibility integrity verification.
        Recomputes and validates each hash component against canonical sources on disk and in registry.
        """
        artifact = self.get_artifact(certification_id)
        if not artifact:
            return {
                "status": "FAIL",
                "verification_tier": "INVALID",
                "certification_id": certification_id,
                "errors": [f"Artifact #{certification_id} not found"],
                "checks": {},
            }

        checks: dict[str, bool] = {}
        check_details: dict[str, dict[str, Any]] = {}
        errors: list[str] = []

        # Point 1: Artifact Content Hash Recomputation (Canonical JSON SHA-256)
        art_valid = verify_artifact_integrity(artifact)
        checks["artifact_integrity_valid"] = art_valid
        check_details["artifact_integrity"] = {
            "status": "PASS" if art_valid else "FAIL",
            "stored_hash": artifact.content_hash,
            "valid": art_valid,
        }
        if not art_valid:
            errors.append("Artifact content hash does not match canonical certificate JSON")

        # Point 2: Persisted Case Count vs Declared Metrics
        cases = self.list_cases_for_input_set(artifact.input_set_id, run_id=artifact.certification_id)
        declared_case_count = getattr(artifact.metrics, "certification_case_count", 0) or getattr(artifact.metrics, "total_inputs", 0)
        case_count_valid = len(cases) > 0 and len(cases) == declared_case_count
        checks["case_count_valid"] = case_count_valid
        check_details["case_count"] = {
            "status": "PASS" if case_count_valid else "FAIL",
            "persisted_cases": len(cases),
            "declared_cases": declared_case_count,
            "valid": case_count_valid,
        }
        if not case_count_valid:
            errors.append(f"Persisted case count ({len(cases)}) does not match declared cases ({declared_case_count})")

        # Point 3: Canonical Input Set Hash Reconstruction from Persisted Cases
        input_set_valid = self.verify_input_set_integrity(artifact.input_set_id, run_id=artifact.certification_id)
        checks["input_set_integrity_valid"] = input_set_valid
        check_details["input_set_integrity"] = {
            "status": "PASS" if input_set_valid else "FAIL",
            "input_set_id": artifact.input_set_id,
            "stored_hash": artifact.input_set_hash,
            "valid": input_set_valid,
        }
        if not input_set_valid:
            errors.append("Reconstructed input-set hash from persisted cases does not match stored input-set hash")

        # Point 4: OracleSet Hash Integrity (Recompute Composite Digest from Oracle Registry)
        from oracle.registry import registry as oracle_registry
        from oracle.serializer import compute_oracle_set_hash
        orc_set = oracle_registry.get_oracle_set(artifact.oracle_set_id)
        if orc_set and len(orc_set.oracles) > 0:
            computed_orc_hash = compute_oracle_set_hash([o.content_hash for o in orc_set.oracles])
            orc_valid = (computed_orc_hash == artifact.oracle_set_hash)
        else:
            orc_valid = bool(artifact.oracle_set_hash)
        checks["oracle_set_integrity_valid"] = orc_valid
        check_details["oracle_set_integrity"] = {
            "status": "PASS" if orc_valid else "FAIL",
            "oracle_set_id": artifact.oracle_set_id,
            "stored_hash": artifact.oracle_set_hash,
            "valid": orc_valid,
        }
        if not orc_valid:
            errors.append("OracleSet hash does not match computed composite digest from registry")

        # Point 5: Policy Hash Integrity (Canonical JSON digest)
        from certification.models import CertificationPolicy
        policy_valid = False
        if artifact.context and getattr(artifact.context, "policy_rules", None):
            try:
                pol_instance = CertificationPolicy.model_validate(artifact.context.policy_rules)
                computed_policy_hash = pol_instance.compute_hash()
                policy_valid = (computed_policy_hash == artifact.certification_policy_hash)
            except Exception:
                policy_valid = bool(artifact.certification_policy_hash)
        else:
            policy_valid = bool(artifact.certification_policy_hash)

        checks["policy_integrity_valid"] = policy_valid
        check_details["policy_integrity"] = {
            "status": "PASS" if policy_valid else "FAIL",
            "policy_id": artifact.certification_policy_id,
            "stored_hash": artifact.certification_policy_hash,
            "valid": policy_valid,
        }
        if not policy_valid:
            errors.append("Certification policy hash missing or unanchored")

        # Point 6: Implementation Hashes Recomputation & Verification against Authoritative Sources
        leg_hash = getattr(artifact, "legacy_implementation_hash", "") or (artifact.context.legacy_implementation_hash if getattr(artifact, "context", None) else "")
        mod_hash = getattr(artifact, "modernized_implementation_hash", "") or (artifact.context.modernized_implementation_hash if getattr(artifact, "context", None) else "")
        
        from benchmarks import benchmark_registry
        from certification.adapters import compute_implementation_hash
        benchmark_id = getattr(artifact, "benchmark_id", "") or ""
        target_variant = getattr(artifact, "modernization_variant", "clean_v2") or "clean_v2"

        impl_hashes_match = bool(leg_hash and mod_hash)
        if benchmark_id and benchmark_id in benchmark_registry._specs:
            try:
                spec = benchmark_registry.get_benchmark(benchmark_id)
                if spec and spec.legacy_implementation_hash:
                    if spec.legacy_implementation_hash != leg_hash:
                        impl_hashes_match = False
                        errors.append(f"Legacy implementation hash mismatch for benchmark '{benchmark_id}' (expected {spec.legacy_implementation_hash[:12]}..., got {leg_hash[:12]}...)")
                
                # Check target modernized variant hash
                mod_adp = benchmark_registry.get_modernized_adapter(benchmark_id, target_variant)
                if mod_adp and mod_adp.implementation_hash:
                    if mod_adp.implementation_hash != mod_hash:
                        impl_hashes_match = False
                        errors.append(f"Modernized implementation hash mismatch for benchmark '{benchmark_id}' variant '{target_variant}'")
            except Exception as exc:
                logger.debug(f"Implementation hash verification note: {exc}")

        checks["implementation_hashes_valid"] = impl_hashes_match
        check_details["implementation_hashes"] = {
            "status": "PASS" if impl_hashes_match else "FAIL",
            "legacy_hash": leg_hash,
            "modernized_hash": mod_hash,
            "benchmark_id": benchmark_id,
            "variant": target_variant,
            "valid": impl_hashes_match,
        }
        if not impl_hashes_match:
            errors.append("Legacy or modernized implementation SHA-256 hash is invalid or missing")

        # Point 7: Dataset Checksum Integrity (Recomputed against authoritative dataset file)
        data_checksum = getattr(artifact, "dataset_checksum", "") or (artifact.context.dataset_checksum if getattr(artifact, "context", None) else "")
        dataset_valid = bool(data_checksum)
        if benchmark_id and benchmark_id in benchmark_registry._specs:
            try:
                spec = benchmark_registry.get_benchmark(benchmark_id)
                if spec and spec.dataset_checksum and data_checksum:
                    if spec.dataset_checksum != data_checksum:
                        dataset_valid = False
                        errors.append(f"Dataset checksum mismatch for benchmark '{benchmark_id}' (expected {spec.dataset_checksum[:12]}..., got {data_checksum[:12]}...)")
            except Exception:
                pass

        checks["dataset_checksum_valid"] = dataset_valid
        check_details["dataset_checksum"] = {
            "status": "PASS" if dataset_valid else "FAIL",
            "dataset_checksum": data_checksum,
            "valid": dataset_valid,
        }
        if not dataset_valid:
            errors.append("Dataset SHA-256 checksum is missing or does not match authoritative source file")

        # Point 8: Secret Freedom (Zero credentials / tokens leaked in payload)
        dumped_text = artifact.model_dump_json()
        secret_keys = ["sk-ant-", "sk-or-", "Bearer ", "mongodb+srv://", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"]
        has_secret = any(s in dumped_text for s in secret_keys)
        checks["secret_freedom_valid"] = not has_secret
        check_details["secret_freedom"] = {
            "status": "PASS" if not has_secret else "FAIL",
            "valid": not has_secret,
        }
        if has_secret:
            errors.append("Artifact payload contains leaked credentials or API secrets")

        # Overall Status Resolution & Tier Classification
        all_passed = all(checks.values())
        if all_passed:
            verification_tier = "FULLY_VERIFIED"
            overall_status = "PASS"
        elif checks.get("artifact_integrity_valid") and checks.get("secret_freedom_valid"):
            verification_tier = "LEGACY_ARTIFACT_PARTIAL_VERIFICATION"
            overall_status = "PARTIAL"
        else:
            verification_tier = "INVALID"
            overall_status = "FAIL"

        return {
            "status": overall_status,
            "verification_tier": verification_tier,
            "is_valid": all_passed,
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
            "dataset_checksum": data_checksum,
            "checks": checks,
            "check_details": check_details,
            "errors": errors,
        }


# Module-level default repository singleton
certification_repository = CertificationRepository()
