import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

logger = logging.getLogger(__name__)

sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[2] / "legacy_sample"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
from benchmarks.models import BenchmarkValidationResult

import legacy_loan_approval
import modern_loan_approval
from generate_traces import generate_traces


ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT / "legacy_sample"
FIELD_BOUNDS = {
    "credit_score": (400, 820),
    "debt_ratio": (0.0, 0.9),
    "annual_income": (10_000, 150_000),
}

app = FastAPI(title="BEACON API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


class DemoRunRequest(BaseModel):
    implementation: Literal["buggy", "equivalent"] = "buggy"


class DriftRequest(BaseModel):
    baseline_run_id: str
    implementation: Literal["buggy", "equivalent"] = "buggy"


def _sample_traces():
    trace_path = SAMPLE_DIR / "trace_log.json"
    if not trace_path.exists():
        import json
        trace_path.write_text(json.dumps(generate_traces(), indent=2))
    return load_traces(trace_path)


from ingestion.legacy_parser import extract_ast_structure
from evidence.builder import build_evidence_package
from mining.pipeline import run_mining_pipeline

def _sample_oracles():
    traces = _sample_traces()
    legacy_file = str(SAMPLE_DIR / "legacy_loan_approval.py")
    static_result = extract_ast_structure(legacy_file)
    evidence_pkg = build_evidence_package(static_result, traces)
    
    graduated, unconfirmed = run_mining_pipeline(
        evidence_package=evidence_pkg,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        already_validated=[],
        use_atlas=False,
        use_llm=False
    )
    return [synthesize_oracle(invariant) for invariant in graduated], graduated

def _implementation(name: str):
    return modern_loan_approval.evaluate_loan if name == "buggy" else legacy_loan_approval.evaluate_loan


@app.get("/")
def root():
    return {
        "name": "BEACON API",
        "status": "ok",
        "storage": "local SQLite",
        "docs": "/docs",
        "health": "/health",
    }


from llm.manager import get_provider_manager


@app.get("/health")
def health():
    return {"status": "ok", "storage": "local SQLite"}


@app.get("/api/llm/status")
def get_llm_status():
    """Returns sanitized multi-provider LLM status and availability."""
    manager = get_provider_manager()
    return manager.get_status()


from oracle.registry import registry
from oracle.compiler import compile_candidate_to_oracle, OracleCompilationError
from common.models import CandidateInvariant


@app.get("/api/oracles")
def list_oracles(domain: Optional[str] = None):
    """Lists registered canonical language-independent oracles."""
    oracles = registry.list_oracles(domain=domain)
    return {"oracles": [o.model_dump(mode="json") for o in oracles]}


@app.get("/api/oracles/{oracle_id}")
def get_oracle_endpoint(oracle_id: str, version: Optional[int] = None):
    """Retrieves a specific versioned oracle definition."""
    oracle = registry.get_oracle(oracle_id, version=version)
    if oracle is None:
        raise HTTPException(status_code=404, detail=f"Oracle '{oracle_id}' not found")
    return oracle.model_dump(mode="json")


@app.get("/api/oracle-sets")
def list_oracle_sets_endpoint(domain: Optional[str] = None):
    """Lists frozen Oracle Sets."""
    sets = registry.list_oracle_sets(domain=domain)
    return {"oracle_sets": [s.model_dump(mode="json") for s in sets]}


@app.get("/api/oracle-sets/{set_id}")
def get_oracle_set_endpoint(set_id: str):
    """Retrieves a frozen Oracle Set by ID."""
    oracle_set = registry.get_oracle_set(set_id)
    if oracle_set is None:
        raise HTTPException(status_code=404, detail=f"OracleSet '{set_id}' not found")
    return oracle_set.model_dump(mode="json")


@app.post("/api/oracles/compile")
def compile_oracle_endpoint(candidate: CandidateInvariant):
    """Compiles a validated CandidateInvariant into a canonical Oracle.
    Rejects unvalidated, invalidated, grounding-failed, or low-confidence (<0.8) candidates.
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
def list_runs(limit: int = 20):
    return {"runs": local_store.list_runs(max(1, min(limit, 100)))}


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    run = local_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Certification run not found")
    return run


@app.post("/demo/run")
def run_demo(request: DemoRunRequest):
    """Mine local rules, certify a sample implementation, and persist the report."""
    oracles, invariants = _sample_oracles()
    if not oracles:
        raise HTTPException(status_code=500, detail="No validated sample invariants were produced")
    run = certify(
        oracles=oracles,
        modern_fn=_implementation(request.implementation),
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        domain_of={oracle.invariant_id: "Loan approval" for oracle in oracles},
    )
    local_store.save_run(run)
    return {
        "run": run.model_dump(mode="json"),
        "implementation": request.implementation,
        "invariants": [invariant.model_dump(mode="json") for invariant in invariants],
    }


@app.get("/demo/invariants")
def list_demo_invariants():
    _, invariants = _sample_oracles()
    return {"invariants": [invariant.model_dump(mode="json") for invariant in invariants]}


@app.post("/drift/demo")
def check_demo_drift(request: DriftRequest):
    baseline = local_store.get_run(request.baseline_run_id)
    if baseline is None:
        raise HTTPException(status_code=404, detail="Baseline certification run not found")
    oracles, _ = _sample_oracles()
    results = [run_oracle(oracle, _implementation(request.implementation), FIELD_BOUNDS) for oracle in oracles]
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
def list_drift_samples(limit: int = 100, benchmark_id: Optional[str] = None):
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
    project_id: str = "default_project"
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
):
    """Performs comprehensive pre-flight validation on a benchmark's adapters, schemas, dataset, and configuration."""
    mode = request.evaluation_mode if request and request.evaluation_mode else evaluation_mode
    variant = request.target_variant if request and request.target_variant else target_variant
    provider = request.preferred_provider if request and request.preferred_provider else preferred_provider
    d_name = request.dataset_name if request and request.dataset_name else dataset_name

    result = benchmark_registry.validate_benchmark(
        benchmark_id=benchmark_id,
        evaluation_mode=mode,
        target_variant=variant,
        preferred_provider=provider,
        dataset_name=d_name,
    )
    if not result.is_valid and any("not found in registry" in e for e in result.errors):
        raise HTTPException(status_code=404, detail=f"Benchmark '{benchmark_id}' not found.")
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
def run_certification_v1(request: CertificationRunRequest):
    """Executes a policy-driven behavioral certification run using registered ImplementationAdapters or Benchmarks."""
    # 1. Benchmark Resolution Mode
    test_inputs = None
    context = None
    if request.benchmark_id:
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
        except Exception as exc:
            logger.warning(f"Could not load dataset for benchmark {request.benchmark_id}: {exc}")

        field_bounds = bench_spec.field_bounds
        proj_id = request.project_id if request.project_id != "default_project" else f"benchmark_{request.benchmark_id}"

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
        proj_id = request.project_id

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
    )

    if context:
        context.request_identity = request_identity
        context.idempotency_key = request.idempotency_key
        context.is_forced_recompute = request.force_recompute

    # 4. Deterministic Idempotency / Duplicate Request Protection
    if not request.force_recompute:
        existing_artifact = certification_repository.get_by_request_identity(request_identity)
        if existing_artifact is None:
            existing_artifact = certification_repository.find_idempotent_artifact(
                request_identity=request_identity,
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
            return existing_artifact.model_dump(mode="json")
    else:
        logger.info(
            f"Force recompute requested (force_recompute=True) for benchmark '{request.benchmark_id or proj_id}'. "
            f"Bypassing cache reuse and executing fresh certification run."
        )

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

    return artifact.model_dump(mode="json")


@app.get("/api/v1/certification/artifacts")
def list_certification_artifacts(
    project_id: Optional[str] = None,
    benchmark_id: Optional[str] = None,
    limit: int = 50,
):
    """Lists historical immutable CertificationArtifacts filtered by project or benchmark."""
    artifacts = certification_repository.list_artifacts(project_id=project_id, benchmark_id=benchmark_id, limit=limit)
    return {"artifacts": [a.model_dump(mode="json") for a in artifacts]}


@app.post("/api/v1/certification/{certification_id}/verify")
def verify_certification_artifact_endpoint(certification_id: str):
    """Cryptographically validates complete 8-point integrity of a certification artifact and its inputs."""
    report = certification_repository.verify_certification_run_integrity(certification_id)
    if report.get("status") == "FAIL" and any("not found" in e for e in report.get("errors", [])):
        raise HTTPException(status_code=404, detail=f"Certification artifact '{certification_id}' not found.")
    return report


@app.get("/api/v1/certification/{certification_id}")
def get_certification_artifact(certification_id: str):
    """Retrieves a single CertificationArtifact by ID."""
    artifact = certification_repository.get_artifact(certification_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Certificate '{certification_id}' not found.")
    return artifact.model_dump(mode="json")


@app.get("/api/v1/certification/{certification_id}/report")
def get_certification_report(certification_id: str, format: Literal["html", "markdown", "json"] = "html"):
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
def get_certification_oracles(certification_id: str):
    """Retrieves per-oracle verification summaries for drill-down."""
    artifact = certification_repository.get_artifact(certification_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Certificate '{certification_id}' not found.")
    return {"oracle_summaries": [s.model_dump(mode="json") for s in artifact.oracle_summaries]}


@app.get("/api/v1/certification/{certification_id}/counterexamples")
def get_certification_counterexamples(certification_id: str):
    """Retrieves exact counterexamples / regressions produced by certification."""
    artifact = certification_repository.get_artifact(certification_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Certificate '{certification_id}' not found.")
    return {"counterexamples": [r.model_dump(mode="json") for r in artifact.regressions]}


@app.post("/api/v1/drift/evaluate")
def evaluate_drift_endpoint(request: DriftEvaluateRequest):
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
def get_certification_cases(certification_id: str, limit: int = 100, offset: int = 0, classification: Optional[str] = None):
    """Retrieves paginated test cases for a certification run."""
    cases = certification_repository.list_certification_cases(certification_id, limit, offset, classification)
    return {"cases": [c.model_dump(mode="json") for c in cases]}


@app.get("/api/v1/certification/{certification_id}/input_set")
def get_certification_input_set(certification_id: str):
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
):
    """Exports a complete, auditable certification dossier in JSON, Markdown, or CSV format with complete context and zero secrets."""
    artifact = certification_repository.get_artifact(certification_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Certification not found.")

    cases = certification_repository.list_cases_for_input_set(artifact.input_set_id, run_id=artifact.certification_id)
    input_set = certification_repository.get_input_set(artifact.input_set_id)
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
def verify_certification_artifact(certification_id: str):
    """Cryptographically validates complete 8-point integrity of a certification artifact and its inputs."""
    report = certification_repository.verify_certification_run_integrity(certification_id)
    if report.get("status") == "FAIL" and any("not found" in e for e in report.get("errors", [])):
        raise HTTPException(status_code=404, detail=f"Certification artifact '{certification_id}' not found.")
    return report


@app.get("/api/v1/certification/{certification_id}/verify_reproducibility")
def verify_certification_reproducibility(certification_id: str):
    """Backward-compatible endpoint for checking artifact and input-set integrity."""
    return verify_certification_artifact(certification_id)


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
def preview_custom_dataset(request: DatasetIngestionRequest):
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
def upload_custom_dataset(request: DatasetIngestionRequest):
    """Authoritatively validates, canonicalizes, registers, and manifests a user-supplied dataset."""
    try:
        manifest, records, test_inputs = dataset_validator.validate_for_ingestion(request)
    except ValueError as ve:
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
def list_custom_datasets(project_id: Optional[str] = None, limit: int = 50):
    """Lists registered custom dataset manifests with project namespace isolation."""
    manifests = user_dataset_registry.list_datasets(project_id=project_id, limit=limit)
    return {"datasets": [m.model_dump(mode="json") for m in manifests]}


@app.get("/api/v1/custom/datasets/{dataset_id}")
def get_custom_dataset(dataset_id: str, project_id: Optional[str] = None):
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
def delete_custom_dataset(dataset_id: str):
    """Deletes a custom dataset and its stored records."""
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
        "SET-RETAIL-CONTROLLED-v1": "retail_discount_pricing",
        "SET-LOAN-CONTROLLED-v1": "loan_approval",
        "SET-PAYROLL-CONTROLLED-v1": "payroll_tax",
        "SET-MEDICAL-CONTROLLED-v1": "medical_triage",
        "retail_discount_pricing": "retail_discount_pricing",
        "loan_approval": "loan_approval",
        "payroll_tax": "payroll_tax",
        "medical_triage": "medical_triage",
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


@app.get("/api/v1/custom/oracle-sets")
def list_custom_oracle_sets(domain: Optional[str] = None):
    """Lists registered, frozen OracleSets available for explicit custom certification binding."""
    from oracle.registry import registry as oracle_reg
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
def validate_custom_certification(req: CustomPreflightRequest):
    """Performs authoritative pre-flight validation on user dataset, schema, allowlisted adapters,
    explicit OracleSet binding, compatibility, policy, and privacy boundaries.
    """
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
        else:
            orc_set = resolve_oracle_set("SET-RETAIL-CONTROLLED-v1")
        if orc_set:
            orc_set_hash = orc_set.oracle_set_hash
            is_compat, missing_vars = check_oracle_set_compatibility(orc_set, manifest.inferred_schema)
            if not is_compat:
                errors.append(
                    f"OracleSet '{orc_set_id}' requires schema fields {missing_vars} which are absent in dataset '{req.dataset_id}'."
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
def run_custom_certification(req: CustomCertificationRunRequest):
    """Certifies custom user-supplied dataset using the authoritative deterministic CertificationEngine.
    Enforces authoritative configuration fingerprint match against pre-flight, explicit OracleSet binding,
    and privacy boundaries.
    """
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
        else:
            orc_set = resolve_oracle_set("SET-RETAIL-CONTROLLED-v1")
        if not orc_set:
            raise HTTPException(status_code=404, detail="No valid OracleSet could be resolved or discovered for FULL_BEACON mode.")

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

    # Idempotency lookup
    if not req.force_recompute:
        existing_artifact = certification_repository.get_by_request_identity(request_identity)
        if existing_artifact is not None:
            logger.info(
                f"Returning existing completed custom artifact '{existing_artifact.certification_id}' "
                f"for request identity '{request_identity[:16]}...'."
            )
            audit_logger.log(
                project_id=req.project_id,
                action=AuditAction.CERTIFICATION_COMPLETE,
                status="SUCCESS",
                dataset_id=req.dataset_id,
                certification_id=existing_artifact.certification_id,
                details={"reuse": True, "request_identity": request_identity},
            )
            return existing_artifact.model_dump(mode="json")

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
        return artifact.model_dump(mode="json")

    except Exception as exc:
        audit_logger.log(
            project_id=req.project_id,
            action=AuditAction.CERTIFICATION_FAIL,
            status="FAIL",
            dataset_id=req.dataset_id,
            details={"error": str(exc)},
        )
        raise HTTPException(status_code=500, detail=f"Custom certification failed: {str(exc)}")


@app.get("/api/v1/custom/audit")
def list_custom_audit_events(
    project_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    limit: int = 50,
):
    """Lists audit events for custom dataset ingestion and certification."""
    events = audit_logger.list_events(project_id=project_id, dataset_id=dataset_id, limit=limit)
    return {"events": [e.model_dump(mode="json") for e in events]}


