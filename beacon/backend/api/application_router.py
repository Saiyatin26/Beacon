"""BEACON V2 — Domain-Agnostic Application API Router.

Provides endpoints for registering, querying, and certifying arbitrary applications
independent of pre-packaged benchmark scenarios.
"""

import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from application import (
    ApplicationRegistry,
    ApplicationResolver,
    ApplicationSpec,
    application_registry,
)
from auth import get_current_active_user, User
from certification import (
    CertificationArtifact,
    CertificationContext,
    CertificationPolicy,
    certification_engine,
    certification_repository,
)
from llm.explanation import CertificationExplainer

logger = logging.getLogger("beacon.api.applications")

application_router = APIRouter(prefix="/api/v2/applications", tags=["Applications V2"])
application_resolver = ApplicationResolver()
certification_explainer = CertificationExplainer()


class ApplicationCertifyRequest(BaseModel):
    """Request payload for certifying an application."""
    target_index: int = 0
    sample_count: Optional[int] = None
    custom_inputs: Optional[list[dict[str, Any]]] = None
    policy_min_equivalence_score: float = 0.999
    policy_min_oracle_coverage: float = 0.0
    allow_warnings: bool = False
    explain: bool = False


@application_router.post(
    "",
    response_model=ApplicationSpec,
    status_code=status.HTTP_201_CREATED,
    summary="Register or update an ApplicationSpec",
)
def register_application(
    spec: ApplicationSpec,
    current_user: User = Depends(get_current_active_user),
):
    """Registers an application for behavioral equivalence certification."""
    try:
        registered = application_registry.register_application(spec)
        return registered
    except Exception as exc:
        logger.error(f"Failed to register application: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Application registration failed: {str(exc)}",
        )


@application_router.get(
    "",
    response_model=list[ApplicationSpec],
    summary="List registered applications",
)
def list_applications(
    domain: Optional[str] = Query(None, description="Optional domain filter metadata (e.g. 'agriculture', 'banking')"),
    current_user: User = Depends(get_current_active_user),
):
    """Lists all registered applications, optionally filtered by domain metadata."""
    return application_registry.list_applications(domain=domain)


@application_router.get(
    "/{app_id}",
    response_model=ApplicationSpec,
    summary="Get ApplicationSpec by ID",
)
def get_application(
    app_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Retrieves an application specification by its identifier."""
    app = application_registry.get_application(app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )
    return app


@application_router.delete(
    "/{app_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unregister an application",
)
def delete_application(
    app_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Removes an application from the registry."""
    success = application_registry.unregister_application(app_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )


@application_router.post(
    "/{app_id}/certify",
    summary="Execute behavioral equivalence certification for an application",
)
def certify_application(
    app_id: str,
    req: ApplicationCertifyRequest = ApplicationCertifyRequest(),
    current_user: User = Depends(get_current_active_user),
):
    """Executes deterministic behavioral equivalence certification for an application."""
    spec = application_registry.get_application(app_id)
    if not spec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )

    try:
        # 1. Resolve adapters
        ref_adapter, target_adapter = application_resolver.resolve_adapters(
            spec=spec,
            target_index=req.target_index,
        )

        # 2. Resolve inputs
        test_inputs = application_resolver.resolve_inputs(
            spec=spec,
            custom_inputs=req.custom_inputs,
        )

        # 3. Resolve OracleSet
        oracle_set = application_resolver.resolve_oracle_set(spec=spec)

        # 4. Construct execution policy
        policy = CertificationPolicy(
            policy_id=f"POL-{spec.application_id}",
            min_equivalence_score=req.policy_min_equivalence_score,
            min_oracle_coverage=req.policy_min_oracle_coverage,
            min_applicable_probes_per_oracle=0,
            allow_warnings=req.allow_warnings,
            block_on_critical_regression=True,
            block_on_reference_inconsistent=True,
        )

        # 5. Build context
        context = CertificationContext(
            benchmark_id=spec.application_id,
            benchmark_name=spec.name,
            benchmark_version=spec.version,
            legacy_implementation_id=ref_adapter.name,
            legacy_implementation_hash=getattr(ref_adapter, "implementation_hash", ""),
            modernized_implementation_id=target_adapter.name,
            modernized_implementation_hash=getattr(target_adapter, "implementation_hash", ""),
            oracle_set_id=oracle_set.oracle_set_id,
            oracle_set_hash=getattr(oracle_set, "oracle_set_hash", ""),
            evaluation_mode=spec.rule_config.mode if spec.rule_config else "CONTROLLED",
            policy_min_equivalence_score=req.policy_min_equivalence_score,
            policy_allow_warnings=req.allow_warnings,
        )

        # 6. Execute deterministic certification
        artifact = certification_engine.certify(
            legacy_adapter=ref_adapter,
            modern_adapter=target_adapter,
            test_inputs=test_inputs,
            oracle_set=oracle_set,
            context=context,
            policy=policy,
        )

        # 7. Persist artifact
        certification_repository.save_artifact(artifact)

        status_val = artifact.certification_status.value if hasattr(artifact.certification_status, "value") else str(artifact.certification_status)
        response_payload: dict[str, Any] = {
            "application_id": spec.application_id,
            "application_name": spec.name,
            "domain": spec.domain,
            "status": status_val,
            "equivalence_score": artifact.equivalence_score,
            "artifact_id": artifact.artifact_id,
            "artifact_hash": artifact.artifact_hash,
            "unique_input_count": artifact.metrics.unique_input_count if artifact.metrics else len(test_inputs),
            "regressions_count": len(artifact.regressions),
            "regressions": [r.model_dump() for r in artifact.regressions[:10]],
        }

        # 8. Optional post-certification AI explanation
        if req.explain:
            explanation = certification_explainer.generate_explanation(artifact)
            response_payload["explanation"] = explanation

        return response_payload

    except Exception as exc:
        logger.error(f"Certification failed for application '{app_id}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Certification execution failed: {str(exc)}",
        )
