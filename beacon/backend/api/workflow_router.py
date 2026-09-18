"""BEACON V2 — Phase 11 Canonical Workflow REST API Router.

Exposes endpoints to execute, inspect, and recover production-grade end-to-end
behavioral equivalence certification workflows.
"""

import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth import (
    Permission,
    User,
    get_current_active_user,
    require_system_admin,
    verify_user_project_permission,
)
from workflow.models import (
    WorkflowRunRequest,
    WorkflowRun,
    WorkflowResult,
    WorkflowState,
    WorkflowErrorCode,
)
from workflow.engine import workflow_engine
from workflow.persistence import workflow_persistence
from workflow.recovery import workflow_recovery

logger = logging.getLogger("beacon.api.workflow")

workflow_router = APIRouter(prefix="/api/v2/workflow", tags=["v2-production-workflow"])


from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

from application.repository_service import (
    RepositoryService,
    RepositorySourceSpec,
    RepositorySourceType,
    repository_service,
)
from application.adapter_detector import (
    AdapterDetector,
    AdapterResolutionStatus,
    adapter_detector,
)
from application.input_discovery import (
    InputDiscoveryEngine,
    InputDiscoveryStatus,
    input_discovery_engine,
)
from application.models import (
    ApplicationSpec,
    ImplementationTarget,
    RuleConfig,
    DatasetConfig,
)
from application.repository import application_repository
from certification.adapter_registry import adapter_registry
from threshold.persistence import threshold_persistence
from threshold.models import ThresholdPolicy, DifferenceMetric, ThresholdStrategy


class RepositoryAnalysisRequest(BaseModel):
    """Request payload for repository static analysis and discovery."""
    legacy_repository: RepositorySourceSpec
    modern_repository: RepositorySourceSpec
    evaluation_mode: Literal["CONTROLLED", "FULL", "FULL_BEACON"] = "CONTROLLED"


class RepositoryAnalysisResult(BaseModel):
    """Structured result of automated repository static analysis and discovery."""
    model_config = ConfigDict(extra="ignore")

    status: str = "READY"
    evaluation_mode: str = "CONTROLLED"
    application_id: str = ""
    specification_fingerprint: str = ""
    legacy: dict[str, Any] = Field(default_factory=dict)
    modern: dict[str, Any] = Field(default_factory=dict)
    rules: list[dict[str, Any]] = Field(default_factory=list)
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    inputs_count: int = 0
    input_provenance: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    diagnostic_message: str = ""
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RepositoryCertificationRequest(BaseModel):
    """Primary request payload for repository-first V2 certification."""
    legacy_repository: RepositorySourceSpec
    modern_repository: RepositorySourceSpec
    evaluation_mode: Literal["CONTROLLED", "FULL", "FULL_BEACON"] = "CONTROLLED"
    policy_min_equivalence_score: float = 0.999
    policy_min_oracle_coverage: float = 0.0
    allow_warnings: bool = False
    explain: bool = True
    explanation_mode: Literal["deterministic", "llm", "auto"] = "deterministic"
    custom_inputs: Optional[list[dict[str, Any]]] = None
    idempotency_key: Optional[str] = None


def _perform_repository_analysis(
    req: Union[RepositoryAnalysisRequest, RepositoryCertificationRequest],
) -> tuple[Any, Any, Any, Any, Any, Any, Any, RepositoryAnalysisResult]:
    """Performs safe static ingestion, static analysis, adapter resolution, and input discovery."""
    # 1. Ingest repositories securely
    try:
        legacy_dir, legacy_prov = repository_service.ingest_repository(req.legacy_repository)
        modern_dir, modern_prov = repository_service.ingest_repository(req.modern_repository)
    except Exception as exc:
        logger.error(f"Repository ingestion failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Repository ingestion failed: {str(exc)}",
        )

    # 2. Automated static repository analysis
    try:
        legacy_analysis = repository_service.analyze_repository(legacy_dir, legacy_prov)
        modern_analysis = repository_service.analyze_repository(modern_dir, modern_prov)
    except Exception as exc:
        logger.error(f"Repository analysis failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Repository static analysis failed: {str(exc)}",
        )

    # 3. Static adapter resolution (fail-closed, no code execution)
    legacy_adapter_res = adapter_detector.resolve_adapter_for_repository(legacy_analysis, role="reference")
    modern_adapter_res = adapter_detector.resolve_adapter_for_repository(modern_analysis, role="target")

    # 4. Input & fixture discovery (no synthetic fallback, no keyword mapping)
    input_discovery_res = input_discovery_engine.discover_inputs(legacy_analysis, modern_analysis)

    app_id = f"APP-{legacy_prov.content_hash[:8]}-{modern_prov.content_hash[:8]}"

    # Aggregate discovered rules & boundary invariants
    discovered_rules = []
    for idx, inv in enumerate(legacy_analysis.boundary_invariants + modern_analysis.boundary_invariants):
        discovered_rules.append({
            "rule_id": f"RULE-{idx+1:03d}",
            "description": inv,
            "source": "STATIC_AST_COMPARISON",
        })

    # Prepare inputs payload
    discovered_inputs = [inp.values for inp in input_discovery_res.test_inputs]

    # Calculate specification fingerprint
    raw_fp_data = {
        "legacy_content_hash": legacy_prov.content_hash,
        "modern_content_hash": modern_prov.content_hash,
        "legacy_adapter": legacy_adapter_res.adapter_name,
        "modern_adapter": modern_adapter_res.adapter_name,
        "legacy_entrypoint": legacy_adapter_res.resolved_entrypoint,
        "modern_entrypoint": modern_adapter_res.resolved_entrypoint,
        "input_set_hash": input_discovery_res.input_set_hash,
        "evaluation_mode": req.evaluation_mode,
    }
    spec_fingerprint = hashlib.sha256(
        json.dumps(raw_fp_data, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()

    # Determine overall status
    errors = []
    warnings = []
    analysis_status = "READY"

    if legacy_adapter_res.status != AdapterResolutionStatus.RESOLVED:
        analysis_status = legacy_adapter_res.status.value
        errors.append(f"Legacy adapter: {legacy_adapter_res.diagnostic_message}")
    if modern_adapter_res.status != AdapterResolutionStatus.RESOLVED:
        if analysis_status == "READY":
            analysis_status = modern_adapter_res.status.value
        errors.append(f"Modern adapter: {modern_adapter_res.diagnostic_message}")
    if input_discovery_res.status != InputDiscoveryStatus.SUCCESS:
        if analysis_status == "READY":
            analysis_status = "DISCOVERY_INSUFFICIENT"
        errors.append(f"Inputs: {input_discovery_res.diagnostic_message}")

    analysis_result = RepositoryAnalysisResult(
        status=analysis_status,
        evaluation_mode=req.evaluation_mode,
        application_id=app_id,
        specification_fingerprint=spec_fingerprint,
        legacy={
            "source_identity": (legacy_prov.identity.model_dump() if legacy_prov.identity else {}),
            "repository_url": legacy_prov.source_url,
            "resolved_revision": legacy_prov.resolved_revision,
            "commit_sha": legacy_prov.commit_sha,
            "content_hash": legacy_prov.content_hash,
            "languages": legacy_analysis.languages,
            "technologies": legacy_analysis.frameworks or legacy_analysis.languages,
            "adapter": legacy_adapter_res.model_dump(exclude={"adapter_instance"}),
            "entrypoints": [e.model_dump() for e in legacy_analysis.entrypoint_candidates],
        },
        modern={
            "source_identity": (modern_prov.identity.model_dump() if modern_prov.identity else {}),
            "repository_url": modern_prov.source_url,
            "resolved_revision": modern_prov.resolved_revision,
            "commit_sha": modern_prov.commit_sha,
            "content_hash": modern_prov.content_hash,
            "languages": modern_analysis.languages,
            "technologies": modern_analysis.frameworks or modern_analysis.languages,
            "adapter": modern_adapter_res.model_dump(exclude={"adapter_instance"}),
            "entrypoints": [e.model_dump() for e in modern_analysis.entrypoint_candidates],
        },
        rules=discovered_rules,
        inputs=discovered_inputs[:5],  # Sample for inspection
        inputs_count=len(input_discovery_res.test_inputs),
        input_provenance=input_discovery_res.provenance,
        provenance={
            "legacy_provenance": legacy_prov.model_dump(),
            "modern_provenance": modern_prov.model_dump(),
            "fingerprint": spec_fingerprint,
        },
        diagnostic_message=(
            f"Successfully analyzed repositories ({len(input_discovery_res.test_inputs)} inputs, "
            f"{len(discovered_rules)} invariants discovered)." if analysis_status == "READY"
            else f"Repository analysis failed closed: {'; '.join(errors)}"
        ),
        errors=errors,
        warnings=warnings,
    )

    return (
        legacy_dir,
        legacy_prov,
        modern_dir,
        modern_prov,
        legacy_adapter_res,
        modern_adapter_res,
        input_discovery_res,
        analysis_result,
    )


def _run_repository_certification_pipeline(
    req: RepositoryCertificationRequest,
    current_user: User,
) -> WorkflowResult:
    """Executes full repository ingestion, analysis, adapter detection, input discovery, and canonical certification."""
    (
        legacy_dir,
        legacy_prov,
        modern_dir,
        modern_prov,
        legacy_adapter_res,
        modern_adapter_res,
        input_discovery_res,
        analysis_result,
    ) = _perform_repository_analysis(req)

    if legacy_adapter_res.status != AdapterResolutionStatus.RESOLVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "LEGACY_ADAPTER_RESOLUTION_FAILED",
                "status": legacy_adapter_res.status.value,
                "message": legacy_adapter_res.diagnostic_message,
                "evidence": legacy_adapter_res.detection_evidence,
                "candidates": legacy_adapter_res.candidate_names,
            },
        )

    if modern_adapter_res.status != AdapterResolutionStatus.RESOLVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "MODERN_ADAPTER_RESOLUTION_FAILED",
                "status": modern_adapter_res.status.value,
                "message": modern_adapter_res.diagnostic_message,
                "evidence": modern_adapter_res.detection_evidence,
                "candidates": modern_adapter_res.candidate_names,
            },
        )

    if req.custom_inputs and len(req.custom_inputs) > 0:
        test_inputs = req.custom_inputs
        input_source_desc = "User-supplied custom inputs"
        input_discovery_meta = {"source": input_source_desc, "count": len(test_inputs)}
    else:
        if input_discovery_res.status != InputDiscoveryStatus.SUCCESS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "INPUT_DISCOVERY_FAILED",
                    "status": input_discovery_res.status.value,
                    "message": input_discovery_res.diagnostic_message,
                },
            )
        test_inputs = [inp.values for inp in input_discovery_res.test_inputs]
        input_source_desc = input_discovery_res.discovery_source
        input_discovery_meta = input_discovery_res.provenance

    # 5. Execution Authorization: Load executable callables ONLY NOW in the authorized execution stage
    legacy_instance = adapter_detector.load_authorized_adapter(
        file_path=Path(legacy_adapter_res.resolved_file),
        fn_name=legacy_adapter_res.resolved_function,
        adapter_name=legacy_adapter_res.adapter_name or "legacy_ref",
        role="reference",
        version=legacy_prov.resolved_revision or "1.0.0",
    )
    modern_instance = adapter_detector.load_authorized_adapter(
        file_path=Path(modern_adapter_res.resolved_file),
        fn_name=modern_adapter_res.resolved_function,
        adapter_name=modern_adapter_res.adapter_name or "modern_tgt",
        role="target",
        version=modern_prov.resolved_revision or "1.0.0",
    )

    adapter_registry.register_adapter(legacy_instance)
    adapter_registry.register_adapter(modern_instance)

    app_id = analysis_result.application_id

    ref_target = ImplementationTarget(
        name=legacy_adapter_res.adapter_name or "legacy_ref",
        version=legacy_prov.resolved_revision or "1.0.0",
        target_type="adapter",
        entrypoint=legacy_adapter_res.resolved_entrypoint or "reference",
        role="reference",
        source_hash=legacy_prov.content_hash,
        metadata={"provenance": legacy_prov.model_dump(), "source_url": legacy_prov.source_url},
    )

    modern_target = ImplementationTarget(
        name=modern_adapter_res.adapter_name or "modern_tgt",
        version=modern_prov.resolved_revision or "1.0.0",
        target_type="adapter",
        entrypoint=modern_adapter_res.resolved_entrypoint or "target",
        role="target",
        source_hash=modern_prov.content_hash,
        metadata={"provenance": modern_prov.model_dump(), "source_url": modern_prov.source_url},
    )

    rule_mode = "CONTROLLED" if req.evaluation_mode == "CONTROLLED" else "FULL_BEACON"
    spec = ApplicationSpec(
        application_id=app_id,
        name=f"Repo-Certification-{app_id}",
        version="1.0.0",
        domain="general",
        reference_implementation=ref_target,
        target_implementations=[modern_target],
        rule_config=RuleConfig(mode=rule_mode),
        dataset_config=DatasetConfig(metadata={"custom_inputs": test_inputs}),
        metadata={
            "legacy_provenance": legacy_prov.model_dump(),
            "modern_provenance": modern_prov.model_dump(),
            "input_discovery": input_discovery_meta,
            "evaluation_mode": req.evaluation_mode,
            "specification_fingerprint": analysis_result.specification_fingerprint,
        },
    )
    application_repository.save_application(spec)

    # 6. Execute canonical V2 workflow engine (deterministic threshold engine handles resolution in Part 2)
    wf_req = WorkflowRunRequest(
        application_id=app_id,
        target_index=0,
        custom_inputs=test_inputs,
        policy_min_equivalence_score=req.policy_min_equivalence_score,
        policy_min_oracle_coverage=req.policy_min_oracle_coverage,
        allow_warnings=req.allow_warnings,
        explain=req.explain,
        explanation_mode=req.explanation_mode,
        enable_discovery=(req.evaluation_mode in ("FULL", "FULL_BEACON")),
        evaluation_mode=req.evaluation_mode,
        idempotency_key=req.idempotency_key,
        user_id=current_user.user_id,
    )

    result = workflow_engine.execute_workflow(wf_req, spec_override=spec)

    # 7. Enrich result metadata with repository facts
    result.metadata = result.metadata or {}
    result.metadata["repository_certification"] = True
    result.metadata["evaluation_mode"] = req.evaluation_mode
    result.metadata["specification_fingerprint"] = analysis_result.specification_fingerprint
    result.metadata["legacy_provenance"] = legacy_prov.model_dump()
    result.metadata["modern_provenance"] = modern_prov.model_dump()
    result.metadata["legacy_adapter_resolution"] = legacy_adapter_res.model_dump(exclude={"adapter_instance"})
    result.metadata["modern_adapter_resolution"] = modern_adapter_res.model_dump(exclude={"adapter_instance"})
    result.metadata["input_discovery"] = (
        input_discovery_res.model_dump(exclude={"test_inputs"}) if input_discovery_res else input_discovery_meta
    )
    result.metadata["inputs_count"] = len(test_inputs)

    return result


@workflow_router.post(
    "/analyze-repository",
    response_model=RepositoryAnalysisResult,
    status_code=status.HTTP_200_OK,
    summary="Safely analyze repositories, detect technology, resolve adapters, and discover legitimate inputs",
)
def analyze_repository_endpoint(
    req: RepositoryAnalysisRequest,
    current_user: User = Depends(get_current_active_user),
) -> RepositoryAnalysisResult:
    """Performs non-executing static analysis on legacy and modern repositories."""
    _, _, _, _, _, _, _, analysis_result = _perform_repository_analysis(req)
    return analysis_result


@workflow_router.post(
    "/certify-repository",
    response_model=WorkflowResult,
    status_code=status.HTTP_200_OK,
    summary="Execute repository-first V2 certification workflow from source repositories",
)
def certify_repository_endpoint(
    req: RepositoryCertificationRequest,
    current_user: User = Depends(get_current_active_user),
) -> WorkflowResult:
    """Ingests legacy & modern repositories, analyzes sources, resolves adapters, discovers inputs,

    and executes the authoritative BEACON V2 certification engine.
    """
    return _run_repository_certification_pipeline(req, current_user)


@workflow_router.post(
    "/certify",
    response_model=WorkflowResult,
    status_code=status.HTTP_200_OK,
    summary="Execute canonical V2 behavioral equivalence certification workflow",
)
def certify_workflow(
    req: WorkflowRunRequest,
    current_user: User = Depends(get_current_active_user),
) -> WorkflowResult:
    """Executes the canonical, end-to-end V2 certification workflow with strict authority checks,

    fail-closed guarantees, idempotency, and audit persistence.
    """
    # 1. Enforce RBAC permission
    verify_user_project_permission(current_user, req.application_id, Permission.CERTIFY)

    # Attach authenticated user identity
    req.user_id = current_user.user_id

    try:
        result = workflow_engine.execute_workflow(req)
        return result
    except Exception as exc:
        logger.error(f"Workflow execution unexpected exception for application '{req.application_id}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow execution failed: {str(exc)}",
        )


@workflow_router.get(
    "/runs/{run_id}",
    response_model=WorkflowRun,
    status_code=status.HTTP_200_OK,
    summary="Get workflow execution run status and authoritative links",
)
def get_workflow_run(
    run_id: str,
    current_user: User = Depends(get_current_active_user),
) -> WorkflowRun:
    """Retrieves an authoritative workflow run by ID."""
    run = workflow_persistence.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run '{run_id}' not found.",
        )

    verify_user_project_permission(current_user, run.application_id, Permission.VIEW)
    return run


@workflow_router.get(
    "/runs",
    response_model=list[WorkflowRun],
    status_code=status.HTTP_200_OK,
    summary="List workflow execution runs with optional filtering",
)
def list_workflow_runs(
    application_id: Optional[str] = Query(None, description="Filter by application ID"),
    state: Optional[WorkflowState] = Query(None, description="Filter by workflow state"),
    limit: int = Query(50, ge=1, le=500, description="Max runs to return"),
    current_user: User = Depends(get_current_active_user),
) -> list[WorkflowRun]:
    """Lists workflow runs matching criteria."""
    if application_id:
        verify_user_project_permission(current_user, application_id, Permission.VIEW)

    return workflow_persistence.list_runs(
        application_id=application_id,
        state=state,
        limit=limit,
    )


@workflow_router.post(
    "/recover",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Trigger interrupted workflow recovery scan",
)
def recover_workflows(
    current_user: User = Depends(require_system_admin),
) -> dict[str, Any]:
    """Scans and recovers any non-terminal workflow runs safely."""
    recovered = workflow_recovery.recover_interrupted_workflows()
    return {
        "status": "SUCCESS",
        "recovered_count": len(recovered),
        "recovered_runs": [r.model_dump(mode="json") for r in recovered],
    }
