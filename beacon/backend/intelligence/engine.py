"""BEACON V2 — Phase 10 Intelligence Engine.

Orchestrates context building, LLM provider invocation, schema validation, hallucination guards,
deterministic fallback, explanation assembly, and interactive Q&A.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import time
from typing import Any, Optional

from certification.models import CertificationArtifact
from certification.repository import CertificationRepository, certification_repository
from common.config import settings
from evaluation.models import EvaluationResult
from execution.evidence_models import EvidenceBundle, EvidenceRecord
from llm.base import extract_json_payload
from llm.manager import ProviderManager, get_provider_manager
from reconciliation.models import OracleSet
from threshold.models import ThresholdResolution
from .context_builder import ExplanationContextBuilder, explanation_context_builder
from .deterministic_generator import DeterministicExplanationGenerator, deterministic_generator
from .models import (
    AskCertificationRequest,
    AskCertificationResponse,
    CertificationExplanation,
    EvidenceSupportLevel,
    ExplanationContext,
    ExplanationRequest,
    GenerationMetadata,
)
from .persistence import IntelligencePersistenceStore, intelligence_persistence
from .prompts.explanation_prompt import render_explanation_prompt
from .prompts.qa_prompt import render_qa_prompt
from .security import sanitize_prompt_input, wrap_untrusted_context
from .validation import GroundingValidator, grounding_validator

logger = logging.getLogger("beacon.intelligence.engine")


class IntelligenceEngine:
    """Primary intelligence and explanation engine for BEACON V2."""

    def __init__(
        self,
        context_builder: Optional[ExplanationContextBuilder] = None,
        det_generator: Optional[DeterministicExplanationGenerator] = None,
        validator: Optional[GroundingValidator] = None,
        persistence: Optional[IntelligencePersistenceStore] = None,
        provider_manager: Optional[ProviderManager] = None,
    ):
        self.context_builder = context_builder or explanation_context_builder
        self.det_generator = det_generator or deterministic_generator
        self.validator = validator or grounding_validator
        self.persistence = persistence or intelligence_persistence
        self.provider_manager = provider_manager or get_provider_manager()

    def generate_explanation(
        self,
        certification_id: str,
        artifact: Optional[CertificationArtifact] = None,
        evidence_bundle: Optional[EvidenceBundle] = None,
        evidence_records: Optional[list[EvidenceRecord]] = None,
        evaluation_result: Optional[EvaluationResult] = None,
        oracle_set: Optional[OracleSet] = None,
        threshold_resolution: Optional[ThresholdResolution] = None,
        request: Optional[ExplanationRequest] = None,
        user_id: str = "system",
    ) -> CertificationExplanation:
        """Generates or retrieves a structured CertificationExplanation with strict boundary guarantees."""
        req = request or ExplanationRequest()

        # 1. Build Authoritative ExplanationContext from Phase 3–8 entities
        context = self.context_builder.build_context(
            certification_id=certification_id,
            artifact=artifact,
            evidence_bundle=evidence_bundle,
            evidence_records=evidence_records,
            evaluation_result=evaluation_result,
            oracle_set=oracle_set,
            threshold_resolution=threshold_resolution,
            use_company_knowledge=req.use_company_knowledge,
            custom_query=req.custom_query,
        )

        mode = req.mode.lower().strip()
        preferred_provider = req.preferred_provider or settings.llm_provider or "auto"
        expected_cache_key = context.compute_cache_key(
            mode=mode,
            use_company_knowledge=req.use_company_knowledge,
            prompt_version="v1.0",
        )

        # Check existing cached explanation matching exact cache key unless force_recompute is requested
        if not req.force_recompute:
            cached = self.persistence.get_explanation(certification_id, cache_key=expected_cache_key)
            if cached:
                logger.info(f"Returning cached explanation for certification '{certification_id}' (cache_key: {expected_cache_key[:12]}).")
                return cached

        start_time = time.perf_counter()

        # 2. Pure Deterministic Mode Execution
        if mode == "deterministic" or preferred_provider == "offline":
            explanation = self.det_generator.generate_explanation(context)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            explanation.generation_metadata.latency_ms = round(elapsed_ms, 2)
            explanation.cache_key = expected_cache_key
            saved = self.persistence.save_explanation(explanation)
            self.persistence.log_audit_event(
                audit_id=f"AUD-{hashlib.sha256(str(time.time()).encode()).hexdigest()[:12]}",
                user_id=user_id,
                certification_id=context.certification_id,
                application_id=context.application_id,
                mode="DETERMINISTIC",
                provider="offline",
                model="deterministic",
                context_fingerprint=explanation.context_fingerprint,
                fallback_used=False,
            )
            return saved

        # 3. LLM / Assisted Mode Execution
        knowledge_block = "No company documentation was retrieved."
        if context.knowledge_context and context.knowledge_context.citations:
            doc_snippets = []
            for c in context.knowledge_context.citations:
                doc_snippets.append(f"[{c.filename} - Section {c.section_name or 'General'}]: {c.content_snippet}")
            knowledge_block = wrap_untrusted_context("COMPANY_KNOWLEDGE", "\n\n".join(doc_snippets))

        context_dict = {
            "certification_id": context.certification_id,
            "application_id": context.application_id,
            "authoritative_verdict": context.authoritative_verdict,
            "equivalence_score": context.equivalence_score,
            "unique_inputs_count": context.unique_inputs_count,
            "matching_cases_count": context.matching_cases_count,
            "regression_cases_count": context.regression_cases_count,
            "dimensions": [d.value for d in context.dimensions_evaluated],
            "valid_evidence_ids": context.valid_evidence_ids,
            "valid_rule_ids": context.valid_rule_ids,
            "valid_input_ids": context.valid_input_ids,
            "differences_summary": context.differences_summary,
            "rules_context": context.rules_context,
            "thresholds_context": context.thresholds_context,
            "missing_evidence": [m.model_dump() for m in context.missing_evidence],
        }

        system_prompt, user_prompt = render_explanation_prompt(context_dict, knowledge_block)

        try:
            llm_resp = self.provider_manager.generate(
                prompt=user_prompt,
                system=system_prompt,
                json_mode=True,
                preferred_provider=preferred_provider if mode == "llm" else "auto",
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            if llm_resp.success and llm_resp.parsed_json:
                gen_metadata = GenerationMetadata(
                    provider=llm_resp.provider_name,
                    model=llm_resp.model_name,
                    generation_mode="LLM" if mode == "llm" else "ASSISTED",
                    prompt_version="v1.0",
                    schema_version="1.0.0",
                    latency_ms=round(elapsed_ms, 2),
                    fallback_occurred=llm_resp.fallback_occurred,
                    fallback_reason=llm_resp.fallback_reason,
                    reproducibility="NOT_GUARANTEED",
                )
                is_valid, validation_errors, validated_explanation = self.validator.validate_and_sanitize_explanation(
                    raw_payload=llm_resp.parsed_json,
                    context=context,
                    metadata=gen_metadata,
                )
                if is_valid and validated_explanation:
                    # Merge deterministic traces and affected inputs strictly from authoritative ground truth
                    det_baseline = self.det_generator.generate_explanation(context)
                    validated_explanation.evidence_traces = det_baseline.evidence_traces
                    validated_explanation.affected_inputs = det_baseline.affected_inputs
                    validated_explanation.cache_key = expected_cache_key
                    validated_explanation.content_hash = validated_explanation.compute_content_hash()

                    saved = self.persistence.save_explanation(validated_explanation)
                    self.persistence.log_audit_event(
                        audit_id=f"AUD-{hashlib.sha256(str(time.time()).encode()).hexdigest()[:12]}",
                        user_id=user_id,
                        certification_id=context.certification_id,
                        application_id=context.application_id,
                        mode=validated_explanation.generation_metadata.generation_mode,
                        provider=validated_explanation.generation_metadata.provider,
                        model=validated_explanation.generation_metadata.model,
                        context_fingerprint=validated_explanation.context_fingerprint,
                        fallback_used=llm_resp.fallback_occurred,
                    )
                    return saved
                else:
                    logger.warning(f"LLM output validation failed: {validation_errors}. Executing deterministic fallback.")
            else:
                logger.warning(f"LLM generation failed ({llm_resp.error}). Executing deterministic fallback.")

        except Exception as exc:
            logger.error(f"Unexpected error during LLM explanation generation: {exc}", exc_info=True)

        # 4. Guaranteed Deterministic Fallback
        fallback_explanation = self.det_generator.generate_explanation(
            context=context,
            fallback_reason="LLM generation or schema validation unfulfilled",
        )
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        fallback_explanation.generation_metadata.latency_ms = round(elapsed_ms, 2)
        fallback_explanation.cache_key = expected_cache_key
        saved = self.persistence.save_explanation(fallback_explanation)
        self.persistence.log_audit_event(
            audit_id=f"AUD-{hashlib.sha256(str(time.time()).encode()).hexdigest()[:12]}",
            user_id=user_id,
            certification_id=context.certification_id,
            application_id=context.application_id,
            mode="DETERMINISTIC",
            provider="offline",
            model="deterministic-fallback",
            context_fingerprint=fallback_explanation.context_fingerprint,
            fallback_used=True,
        )
        return saved

    def ask_certification(
        self,
        certification_id: str,
        question: str,
        artifact: Optional[CertificationArtifact] = None,
        evidence_bundle: Optional[EvidenceBundle] = None,
        evidence_records: Optional[list[EvidenceRecord]] = None,
        evaluation_result: Optional[EvaluationResult] = None,
        oracle_set: Optional[OracleSet] = None,
        threshold_resolution: Optional[ThresholdResolution] = None,
        use_company_knowledge: bool = True,
        preferred_provider: Optional[str] = None,
        user_id: str = "system",
    ) -> AskCertificationResponse:
        """Answers an interactive question over authoritative certification context with strict guardrails."""
        # 1. Build Context from Authoritative Sources
        context = self.context_builder.build_context(
            certification_id=certification_id,
            artifact=artifact,
            evidence_bundle=evidence_bundle,
            evidence_records=evidence_records,
            evaluation_result=evaluation_result,
            oracle_set=oracle_set,
            threshold_resolution=threshold_resolution,
            use_company_knowledge=use_company_knowledge,
            user_question=question,
        )

        clean_question = sanitize_prompt_input(question)
        start_time = time.perf_counter()

        knowledge_block = "No company documentation was retrieved."
        referenced_doc_ids: list[str] = []
        if context.knowledge_context and context.knowledge_context.citations:
            doc_snippets = []
            for c in context.knowledge_context.citations:
                referenced_doc_ids.append(c.document_id)
                doc_snippets.append(f"[{c.filename} - Section {c.section_name or 'General'}]: {c.content_snippet}")
            knowledge_block = wrap_untrusted_context("COMPANY_KNOWLEDGE", "\n\n".join(doc_snippets))

        context_dict = {
            "certification_id": context.certification_id,
            "application_id": context.application_id,
            "authoritative_verdict": context.authoritative_verdict,
            "equivalence_score": context.equivalence_score,
            "unique_inputs_count": context.unique_inputs_count,
            "matching_cases_count": context.matching_cases_count,
            "regression_cases_count": context.regression_cases_count,
            "dimensions": [d.value for d in context.dimensions_evaluated],
            "valid_evidence_ids": context.valid_evidence_ids,
            "valid_rule_ids": context.valid_rule_ids,
            "valid_input_ids": context.valid_input_ids,
            "differences_summary": context.differences_summary,
            "rules_context": context.rules_context,
            "thresholds_context": context.thresholds_context,
            "missing_evidence": [m.model_dump() for m in context.missing_evidence],
        }

        # Check for provider availability
        provider_name = preferred_provider or settings.llm_provider or "auto"
        if provider_name != "offline":
            system_prompt, user_prompt = render_qa_prompt(clean_question, context_dict, knowledge_block)
            try:
                llm_resp = self.provider_manager.generate(
                    prompt=user_prompt,
                    system=system_prompt,
                    json_mode=True,
                    preferred_provider=provider_name,
                )
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0

                if llm_resp.success and isinstance(llm_resp.parsed_json, dict):
                    meta = GenerationMetadata(
                        provider=llm_resp.provider_name,
                        model=llm_resp.model_name,
                        generation_mode="LLM",
                        prompt_version="v1.0",
                        schema_version="1.0.0",
                        latency_ms=round(elapsed_ms, 2),
                        fallback_occurred=llm_resp.fallback_occurred,
                    )
                    is_valid, validation_errors, qa_response = self.validator.validate_qa_response(
                        raw_payload=llm_resp.parsed_json,
                        context=context,
                        metadata=meta,
                        question=clean_question,
                        referenced_doc_ids=referenced_doc_ids,
                    )
                    if is_valid and qa_response:
                        self.persistence.log_audit_event(
                            audit_id=f"AUD-{hashlib.sha256(str(time.time()).encode()).hexdigest()[:12]}",
                            user_id=user_id,
                            certification_id=context.certification_id,
                            application_id=context.application_id,
                            mode="LLM",
                            provider=llm_resp.provider_name,
                            model=llm_resp.model_name,
                            context_fingerprint=context.compute_context_fingerprint(),
                            fallback_used=False,
                        )
                        return qa_response
                    else:
                        logger.warning(f"Interactive LLM QA validation failed: {validation_errors}. Executing deterministic fallback.")
            except Exception as exc:
                logger.warning(f"Interactive LLM QA failed: {exc}. Falling back to deterministic answer.")

        # Deterministic Q&A Answer Synthesis (Dimension-aware & conservative)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        verdict = context.authoritative_verdict
        score_pct = context.equivalence_score * 100

        # Dynamically determine observed differing dimensions (no default to OUTPUT)
        diff_dims = sorted(list({str(d.get("dimension")).upper() for d in context.differences_summary if d.get("dimension")}))
        diff_dims_str = ", ".join(diff_dims) if diff_dims else "UNKNOWN"

        det_answer = (
            f"Authoritative Certification Status: {verdict} (Equivalence Score: {score_pct:.1f}%). "
            f"Evaluated {context.unique_inputs_count} inputs with {context.matching_cases_count} matches "
            f"and {context.regression_cases_count} counterexamples."
        )
        if context.regression_cases_count > 0:
            det_answer += (
                f" The primary deviations occurred in the {diff_dims_str} dimension, affecting rules: "
                f"{', '.join(context.valid_rule_ids[:3]) or 'observed invariants'}."
            )

        meta = GenerationMetadata(
            provider="offline",
            model="deterministic-qa",
            generation_mode="DETERMINISTIC",
            latency_ms=round(elapsed_ms, 2),
            fallback_occurred=True,
            fallback_reason="Offline, deterministic mode, or validation fallback triggered",
        )

        # Claim-specific referenced evidence and rule IDs rather than arbitrary top-5
        qa_evidence_ids: list[str] = []
        for diff in context.differences_summary:
            for eid in diff.get("evidence_ids", []):
                if eid in context.valid_evidence_ids and eid not in qa_evidence_ids:
                    qa_evidence_ids.append(eid)
            ref_e = diff.get("reference_evidence_id")
            tgt_e = diff.get("target_evidence_id")
            if ref_e and ref_e in context.valid_evidence_ids and ref_e not in qa_evidence_ids:
                qa_evidence_ids.append(ref_e)
            if tgt_e and tgt_e in context.valid_evidence_ids and tgt_e not in qa_evidence_ids:
                qa_evidence_ids.append(tgt_e)

        qa_rule_ids: list[str] = []
        for diff in context.differences_summary:
            for r_id in diff.get("violated_oracle_ids", []):
                if r_id in context.valid_rule_ids and r_id not in qa_rule_ids:
                    qa_rule_ids.append(r_id)

        resp = AskCertificationResponse(
            question=clean_question,
            answer=det_answer,
            support_level=EvidenceSupportLevel.DETERMINISTIC_FACT,
            referenced_evidence_ids=qa_evidence_ids,
            referenced_rule_ids=qa_rule_ids,
            referenced_document_ids=list(set(referenced_doc_ids)),
            uncertainties=[m.description for m in context.missing_evidence],
            authoritative_verdict=verdict,
            context_fingerprint=context.compute_context_fingerprint(),
            generation_metadata=meta,
        )
        self.persistence.log_audit_event(
            audit_id=f"AUD-{hashlib.sha256(str(time.time()).encode()).hexdigest()[:12]}",
            user_id=user_id,
            certification_id=context.certification_id,
            application_id=context.application_id,
            mode="DETERMINISTIC",
            provider="offline",
            model="deterministic-qa",
            context_fingerprint=context.compute_context_fingerprint(),
            fallback_used=True,
        )
        return resp


intelligence_engine = IntelligenceEngine()
