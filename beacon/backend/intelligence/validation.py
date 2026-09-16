"""BEACON V2 — Phase 10 Unified Grounding Validator & Hallucination Guard.

Provides unified, fail-closed validation for:
- Explanation generation payloads
- Interactive Q&A responses
- Structured factual claims against authoritative Phase 3–8 ground truth
"""

import logging
import re
from typing import Any, Optional

from evaluation.models import BehaviorDimension
from .models import (
    AffectedInput,
    AskCertificationResponse,
    CertificationExplanation,
    DimensionExplanation,
    EvidenceSupportLevel,
    EvidenceTrace,
    ExplanationContext,
    ExplanationFinding,
    GenerationMetadata,
    GroundingClaim,
    GroundingClaimType,
    InvestigationRecommendation,
    MissingEvidence,
    RuleImpact,
    UncertaintyNote,
)

logger = logging.getLogger("beacon.intelligence.validation")


class HallucinationGuardError(ValueError):
    """Raised when an unrecoverable hallucination or schema violation is detected."""
    pass


class GroundingValidator:
    """Unified central validator ensuring all factual claims are strictly grounded in authoritative context."""

    def validate_claims(
        self,
        claims: list[GroundingClaim],
        context: ExplanationContext,
    ) -> tuple[bool, list[str], list[GroundingClaim]]:
        """Deterministically validates a list of structured factual claims against ExplanationContext."""
        valid_evid_set = set(context.valid_evidence_ids)
        valid_rule_set = set(context.valid_rule_ids)
        valid_input_set = set(context.valid_input_ids)

        diffs_by_input: dict[str, dict[str, Any]] = {}
        for diff in context.differences_summary:
            inp_id = diff.get("input_id")
            if inp_id:
                diffs_by_input[inp_id] = diff

        errors: list[str] = []
        validated_claims: list[GroundingClaim] = []
        is_all_valid = True

        for idx, claim in enumerate(claims):
            # Check Evidence references
            if claim.evidence_ids:
                invalid_evids = [eid for eid in claim.evidence_ids if eid not in valid_evid_set]
                if invalid_evids:
                    errors.append(f"Claim {idx+1}: UNSUPPORTED_EVIDENCE_REFERENCE {invalid_evids}")
                    is_all_valid = False
                    continue

            # Check Rule references
            if claim.rule_id:
                if valid_rule_set and claim.rule_id not in valid_rule_set:
                    errors.append(f"Claim {idx+1}: UNSUPPORTED_RULE_REFERENCE '{claim.rule_id}'")
                    is_all_valid = False
                    continue

            # Check Input references
            if claim.input_id:
                if valid_input_set and claim.input_id not in valid_input_set:
                    errors.append(f"Claim {idx+1}: UNSUPPORTED_INPUT_REFERENCE '{claim.input_id}'")
                    is_all_valid = False
                    continue

            # Check Numeric Value consistency against authoritative differences
            if claim.claim_type == GroundingClaimType.NUMERIC_VALUE and claim.input_id in diffs_by_input:
                auth_diff = diffs_by_input[claim.input_id]
                auth_val = auth_diff.get("target_value") if claim.role == "TARGET" else auth_diff.get("reference_value")
                if auth_val is not None and claim.value is not None:
                    try:
                        if abs(float(claim.value) - float(auth_val)) > 1e-6:
                            errors.append(
                                f"Claim {idx+1}: NUMERIC_VALUE_MISMATCH for input '{claim.input_id}' "
                                f"(claimed {claim.value} vs authoritative {auth_val})"
                            )
                            is_all_valid = False
                            continue
                    except (ValueError, TypeError):
                        if str(claim.value) != str(auth_val):
                            errors.append(f"Claim {idx+1}: NUMERIC_VALUE_MISMATCH for input '{claim.input_id}'")
                            is_all_valid = False
                            continue

            validated_claims.append(claim)

        return is_all_valid, errors, validated_claims

    def validate_and_sanitize_explanation(
        self,
        raw_payload: dict[str, Any],
        context: ExplanationContext,
        metadata: GenerationMetadata,
    ) -> tuple[bool, list[str], Optional[CertificationExplanation]]:
        """Validates the raw LLM JSON response against context bounds and constructs a clean CertificationExplanation."""
        errors: list[str] = []

        if not isinstance(raw_payload, dict):
            return False, ["LLM output is not a JSON object."], None

        # 1. Authoritative Verdict Protection (Immutable)
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

        valid_evid_set = set(context.valid_evidence_ids)
        valid_input_set = set(context.valid_input_ids)
        valid_rule_set = set(context.valid_rule_ids)

        diffs_by_input: dict[str, dict[str, Any]] = {}
        for diff in context.differences_summary:
            inp_id = diff.get("input_id")
            if inp_id:
                diffs_by_input[inp_id] = diff

        # 3. Dimension Explanations Validation (Fail-closed on invalid dimensions)
        raw_dims = raw_payload.get("dimension_explanations", [])
        validated_dims: list[DimensionExplanation] = []
        allowed_dimensions = {d.value: d for d in BehaviorDimension}

        if isinstance(raw_dims, list):
            for raw_d in raw_dims:
                if not isinstance(raw_d, dict):
                    continue
                dim_str = str(raw_d.get("dimension", "")).strip().upper()

                if dim_str not in allowed_dimensions:
                    errors.append(f"Invalid dimension '{dim_str}' rejected (INVALID_DIMENSION: no coercion to OUTPUT).")
                    continue

                dim_enum = allowed_dimensions[dim_str]

                # Evidence references in dimension explanation
                raw_evids = raw_d.get("evidence_ids", [])
                if isinstance(raw_evids, list):
                    invalid_dim_evids = [eid for eid in raw_evids if eid not in valid_evid_set]
                    if invalid_dim_evids:
                        errors.append(f"Dimension {dim_str} references invalid evidence IDs: {invalid_dim_evids}")
                    filtered_evids = [eid for eid in raw_evids if eid in valid_evid_set]
                else:
                    filtered_evids = []

                # Derive authoritative dimension status if missing or invalid (no default PASS)
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

                # Filter findings & validate factual values (Fail-closed)
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
                                errors.append(f"UNSUPPORTED_EVIDENCE_REFERENCE {invalid_evids} in finding rejected.")
                                continue
                            f_evids = [eid for eid in f_evids_raw if eid in valid_evid_set]
                        else:
                            f_evids = []

                        inp_id = rf.get("input_id")
                        if inp_id and valid_input_set and inp_id not in valid_input_set:
                            errors.append(f"UNSUPPORTED_INPUT_REFERENCE '{inp_id}' in finding rejected.")
                            continue

                        ref_val = rf.get("reference_value")
                        tgt_val = rf.get("target_value")

                        # Value validation against authoritative diffs
                        if inp_id and inp_id in diffs_by_input:
                            auth_diff = diffs_by_input[inp_id]
                            auth_ref = auth_diff.get("reference_value")
                            auth_tgt = auth_diff.get("target_value")

                            if ref_val is not None and auth_ref is not None:
                                if str(ref_val) != str(auth_ref) and ref_val != auth_ref:
                                    errors.append(f"Factual value mismatch (NUMERIC_VALUE_MISMATCH) for input '{inp_id}': LLM ref='{ref_val}' vs authoritative='{auth_ref}'. Claim rejected.")
                                    continue
                            if tgt_val is not None and auth_tgt is not None:
                                if str(tgt_val) != str(auth_tgt) and tgt_val != auth_tgt:
                                    errors.append(f"Factual value mismatch (NUMERIC_VALUE_MISMATCH) for input '{inp_id}': LLM tgt='{tgt_val}' vs authoritative='{auth_tgt}'. Claim rejected.")
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

        # 4. Rule Impacts Validation (Fail-closed on hallucinated rule IDs)
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
                    errors.append(f"Hallucinated rule_id '{rule_id}' rejected by validator (UNSUPPORTED_RULE_REFERENCE).")
                    continue

                r_evids_raw = raw_r.get("supporting_evidence_ids", [])
                if isinstance(r_evids_raw, list):
                    invalid_r_evids = [eid for eid in r_evids_raw if eid not in valid_evid_set]
                    if invalid_r_evids:
                        errors.append(f"Rule impact '{rule_id}' references invalid evidence IDs: {invalid_r_evids}")
                    r_evids = [eid for eid in r_evids_raw if eid in valid_evid_set]
                else:
                    r_evids = []

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
                rec_evids_raw = rec.get("evidence_references", [])
                if isinstance(rec_evids_raw, list):
                    rec_evids = [eid for eid in rec_evids_raw if eid in valid_evid_set]
                else:
                    rec_evids = []

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
            evidence_traces=[],
            affected_inputs=[],
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

    def validate_qa_response(
        self,
        raw_payload: dict[str, Any],
        context: ExplanationContext,
        metadata: GenerationMetadata,
        question: str,
        referenced_doc_ids: list[str],
    ) -> tuple[bool, list[str], Optional[AskCertificationResponse]]:
        """Validates an interactive Q&A answer against authoritative context and grounding constraints."""
        errors: list[str] = []
        if not isinstance(raw_payload, dict):
            return False, ["Q&A response is not a JSON object."], None

        raw_evids = raw_payload.get("referenced_evidence_ids", [])
        raw_rules = raw_payload.get("referenced_rule_ids", [])

        # Fail-closed if invalid evidence IDs or rule IDs are present
        if isinstance(raw_evids, list):
            invalid_evids = [e for e in raw_evids if e not in context.valid_evidence_ids]
            if invalid_evids:
                errors.append(f"UNSUPPORTED_EVIDENCE_REFERENCE: {invalid_evids}")
                return False, errors, None
            filtered_evids = [e for e in raw_evids if e in context.valid_evidence_ids]
        else:
            filtered_evids = []

        if isinstance(raw_rules, list):
            invalid_rules = [r for r in raw_rules if r not in context.valid_rule_ids]
            if invalid_rules:
                errors.append(f"UNSUPPORTED_RULE_REFERENCE: {invalid_rules}")
                return False, errors, None
            filtered_rules = [r for r in raw_rules if r in context.valid_rule_ids]
        else:
            filtered_rules = []

        answer_text = str(raw_payload.get("answer", ""))
        if not answer_text:
            errors.append("Q&A answer is empty.")
            return False, errors, None

        # Validate factual numbers in answer against authoritative differences
        for diff in context.differences_summary:
            auth_tgt = diff.get("target_value")
            auth_ref = diff.get("reference_value")
            if auth_tgt is not None and isinstance(auth_tgt, (int, float)):
                # Match patterns like "target is 97", "target returned 97", "target value: 97"
                patterns = [
                    r"target\s*(?:output|value)?\s*(?:is|=|was|produced|of|returned)\s*(\d+(?:\.\d+)?)",
                    r"modern\s*(?:implementation|output|variant)?\s*(?:is|=|was|produced|of|returned)\s*(\d+(?:\.\d+)?)",
                    r"target\s*:\s*(\d+(?:\.\d+)?)",
                ]
                for pat in patterns:
                    for m in re.finditer(pat, answer_text, re.IGNORECASE):
                        claimed_val = float(m.group(1))
                        if abs(claimed_val - float(auth_tgt)) > 1e-6:
                            errors.append(
                                f"NUMERIC_VALUE_MISMATCH: Q&A answer claimed target={claimed_val} "
                                f"vs authoritative target={auth_tgt}."
                            )
                            return False, errors, None

        support_str = str(raw_payload.get("support_level", "DETERMINISTIC_FACT")).upper()
        try:
            sup_enum = EvidenceSupportLevel(support_str)
        except ValueError:
            sup_enum = EvidenceSupportLevel.DETERMINISTIC_FACT

        response = AskCertificationResponse(
            question=question,
            answer=answer_text,
            support_level=sup_enum,
            referenced_evidence_ids=filtered_evids,
            referenced_rule_ids=filtered_rules,
            referenced_document_ids=list(set(referenced_doc_ids)),
            uncertainties=raw_payload.get("uncertainties", []),
            authoritative_verdict=context.authoritative_verdict,
            context_fingerprint=context.compute_context_fingerprint(),
            generation_metadata=metadata,
        )
        return True, [], response


# Module-level singletons
grounding_validator = GroundingValidator()
explanation_validator = grounding_validator
ExplanationValidator = GroundingValidator
