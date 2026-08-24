# BEACON Release Candidate Checklist

This checklist must be executed and confirmed prior to tagging or freezing any production release candidate for BEACON.

---

## Production Release Verification Checklist

- [ ] **JWT production secret $\ge 32$ characters**: `JWT_SECRET_KEY` is provisioned with $\ge 32$ cryptographically random characters in production/staging; empty, short, or placeholder keys fail closed on startup.
- [ ] **Production CORS verified**: Wildcard `*` is strictly rejected when credentials are enabled; explicit allowlists are configured for methods (`GET, POST, PUT, PATCH, DELETE, OPTIONS`) and headers.
- [ ] **HSTS production behavior verified**: `Strict-Transport-Security` is conditionally attached on HTTPS requests in production/staging environments, and omitted in local dev/test HTTP requests.
- [ ] **Public health disclosure reviewed**: `/health` and `/health/live` expose only minimal safe operational status (`status`, `version`) without leaking filesystem paths, environment names, or storage internals.
- [ ] **Detailed health authorization verified**: `/health/details` strictly enforces `SYSTEM_ADMIN` role via bearer token authentication; unauthenticated or non-admin requests return `401`/`403`.
- [ ] **Every endpoint classified**: All backend API endpoints are audited and classified into `PUBLIC`, `AUTHENTICATED`, `PROJECT-SCOPED`, or `SYSTEM-ADMIN`.
- [ ] **Project isolation verified**: Project-scoped endpoints enforce server-derived project authorization rather than relying solely on unverified client-supplied project IDs.
- [ ] **Database architecture documented**: Hybrid architecture (SQLite for operational state/idempotency/jobs; optional MongoDB Atlas for domain vector search/invariants) is explicitly documented.
- [ ] **SQLite backup documented**: Online WAL snapshot procedures and restoration commands are documented in `BACKUP_AND_RECOVERY.md`.
- [ ] **MongoDB backup documented if applicable**: `mongodump` and Atlas snapshot procedures documented for optional enterprise vector deployments.
- [ ] **Upload limits verified**: Request bodies and custom dataset uploads exceeding `MAX_DATASET_SIZE_BYTES` or containing prohibited API secrets are rejected.
- [ ] **Temporary file cleanup verified**: Ingestion and preview parsers operate in-memory with automatic cleanup in `finally` blocks upon errors, timeouts, or completion.
- [ ] **Provider secrets redacted**: Structured JSON logs and error responses scrub API keys, bearer tokens, passwords, and connection strings.
- [ ] **Production frontend API URL verified**: `VITE_API_BASE_URL` properly defaults to relative path `""` in production builds without hardcoded `localhost` references or exposed backend secrets.
- [ ] **Backend tests pass**: Full test suite passes: `python -m pytest -q tests` ($\ge 354$ tests, 0 failures, 0 errors).
- [ ] **Frontend build succeeds**: Production Vite build executes cleanly: `cd frontend && npm run build` (`✓ built`, 0 errors).
- [ ] **Git working tree clean**: All files staged/committed and synchronized.
