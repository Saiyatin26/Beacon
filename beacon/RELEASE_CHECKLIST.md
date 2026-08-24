# BEACON Release Candidate Checklist

This checklist must be executed and confirmed prior to tagging or freezing any production release candidate for BEACON.

---

## Production Release Verification Checklist

- [ ] **Production JWT secret $\ge 32$ characters**: `JWT_SECRET_KEY` is provisioned with $\ge 32$ cryptographically random characters in production/staging; empty, short, or placeholder keys fail closed on startup.
- [ ] **Production CORS verified**: Wildcard `*` is strictly rejected when credentials are enabled; explicit allowlists are configured for methods (`GET, POST, PUT, PATCH, DELETE, OPTIONS`) and headers.
- [ ] **HSTS verified**: `Strict-Transport-Security` is conditionally attached on HTTPS requests in production/staging environments, and omitted in local dev/test HTTP requests.
- [ ] **Public health disclosure reviewed**: `/health` and `/health/live` expose only minimal safe operational status (`status`, `version`) without leaking filesystem paths, environment names, or storage internals.
- [ ] **Detailed health authorization verified**: `/health/details` strictly enforces `SYSTEM_ADMIN` role via bearer token authentication; unauthenticated or non-admin requests return `401`/`403`.
- [ ] **Every API endpoint classified**: All backend API endpoints are audited and classified into `PUBLIC`, `AUTHENTICATED`, `PROJECT-SCOPED`, or `SYSTEM-ADMIN`.
- [ ] **Demo endpoints reviewed**: `/demo/run`, `/drift/demo`, and `/demo/invariants` are disabled in production and staging environments (`403 Forbidden`).
- [ ] **Drift endpoints authorized**: `/api/v1/drift/evaluate` and `/drift` require authenticated project permissions.
- [ ] **Benchmark validation classified**: `/api/v1/benchmarks/{id}/validate` requires authenticated project `VIEW` permission.
- [ ] **Oracle compilation protected**: `/api/oracles/compile` strictly requires `CERTIFY` permissions.
- [ ] **Project isolation verified**: Project-scoped endpoints enforce server-derived project authorization rather than relying solely on unverified client-supplied project IDs.
- [ ] **Frontend production URL verified**: `VITE_API_BASE_URL` properly defaults to relative path `""` in production builds without hardcoded `localhost` references.
- [ ] **No frontend secrets**: Frontend environment files contain no backend credentials, API keys, or JWT secrets.
- [ ] **Upload limits verified**: Request bodies and custom dataset uploads exceeding `MAX_DATASET_SIZE_BYTES` or containing prohibited API secrets are rejected.
- [ ] **Temporary-file cleanup verified**: Ingestion and preview parsers operate in-memory with automatic cleanup in `finally` blocks upon errors, timeouts, or completion.
- [ ] **Provider secrets redacted**: Structured JSON logs and error responses scrub API keys, bearer tokens, passwords, and connection strings.
- [ ] **SQLite architecture documented**: Core operational jobs, idempotency keys, and dataset metadata documented in `DEPLOYMENT.md` and `BACKUP_AND_RECOVERY.md`.
- [ ] **MongoDB architecture documented**: Optional hybrid domain persistence for vector search invariant deduplication and cloud drift time-series documented.
- [ ] **Backup/recovery documented**: Online WAL snapshots (`.backup`) and `mongodump`/`mongorestore` restoration procedures documented in `BACKUP_AND_RECOVERY.md`.
- [ ] **Backend tests $\ge 354$ passed**: Full test suite passes: `python -m pytest -q tests` ($\ge 354$ tests, 0 failures, 0 errors).
- [ ] **Frontend build succeeds**: Production Vite build executes cleanly: `cd frontend && npm run build` (`✓ built`, 0 errors).
- [ ] **Git working tree clean**: All files staged/committed and synchronized.
