"""BEACON V2 — Phase 7 Rule Reconciliation & OracleSet Generation Engine.

Transforms Phase 5 user rules and Phase 6 discovered candidate rules into
a deterministic, auditable, provenance-preserving OracleSet for certification.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Optional
import uuid

from discovery.models import CandidateValidationStatus, DiscoveredCandidate, DiscoveryResult
from execution.evidence_models import EvidenceBundle
from rules.models import BusinessRule, RuleStatus
from .comparator import rule_comparator
from .models import (
    DecisionTraceRecord,
    OracleRule,
    OracleSet,
    OracleSetStatus,
    ReconciliationDiagnostic,
    ReconciliationPolicy,
    ReconciliationResult,
    ResolutionState,
    RuleConflict,
    RuleProvenanceSource,
    RuleRelationship,
    compute_deterministic_hash,
)
from .normalizer import NormalizedRuleRepresentation, rule_normalizer
from .persistence import reconciliation_persistence

logger = logging.getLogger("beacon.reconciliation.engine")


class RuleReconciliationEngine:
    """Orchestrates candidate filtering, semantic normalization, deduplication, conflict detection, and OracleSet assembly."""

    def reconcile(
        self,
        application_id: str,
        user_rules: Optional[list[BusinessRule]] = None,
        discovered_candidates: Optional[list[DiscoveredCandidate]] = None,
        discovery_result: Optional[DiscoveryResult] = None,
        evidence_bundle: Optional[EvidenceBundle] = None,
        policy: Optional[ReconciliationPolicy] = None,
        session_id: Optional[str] = None,
        version: int = 1,
        persist: bool = True,
    ) -> ReconciliationResult:
        """Executes full deterministic rule reconciliation and generates an OracleSet."""
        active_policy = policy or ReconciliationPolicy()
        run_id = f"recon_{uuid.uuid4().hex[:12]}"
        effective_session = session_id or (evidence_bundle.session_id if evidence_bundle else f"sess_{uuid.uuid4().hex[:8]}")

        # Gather inputs
        all_user_rules: list[BusinessRule] = list(user_rules or [])
        all_candidates: list[DiscoveredCandidate] = list(discovered_candidates or [])
        if discovery_result and not all_candidates:
            all_candidates = list(discovery_result.candidates)

        diagnostics: list[ReconciliationDiagnostic] = []
        decision_traces: list[DecisionTraceRecord] = []

        logger.info(
            f"[PHASE7] Starting reconciliation for app '{application_id}'. "
            f"Input user rules: {len(all_user_rules)}, discovered candidates: {len(all_candidates)}"
        )
        diagnostics.append(ReconciliationDiagnostic(
            stage="INGESTION",
            message=f"Ingested {len(all_user_rules)} user rules and {len(all_candidates)} discovered candidates.",
            details={"user_rule_count": len(all_user_rules), "candidate_count": len(all_candidates)},
        ))

        # ----------------------------------------------------------------------
        # 1. Candidate Eligibility Gate
        # ----------------------------------------------------------------------
        eligible_candidates: list[DiscoveredCandidate] = []
        rejected_candidate_count = 0

        for cand in all_candidates:
            reasons = []

            if active_policy.require_validated_candidates:
                if cand.validation_status != CandidateValidationStatus.VALIDATED:
                    reasons.append(f"Candidate validation status is {cand.validation_status.value} (requires VALIDATED).")

            if cand.support_count < active_policy.minimum_support_count:
                reasons.append(
                    f"Candidate support count {cand.support_count} < minimum required {active_policy.minimum_support_count}."
                )

            if cand.confidence < active_policy.minimum_confidence:
                reasons.append(
                    f"Candidate confidence {cand.confidence:.2f} < minimum required {active_policy.minimum_confidence:.2f}."
                )

            if not reasons:
                eligible_candidates.append(cand)
            else:
                rejected_candidate_count += 1
                decision_traces.append(DecisionTraceRecord(
                    trace_id=f"trace_{uuid.uuid4().hex[:8]}",
                    source_id=cand.candidate_id or cand.fingerprint[:16],
                    source_type="DISCOVERED",
                    normalized_expression=cand.canonical_expression,
                    decision="REJECTED",
                    reason="; ".join(reasons),
                ))

        logger.info(f"[PHASE7] Eligible candidates after filtering: {len(eligible_candidates)}, rejected: {rejected_candidate_count}")

        # ----------------------------------------------------------------------
        # 2. Normalization
        # ----------------------------------------------------------------------
        normalized_rules: list[NormalizedRuleRepresentation] = []

        for u_rule in all_user_rules:
            if u_rule.status in (RuleStatus.ACTIVE, RuleStatus.VALID, RuleStatus.DRAFT):
                norm = rule_normalizer.normalize_user_rule(u_rule)
                normalized_rules.append(norm)

        for c_cand in eligible_candidates:
            norm = rule_normalizer.normalize_discovered_candidate(c_cand)
            normalized_rules.append(norm)

        # Sort normalized rules deterministically before deduplication
        normalized_rules.sort(key=lambda r: (r.fingerprint, r.role_scope, r.source_id))

        # ----------------------------------------------------------------------
        # 3. Semantic Deduplication & Provenance Fusion
        # ----------------------------------------------------------------------
        dedup_list: list[NormalizedRuleRepresentation] = []
        merged_count = 0

        for r in normalized_rules:
            match_idx = None
            for idx, existing in enumerate(dedup_list):
                if r.role_scope == existing.role_scope:
                    if (
                        r.fingerprint == existing.fingerprint
                        or rule_comparator.compare_rules(r, existing)[0] == RuleRelationship.EQUIVALENT
                    ):
                        match_idx = idx
                        break

            if match_idx is None:
                dedup_list.append(r)
            else:
                merged_count += 1
                existing = dedup_list[match_idx]
                # Fuse provenance
                fused_ev = sorted(list(set(existing.evidence_ids + r.evidence_ids)))
                fused_in = sorted(list(set(existing.input_ids + r.input_ids)))
                fused_rf = sorted(list(set(existing.source_rule_ids + r.source_rule_ids)))
                fused_cf = sorted(list(set(existing.source_candidate_ids + r.source_candidate_ids)))
                fused_fp = sorted(list(set(existing.candidate_fingerprints + r.candidate_fingerprints)))

                fused_source = (
                    RuleProvenanceSource.MERGED
                    if existing.source_type != r.source_type or existing.source_type == RuleProvenanceSource.MERGED
                    else existing.source_type
                )
                # Aggregate empirical counts accurately without fabrication
                if fused_in:
                    fused_support = max(len(fused_in), max(existing.support_count, r.support_count))
                else:
                    fused_support = max(existing.support_count, r.support_count)
                fused_contra = max(existing.contradiction_count, r.contradiction_count)
                fused_unknown = max(existing.unknown_count, r.unknown_count)
                fused_app = fused_support + fused_contra
                fused_conf = round(fused_support / fused_app, 4) if fused_app > 0 else max(existing.confidence, r.confidence)

                dedup_list[match_idx] = existing.model_copy(update={
                    "source_type": fused_source,
                    "evidence_ids": fused_ev,
                    "input_ids": fused_in,
                    "source_rule_ids": fused_rf,
                    "source_candidate_ids": fused_cf,
                    "candidate_fingerprints": fused_fp,
                    "support_count": fused_support,
                    "contradiction_count": fused_contra,
                    "unknown_count": fused_unknown,
                    "applicable_count": fused_app,
                    "confidence": fused_conf,
                })

                decision_traces.append(DecisionTraceRecord(
                    trace_id=f"trace_{uuid.uuid4().hex[:8]}",
                    source_id=r.source_id,
                    source_type="USER_DEFINED" if r.source_type == RuleProvenanceSource.USER_DEFINED else "DISCOVERED",
                    normalized_expression=r.canonical_expression,
                    decision="MERGED",
                    reason="Fused with identical semantic rule",
                    target_oracle_rule_id=existing.source_id,
                ))

        unique_normalized = list(dedup_list)
        unique_normalized.sort(key=lambda r: (r.fingerprint, r.role_scope, r.source_id))

        # ----------------------------------------------------------------------
        # 4. Relationship & Conflict Analysis
        # ----------------------------------------------------------------------
        conflicts: list[RuleConflict] = []
        conflicted_fingerprints: set[str] = set()

        for i in range(len(unique_normalized)):
            for j in range(i + 1, len(unique_normalized)):
                rule_a = unique_normalized[i]
                rule_b = unique_normalized[j]

                rel, reason = rule_comparator.compare_rules(rule_a, rule_b)

                if rel == RuleRelationship.CONFLICT:
                    conflicted_fingerprints.add(rule_a.fingerprint)
                    conflicted_fingerprints.add(rule_b.fingerprint)

                    conflict = RuleConflict(
                        conflict_id=f"conf_{compute_deterministic_hash([rule_a.source_id, rule_b.source_id])[:12]}",
                        rule_a_id=rule_a.source_id,
                        rule_b_id=rule_b.source_id,
                        rule_a_source=rule_a.source_type.value,
                        rule_b_source=rule_b.source_type.value,
                        relationship=RuleRelationship.CONFLICT,
                        reason=reason,
                        evidence_ids=sorted(list(set(rule_a.evidence_ids + rule_b.evidence_ids))),
                    )
                    conflicts.append(conflict)

                    decision_traces.append(DecisionTraceRecord(
                        trace_id=f"trace_{uuid.uuid4().hex[:8]}",
                        source_id=rule_a.source_id,
                        source_type="USER_DEFINED" if rule_a.source_type == RuleProvenanceSource.USER_DEFINED else "DISCOVERED",
                        normalized_expression=rule_a.canonical_expression,
                        decision="CONFLICTED",
                        reason=reason,
                        related_rule_ids=[rule_b.source_id],
                    ))

        # ----------------------------------------------------------------------
        # 5. Rule Resolution & Oracle Assembly
        # ----------------------------------------------------------------------
        approved_oracle_rules: list[OracleRule] = []

        for norm in unique_normalized:
            if norm.fingerprint in conflicted_fingerprints:
                # Quarantined / conflicted
                continue

            rule_id = f"oracle_{norm.fingerprint[:12]}"
            o_rule = OracleRule(
                rule_id=rule_id,
                rule_type=norm.rule_type,
                name=norm.name,
                description=norm.description,
                canonical_expression=norm.canonical_expression,
                conditions=norm.normalized_conditions,
                expected_behavior=norm.normalized_expected_behavior,
                role_scope=norm.role_scope,
                source=norm.source_type,
                resolution_state=ResolutionState.APPROVED,
                confidence=norm.confidence,
                support_count=norm.support_count,
                contradiction_count=norm.contradiction_count,
                unknown_count=norm.unknown_count,
                applicable_count=norm.applicable_count,
                evidence_ids=norm.evidence_ids,
                input_ids=norm.input_ids,
                source_rule_ids=norm.source_rule_ids,
                source_candidate_ids=norm.source_candidate_ids,
                candidate_fingerprints=norm.candidate_fingerprints,
                decision_trace=[
                    dt for dt in decision_traces if dt.source_id in (norm.source_rule_ids + norm.source_candidate_ids)
                ],
                fingerprint=norm.fingerprint,
            )
            approved_oracle_rules.append(o_rule)

            decision_traces.append(DecisionTraceRecord(
                trace_id=f"trace_{uuid.uuid4().hex[:8]}",
                source_id=norm.source_id,
                source_type="USER_DEFINED" if norm.source_type == RuleProvenanceSource.USER_DEFINED else "DISCOVERED",
                normalized_expression=norm.canonical_expression,
                decision="ADMITTED",
                reason="Satisfies reconciliation eligibility and is free of behavioral conflicts.",
                target_oracle_rule_id=rule_id,
            ))

        # Deterministic sorting of approved rules
        approved_oracle_rules.sort(key=lambda r: (r.fingerprint, r.role_scope, r.rule_id))

        # ----------------------------------------------------------------------
        # 6. OracleSet Construction (Fail-Closed: Any unresolved conflict -> BLOCKED)
        # ----------------------------------------------------------------------
        unresolved_conflicts = [c for c in conflicts if c.resolution_status == "UNRESOLVED"]
        oracle_set_status = (
            OracleSetStatus.BLOCKED
            if unresolved_conflicts
            else OracleSetStatus.READY
        )

        oracle_set_id = f"os_{application_id}_v{version}"
        oracle_set = OracleSet(
            oracle_set_id=oracle_set_id,
            application_id=application_id,
            version=version,
            status=oracle_set_status,
            rules=approved_oracle_rules,
            conflicts=conflicts,
            provenance={
                "run_id": run_id,
                "session_id": effective_session,
                "input_user_rules": len(all_user_rules),
                "input_candidates": len(all_candidates),
                "eligible_candidates": len(eligible_candidates),
                "merged_rules": merged_count,
                "unresolved_conflicts": len(conflicts),
            },
        )

        result = ReconciliationResult(
            run_id=run_id,
            application_id=application_id,
            session_id=effective_session,
            policy=active_policy,
            input_rule_count=len(all_user_rules),
            input_candidate_count=len(all_candidates),
            normalized_count=len(normalized_rules),
            merged_count=merged_count,
            approved_count=len(approved_oracle_rules),
            rejected_count=rejected_candidate_count,
            conflict_count=len(conflicts),
            unresolved_conflict_count=len([c for c in conflicts if c.resolution_status == "UNRESOLVED"]),
            rules=approved_oracle_rules,
            conflicts=conflicts,
            decision_traces=decision_traces,
            diagnostics=diagnostics,
            oracle_set=oracle_set,
            oracle_set_id=oracle_set.oracle_set_id,
            oracle_set_version=oracle_set.version,
            overall_status="COMPLETE",
            persistence_status="NOT_REQUESTED",
        )

        # ----------------------------------------------------------------------
        # 7. Persistence
        # ----------------------------------------------------------------------
        if persist:
            try:
                reconciliation_persistence.save_reconciliation_result(result)
                result.persistence_status = "PERSISTED"
                logger.info(f"[PHASE7] Persisted reconciliation result '{result.run_id}' and OracleSet '{oracle_set.oracle_set_id}'.")
            except Exception as exc:
                logger.error(f"[PHASE7] Persistence failed for run '{result.run_id}': {exc}")
                result.persistence_status = "FAILED"
                result.overall_status = "PARTIAL"
                diagnostics.append(ReconciliationDiagnostic(
                    stage="PERSISTENCE",
                    severity="ERROR",
                    message=f"Reconciliation persistence failed: {exc}",
                ))

        logger.info(
            f"[PHASE7] Reconciliation complete. Status: {result.overall_status}, "
            f"Approved rules: {result.approved_count}, Conflicts: {result.conflict_count}, "
            f"OracleSet Status: {oracle_set.status.value}"
        )
        return result


rule_reconciliation_engine = RuleReconciliationEngine()
