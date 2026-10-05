"""SQLite persistence used by the local, no-credentials BEACON prototype.

Atlas remains available for the original cloud architecture, but a project demo
must not depend on external credentials just to retain certification history.
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional

from common.config import settings
from common.models import CertificationRun, DriftSample


class LocalStore:
    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path else Path(settings.database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS certification_runs (
                    run_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    equivalence_score REAL NOT NULL,
                    total_checked INTEGER NOT NULL,
                    total_violated INTEGER NOT NULL,
                    project_id TEXT,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS drift_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_timestamp TEXT NOT NULL,
                    equivalence_score REAL NOT NULL,
                    baseline_score REAL NOT NULL,
                    delta_pct REAL NOT NULL,
                    alert INTEGER NOT NULL,
                    benchmark_id TEXT,
                    payload TEXT NOT NULL
                );
                """
            )
            # Add project_id column if table already existed without it
            try:
                connection.execute("ALTER TABLE certification_runs ADD COLUMN project_id TEXT")
            except Exception:
                pass
            # Add benchmark_id column if table already existed without it
            try:
                connection.execute("ALTER TABLE drift_samples ADD COLUMN benchmark_id TEXT")
            except Exception:
                pass

    def save_run(self, run: CertificationRun, project_id: str | None = None) -> None:
        payload = run.model_dump(mode="json")
        resolved_proj = project_id or payload.get("project_id") or "default_project"
        payload["project_id"] = resolved_proj
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO certification_runs
                (run_id, timestamp, equivalence_score, total_checked, total_violated, project_id, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (run.run_id, run.timestamp, run.equivalence_score, run.total_checked,
                 run.total_violated, resolved_proj, json.dumps(payload)),
            )

    def list_runs(self, limit: int = 20, project_id: str | None = None) -> list[dict]:
        with self._connect() as connection:
            if project_id:
                rows = connection.execute(
                    "SELECT payload FROM certification_runs WHERE project_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT payload FROM certification_runs ORDER BY timestamp DESC LIMIT ?", (limit,)
                ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def get_run(self, run_id: str, project_id: str | None = None) -> dict | None:
        with self._connect() as connection:
            if project_id:
                row = connection.execute(
                    "SELECT payload FROM certification_runs WHERE run_id = ? AND project_id = ?",
                    (run_id, project_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT payload FROM certification_runs WHERE run_id = ?", (run_id,)
                ).fetchone()
        return json.loads(row["payload"]) if row else None

    def save_drift_sample(self, sample: DriftSample) -> None:
        payload = sample.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO drift_samples
                (run_timestamp, equivalence_score, baseline_score, delta_pct, alert, benchmark_id, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (sample.run_timestamp, sample.equivalence_score, sample.baseline_score,
                 sample.delta_pct, int(sample.alert), sample.benchmark_id, json.dumps(payload)),
            )

    def list_drift_samples(self, benchmark_id: str | None = None, limit: int = 100) -> list[dict]:
        with self._connect() as connection:
            if benchmark_id:
                rows = connection.execute(
                    "SELECT payload FROM drift_samples WHERE benchmark_id = ? ORDER BY id DESC LIMIT ?",
                    (benchmark_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT payload FROM drift_samples ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [json.loads(row["payload"]) for row in rows]


local_store = LocalStore()
