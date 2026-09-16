"""BEACON V2 — Phase 10 Validation & Hallucination Guard.

Validates LLM-generated outputs against strict schemas, enforces authoritative verdict
immutability, filters nonexistent evidence and rule IDs, validates factual values,
and guards against hallucinated claims.
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

        # Build authoritative lookup maps for factual value validation
        valid_evid_set = set(context.valid_evidence_ids)
        valid_input_set = set(context.valid_input_ids)
        valid_rule_set = set(context.valid_rule_ids)

        # Map input_id -> diff record
        diffs_by_input: dict[str, dict[str, Any]] = {}
        for diff in context.differences_summary:
            inp_id = diff.get("input_id")
            if inp_id:
                diffs_by_input[inp_id] = diff

        # 3. Dimension Explanations Validation
        raw_dims = raw_payload.get("dimension_explanations", [])
        validated_dims: list[DimensionExplanation] = []

        # Canonical behavior dimensions allowed
        allowed_dimensions = {d.value: d for d in BehaviorDimension}

        if isinstance(raw_dims, list):
            for raw_d in raw_dims:
                if not isinstance(raw_d, dict):
                    continue
                dim_str = str(raw_d.get("dimension", "")).strip().upper()

                # No Invalid Dimension Coercion
                if dim_str not in allowed_dimensions:
                    errors.append(f"Invalid dimension '{dim_str}' rejected (no coercion to OUTPUT).")
                    continue

                dim_enum = allowed_dimensions[dim_str]

                # Filter referenced evidence IDs
                raw_evids = raw_d.get("evidence_ids", [])
                filtered_evids = [eid for eid in raw_evids if eid in valid_evid_set] if isinstance(raw_evids, list) else []

                # No Default PASS! Derive status from authoritative context if missing or invalid
                raw_status = raw_d.get("status")
                dim_diffs = [
                    d for d in context.differences_summary
                    if str(d.get("dimension", "")).upper() == dim_enum.value
                ]
                missing_for_dim = [m for m in context.missing_evidence if m.dimension == dim_enum]

                if not raw_status or not isinstance(raw_status, str):
                    if dim_diffs:
                        dim_status = "DIFFERENT"
                    elif missing_for_dim:
                        dim_status = "INCONCLUSIVE"
                    else:
                        dim_status = "PASS"
                else:
                    status_upper = raw_status.strip().upper()
                    if status_upper in ("PASS", "DIFFERENT", "INCONCLUSIVE", "NOT_APPLICABLE", "ERROR", "UNKNOWN"):
                        dim_status = status_upper
                    else:
                        dim_status = "DIFFERENT" if dim_diffs else ("INCONCLUSIVE" if missing_for_dim else "UNKNOWN")

                # Filter findings & validate factual values
                raw_findings = raw_d.get("findings", [])
                validated_findings: list[ExplanationFinding] = []
                if isinstance(raw_findings, list):
                    for f_idx, rf in enumerate(raw_findings):
                        if not isinstance(rf, dict) or not rf.get("statement"):
                            continue

                        f_evids_raw = rf.get("evidence_ids", [])
                        if isinstance(f_evids_raw, list):
                            invalid_evids = [eid for eid in f_evids_raw if eid not in valid_evid_set]
                            if invalid_evids:
                                errors.append(f"Invalid evidence IDs {invalid_evids} in finding rejected.")
                            f_evids = [eid for eid in f_evids_raw if eid in valid_evid_set]
                        else:
                            f_evids = []

                        inp_id = rf.get("input_id")
                        if inp_id and valid_input_set and inp_id not in valid_input_set:
                            errors.append(f"Hallucinated input_id '{inp_id}' in finding rejected.")
                            continue

                        ref_val = rf.get("reference_value")
                        tgt_val = rf.get("target_value")

                        # Factual value validation against authoritative diffs
                        if inp_id and inp_id in diffs_by_input:
                            auth_diff = diffs_by_input[inp_id]
                            auth_ref = auth_diff.get("reference_value")
                            auth_tgt = auth_diff.get("target_value")

                            # If model specified differing values, reject factual claim
                            if ref_val is not None and auth_ref is not None:
                                if str(ref_val) != str(auth_ref) and ref_val != auth_ref:
                                    errors.append(f"Factual value mismatch for input '{inp_id}': LLM ref='{ref_val}' vs authoritative='{auth_ref}'. Claim rejected.")
                                    continue
                            if tgt_val is not None and auth_tgt is not None:
                                if str(tgt_val) != str(auth_tgt) and tgt_val != auth_tgt:
                                    errors.append(f"Factual value mismatch for input '{inp_id}': LLM tgt='{tgt_val}' vs authoritative='{auth_tgt}'. Claim rejected.")
                                    continue

                        support_str = str(rf.get("support", "DETERMINISTIC_FACT")).upper()
                        try:
                            support_enum = EvidenceSupportLevel(support_str)
                        except ValueError:
                            support_enum = EvidenceSupportLevel.DETERMINISTIC_FACT

                        validated_findings.append(
                            ExplanationFinding(
                                finding_id=rf.get("finding_id") or f"FIND-{dim_enum.value}-{f_idx+1}",
                                dimension=dim_enum,
                                statement=str(rf.get("statement", "")),
                                support=support_enum,
                                evidence_ids=f_evids,
                                input_id=inp_id,
                                reference_value=ref_val,
                                target_value=tgt_val,
                                difference_details=rf.get("difference_details", {}) if isinstance(rf.get("difference_details"), dict) else {},
                            )
                        )

                validated_dims.append(
                    DimensionExplanation(
                        dimension=dim_enum,
                        status=dim_status,
                        reference_summary=str(raw_d.get("reference_summary", "")),
                        target_summary=str(raw_d.get("target_summary", "")),
                        difference_summary=str(raw_d.get("difference_summary", "")),
                        tolerance_applied=raw_d.get("tolerance_applied"),
                        evidence_ids=filtered_evids,
                        findings=validated_findings,
                    )
                )

        # 4. Rule Impacts Validation (No Invented Rule IDs)
        raw_rules = raw_payload.get("rule_impacts", [])
        validated_rules: list[RuleImpact] = []

        if isinstance(raw_rules, list):
            for raw_r in raw_rules:
                if not isinstance(raw_r, dict):
                    continue
                rule_id = str(raw_r.get("rule_id", "")).strip()

                if not rule_id:
                    errors.append("Rule impact with missing rule_id rejected.")
                    continue

                if valid_rule_set and rule_id not in valid_rule_set:
                    errors.append(f"Hallucinated rule_id '{rule_id}' rejected by validator.")
                    continue

                r_evids = [eid for eid in raw_r.get("supporting_evidence_ids", []) if eid in valid_evid_set] if isinstance(raw_r.get("supporting_evidence_ids"), list) else []

                validated_rules.append(
                    RuleImpact(
                        rule_id=rule_id,
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
                support_str = str(un.get("support_level", "INFERENCE")).upper()
                try:
                    sup_enum = EvidenceSupportLevel(support_str)
                except ValueError:
                    sup_enum = EvidenceSupportLevel.INFERENCE

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

        # 7. Construct Full Explanation with Authoritative Ground Truth
        fp = context.compute_context_fingerprint()
        mode_tag = metadata.generation_mode.lower()[:4]
        explanation_id = f"EXP-{context.certification_id[:8]}-{fp[:8]}-{mode_tag}"
        cache_key = context.compute_cache_key(
            mode=metadata.generation_mode.lower(),
            use_company_knowledge=bool(context.knowledge_context),
            prompt_version=metadata.prompt_version,
        )

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
            evidence_traces=[],  # Will be merged from deterministic baseline
            affected_inputs=[],   # Will be merged from deterministic baseline
            missing_evidence=context.missing_evidence,
            uncertainty_notes=validated_uncertainties,
            company_knowledge_context=context.knowledge_context,
            investigation_recommendations=validated_recs,
            context_fingerprint=fp,
            cache_key=cache_key,
            generation_metadata=metadata,
        )
        explanation.content_hash = explanation.compute_content_hash()

        return True, errors, explanation


explanation_validator = ExplanationValidator()
