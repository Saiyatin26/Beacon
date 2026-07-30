# BEACON — Behavioral Equivalence Certification Framework

Database Management Systems Project — Team: Sai, Yatin, Navaneeth

BEACON is a verification layer that certifies whether AI-modernized code preserves the
behavior of the legacy system it replaces. It does not translate code — it mines implicit
business-rule invariants from a legacy system, compiles them into language-agnostic
executable oracles, certifies modernized code against those oracles with a quantified
score, and keeps monitoring production traffic for behavioral drift after deployment.

See `/mnt/user-data/outputs/BEACON-Architecture-Report.pdf` (or the project doc) for the
full architecture writeup. This repo mirrors that document's six stages 1:1.

## Repo layout

```
beacon/
├── legacy_sample/        Stage 1 — sample legacy app + synthetic trace generator
├── backend/
│   ├── common/            shared config, DB client, pydantic models
│   ├── ingestion/          Stage 1 — parsing + trace ingestion glue
│   ├── mining/              Stage 2 — invariant mining sub-pipeline (novel)
│   ├── oracle/               Stage 3 — oracle DSL + synthesis + interpreter (novel)
│   ├── certification/         Stage 4 — equivalence scoring engine (novel)
│   ├── drift/                  Stage 5 — production drift monitor (novel)
│   └── api/                     FastAPI app wiring all stages together
├── frontend/              Stage 6 — React + Recharts dashboard
├── openspec/              OpenSpec-managed change proposals (one per mined invariant)
├── scripts/               End-to-end demo runner
└── tests/                  pytest unit tests for the scoring/validation logic
```

## Local prototype setup (recommended)

The project now runs end to end without API keys. It uses SQLite at
`data/beacon.sqlite3` for certification history, while retaining the original
Atlas, Claude, and Voyage integrations as optional cloud mode.

From the repository root in Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# terminal 1: API
cd backend
..\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000

# terminal 2: dashboard
cd frontend
npm.cmd install
npm.cmd run dev
```

Open http://localhost:5173 and choose a sample certification action. The API
documentation is at http://localhost:8000/docs. Run checks and the command
line workflow with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_demo_pipeline.py
```

## Optional cloud mode

Copy `.env.example` to `.env`, configure `ANTHROPIC_API_KEY`,
`MONGODB_ATLAS_URI`, and `VOYAGE_API_KEY`, then install the vector embedding
client and enable LLM mining:

```powershell
.\.venv\Scripts\python.exe -m pip install voyageai
$env:MINE_WITH_LLM = "1"
```

Atlas Vector Search still requires an `invariant_vector_index` on the
`invariants.embedding` field, as described in `backend/mining/dedup.py`.

## Original setup reference

```bash
# backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env   # fill in ANTHROPIC_API_KEY, MONGODB_ATLAS_URI, VOYAGE_API_KEY
uvicorn api.main:app --reload --port 8000

# frontend
cd frontend
npm install
npm run dev

# openspec (spec provenance tracking)
npx openspec@latest init
```

## Running the end-to-end demo

```bash
python3 scripts/run_demo_pipeline.py
```

This runs the full pipeline against the sample legacy loan-approval app and its
intentionally-buggy "modernized" counterpart in `legacy_sample/`, prints the mined
invariants, and produces a certification report matching the format in the
architecture document (Section 7.4).

## What's real vs mocked (see architecture doc Section 5 for full table)

Real: parsing, LLM invariant reasoning, evidence/validation/confidence scoring, Atlas
storage + vector dedup, OpenSpec provenance, oracle DSL + interpreter, certification
scoring, dashboard.

Mocked (student-project scope): real mainframe trace capture (synthetic script
instead), Docker-sandboxed multi-language execution (in-process stub instead), live
production traffic (replay script instead), Slack/PagerDuty alerting (console log
instead).
