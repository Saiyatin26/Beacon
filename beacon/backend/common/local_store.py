"""SQLite persistence used by the local, no-credentials BEACON prototype.

Atlas remains available for the original cloud architecture, but a project demo
must not depend on external credentials just to retain certification history.
"""

import json
import sqlite3
from pathlib import Path

from common.models import CertificationRun, DriftSample


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "beacon.sqlite3"


class LocalStore:
    def __init__(self, path: str | Path = DEFAULT_DB_PATH):
        self.path = Path(path)
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
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS drift_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_timestamp TEXT NOT NULL,
                    equivalence_score REAL NOT NULL,
                    baseline_score REAL NOT NULL,
                    delta_pct REAL NOT NULL,
                    alert INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )

    def save_run(self, run: CertificationRun) -> None:
        payload = run.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO certification_runs
                (run_id, timestamp, equivalence_score, total_checked, total_violated, payload)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (run.run_id, run.timestamp, run.equivalence_score, run.total_checked,
                 run.total_violated, json.dumps(payload)),
            )

    def list_runs(self, limit: int = 20) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM certification_runs ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def get_run(self, run_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM certification_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def save_drift_sample(self, sample: DriftSample) -> None:
        payload = sample.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO drift_samples
                (run_timestamp, equivalence_score, baseline_score, delta_pct, alert, payload)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (sample.run_timestamp, sample.equivalence_score, sample.baseline_score,
                 sample.delta_pct, int(sample.alert), json.dumps(payload)),
            )

    def list_drift_samples(self, limit: int = 100) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM drift_samples ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]


local_store = LocalStore()
