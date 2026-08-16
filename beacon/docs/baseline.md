# BEACON Repository Baseline

**Date:** 2026-08-16  
**Environment:** Windows (PowerShell)  

---

## 1. System & Environment Specifications

- **Python Version:** `Python 3.11.9` (64-bit) (compatible environment for `numpy==1.26.4` and full dependency set)
- **Node.js Version:** `v24.14.1`
- **Virtual Environment:** Active at `.venv` (`c:\Users\Navaneeth Motamarry\Beacon\Beacon\beacon\.venv`)

---

## 2. Component & Service Status

### Backend Service (FastAPI)
- **Status:** Working / Running
- **Server:** Uvicorn on `http://127.0.0.1:8000`
- **Health Check:** `http://127.0.0.1:8000/` $\rightarrow$ `{"name":"BEACON API","status":"ok","storage":"local SQLite","docs":"/docs","health":"/health"}`
- **Swagger Documentation:** Available and functional at `http://127.0.0.1:8000/docs`

### Frontend Application (React + Vite)
- **Status:** Working / Running
- **Server:** Vite Dev Server on `http://localhost:5173`
- **Title:** `BEACON Dashboard`

---

## 3. Verification & Demo Results

### Automated Tests (`pytest -v`)
- **Total Tests:** 10
- **Passed:** 10
- **Failed:** 0
- **Execution Time:** ~1.70 seconds
- **Test Modules Verified:**
  - `tests/test_api.py` (1 passed)
  - `tests/test_local_demo_api.py` (3 passed)
  - `tests/test_scoring.py` (6 passed)

### Pipeline Demo Runner (`scripts/run_demo_pipeline.py`)
- **Status:** Runnable & Fully Passing
- **Extracted Invariants:** 3 graduated invariants (`local-c7180ce5`, `local-1b27dc7b`, `local-9aae83ec`)
- **Equivalence Score (Buggy Modernization):** `66.7%` (11 violations detected over 52 checks)
- **Persistence:** Certification run saved to SQLite at `data/beacon.sqlite3`

---

## 4. Acceptance Criteria Checklist

- [x] Python environment works
- [x] `requirements.txt` installs cleanly into `.venv`
- [x] FastAPI starts on port 8000
- [x] `/docs` Swagger UI works
- [x] React/Vite dev server starts on port 5173
- [x] Frontend loads successfully
- [x] `pytest -v` passes (10 passing tests recorded)
- [x] Repository baseline documented in `docs/baseline.md`
