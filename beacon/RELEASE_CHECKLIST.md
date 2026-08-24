# BEACON Release Candidate Checklist

This checklist must be executed and confirmed prior to tagging any production release candidate for BEACON.

---

## 1. Configuration & Security Audit
- [ ] `BEACON_ENV=production` is verified in the deployment manifest.
- [ ] `JWT_SECRET_KEY` is provisioned with a secure $\ge 32$-character random key (not empty, not default).
- [ ] `CORS_ORIGINS` contains explicit allowed origins and does not use wildcard `*` with credentials.
- [ ] Configuration validation passes on startup without errors.
- [ ] No secrets, private keys, or credentials are hard-coded in git-tracked files or test fixtures.

## 2. Database & Lifecycle Verification
- [ ] SQLite database file path is configured on persistent volume storage (`BEACON_DATABASE_PATH`).
- [ ] Database tables and indexes initialize deterministically on clean startup.
- [ ] Startup interrupted job recovery runs safely and marks non-terminal jobs as `FAILED`.
- [ ] Graceful shutdown drains in-flight requests cleanly on `SIGTERM`.

## 3. Health & Observability Endpoints
- [ ] `GET /health/live` returns `200 OK` (`status: "UP"`).
- [ ] `GET /health/ready` returns `200 OK` (`status: "READY"`).
- [ ] `GET /health/details` requires valid `SYSTEM_ADMIN` bearer token and does not leak secrets.
- [ ] `GET /api/v1/operations/version` reports authoritative `1.0.0` version and environment.
- [ ] Structured JSON logs include request IDs and redact Authorization headers / tokens.

## 4. Resilience & Concurrency Guardrails
- [ ] Project-scoped idempotency prevents duplicate execution on concurrent requests with identical keys.
- [ ] Mismatched payloads with the same idempotency key return `409 Conflict`.
- [ ] Execution timeout operates non-blocking with cooperative cancellation.
- [ ] Late workers cannot overwrite timed-out operations with fake success.
- [ ] Bounded retries apply only at transient external provider / lock boundaries.

## 5. Certification Mathematics & Data Integrity
- [ ] Equivalence scoring formulas and thresholds match specifications.
- [ ] Counterexample extraction and OracleSet hashing maintain deterministic integrity.
- [ ] Benchmark registry and user dataset registries isolate project namespaces.

## 6. Automated Test Suite & Build Verification
- [ ] Backend test suite passes: `python -m pytest -q tests` ($\ge 354$ tests, 0 failures, 0 errors).
- [ ] Frontend production bundle builds cleanly: `cd frontend && npm run build` (`✓ built`, 0 errors).
- [ ] Git working tree is clean and synchronized.
