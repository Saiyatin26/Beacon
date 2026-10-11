"""BEACON V2 — Phase 11 Canonical Workflow REST API Router.

Exposes endpoints to execute, inspect, and recover production-grade end-to-end
behavioral equivalence certification workflows.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File, Form
from fastapi.responses import Response

from auth import (
    Permission,
    User,
    get_current_active_user,
    require_system_admin,
    verify_user_project_permission,
)
from workflow.models import (
    FinalizationState,
    WorkflowRunRequest,
    WorkflowRun,
    WorkflowResult,
    WorkflowState,
    WorkflowErrorCode,
)
from workflow.engine import workflow_engine
from workflow.persistence import workflow_persistence
from workflow.recovery import workflow_recovery
from certification.report_generator import generate_workflow_run_pdf_report

logger = logging.getLogger("beacon.api.workflow")

workflow_router = APIRouter(prefix="/api/v2/workflow", tags=["v2-production-workflow"])


from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

from application.repository_service import (
    RepositoryIdentity,
    RepositoryProvenance,
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
    RepositoryExecutionSpec,
    SourceIngestionMode,
    AnalysisScope,
    SourceArtifact,
    build_application_spec_from_repository_execution_spec,
)
from application.repository import application_repository
from certification.adapter_registry import adapter_registry
from certification.adapters import compute_implementation_hash
from certification.models import CertificationTestInput, compute_input_set_canonical_hash
from certification.repository import certification_repository
from threshold.persistence import threshold_persistence
from threshold.models import ThresholdPolicy, DifferenceMetric, ThresholdStrategy
from certification.policies import certification_policy_resolver
from common.config import settings


class RepositoryAnalysisRequest(BaseModel):
    """Request payload for repository static analysis and discovery."""
    legacy_repository: Optional[RepositorySourceSpec] = None
    modern_repository: Optional[RepositorySourceSpec] = None
    evaluation_mode: Literal["CONTROLLED", "FULL", "FULL_BEACON"] = "FULL_BEACON"
    source_mode: Union[SourceIngestionMode, str] = SourceIngestionMode.GITHUB_REPOSITORY
    analysis_scope: Union[AnalysisScope, str] = AnalysisScope.REPOSITORY
    selected_artifacts: Optional[list[Union[dict[str, Any], str, SourceArtifact]]] = None
    upload_id: Optional[str] = None


class RepositoryAnalysisResult(BaseModel):
    """Structured result of automated repository static analysis and discovery."""
    model_config = ConfigDict(extra="ignore")

    status: str = "READY"
    evaluation_mode: str = "CONTROLLED"
    source_mode: str = "GITHUB_REPOSITORY"
    analysis_scope: str = "REPOSITORY"
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
    legacy_repository: Optional[RepositorySourceSpec] = None
    modern_repository: Optional[RepositorySourceSpec] = None
    evaluation_mode: Literal["CONTROLLED", "FULL", "FULL_BEACON"] = "FULL_BEACON"
    policy_min_equivalence_score: float = 0.999
    policy_min_oracle_coverage: float = 0.0
    allow_warnings: bool = False
    explain: bool = True
    explanation_mode: Literal["deterministic", "llm", "auto"] = "auto"
    custom_inputs: Optional[list[dict[str, Any]]] = None
    idempotency_key: Optional[str] = None
    source_mode: Union[SourceIngestionMode, str] = SourceIngestionMode.GITHUB_REPOSITORY
    analysis_scope: Union[AnalysisScope, str] = AnalysisScope.REPOSITORY
    selected_artifacts: Optional[list[Union[dict[str, Any], str, SourceArtifact]]] = None
    upload_id: Optional[str] = None
    force_recompute: bool = True


def _perform_repository_analysis(
    req: Union[RepositoryAnalysisRequest, RepositoryCertificationRequest],
) -> tuple[Any, Any, Any, Any, Any, Any, Any, RepositoryAnalysisResult]:
    """Performs safe static ingestion, static analysis, adapter resolution, and input discovery."""
    # 1. Ingest repositories or load staged upload sources
    try:
        is_upload = (
            str(getattr(req, "source_mode", "")).upper() in ("UPLOADED_FILES", "UPLOADED", "UPLOAD")
            or bool(getattr(req, "upload_id", None))
        )
        if is_upload and getattr(req, "upload_id", None):
            upload_id = req.upload_id
            staged_dir = repository_service.cache_dir.parent / "staged_sources" / upload_id
            legacy_dir = staged_dir / "legacy"
            modern_dir = staged_dir / "modern"
            if not legacy_dir.exists() or not modern_dir.exists():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Staged upload workspace '{upload_id}' not found.",
                )
            repository_service.normalize_extensionless_sources(legacy_dir)
            repository_service.normalize_extensionless_sources(modern_dir)
            legacy_content_hash = compute_implementation_hash(legacy_dir)
            modern_content_hash = compute_implementation_hash(modern_dir)
            legacy_identity = RepositoryIdentity(
                canonical_url=str(legacy_dir),
                resolved_revision=upload_id,
                commit_sha=None,
                content_hash=legacy_content_hash,
            )
            legacy_prov = RepositoryProvenance(
                source_url=f"upload://{upload_id}/legacy",
                canonical_source_url=f"upload://{upload_id}/legacy",
                source_type="directory",
                resolved_revision=upload_id,
                commit_sha=None,
                content_hash=legacy_content_hash,
                retrieval_timestamp=datetime.now(timezone.utc).isoformat(),
                local_path=str(legacy_dir),
                identity=legacy_identity,
            )
            modern_identity = RepositoryIdentity(
                canonical_url=str(modern_dir),
                resolved_revision=upload_id,
                commit_sha=None,
                content_hash=modern_content_hash,
            )
            modern_prov = RepositoryProvenance(
                source_url=f"upload://{upload_id}/modern",
                canonical_source_url=f"upload://{upload_id}/modern",
                source_type="directory",
                resolved_revision=upload_id,
                commit_sha=None,
                content_hash=modern_content_hash,
                retrieval_timestamp=datetime.now(timezone.utc).isoformat(),
                local_path=str(modern_dir),
                identity=modern_identity,
            )
        else:
            if not req.legacy_repository or not req.modern_repository:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Both legacy_repository and modern_repository must be specified for GITHUB_REPOSITORY source mode.",
                )
            legacy_dir, legacy_prov = repository_service.ingest_repository(req.legacy_repository)
            modern_dir, modern_prov = repository_service.ingest_repository(req.modern_repository)
    except HTTPException:
        raise
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
    input_discovery_res = input_discovery_engine.discover_inputs(
        legacy_analysis,
        modern_analysis,
        legacy_entrypoint_file=(
            Path(legacy_adapter_res.resolved_file)
            if legacy_adapter_res.resolved_file
            else None
        ),
        modern_entrypoint_file=(
            Path(modern_adapter_res.resolved_file)
            if modern_adapter_res.resolved_file
            else None
        ),
    )

    app_id = f"APP-{legacy_prov.content_hash[:8]}-{modern_prov.content_hash[:8]}"

    # 4.1 Generate structured COBOL execution plan via OpenRouter intelligence layer
    cobol_plan = None
    if any(lang.lower() == "cobol" for lang in legacy_analysis.languages):
        cbl_files = list(Path(legacy_dir).rglob("*.cbl")) + list(Path(legacy_dir).rglob("*.cob"))
        if cbl_files:
            cbl_src = cbl_files[0].read_text(encoding="utf-8", errors="ignore")
            from intelligence.cobol_plan import generate_cobol_execution_plan
            cobol_plan = generate_cobol_execution_plan(cbl_src, file_path=cbl_files[0])

    # Only source-anchored AI candidates are behavioral rules. Execution-plan
    # predicates and AST boundary checks are diagnostics, not business rules.
    discovered_rules = []
    ai_rules = input_discovery_res.provenance.get("ai_mined_rules") or []
    if ai_rules:
        discovered_rules.extend(ai_rules)

    # Prepare inputs payload
    discovered_inputs = [inp.values for inp in input_discovery_res.test_inputs]
    input_set_id = input_discovery_res.input_set_hash or hashlib.sha256(
        json.dumps(discovered_inputs, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    rule_set_id = hashlib.sha256(
        json.dumps(discovered_rules, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()

    # Normalize selected artifacts
    raw_selected = getattr(req, "selected_artifacts", None) or []
    norm_selected: list[SourceArtifact] = []
    for item in raw_selected:
        if isinstance(item, SourceArtifact):
            norm_selected.append(item)
        elif isinstance(item, dict):
            norm_selected.append(SourceArtifact(**item))
        elif isinstance(item, str):
            norm_selected.append(
                SourceArtifact(
                    artifact_id=item,
                    filename=Path(item).name,
                    relative_path=item,
                    content_hash=hashlib.sha256(item.encode()).hexdigest()[:16],
                )
            )

    # Build authoritative RepositoryExecutionSpec
    repo_spec = RepositoryExecutionSpec(
        specification_id=app_id,
        source_mode=getattr(req, "source_mode", SourceIngestionMode.GITHUB_REPOSITORY),
        analysis_scope=getattr(req, "analysis_scope", AnalysisScope.REPOSITORY),
        selected_artifacts=norm_selected,
        legacy_source_identity={
            **(legacy_prov.identity.model_dump() if legacy_prov.identity else {}),
            "repository_url": legacy_prov.source_url,
            "commit_sha": legacy_prov.commit_sha,
            "content_hash": legacy_prov.content_hash,
            "technologies": legacy_analysis.frameworks or legacy_analysis.languages,
            "source_mode": str(getattr(req, "source_mode", SourceIngestionMode.GITHUB_REPOSITORY)),
            "analysis_scope": str(getattr(req, "analysis_scope", AnalysisScope.REPOSITORY)),
        },
        modern_source_identity={
            **(modern_prov.identity.model_dump() if modern_prov.identity else {}),
            "repository_url": modern_prov.source_url,
            "commit_sha": modern_prov.commit_sha,
            "content_hash": modern_prov.content_hash,
            "technologies": modern_analysis.frameworks or modern_analysis.languages,
            "source_mode": str(getattr(req, "source_mode", SourceIngestionMode.GITHUB_REPOSITORY)),
            "analysis_scope": str(getattr(req, "analysis_scope", AnalysisScope.REPOSITORY)),
        },
        legacy_adapter=legacy_adapter_res.model_dump(exclude={"adapter_instance"}),
        modern_adapter=modern_adapter_res.model_dump(exclude={"adapter_instance"}),
        legacy_entrypoint=legacy_adapter_res.resolved_entrypoint or "",
        modern_entrypoint=modern_adapter_res.resolved_entrypoint or "",
        discovered_rules=discovered_rules,
        discovered_inputs=discovered_inputs,
        input_set_identity=input_set_id,
        rule_set_identity=rule_set_id,
        evaluation_mode=req.evaluation_mode,
        policy_identity=certification_policy_resolver.resolve_effective_policy(
            application_id=app_id,
            evaluation_mode=req.evaluation_mode,
        ).compute_policy_fingerprint(),
        provenance={
            "legacy_provenance": legacy_prov.model_dump(),
            "modern_provenance": modern_prov.model_dump(),
            "input_discovery_provenance": input_discovery_res.provenance,
            "cobol_execution_plan": cobol_plan.model_dump() if cobol_plan else None,
            "llm_provider": (
                input_discovery_res.provenance.get("llm_provider")
                or (cobol_plan.provenance if cobol_plan else {})
            ),
        },
    )
    spec_fingerprint = repo_spec.specification_fingerprint

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
    if any(lang.lower() == "cobol" for lang in legacy_analysis.languages) and not discovered_rules:
        if analysis_status == "READY":
            analysis_status = "RULE_DISCOVERY_INSUFFICIENT"
        provider_status = input_discovery_res.provenance.get("llm_provider", {}).get(
            "rule_extraction_status",
            "NOT_RECORDED",
        )
        errors.append(
            f"AI behavioral-rule extraction produced no source-validated rules "
            f"(status: {provider_status})."
        )

    analysis_result = RepositoryAnalysisResult(
        status=analysis_status,
        evaluation_mode=req.evaluation_mode,
        source_mode=str(getattr(req, "source_mode", SourceIngestionMode.GITHUB_REPOSITORY)),
        analysis_scope=str(getattr(req, "analysis_scope", AnalysisScope.REPOSITORY)),
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
            "input_set_identity": input_set_id,
            "rule_set_identity": rule_set_id,
            "cobol_execution_plan": cobol_plan.model_dump() if cobol_plan else None,
        },
        diagnostic_message=(
            f"Successfully analyzed repositories ({len(input_discovery_res.test_inputs)} inputs, "
            f"{len(discovered_rules)} source-validated behavioral rules discovered)." if analysis_status == "READY"
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
        repo_spec,
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
        repo_spec,
    ) = _perform_repository_analysis(req)

    if legacy_adapter_res.status != AdapterResolutionStatus.RESOLVED:
        inconclusive_run_id = f"run_{hashlib.sha256(f'{analysis_result.application_id}_legacy_unresolved_{datetime.now(timezone.utc).isoformat()}'.encode()).hexdigest()[:16]}"
        run_record = WorkflowRun(
            workflow_run_id=inconclusive_run_id,
            application_id=analysis_result.application_id,
            request_fingerprint=analysis_result.specification_fingerprint,
            state=WorkflowState.INCONCLUSIVE,
            finalization_state=FinalizationState.COMPLETED,
            certification_status="INCONCLUSIVE",
            error_code=WorkflowErrorCode.CERTIFICATION_INCONCLUSIVE,
            error_message=f"Legacy adapter unresolved: {legacy_adapter_res.diagnostic_message}",
            metadata={
                "error": "LEGACY_ADAPTER_UNRESOLVED",
                "status": legacy_adapter_res.status.value,
                "diagnostic_message": legacy_adapter_res.diagnostic_message,
                "evidence": legacy_adapter_res.detection_evidence,
                "candidates": legacy_adapter_res.candidate_names,
            },
        )
        workflow_persistence.save_run(run_record)
        return WorkflowResult(
            workflow_run_id=inconclusive_run_id,
            application_id=analysis_result.application_id,
            state=WorkflowState.INCONCLUSIVE,
            status="INCONCLUSIVE",
            certified=False,
            equivalence_score=None,
            artifact_id=None,
            regressions_count=0,
            regressions=[],
            audit_status="PERSISTED",
            error_code=WorkflowErrorCode.CERTIFICATION_INCONCLUSIVE,
            error_message=f"Legacy adapter unresolved: {legacy_adapter_res.diagnostic_message}",
            metadata=run_record.metadata,
        )

    if modern_adapter_res.status != AdapterResolutionStatus.RESOLVED:
        inconclusive_run_id = f"run_{hashlib.sha256(f'{analysis_result.application_id}_modern_unresolved_{datetime.now(timezone.utc).isoformat()}'.encode()).hexdigest()[:16]}"
        run_record = WorkflowRun(
            workflow_run_id=inconclusive_run_id,
            application_id=analysis_result.application_id,
            request_fingerprint=analysis_result.specification_fingerprint,
            state=WorkflowState.INCONCLUSIVE,
            finalization_state=FinalizationState.COMPLETED,
            certification_status="INCONCLUSIVE",
            error_code=WorkflowErrorCode.CERTIFICATION_INCONCLUSIVE,
            error_message=f"Modern adapter unresolved: {modern_adapter_res.diagnostic_message}",
            metadata={
                "error": "MODERN_ADAPTER_UNRESOLVED",
                "status": modern_adapter_res.status.value,
                "diagnostic_message": modern_adapter_res.diagnostic_message,
                "evidence": modern_adapter_res.detection_evidence,
                "candidates": modern_adapter_res.candidate_names,
            },
        )
        workflow_persistence.save_run(run_record)
        return WorkflowResult(
            workflow_run_id=inconclusive_run_id,
            application_id=analysis_result.application_id,
            state=WorkflowState.INCONCLUSIVE,
            status="INCONCLUSIVE",
            certified=False,
            equivalence_score=None,
            artifact_id=None,
            regressions_count=0,
            regressions=[],
            audit_status="PERSISTED",
            error_code=WorkflowErrorCode.CERTIFICATION_INCONCLUSIVE,
            error_message=f"Modern adapter unresolved: {modern_adapter_res.diagnostic_message}",
            metadata=run_record.metadata,
        )

    if any(lang.lower() == "cobol" for lang in legacy_analysis.languages) and not repo_spec.discovered_rules:
        provider_metadata = input_discovery_res.provenance.get("llm_provider", {})
        discovery_status = provider_metadata.get("rule_extraction_status", "NOT_RECORDED")
        inconclusive_run_id = f"run_{hashlib.sha256(f'{analysis_result.application_id}_rule_discovery_{datetime.now(timezone.utc).isoformat()}'.encode()).hexdigest()[:16]}"
        error_message = (
            "AI behavioral-rule extraction did not produce source-validated rules "
            f"(status: {discovery_status}). Certification is blocked rather than treating "
            "implementation predicates as business rules."
        )
        run_record = WorkflowRun(
            workflow_run_id=inconclusive_run_id,
            application_id=analysis_result.application_id,
            request_fingerprint=analysis_result.specification_fingerprint,
            state=WorkflowState.INCONCLUSIVE,
            finalization_state=FinalizationState.COMPLETED,
            certification_status="RULE_DISCOVERY_INSUFFICIENT",
            error_code=WorkflowErrorCode.CERTIFICATION_INCONCLUSIVE,
            error_message=error_message,
            metadata={
                "error": "RULE_DISCOVERY_INSUFFICIENT",
                "status": "RULE_DISCOVERY_INSUFFICIENT",
                "diagnostic_message": error_message,
                "llm_provider": provider_metadata,
                "source_hashes": {
                    "legacy": legacy_prov.content_hash,
                    "modern": modern_prov.content_hash,
                },
            },
        )
        workflow_persistence.save_run(run_record)
        return WorkflowResult(
            workflow_run_id=inconclusive_run_id,
            application_id=analysis_result.application_id,
            state=WorkflowState.INCONCLUSIVE,
            status="RULE_DISCOVERY_INSUFFICIENT",
            certified=False,
            equivalence_score=None,
            artifact_id=None,
            regressions_count=0,
            regressions=[],
            audit_status="PERSISTED",
            error_code=WorkflowErrorCode.CERTIFICATION_INCONCLUSIVE,
            error_message=error_message,
            metadata=run_record.metadata,
        )

    if (
        (input_discovery_res.status != InputDiscoveryStatus.SUCCESS or not repo_spec.discovered_inputs)
        and not req.custom_inputs
    ):
        inconclusive_run_id = f"run_{hashlib.sha256(f'{analysis_result.application_id}_insufficient_inputs_{datetime.now(timezone.utc).isoformat()}'.encode()).hexdigest()[:16]}"
        run_record = WorkflowRun(
            workflow_run_id=inconclusive_run_id,
            application_id=analysis_result.application_id,
            request_fingerprint=analysis_result.specification_fingerprint,
            state=WorkflowState.INCONCLUSIVE,
            finalization_state=FinalizationState.COMPLETED,
            certification_status="INSUFFICIENT_COVERAGE",
            error_code=WorkflowErrorCode.CERTIFICATION_INCONCLUSIVE,
            error_message="Repository analysis discovered zero legitimate input test cases. Equivalence certification cannot proceed without genuine input evidence.",
            metadata={
                "error": "INSUFFICIENT_COVERAGE",
                "status": "INSUFFICIENT_COVERAGE",
                "diagnostic_message": "Zero legitimate input test cases discovered. Equivalence certification cannot proceed without genuine input evidence.",
                "evidence": input_discovery_res.provenance,
            },
        )
        workflow_persistence.save_run(run_record)
        return WorkflowResult(
            workflow_run_id=inconclusive_run_id,
            application_id=analysis_result.application_id,
            state=WorkflowState.INCONCLUSIVE,
            status="INSUFFICIENT_COVERAGE",
            certified=False,
            equivalence_score=None,
            artifact_id=None,
            regressions_count=0,
            regressions=[],
            audit_status="PERSISTED",
            error_code=WorkflowErrorCode.CERTIFICATION_INCONCLUSIVE,
            error_message="Zero legitimate input test cases discovered. Equivalence certification cannot proceed without genuine input evidence.",
            metadata=run_record.metadata,
        )

    test_inputs = list(input_discovery_res.test_inputs)
    if req.custom_inputs:
        if len(test_inputs) + len(req.custom_inputs) > settings.max_input_records:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"The combined discovered and caller-supplied test input count may not exceed "
                    f"{settings.max_input_records}."
                ),
            )
        for index, values in enumerate(req.custom_inputs, start=1):
            if not values:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Caller-supplied test input #{index} must be a non-empty JSON object.",
                )
            test_inputs.append(
                CertificationTestInput(
                    input_id=f"USER-INP-{index:04d}",
                    values=values,
                    origin="explicit_case",
                    provenance={"source": "user_supplied", "index": index},
                )
            )
        repo_spec.discovered_inputs = [item.values for item in test_inputs]
        repo_spec.input_set_identity = compute_input_set_canonical_hash(test_inputs)
        analysis_result.specification_fingerprint = repo_spec.specification_fingerprint
        analysis_result.inputs_count = len(test_inputs)
        analysis_result.inputs = [item.values for item in test_inputs[:5]]

    input_source_desc = input_discovery_res.discovery_source
    input_discovery_meta = {
        **(input_discovery_res.provenance or {}),
        "user_supplied_inputs_count": len(req.custom_inputs or []),
    }
    if req.custom_inputs:
        input_source_desc = (
            f"{input_source_desc}; " if input_source_desc else ""
        ) + f"{len(req.custom_inputs)} user-supplied input case(s)"

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

    # 6. Authoritative Bridge: Derive internal ApplicationSpec from RepositoryExecutionSpec
    spec = build_application_spec_from_repository_execution_spec(repo_spec)
    application_repository.save_application(spec)

    # 7. Execute canonical V2 workflow engine (deterministic threshold engine handles resolution)
    wf_req = WorkflowRunRequest(
        application_id=spec.application_id,
        target_index=0,
        authoritative_input_set=test_inputs,
        custom_inputs=None,
        policy_override=None,
        explain=req.explain,
        explanation_mode=req.explanation_mode,
        enable_discovery=(req.evaluation_mode in ("FULL", "FULL_BEACON")),
        evaluation_mode=req.evaluation_mode,
        idempotency_key=req.idempotency_key,
        user_id=current_user.user_id,
        force_recompute=getattr(req, "force_recompute", True),
    )

    result = workflow_engine.execute_workflow(wf_req, spec_override=spec)

    # 7. Enrich result metadata with repository facts and execution authority objects
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
    result.metadata["discovered_rules"] = getattr(analysis_result, "rules", None) or getattr(analysis_result, "discovered_rules", [])

    cob_plan_data = analysis_result.provenance.get("cobol_execution_plan") if (analysis_result and analysis_result.provenance) else None
    if cob_plan_data:
        result.metadata["cobol_execution_plan"] = cob_plan_data
        cics_operations = cob_plan_data.get("cics_operations", [])
        result.metadata["cobol_execution"] = {
            "runtime": "GnuCOBOL",
            "cics_operations": cics_operations,
            "cics_execution_mode": "COMPATIBILITY_EMULATION" if cics_operations else "NOT_APPLICABLE",
            "genuine_cics_execution": False if cics_operations else None,
            "limitations": (
                ["CICS commands are transformed to a standalone compatibility harness; this is not genuine CICS execution."]
                if cics_operations
                else []
            ),
        }

    if result.threshold_resolution_id:
        th_res = threshold_persistence.get_resolution(result.threshold_resolution_id)
        if th_res:
            result.metadata["threshold_resolution"] = {
                "resolution_id": th_res.resolution_id,
                "metric": th_res.metric.value if hasattr(th_res.metric, "value") else str(th_res.metric),
                "strategy": th_res.strategy.value if hasattr(th_res.strategy, "value") else str(th_res.strategy),
                "status": th_res.status.value if hasattr(th_res.status, "value") else str(th_res.status),
                "raw_value": th_res.raw_value,
                "final_value": th_res.final_value,
                "sample_count": th_res.sample_count,
                "minimum_required_samples": th_res.minimum_required_samples,
                "estimator": th_res.estimator.value if hasattr(th_res.estimator, "value") else (str(th_res.estimator) if th_res.estimator else None),
                "outlier_policy": th_res.outlier_policy.value if hasattr(th_res.outlier_policy, "value") else (str(th_res.outlier_policy) if th_res.outlier_policy else "NONE"),
                "outliers_detected": th_res.outliers_detected,
                "fingerprint": th_res.fingerprint,
                "fallback_used": th_res.fallback_used,
            }

    if result.artifact_id:
        try:
            persisted_cases = certification_repository.list_certification_cases(result.artifact_id, limit=20)
            rep_cases = []
            for c in persisted_cases:
                rep_cases.append({
                    "case_index": c.case_index,
                    "input": json.loads(c.input_json) if isinstance(c.input_json, str) else c.input_json,
                    "legacy_output": json.loads(c.legacy_output_json) if isinstance(c.legacy_output_json, str) else c.legacy_output_json,
                    "modern_output": json.loads(c.modern_output_json) if isinstance(c.modern_output_json, str) else c.modern_output_json,
                    "oracle_result": c.oracle_result,
                    "classification": c.classification,
                })
            result.metadata["representative_cases"] = rep_cases
        except Exception as c_err:
            logger.debug(f"Representative cases extraction note: {c_err}")

        try:
            from intelligence.persistence import intelligence_persistence
            expl = intelligence_persistence.get_explanation(result.artifact_id)
            if expl:
                expl_dict = {
                    "verdict": expl.overall_verdict,
                    "summary": expl.executive_summary,
                    "executive_summary": expl.executive_summary,
                    "behavioral_summary": expl.behavioral_summary,
                    "status_rationale": expl.executive_summary,
                    "mode": expl.generation_metadata.generation_mode if expl.generation_metadata else "DETERMINISTIC",
                    "provider": expl.generation_metadata.provider if expl.generation_metadata else "offline",
                    "authoritative_match_status": expl.authoritative_match_status,
                }
                result.explanation = expl_dict
                result.metadata["explanation"] = expl_dict
        except Exception as e_err:
            logger.debug(f"Explanation attachment note: {e_err}")

    persisted_run = workflow_persistence.get_run(result.workflow_run_id)
    if persisted_run:
        result.metadata["execution_fingerprint"] = persisted_run.execution_fingerprint
        result.metadata["finalization_state"] = persisted_run.finalization_state.value if persisted_run.finalization_state else "COMPLETED"
        result.metadata["oracle_set_id"] = persisted_run.oracle_set_id
        result.metadata["oracle_set_hash"] = persisted_run.oracle_set_hash
        try:
            persisted_run.metadata = {**(persisted_run.metadata or {}), **result.metadata}
            workflow_persistence.save_run(persisted_run)
        except Exception as p_err:
            logger.debug(f"Could not update run metadata: {p_err}")

    return result


@workflow_router.post(
    "/sources/upload",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Upload source files or archives for direct file/directory ingestion",
)
async def upload_sources_endpoint(
    legacy_files: list[UploadFile] = File(...),
    modern_files: list[UploadFile] = File(...),
    scope: Optional[str] = Form(None),
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Securely stages uploaded source files or archives and returns deterministic source specifications."""
    try:
        import uuid
        upload_id = f"upl_{uuid.uuid4().hex[:12]}"

        leg_items = []
        for lf in legacy_files:
            content = await lf.read()
            leg_items.append((lf.filename or "legacy_source", content))

        mod_items = []
        for mf in modern_files:
            content = await mf.read()
            mod_items.append((mf.filename or "modern_source", content))

        staged = repository_service.stage_uploaded_sources(
            upload_id=upload_id,
            legacy_files=leg_items,
            modern_files=mod_items,
            preferred_scope=scope,
        )
        return staged
    except Exception as exc:
        logger.error(f"Source file upload failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "SOURCE_UPLOAD_FAILED",
                "message": str(exc),
            },
        )


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
    _, _, _, _, _, _, _, analysis_result, _ = _perform_repository_analysis(req)
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
    "/runs/{run_id}/export",
    status_code=status.HTTP_200_OK,
    summary="Download a PDF report for a workflow run without a certificate",
)
def export_workflow_run_report(
    run_id: str,
    current_user: User = Depends(get_current_active_user),
) -> Response:
    """Exports a failed or inconclusive run as a clearly non-certifying PDF report."""
    run = workflow_persistence.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run '{run_id}' not found.",
        )
    verify_user_project_permission(current_user, run.application_id, Permission.VIEW)
    run_payload = run.model_dump(mode="json")
    metadata = run_payload.get("metadata") or {}
    explanation = metadata.get("explanation") if isinstance(metadata, dict) else None
    ai_summary = None
    if isinstance(explanation, dict):
        ai_summary = explanation.get("executive_summary") or explanation.get("summary")
    pdf_content = generate_workflow_run_pdf_report(run_payload, ai_summary=ai_summary)
    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=beacon_run_{run_id}.pdf"},
    )


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
