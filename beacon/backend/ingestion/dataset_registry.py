"""Phase 14 — User Dataset Registry and Persistence Layer.

Provides thread-safe and SQLite-backed storage for ingested datasets, manifests,
and test inputs with project namespace isolation and duplicate detection.
"""

import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Optional

from certification.models import CertificationTestInput
from .dataset_models import (
    DatasetIngestionManifest,
    DatasetLifecycleStatus,
    UserDatasetRecord,
)
from .audit import AuditAction, audit_logger

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[1] / "beacon.sqlite3"


class UserDatasetRegistry:
    """Manages storage, retrieval, listing, and deletion of custom user-supplied datasets."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or DB_PATH
        self._memory_datasets: dict[str, UserDatasetRecord] = {}
        self._memory_inputs: dict[str, list[CertificationTestInput]] = {}
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_datasets (
                        dataset_id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        dataset_name TEXT NOT NULL,
                        version TEXT NOT NULL,
                        checksum TEXT NOT NULL,
                        manifest_json TEXT NOT NULL,
                        records_json TEXT NOT NULL,
                        test_inputs_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_user_ds_proj ON user_datasets(project_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_user_ds_chk ON user_datasets(checksum)")
                conn.commit()
        except Exception as exc:
            logger.warning(f"Failed to initialize SQLite user_datasets table: {exc}")

    def register_dataset(
        self,
        manifest: DatasetIngestionManifest,
        records: list[dict[str, Any]],
        test_inputs: list[CertificationTestInput],
    ) -> UserDatasetRecord:
        """Registers a validated user dataset immutably with idempotent duplicate detection."""
        ds_id = manifest.dataset_id

        # Check existing by ID in memory or DB
        existing = self.get_dataset(ds_id)
        if existing:
            logger.info(f"Dataset '{ds_id}' already registered with identical checksum; reusing existing manifest.")
            audit_logger.log(
                project_id=manifest.project_id,
                action=AuditAction.DATASET_REGISTER,
                status="SUCCESS",
                dataset_id=ds_id,
                details={"reuse": True, "checksum": manifest.checksum, "row_count": manifest.row_count},
            )
            return existing

        user_record = UserDatasetRecord(
            dataset_id=ds_id,
            project_id=manifest.project_id,
            dataset_name=manifest.dataset_name,
            version=manifest.version,
            manifest=manifest,
            canonical_records=records,
            created_at=manifest.created_at,
        )

        test_inputs_json = json.dumps([inp.model_dump(mode="json") for inp in test_inputs])
        manifest_json = manifest.model_dump_json()
        records_json = json.dumps(records)

        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO user_datasets (
                        dataset_id, project_id, dataset_name, version, checksum, manifest_json, records_json, test_inputs_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ds_id,
                    manifest.project_id,
                    manifest.dataset_name,
                    manifest.version,
                    manifest.checksum,
                    manifest_json,
                    records_json,
                    test_inputs_json,
                    manifest.created_at,
                ))
                conn.commit()
        except Exception as exc:
            logger.error(f"Failed to persist user dataset {ds_id} to SQLite: {exc}")

        self._memory_datasets[ds_id] = user_record
        self._memory_inputs[ds_id] = test_inputs

        audit_logger.log(
            project_id=manifest.project_id,
            action=AuditAction.DATASET_REGISTER,
            status="SUCCESS",
            dataset_id=ds_id,
            details={
                "dataset_name": manifest.dataset_name,
                "version": manifest.version,
                "checksum": manifest.checksum,
                "row_count": manifest.row_count,
                "provenance": manifest.declared_provenance.value,
            },
        )

        return user_record

    def get_dataset(self, dataset_id: str) -> Optional[UserDatasetRecord]:
        """Retrieves complete UserDatasetRecord by dataset_id."""
        if dataset_id in self._memory_datasets:
            return self._memory_datasets[dataset_id]

        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT dataset_id, project_id, dataset_name, version, manifest_json, records_json, test_inputs_json, created_at
                    FROM user_datasets WHERE dataset_id = ?
                """, (dataset_id,))
                row = cursor.fetchone()
                if row:
                    manifest = DatasetIngestionManifest.model_validate_json(row[4])
                    records = json.loads(row[5])
                    raw_inputs = json.loads(row[6])
                    test_inputs = [CertificationTestInput.model_validate(inp) for inp in raw_inputs]

                    record = UserDatasetRecord(
                        dataset_id=row[0],
                        project_id=row[1],
                        dataset_name=row[2],
                        version=row[3],
                        manifest=manifest,
                        canonical_records=records,
                        created_at=row[7],
                    )
                    self._memory_datasets[dataset_id] = record
                    self._memory_inputs[dataset_id] = test_inputs
                    return record
        except Exception as exc:
            logger.debug(f"SQLite get_dataset notice: {exc}")

        return None

    def get_manifest(self, dataset_id: str) -> Optional[DatasetIngestionManifest]:
        """Retrieves the manifest for a dataset."""
        record = self.get_dataset(dataset_id)
        if record:
            return record.manifest
        return None

    def get_test_inputs(self, dataset_id: str) -> list[CertificationTestInput]:
        """Retrieves the list of canonical CertificationTestInputs for a dataset."""
        if dataset_id in self._memory_inputs:
            return self._memory_inputs[dataset_id]

        record = self.get_dataset(dataset_id)
        if record and dataset_id in self._memory_inputs:
            return self._memory_inputs[dataset_id]
        return []

    def list_datasets(
        self,
        project_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[DatasetIngestionManifest]:
        """Lists DatasetIngestionManifests, optionally filtered by project_id."""
        manifests: list[DatasetIngestionManifest] = []
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                query = "SELECT manifest_json FROM user_datasets WHERE 1=1"
                params: list[object] = []
                if project_id:
                    query += " AND project_id = ?"
                    params.append(project_id)
                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)

                cursor.execute(query, params)
                for row in cursor.fetchall():
                    manifests.append(DatasetIngestionManifest.model_validate_json(row[0]))
        except Exception as exc:
            logger.debug(f"SQLite list_datasets notice: {exc}")

        if not manifests and self._memory_datasets:
            filtered = [
                rec.manifest for rec in self._memory_datasets.values()
                if not project_id or rec.project_id == project_id
            ]
            return list(reversed(filtered[-limit:]))

        return manifests

    def delete_dataset(self, dataset_id: str) -> bool:
        """Deletes a custom dataset record and manifest from storage."""
        record = self.get_dataset(dataset_id)
        project_id = record.project_id if record else "UNKNOWN"

        deleted = False
        if dataset_id in self._memory_datasets:
            del self._memory_datasets[dataset_id]
            deleted = True
        if dataset_id in self._memory_inputs:
            del self._memory_inputs[dataset_id]
            deleted = True

        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM user_datasets WHERE dataset_id = ?", (dataset_id,))
                if cursor.rowcount > 0:
                    deleted = True
                conn.commit()
        except Exception as exc:
            logger.warning(f"Error deleting dataset {dataset_id} from SQLite: {exc}")

        if deleted:
            audit_logger.log(
                project_id=project_id,
                action=AuditAction.DATASET_DELETE,
                status="SUCCESS",
                dataset_id=dataset_id,
                details={"deleted": True},
            )

        return deleted

    def clear(self):
        """Clears memory and SQLite user_datasets table (for test isolation)."""
        self._memory_datasets.clear()
        self._memory_inputs.clear()
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("DELETE FROM user_datasets")
                conn.commit()
        except Exception:
            pass


# Module-level default instance
user_dataset_registry = UserDatasetRegistry()
