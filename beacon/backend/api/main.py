import hashlib
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

logger = logging.getLogger(__name__)

sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[2] / "legacy_sample"))

from fastapi import FastAPI, HTTPException, Request, Response, Depends, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from certification.runner import certify
from certification.scorer import equivalence_score
from certification import (
    CertificationArtifact,
    CertificationContext,
    CertificationEngine,
    CertificationPolicy,
    CertificationStatus,
    LegacyAdapter,
    ModernizedAdapter,
    certification_engine,
    certification_repository,
    compute_certification_request_identity,
    generate_html_report,
    generate_markdown_report,
    verify_artifact_integrity,
)
from drift import (
    DriftEvent,
    DriftObservation,
    DriftPolicy,
    DriftStatus,
    evaluate_drift_observation,
)
from common.config import settings
from common.local_store import local_store
from common.models import DriftSample
from ingestion.legacy_parser import load_source
from ingestion.trace_loader import load_traces

from oracle.interpreter import run_oracle
from oracle.synthesizer import synthesize_oracle
from oracle import registry, compile_candidate_to_oracle, OracleCompilationError
from oracle.models import OracleSet
from benchmarks.models import BenchmarkValidationResult

from contextlib import asynccontextmanager

from operations import (
    check_liveness,
    check_readiness,
    check_dependency_health,
    get_version_info,
    validate_startup_configuration,
    setup_structured_logging,
    recover_interrupted_operations,
    RequestCorrelationMiddleware,
    WorkloadLimiterMiddleware,
    register_error_handlers,
    JobState,
    certification_job_tracker,
    operational_metrics,
    workload_protector,
    log_operational_event,
    execution_step,
    ResourceLimitError,
    idempotency_manager,
    IdempotencyConflictError,
)


from auth import (
    auth_router,
    get_current_user,
    get_current_active_user,
    require_project_permission,
    require_system_admin,
    Permission,
    User,
    auth_repository,
)
from api.application_router import application_router

from common.db_migration import consolidate_database_architecture



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern FastAPI application lifespan context manager for startup & shutdown."""
    # 1. Structured logging initialization
    setup_structured_logging()

    # 2. Database architecture consolidation (single canonical SQLite store & WAL mode)
    try:
        consolidate_database_architecture()
    except Exception as _exc:
        logger.warning(f"Database consolidation check notice: {_exc}")

    # 3. Hardened configuration validation (fail-closed in production)
    settings.validate(raise_on_error=(settings.beacon_env in ("production", "staging")))
    validate_startup_configuration()

    # 4. Safe interrupted operations recovery (executed once at startup)
    try:
        recover_interrupted_operations()
    except Exception as _exc:
        logger.warning(f"Startup interrupted operation recovery encountered non-fatal error: {_exc}")

    # 5. Pre-load controlled OracleSets for read-only /health/ready
    try:
        from benchmarks import benchmark_registry as _br
        from oracle.registry import registry as _or
        for _bench in _br.list_benchmarks():
            try:
                _oset = _br.get_or_create_oracle_set(_bench.benchmark_id, mode="CONTROLLED")
                if _oset and not _or.get_oracle_set(_oset.oracle_set_id):
                    _or.register_oracle_set(_oset)
            except Exception as _exc:
                logger.debug(f"Startup oracle pre-load for {_bench.benchmark_id}: {_exc}")
    except Exception as _exc:
        logger.warning(f"Startup oracle pre-load failed: {_exc}")

    logger.info(f"BEACON v{settings.beacon_version} operational and ready [Environment: {settings.beacon_env}]")
    yield

    # 6. Graceful shutdown
    logger.info("BEACON server shutdown initiated. Performing graceful cleanup...")
    try:
        operational_metrics.get_snapshot()
    except Exception:
        pass
    logger.info("BEACON server shutdown completed cleanly.")


app = FastAPI(title="BEACON API", version=settings.beacon_version, lifespan=lifespan)

# Phase 16 & 20 CORS Configuration
allowed_methods = (
    ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    if settings.beacon_env in ("production", "staging")
    else ["*"]
)
allowed_headers = (
    [
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "X-Correlation-ID",
        "X-Request-ID",
        "Accept",
        "Origin",
    ]
    if settings.beacon_env in ("production", "staging")
    else ["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=allowed_methods,
    allow_headers=allowed_headers,
    allow_credentials=True,
)
app.add_middleware(RequestCorrelationMiddleware)
app.add_middleware(WorkloadLimiterMiddleware)

# Phase 17 & 20 Security Headers & API Version Middleware
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Beacon-Version"] = settings.beacon_version

    # HSTS is conditionally applied in production/staging environments on HTTPS requests
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"
    if settings.beacon_env in ("production", "staging") and is_https:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    return response



# Phase 16 Error Handlers
register_error_handlers(app)

# Phase 17 Authentication & RBAC Routes
app.include_router(auth_router)

# Phase 1 (V2) Generic Domain-Agnostic Applications Routes
app.include_router(application_router)

# Phase 2 (V2) Generic Adapter & Execution Routes
from api.adapter_router import adapter_router
app.include_router(adapter_router)

# Phase 3 (V2) Paired Application Execution & Evidence Capture Routes
from api.paired_router import paired_router
app.include_router(paired_router)

# Phase 4 (V2) Behavioral Equivalence Evaluation Routes
from api.evaluation_router import evaluation_router
app.include_router(evaluation_router)

# Phase 5 (V2) Business-Rule Understanding & Controlled Mode Routes
from api.controlled_router import controlled_router
app.include_router(controlled_router)

# Phase 6 (V2) Behavioral Rule & Invariant Discovery Routes
from api.discovery_router import discovery_router
app.include_router(discovery_router)




class DemoRunRequest(BaseModel):
    implementation: Literal["buggy", "equivalent", "clean"] = "buggy"
    project_id: str = "loan_demo"


class DriftRequest(BaseModel):
    baseline_run_id: str
    implementation: Literal["buggy", "equivalent", "clean"] = "buggy"
    project_id: str = "loan_demo"


# ==============================================================================
# V1 Demo / Local Sample Compatibility Fixtures & Helpers
# ==============================================================================
_DEMO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_SAMPLE_DIR = _DEMO_ROOT / "legacy_sample"
_DEMO_FIELD_BOUNDS = {
    "credit_score": (400, 820),
    "debt_ratio": (0.0, 0.9),
    "annual_income": (10_000, 150_000),
}


def _sample_traces():
    import generate_traces
    trace_path = _DEMO_SAMPLE_DIR / "trace_log.json"
    if not trace_path.exists():
        import json
        trace_path.write_text(json.dumps(generate_traces.generate_traces(), indent=2))
    return load_traces(trace_path)


from ingestion.legacy_parser import extract_ast_structure
from evidence.builder import build_evidence_package
from mining.pipeline import run_mining_pipeline

def _sample_oracles():
    import legacy_loan_approval
    traces = _sample_traces()
    legacy_file = str(_DEMO_SAMPLE_DIR / "legacy_loan_approval.py")
    static_result = extract_ast_structure(legacy_file)
    evidence_pkg = build_evidence_package(static_result, traces)
    
    graduated, unconfirmed = run_mining_pipeline(
        evidence_package=evidence_pkg,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=_DEMO_FIELD_BOUNDS,
        already_validated=[],
        use_atlas=False,
        use_llm=False
    )
    return [synthesize_oracle(invariant) for invariant in graduated], graduated

def _implementation(name: str):
    import modern_loan_approval
    import modern_clean_loan_approval
    if name == "buggy":
        return modern_loan_approval.evaluate_loan
    return modern_clean_loan_approval.evaluate_loan



@app.get("/")
def root():
    return {
        "name": "BEACON API",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "live": "/health/live",
        "ready": "/health/ready",
        "details": "/health/details",
        "version": "/api/v1/operations/version",
    }


# ==============================================================================
# Phase 16 & 18: Operational Health, Version & Metrics Endpoints
# ==============================================================================

@app.get("/api/v1/operations/version")
@app.get("/version")
def version_endpoint():
    """Safe, non-sensitive version, build, and API environment metadata."""
    res = get_version_info()
    return res.model_dump(mode="json")


@app.get("/health/live")
@app.get("/live")
@app.get("/api/v1/health/live")
def liveness_endpoint():
    """Liveness probe: answers if BEACON process is running and responsive."""
    res = check_liveness()
    return res.model_dump(mode="json")


@app.get("/health/ready")
@app.get("/ready")
@app.get("/api/v1/health/ready")
def readiness_endpoint():
    """Readiness probe: answers if BEACON is currently able to accept certification work."""
    res = check_readiness()
    if res.status != "READY":
        return JSONResponse(status_code=503, content=res.model_dump(mode="json"))
    return res.model_dump(mode="json")


@app.get("/health/details")
@app.get("/api/v1/health/details")
def health_details_endpoint(
    current_user: User = Depends(require_system_admin),
):
    """Granular dependency health inspection without secret exposure (System Administrator only)."""
    res = check_dependency_health()
    return res.model_dump(mode="json")


@app.get("/health")
@app.get("/api/v1/health")
def health():
    """Standard public health endpoint returning safe liveness, readiness, and version."""
    readiness = check_readiness()
    return {
        "status": "ok" if readiness.status == "READY" else "degraded",
        "version": settings.beacon_version,
    }




@app.get("/api/v1/operations/system-metrics")
def get_system_operations_metrics_endpoint(
    current_user: User = Depends(require_system_admin),
):
    """Returns global system-wide operational metrics (System Administrator only)."""
    return operational_metrics.get_snapshot().model_dump(mode="json")





@app.get("/api/v1/certification/jobs/{job_id}")
def get_certification_job_endpoint(
    job_id: str,
    project_id: str,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Retrieves operational lifecycle state for a certification job.
    project_id is required and enforced server-side for project isolation.
    Returns 403 if the job belongs to a different project.
    """
    try:
        job = certification_job_tracker.get_job(job_id, project_id=project_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Certification job '{job_id}' not found.")
        return job.model_dump(mode="json")
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))


@app.get("/api/v1/certification/jobs")
def list_certification_jobs_endpoint(
    project_id: str,
    limit: int = 50,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Lists recent operational certification jobs scoped to the given project.
    project_id is required and enforced server-side — the server only returns
    jobs belonging to the specified project.
    """
    jobs = certification_job_tracker.list_jobs(project_id=project_id, limit=limit)
    return {"jobs": [j.model_dump(mode="json") for j in jobs]}


@app.get("/api/v1/operations/metrics")
def get_operations_metrics_endpoint(
    project_id: str,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Returns aggregated runtime counters, latency averages, and error metrics
    scoped to the given project. project_id is required.
    """
    snapshot = operational_metrics.get_project_snapshot(project_id=project_id)
    return snapshot


@app.get("/api/v1/operations/summary")
def get_operations_summary_endpoint(
    project_id: str,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Returns high-level operational system summary scoped to the given project.
    project_id is required.
    """
    health_det = check_dependency_health()
    metrics_snap = operational_metrics.get_project_snapshot(project_id=project_id)
    recent_jobs = certification_job_tracker.list_jobs(project_id=project_id, limit=10)

    return {
        "system_status": health_det.status,
        "liveness": health_det.liveness,
        "readiness": health_det.readiness,
        "dependencies": {k: v.model_dump(mode="json") for k, v in health_det.dependencies.items()},
        "metrics": metrics_snap,
        "recent_jobs": [j.model_dump(mode="json") for j in recent_jobs],
    }


from llm.manager import get_provider_manager


@app.get("/api/llm/status")
def get_llm_status(current_user: User = Depends(get_current_active_user)):
    """Returns sanitized multi-provider LLM status and availability for authenticated users."""
    manager = get_provider_manager()
    return manager.get_status()


from oracle.registry import registry
from oracle.compiler import compile_candidate_to_oracle, OracleCompilationError
from common.models import CandidateInvariant


@app.get("/api/oracles")
def list_oracles(
    domain: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
):
    """Lists registered canonical language-independent oracles."""
    oracles = registry.list_oracles(domain=domain)
    return {"oracles": [o.model_dump(mode="json") for o in oracles]}


@app.get("/api/oracles/{oracle_id}")
def get_oracle_endpoint(
    oracle_id: str,
    version: Optional[int] = None,
    current_user: User = Depends(get_current_active_user),
):
    """Retrieves a specific versioned oracle definition."""
    oracle = registry.get_oracle(oracle_id, version=version)
    if oracle is None:
        raise HTTPException(status_code=404, detail=f"Oracle '{oracle_id}' not found")
    return oracle.model_dump(mode="json")


@app.get("/api/oracle-sets")
def list_oracle_sets_endpoint(
    domain: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
):
    """Lists frozen Oracle Sets."""
    sets = registry.list_oracle_sets(domain=domain)
    return {"oracle_sets": [s.model_dump(mode="json") for s in sets]}


@app.get("/api/oracle-sets/{set_id}")
def get_oracle_set_endpoint(
    set_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Retrieves a frozen Oracle Set by ID."""
    oracle_set = registry.get_oracle_set(set_id)
    if oracle_set is None:
        raise HTTPException(status_code=404, detail=f"OracleSet '{set_id}' not found")
    return oracle_set.model_dump(mode="json")


@app.post("/api/oracles/compile")
def compile_oracle_endpoint(
    candidate: CandidateInvariant,
    current_user: User = Depends(require_project_permission(Permission.CERTIFY)),
):
    """Compiles a validated CandidateInvariant into a canonical Oracle.
    Rejects unvalidated, invalidated, grounding-failed, or low-confidence (<0.8) candidates.
    Requires authenticated user with CERTIFY permission.
    """
    try:
        oracle = compile_candidate_to_oracle(candidate)
        registered = registry.register_oracle(oracle)
        return registered.model_dump(mode="json")
    except OracleCompilationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Oracle compilation error: {exc}")



@app.get("/runs")
def list_runs(
    project_id: Optional[str] = Query(None, description="Authorized project identifier to scope runs"),
    limit: int = 20,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Lists certification runs filtered by authorized project."""
    bounded_limit = max(1, min(limit, 100))
    target_project = project_id
    if not target_project and not current_user.is_system_admin:
        memberships = auth_repository.get_user_memberships(current_user.user_id)
        if memberships:
            target_project = memberships[0].project_id

    runs = local_store.list_runs(limit=bounded_limit, project_id=target_project)
    if target_project and not current_user.is_system_admin:
        runs = [r for r in runs if r.get("project_id") == target_project or r.get("project_id") is None]

    return {"runs": runs}


@app.get("/runs/{run_id}")
def get_run(
    run_id: str,
    project_id: Optional[str] = Query(None),
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Retrieves a specific certification run ensuring project isolation."""
    run = local_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Certification run not found")

    run_proj = run.get("project_id")
    if run_proj and not current_user.is_system_admin:
        memberships = auth_repository.get_user_memberships(current_user.user_id)
        user_projects = {m.project_id for m in memberships}
        if run_proj not in user_projects and run_proj not in ("loan_approval", "proj-default"):
            raise HTTPException(status_code=404, detail="Certification run not found")

    return run


@app.post("/demo/run")
def run_demo(
    request: DemoRunRequest,
    current_user: User = Depends(require_project_permission(Permission.CERTIFY)),
):
    """Mine local rules, certify a sample implementation, and persist the report.
    Disabled in production/staging environments.
    """
    if settings.beacon_env in ("production", "staging"):
        raise HTTPException(
            status_code=403,
            detail="Demo endpoints are disabled in production and staging environments.",
        )
    oracles, invariants = _sample_oracles()
    if not oracles:
        raise HTTPException(status_code=500, detail="No validated sample invariants were produced")
    import legacy_loan_approval
    run = certify(
        oracles=oracles,
        modern_fn=_implementation(request.implementation),
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=_DEMO_FIELD_BOUNDS,
        domain_of={oracle.invariant_id: "Loan approval" for oracle in oracles},
    )
    local_store.save_run(run, project_id=request.project_id)
    return {
        "run": run.model_dump(mode="json"),
        "implementation": request.implementation,
        "invariants": [invariant.model_dump(mode="json") for invariant in invariants],
    }


@app.get("/demo/invariants")
def list_demo_invariants(
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    if settings.beacon_env in ("production", "staging"):
        raise HTTPException(
            status_code=403,
            detail="Demo endpoints are disabled in production and staging environments.",
        )
    _, invariants = _sample_oracles()
    return {"invariants": [invariant.model_dump(mode="json") for invariant in invariants]}


@app.post("/drift/demo")
def check_demo_drift(
    request: DriftRequest,
    current_user: User = Depends(require_project_permission(Permission.CERTIFY)),
):
    if settings.beacon_env in ("production", "staging"):
        raise HTTPException(
            status_code=403,
            detail="Demo endpoints are disabled in production and staging environments.",
        )
    baseline = local_store.get_run(request.baseline_run_id)
    if baseline is None:
        raise HTTPException(status_code=404, detail="Baseline certification run not found")
    oracles, _ = _sample_oracles()
    results = [run_oracle(oracle, _implementation(request.implementation), _DEMO_FIELD_BOUNDS) for oracle in oracles]
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
def list_drift_samples(
    limit: int = 100,
    benchmark_id: Optional[str] = None,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    all_samples = local_store.list_drift_samples(benchmark_id=benchmark_id, limit=max(1, min(limit, 500)))
    if benchmark_id:
        if benchmark_id in ("loan", "loan_approval"):
            return {"samples": [s for s in all_samples if s.get("benchmark_id") in ("loan", "loan_approval", None)]}
        return {"samples": [s for s in all_samples if s.get("benchmark_id") == benchmark_id]}
    return {"samples": all_samples}



# ==============================================================================
# Phase 10 — Production-Grade Certification & Drift Endpoints
# ==============================================================================

from certification.adapter_registry import adapter_registry
from benchmarks.models import DiscoveryMode, BenchmarkValidationRequest
from benchmarks.registry import benchmark_registry

class CertificationRunRequest(BaseModel):
    project_id: Optional[str] = None
    benchmark_id: Optional[str] = None
    benchmark_variant: Optional[str] = "clean_v2"
    discovery_mode: Literal["CONTROLLED", "FULL_BEACON"] = "CONTROLLED"
    preferred_provider: Optional[str] = "auto"
    use_llm: bool = False
    legacy_target: Optional[str] = "loan_approval_legacy"
    modernized_target: Optional[str] = "loan_approval_modern_equiv"
    legacy_version: Optional[str] = None
    modernized_version: Optional[str] = None
    oracle_set_id: Optional[str] = None
    policy: Optional[CertificationPolicy] = None
    implementation: Optional[Literal["equivalent", "buggy"]] = None
    dataset_name: str = "default"
    n_samples: int = 100
    seed: int = 42
    force_recompute: bool = False
    idempotency_key: Optional[str] = None


class DriftEvaluateRequest(BaseModel):
    observation_id: str
    oracle_set_id: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    environment: str = "production"
    application_version: str = "2.0.0"
    certification_id: Optional[str] = None


@app.get("/api/v1/benchmarks")
def list_benchmarks_endpoint():
    """Lists all registered benchmarks with full provenance metadata."""
    benchmarks = benchmark_registry.list_benchmarks()
    return {"benchmarks": [b.model_dump(mode="json") for b in benchmarks]}


@app.get("/api/v1/benchmarks/{benchmark_id}")
def get_benchmark_endpoint(benchmark_id: str):
    """Retrieves detailed specification for a specific benchmark."""
    spec = benchmark_registry.get_benchmark(benchmark_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Benchmark '{benchmark_id}' not found.")
    return spec.model_dump(mode="json")


@app.get("/api/v1/benchmarks/{benchmark_id}/validate")
@app.post("/api/v1/benchmarks/{benchmark_id}/validate")
def validate_benchmark_endpoint(
    benchmark_id: str,
    request: Optional[BenchmarkValidationRequest] = None,
    evaluation_mode: str = "CONTROLLED",
    target_variant: str = "clean_v2",
    preferred_provider: str = "auto",
    dataset_name: str = "default",
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Performs comprehensive pre-flight validation on a benchmark's adapters, schemas, dataset, and configuration."""

    mode = request.evaluation_mode if request and request.evaluation_mode else evaluation_mode
    variant = request.target_variant if request and request.target_variant else target_variant
    provider = request.preferred_provider if request and request.preferred_provider else preferred_provider
    d_name = request.dataset_name if request and request.dataset_name else dataset_name

    log_operational_event(
        event="preflight_started",
        logger_name="beacon.execution",
        operation="PRE-FLIGHT",
        step="REQUEST",
        phase="01",
        benchmark_id=benchmark_id,
        evaluation_mode=mode,
        target_variant=variant,
        provider=provider,
        message=f"[PRE-FLIGHT] START | benchmark={benchmark_id} | mode={mode} | variant={variant}",
    )

    result = benchmark_registry.validate_benchmark(
        benchmark_id=benchmark_id,
        evaluation_mode=mode,
        target_variant=variant,
        preferred_provider=provider,
        dataset_name=d_name,
    )
    if not result.is_valid and any("not found in registry" in e for e in result.errors):
        raise HTTPException(status_code=404, detail=f"Benchmark '{benchmark_id}' not found.")
    log_operational_event(
        event="preflight_completed",
        logger_name="beacon.execution",
        operation="PRE-FLIGHT",
        step="RESULT",
        benchmark_id=benchmark_id,
        evaluation_mode=result.evaluation_mode,
        target_variant=result.target_variant,
        outcome="READY" if result.is_valid else "NOT_READY",
        records=result.dataset_record_count,
        message=(
            f"[PRE-FLIGHT] COMPLETE | status={'READY' if result.is_valid else 'NOT_READY'} "
            f"| records={result.dataset_record_count} | errors={len(result.errors)}"
        ),
    )
    return result.model_dump(mode="json")


@app.get("/api/v1/benchmarks/{benchmark_id}/manifest")
def get_benchmark_manifest(
    benchmark_id: str,
    discovery_mode: DiscoveryMode = DiscoveryMode.CONTROLLED,
    variant: str = "clean_v2",
):
    """Retrieves an execution manifest matching the EXACT benchmark, mode, and variant context."""
    spec = benchmark_registry.get_benchmark(benchmark_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Benchmark '{benchmark_id}' not found.")

    mode_str = discovery_mode.value if hasattr(discovery_mode, "value") else str(discovery_mode)
    art = certification_repository.get_artifact_by_context(
        benchmark_id=benchmark_id,
        evaluation_mode=mode_str,
        modernization_variant=variant,
    )
    manifest = benchmark_registry.create_execution_manifest(
        benchmark_id=benchmark_id,
        artifact=art or {},
        discovery_mode=discovery_mode,
        variant_name=variant,
    )
    return manifest.model_dump(mode="json")


@app.post("/api/v1/certification/run")
def run_certification_v1(
    request: CertificationRunRequest,
    project_id: Optional[str] = Query(None),
    current_user: User = Depends(require_project_permission(Permission.CERTIFY)),
):
    """Executes a policy-driven behavioral certification run using registered ImplementationAdapters or Benchmarks."""
    resolved_project_id = project_id or request.project_id

    log_operational_event(
        event="certification_started",
        logger_name="beacon.execution",
        operation="CERTIFICATION",
        step="REQUEST",
        benchmark_id=request.benchmark_id or resolved_project_id,
        evaluation_mode=request.discovery_mode,
        target_variant=request.benchmark_variant or request.modernized_target or "clean_v2",
        provider=request.preferred_provider,
        message=(
            f"[CERTIFICATION] START | benchmark={request.benchmark_id or resolved_project_id} "
            f"| mode={request.discovery_mode} | implementation={request.implementation}"
        ),
    )


    # 1. Benchmark Resolution Mode
    test_inputs = None
    context = None
    if request.benchmark_id:
        proj_id = resolved_project_id or f"benchmark_{request.benchmark_id}"
        bench_spec = benchmark_registry.get_benchmark(request.benchmark_id)

        if not bench_spec:
            raise HTTPException(status_code=404, detail=f"Benchmark '{request.benchmark_id}' not found.")

        mode = "FULL_BEACON" if request.discovery_mode == "FULL_BEACON" else "CONTROLLED"
        pref_prov = (request.preferred_provider or "auto").lower().strip()
        use_llm_flag = request.use_llm or (mode == "FULL_BEACON" and pref_prov != "offline")

        oracle_set = benchmark_registry.get_or_create_oracle_set(
            request.benchmark_id,
            mode=mode,
            preferred_provider=pref_prov,
            use_llm=use_llm_flag,
        )
        log_operational_event(
            event="certification_configuration_resolved",
            logger_name="beacon.execution",
            operation="CERTIFICATION",
            step="CONFIGURATION",
            benchmark_id=request.benchmark_id,
            evaluation_mode=mode,
            provider=pref_prov,
            oracles=len(oracle_set.oracles),
            message=(
                f"[CERTIFICATION] CONFIGURATION COMPLETE | benchmark={request.benchmark_id} "
                f"| mode={mode} | oracles={len(oracle_set.oracles)}"
            ),
        )
        legacy_adp = benchmark_registry.get_legacy_adapter(request.benchmark_id)
        if not legacy_adp:
            raise HTTPException(status_code=404, detail=f"Legacy adapter for benchmark '{request.benchmark_id}' not found.")

        # Map variant
        variant = request.benchmark_variant or "clean_v2"
        if request.implementation == "buggy" and variant == "clean_v2":
            variant = list(bench_spec.modernized_adapters.keys())[1] if len(bench_spec.modernized_adapters) > 1 else "buggy_v2"
        elif request.implementation == "equivalent":
            variant = "clean_v2"

        modern_adp = benchmark_registry.get_modernized_adapter(request.benchmark_id, variant=variant)
        if not modern_adp:
            raise HTTPException(status_code=404, detail=f"Modernized adapter variant '{variant}' for benchmark '{request.benchmark_id}' not found.")

        # Load input dataset
        try:
            test_inputs = benchmark_registry.get_input_dataset(request.benchmark_id, dataset_name=request.dataset_name)
            log_operational_event(
                event="dataset_loaded",
                logger_name="beacon.execution",
                operation="CERTIFICATION",
                step="DATASET",
                benchmark_id=request.benchmark_id,
                dataset_id=request.dataset_name,
                records=len(test_inputs),
                message=f"[CERTIFICATION] DATASET COMPLETE | records={len(test_inputs)}",
            )
        except Exception as exc:
            logger.warning(f"Could not load dataset for benchmark {request.benchmark_id}: {exc}")

        field_bounds = bench_spec.field_bounds
        proj_id = request.project_id or f"benchmark_{request.benchmark_id}"

        prov_cat = bench_spec.provenance_category.value if hasattr(bench_spec.provenance_category, "value") else str(bench_spec.provenance_category)
        mod_prov = bench_spec.modernization_provenance.get(variant, "INDEPENDENT_REIMPLEMENTATION")
        if hasattr(mod_prov, "value"):
            mod_prov = mod_prov.value

        first_prov = getattr(oracle_set.oracles[0], "provenance", None) if oracle_set.oracles else None
        ev_src = getattr(first_prov, "evidence_source", "") if first_prov else ""
        repro = getattr(first_prov, "reproducibility", {}) if first_prov else {}
        act_prov = repro.get("actual_provider") or repro.get("provider") or ("offline" if mode == "CONTROLLED" else pref_prov)
        act_mod = repro.get("actual_model") or repro.get("model") or ("deterministic" if mode == "CONTROLLED" else "default")
        fb_occ = repro.get("fallback_occurred", False)
        fb_chain = repro.get("fallback_chain", [])
        fb_reason = repro.get("fallback_reason") or repro.get("prior_error")
        gen_method = getattr(first_prov, "generation_method", "offline") if first_prov else "offline"
        mining_method = getattr(first_prov, "mining_method", "manual_baseline_specification") if first_prov else "manual"

        if mode == "CONTROLLED":
            oracle_src = "CONTROLLED_ORACLE_SET"
        elif act_prov == "offline" or ev_src == "FULL_BEACON_OFFLINE_FALLBACK":
            oracle_src = "FULL_BEACON_OFFLINE_FALLBACK"
        else:
            oracle_src = "FULL_BEACON_DISCOVERED"

        ev_pkg_h = repro.get("evidence_package_hash", "")
        prompt_ver = repro.get("prompt_version", "v1.0")

        context = CertificationContext(
            benchmark_id=request.benchmark_id,
            benchmark_version=bench_spec.legacy_version,
            benchmark_name=bench_spec.name,
            benchmark_provenance=prov_cat,
            dataset_id=request.dataset_name,
            dataset_version=bench_spec.dataset_version,
            dataset_checksum=bench_spec.dataset_checksum,
            evaluation_mode=mode,
            modernization_variant_id=variant,
            modernization_variant_name=variant.replace("_v2", "").replace("_", " ").title(),
            modernization_provenance=str(mod_prov),
            legacy_implementation_id=legacy_adp.name,
            legacy_implementation_hash=getattr(legacy_adp, "implementation_hash", "") or bench_spec.legacy_implementation_hash,
            modernized_implementation_id=modern_adp.name,
            modernized_implementation_hash=getattr(modern_adp, "implementation_hash", ""),
            oracle_set_id=oracle_set.oracle_set_id,
            oracle_set_hash=oracle_set.oracle_set_hash,
            oracle_source_type=oracle_src,
            evidence_package_hash=ev_pkg_h,
            prompt_version=prompt_ver,
            provider=act_prov,
            model=act_mod,
            generation_method=gen_method,
            policy_id=request.policy.policy_id if request.policy else "POL-DEFAULT",
            policy_hash="",
            provider_metadata={
                "preferred_provider": pref_prov,
                "actual_provider": act_prov,
                "actual_model": act_mod,
                "fallback_occurred": fb_occ,
                "fallback_chain": fb_chain,
                "fallback_reason": fb_reason,
                "evidence_package_hash": ev_pkg_h,
                "prompt_version": prompt_ver,
                "generation_method": gen_method,
                "mining_method": mining_method,
                "oracle_source_type": oracle_src,
            },
        )

    # 2. Generic Adapter Resolution Mode
    else:
        if not request.oracle_set_id:
            raise HTTPException(status_code=400, detail="Missing oracle_set_id for generic certification run.")

        oracle_set = registry.get_oracle_set(request.oracle_set_id)
        if oracle_set is None:
            raise HTTPException(
                status_code=404,
                detail=f"Frozen OracleSet '{request.oracle_set_id}' not found in registry.",
            )

        legacy_adp = adapter_registry.get_adapter(request.legacy_target or "loan_approval_legacy", request.legacy_version)
        if legacy_adp is None:
            raise HTTPException(
                status_code=404,
                detail=f"Legacy implementation adapter '{request.legacy_target}' not found in adapter registry.",
            )

        mod_target_name = request.modernized_target or "loan_approval_modern_equiv"
        if request.implementation == "buggy" and mod_target_name in ("loan_approval_modern_equiv", "loan_approval_modern"):
            mod_target_name = "loan_approval_modern_buggy"
        elif request.implementation == "equivalent" and mod_target_name == "loan_approval_modern_buggy":
            mod_target_name = "loan_approval_modern_equiv"

        modern_adp = adapter_registry.get_adapter(mod_target_name, request.modernized_version)
        if modern_adp is None:
            raise HTTPException(
                status_code=404,
                detail=f"Modernized implementation adapter '{mod_target_name}' not found in adapter registry.",
            )

        field_bounds = None
        proj_id = resolved_project_id or request.project_id or "default_project"


    # 3. Construct Deterministic Request Identity (All Certification-Affecting Fields)
    pol_id = request.policy.policy_id if request.policy else "POL-DEFAULT"
    pol_hash = request.policy.compute_hash() if request.policy else ""
    leg_impl_hash = getattr(legacy_adp, "implementation_hash", "") or (context.legacy_implementation_hash if context else "")
    mod_impl_hash = getattr(modern_adp, "implementation_hash", "") or (context.modernized_implementation_hash if context else "")
    d_checksum = context.dataset_checksum if context else ""
    b_ver = context.benchmark_version if context else "1.0.0"
    e_mode = context.evaluation_mode if context else request.discovery_mode
    t_variant = context.modernization_variant_id if context else (request.benchmark_variant or "clean_v2")
    p_prov = request.preferred_provider or "auto"
    use_llm_flag = request.use_llm or (e_mode == "FULL_BEACON" and p_prov != "offline")

    request_identity = compute_certification_request_identity(
        benchmark_id=request.benchmark_id or proj_id,
        benchmark_version=b_ver,
        dataset_name=request.dataset_name,
        dataset_checksum=d_checksum,
        discovery_mode=e_mode,
        target_variant=t_variant,
        preferred_provider=p_prov,
        use_llm=use_llm_flag,
        policy_id=pol_id,
        policy_hash=pol_hash,
        legacy_implementation_hash=leg_impl_hash,
        modernized_implementation_hash=mod_impl_hash,
        oracle_set_id=oracle_set.oracle_set_id,
        oracle_set_hash=oracle_set.oracle_set_hash,
        idempotency_key=request.idempotency_key,
        project_id=proj_id,
    )

    if context:
        context.request_identity = request_identity
        context.idempotency_key = request.idempotency_key
        context.is_forced_recompute = request.force_recompute

    # 4. Deterministic Idempotency / Duplicate Request Protection & Conflict Detection
    if not request.force_recompute:
        if request.idempotency_key:
            cached_data, cached_status = idempotency_manager.check_or_reserve(
                project_id=proj_id,
                endpoint="/api/v1/certification/run",
                idempotency_key=request.idempotency_key,
                request_payload=request,
            )
            if cached_data is not None:
                if cached_status and cached_status != 200:
                    return JSONResponse(status_code=cached_status, content=cached_data)
                return cached_data


        existing_artifact = certification_repository.get_by_request_identity(request_identity, project_id=proj_id)
        if existing_artifact is None:
            existing_artifact = certification_repository.find_idempotent_artifact(
                request_identity=request_identity,
                project_id=proj_id,
                benchmark_id=request.benchmark_id,
                evaluation_mode=e_mode,

                target_variant=t_variant,
                dataset_checksum=d_checksum,
                oracle_set_hash=oracle_set.oracle_set_hash,
                legacy_implementation_hash=leg_impl_hash,
                modernized_implementation_hash=mod_impl_hash,
                policy_id=pol_id,
                preferred_provider=p_prov,
                idempotency_key=request.idempotency_key,
            )
        if existing_artifact is not None:
            logger.info(
                f"Returning existing completed artifact '{existing_artifact.certification_id}' "
                f"for deterministic request identity '{request_identity[:16]}...'."
            )
            # Register idempotent job record
            job = certification_job_tracker.create_job(
                project_id=proj_id,
                benchmark_id=request.benchmark_id,
                evaluation_mode=e_mode,
                target_variant=t_variant,
                provider=p_prov,
            )
            certification_job_tracker.update_state(
                job_id=job.job_id,
                state=JobState.QUEUED,
                current_step="Job queued — checking idempotency cache",
            )
            certification_job_tracker.update_state(
                job_id=job.job_id,
                state=JobState.COMPLETED,
                current_step="Completed via deterministic idempotency cache (result reused, engine not re-executed)",
                certification_id=existing_artifact.certification_id,
                certification_status=existing_artifact.status.value,
                equivalence_score=existing_artifact.score,
            )
            if request.idempotency_key:
                idempotency_manager.record_completed(
                    project_id=proj_id,
                    endpoint="/api/v1/certification/run",
                    idempotency_key=request.idempotency_key,
                    request_payload=request,
                    response_data=existing_artifact.model_dump(mode="json"),
                    status_code=200,
                )
            return existing_artifact.model_dump(mode="json")
    else:
        logger.info(
            f"Force recompute requested (force_recompute=True) for benchmark '{request.benchmark_id or proj_id}'. "
            f"Bypassing cache reuse and executing fresh certification run."
        )

    # 5. Workload Protection & Job Lifecycle Tracking
    workload_protector.acquire_job_slot(project_id=proj_id)
    job = certification_job_tracker.create_job(
        project_id=proj_id,
        benchmark_id=request.benchmark_id,
        evaluation_mode=e_mode,
        target_variant=t_variant,
        provider=p_prov,
    )
    # QUEUED: job has been accepted and is about to start processing
    certification_job_tracker.update_state(job.job_id, JobState.QUEUED, "Job queued for execution")
    # VALIDATING: request parameters, adapter resolution, and oracle set already validated above
    certification_job_tracker.update_state(job.job_id, JobState.VALIDATING, "Request and adapter validation complete")
    # PREFLIGHT: policy, identity, and configuration pre-checks done
    certification_job_tracker.update_state(job.job_id, JobState.PREFLIGHT, "Pre-flight configuration and policy checks complete")
    # RUNNING: executing the deterministic CertificationEngine
    certification_job_tracker.update_state(job.job_id, JobState.RUNNING, "Executing dual-probe behavioral certification")

    import time
    start_time = time.perf_counter()
    try:
        artifact = certification_engine.certify(
            project_id=proj_id,
            legacy_adapter=legacy_adp,
            modern_adapter=modern_adp,
            oracle_set=oracle_set,
            policy=request.policy,
            test_inputs=test_inputs,
            field_bounds=field_bounds,
            context=context,
            n_samples=request.n_samples,
            seed=request.seed,
        )
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        # EVIDENCE_GENERATION: artifact and evidence packages produced by certify()
        certification_job_tracker.update_state(
            job_id=job.job_id,
            state=JobState.EVIDENCE_GENERATION,
            current_step="Evidence packages and certification artifact generated",
            certification_id=artifact.certification_id,
            certification_status=artifact.status.value,
            equivalence_score=artifact.score,
        )
        # PERSISTING: artifact already persisted atomically by CertificationEngine
        certification_job_tracker.update_state(
            job_id=job.job_id,
            state=JobState.PERSISTING,
            current_step="Certification artifact persisted to storage",
        )
        # COMPLETED: lifecycle done
        certification_job_tracker.update_state(
            job_id=job.job_id,
            state=JobState.COMPLETED,
            current_step="Certification completed successfully",
        )
        operational_metrics.record_job_completed(
            project_id=proj_id,
            duration_ms=duration_ms,
            certification_status=artifact.status.value,
            success=True,
        )
        log_operational_event(
            event="certification_completed",
            logger_name="beacon.execution",
            operation="CERTIFICATION",
            step="RESULT",
            certification_run_id=artifact.certification_id,
            benchmark_id=request.benchmark_id or proj_id,
            evaluation_mode=e_mode,
            target_variant=t_variant,
            duration_ms=round(duration_ms, 2),
            outcome=artifact.status.value,
            cases=artifact.metrics.certification_case_count,
            regressions=artifact.metrics.regression_case_count,
            matching=artifact.metrics.matching_case_count,
            backend="SQLite",
            message=(
                f"[CERTIFICATION] COMPLETE | run={artifact.certification_id} "
                f"| result={artifact.status.value} | cases={artifact.metrics.certification_case_count} "
                f"| regressions={artifact.metrics.regression_case_count} | duration={duration_ms:.2f}ms"
            ),
        )
        if request.idempotency_key:
            idempotency_manager.record_completed(
                project_id=proj_id,
                endpoint="/api/v1/certification/run",
                idempotency_key=request.idempotency_key,
                request_payload=request,
                response_data=artifact.model_dump(mode="json"),
                status_code=200,
            )
        return artifact.model_dump(mode="json")
    except Exception as exc:
        log_operational_event(
            event="certification_failed",
            level=logging.ERROR,
            logger_name="beacon.execution",
            operation="CERTIFICATION",
            step="REQUEST",
            benchmark_id=request.benchmark_id or proj_id,
            evaluation_mode=e_mode,
            outcome="ABORTED",
            safe_error=str(exc),
            message="[CERTIFICATION] ERROR | execution aborted",
        )
        if request.idempotency_key:
            idempotency_manager.record_failed(
                project_id=proj_id,
                endpoint="/api/v1/certification/run",
                idempotency_key=request.idempotency_key,
                request_payload=request,
                error_message=str(exc),
            )
        certification_job_tracker.update_state(
            job_id=job.job_id,
            state=JobState.FAILED,
            current_step="Execution error during certification",
            error_category="CERTIFICATION_FAILURE",
            error_message=str(exc),
        )
        operational_metrics.record_job_failed(project_id=proj_id, error_category="CERTIFICATION_FAILURE")
        raise
    finally:
        workload_protector.release_job_slot()




@app.get("/api/v1/certification/artifacts")
def list_certification_artifacts(
    project_id: Optional[str] = None,
    benchmark_id: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Lists historical immutable CertificationArtifacts filtered by project or benchmark."""
    artifacts = certification_repository.list_artifacts(project_id=project_id, benchmark_id=benchmark_id, limit=limit)
    return {"artifacts": [a.model_dump(mode="json") for a in artifacts]}


@app.get("/api/v1/certification/{certification_id}")
def get_certification_artifact(
    certification_id: str,
    project_id: Optional[str] = None,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Retrieves a single CertificationArtifact by ID."""
    artifact = certification_repository.get_artifact(certification_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Certificate '{certification_id}' not found.")
    if project_id and artifact.project_id != project_id:
        raise HTTPException(status_code=403, detail="Forbidden: Resource belongs to a different project tenant.")
    return artifact.model_dump(mode="json")


@app.get("/api/v1/certification/{certification_id}/report")
def get_certification_report(
    certification_id: str,
    format: Literal["html", "markdown", "json"] = "html",
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Retrieves a human-readable HTML or Markdown audit report."""
    from fastapi.responses import HTMLResponse, PlainTextResponse

    artifact = certification_repository.get_artifact(certification_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Certificate '{certification_id}' not found.")

    if format == "html":
        html_content = generate_html_report(artifact)
        return HTMLResponse(content=html_content)
    elif format == "markdown":
        md_content = generate_markdown_report(artifact)
        return PlainTextResponse(content=md_content)
    return artifact.model_dump(mode="json")


@app.get("/api/v1/certification/{certification_id}/oracles")
def get_certification_oracles(
    certification_id: str,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Retrieves per-oracle verification summaries for drill-down."""
    artifact = certification_repository.get_artifact(certification_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Certificate '{certification_id}' not found.")
    return {"oracle_summaries": [s.model_dump(mode="json") for s in artifact.oracle_summaries]}


@app.get("/api/v1/certification/{certification_id}/counterexamples")
def get_certification_counterexamples(
    certification_id: str,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Retrieves exact counterexamples / regressions produced by certification."""
    artifact = certification_repository.get_artifact(certification_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Certificate '{certification_id}' not found.")
    return {"counterexamples": [r.model_dump(mode="json") for r in artifact.regressions]}


@app.post("/api/v1/drift/evaluate")
def evaluate_drift_endpoint(
    request: DriftEvaluateRequest,
    current_user: User = Depends(require_project_permission(Permission.CERTIFY)),
):
    """Evaluates a post-migration runtime observation against a frozen OracleSet."""

    oracle_set = registry.get_oracle_set(request.oracle_set_id)
    if oracle_set is None:
        raise HTTPException(
            status_code=404,
            detail=f"Frozen OracleSet '{request.oracle_set_id}' not found in registry.",
        )

    obs = DriftObservation(
        observation_id=request.observation_id,
        environment=request.environment,
        application_version=request.application_version,
        inputs=request.inputs,
        outputs=request.outputs,
    )

    event = evaluate_drift_observation(
        observation=obs,
        oracle_set=oracle_set,
        certification_id=request.certification_id,
    )

    return event.model_dump(mode="json")


@app.get("/api/v1/certification/{certification_id}/cases")
def get_certification_cases(
    certification_id: str,
    limit: int = 100,
    offset: int = 0,
    classification: Optional[str] = None,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Retrieves paginated test cases for a certification run."""
    cases = certification_repository.list_certification_cases(certification_id, limit, offset, classification)
    return {"cases": [c.model_dump(mode="json") for c in cases]}


@app.get("/api/v1/certification/{certification_id}/input_set")
def get_certification_input_set(
    certification_id: str,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Retrieves the full InputSet used by a certification run."""
    artifact = certification_repository.get_artifact(certification_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Certification not found.")
    input_set = certification_repository.get_input_set(artifact.input_set_id)
    if not input_set:
        raise HTTPException(status_code=404, detail="Input set not found.")
    return input_set.model_dump(mode="json")


from fastapi.responses import JSONResponse, Response

@app.get("/api/v1/certification/{certification_id}/export")
def export_certification_dossier(
    certification_id: str,
    format: Literal["json", "markdown", "csv"] = "json",
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Exports a complete, auditable certification dossier in JSON, Markdown, or CSV format with complete context and zero secrets."""
    artifact = certification_repository.get_artifact(certification_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Certification not found.")

    cases = certification_repository.list_cases_for_input_set(artifact.input_set_id, run_id=artifact.certification_id)
    input_set = certification_repository.get_input_set(artifact.input_set_id)
    if not input_set:
        raise HTTPException(status_code=409, detail="Cannot export dossier: Incomplete certification data (InputSet missing).")
    integrity_report = certification_repository.verify_certification_run_integrity(certification_id)


    if format == "json":
        ctx = artifact.context
        b_id = ctx.benchmark_id if ctx else (artifact.benchmark_id or artifact.project_id)
        export_payload = {
            "certification_id": artifact.certification_id,
            "benchmark_id": b_id,
            "artifact_hash": artifact.content_hash,
            "content_hash": artifact.content_hash,
            "legacy_implementation_hash": getattr(artifact, "legacy_implementation_hash", "") or (ctx.legacy_implementation_hash if ctx else ""),
            "modernized_implementation_hash": getattr(artifact, "modernized_implementation_hash", "") or (ctx.modernized_implementation_hash if ctx else ""),
            "input_set_hash": artifact.input_set_hash,
            "oracle_set_hash": artifact.oracle_set_hash,
            "status": artifact.status.value if hasattr(artifact.status, "value") else str(artifact.status),
            "score": artifact.score,
            "context": artifact.context.model_dump(mode="json") if artifact.context else {},
            "metrics": artifact.metrics.model_dump(mode="json"),
            "integrity_verification": integrity_report,
            "oracle_set": {
                "oracle_set_id": artifact.oracle_set_id,
                "oracle_set_hash": artifact.oracle_set_hash,
                "summaries": [s.model_dump(mode="json") for s in artifact.oracle_summaries],
            },
            "policy": {
                "policy_id": artifact.certification_policy_id,
                "policy_hash": artifact.certification_policy_hash,
            },
            "regressions": [r.model_dump(mode="json") for r in artifact.regressions],
            "input_set": input_set.model_dump(mode="json") if input_set else None,
            "cases_sample": [c.model_dump(mode="json") for c in cases[:100]],
        }
        return JSONResponse(
            content=export_payload,
            headers={"Content-Disposition": f"attachment; filename=certification_dossier_{certification_id}.json"}
        )

    elif format == "markdown":
        ctx = artifact.context
        b_id = ctx.benchmark_id if ctx else artifact.benchmark_id or "default"
        b_name = ctx.benchmark_name if ctx else b_id
        prov = ctx.benchmark_provenance if ctx else "CONTROLLED"
        mode = ctx.evaluation_mode if ctx else artifact.evaluation_mode or "CONTROLLED"
        var = ctx.modernization_variant_id if ctx else artifact.modernization_variant or "clean_v2"
        leg_h = getattr(artifact, "legacy_implementation_hash", "") or (ctx.legacy_implementation_hash if ctx else "")
        mod_h = getattr(artifact, "modernized_implementation_hash", "") or (ctx.modernized_implementation_hash if ctx else "")
        data_chk = getattr(artifact, "dataset_checksum", "") or (ctx.dataset_checksum if ctx else "")

        md = f"""# BEACON Behavioral Equivalence Certificate Dossier

## Certificate Identity
- **Certificate ID:** `{artifact.certification_id}`
- **Artifact Content Hash (SHA-256):** `{artifact.content_hash}`
- **Integrity Verification Status:** **`{integrity_report.get('status', 'UNKNOWN')}`**
- **Certification Status:** **`{artifact.status.value if hasattr(artifact.status, 'value') else str(artifact.status)}`**
- **Equivalence Score:** `{artifact.score * 100:.1f}%`

## Execution Context & Cryptographic Fingerprints
- **Benchmark:** `{b_id}` ({b_name})
- **Provenance Category:** `{prov}`
- **Evaluation Mode:** `{mode}` ({ctx.oracle_source_type if ctx else 'CONTROLLED_ORACLE_SET'})
- **Modernization Variant:** `{var}` ({ctx.modernization_provenance if ctx else 'INDEPENDENT_REIMPLEMENTATION'})
- **Legacy Implementation Hash:** `{leg_h}`
- **Modernized Implementation Hash:** `{mod_h}`
- **Dataset Checksum:** `{data_chk}`
- **Input Set ID & Hash:** `{artifact.input_set_id}` (`{artifact.input_set_hash}`)
- **Oracle Set ID & Hash:** `{artifact.oracle_set_id}` (`{artifact.oracle_set_hash}`)
- **Policy ID & Hash:** `{artifact.certification_policy_id}` (`{artifact.certification_policy_hash}`)
- **Execution Timestamp:** `{artifact.timestamp}`

## Disambiguated Metric Breakdown
- **Unique Inputs Evaluated:** `{artifact.metrics.unique_input_count}`
- **Certification Cases Persisted:** `{artifact.metrics.certification_case_count}`
- **Oracle Definitions:** `{artifact.metrics.oracle_count}`
- **Oracle Evaluations Executed:** `{artifact.metrics.oracle_evaluation_count}`
- **Matching Cases:** `{artifact.metrics.matching_case_count}`
- **Regression Cases:** `{artifact.metrics.regression_case_count}`
- **Execution Errors:** `{artifact.metrics.execution_error_count}`
- **Counterexamples Detected:** `{artifact.metrics.counterexample_count}`
- **Oracle Coverage:** `{artifact.metrics.oracle_coverage_pct * 100:.1f}%`

## Behavioral Regressions ({len(artifact.regressions)})
"""
        for r in artifact.regressions:
            md += f"- **Oracle `{r.oracle_id}`** on Input `{r.input_id}` (Hash `{r.input_hash}`): Legacy `{r.legacy_output}` vs Modern `{r.modern_output}`. *{r.details}*\n"

        return Response(
            content=md,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=certification_dossier_{certification_id}.md"}
        )

    elif format == "csv":
        import io, csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["case_id", "case_index", "input_id", "input_hash", "classification", "severity", "oracle_result", "input_json", "legacy_output_json", "modern_output_json"])
        for c in cases:
            writer.writerow([c.case_id, c.case_index, c.input_id, c.input_hash, c.classification, c.severity, c.oracle_result, c.input_json, c.legacy_output_json, c.modern_output_json])
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=certification_cases_{certification_id}.csv"}
        )


@app.post("/api/v1/certification/{certification_id}/verify")
def verify_certification_artifact(
    certification_id: str,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Cryptographically validates complete 8-point integrity of a certification artifact and its inputs."""
    report = certification_repository.verify_certification_run_integrity(certification_id)
    if report.get("status") == "FAIL" and any("not found" in e for e in report.get("errors", [])):
        raise HTTPException(status_code=404, detail=f"Certification artifact '{certification_id}' not found.")
    return report


@app.get("/api/v1/certification/{certification_id}/verify_reproducibility")
def verify_certification_reproducibility(
    certification_id: str,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Backward-compatible endpoint for checking artifact and input-set integrity."""
    return verify_certification_artifact(certification_id, current_user=current_user)


# ==============================================================================
# Phase 14 — User-Supplied Dataset Ingestion & Custom Certification Endpoints
# ==============================================================================

from ingestion import (
    DataFormat,
    DatasetProvenanceCategory,
    DatasetLifecycleStatus,
    DatasetIngestionRequest,
    DatasetPreview,
    DatasetIngestionManifest,
    UserDatasetRecord,
    dataset_validator,
    user_dataset_registry,
    AuditAction,
    AuditEvent,
    audit_logger,
)
from certification.adapter_registry import adapter_registry


class CustomPreflightRequest(BaseModel):
    """Request payload for custom dataset pre-flight validation."""
    project_id: str
    dataset_id: str
    legacy_adapter_id: str
    modernized_adapter_id: str
    oracle_set_id: Optional[str] = None
    evaluation_mode: str = "CONTROLLED"
    preferred_provider: str = "auto"
    allow_external_llm: bool = False
    policy_id: Optional[str] = "POL-DEFAULT"


class CustomCertificationRunRequest(BaseModel):
    """Request payload for certifying custom user-supplied datasets."""
    project_id: str
    dataset_id: str
    legacy_adapter_id: str
    modernized_adapter_id: str
    oracle_set_id: Optional[str] = None
    evaluation_mode: str = "CONTROLLED"
    preferred_provider: str = "auto"
    allow_external_llm: bool = False
    policy: Optional[CertificationPolicy] = None
    idempotency_key: Optional[str] = None
    force_recompute: bool = False
    config_fingerprint: Optional[str] = None


@app.post("/api/v1/custom/datasets/preview", response_model=DatasetPreview)
def preview_custom_dataset(
    request: DatasetIngestionRequest,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Dry-run preview that parses, sanitizes, and extracts schema/checksum without persisting."""
    preview = dataset_validator.create_preview(request)
    audit_logger.log(
        project_id=request.project_id,
        action=AuditAction.DATASET_VALIDATE,
        status="SUCCESS" if preview.validation_passed else "FAIL",
        details={
            "dataset_name": request.dataset_name,
            "format": request.data_format.value,
            "row_count": preview.row_count,
            "validation_passed": preview.validation_passed,
            "errors": preview.errors,
        },
    )
    return preview


@app.post("/api/v1/custom/datasets/upload")
def upload_custom_dataset(
    request: DatasetIngestionRequest,
    current_user: User = Depends(require_project_permission(Permission.CERTIFY)),
):
    """Authoritatively validates, canonicalizes, registers, and manifests a user-supplied dataset."""
    raw_bytes_len = len(request.raw_content.encode("utf-8")) if isinstance(request.raw_content, str) else 0
    workload_protector.validate_dataset_upload(raw_bytes_len)

    try:
        manifest, records, test_inputs = dataset_validator.validate_for_ingestion(request)
    except ResourceLimitError as rle:
        operational_metrics.record_ingestion_failure()
        audit_logger.log(
            project_id=request.project_id,
            action=AuditAction.DATASET_UPLOAD,
            status="FAIL",
            details={"dataset_name": request.dataset_name, "error": str(rle)},
        )
        raise
    except ValueError as ve:
        operational_metrics.record_ingestion_failure()
        audit_logger.log(
            project_id=request.project_id,
            action=AuditAction.DATASET_UPLOAD,
            status="FAIL",
            details={"dataset_name": request.dataset_name, "error": str(ve)},
        )
        raise HTTPException(status_code=400, detail=str(ve))

    user_record = user_dataset_registry.register_dataset(manifest, records, test_inputs)
    return user_record.manifest.model_dump(mode="json")


@app.get("/api/v1/custom/datasets")
def list_custom_datasets(
    project_id: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Lists registered custom dataset manifests with project namespace isolation."""
    manifests = user_dataset_registry.list_datasets(project_id=project_id, limit=limit)
    return {"datasets": [m.model_dump(mode="json") for m in manifests]}


@app.get("/api/v1/custom/datasets/{dataset_id}")
def get_custom_dataset(
    dataset_id: str,
    project_id: Optional[str] = None,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Retrieves metadata only for a single custom dataset manifest without exposing raw/stored data."""
    manifest = user_dataset_registry.get_manifest(dataset_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Custom dataset '{dataset_id}' not found.")
    if project_id and manifest.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"Custom dataset '{dataset_id}' not found in project '{project_id}'.")
    return {
        "manifest": manifest.model_dump(mode="json"),
        "dataset_id": manifest.dataset_id,
        "project_id": manifest.project_id,
        "dataset_name": manifest.dataset_name,
        "version": manifest.version,
        "data_format": manifest.data_format,
        "declared_provenance": manifest.declared_provenance.value if hasattr(manifest.declared_provenance, "value") else str(manifest.declared_provenance),
        "source_reference": manifest.source_reference,
        "target_domain": manifest.target_domain,
        "checksum": manifest.checksum,
        "schema_fingerprint": manifest.schema_fingerprint,
        "input_set_hash": manifest.input_set_hash,
        "inferred_schema": manifest.inferred_schema,
        "row_count": manifest.row_count,
        "status": manifest.status.value if hasattr(manifest.status, "value") else str(manifest.status),
        "lifecycle_status": manifest.status.value if hasattr(manifest.status, "value") else str(manifest.status),
        "created_at": manifest.created_at,
        "updated_at": manifest.created_at,
    }


@app.delete("/api/v1/custom/datasets/{dataset_id}")
def delete_custom_dataset(
    dataset_id: str,
    project_id: Optional[str] = None,
    current_user: User = Depends(require_project_permission(Permission.MANAGE_PROJECT)),
):
    """Deletes a custom dataset and its stored records."""
    if project_id:
        manifest = user_dataset_registry.get_manifest(dataset_id)
        if not manifest or manifest.project_id != project_id:
            raise HTTPException(status_code=404, detail=f"Custom dataset '{dataset_id}' not found in project '{project_id}'.")

    deleted = user_dataset_registry.delete_dataset(dataset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Custom dataset '{dataset_id}' not found.")
    return {"deleted": True, "dataset_id": dataset_id}


@app.get("/api/v1/custom/adapters")
def list_custom_adapters():
    """Lists registered, allowlisted implementation adapters for custom certification."""
    return {"adapters": adapter_registry.list_adapters()}


def get_oracle_required_variables(oracle: Any) -> set[str]:
    """Extracts required input variable names from an OracleDefinition."""
    vars_set = set()
    if hasattr(oracle, "input_schema") and oracle.input_schema and hasattr(oracle.input_schema, "variables"):
        for v in oracle.input_schema.variables:
            vars_set.add(v.name)
    if hasattr(oracle, "inputs") and oracle.inputs:
        vars_set.update(oracle.inputs)
    def _extract_from_node(node):
        if hasattr(node, "variable") and node.variable:
            vars_set.add(node.variable)
        if hasattr(node, "left_var") and node.left_var:
            vars_set.add(node.left_var)
        if hasattr(node, "conditions") and node.conditions:
            for c in node.conditions:
                _extract_from_node(c)
        if hasattr(node, "operand") and node.operand:
            _extract_from_node(node.operand)
    if hasattr(oracle, "condition") and oracle.condition:
        _extract_from_node(oracle.condition)
    if hasattr(oracle, "expression") and hasattr(oracle.expression, "condition"):
        _extract_from_node(oracle.expression.condition)
    return vars_set


def check_oracle_set_compatibility(orc_set: Any, inferred_schema: dict[str, str]) -> tuple[bool, list[str]]:
    """Checks if an OracleSet's required condition variables exist in the dataset schema."""
    required = set()
    for o in getattr(orc_set, "oracles", []):
        required.update(get_oracle_required_variables(o))
    missing = [v for v in sorted(required) if v not in inferred_schema]
    return len(missing) == 0, missing


def resolve_oracle_set(
    oracle_set_id: str,
    mode: str = "CONTROLLED",
    preferred_provider: str = "offline",
    allow_external_llm: bool = False,
) -> Optional[Any]:
    """Resolves an OracleSet by its explicit ID from oracle_registry or benchmark_registry."""
    if not oracle_set_id:
        return None
    from oracle.registry import registry as oracle_reg
    orc_set = oracle_reg.get_oracle_set(oracle_set_id)
    if orc_set is not None:
        return orc_set

    # Check if oracle_set_id maps to a benchmark specification
    bench_map = {
        # Human-friendly aliases
        "SET-RETAIL-CONTROLLED-v1": "retail_discount_pricing",
        "SET-LOAN-CONTROLLED-v1": "loan_approval",
        "SET-PAYROLL-CONTROLLED-v1": "payroll_tax",
        "SET-MEDICAL-CONTROLLED-v1": "medical_triage",
        # Direct benchmark IDs
        "retail_discount_pricing": "retail_discount_pricing",
        "loan_approval": "loan_approval",
        "payroll_tax": "payroll_tax",
        "medical_triage": "medical_triage",
        # Actual generated IDs from benchmark_registry.resolve_controlled_oracle_set()
        "SET-RETAIL_DISCOUNT_PRICING-CONTROLLED": "retail_discount_pricing",
        "SET-LOAN_DEMO-CONTROLLED": "loan_demo",
        "SET-LOAN_APPROVAL-CONTROLLED": "loan_approval",
        "SET-MEDICAL_TRIAGE-CONTROLLED": "medical_triage",
        "SET-PAYROLL_TAX-CONTROLLED": "payroll_tax",
    }
    bench_id = bench_map.get(oracle_set_id)
    if bench_id:
        try:
            use_llm = (mode.upper() == "FULL_BEACON" and allow_external_llm)
            orc_set = benchmark_registry.get_or_create_oracle_set(
                bench_id,
                mode=mode,
                preferred_provider=preferred_provider,
                use_llm=use_llm,
            )
            if orc_set:
                oracle_reg.register_oracle_set(orc_set)
                return orc_set
        except Exception:
            pass
    return None


def discover_custom_oracle_set(
    legacy_adapter_id: str,
    inferred_schema: dict[str, str],
    preferred_provider: str = "offline",
    allow_external_llm: bool = False,
) -> tuple[Optional[OracleSet], list[str]]:
    """Uses the existing evidence/discovery -> validation/grounding pipeline to obtain a compatible OracleSet.
    If no compatible validated OracleSet can be established, returns (None, reasons).
    """
    bench_map = {
        "retail_discount_legacy": "retail_discount_pricing",
        "retail_pricing_legacy": "retail_discount_pricing",
        "loan_approval_legacy": "loan_demo",
        "loan_legacy": "loan_demo",
        "payroll_tax_legacy": "payroll_tax_calculator",
        "payroll_legacy": "payroll_tax_calculator",
        "medical_triage_legacy": "medical_triage",
    }
    bench_id = bench_map.get(legacy_adapter_id)
    if not bench_id:
        return None, [f"No registered discovery pipeline for legacy adapter '{legacy_adapter_id}'."]

    try:
        use_llm = bool(allow_external_llm and preferred_provider in ("openrouter", "anthropic"))
        candidate_orc_set = benchmark_registry.get_or_create_oracle_set(
            bench_id,
            mode="FULL_BEACON",
            preferred_provider=preferred_provider,
            use_llm=use_llm,
        )
        if not candidate_orc_set or not candidate_orc_set.oracles:
            return None, [f"Discovery pipeline produced 0 validated oracles for benchmark '{bench_id}'."]

        is_compat, missing_vars = check_oracle_set_compatibility(candidate_orc_set, inferred_schema)
        if not is_compat:
            return None, [
                f"Discovered OracleSet '{candidate_orc_set.oracle_set_id}' requires schema fields {missing_vars} "
                f"which are absent in dataset schema ({list(inferred_schema.keys())})."
            ]

        return candidate_orc_set, []
    except Exception as e:
        logger.warning(f"Error in FULL_BEACON custom oracle discovery: {e}")
        return None, [f"FULL_BEACON oracle discovery failed: {str(e)}"]


@app.get("/api/v1/custom/oracle-sets")
def list_custom_oracle_sets(domain: Optional[str] = None):
    """Lists registered, frozen OracleSets available for explicit custom certification binding."""
    from oracle.registry import registry as oracle_reg
    sets = oracle_reg.list_oracle_sets(domain=domain)
    if not sets:
        for bid in ["retail_discount_pricing", "loan_approval", "payroll_tax", "medical_triage"]:
            try:
                s = benchmark_registry.get_or_create_oracle_set(bid, mode="CONTROLLED")
                if s:
                    oracle_reg.register_oracle_set(s)
            except Exception:
                pass
        sets = oracle_reg.list_oracle_sets(domain=domain)

    return {
        "oracle_sets": [
            {
                "oracle_set_id": s.oracle_set_id,
                "name": s.name,
                "domain": s.domain,
                "version": s.version,
                "oracle_count": len(s.oracles),
                "oracle_set_hash": s.oracle_set_hash,
            }
            for s in sets
        ]
    }


def compute_custom_config_fingerprint(
    project_id: str,
    dataset_id: str,
    dataset_checksum: str,
    input_set_hash: str,
    legacy_adapter_id: str,
    legacy_hash: str,
    modernized_adapter_id: str,
    modern_hash: str,
    oracle_set_id: str,
    oracle_set_hash: str,
    policy_id: str,
    policy_hash: str,
    evaluation_mode: str,
    preferred_provider: str,
    allow_external_llm: bool,
) -> str:
    """Computes deterministic SHA-256 fingerprint of the full certification configuration.
    Never includes secrets, API keys, volatile timestamps, or random values.
    """
    fingerprint_dict = {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "dataset_checksum": dataset_checksum,
        "input_set_hash": input_set_hash,
        "legacy_adapter_id": legacy_adapter_id,
        "legacy_hash": legacy_hash,
        "modernized_adapter_id": modernized_adapter_id,
        "modern_hash": modern_hash,
        "oracle_set_id": oracle_set_id,
        "oracle_set_hash": oracle_set_hash,
        "policy_id": policy_id,
        "policy_hash": policy_hash,
        "evaluation_mode": evaluation_mode.upper(),
        "preferred_provider": preferred_provider.lower().strip(),
        "allow_external_llm": bool(allow_external_llm),
    }
    raw_fp = json.dumps(fingerprint_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw_fp.encode("utf-8")).hexdigest()


@app.post("/api/v1/custom/validate")
@app.post("/api/v1/custom/preflight")
def validate_custom_certification(
    req: CustomPreflightRequest,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Performs authoritative pre-flight validation on user dataset, schema, allowlisted adapters,
    explicit OracleSet binding, compatibility, policy, and privacy boundaries.
    """
    import time
    start_time = time.perf_counter()
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Dataset Verification
    record = user_dataset_registry.get_dataset(req.dataset_id)
    if not record:
        errors.append(f"Custom dataset '{req.dataset_id}' not found in registry.")
        return BenchmarkValidationResult(
            is_valid=False,
            benchmark_id="custom",
            benchmark_version="1.0.0",
            declared_dataset_checksum="",
            verified_dataset_checksum="",
            dataset_checksum_valid=False,
            total_input_count=0,
            legacy_adapter_status="NOT_FOUND",
            modernized_adapter_status="NOT_FOUND",
            oracle_set_id=req.oracle_set_id or "",
            oracle_set_hash="",
            policy_id=req.policy_id or "POL-DEFAULT",
            policy_hash="",
            config_fingerprint="",
            errors=errors,
            warnings=warnings,
        )

    if record.project_id != req.project_id:
        errors.append(f"Project namespace isolation mismatch: Dataset belongs to '{record.project_id}', not '{req.project_id}'.")

    manifest = record.manifest
    test_inputs = user_dataset_registry.get_test_inputs(req.dataset_id)
    if not test_inputs:
        errors.append("Dataset contains 0 executable input probe records.")

    # 2. Allowlisted Adapter Resolution
    leg_adp = adapter_registry.get_adapter(req.legacy_adapter_id)
    mod_adp = adapter_registry.get_adapter(req.modernized_adapter_id)
    if not leg_adp or not mod_adp:
        try:
            from benchmarks.registry import benchmark_registry
            benchmark_registry.refresh()
            leg_adp = adapter_registry.get_adapter(req.legacy_adapter_id)
            mod_adp = adapter_registry.get_adapter(req.modernized_adapter_id)
        except Exception:
            pass

    leg_status = "READY" if leg_adp else "NOT_FOUND"
    mod_status = "READY" if mod_adp else "NOT_FOUND"

    if not leg_adp:
        errors.append(f"Unsupported legacy implementation adapter '{req.legacy_adapter_id}'. Only registered adapters are permitted.")
    if not mod_adp:
        errors.append(f"Unsupported modernized implementation adapter '{req.modernized_adapter_id}'. Only registered adapters are permitted.")

    # 3. Dry-run sample evaluation
    if leg_adp and mod_adp and test_inputs:
        sample_inp = test_inputs[0].values
        try:
            leg_out = leg_adp.execute(sample_inp)
        except Exception as exc:
            errors.append(f"Legacy adapter failed on sample dataset record: {str(exc)}")
        try:
            mod_out = mod_adp.execute(sample_inp)
        except Exception as exc:
            errors.append(f"Modernized adapter failed on sample dataset record: {str(exc)}")

    # 4. Explicit OracleSet Binding & Compatibility Verification (NO STRING-BASED GUESSING)
    mode = req.evaluation_mode.upper()
    orc_set = None
    orc_set_id = req.oracle_set_id or ""
    orc_set_hash = ""

    if mode == "CONTROLLED":
        if not orc_set_id:
            errors.append("Explicit 'oracle_set_id' is required for CONTROLLED mode custom certification.")
        else:
            orc_set = resolve_oracle_set(orc_set_id, mode="CONTROLLED")
            if not orc_set:
                errors.append(f"OracleSet '{orc_set_id}' not found in registry.")
            else:
                orc_set_hash = orc_set.oracle_set_hash
                is_compat, missing_vars = check_oracle_set_compatibility(orc_set, manifest.inferred_schema)
                if not is_compat:
                    errors.append(
                        f"OracleSet '{orc_set_id}' requires schema fields {missing_vars} which are absent in dataset '{req.dataset_id}'."
                    )
    elif mode == "FULL_BEACON":
        # Privacy boundary check
        prov_norm = req.preferred_provider.lower().strip()
        if prov_norm in ("openrouter", "anthropic") and not req.allow_external_llm:
            errors.append(
                f"Privacy boundary violation: External cloud provider '{prov_norm}' selected without explicit user consent (allow_external_llm=False). "
                "User data cannot leave local environment. Enable consent or select local/offline provider."
            )
        actual_provider = prov_norm if req.allow_external_llm else "offline"
        if orc_set_id:
            orc_set = resolve_oracle_set(
                orc_set_id,
                mode="FULL_BEACON",
                preferred_provider=actual_provider,
                allow_external_llm=req.allow_external_llm,
            )
            if not orc_set:
                errors.append(f"OracleSet '{orc_set_id}' not found in registry.")
            else:
                orc_set_hash = orc_set.oracle_set_hash
                is_compat, missing_vars = check_oracle_set_compatibility(orc_set, manifest.inferred_schema)
                if not is_compat:
                    errors.append(
                        f"OracleSet '{orc_set_id}' requires schema fields {missing_vars} which are absent in dataset '{req.dataset_id}'."
                    )
        else:
            # NO UNCONDITIONAL FALLBACK TO RETAIL.
            # Use existing evidence/discovery -> validation/grounding pipeline to obtain a compatible OracleSet.
            disc_orc_set, disc_reasons = discover_custom_oracle_set(
                legacy_adapter_id=req.legacy_adapter_id,
                inferred_schema=manifest.inferred_schema,
                preferred_provider=actual_provider,
                allow_external_llm=req.allow_external_llm,
            )
            if disc_orc_set:
                orc_set = disc_orc_set
                orc_set_hash = disc_orc_set.oracle_set_hash
            else:
                # No compatible validated OracleSet could be established.
                # Rather than silently using Retail, construct empty OracleSet and emit warning.
                orc_set = OracleSet(
                    oracle_set_id="SET-EMPTY",
                    name="Empty Discovered OracleSet",
                    domain="Custom",
                    oracle_ids=[],
                    oracles=[],
                    oracle_set_hash="",
                )
                orc_set_hash = ""
                warnings.append(
                    "No compatible validated OracleSet could be established for dataset schema. "
                    "Certification status will be INSUFFICIENT_COVERAGE. " + " ".join(disc_reasons)
                )

    # 5. Compute Deterministic Configuration Fingerprint
    leg_hash = getattr(leg_adp, "implementation_hash", "") or (hashlib.sha256(req.legacy_adapter_id.encode()).hexdigest() if leg_adp else "")
    mod_hash = getattr(mod_adp, "implementation_hash", "") or (hashlib.sha256(req.modernized_adapter_id.encode()).hexdigest() if mod_adp else "")
    policy = CertificationPolicy(policy_id=req.policy_id or "POL-DEFAULT", min_equivalence_score=0.80, min_oracle_coverage=0.0)
    pol_id = policy.policy_id
    pol_hash = policy.compute_hash()

    final_orc_set_id = orc_set.oracle_set_id if orc_set else (orc_set_id or "SET-NONE")

    config_fingerprint = compute_custom_config_fingerprint(
        project_id=req.project_id,
        dataset_id=req.dataset_id,
        dataset_checksum=manifest.checksum,
        input_set_hash=manifest.input_set_hash,
        legacy_adapter_id=req.legacy_adapter_id,
        legacy_hash=leg_hash,
        modernized_adapter_id=req.modernized_adapter_id,
        modern_hash=mod_hash,
        oracle_set_id=final_orc_set_id,
        oracle_set_hash=orc_set_hash,
        policy_id=pol_id,
        policy_hash=pol_hash,
        evaluation_mode=mode,
        preferred_provider=req.preferred_provider,
        allow_external_llm=req.allow_external_llm,
    )

    is_valid = len(errors) == 0

    duration_ms = (time.perf_counter() - start_time) * 1000.0
    operational_metrics.record_preflight_event(duration_ms=duration_ms, success=is_valid)

    return BenchmarkValidationResult(
        is_valid=is_valid,
        benchmark_id="custom",
        benchmark_version="1.0.0",
        declared_dataset_checksum=manifest.checksum,
        verified_dataset_checksum=manifest.checksum,
        dataset_checksum_valid=True,
        total_input_count=len(test_inputs),
        legacy_adapter_status=leg_status,
        modernized_adapter_status=mod_status,
        oracle_set_id=final_orc_set_id,
        oracle_set_hash=orc_set_hash,
        policy_id=pol_id,
        policy_hash=pol_hash,
        config_fingerprint=config_fingerprint,
        errors=errors,
        warnings=warnings,
    )


@app.post("/api/v1/custom/certify")
def run_custom_certification(
    req: CustomCertificationRunRequest,
    current_user: User = Depends(require_project_permission(Permission.CERTIFY)),
):
    """Certifies custom user-supplied dataset using the authoritative deterministic CertificationEngine.
    Enforces authoritative configuration fingerprint match against pre-flight, explicit OracleSet binding,
    and privacy boundaries.
    """
    log_operational_event(
        event="custom_certification_started",
        logger_name="beacon.execution",
        operation="CUSTOM_CERTIFICATION",
        step="REQUEST",
        dataset_id=req.dataset_id,
        evaluation_mode=req.evaluation_mode,
        target_variant=req.modernized_adapter_id,
        provider=req.preferred_provider,
        message=f"[CUSTOM CERTIFICATION] START | dataset={req.dataset_id} | mode={req.evaluation_mode}",
    )
    record = user_dataset_registry.get_dataset(req.dataset_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Custom dataset '{req.dataset_id}' not found.")

    if record.project_id != req.project_id:
        raise HTTPException(
            status_code=400,
            detail=f"Project namespace isolation mismatch: Dataset belongs to '{record.project_id}', not '{req.project_id}'.",
        )

    manifest = record.manifest
    test_inputs = user_dataset_registry.get_test_inputs(req.dataset_id)
    if not test_inputs:
        raise HTTPException(status_code=400, detail="Dataset contains no executable test inputs.")

    leg_adp = adapter_registry.get_adapter(req.legacy_adapter_id)
    mod_adp = adapter_registry.get_adapter(req.modernized_adapter_id)
    if not leg_adp or not mod_adp:
        try:
            from benchmarks.registry import benchmark_registry
            benchmark_registry.refresh()
            leg_adp = adapter_registry.get_adapter(req.legacy_adapter_id)
            mod_adp = adapter_registry.get_adapter(req.modernized_adapter_id)
        except Exception:
            pass
    if not leg_adp:
        raise HTTPException(status_code=400, detail=f"Unsupported legacy implementation adapter '{req.legacy_adapter_id}'.")
    if not mod_adp:
        raise HTTPException(status_code=400, detail=f"Unsupported modernized implementation adapter '{req.modernized_adapter_id}'.")

    # Mode & Privacy boundary
    mode = req.evaluation_mode.upper()
    prov_norm = req.preferred_provider.lower().strip()
    if prov_norm in ("openrouter", "anthropic") and not req.allow_external_llm:
        raise HTTPException(
            status_code=403,
            detail="Privacy violation: Cloud LLM requested without explicit user consent (allow_external_llm=False).",
        )

    actual_provider = prov_norm if req.allow_external_llm else "offline"

    # Explicit OracleSet Resolution & Validation (NO STRING-BASED GUESSING)
    orc_set_id = req.oracle_set_id or ""
    if mode == "CONTROLLED":
        if not orc_set_id:
            raise HTTPException(status_code=400, detail="Explicit 'oracle_set_id' is required for CONTROLLED mode custom certification.")
        orc_set = resolve_oracle_set(orc_set_id, mode="CONTROLLED")
        if not orc_set:
            raise HTTPException(status_code=404, detail=f"OracleSet '{orc_set_id}' not found in registry.")
        
        is_compat, missing_vars = check_oracle_set_compatibility(orc_set, manifest.inferred_schema)
        if not is_compat:
            raise HTTPException(
                status_code=400,
                detail=f"OracleSet '{orc_set_id}' is incompatible with dataset schema: missing fields {missing_vars}.",
            )
    else:  # FULL_BEACON
        if orc_set_id:
            orc_set = resolve_oracle_set(
                orc_set_id,
                mode="FULL_BEACON",
                preferred_provider=actual_provider,
                allow_external_llm=req.allow_external_llm,
            )
            if not orc_set:
                raise HTTPException(status_code=404, detail=f"OracleSet '{orc_set_id}' not found in registry.")
            is_compat, missing_vars = check_oracle_set_compatibility(orc_set, manifest.inferred_schema)
            if not is_compat:
                raise HTTPException(
                    status_code=400,
                    detail=f"OracleSet '{orc_set_id}' is incompatible with dataset schema: missing fields {missing_vars}.",
                )
        else:
            # NO UNCONDITIONAL FALLBACK TO RETAIL.
            disc_orc_set, disc_reasons = discover_custom_oracle_set(
                legacy_adapter_id=req.legacy_adapter_id,
                inferred_schema=manifest.inferred_schema,
                preferred_provider=actual_provider,
                allow_external_llm=req.allow_external_llm,
            )
            if disc_orc_set:
                orc_set = disc_orc_set
            else:
                # No compatible validated OracleSet could be established.
                # Rather than silently using Retail or failing, construct empty OracleSet so CertificationEngine
                # yields an authoritative INSUFFICIENT_COVERAGE outcome.
                orc_set = OracleSet(
                    oracle_set_id="SET-EMPTY",
                    name="Empty Discovered OracleSet",
                    domain="Custom",
                    oracle_ids=[],
                    oracles=[],
                    oracle_set_hash="",
                )

    orc_set_hash = orc_set.oracle_set_hash if orc_set else ""

    # Policy
    policy = req.policy or CertificationPolicy(policy_id="POL-DEFAULT", min_equivalence_score=0.80, min_oracle_coverage=0.0)
    policy_hash = policy.compute_hash()

    leg_hash = getattr(leg_adp, "implementation_hash", "") or hashlib.sha256(req.legacy_adapter_id.encode()).hexdigest()
    mod_hash = getattr(mod_adp, "implementation_hash", "") or hashlib.sha256(req.modernized_adapter_id.encode()).hexdigest()

    final_orc_set_id = orc_set.oracle_set_id if orc_set else (orc_set_id or "SET-NONE")

    # Authoritative Backend Configuration Fingerprint Calculation & Enforcement
    expected_fingerprint = compute_custom_config_fingerprint(
        project_id=req.project_id,
        dataset_id=req.dataset_id,
        dataset_checksum=manifest.checksum,
        input_set_hash=manifest.input_set_hash,
        legacy_adapter_id=req.legacy_adapter_id,
        legacy_hash=leg_hash,
        modernized_adapter_id=req.modernized_adapter_id,
        modern_hash=mod_hash,
        oracle_set_id=final_orc_set_id,
        oracle_set_hash=orc_set_hash,
        policy_id=policy.policy_id,
        policy_hash=policy_hash,
        evaluation_mode=mode,
        preferred_provider=req.preferred_provider,
        allow_external_llm=req.allow_external_llm,
    )

    if not req.config_fingerprint or req.config_fingerprint.strip() != expected_fingerprint:
        logger.warning(
            f"Custom certification pre-flight fingerprint mismatch: "
            f"received='{req.config_fingerprint}', expected='{expected_fingerprint}'"
        )
        raise HTTPException(
            status_code=409,
            detail="Custom certification pre-flight is stale. Run pre-flight again.",
        )

    # 16-field Deterministic Request Identity
    request_identity = compute_certification_request_identity(
        benchmark_id=req.project_id,
        benchmark_version="1.0.0",
        dataset_name=manifest.dataset_name,
        dataset_checksum=manifest.checksum,
        discovery_mode=req.evaluation_mode,
        target_variant=req.modernized_adapter_id,
        preferred_provider=actual_provider,
        use_llm=(mode == "FULL_BEACON" and req.allow_external_llm),
        policy_id=policy.policy_id,
        policy_hash=policy_hash,
        legacy_implementation_hash=leg_hash,
        modernized_implementation_hash=mod_hash,
        oracle_set_id=orc_set.oracle_set_id,
        oracle_set_hash=orc_set_hash,
        input_set_hash=manifest.input_set_hash,
        idempotency_key=req.idempotency_key,
    )

    # Idempotency lookup & conflict detection
    if not req.force_recompute:
        if req.idempotency_key:
            cached_data, cached_status = idempotency_manager.check_or_reserve(
                project_id=req.project_id,
                endpoint="/api/v1/certification/run-custom",
                idempotency_key=req.idempotency_key,
                request_payload=req,
            )
            if cached_data is not None:
                if cached_status and cached_status != 200:
                    return JSONResponse(status_code=cached_status, content=cached_data)
                return cached_data


        existing_artifact = certification_repository.get_by_request_identity(request_identity)
        if existing_artifact is not None:
            logger.info(
                f"Returning existing completed custom artifact '{existing_artifact.certification_id}' "
                f"for request identity '{request_identity[:16]}...'."
            )
            job = certification_job_tracker.create_job(
                project_id=req.project_id,
                dataset_id=req.dataset_id,
                evaluation_mode=req.evaluation_mode,
                target_variant=req.modernized_adapter_id,
                provider=actual_provider,
            )
            certification_job_tracker.update_state(
                job_id=job.job_id,
                state=JobState.COMPLETED,
                current_step="Completed via deterministic idempotency cache",
                certification_id=existing_artifact.certification_id,
                certification_status=existing_artifact.status.value,
                equivalence_score=existing_artifact.score,
            )
            audit_logger.log(
                project_id=req.project_id,
                action=AuditAction.CERTIFICATION_COMPLETE,
                status="SUCCESS",
                dataset_id=req.dataset_id,
                certification_id=existing_artifact.certification_id,
                details={"reuse": True, "request_identity": request_identity},
            )
            if req.idempotency_key:
                idempotency_manager.record_completed(
                    project_id=req.project_id,
                    endpoint="/api/v1/certification/run-custom",
                    idempotency_key=req.idempotency_key,
                    request_payload=req,
                    response_data=existing_artifact.model_dump(mode="json"),
                    status_code=200,
                )
            return existing_artifact.model_dump(mode="json")


    # Workload Protection & Concurrency Limits
    workload_protector.validate_certification_records(len(test_inputs), project_id=req.project_id)
    workload_protector.acquire_job_slot(project_id=req.project_id)

    job = certification_job_tracker.create_job(
        project_id=req.project_id,
        dataset_id=req.dataset_id,
        evaluation_mode=req.evaluation_mode,
        target_variant=req.modernized_adapter_id,
        provider=actual_provider,
    )
    # QUEUED: job accepted, about to start
    certification_job_tracker.update_state(job.job_id, JobState.QUEUED, "Job queued for execution")
    # VALIDATING: dataset, adapter, oracle set, privacy boundary already validated above
    certification_job_tracker.update_state(job.job_id, JobState.VALIDATING, "Dataset, adapter, and oracle set validation complete")
    # PREFLIGHT: config fingerprint verification already done above
    certification_job_tracker.update_state(job.job_id, JobState.PREFLIGHT, "Pre-flight configuration fingerprint verified")
    # RUNNING: executing the deterministic CertificationEngine
    certification_job_tracker.update_state(job.job_id, JobState.RUNNING, "Executing custom dataset certification probes")

    audit_logger.log(
        project_id=req.project_id,
        action=AuditAction.CERTIFICATION_START,
        status="INFO",
        dataset_id=req.dataset_id,
        details={
            "dataset_name": manifest.dataset_name,
            "mode": req.evaluation_mode,
            "allow_external_llm": req.allow_external_llm,
            "provider": actual_provider,
        },
    )

    context = CertificationContext(
        benchmark_id=f"custom_{req.project_id}",
        benchmark_version="1.0.0",
        benchmark_name=f"Custom: {manifest.dataset_name}",
        benchmark_domain=manifest.target_domain or "User-Supplied Domain",
        benchmark_provenance=manifest.declared_provenance.value if hasattr(manifest.declared_provenance, "value") else str(manifest.declared_provenance),
        project_id=req.project_id,
        dataset_id=req.dataset_id,
        dataset_name=manifest.dataset_name,
        dataset_version=manifest.version,
        dataset_checksum=manifest.checksum,
        input_set_id=f"INPSET-{manifest.checksum[:8]}",
        input_set_hash=manifest.input_set_hash,
        evaluation_mode=req.evaluation_mode.upper(),
        modernization_variant_id=req.modernized_adapter_id,
        legacy_implementation_hash=leg_hash,
        modernized_implementation_hash=mod_hash,
        policy_id=policy.policy_id,
        policy_hash=policy_hash,
        oracle_set_id=orc_set.oracle_set_id,
        oracle_set_hash=orc_set_hash,
        provider=actual_provider,
        idempotency_key=req.idempotency_key,
        request_identity=request_identity,
        is_forced_recompute=req.force_recompute,
        provider_metadata={
            "allow_external_llm": req.allow_external_llm,
            "dataset_provenance": manifest.declared_provenance.value if hasattr(manifest.declared_provenance, "value") else str(manifest.declared_provenance),
            "schema_fingerprint": manifest.schema_fingerprint,
            "row_count": manifest.row_count,
        },
    )

    import time
    start_time = time.perf_counter()
    try:
        artifact = certification_engine.certify(
            project_id=req.project_id,
            legacy_adapter=leg_adp,
            modern_adapter=mod_adp,
            oracle_set=orc_set,
            policy=policy,
            test_inputs=test_inputs,
            field_bounds={},
            context=context,
            n_samples=len(test_inputs),
        )
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # EVIDENCE_GENERATION: artifact and evidence packages produced by certify()
        certification_job_tracker.update_state(
            job_id=job.job_id,
            state=JobState.EVIDENCE_GENERATION,
            current_step="Evidence packages and certification artifact generated",
            certification_id=artifact.certification_id,
            certification_status=artifact.status.value,
            equivalence_score=artifact.score,
        )
        # PERSISTING: artifact already persisted atomically by CertificationEngine
        certification_job_tracker.update_state(
            job_id=job.job_id,
            state=JobState.PERSISTING,
            current_step="Custom certification artifact persisted to storage",
        )
        # COMPLETED: lifecycle done
        certification_job_tracker.update_state(
            job_id=job.job_id,
            state=JobState.COMPLETED,
            current_step="Custom certification completed successfully",
        )

        operational_metrics.record_job_completed(
            project_id=req.project_id,
            duration_ms=duration_ms,
            certification_status=artifact.status.value,
            success=True,
        )

        audit_logger.log(
            project_id=req.project_id,
            action=AuditAction.CERTIFICATION_COMPLETE,
            status="SUCCESS",
            dataset_id=req.dataset_id,
            certification_id=artifact.certification_id,
            details={
                "status": artifact.status.value if hasattr(artifact.status, "value") else str(artifact.status),
                "score": artifact.score,
                "regressions": len(artifact.regressions),
                "content_hash": artifact.content_hash,
            },
        )
        log_operational_event(
            event="custom_certification_completed",
            logger_name="beacon.execution",
            operation="CUSTOM_CERTIFICATION",
            step="RESULT",
            dataset_id=req.dataset_id,
            certification_run_id=artifact.certification_id,
            duration_ms=round(duration_ms, 2),
            outcome=artifact.status.value,
            cases=artifact.metrics.certification_case_count,
            regressions=artifact.metrics.regression_case_count,
            backend="SQLite",
            message=f"[CUSTOM CERTIFICATION] COMPLETE | run={artifact.certification_id} | result={artifact.status.value} | duration={duration_ms:.2f}ms",
        )
        if req.idempotency_key:
            idempotency_manager.record_completed(
                project_id=req.project_id,
                endpoint="/api/v1/certification/run-custom",
                idempotency_key=req.idempotency_key,
                request_payload=req,
                response_data=artifact.model_dump(mode="json"),
                status_code=200,
            )
        return artifact.model_dump(mode="json")


    except Exception as exc:
        if req.idempotency_key:
            idempotency_manager.record_failed(
                project_id=req.project_id,
                endpoint="/api/v1/certification/run-custom",
                idempotency_key=req.idempotency_key,
                request_payload=req,
                error_message=str(exc),
            )
        certification_job_tracker.update_state(
            job_id=job.job_id,
            state=JobState.FAILED,
            current_step=f"Custom certification error: {str(exc)}",
            error_category="CERTIFICATION_FAILURE",
            error_message=str(exc),
        )
        operational_metrics.record_job_failed(project_id=req.project_id, error_category="CERTIFICATION_FAILURE")


        audit_logger.log(
            project_id=req.project_id,
            action=AuditAction.CERTIFICATION_FAIL,
            status="FAIL",
            dataset_id=req.dataset_id,
            details={"error": str(exc)},
        )
        raise HTTPException(status_code=500, detail=f"Custom certification failed: {str(exc)}")
    finally:
        workload_protector.release_job_slot()


@app.get("/api/v1/custom/audit")
def list_custom_audit_events(
    project_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(require_project_permission(Permission.AUDIT)),
):
    """Lists audit events for custom dataset ingestion and certification."""
    events = audit_logger.list_events(project_id=project_id, dataset_id=dataset_id, limit=limit)
    return {"events": [e.model_dump(mode="json") for e in events]}


# ==============================================================================
# Phase 15 — Advanced Evidence, Explainability, and Auditability Endpoints
# ==============================================================================

from evidence import (
    build_evidence_dossier,
    generate_structured_explanation,
    build_traceability_graph,
    auditor_notes_store,
    compare_certification_runs,
)


class AuditorNoteCreateRequest(BaseModel):
    """Request payload for creating an isolated human auditor note."""
    content: str
    author: Optional[str] = "Auditor"
    project_id: Optional[str] = None


class RunCompareRequest(BaseModel):
    """Request payload for comparing two certification runs side-by-side."""
    run_id_a: str
    run_id_b: str
    project_id: Optional[str] = None


@app.get("/api/v1/evidence/dossiers/{certification_id}")
def get_evidence_dossier_endpoint(
    certification_id: str,
    project_id: Optional[str] = None,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Retrieves a unified, immutable Evidence Dossier for a specific certification run."""
    try:
        dossier = build_evidence_dossier(certification_id, project_id=project_id)
        return dossier.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.get("/api/v1/evidence/dossiers/{certification_id}/explain")
def explain_certification_endpoint(
    certification_id: str,
    project_id: Optional[str] = None,
    use_llm: bool = False,
    preferred_provider: str = "offline",
    allow_external_llm: bool = False,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Generates an authoritative, structured explanation directly from the Evidence Dossier."""
    try:
        dossier = build_evidence_dossier(certification_id, project_id=project_id)
        explanation = generate_structured_explanation(
            dossier=dossier,
            use_llm=use_llm,
            preferred_provider=preferred_provider,
            allow_external_llm=allow_external_llm,
        )
        return explanation.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.get("/api/v1/evidence/dossiers/{certification_id}/graph")
def get_traceability_graph_endpoint(
    certification_id: str,
    project_id: Optional[str] = None,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Returns a directed traceability graph connecting Dataset -> Input Set -> Implementations
    -> OracleSet -> Evaluations -> Counterexamples -> Policy -> Artifact -> Hash."""
    try:
        dossier = build_evidence_dossier(certification_id, project_id=project_id)
        nodes = build_traceability_graph(dossier)
        return {"nodes": [n.model_dump(mode="json") for n in nodes]}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.get("/api/v1/evidence/dossiers/{certification_id}/timeline")
def get_evidence_timeline_endpoint(
    certification_id: str,
    project_id: Optional[str] = None,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Returns the immutable chronological audit timeline for a certification run."""
    try:
        dossier = build_evidence_dossier(certification_id, project_id=project_id)
        return {"timeline": dossier.audit_timeline}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.post("/api/v1/evidence/verify/{certification_id}")
def verify_evidence_endpoint(
    certification_id: str,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Authoritatively reconstructs cryptographic hashes and verifies artifact integrity."""
    log_operational_event(
        event="integrity_verification_started",
        logger_name="beacon.execution",
        operation="INTEGRITY",
        step="VERIFY_HASHES",
        certification_run_id=certification_id,
        message=f"[INTEGRITY] START | run={certification_id}",
    )
    artifact = certification_repository.get_artifact(certification_id)
    if not artifact:
        raise HTTPException(status_code=404, detail=f"Certification artifact '{certification_id}' not found.")

    report = certification_repository.verify_certification_run_integrity(certification_id)
    if report.get("status") == "FAIL" and any("not found" in e for e in report.get("errors", [])):
        raise HTTPException(status_code=404, detail=f"Certification artifact '{certification_id}' not found.")

    audit_logger.log(
        project_id=artifact.project_id,
        action=AuditAction.INTEGRITY_VERIFY,
        status="SUCCESS" if report.get("status") == "PASS" else "FAIL",
        certification_id=certification_id,
        details={"status": report.get("status"), "reasons": report.get("reasons", [])},
    )
    log_operational_event(
        event="integrity_verification_completed",
        logger_name="beacon.execution",
        operation="INTEGRITY",
        step="VERIFY_HASHES",
        certification_run_id=certification_id,
        outcome=report.get("status", "FAIL"),
        message=f"[INTEGRITY] COMPLETE | run={certification_id} | status={report.get('status', 'FAIL')}",
    )
    return report


@app.post("/api/v1/evidence/dossiers/{certification_id}/notes")
def add_auditor_note_endpoint(
    certification_id: str,
    req: AuditorNoteCreateRequest,
    current_user: User = Depends(require_project_permission(Permission.AUDIT)),
):
    """Appends an isolated human auditor note without altering artifact hashes or certification status."""
    artifact = certification_repository.get_artifact(certification_id)
    if not artifact:
        raise HTTPException(status_code=404, detail=f"Certification artifact '{certification_id}' not found.")
    
    proj_id = req.project_id or artifact.project_id
    if req.project_id and req.project_id != artifact.project_id:
        raise HTTPException(status_code=403, detail=f"Project scope mismatch: Certificate belongs to '{artifact.project_id}'.")

    note = auditor_notes_store.add_note(
        certification_id=certification_id,
        project_id=proj_id,
        content=req.content,
        author=req.author or (current_user.full_name or current_user.username if current_user else "Auditor"),
    )
    return note.model_dump(mode="json")


@app.get("/api/v1/evidence/dossiers/{certification_id}/notes")
def list_auditor_notes_endpoint(
    certification_id: str,
    project_id: Optional[str] = None,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Lists human reviewer notes with project isolation."""
    artifact = certification_repository.get_artifact(certification_id)
    if not artifact:
        raise HTTPException(status_code=404, detail=f"Certification artifact '{certification_id}' not found.")
    
    if project_id and project_id != artifact.project_id:
        raise HTTPException(status_code=403, detail=f"Access denied: Certification belongs to project '{artifact.project_id}'.")

    notes = auditor_notes_store.list_notes(certification_id=certification_id, project_id=artifact.project_id)
    return {"notes": [n.model_dump(mode="json") for n in notes]}


@app.post("/api/v1/evidence/compare")
def compare_runs_endpoint(
    req: RunCompareRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Performs side-by-side differential analysis between two certification runs.
    Server-side resolves both runs and strictly enforces project isolation.
    """
    art_a = certification_repository.get_artifact(req.run_id_a)
    if not art_a:
        raise HTTPException(status_code=404, detail=f"Certification run '{req.run_id_a}' not found.")
    art_b = certification_repository.get_artifact(req.run_id_b)
    if not art_b:
        raise HTTPException(status_code=404, detail=f"Certification run '{req.run_id_b}' not found.")

    # If caller is not a system administrator: strictly enforce project ownership and membership
    if not current_user.is_system_admin:
        if art_a.project_id != art_b.project_id:
            raise HTTPException(
                status_code=403,
                detail=f"Forbidden: Cross-project comparison is prohibited. Run A belongs to '{art_a.project_id}', Run B belongs to '{art_b.project_id}'.",
            )
        memberships = auth_repository.get_user_memberships(current_user.user_id)
        user_has_access = any(
            m.project_id == art_a.project_id
            or m.project_id == f"benchmark_{art_a.project_id}"
            or (art_a.project_id.startswith("benchmark_") and m.project_id == art_a.project_id.replace("benchmark_", ""))
            for m in memberships
        )
        if not user_has_access:
            raise HTTPException(
                status_code=403,
                detail=f"Forbidden: User '{current_user.username}' is not a member of project '{art_a.project_id}'.",
            )

    try:
        comparison = compare_certification_runs(req.run_id_a, req.run_id_b)
        return comparison
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/v1/evidence/dossiers/{certification_id}/export")
def export_evidence_dossier_endpoint(
    certification_id: str,
    format: Literal["json", "markdown", "csv"] = "json",
    project_id: Optional[str] = None,
    current_user: User = Depends(require_project_permission(Permission.VIEW)),
):
    """Exports complete, auditable Evidence Dossier with export audit logging and zero secrets."""
    try:
        dossier = build_evidence_dossier(certification_id, project_id=project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    now_str = datetime.now(timezone.utc).isoformat()
    export_id = f"EXP-{uuid.uuid4().hex[:8]}"

    audit_logger.log(
        project_id=dossier.project_id,
        action=AuditAction.EXPORT,
        status="SUCCESS",
        certification_id=certification_id,
        details={
            "export_id": export_id,
            "format": format,
            "dossier_hash": dossier.dossier_hash,
            "timestamp": now_str,
        },
    )

    if format == "json":
        return JSONResponse(
            content=dossier.model_dump(mode="json"),
            headers={"Content-Disposition": f"attachment; filename=evidence_dossier_{certification_id}.json"}
        )
    elif format == "markdown":
        explanation = generate_structured_explanation(dossier)
        md_text = f"""# BEACON Evidence Dossier Audit Report

- **Dossier ID:** `{dossier.dossier_id}`
- **Certification ID:** `{dossier.certification_id}`
- **Export ID:** `{export_id}`
- **Generated At:** `{now_str}`
- **Dossier Hash:** `{dossier.dossier_hash}`
- **Evidence Completeness:** **`{dossier.completeness.status}`** (Score: {dossier.completeness.completeness_score * 100.0:.1f}%)
- **Cryptographic Verification:** **`{dossier.cryptographic_evidence.integrity_status}`**

---

{explanation.natural_language_explanation}

---

## Complete Cryptographic Receipts
- **Artifact Hash:** `{dossier.cryptographic_evidence.artifact_hash}`
- **Dataset Checksum:** `{dossier.cryptographic_evidence.dataset_checksum}`
- **Legacy Implementation Hash:** `{dossier.cryptographic_evidence.legacy_implementation_hash}`
- **Modernized Implementation Hash:** `{dossier.cryptographic_evidence.modernized_implementation_hash}`
- **OracleSet Hash:** `{dossier.cryptographic_evidence.oracle_set_hash}`
- **Policy Hash:** `{dossier.cryptographic_evidence.policy_hash}`

## Audit Notes ({len(dossier.notes)})
"""
        for n in dossier.notes:
            md_text += f"- **{n.author}** ({n.timestamp}): {n.content}\n"

        return Response(
            content=md_text,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=evidence_dossier_{certification_id}.md"}
        )
    elif format == "csv":
        import io, csv
        cases = certification_repository.list_cases_for_input_set(dossier.execution_evidence.input_set_id, run_id=certification_id)
        output = io.StringIO()
        writer = csv.writer(output)
        
        is_custom = dossier.source_evidence.is_custom_dataset or dossier.project_id.startswith("proj_")
        if is_custom:
            # Sanitized/minimized columns for user-supplied/private datasets (NO raw input JSON or secret credentials)
            writer.writerow([
                "case_id",
                "case_index",
                "input_id",
                "input_hash",
                "classification",
                "severity",
                "oracle_result",
                "violated_oracle_ids",
                "legacy_output",
                "modern_output",
                "evidence_reference",
            ])
            for c in cases:
                leg_out = sanitize_details({"out": c.legacy_output_json}).get("out", c.legacy_output_json) if isinstance(c.legacy_output_json, dict) else c.legacy_output_json
                mod_out = sanitize_details({"out": c.modern_output_json}).get("out", c.modern_output_json) if isinstance(c.modern_output_json, dict) else c.modern_output_json
                writer.writerow([
                    c.case_id,
                    c.case_index,
                    c.input_id,
                    c.input_hash,
                    c.classification,
                    c.severity,
                    c.oracle_result,
                    ";".join(c.violated_oracle_ids) if c.violated_oracle_ids else "",
                    leg_out,
                    mod_out,
                    f"artifact://{certification_id}/cases/{c.case_index}",
                ])
        else:
            # Built-in benchmark datasets: full standard case evidence columns
            writer.writerow([
                "case_id",
                "case_index",
                "input_id",
                "input_hash",
                "classification",
                "severity",
                "oracle_result",
                "input_json",
                "legacy_output_json",
                "modern_output_json",
            ])
            for c in cases:
                writer.writerow([
                    c.case_id,
                    c.case_index,
                    c.input_id,
                    c.input_hash,
                    c.classification,
                    c.severity,
                    c.oracle_result,
                    c.input_json,
                    c.legacy_output_json,
                    c.modern_output_json,
                ])

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=evidence_cases_{certification_id}.csv"}
        )
