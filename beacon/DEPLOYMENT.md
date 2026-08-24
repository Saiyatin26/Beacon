# BEACON Production Deployment & Operational Guide

## Overview

BEACON is an enterprise-grade legacy-to-modernized code certification and behavioral equivalence system. This guide provides deployment topology, persistence architecture, configuration hardening, lifecycle management, health monitoring, and operational instructions for production environments.

---

## 1. Persistence & Database Architecture

BEACON implements a **Hybrid Persistence Architecture**:

```
                       BEACON DATA PERSISTENCE
                                  │
                 ┌────────────────┴────────────────┐
                 ▼                                 ▼
           SQLite Database                   MongoDB Atlas
          (Local / State)                  (Optional Domain)
                 │                                 │
                 ▼                                 ▼
        • Operational State               • Vector Invariant Search
        • Project Idempotency             • Invariant Deduplication
        • Job Lifecycle & Recovery        • Cross-service OracleSets
        • Custom Dataset Registries       • High-Throughput Drift
        • Local Certification Records     • Long-Term Historical Runs
```

### Persistence Layer Responsibilities

| Storage Layer | Deployment Mode | Data Stored | Failure / Offline Behavior |
| :--- | :--- | :--- | :--- |
| **SQLite** (`beacon.sqlite3`) | **Mandatory** (Core) | Operational jobs, idempotency keys, project namespaces, local dataset registry, local artifacts | If SQLite is inaccessible, `/health/ready` returns `503 Service Unavailable` (`database_unavailable`). All stateful mutations fail closed. |
| **MongoDB Atlas** (`MONGODB_ATLAS_URI`) | **Optional** (Hybrid Domain) | Invariants with Voyage AI vector embeddings, candidate deduplication, cloud OracleSets, drift telemetry | If not configured or offline, BEACON automatically degrades gracefully to standalone mode using AST/lexical deduplication and local file storage. |

---

## 2. Environment Configuration

Copy the example environment configuration and supply production secrets:

```bash
cp .env.example .env
```

### Essential Production Environment Variables

| Variable | Description | Production Requirement | Example Value |
| :--- | :--- | :--- | :--- |
| `BEACON_ENV` | Environment mode | Must be set to `production` or `staging` | `production` |
| `JWT_SECRET_KEY` | HMAC SHA-256 secret for signing auth tokens | Must be $\ge 32$ cryptographically random chars | `CHANGE_ME_TO_A_32_CHAR_RANDOM_SECRET` |
| `JWT_ALGORITHM` | Algorithm for JWT tokens | Defaults to `HS256` | `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifespan | Positive integer (e.g. 60) | `60` |
| `CORS_ORIGINS` | Permitted client origin URLs | Comma-separated list of exact domains (No `*`) | `https://beacon.example.com` |
| `LOG_LEVEL` | Minimum log verbosity | `INFO` or `WARNING` | `INFO` |
| `OPERATION_TIMEOUT_SECONDS` | Maximum timeout for certification runs | Positive float (e.g. 60.0) | `60.0` |
| `MAX_RETRY_ATTEMPTS` | Maximum transient retry attempts | Integer between 1 and 5 | `3` |
| `MAX_DATASET_SIZE_BYTES` | Maximum upload size per dataset | Byte limit (e.g. 10MB) | `10485760` |
| `BEACON_DATABASE_PATH` | Path to SQLite database file | Persistent directory path | `/var/lib/beacon/beacon.sqlite3` |
| `MONGODB_ATLAS_URI` | Optional MongoDB connection string | Valid URI starting with `mongodb://` or `mongodb+srv://` | `mongodb+srv://user:pass@cluster.mongodb.net/` |

> [!CAUTION]
> In `BEACON_ENV=production`, startup will immediately **fail closed** if `JWT_SECRET_KEY` is missing, shorter than 32 characters, or matches known insecure default placeholders.

---

## 3. API Endpoint Classification & Access Matrix

All BEACON endpoints follow strict security classification:

| Endpoint | Method | Classification | Access Requirement | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `/health/live`, `/live` | `GET` | **PUBLIC** | None | Process liveness and uptime check |
| `/health/ready`, `/ready` | `GET` | **PUBLIC / CONTROLLED** | None | Read-only database & registry readiness check |
| `/health` | `GET` | **PUBLIC** | None | Minimal safe operational status (`status`, `version`) |
| `/api/v1/operations/version` | `GET` | **PUBLIC** | None | Safe service and version metadata |
| `/api/v1/benchmarks`, `{id}` | `GET` | **PUBLIC** | None | List frozen standard benchmarks and specifications |
| `/api/v1/benchmarks/{id}/manifest` | `GET` | **PUBLIC** | None | Public benchmark manifest metadata |
| `/api/auth/login` | `POST` | **PUBLIC** | Valid credentials | Issue JWT access token |
| `/api/llm/status` | `GET` | **AUTHENTICATED** | Bearer Token | Provider availability status (no keys) |
| `/api/oracles`, `{id}` | `GET` | **AUTHENTICATED** | Bearer Token | Registered language-independent oracle catalog |
| `/api/oracle-sets`, `{id}` | `GET` | **AUTHENTICATED** | Bearer Token | Frozen OracleSets definitions |
| `/api/v1/certification/run` | `POST` | **PROJECT-SCOPED** | Bearer Token (`CERTIFY`) | Execute certification job with idempotency |
| `/api/v1/certification/jobs` | `GET` | **PROJECT-SCOPED** | Bearer Token (`VIEW`) | Inspect certification jobs |
| `/api/v1/certification/{id}/*` | `GET/POST` | **PROJECT-SCOPED** | Bearer Token (`VIEW`) | Certificate reports, cases, oracles, counterexamples, verify |
| `/api/v1/custom/datasets/upload` | `POST` | **PROJECT-SCOPED** | Bearer Token (`CERTIFY`) | Upload and validate user dataset |
| `/api/v1/custom/datasets/preview` | `POST` | **PROJECT-SCOPED** | Bearer Token (`VIEW`) | Ingestion preview and schema validation |
| `/api/v1/custom/datasets` | `GET` | **PROJECT-SCOPED** | Bearer Token (`VIEW`) | List project custom datasets |
| `/api/v1/benchmarks/{id}/validate` | `POST/GET` | **PROJECT-SCOPED** | Bearer Token (`VIEW`) | Benchmark pre-flight validation |
| `/api/oracles/compile` | `POST` | **PROJECT-SCOPED** | Bearer Token (`CERTIFY`) | Compile and register invariant oracle |
| `/api/v1/drift/evaluate` | `POST` | **PROJECT-SCOPED** | Bearer Token (`CERTIFY`) | Run drift observation analysis |
| `/runs`, `/runs/{id}` | `GET` | **PROJECT-SCOPED** | Bearer Token (`VIEW`) | Local/legacy certification runs |
| `/drift` | `GET` | **PROJECT-SCOPED** | Bearer Token (`VIEW`) | Streaming drift samples |
| `/demo/run`, `/drift/demo` | `POST` | **DEVELOPMENT-ONLY** | Bearer Token (`CERTIFY`) | Disabled in production/staging (`403 Forbidden`) |
| `/health/details` | `GET` | **SYSTEM-ADMIN** | Bearer Token (`SYSTEM_ADMIN`) | Granular diagnostic inspection without secret leaks |
| `/api/v1/operations/system-metrics` | `GET` | **SYSTEM-ADMIN** | Bearer Token (`SYSTEM_ADMIN`) | Real-time system telemetry and process stats |

---

## 4. Installation & Build

### Step 1: Backend Setup
```bash
# Create isolated virtual environment
python3.11 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 2: Frontend Production Build
```bash
cd frontend
npm ci
npm run build
cd ..
```
The compiled static assets are generated in `frontend/dist/`.

---

## 5. Starting the Application

### Running with Uvicorn (Standard Production)
```bash
uvicorn backend.api.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 \
  --lifespan on \
  --proxy-headers \
  --forwarded-allow-ips "*"
```

### Running with Gunicorn + Uvicorn Workers (High Concurrency)
```bash
gunicorn backend.api.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile -
```

---

## 6. Health Probes & Readiness Topologies

- **Liveness Probe**: `GET /health/live` (or `/live`) → Returns HTTP `200 OK` if the Python runtime is responsive.
- **Readiness Probe**: `GET /health/ready` (or `/ready`) → Returns HTTP `200 OK` if SQLite database and registries are online; returns `503 Service Unavailable` if database is down. Strictly read-only (`SELECT 1`).
- **Detailed Health**: `GET /health/details` → Protected by `SYSTEM_ADMIN` role; provides detailed telemetry without exposing credentials or internal paths.
