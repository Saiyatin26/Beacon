"""BEACON V2 — Phase 10 Explanation Context Builder.

Assembles bounded, redacted, audit-grade ExplanationContext from Phase 3 Evidence,
Phase 4 Evaluation, Phase 5/6/7 Rules & OracleSets, Phase 8 Dynamic Thresholds,
and optional Phase 9 Company Knowledge.
"""

import json
import logging
from typing import Any, Optional

from certification.models import CertificationArtifact
from certification.repository import CertificationRepository
from common.config import settings
from evaluation.models import BehaviorDimension
from knowledge.models import KnowledgeContext
from knowledge.service import knowledge_service
from .models import (
    CompanyKnowledgeContext,
    ExplanationContext,
    MissingEvidence,
    RetrievedKnowledgeCitation,
)
from .security import redact_sensitive_data

logger = logging.getLogger("beacon.intelligence.context_builder")


class ExplanationContextBuilder:
    """Builds bounded, authoritative ExplanationContext for explanation generation and Q&A."""

    def __init__(self, cert_repository: Optional[CertificationRepository] = None):
        self.cert_repository = cert_repository or CertificationRepository()

    def build_context(
        self,
        certification_id: str,
        artifact: Optional[CertificationArtifact] = None,
        use_company_knowledge: bool = True,
        user_question: Optional[str] = None,
        custom_query: Optional[str] = None,
    ) -> ExplanationContext:
        """Assembles authoritative context from repository and external sources."""
        # 1. Load Certification Artifact
        if not artifact:
            artifact = self.cert_repository.get_artifact(certification_id)

        if not artifact:
            raise ValueError(f"CertificationArtifact '{certification_id}' not found.")

        app_id = artifact.project_id or (artifact.benchmark_id or "default_app")
        proj_id = artifact.project_id or "default_project"
        verdict_str = artifact.status.value if hasattr(artifact.status, "value") else str(artifact.status)

        # 2. Extract Valid Identifiers & Dimensions
        valid_evid_ids: set[str] = set()
        valid_rule_ids: set[str] = set()
        valid_input_ids: set[str] = set()
        differences_summary: list[dict[str, Any]] = []

        # Rules from Oracle Summaries
        rules_context: list[dict[str, Any]] = []
        for s in artifact.oracle_summaries:
            valid_rule_ids.add(s.oracle_id)
            rule_dict = {
                "rule_id": s.oracle_id,
                "rule_description": f"Condition: {s.condition_str} -> Expected: {s.consequence_str}",
                "condition_str": s.condition_str,
                "consequence_str": s.consequence_str,
                "severity": s.severity,
                "status": "VIOLATED" if s.modern_regressions > 0 else "COMPLIANT",
                "matching_probes": s.matching_probes,
                "regressions": s.modern_regressions,
                "supporting_evidence_ids": [],
            }
            rules_context.append(rule_dict)

        # Regressions / Counterexamples
        for r in artifact.regressions:
            valid_input_ids.add(r.input_id)
            for eid in r.evidence_ids:
                valid_evid_ids.add(eid)
            if not r.evidence_ids:
                synthetic_eid = f"EVID-{r.regression_id}"
                valid_evid_ids.add(synthetic_eid)
                evid_list = [synthetic_eid]
            else:
                evid_list = r.evidence_ids

            diff_record = {
                "difference_id": r.regression_id,
                "dimension": "OUTPUT",
                "input_id": r.input_id,
                "reference_value": r.legacy_output,
                "target_value": r.modern_output,
                "reference_evidence_id": evid_list[0] if evid_list else f"EVID-REF-{r.input_id}",
                "target_evidence_id": evid_list[-1] if evid_list else f"EVID-TGT-{r.input_id}",
                "input_values": r.input_values,
                "failed_assertion": r.failed_assertion,
                "severity": r.severity,
                "violated_oracle_ids": [r.oracle_id],
            }
            differences_summary.append(diff_record)

        # If no regressions and no explicit evidence IDs, generate baseline IDs
        if not valid_evid_ids:
            for idx in range(min(artifact.metrics.unique_input_count or 1, 5)):
                valid_evid_ids.add(f"EVID-RUN-{idx+1}")

        # Dimensions evaluated
        dimensions_evaluated = [
            BehaviorDimension.OUTPUT,
            BehaviorDimension.ERROR,
            BehaviorDimension.BOUNDARY,
            BehaviorDimension.STATE,
            BehaviorDimension.WORKFLOW,
        ]

        # 3. Missing Evidence Analysis
        missing_evidence: list[MissingEvidence] = [
            MissingEvidence(
                dimension=BehaviorDimension.STATE,
                description="Before/after database state snapshots were not collected for black-box API execution.",
                implication="State equivalence is inferred from pure output observations rather than physical DB delta.",
                status="INCONCLUSIVE",
            ),
            MissingEvidence(
                dimension=BehaviorDimension.WORKFLOW,
                description="Multi-step distributed trace telemetry was not captured for single-invocation execution.",
                implication="Intermediate workflow step sequence equivalence is assumed based on final output.",
                status="INCONCLUSIVE",
            ),
        ]

        # 4. Optional Phase 9 Knowledge Context Retrieval
        company_knowledge_context: Optional[CompanyKnowledgeContext] = None
        if use_company_knowledge:
            try:
                query_text = custom_query or user_question or f"{app_id} behavioral equivalence rules business logic"
                retrieved_context: KnowledgeContext = knowledge_service.retrieve(
                    query=query_text,
                    application_id=app_id,
                    top_k=3,
                    min_relevance_score=0.1,
                )
                if retrieved_context and retrieved_context.retrieved_chunks:
                    citations: list[RetrievedKnowledgeCitation] = []
                    for chunk in retrieved_context.retrieved_chunks:
                        citations.append(
                            RetrievedKnowledgeCitation(
                                chunk_id=chunk.chunk_id,
                                document_id=chunk.document_id,
                                filename=chunk.filename,
                                content_snippet=chunk.content[:300],
                                relevance_score=chunk.score,
                                page_number=chunk.page_number,
                                section_name=chunk.section_name,
                            )
                        )
                    company_knowledge_context = CompanyKnowledgeContext(
                        retrieval_query=query_text,
                        retrieval_fingerprint=retrieved_context.retrieval_fingerprint,
                        citations=citations,
                    )
            except Exception as exc:
                logger.warning(f"Optional Phase 9 knowledge retrieval skipped or failed: {exc}")

        # 5. Redact All Payloads
        redacted_diffs = redact_sensitive_data(differences_summary)
        redacted_rules = redact_sensitive_data(rules_context)

        # 6. Construct Context
        context = ExplanationContext(
            certification_id=artifact.certification_id,
            application_id=app_id,
            project_id=proj_id,
            session_id=artifact.certification_id,
            authoritative_verdict=verdict_str,
            equivalence_score=artifact.score,
            unique_inputs_count=artifact.metrics.unique_input_count or len(artifact.regressions) or 1,
            matching_cases_count=artifact.metrics.matching_case_count,
            regression_cases_count=artifact.metrics.regression_case_count or len(artifact.regressions),
            dimensions_evaluated=dimensions_evaluated,
            differences_summary=redacted_diffs,
            valid_evidence_ids=sorted(valid_evid_ids),
            valid_rule_ids=sorted(valid_rule_ids),
            valid_input_ids=sorted(valid_input_ids),
            rules_context=redacted_rules,
            thresholds_context=[
                {
                    "policy_id": artifact.certification_policy_id,
                    "min_equivalence_score": 0.80,
                    "tolerance_strategy": "FIXED_AND_BOUNDED",
                }
            ],
            missing_evidence=missing_evidence,
            knowledge_context=company_knowledge_context,
            user_question=user_question,
        )
        return context


explanation_context_builder = ExplanationContextBuilder()
