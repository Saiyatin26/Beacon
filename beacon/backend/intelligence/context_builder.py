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
from common.contracts import compute_canonical_input_hash
from evaluation.models import BehaviorDimension
from execution.evidence_store import evidence_store
from knowledge.models import KnowledgeContext
from knowledge.service import knowledge_service
from reconciliation.persistence import reconciliation_persistence
from threshold.persistence import threshold_persistence
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

        # Rules from Canonical Phase 7 OracleSet (if available) or Oracle Summaries
        rules_context: list[dict[str, Any]] = []
        oset_id = getattr(artifact, "oracle_set_id", None)
        if not oset_id and artifact.context and hasattr(artifact.context, "oracle_set_id"):
            oset_id = getattr(artifact.context, "oracle_set_id", None)

        canonical_oracle_set = None
        if oset_id:
            try:
                canonical_oracle_set = reconciliation_persistence.get_oracle_set(oset_id)
            except Exception as exc:
                logger.debug(f"Could not load canonical OracleSet '{oset_id}': {exc}")

        if canonical_oracle_set and canonical_oracle_set.rules:
            for rule in canonical_oracle_set.rules:
                if rule.rule_id:
                    valid_rule_ids.add(rule.rule_id)
                rule_dict = {
                    "rule_id": rule.rule_id,
                    "rule_description": rule.canonical_expression or f"Rule {rule.rule_id}",
                    "condition_str": rule.canonical_expression or "",
                    "consequence_str": "",
                    "severity": "medium",
                    "status": "COMPLIANT",
                    "fingerprint": rule.fingerprint,
                    "source": rule.source.value if hasattr(rule.source, "value") else str(rule.source),
                    "role_scope": rule.role_scope,
                    "confidence": rule.confidence,
                    "matching_probes": rule.support_count,
                    "regressions": 0,
                    "supporting_evidence_ids": [],
                }
                rules_context.append(rule_dict)
        else:
            for s in artifact.oracle_summaries:
                if s.oracle_id:
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

        # Regressions / Counterexamples (Strictly using actual evidence IDs and role metadata)
        for r in artifact.regressions:
            if getattr(r, "input_id", None):
                valid_input_ids.add(r.input_id)

            actual_evids = [e for e in getattr(r, "evidence_ids", []) if e]
            for eid in actual_evids:
                valid_evid_ids.add(eid)

            # Role resolution strictly from metadata (never infer first=ref, last=tgt by list index)
            ref_eid: Optional[str] = None
            tgt_eid: Optional[str] = None

            # 1) Inspect actual EvidenceStore records if available
            for eid in actual_evids:
                try:
                    rec = evidence_store.get_record(eid)
                    if rec:
                        role_str = str(rec.role).lower()
                        if role_str in ("reference", "legacy") and not ref_eid:
                            ref_eid = eid
                        elif role_str in ("target", "modernized") and not tgt_eid:
                            tgt_eid = eid
                except Exception:
                    pass

            # 2) Check explicit regression attributes if present
            if not ref_eid and getattr(r, "reference_evidence_id", None) in actual_evids:
                ref_eid = getattr(r, "reference_evidence_id", None)
            if not tgt_eid and getattr(r, "target_evidence_id", None) in actual_evids:
                tgt_eid = getattr(r, "target_evidence_id", None)

            # 3) Check substring naming metadata if unambiguous
            if not ref_eid or not tgt_eid:
                for eid in actual_evids:
                    eid_lower = eid.lower()
                    if ("ref" in eid_lower or "legacy" in eid_lower) and not ref_eid:
                        ref_eid = eid
                    elif ("tgt" in eid_lower or "target" in eid_lower or "modern" in eid_lower) and not tgt_eid:
                        tgt_eid = eid

            # Determine canonical input hash
            inp_hash = getattr(r, "input_hash", None)
            if not inp_hash and getattr(r, "input_values", None):
                inp_hash = compute_canonical_input_hash(r.input_values)

            # Determine actual dimension
            raw_dim = getattr(r, "dimension", None) or getattr(r, "domain", None)
            dim_str = "OUTPUT"
            if raw_dim:
                if isinstance(raw_dim, BehaviorDimension):
                    dim_str = raw_dim.value
                elif str(raw_dim).upper() in {d.value for d in BehaviorDimension}:
                    dim_str = str(raw_dim).upper()

            diff_record = {
                "difference_id": r.regression_id,
                "dimension": dim_str,
                "input_id": getattr(r, "input_id", None),
                "input_hash": inp_hash,
                "reference_value": r.legacy_output,
                "target_value": r.modern_output,
                "reference_evidence_id": ref_eid,
                "target_evidence_id": tgt_eid,
                "evidence_ids": actual_evids,
                "input_values": r.input_values,
                "failed_assertion": r.failed_assertion,
                "severity": r.severity,
                "violated_oracle_ids": [r.oracle_id] if getattr(r, "oracle_id", None) else [],
            }
            differences_summary.append(diff_record)

        # Dimensions evaluated
        dimensions_evaluated = [
            BehaviorDimension.OUTPUT,
            BehaviorDimension.ERROR,
            BehaviorDimension.BOUNDARY,
            BehaviorDimension.STATE,
            BehaviorDimension.WORKFLOW,
        ]

        # 3. Dynamic Missing Evidence Analysis (Derived from actual availability, not hardcoded)
        missing_evidence: list[MissingEvidence] = []

        # State Dimension Availability Analysis
        has_state_evidence = bool(
            getattr(artifact, "state_snapshots", None)
            or (artifact.context and getattr(artifact.context, "state_snapshots_captured", False))
        )
        if not has_state_evidence:
            missing_evidence.append(
                MissingEvidence(
                    dimension=BehaviorDimension.STATE,
                    description="Database and memory state snapshots were not collected for this certification run.",
                    implication="State equivalence is inconclusive as physical DB delta was not recorded.",
                    status="INCONCLUSIVE",
                )
            )

        # Workflow Dimension Availability Analysis
        has_workflow_evidence = bool(
            getattr(artifact, "workflow_traces", None)
            or (artifact.context and getattr(artifact.context, "workflow_traces_captured", False))
        )
        if not has_workflow_evidence:
            missing_evidence.append(
                MissingEvidence(
                    dimension=BehaviorDimension.WORKFLOW,
                    description="Workflow execution trace telemetry was not captured for single-invocation execution.",
                    implication="Intermediate workflow step sequence equivalence could not be established from the available evidence.",
                    status="INCONCLUSIVE",
                )
            )

        # 4. Phase 8 Dynamic Threshold Resolution Loading (Authoritative exact consumption)
        thresholds_context: list[dict[str, Any]] = []
        if artifact.certification_policy_id:
            try:
                pol = threshold_persistence.get_policy(artifact.certification_policy_id)
                if pol:
                    res_info: dict[str, Any] = {}
                    # Check for exact resolution ID or fingerprint tied to artifact/context
                    exact_res_id = getattr(artifact, "threshold_resolution_id", None)
                    if not exact_res_id and artifact.context and hasattr(artifact.context, "threshold_resolution_id"):
                        exact_res_id = getattr(artifact.context, "threshold_resolution_id", None)

                    exact_res_fp = getattr(artifact, "threshold_resolution_fingerprint", None)
                    if not exact_res_fp and artifact.context and hasattr(artifact.context, "threshold_resolution_fingerprint"):
                        exact_res_fp = getattr(artifact.context, "threshold_resolution_fingerprint", None)

                    pol_ver = getattr(artifact, "certification_policy_version", None)
                    if not pol_ver and artifact.context and hasattr(artifact.context, "policy_version"):
                        pol_ver = getattr(artifact.context, "policy_version", None)

                    try:
                        with threshold_persistence._get_connection() as conn:
                            row = None
                            if exact_res_id:
                                row = conn.execute(
                                    "SELECT resolution_json, fingerprint, final_value, status, sample_count FROM threshold_resolutions WHERE resolution_id = ?",
                                    (exact_res_id,),
                                ).fetchone()
                            elif exact_res_fp:
                                row = conn.execute(
                                    "SELECT resolution_json, fingerprint, final_value, status, sample_count FROM threshold_resolutions WHERE fingerprint = ?",
                                    (exact_res_fp,),
                                ).fetchone()
                            else:
                                rows = conn.execute(
                                    "SELECT resolution_json, fingerprint, final_value, status, sample_count FROM threshold_resolutions WHERE policy_id = ? ORDER BY created_at DESC",
                                    (artifact.certification_policy_id,),
                                ).fetchall()
                                if pol_ver and rows:
                                    ver_str = str(pol_ver)
                                    for r in rows:
                                        try:
                                            res_data = json.loads(r["resolution_json"])
                                            r_ver = str(res_data.get("policy_version", ""))
                                            if r_ver == ver_str or r_ver.startswith(f"{ver_str}."):
                                                row = r
                                                break
                                        except Exception:
                                            pass
                                if not row and rows:
                                    row = rows[0]

                            if row:
                                res_info = {
                                    "resolution_fingerprint": row["fingerprint"],
                                    "resolved_threshold": row["final_value"],
                                    "resolution_status": row["status"],
                                    "sample_count": row["sample_count"],
                                }
                    except Exception as conn_err:
                        logger.debug(f"Could not load resolution details for policy {artifact.certification_policy_id}: {conn_err}")

                    pol_hash = pol.compute_policy_hash() if hasattr(pol, "compute_policy_hash") else getattr(pol, "policy_hash", "")
                    threshold_dict = {
                        "policy_id": pol.policy_id,
                        "version": pol.version,
                        "metric": pol.metric.value if hasattr(pol.metric, "value") else str(pol.metric),
                        "strategy": pol.strategy.value if hasattr(pol.strategy, "value") else str(pol.strategy),
                        "policy_hash": pol_hash,
                        **res_info,
                    }
                    thresholds_context.append(threshold_dict)
            except Exception as exc:
                logger.debug(f"Phase 8 policy resolution not found in persistence: {exc}")

        # 5. Optional Phase 9 Knowledge Context Retrieval
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

        # 6. Redact All Payloads
        redacted_diffs = redact_sensitive_data(differences_summary)
        redacted_rules = redact_sensitive_data(rules_context)

        # Extract actual session id if present, else None (Never certification_id)
        actual_session_id = getattr(artifact, "session_id", None)
        if not actual_session_id and artifact.context and hasattr(artifact.context, "session_id"):
            actual_session_id = getattr(artifact.context, "session_id", None)

        # 7. Construct Context
        context = ExplanationContext(
            certification_id=artifact.certification_id,
            application_id=app_id,
            project_id=proj_id,
            session_id=actual_session_id,
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
            thresholds_context=thresholds_context,
            missing_evidence=missing_evidence,
            knowledge_context=company_knowledge_context,
            user_question=user_question,
        )
        return context


explanation_context_builder = ExplanationContextBuilder()
