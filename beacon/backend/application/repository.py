"""BEACON V2 — Application Repository.

Provides persistent storage and querying of ApplicationSpec instances in SQLite
with thread-safety and in-memory caching/isolation.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Optional, Union

from common.config import settings
from .models import ApplicationSpec

logger = logging.getLogger("beacon.application")


class ApplicationRepository:
    """Manages persistent storage and retrieval of ApplicationSpec models."""

    def __init__(self, db_path: Optional[Union[Path, str]] = None):
        self._db_path = Path(db_path) if db_path else Path(settings.database_path)
        self._memory_apps: dict[str, ApplicationSpec] = {}
        self._init_db()

    def _init_db(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS applications (
                        application_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT,
                        domain TEXT,
                        version TEXT NOT NULL DEFAULT '1.0.0',
                        spec_json TEXT NOT NULL,
                        spec_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_apps_domain ON applications(domain);")
                conn.commit()
        except Exception as exc:
            logger.warning(f"Could not initialize applications SQLite table: {exc}")

    def save_application(self, spec: ApplicationSpec) -> ApplicationSpec:
        """Saves or updates an ApplicationSpec."""
        spec_hash = spec.compute_spec_hash()
        spec.spec_hash = spec_hash
        self._memory_apps[spec.application_id] = spec

        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            spec_json = spec.model_dump_json()
        except Exception:
            spec_json = json.dumps(spec.model_dump(mode="python"), default=str)

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    INSERT INTO applications (
                        application_id, name, description, domain, version, spec_json, spec_hash, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(application_id) DO UPDATE SET
                        name=excluded.name,
                        description=excluded.description,
                        domain=excluded.domain,
                        version=excluded.version,
                        spec_json=excluded.spec_json,
                        spec_hash=excluded.spec_hash,
                        updated_at=excluded.updated_at
                """, (
                    spec.application_id,
                    spec.name,
                    spec.description,
                    spec.domain,
                    spec.version,
                    spec_json,
                    spec_hash,
                    now_iso,
                    now_iso,
                ))
                conn.commit()
        except Exception as exc:
            logger.warning(f"SQLite save_application failed (retained in-memory): {exc}")

        return spec

    def get_application(self, application_id: str) -> Optional[ApplicationSpec]:
        """Retrieves an ApplicationSpec by ID."""
        if application_id in self._memory_apps:
            return self._memory_apps[application_id]

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT spec_json FROM applications WHERE application_id = ?", (application_id,))
                row = cursor.fetchone()
                if row:
                    data = json.loads(row[0])
                    spec = ApplicationSpec(**data)
                    self._memory_apps[application_id] = spec
                    return spec
        except Exception as exc:
            logger.warning(f"SQLite get_application error: {exc}")

        return None

    def list_applications(self, domain: Optional[str] = None) -> list[ApplicationSpec]:
        """Lists all registered applications, optionally filtered by domain metadata."""
        apps: list[ApplicationSpec] = []
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                if domain:
                    cursor.execute("SELECT spec_json FROM applications WHERE domain = ? ORDER BY name ASC", (domain,))
                else:
                    cursor.execute("SELECT spec_json FROM applications ORDER BY name ASC")
                rows = cursor.fetchall()
                for row in rows:
                    data = json.loads(row[0])
                    spec = ApplicationSpec(**data)
                    apps.append(spec)
                    self._memory_apps[spec.application_id] = spec
        except Exception as exc:
            logger.warning(f"SQLite list_applications error: {exc}")
            apps = list(self._memory_apps.values())
            if domain:
                apps = [a for a in apps if a.domain == domain]

        # Combine with any in-memory only items
        existing_ids = {a.application_id for a in apps}
        for mem_app in self._memory_apps.values():
            if mem_app.application_id not in existing_ids:
                if domain is None or mem_app.domain == domain:
                    apps.append(mem_app)

        return apps

    def delete_application(self, application_id: str) -> bool:
        """Deletes an ApplicationSpec by ID."""
        self._memory_apps.pop(application_id, None)
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("DELETE FROM applications WHERE application_id = ?", (application_id,))
                conn.commit()
            return True
        except Exception as exc:
            logger.warning(f"SQLite delete_application error: {exc}")
            return False

    def clear(self) -> None:
        """Clears all applications (for test isolation)."""
        self._memory_apps.clear()
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("DELETE FROM applications")
                conn.commit()
        except Exception:
            pass


application_repository = ApplicationRepository()
