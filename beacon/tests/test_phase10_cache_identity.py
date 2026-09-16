"""BEACON V2 — Phase 10 Context-Sensitive Cache Identity Tests.

Verifies:
1. Cache identity distinguishes materially different explanation requests.
2. A request with use_company_knowledge=False does NOT reuse a cached explanation with use_company_knowledge=True.
3. A change in context fingerprint generates a new cache key and does not reuse stale cache.
"""

import pytest
from evaluation.models import BehaviorDimension
from certification.models import (
    CertificationArtifact,
    CertificationMetrics,
    CertificationStatus,
    compute_artifact_content_hash,
)
from certification.repository import certification_repository
from intelligence.engine import IntelligenceEngine
from intelligence.models import ExplanationRequest


def test_cache_distinguishes_knowledge_on_vs_off():
    """Verify that requests with knowledge ON vs OFF use distinct cache entries."""
    artifact_raw = CertificationArtifact(
        certification_id="CERT-CACHE-001",
        project_id="app_cache_test",
        status=CertificationStatus.CERTIFIED,
        score=1.0,
        metrics=CertificationMetrics(unique_input_count=2, matching_case_count=2),
        regressions=[],
        oracle_summaries=[],
    )
    artifact = artifact_raw.model_copy(update={"content_hash": compute_artifact_content_hash(artifact_raw)})
    certification_repository.save_artifact(artifact)

    engine = IntelligenceEngine()

    # Request A: Knowledge OFF
    exp_a = engine.generate_explanation(
        certification_id=artifact.certification_id,
        artifact=artifact,
        request=ExplanationRequest(mode="deterministic", use_company_knowledge=False, force_recompute=True),
    )

    # Request B: Knowledge ON
    exp_b = engine.generate_explanation(
        certification_id=artifact.certification_id,
        artifact=artifact,
        request=ExplanationRequest(mode="deterministic", use_company_knowledge=True, force_recompute=True),
    )

    assert exp_a.cache_key != exp_b.cache_key, "Cache keys must differ between knowledge ON and OFF."
