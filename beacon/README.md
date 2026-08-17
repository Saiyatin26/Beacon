# BEACON — Behavioral Equivalence Certification Framework

Database Management Systems Project — Team: Sai, Yatin, Navaneeth

BEACON is a verification layer that certifies whether AI-modernized code preserves the
behavior of the legacy system it replaces. It does not translate code — it mines implicit
business-rule invariants from a legacy system, compiles them into language-agnostic
executable oracles, certifies modernized code against those oracles with a quantified
score, and keeps monitoring production traffic for behavioral drift after deployment.

## Repo Layout

```
beacon/
├── legacy_sample/         Sample legacy app + synthetic trace generator
├── backend/
│   ├── common/            Shared config, SQLite/Atlas client, Pydantic models
│   ├── ingestion/         Static AST parsing + dynamic runtime tracer
│   ├── evidence/          UnifiedEvidencePackage builder & correlated facts
│   ├── mining/            Adversarial invariant mining & validation sub-pipeline
│   │   ├── base_generator.py      CandidateGenerator interface
│   │   ├── offline_miner.py       Deterministic local invariant miner
│   │   ├── candidate_generator.py LLM-assisted candidate miner
│   │   ├── evidence_selector.py   Relevance scoring & top-K selection
│   │   ├── prompt_builder.py      Structured LLM prompt with guardrails
│   │   ├── normalizer.py          Commutative AST boolean canonicalization
│   │   ├── grounding_checker.py   Semantic evidence grounding & anti-hallucination
│   │   ├── adversarial.py         Multi-strategy boundary/diverse validation & shrinking
│   │   ├── validator.py           Invariant validation routing
│   │   ├── confidence_scorer.py   Weighted confidence formula & 0.8 gate
│   │   └── pipeline.py            Canonical mining & validation orchestrator
│   ├── oracle/            Stage 3 — oracle DSL + synthesis + interpreter
│   ├── certification/     Stage 4 — equivalence scoring engine
│   ├── drift/             Stage 5 — production drift monitor
│   └── api/               FastAPI app wiring all stages together
├── frontend/              React + Recharts dashboard
├── docs/                  Baseline documentation & architectural reports
├── scripts/               End-to-end demo runner
└── tests/                 Comprehensive pytest test suite
```

## Local Prototype Setup (Recommended)

The project runs end to end locally without mandatory cloud dependencies. It uses SQLite at
`data/beacon.sqlite3` for certification history, while retaining MongoDB Atlas, Claude, and
Voyage integrations as optional cloud modes.

From the repository root in Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# Terminal 1: API
cd backend
..\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000

# Terminal 2: Dashboard
cd frontend
npm.cmd install
npm.cmd run dev
```

Open http://localhost:5173 to access the dashboard. The API documentation is available at
http://localhost:8000/docs. Run checks and the deterministic pipeline with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_demo_pipeline.py
```

## Optional Cloud Mode

Copy `.env.example` to `.env` and configure `ANTHROPIC_API_KEY`, `MONGODB_ATLAS_URI`, and
`VOYAGE_API_KEY`. Enable LLM mining with:

```powershell
.\.venv\Scripts\python.exe -m pip install voyageai
$env:MINE_WITH_LLM = "1"
```

## Running the End-to-End Demo

```powershell
python scripts/run_demo_pipeline.py
```

This runs the full pipeline against the sample legacy loan-approval app and its
intentionally-buggy modernized counterpart in `legacy_sample/`, prints the mined
invariants, and produces a certification report.
