import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient

from api.main import app
from common.local_store import LocalStore


def test_local_demo_certifies_buggy_sample_and_persists_result(monkeypatch, tmp_path):
    monkeypatch.setattr("api.main.local_store", LocalStore(tmp_path / "beacon.sqlite3"))

    with TestClient(app) as client:
        response = client.post("/demo/run", json={"implementation": "buggy"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["run"]["equivalence_score"] < 1.0
        assert payload["run"]["total_violated"] > 0

        runs = client.get("/runs").json()["runs"]
        assert len(runs) == 1
        assert runs[0]["run_id"] == payload["run"]["run_id"]


def test_local_demo_certifies_equivalent_sample(monkeypatch, tmp_path):
    monkeypatch.setattr("api.main.local_store", LocalStore(tmp_path / "beacon.sqlite3"))

    with TestClient(app) as client:
        response = client.post("/demo/run", json={"implementation": "equivalent"})

    assert response.status_code == 200
    assert response.json()["run"]["equivalence_score"] == 1.0


def test_drift_alert_compares_buggy_deployment_to_equivalent_baseline(monkeypatch, tmp_path):
    monkeypatch.setattr("api.main.local_store", LocalStore(tmp_path / "beacon.sqlite3"))

    with TestClient(app) as client:
        baseline = client.post("/demo/run", json={"implementation": "equivalent"}).json()["run"]
        response = client.post("/drift/demo", json={
            "baseline_run_id": baseline["run_id"], "implementation": "buggy",
        })

    assert response.status_code == 200
    assert response.json()["alert"] is True
    assert response.json()["delta_pct"] > 0
