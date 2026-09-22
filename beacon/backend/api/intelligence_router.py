"""BEACON V2 — Phase 10 Intelligence & Explanation REST API Router.

Exposes endpoints to generate, retrieve, and query audit-grade structured explanations
for authoritative certification results, backed by RBAC authorization and safe error handling.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth import (
    Permission,
    User,
    get_current_active_user,
    verify_user_project_permission,
)
from certification.repository import certification_repository
from intelligence.engine import intelligence_engine
from intelligence.models import (
    AskCertificationRequest,
    AskCertificationResponse,
    CertificationExplanation,
    ExplanationRequest,
)
from intelligence.persistence import intelligence_persistence

logger = logging.getLogger("beacon.api.intelligence")

intelligence_router = APIRouter(tags=["v2-intelligent-explanations"])


@intelligence_router.post(
    "/api/v2/certifications/{certification_id}/explanation",
    response_model=CertificationExplanation,
    status_code=status.HTTP_200_OK,
)
def generate_or_get_explanation(
    certification_id: str,
    req: ExplanationRequest = ExplanationRequest(),
    current_user: User = Depends(get_current_active_user),
) -> CertificationExplanation:
    """Generates or retrieves a structured, audit-grade certification explanation."""
    artifact = certification_repository.get_artifact(certification_id)
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certification artifact '{certification_id}' not found.",
        )

    # 1. Enforce RBAC Project/Application Authorization
    app_id = getattr(artifact, "application_id", None) or getattr(artifact, "project_id", None) or getattr(artifact, "benchmark_id", None) or ""
    verify_user_project_permission(current_user, app_id, Permission.VIEW)

    try:
        explanation = intelligence_engine.generate_explanation(
            certification_id=certification_id,
            artifact=artifact,
            request=req,
            user_id=current_user.user_id,
        )
        return explanation
    except HTTPException:
        raise
    except RuntimeError as exc:
        logger.error(f"Provider error generating explanation for cert '{certification_id}': {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )
    except Exception as exc:
        logger.error(f"Diagnostic error generating explanation for cert '{certification_id}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate certification explanation: {exc}",
        )


@intelligence_router.get(
    "/api/v2/certifications/{certification_id}/explanation",
    response_model=CertificationExplanation,
    status_code=status.HTTP_200_OK,
)
def get_persisted_explanation(
    certification_id: str,
    current_user: User = Depends(get_current_active_user),
) -> CertificationExplanation:
    """Retrieves an existing persisted certification explanation."""
    artifact = certification_repository.get_artifact(certification_id)
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certification artifact '{certification_id}' not found.",
        )

    app_id = getattr(artifact, "application_id", None) or getattr(artifact, "project_id", None) or getattr(artifact, "benchmark_id", None) or ""
    verify_user_project_permission(current_user, app_id, Permission.VIEW)

    explanation = intelligence_persistence.get_explanation(certification_id)
    if not explanation:
        # If not persisted yet, generate on-demand
        try:
            explanation = intelligence_engine.generate_explanation(
                certification_id=certification_id,
                artifact=artifact,
                request=ExplanationRequest(mode="deterministic"),
                user_id=current_user.user_id,
            )
        except Exception as exc:
            logger.error(f"Diagnostic error fetching explanation for '{certification_id}': {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve certification explanation.",
            )

    return explanation


@intelligence_router.post(
    "/api/v2/certifications/{certification_id}/ask",
    response_model=AskCertificationResponse,
    status_code=status.HTTP_200_OK,
)
def ask_certification_question(
    certification_id: str,
    req: AskCertificationRequest,
    current_user: User = Depends(get_current_active_user),
) -> AskCertificationResponse:
    """Interactively queries the certification explanation engine over authoritative context."""
    artifact = certification_repository.get_artifact(certification_id)
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certification artifact '{certification_id}' not found.",
        )

    app_id = getattr(artifact, "application_id", None) or getattr(artifact, "project_id", None) or getattr(artifact, "benchmark_id", None) or ""
    verify_user_project_permission(current_user, app_id, Permission.VIEW)

    if not req.question or not req.question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question string cannot be empty.",
        )

    try:
        response = intelligence_engine.ask_certification(
            certification_id=certification_id,
            question=req.question,
            artifact=artifact,
            use_company_knowledge=req.use_company_knowledge,
            preferred_provider=req.preferred_provider,
            user_id=current_user.user_id,
        )
        return response
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Diagnostic error asking question for cert '{certification_id}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process certification query.",
        )
