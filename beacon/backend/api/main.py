"""FastAPI application for the local-first BEACON prototype."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

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
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
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
    all_samples = local_store.list_drift_samples(max(1, min(limit, 500)))
    if benchmark_id:
        if benchmark_id in ("loan", "loan_approval"):
            return {"samples": [s for s in all_samples if s.get("benchmark_id") in ("loan", "loan_approval", None)]}
        return {"samples": [s for s in all_samples if s.get("benchmark_id") == benchmark_id]}
    return {"samples": all_samples}


# ==============================================================================
# Phase 10 — Production-Grade Certification & Drift Endpoints
# ==============================================================================

from certification.adapter_registry import adapter_registry
from benchmarks.registry import benchmark_registry


class CertificationRunRequest(BaseModel):
    project_id: str = "default_project"
    benchmark_id: Optional[str] = None
    benchmark_variant: Optional[str] = "clean_v2"
    discovery_mode: Literal["CONTROLLED", "FULL_BEACON"] = "CONTROLLED"
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


@app.post("/api/v1/benchmarks/{benchmark_id}/validate")
def validate_benchmark_endpoint(benchmark_id: str):
    """Performs pre-flight validation on schemas, adapters, and input datasets."""
    result = benchmark_registry.validate_benchmark(benchmark_id)
    return result.model_dump(mode="json")


@app.get("/api/v1/benchmarks/{benchmark_id}/datasets")
def list_benchmark_datasets_endpoint(benchmark_id: str):
    """Lists available input datasets for a benchmark."""
    spec = benchmark_registry.get_benchmark(benchmark_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Benchmark '{benchmark_id}' not found.")
    return {
        "benchmark_id": benchmark_id,
        "datasets": [
            {"dataset_id": "default", "name": "Evaluation Dataset", "source": spec.dataset_source},
            {"dataset_id": "validation", "name": "Pre-flight Validation Dataset", "source": "validation.json"},
        ],
    }


@app.get("/api/v1/benchmarks/{benchmark_id}/manifest")
def get_benchmark_manifest_endpoint(
    benchmark_id: str,
    variant: str = "clean_v2",
    discovery_mode: Literal["CONTROLLED", "FULL_BEACON"] = "CONTROLLED",
):
    """Retrieves the reproducibility and execution manifest for a benchmark."""
    spec = benchmark_registry.get_benchmark(benchmark_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Benchmark '{benchmark_id}' not found.")

    artifacts = certification_repository.list_artifacts(project_id=f"benchmark_{benchmark_id}", limit=1)
    art = artifacts[0] if artifacts else None
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
        oracle_set = benchmark_registry.get_or_create_oracle_set(request.benchmark_id, mode=mode)
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

        oracle_src = "CONTROLLED_ORACLE_SET"
        if mode == "FULL_BEACON":
            first_prov = getattr(oracle_set.oracles[0], "provenance", None) if oracle_set.oracles else None
            ev_src = getattr(first_prov, "evidence_source", "") if first_prov else ""
            oracle_src = "FULL_BEACON_DISCOVERED" if ev_src == "FULL_BEACON_DISCOVERED" else "FULL_BEACON_OFFLINE_FALLBACK"

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
            legacy_implementation_hash="",
            modernized_implementation_id=modern_adp.name,
            modernized_implementation_hash="",
            oracle_set_id=oracle_set.oracle_set_id,
            oracle_set_hash=oracle_set.oracle_set_hash,
            oracle_source_type=oracle_src,
            policy_id=request.policy.policy_id if request.policy else "POL-DEFAULT",
            policy_hash="",
            provider_metadata={"model": "openrouter/auto"} if mode == "FULL_BEACON" and request.use_llm else {},
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
    """Cryptographically verifies artifact content hash and input-set canonical hash."""
    artifact = certification_repository.get_artifact(certification_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Certificate '{certification_id}' not found.")

    is_art_valid = verify_artifact_integrity(artifact)
    is_inp_valid = certification_repository.verify_input_set_integrity(artifact.input_set_id, artifact.certification_id)

    return {
        "certification_id": certification_id,
        "artifact_integrity_valid": is_art_valid,
        "input_set_integrity_valid": is_inp_valid,
        "content_hash": artifact.content_hash,
        "input_set_hash": artifact.input_set_hash,
        "oracle_set_hash": artifact.oracle_set_hash,
        "policy_hash": artifact.certification_policy_hash,
        "reproducibility_state": artifact.reproducibility_state,
        "status": artifact.status.value,
        "benchmark_id": artifact.benchmark_id or (artifact.context.benchmark_id if artifact.context else None),
    }


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


from fastapi.responses import JSONResponse
@app.get("/api/v1/certification/{certification_id}/export")
def export_certification_dataset(certification_id: str):
    """Exports the entire dataset for a certification run."""
    artifact = certification_repository.get_artifact(certification_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Certification not found.")
    cases = certification_repository.list_certification_cases(certification_id, limit=100000)
    input_set = certification_repository.get_input_set(artifact.input_set_id)
    
    export_payload = {
        "metadata": {
            "certification_id": artifact.certification_id,
            "project_id": artifact.project_id,
            "artifact_hash": artifact.content_hash,
            "oracle_set_id": artifact.oracle_set_id,
            "oracle_set_hash": artifact.oracle_set_hash,
            "policy_id": artifact.certification_policy_id,
            "policy_hash": artifact.certification_policy_hash,
            "reproducibility_state": artifact.reproducibility_state,
        },
        "input_set": input_set.model_dump(mode="json") if input_set else None,
        "cases": [c.model_dump(mode="json") for c in cases]
    }
    
    return JSONResponse(
        content=export_payload,
        headers={"Content-Disposition": f"attachment; filename=certification_export_{certification_id}.json"}
    )


@app.get("/api/v1/certification/{certification_id}/verify_reproducibility")
def verify_certification_reproducibility(certification_id: str):
    """Verifies that persisted cases match the stored input set and artifact integrity."""
    artifact = certification_repository.get_artifact(certification_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Certification not found.")

    artifact_intact = verify_artifact_integrity(artifact)
    input_set_intact = certification_repository.verify_input_set_integrity(
        artifact.input_set_id, artifact.certification_id
    )

    return {
        "certification_id": certification_id,
        "artifact_integrity": artifact_intact,
        "input_set_integrity": input_set_intact,
        "reproducibility_state": artifact.reproducibility_state,
        "verified": artifact_intact and input_set_intact,
    }

