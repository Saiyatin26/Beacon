# BEACON Production Deployment & Operational Guide

## Overview

BEACON is a production-grade legacy-to-modernized code certification and behavioral equivalence system. This guide provides deployment topology, environment hardening, lifecycle management, health monitoring, and operational instructions for production environments.

---

## 1. Prerequisites

- **Python**: Python 3.11+ (recommended 3.11.x)
- **Node.js**: Node 18+ / 20+ (for frontend dashboard compilation)
- **Database**: Local SQLite 3.35+ (with WAL mode enabled) or enterprise volume storage
- **Operating System**: Linux (Ubuntu 22.04 LTS / Debian 12 / RHEL 9), macOS, or Windows Server

---

## 2. Environment Configuration

Copy the example environment configuration and supply production secrets:

```bash
cp .env.example .env
```

### Essential Production Environment Variables

| Variable | Description | Production Requirement | Example Value |
| :--- | :--- | :--- | :--- |
| `BEACON_ENV` | Environment mode | Must be set to `production` | `production` |
| `JWT_SECRET_KEY` | HMAC SHA-256 secret for signing auth tokens | Must be $\ge 32$ cryptographically random chars | `CHANGE_ME_TO_A_32_CHAR_RANDOM_SECRET` |
| `JWT_ALGORITHM` | Algorithm for JWT tokens | Defaults to `HS256` | `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifespan | Positive integer (e.g. 60) | `60` |
| `CORS_ORIGINS` | Permitted client origin URLs | Comma-separated list of exact domains (No `*`) | `https://beacon.example.com` |
| `LOG_LEVEL` | Minimum log verbosity | `INFO` or `WARNING` | `INFO` |
| `OPERATION_TIMEOUT_SECONDS` | Maximum timeout for certification runs | Positive float (e.g. 60.0) | `60.0` |
| `MAX_RETRY_ATTEMPTS` | Maximum transient retry attempts | Integer between 1 and 5 | `3` |
| `MAX_DATASET_SIZE_BYTES` | Maximum upload size per dataset | Byte limit (e.g. 10MB) | `10485760` |
| `BEACON_DATABASE_PATH` | Path to SQLite database file | Persistent directory path | `/var/lib/beacon/beacon.sqlite3` |

> [!CAUTION]
> In `BEACON_ENV=production`, startup will immediately **fail closed** if `JWT_SECRET_KEY` is missing or matches known insecure default placeholders.

---

## 3. Installation & Build

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

## 4. Starting the Application

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

## 5. Health Probes & Readiness Topologies

BEACON provides Kubernetes / Container compliant health check endpoints:

### Liveness Probe (`GET /health/live` or `GET /live`)
- **Purpose**: Checks if the BEACON process is alive and responding to HTTP requests.
- **Payload**: `{"status": "UP", "version": "1.0.0", "service": "BEACON"}`
- **HTTP Status**: Always `200 OK` when the process is responsive.

### Readiness Probe (`GET /health/ready` or `GET /ready`)
- **Purpose**: Strictly read-only validation that the database is accessible and registries are loaded.
- **Payload**: `{"status": "READY", "checks": {"database": true, "benchmarks": true, "oracles": true}}`
- **HTTP Status**: `200 OK` when ready to serve; `503 Service Unavailable` if database connectivity fails.

### Detailed Health (`GET /health/details`)
- **Purpose**: Granular dependency inspection.
- **Access**: Restricted to authenticated users with `SYSTEM_ADMIN` role. Never leaks credentials, connection strings, or system paths.

---

## 6. Graceful Shutdown & Lifecycle

When a `SIGTERM` or `SIGINT` signal is received:
1. The server stops accepting new incoming HTTP connections.
2. In-flight requests are allowed up to the graceful shutdown deadline to complete or cancel cooperatively.
3. Active worker thread pools are drained.
4. Database transactions and log buffers are flushed.
5. Process terminates with exit code 0.

---

## 7. Security Hardening Checklist

- [x] Set `BEACON_ENV=production` in the production environment.
- [x] Configure a dedicated, non-default `JWT_SECRET_KEY` via environment variable or secret vault.
- [x] Restrict `CORS_ORIGINS` to trusted enterprise domain names.
- [x] Mount the database on persistent, encrypted storage (e.g. encrypted EBS / persistent volume).
- [x] Serve all public traffic through a TLS reverse proxy (Nginx, Traefik, AWS ALB, Cloudflare).
- [x] Ensure `X-Content-Type-Options`, `X-Frame-Options`, and `Strict-Transport-Security` headers are present on all responses.
