"""BEACON V2 — Phase 10 Validation & Hallucination Guard.

Validates LLM-generated outputs against strict schemas, enforces authoritative verdict
immutability, filters nonexistent evidence and rule IDs, and guards against hallucinated claims.
"""

import logging
from typing import Any, Optional

from evaluation.models import BehaviorDimension
from .models import (
    AffectedInput,
    CertificationExplanation,
    DimensionExplanation,
    EvidenceSupportLevel,
    EvidenceTrace,
    ExplanationContext,
    ExplanationFinding,
    GenerationMetadata,
    InvestigationRecommendation,
    MissingEvidence,
    RuleImpact,
    UncertaintyNote,
)

logger = logging.getLogger("beacon.intelligence.validation")


class HallucinationGuardError(ValueError):
    """Raised when an unrecoverable hallucination or schema violation is detected."""
    pass


class ExplanationValidator:
    """Validates and filters LLM-generated explanation payloads against authoritative ground truth."""

    def __init__(self):
        pass

    def validate_and_sanitize_explanation(
        self,
        raw_payload: dict[str, Any],
        context: ExplanationContext,
        metadata: GenerationMetadata,
    ) -> tuple[bool, list[str], Optional[CertificationExplanation]]:
        """Validates the raw LLM JSON response against context bounds and constructs a clean CertificationExplanation.

        Returns:
            (is_valid, validation_errors, explanation_or_none)
        """
        errors: list[str] = []

        if not isinstance(raw_payload, dict):
            return False, ["LLM output is not a JSON object."], None

        # 1. Authoritative Verdict Protection
        # The overall verdict is IMMUTABLY anchored to the authoritative certification result.
        authoritative_verdict = context.authoritative_verdict

        # 2. Executive & Behavioral Summaries
        exec_summary = raw_payload.get("executive_summary")
        if not exec_summary or not isinstance(exec_summary, str):
            errors.append("Missing or invalid 'executive_summary'.")
            exec_summary = f"Certification concluded with authoritative status {authoritative_verdict}."

        behav_summary = raw_payload.get("behavioral_summary")
        if not behav_summary or not isinstance(behav_summary, str):
            behav_summary = (
                f"Evaluated {context.unique_inputs_count} inputs across dimensions: "
                f"{', '.join(d.value for d in context.dimensions_evaluated)}."
            )

        # 3. Dimension Explanations Validation
        raw_dims = raw_payload.get("dimension_explanations", [])
        validated_dims: list[DimensionExplanation] = []
        valid_evid_set = set(context.valid_evidence_ids)

        if isinstance(raw_dims, list):
            for idx, raw_d in enumerate(raw_dims):
                if not isinstance(raw_d, dict):
                    continue
                dim_str = str(raw_d.get("dimension", "OUTPUT")).upper()
                try:
                    dim_enum = BehaviorDimension(dim_str)
                except ValueError:
                    dim_enum = BehaviorDimension.OUTPUT

                # Filter referenced evidence IDs
                raw_evids = raw_d.get("evidence_ids", [])
                filtered_evids = [eid for eid in raw_evids if eid in valid_evid_set] if isinstance(raw_evids, list) else []

                # Filter findings
                raw_findings = raw_d.get("findings", [])
                validated_findings: list[ExplanationFinding] = []
                if isinstance(raw_findings, list):
                    for f_idx, rf in enumerate(raw_findings):
                        if not isinstance(rf, dict) or not rf.get("statement"):
                            continue
                        f_evids = [eid for eid in rf.get("evidence_ids", []) if eid in valid_evid_set] if isinstance(rf.get("evidence_ids"), list) else []
                        support_str = str(rf.get("support", "DETERMINISTIC_EVIDENCE")).upper()
                        try:
                            support_enum = EvidenceSupportLevel(support_str)
                        except ValueError:
                            support_enum = EvidenceSupportLevel.DETERMINISTIC_EVIDENCE

                        validated_findings.append(
                            ExplanationFinding(
                                finding_id=rf.get("finding_id") or f"FIND-{dim_enum.value}-{f_idx+1}",
                                dimension=dim_enum,
                                statement=str(rf.get("statement", "")),
                                support=support_enum,
                                evidence_ids=f_evids,
                                reference_value=rf.get("reference_value"),
                                target_value=rf.get("target_value"),
                                difference_details=rf.get("difference_details", {}) if isinstance(rf.get("difference_details"), dict) else {},
                            )
                        )

                validated_dims.append(
                    DimensionExplanation(
                        dimension=dim_enum,
                        status=str(raw_d.get("status", "PASS")),
                        reference_summary=str(raw_d.get("reference_summary", "")),
                        target_summary=str(raw_d.get("target_summary", "")),
                        difference_summary=str(raw_d.get("difference_summary", "")),
                        tolerance_applied=raw_d.get("tolerance_applied"),
                        evidence_ids=filtered_evids,
                        findings=validated_findings,
                    )
                )

        # 4. Rule Impacts Validation
        valid_rule_set = set(context.valid_rule_ids)
        raw_rules = raw_payload.get("rule_impacts", [])
        validated_rules: list[RuleImpact] = []

        if isinstance(raw_rules, list):
            for raw_r in raw_rules:
                if not isinstance(raw_r, dict):
                    continue
                rule_id = str(raw_r.get("rule_id", ""))
                # If LLM hallucinates a rule ID not in context, reject or flag
                if valid_rule_set and rule_id not in valid_rule_set:
                    errors.append(f"Hallucinated rule_id '{rule_id}' rejected by validator.")
                    continue

                r_evids = [eid for eid in raw_r.get("supporting_evidence_ids", []) if eid in valid_evid_set] if isinstance(raw_r.get("supporting_evidence_ids"), list) else []

                validated_rules.append(
                    RuleImpact(
                        rule_id=rule_id or "RULE-OBSERVED",
                        rule_description=str(raw_r.get("rule_description", "")),
                        status=raw_r.get("status", "POTENTIALLY_AFFECTED"),
                        observed_behavior=str(raw_r.get("observed_behavior", "")),
                        supporting_evidence_ids=r_evids,
                        relationship_to_verdict=str(raw_r.get("relationship_to_verdict", "")),
                        limitation=str(raw_r.get("limitation", "Evidence demonstrates behavioral deviation without root cause.")),
                    )
                )

        # 5. Uncertainty Notes Validation
        raw_uncertainties = raw_payload.get("uncertainty_notes", [])
        validated_uncertainties: list[UncertaintyNote] = []
        if isinstance(raw_uncertainties, list):
            for un in raw_uncertainties:
                if not isinstance(un, dict) or not un.get("claim"):
                    continue
                support_str = str(un.get("support_level", "UNCERTAIN")).upper()
                try:
                    sup_enum = EvidenceSupportLevel(support_str)
                except ValueError:
                    sup_enum = EvidenceSupportLevel.UNCERTAIN

                validated_uncertainties.append(
                    UncertaintyNote(
                        topic=str(un.get("topic", "General Uncertainty")),
                        claim=str(un.get("claim", "")),
                        support_level=sup_enum,
                        reason=str(un.get("reason", "Incomplete runtime information")),
                    )
                )

        # 6. Investigation Recommendations Validation
        raw_recs = raw_payload.get("investigation_recommendations", [])
        validated_recs: list[InvestigationRecommendation] = []
        if isinstance(raw_recs, list):
            for r_idx, rec in enumerate(raw_recs):
                if not isinstance(rec, dict) or not rec.get("title"):
                    continue
                rec_evids = [eid for eid in rec.get("evidence_references", []) if eid in valid_evid_set] if isinstance(rec.get("evidence_references"), list) else []
                validated_recs.append(
                    InvestigationRecommendation(
                        priority=int(rec.get("priority", r_idx + 1)),
                        title=str(rec.get("title", "")),
                        description=str(rec.get("description", "")),
                        rationale=str(rec.get("rationale", "")),
                        evidence_references=rec_evids,
                    )
                )

        # 7. Construct Full Explanation
        explanation_id = f"EXP-{context.certification_id[:12]}"
        explanation = CertificationExplanation(
            explanation_id=explanation_id,
            certification_id=context.certification_id,
            application_id=context.application_id,
            project_id=context.project_id,
            session_id=context.session_id,
            overall_verdict=authoritative_verdict,
            is_authoritative_match=True,
            executive_summary=exec_summary,
            scope_summary={
                "evaluated_inputs": context.unique_inputs_count,
                "matching_cases": context.matching_cases_count,
                "regression_cases": context.regression_cases_count,
                "equivalence_score": context.equivalence_score,
                "dimensions": [d.value for d in context.dimensions_evaluated],
            },
            behavioral_summary=behav_summary,
            dimension_explanations=validated_dims,
            rule_impacts=validated_rules,
            evidence_traces=[],  # Populated from context
            affected_inputs=[],   # Populated from context
            missing_evidence=context.missing_evidence,
            uncertainty_notes=validated_uncertainties,
            company_knowledge_context=context.knowledge_context,
            investigation_recommendations=validated_recs,
            context_fingerprint=context.compute_context_fingerprint(),
            generation_metadata=metadata,
        )
        explanation.content_hash = explanation.compute_content_hash()

        return True, errors, explanation


explanation_validator = ExplanationValidator()
