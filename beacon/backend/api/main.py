"""FastAPI app wiring all six stages together for the dashboard (Stage 6) to
call. Run with: uvicorn api.main:app --reload --port 8000

Endpoints are intentionally thin — all real logic lives in each stage's own
module so this file stays a coordination layer, not a place novelty leaks
into framework-specific code.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))  # backend/ on path
sys.path.append(str(Path(__file__).resolve().parents[2] / "legacy_sample"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from common.db import certification_runs_col, drift_samples_col

app = FastAPI(title="BEACON API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/runs")
def list_runs(limit: int = 20):
    """Certification run history for the dashboard's score-over-time chart."""
    runs = list(
        certification_runs_col().find({}, {"_id": 0}).sort("timestamp", -1).limit(limit)
    )
    return {"runs": runs}


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    return certification_runs_col().find_one({"run_id": run_id}, {"_id": 0})


@app.get("/drift")
def list_drift_samples(limit: int = 100):
    samples = list(
        drift_samples_col().find({}, {"_id": 0}).sort("run_timestamp", -1).limit(limit)
    )
    return {"samples": samples}


# NOTE: /mine and /certify are intentionally left as long-running scripts
# (scripts/run_demo_pipeline.py) rather than synchronous API endpoints, since
# a full mining+certification pass involves multiple LLM calls and is meant to
# run as a background/offline job in a real deployment, not block a request.
