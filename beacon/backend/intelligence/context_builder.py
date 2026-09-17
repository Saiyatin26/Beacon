"""BEACON V2 — Phase 10 Authoritative Explanation Context Builder.

Strictly consumes and projects authoritative empirical data from:
- Phase 3 Evidence (EvidenceBundle / EvidenceRecords)
- Phase 4 Behavioral Evaluation (EvaluationResult / BehaviorDifference)
- Phase 7 Reconciled OracleSets (OracleSet / OracleRule)
- Phase 8 Dynamic Thresholds (exact frozen ThresholdResolution with fingerprint validation)
- Optional Phase 9 Company Knowledge (untrusted contextual documentation)
"""

import json
import logging
from typing import Any, Optional

from certification.models import CertificationArtifact
from certification.repository import CertificationRepository
from common.config import settings
from common.contracts import compute_canonical_input_hash
from evaluation.models import BehaviorDimension, BehaviorDifference, EvaluationResult, EvaluationVerdict
from execution.evidence_models import EvidenceBundle, EvidenceRecord, EvidenceType
from execution.evidence_store import evidence_store
from knowledge.models import KnowledgeContext
from knowledge.service import knowledge_service
from reconciliation.models import OracleSet, OracleSetStatus
from reconciliation.persistence import reconciliation_persistence
from threshold.models import ThresholdResolution
from threshold.persistence import threshold_persistence
from .models import (
    AuthoritativeFact,
    CompanyKnowledgeContext,
    ExplanationContext,
    MissingEvidence,
    RetrievedKnowledgeCitation,
    StateEvidenceFact,
    WorkflowTraceFact,
)
from .security import redact_sensitive_data

logger = logging.getLogger("beacon.intelligence.context_builder")


def resolve_authoritative_evidence(
    evidence_id: str,
    record_by_id: Optional[dict[str, EvidenceRecord]] = None,
) -> Optional[EvidenceRecord]:
    """Authoritatively resolves an evidence_id to a real Phase 3 EvidenceRecord.

    Queries in-memory indexed records or the persistent EvidenceStore.
    Returns the real EvidenceRecord if found, else None (fail closed).
    Never creates synthetic or fake records from IDs alone.
    """
    if not evidence_id or not isinstance(evidence_id, str):
        return None
    if record_by_id and evidence_id in record_by_id:
        return record_by_id[evidence_id]
    try:
        rec = evidence_store.get_record(evidence_id)
        if rec and isinstance(rec, EvidenceRecord):
            return rec
    except Exception as exc:
        logger.debug(f"Failed to query evidence_store for '{evidence_id}': {exc}")
    return None


class ExplanationContextBuilder:
    """Builds bounded, authoritative ExplanationContext for explanation generation and Q&A."""

    def __init__(self, cert_repository: Optional[CertificationRepository] = None):
        self.cert_repository = cert_repository or CertificationRepository()

    def build_context(
        self,
        certification_id: str,
        artifact: Optional[CertificationArtifact] = None,
        evidence_bundle: Optional[EvidenceBundle] = None,
        evidence_records: Optional[list[EvidenceRecord]] = None,
        evaluation_result: Optional[EvaluationResult] = None,
        oracle_set: Optional[OracleSet] = None,
        threshold_resolution: Optional[ThresholdResolution] = None,
        use_company_knowledge: bool = True,
        user_question: Optional[str] = None,
        custom_query: Optional[str] = None,
        execution_mode: str = "auto",
    ) -> ExplanationContext:
        """Assembles authoritative context directly from canonical Phase 3–8 entities."""
        # 1. Resolve Certification Artifact (Identity & linkage metadata only)
        if not artifact and certification_id:
            try:
                artifact = self.cert_repository.get_artifact(certification_id)
            except Exception as exc:
                logger.debug(f"Could not load CertificationArtifact for '{certification_id}': {exc}")

        app_id = (
            getattr(artifact, "project_id", None)
            or getattr(artifact, "benchmark_id", None)
            or (getattr(evaluation_result, "application_id", None) if evaluation_result else None)
            or "default_app"
        )
        proj_id = getattr(artifact, "project_id", None) or "default_project"

        mode_normalized = (execution_mode or "auto").strip().lower()
        is_strict_v2 = mode_normalized == "v2"
        is_legacy_mode = mode_normalized == "legacy"

        # Determine authoritative verdict
        if evaluation_result:
            verdict_str = evaluation_result.verdict.value if hasattr(evaluation_result.verdict, "value") else str(evaluation_result.verdict)
        elif artifact and not is_strict_v2:
            verdict_str = artifact.status.value if hasattr(artifact.status, "value") else str(artifact.status)
        else:
            verdict_str = "INCONCLUSIVE"

        # Extract actual session id if present, else None (Never certification_id)
        actual_session_id = getattr(artifact, "session_id", None)
        if not isinstance(actual_session_id, str):
            actual_session_id = None
        if not actual_session_id and artifact and getattr(artifact, "context", None):
            ctx_sess = getattr(artifact.context, "session_id", None)
            if isinstance(ctx_sess, str):
                actual_session_id = ctx_sess

        # 2. Phase 3 Authoritative Evidence Resolution
        all_records: list[EvidenceRecord] = []
        if evidence_records:
            all_records = list(evidence_records)
        elif evidence_bundle and evidence_bundle.records:
            all_records = list(evidence_bundle.records)
        elif actual_session_id:
            try:
                all_records = evidence_store.list_records_for_session(actual_session_id)
            except Exception as exc:
                logger.debug(f"Could not load evidence records for session '{actual_session_id}': {exc}")

        # Index evidence records strictly by ID and role metadata
        record_by_id: dict[str, EvidenceRecord] = {}
        valid_evid_ids: set[str] = set()
        unresolved_evid_ids: set[str] = set()

        for rec in all_records:
            if rec.evidence_id:
                record_by_id[rec.evidence_id] = rec
                valid_evid_ids.add(rec.evidence_id)

        # 3. Phase 4 Authoritative Evaluation & Difference Processing
        valid_rule_ids: set[str] = set()
        valid_input_ids: set[str] = set()
        differences_summary: list[dict[str, Any]] = []

        # Consume direct EvaluationResult differences if available
        if evaluation_result and evaluation_result.differences:
            for diff in evaluation_result.differences:
                inp_id = diff.input_id if diff.input_id else None
                if inp_id:
                    valid_input_ids.add(inp_id)

                # Strictly metadata-driven role resolution (never filename, ID string, or list position)
                ref_eid = diff.reference_evidence_id
                tgt_eid = diff.target_evidence_id
                diff_evids = getattr(diff, "evidence_ids", []) or []

                candidate_eids = list(diff_evids)
                if ref_eid:
                    candidate_eids.append(ref_eid)
                if tgt_eid:
                    candidate_eids.append(tgt_eid)
                if not candidate_eids and inp_id:
                    candidate_eids = [rec.evidence_id for rec in all_records if rec.input_id == inp_id]

                for eid in candidate_eids:
                    rec = resolve_authoritative_evidence(eid, record_by_id)
                    if rec is not None:
                        valid_evid_ids.add(rec.evidence_id)
                        record_by_id[rec.evidence_id] = rec
                        role_str = str(rec.role).lower()
                        if role_str in ("reference", "legacy") and not ref_eid:
                            ref_eid = eid
                        elif role_str in ("target", "modernized") and not tgt_eid:
                            tgt_eid = eid
                    else:
                        unresolved_evid_ids.add(eid)

                # Ensure dimension is canonical
                dim_str = diff.dimension.value if hasattr(diff.dimension, "value") else str(diff.dimension)

                all_diff_evids = [e for e in ([ref_eid, tgt_eid] + diff_evids) if e and e in valid_evid_ids]
                seen_eids = set()
                dedup_evids = []
                for e in all_diff_evids:
                    if e not in seen_eids:
                        seen_eids.add(e)
                        dedup_evids.append(e)

                diff_record = {
                    "difference_id": diff.difference_id,
                    "dimension": dim_str,
                    "input_id": inp_id,
                    "reference_value": diff.reference_value,
                    "target_value": diff.target_value,
                    "reference_evidence_id": ref_eid if ref_eid in valid_evid_ids else None,
                    "target_evidence_id": tgt_eid if tgt_eid in valid_evid_ids else None,
                    "evidence_ids": dedup_evids,
                    "details": diff.details,
                    "difference_type": diff.difference_type.value if hasattr(diff.difference_type, "value") else str(diff.difference_type),
                }
                differences_summary.append(diff_record)

        elif not is_strict_v2 and artifact and artifact.regressions:
            # Fallback when in non-strict V2 / legacy mode with strict evidence resolution
            for r in artifact.regressions:
                inp_id = getattr(r, "input_id", None) or None
                if inp_id:
                    valid_input_ids.add(inp_id)

                actual_evids = [e for e in getattr(r, "evidence_ids", []) if e]
                ref_eid = getattr(r, "reference_evidence_id", None)
                tgt_eid = getattr(r, "target_evidence_id", None)

                candidate_eids = list(actual_evids)
                if ref_eid:
                    candidate_eids.append(ref_eid)
                if tgt_eid:
                    candidate_eids.append(tgt_eid)

                for eid in candidate_eids:
                    rec = resolve_authoritative_evidence(eid, record_by_id)
                    if rec is not None:
                        valid_evid_ids.add(rec.evidence_id)
                        record_by_id[rec.evidence_id] = rec
                        role_str = str(rec.role).lower()
                        if role_str in ("reference", "legacy") and not ref_eid:
                            ref_eid = eid
                        elif role_str in ("target", "modernized") and not tgt_eid:
                            tgt_eid = eid
                    else:
                        unresolved_evid_ids.add(eid)

                # Canonical input hash
                inp_hash = getattr(r, "input_hash", None)
                if not inp_hash and getattr(r, "input_values", None):
                    inp_hash = compute_canonical_input_hash(r.input_values)

                # Determine actual dimension
                raw_dim = getattr(r, "dimension", None) or getattr(r, "domain", None)
                dim_str = "UNKNOWN"
                if raw_dim:
                    if isinstance(raw_dim, BehaviorDimension):
                        dim_str = raw_dim.value
                    elif str(raw_dim).upper() in {d.value for d in BehaviorDimension}:
                        dim_str = str(raw_dim).upper()
                elif getattr(r, "legacy_output", None) is not None or getattr(r, "modern_output", None) is not None:
                    dim_str = BehaviorDimension.OUTPUT.value

                valid_r_evids = [e for e in actual_evids if e in valid_evid_ids]

                diff_record = {
                    "difference_id": r.regression_id,
                    "dimension": dim_str,
                    "input_id": inp_id,
                    "input_hash": inp_hash,
                    "reference_value": r.legacy_output,
                    "target_value": r.modern_output,
                    "reference_evidence_id": ref_eid if ref_eid in valid_evid_ids else None,
                    "target_evidence_id": tgt_eid if tgt_eid in valid_evid_ids else None,
                    "evidence_ids": valid_r_evids,
                    "input_values": r.input_values,
                    "failed_assertion": r.failed_assertion,
                    "severity": r.severity,
                    "violated_oracle_ids": [r.oracle_id] if getattr(r, "oracle_id", None) else [],
                }
                differences_summary.append(diff_record)

        # 4. Phase 7 Reconciled OracleSet Loading (Authoritative Grounding)
        rules_context: list[dict[str, Any]] = []
        canonical_oracle_set: Optional[OracleSet] = oracle_set

        if not canonical_oracle_set and artifact:
            oset_id = getattr(artifact, "oracle_set_id", None)
            if not oset_id and artifact.context and hasattr(artifact.context, "oracle_set_id"):
                oset_id = getattr(artifact.context, "oracle_set_id", None)
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
                    "provenance": "PHASE_7_RECONCILED",
                }
                rules_context.append(rule_dict)
        elif is_legacy_mode and artifact and artifact.oracle_summaries:
            # Compatibility fallback explicitly restricted to legacy mode
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
                    "provenance": "LEGACY_COMPATIBILITY",
                }
                rules_context.append(rule_dict)

        # 5. Phase 8 Exact Dynamic Threshold Resolution Loading (with Fingerprint Verification)
        thresholds_context: list[dict[str, Any]] = []
        resolved_thresh: Optional[ThresholdResolution] = threshold_resolution

        if not resolved_thresh and artifact and artifact.certification_policy_id:
            exact_res_id = getattr(artifact, "threshold_resolution_id", None)
            if not exact_res_id and artifact.context and hasattr(artifact.context, "threshold_resolution_id"):
                exact_res_id = getattr(artifact.context, "threshold_resolution_id", None)

            exact_res_fp = getattr(artifact, "threshold_resolution_fingerprint", None)
            if not exact_res_fp and artifact.context and hasattr(artifact.context, "threshold_resolution_fingerprint"):
                exact_res_fp = getattr(artifact.context, "threshold_resolution_fingerprint", None)

            try:
                pol = threshold_persistence.get_policy(artifact.certification_policy_id)
                if pol:
                    with threshold_persistence._get_connection() as conn:
                        if exact_res_id and exact_res_fp:
                            row = conn.execute(
                                "SELECT resolution_json, fingerprint, final_value, status, sample_count FROM threshold_resolutions WHERE resolution_id = ?",
                                (exact_res_id,),
                            ).fetchone()
                            if row:
                                loaded_fp = row["fingerprint"]
                                if loaded_fp != exact_res_fp:
                                    logger.error(f"Threshold resolution fingerprint mismatch: expected '{exact_res_fp}', got '{loaded_fp}'")
                                    threshold_dict = {
                                        "policy_id": pol.policy_id,
                                        "error": "THRESHOLD_CONTEXT_ERROR: Fingerprint mismatch",
                                        "status": "ERROR",
                                    }
                                else:
                                    pol_hash = pol.compute_policy_hash() if hasattr(pol, "compute_policy_hash") else getattr(pol, "policy_hash", "")
                                    fb_used = False
                                    fb_reason = None
                                    if row["resolution_json"]:
                                        try:
                                            rj = json.loads(row["resolution_json"])
                                            fb_used = rj.get("fallback_used", False)
                                            fb_reason = rj.get("fallback_reason")
                                        except Exception:
                                            pass
                                    threshold_dict = {
                                        "policy_id": pol.policy_id,
                                        "version": pol.version,
                                        "metric": pol.metric.value if hasattr(pol.metric, "value") else str(pol.metric),
                                        "strategy": pol.strategy.value if hasattr(pol.strategy, "value") else str(pol.strategy),
                                        "resolution_id": exact_res_id,
                                        "policy_hash": pol_hash,
                                        "resolution_fingerprint": loaded_fp,
                                        "resolved_threshold": row["final_value"],
                                        "resolution_status": row["status"],
                                        "sample_count": row["sample_count"],
                                        "fallback_used": fb_used,
                                        "fallback_reason": fb_reason,
                                    }
                                thresholds_context.append(threshold_dict)
                            else:
                                threshold_dict = {
                                    "policy_id": pol.policy_id,
                                    "status": "INCONCLUSIVE",
                                    "reason": f"Exact threshold resolution '{exact_res_id}' not found in persistence.",
                                }
                                thresholds_context.append(threshold_dict)
                        else:
                            # Both ID and fingerprint must be present; fail closed if either is missing
                            missing_items = []
                            if not exact_res_id:
                                missing_items.append("threshold_resolution_id")
                            if not exact_res_fp:
                                missing_items.append("threshold_resolution_fingerprint")
                            threshold_dict = {
                                "policy_id": pol.policy_id,
                                "status": "INCONCLUSIVE",
                                "reason": f"Exact threshold resolution authority missing: {', '.join(missing_items)}.",
                            }
                            thresholds_context.append(threshold_dict)
            except Exception as exc:
                logger.debug(f"Phase 8 policy resolution not found in persistence: {exc}")
        elif resolved_thresh:
            if not resolved_thresh.resolution_id or not resolved_thresh.fingerprint:
                threshold_dict = {
                    "policy_id": resolved_thresh.policy_id,
                    "status": "INCONCLUSIVE",
                    "reason": "Direct threshold resolution missing resolution_id or fingerprint.",
                }
            else:
                threshold_dict = {
                    "policy_id": resolved_thresh.policy_id,
                    "version": getattr(resolved_thresh, "policy_version", "1.0.0"),
                    "metric": resolved_thresh.metric.value if hasattr(resolved_thresh.metric, "value") else str(resolved_thresh.metric),
                    "strategy": resolved_thresh.strategy.value if hasattr(resolved_thresh.strategy, "value") else str(resolved_thresh.strategy),
                    "resolution_id": resolved_thresh.resolution_id,
                    "resolution_fingerprint": resolved_thresh.fingerprint,
                    "resolved_threshold": resolved_thresh.final_value,
                    "resolution_status": resolved_thresh.status.value if hasattr(resolved_thresh.status, "value") else str(resolved_thresh.status),
                    "sample_count": resolved_thresh.sample_count,
                    "fallback_used": getattr(resolved_thresh, "fallback_used", False),
                    "fallback_reason": getattr(resolved_thresh, "fallback_reason", None),
                }
            thresholds_context.append(threshold_dict)

        # 6. Authoritative State & Workflow Evidence Analysis from Phase 3 Evidence Records
        missing_evidence: list[MissingEvidence] = []
        state_facts: list[StateEvidenceFact] = []
        workflow_facts: list[WorkflowTraceFact] = []

        for r in all_records:
            if r.evidence_type in (EvidenceType.DATABASE, EvidenceType.FILESYSTEM):
                payload = r.payload or {}
                resource = (
                    payload.get("table")
                    or payload.get("connection_target")
                    or (payload.get("configured_paths", [None])[0] if payload.get("configured_paths") else None)
                    or r.metadata.get("resource")
                )
                before = payload.get("snapshot_before") or payload.get("table_row_counts_before") or payload.get("before_state")
                after = payload.get("snapshot_after") or payload.get("table_row_counts_after") or payload.get("after_state")
                delta = payload.get("delta") or payload.get("modified_files") or payload.get("created_files") or payload.get("deleted_files")
                delta_detected = bool(payload.get("delta_detected", False) or delta)

                state_facts.append(
                    StateEvidenceFact(
                        evidence_id=r.evidence_id,
                        role=r.role,
                        evidence_type=r.evidence_type.value,
                        resource=str(resource) if resource else None,
                        before=before,
                        after=after,
                        delta=delta,
                        delta_detected=delta_detected,
                        provenance=r.provenance,
                        timestamp=r.timestamp,
                    )
                )

            elif r.evidence_type == EvidenceType.TRACE:
                payload = r.payload or {}
                events = payload.get("events", [])
                if isinstance(events, list) and events:
                    for ev in events:
                        if isinstance(ev, dict):
                            workflow_facts.append(
                                WorkflowTraceFact(
                                    evidence_id=r.evidence_id,
                                    role=r.role,
                                    event_type=ev.get("event_type", "INVOCATION"),
                                    sequence=ev.get("sequence", 0),
                                    ordering=ev.get("sequence", 0),
                                    action=ev.get("details", {}).get("action") or ev.get("source"),
                                    observed_divergence=ev.get("details", {}).get("divergence"),
                                    details=ev.get("details", {}) if isinstance(ev.get("details"), dict) else {},
                                    provenance=r.provenance,
                                    timestamp=ev.get("timestamp") or r.timestamp,
                                )
                            )
                else:
                    workflow_facts.append(
                        WorkflowTraceFact(
                            evidence_id=r.evidence_id,
                            role=r.role,
                            event_type="TRACE",
                            sequence=r.sequence,
                            ordering=r.sequence,
                            action=r.source,
                            details=payload,
                            provenance=r.provenance,
                            timestamp=r.timestamp,
                        )
                    )

        if not state_facts:
            missing_evidence.append(
                MissingEvidence(
                    dimension=BehaviorDimension.STATE,
                    description="Database and memory state snapshots were not collected for this certification run.",
                    implication="State equivalence is inconclusive as physical storage mutations were not recorded.",
                    status="INCONCLUSIVE",
                )
            )

        if not workflow_facts:
            missing_evidence.append(
                MissingEvidence(
                    dimension=BehaviorDimension.WORKFLOW,
                    description="Workflow execution trace telemetry was not captured for single-invocation execution.",
                    implication="Intermediate workflow step sequence equivalence could not be established from the available evidence.",
                    status="INCONCLUSIVE",
                )
            )

        if is_strict_v2 and not evaluation_result:
            missing_evidence.append(
                MissingEvidence(
                    dimension=BehaviorDimension.OUTPUT,
                    description="Authoritative Phase 4 EvaluationResult was not provided for this certification run.",
                    implication="Behavioral equivalence could not be conclusively verified due to missing evaluation authority.",
                    status="INCONCLUSIVE",
                )
            )

        # Derive evaluated dimensions strictly from Phase 4 EvaluationResult
        evaluated_dims_set = set()
        if evaluation_result:
            if hasattr(evaluation_result, "dimensions_evaluated") and evaluation_result.dimensions_evaluated:
                for d in evaluation_result.dimensions_evaluated:
                    if isinstance(d, BehaviorDimension):
                        evaluated_dims_set.add(d)
                    elif isinstance(d, str) and hasattr(BehaviorDimension, d.upper()):
                        evaluated_dims_set.add(BehaviorDimension[d.upper()])

            if hasattr(evaluation_result, "summary") and evaluation_result.summary:
                if hasattr(evaluation_result.summary, "dimension_summaries") and evaluation_result.summary.dimension_summaries:
                    for dim_key in evaluation_result.summary.dimension_summaries.keys():
                        if isinstance(dim_key, BehaviorDimension):
                            evaluated_dims_set.add(dim_key)
                        elif isinstance(dim_key, str) and hasattr(BehaviorDimension, dim_key.upper()):
                            evaluated_dims_set.add(BehaviorDimension[dim_key.upper()])

            if hasattr(evaluation_result, "input_results") and evaluation_result.input_results:
                for ir in evaluation_result.input_results:
                    if hasattr(ir, "dimension_results") and ir.dimension_results:
                        for dim_key in ir.dimension_results.keys():
                            if isinstance(dim_key, BehaviorDimension):
                                evaluated_dims_set.add(dim_key)
                            elif isinstance(dim_key, str) and hasattr(BehaviorDimension, dim_key.upper()):
                                evaluated_dims_set.add(BehaviorDimension[dim_key.upper()])

            if evaluation_result.differences:
                for diff in evaluation_result.differences:
                    if isinstance(diff.dimension, BehaviorDimension):
                        evaluated_dims_set.add(diff.dimension)
                    elif isinstance(diff.dimension, str) and hasattr(BehaviorDimension, diff.dimension.upper()):
                        evaluated_dims_set.add(BehaviorDimension[diff.dimension.upper()])
        elif differences_summary:
            for d in differences_summary:
                dim_str = d.get("dimension")
                if dim_str and dim_str != "UNKNOWN" and hasattr(BehaviorDimension, str(dim_str).upper()):
                    evaluated_dims_set.add(BehaviorDimension[str(dim_str).upper()])

        if not is_strict_v2 and not evaluated_dims_set and artifact and artifact.metrics and (getattr(artifact.metrics, "unique_input_count", 0) > 0 or getattr(artifact.metrics, "matching_case_count", 0) > 0):
            evaluated_dims_set.add(BehaviorDimension.OUTPUT)

        dimensions_evaluated = sorted(list(evaluated_dims_set), key=lambda d: d.value)

        # 7. Optional Phase 9 Knowledge Context Retrieval
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

        # 8. Redact All Payloads
        redacted_diffs = redact_sensitive_data(differences_summary)
        redacted_rules = redact_sensitive_data(rules_context)

        # Derive evaluation counts authoritatively from Phase 4 EvaluationResult if present
        equiv_score: Optional[float] = None
        total_inputs: Optional[int] = None
        matching_count: Optional[int] = None
        regression_count: Optional[int] = None

        if evaluation_result:
            if hasattr(evaluation_result, "summary") and evaluation_result.summary and (getattr(evaluation_result.summary, "total_inputs", 0) > 0 or getattr(evaluation_result.summary, "evaluated_inputs", 0) > 0):
                total_inputs = getattr(evaluation_result.summary, "evaluated_inputs", 0) or getattr(evaluation_result.summary, "total_inputs", 0)
                matching_count = getattr(evaluation_result.summary, "equivalent_inputs", 0)
                regression_count = getattr(evaluation_result.summary, "different_inputs", 0) or getattr(evaluation_result.summary, "total_differences", 0)
            elif hasattr(evaluation_result, "input_results") and evaluation_result.input_results:
                total_inputs = len(evaluation_result.input_results)
                regression_count = len([ir for ir in evaluation_result.input_results if getattr(ir, "verdict", None) == EvaluationVerdict.DIFFERENT or getattr(ir, "differences", None)])
                matching_count = total_inputs - regression_count
            else:
                regression_count = len(differences_summary)
                total_inputs = len(valid_input_ids) or regression_count or 1
                matching_count = max(0, total_inputs - regression_count)

            if total_inputs is not None and total_inputs > 0:
                equiv_score = float(matching_count or 0) / float(total_inputs)
            else:
                equiv_score = 0.0
        elif not is_strict_v2:
            total_inputs = len(valid_input_ids) or (artifact.metrics.unique_input_count if artifact and artifact.metrics else 1)
            matching_count = (artifact.metrics.matching_case_count if artifact and artifact.metrics else 0)
            regression_count = len(differences_summary) or (artifact.metrics.regression_case_count if artifact and artifact.metrics else 0)
            equiv_score = artifact.score if artifact else 0.0
        else:
            # Strict V2 with missing EvaluationResult: represent as unavailable/None, not fake numerical evaluation
            total_inputs = None
            matching_count = None
            regression_count = None
            equiv_score = None

        # 9. Construct Context
        context = ExplanationContext(
            certification_id=certification_id or (artifact.certification_id if artifact else "UNKNOWN_CERT"),
            application_id=app_id,
            project_id=proj_id,
            session_id=actual_session_id,
            authoritative_verdict=verdict_str,
            equivalence_score=equiv_score,
            unique_inputs_count=total_inputs,
            matching_cases_count=matching_count,
            regression_cases_count=regression_count,
            dimensions_evaluated=dimensions_evaluated,
            differences_summary=redacted_diffs,
            valid_evidence_ids=sorted(valid_evid_ids),
            unresolved_evidence_ids=sorted(unresolved_evid_ids),
            valid_rule_ids=sorted(valid_rule_ids),
            valid_input_ids=sorted(valid_input_ids),
            rules_context=redacted_rules,
            thresholds_context=thresholds_context,
            missing_evidence=missing_evidence,
            state_facts=state_facts,
            workflow_facts=workflow_facts,
            knowledge_context=company_knowledge_context,
            user_question=user_question,
        )
        return context


explanation_context_builder = ExplanationContextBuilder()
