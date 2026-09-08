"""BEACON V2 — Phase 6 Master Rule / Invariant Discovery Engine.

Orchestrates the entire Phase 6 discovery pipeline: Evidence extraction, ObservationMatrix construction,
domain-agnostic candidate hypothesis mining, empirical validation, deduplication, ranking, and persistence.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Optional
import uuid

from execution.evidence_models import EvidenceBundle
from .generators.boundary import BoundaryCandidateGenerator
from .generators.cross_input import CrossInputCandidateGenerator
from .generators.error_behavior import ErrorBehaviorCandidateGenerator
from .generators.input_output import InputOutputCandidateGenerator
from .generators.nullability import NullabilityCandidateGenerator
from .generators.relational import RelationalCandidateGenerator
from .generators.state import StateCandidateGenerator
from .generators.type_shape import TypeShapeCandidateGenerator
from .generators.workflow import WorkflowCandidateGenerator
from .matrix import observation_matrix_builder
from .models import (
    CandidateValidationStatus,
    DiscoveredCandidate,
    DiscoveryDiagnostic,
    DiscoveryPolicy,
    DiscoveryResult,
)
from .persistence import discovery_persistence
from .ranking import candidate_ranker
from .validator import candidate_validator

logger = logging.getLogger("beacon.discovery.engine")


class RuleDiscoveryEngine:
    """Master discovery engine discovering candidate behavioral rules and invariants from Phase 3 evidence."""

    def __init__(self):
        self.generators = [
            InputOutputCandidateGenerator(),
            CrossInputCandidateGenerator(),
            TypeShapeCandidateGenerator(),
            NullabilityCandidateGenerator(),
            RelationalCandidateGenerator(),
            ErrorBehaviorCandidateGenerator(),
            StateCandidateGenerator(),
            WorkflowCandidateGenerator(),
            BoundaryCandidateGenerator(),
        ]

    def discover_rules(
        self,
        bundle: EvidenceBundle,
        policy: Optional[DiscoveryPolicy] = None,
        phase4_result: Optional[Any] = None,
        persist: bool = True,
    ) -> DiscoveryResult:
        """Executes full rule and invariant discovery over an EvidenceBundle.

        Args:
            bundle: Tamper-evident Phase 3 EvidenceBundle.
            policy: Optional DiscoveryPolicy configuration.
            phase4_result: Optional Phase 4 EvaluationResult.
            persist: Whether to store results in SQLite.

        Returns:
            DiscoveryResult containing ranked, validated DiscoveredCandidates.
        """
        active_policy = policy or DiscoveryPolicy()
        discovery_id = f"disc_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        session_id = getattr(bundle, "session_id", "session_default")
        application_id = getattr(bundle, "application_id", "app_default")

        # 1. Build Normalized Observation Matrix
        matrix = observation_matrix_builder.build_matrix(bundle=bundle, phase4_result=phase4_result)

        raw_candidates: list[DiscoveredCandidate] = []
        diagnostics: list[DiscoveryDiagnostic] = []

        # Helper to execute a generator safely with structured diagnostics
        def run_generator(gen: Any, facts: list[Any], role: str) -> list[DiscoveredCandidate]:
            gen_name = getattr(gen, "generator_name", type(gen).__name__)

            # Check policy feature flags
            if gen_name == "state_generator" and not active_policy.enable_state_discovery:
                diagnostics.append(
                    DiscoveryDiagnostic(
                        generator_name=f"{gen_name}_{role}",
                        status="SKIPPED",
                        severity="INFO",
                        message="State discovery disabled by policy",
                        evidence_scope=role,
                    )
                )
                return []
            if gen_name == "boundary_generator" and not active_policy.enable_boundary_discovery:
                diagnostics.append(
                    DiscoveryDiagnostic(
                        generator_name=f"{gen_name}_{role}",
                        status="SKIPPED",
                        severity="INFO",
                        message="Boundary discovery disabled by policy",
                        evidence_scope=role,
                    )
                )
                return []
            if gen_name == "workflow_generator" and not active_policy.enable_sequence_discovery:
                diagnostics.append(
                    DiscoveryDiagnostic(
                        generator_name=f"{gen_name}_{role}",
                        status="SKIPPED",
                        severity="INFO",
                        message="Workflow sequence discovery disabled by policy",
                        evidence_scope=role,
                    )
                )
                return []

            try:
                cands = gen.generate_candidates(facts=facts, policy=active_policy, role_scope=role)
                diagnostics.append(
                    DiscoveryDiagnostic(
                        generator_name=f"{gen_name}_{role}",
                        status="SUCCESS",
                        severity="INFO",
                        candidate_count=len(cands),
                        evidence_scope=role,
                    )
                )
                return cands
            except Exception as exc:
                logger.warning(f"Generator {gen_name} failed on {role} facts: {exc}", exc_info=True)
                diagnostics.append(
                    DiscoveryDiagnostic(
                        generator_name=f"{gen_name}_{role}",
                        status="FAILED",
                        severity="ERROR",
                        message=str(exc),
                        exception_type=type(exc).__name__,
                        candidate_count=0,
                        evidence_scope=role,
                    )
                )
                return []

        # 2. Reference Discovery
        if matrix.reference_facts:
            for gen in self.generators:
                raw_candidates.extend(run_generator(gen, matrix.reference_facts, "reference"))

        # 3. Target Discovery
        if matrix.target_facts:
            for gen in self.generators:
                raw_candidates.extend(run_generator(gen, matrix.target_facts, "target"))

        generated_count = len(raw_candidates)

        # 4. Validate all candidates against their respective observation facts
        validated_candidates: list[DiscoveredCandidate] = []
        for cand in raw_candidates:
            facts_to_test = matrix.reference_facts if cand.role_scope == "reference" else matrix.target_facts
            val_cand = candidate_validator.validate_candidate(
                candidate=cand,
                facts=facts_to_test,
                policy=active_policy,
            )
            validated_candidates.append(val_cand)

        # 5. Detect Shared Candidates (Discovered and validated independently on both Ref and Target)
        ref_by_expr = {c.canonical_expression: c for c in validated_candidates if c.role_scope == "reference"}
        tgt_by_expr = {c.canonical_expression: c for c in validated_candidates if c.role_scope == "target"}

        common_exprs = set(ref_by_expr.keys()) & set(tgt_by_expr.keys())
        shared_candidates: list[DiscoveredCandidate] = []

        for expr in sorted(common_exprs):
            rc = ref_by_expr[expr]
            tc = tgt_by_expr[expr]
            if rc.validation_status in (CandidateValidationStatus.VALIDATED, CandidateValidationStatus.WEAK) and tc.validation_status in (CandidateValidationStatus.VALIDATED, CandidateValidationStatus.WEAK):
                combined_iids = sorted(list(set(rc.input_ids) | set(tc.input_ids)))
                combined_eids = sorted(list(set(rc.evidence_ids) | set(tc.evidence_ids)))
                shared_cand = DiscoveredCandidate(
                    discovery_id=f"disc_{uuid.uuid4().hex[:10]}",
                    candidate_id=f"cand_shared_{rc.candidate_id[5:] if len(rc.candidate_id) > 5 else rc.candidate_id}",
                    rule_type=rc.rule_type,
                    canonical_expression=rc.canonical_expression,
                    normalized_expression=rc.normalized_expression,
                    description=f"Shared invariant discovered on both Reference and Target: {rc.description}",
                    variables=rc.variables,
                    source_fields=rc.source_fields,
                    support_count=rc.support_count + tc.support_count,
                    contradiction_count=rc.contradiction_count + tc.contradiction_count,
                    unknown_count=rc.unknown_count + tc.unknown_count,
                    applicable_count=rc.applicable_count + tc.applicable_count,
                    observation_count=rc.observation_count + tc.observation_count,
                    support_ratio=round((rc.support_count + tc.support_count) / max(1, rc.observation_count + tc.observation_count), 4),
                    confidence=round((rc.support_count + tc.support_count) / max(1, rc.applicable_count + tc.applicable_count), 4),
                    complexity=rc.complexity,
                    validation_status=CandidateValidationStatus.VALIDATED if (rc.contradiction_count + tc.contradiction_count == 0) else CandidateValidationStatus.WEAK,
                    evidence_ids=combined_eids,
                    input_ids=combined_iids,
                    role_scope="both",
                    provenance={"reference_candidate_id": rc.candidate_id, "target_candidate_id": tc.candidate_id},
                    discovery_method=rc.discovery_method,
                    policy_version=active_policy.policy_version,
                )
                shared_candidates.append(shared_cand)

        all_candidates = validated_candidates + shared_candidates

        # 6. Deduplicate & Rank Deterministically
        ranked_candidates = candidate_ranker.deduplicate_and_rank(all_candidates, active_policy)

        # 7. Compute Summary Counts & Overall Status
        val_count = sum(1 for c in ranked_candidates if c.validation_status == CandidateValidationStatus.VALIDATED)
        contra_count = sum(1 for c in ranked_candidates if c.validation_status in (CandidateValidationStatus.CONTRADICTED, CandidateValidationStatus.WEAK))
        inconc_count = sum(1 for c in ranked_candidates if c.validation_status in (CandidateValidationStatus.INCONCLUSIVE, CandidateValidationStatus.INSUFFICIENT_COVERAGE))

        has_failures = any(d.status == "FAILED" or d.severity == "ERROR" for d in diagnostics)
        has_warnings = any(d.severity == "WARNING" for d in diagnostics)

        if has_failures:
            overall_status = "PARTIAL" if (val_count > 0 or generated_count > 0) else "FAILED"
        else:
            overall_status = "COMPLETE"

        total_observations = len(matrix.reference_facts) + len(matrix.target_facts)

        result = DiscoveryResult(
            discovery_id=discovery_id,
            application_id=application_id,
            session_id=session_id,
            policy=active_policy,
            policy_hash=active_policy.compute_policy_hash(),
            candidates=ranked_candidates,
            overall_status=overall_status,
            diagnostics=diagnostics,
            has_failures=has_failures,
            has_warnings=has_warnings,
            evidence_scope={
                "bundle_id": getattr(bundle, "bundle_id", ""),
                "session_id": session_id,
                "application_id": application_id,
                "reference_facts_count": len(matrix.reference_facts),
                "target_facts_count": len(matrix.target_facts),
            },
            observation_count=total_observations,
            generated_count=generated_count,
            validated_count=val_count,
            contradicted_count=contra_count,
            inconclusive_count=inconc_count,
        )

        # 8. Persistence
        if persist:
            try:
                discovery_persistence.save_discovery_result(result)
            except Exception as exc:
                logger.error(f"Failed to persist discovery result '{result.discovery_id}': {exc}")

        return result


rule_discovery_engine = RuleDiscoveryEngine()
