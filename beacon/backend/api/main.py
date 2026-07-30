"""FastAPI application for the local-first BEACON prototype."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[2] / "legacy_sample"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from certification.runner import certify
from certification.scorer import equivalence_score
from common.config import settings
from common.local_store import local_store
from common.models import DriftSample
from ingestion.legacy_parser import load_source
from ingestion.trace_loader import load_traces
from mining.offline_miner import mine_python_decision_rules
from oracle.interpreter import run_oracle
from oracle.synthesizer import synthesize_oracle

import legacy_loan_approval
import modern_loan_approval
from generate_traces import generate_traces


ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT / "legacy_sample"
FIELD_BOUNDS = {
    "credit_score": (400, 820),
    "debt_ratio": (0.0, 0.9),
    "annual_income": (10_000, 150_000),
}

app = FastAPI(title="BEACON API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class DemoRunRequest(BaseModel):
    implementation: Literal["buggy", "equivalent"] = "buggy"


class DriftRequest(BaseModel):
    baseline_run_id: str
    implementation: Literal["buggy", "equivalent"] = "buggy"


def _sample_traces():
    trace_path = SAMPLE_DIR / "trace_log.json"
    if not trace_path.exists():
        import json
        trace_path.write_text(json.dumps(generate_traces(), indent=2))
    return load_traces(trace_path)


def _sample_oracles():
    invariants = mine_python_decision_rules(
        load_source(SAMPLE_DIR / "legacy_loan_approval.py"),
        _sample_traces(),
        legacy_loan_approval.evaluate_loan,
        FIELD_BOUNDS,
    )
    return [synthesize_oracle(invariant) for invariant in invariants if invariant.graduated], invariants


def _implementation(name: str):
    return modern_loan_approval.evaluate_loan if name == "buggy" else legacy_loan_approval.evaluate_loan


@app.get("/")
def root():
    return {
        "name": "BEACON API",
        "status": "ok",
        "storage": "local SQLite",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    return {"status": "ok", "storage": "local SQLite"}


@app.get("/runs")
def list_runs(limit: int = 20):
    return {"runs": local_store.list_runs(max(1, min(limit, 100)))}


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    run = local_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Certification run not found")
    return run


@app.post("/demo/run")
def run_demo(request: DemoRunRequest):
    """Mine local rules, certify a sample implementation, and persist the report."""
    oracles, invariants = _sample_oracles()
    if not oracles:
        raise HTTPException(status_code=500, detail="No validated sample invariants were produced")
    run = certify(
        oracles=oracles,
        modern_fn=_implementation(request.implementation),
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        domain_of={oracle.invariant_id: "Loan approval" for oracle in oracles},
    )
    local_store.save_run(run)
    return {
        "run": run.model_dump(mode="json"),
        "implementation": request.implementation,
        "invariants": [invariant.model_dump(mode="json") for invariant in invariants],
    }


@app.get("/demo/invariants")
def list_demo_invariants():
    _, invariants = _sample_oracles()
    return {"invariants": [invariant.model_dump(mode="json") for invariant in invariants]}


@app.post("/drift/demo")
def check_demo_drift(request: DriftRequest):
    baseline = local_store.get_run(request.baseline_run_id)
    if baseline is None:
        raise HTTPException(status_code=404, detail="Baseline certification run not found")
    oracles, _ = _sample_oracles()
    results = [run_oracle(oracle, _implementation(request.implementation), FIELD_BOUNDS) for oracle in oracles]
    score = equivalence_score(results, {oracle.invariant_id: oracle for oracle in oracles})
    delta_pct = round((baseline["equivalence_score"] - score) * 100, 2)
    sample = DriftSample(
        run_timestamp=datetime.now(timezone.utc).isoformat(),
        equivalence_score=score,
        baseline_score=baseline["equivalence_score"],
        delta_pct=delta_pct,
        alert=delta_pct > settings.drift_alert_delta_pct,
    )
    local_store.save_drift_sample(sample)
    return sample.model_dump(mode="json")


@app.get("/drift")
def list_drift_samples(limit: int = 100):
    return {"samples": local_store.list_drift_samples(max(1, min(limit, 500)))}
