"""BEACON V2 — Certification Intelligence & Explanation Boundary.

CRITICAL ARCHITECTURAL PRINCIPLE:
The LLM / AI intelligence layer NEVER determines certification outcomes.
Certification status (CERTIFIED, NOT_CERTIFIED, CERTIFIED_WITH_WARNINGS) is
strictly computed by the deterministic behavioral certification engine.

The Intelligence layer operates purely post-decision to generate explanations,
summarize regressions, and provide remediation guidance for human engineers.
"""

import logging
from typing import Any, Optional

from certification.models import CertificationArtifact, CertificationStatus
from llm.manager import get_provider_manager

logger = logging.getLogger("beacon.llm.explanation")


class CertificationExplainer:
    """Generates human-readable explanations and remediation guidance from deterministic artifacts."""

    def __init__(self):
        self.llm_manager = get_provider_manager()

    def generate_explanation(
        self,
        artifact: CertificationArtifact,
        include_remediation: bool = True,
    ) -> dict[str, Any]:
        """Produces structured explanation from an immutable CertificationArtifact."""
        status = artifact.certification_status
        score = artifact.equivalence_score
        regressions = artifact.regressions

        summary_lines = [
            f"Equivalence Score: {score * 100:.2f}%",
            f"Status: {status.value if hasattr(status, 'value') else str(status)}",
            f"Total Test Cases: {artifact.metrics.unique_input_count if artifact.metrics else len(artifact.cases)}",
            f"Regressions Detected: {len(regressions)}",
        ]

        # Generate deterministic baseline summary
        baseline_explanation = (
            f"Certification evaluation concluded with status {status}. "
            f"The candidate implementation achieved a quantified behavioral equivalence score of {score * 100:.2f}%. "
            f"{'Zero behavioral regressions were detected.' if len(regressions) == 0 else f'{len(regressions)} counterexamples were identified where the candidate deviated from reference behavior.'}"
        )

        remediation_suggestions = []
        if regressions:
            for reg in regressions[:5]:
                remediation_suggestions.append({
                    "regression_id": getattr(reg, "regression_id", "REG-001"),
                    "failed_assertion": getattr(reg, "failed_assertion", ""),
                    "input_values": getattr(reg, "input_values", {}),
                    "legacy_output": getattr(reg, "legacy_output", ""),
                    "modern_output": getattr(reg, "modern_output", ""),
                    "suggestion": "Inspect condition boundaries and ensure output transformation matches reference logic.",
                })

        return {
            "artifact_id": artifact.artifact_id,
            "status": str(status),
            "score": score,
            "summary": "\n".join(summary_lines),
            "explanation": baseline_explanation,
            "regressions_analyzed": len(regressions),
            "remediation_suggestions": remediation_suggestions if include_remediation else [],
            "deterministic_authority": True,
        }
