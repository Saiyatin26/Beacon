import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient

from api.main import app
from common.local_store import LocalStore


def test_runs_endpoint_returns_empty_for_new_local_store(monkeypatch, tmp_path):
    monkeypatch.setattr("api.main.local_store", LocalStore(tmp_path / "beacon.sqlite3"))

    with TestClient(app) as client:
        response = client.get("/runs")

    assert response.status_code == 200
    assert response.json() == {"runs": []}
