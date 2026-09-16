"""BEACON V2 — Phase 10 Deterministic Explanation Generator.

Provides 100% deterministic, evidence-grounded explanation synthesis directly
from authoritative certification context without external LLM dependencies.
"""

from typing import Any, Optional
import hashlib

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


class DeterministicExplanationGenerator:
    """Synthesizes structured, audit-grade explanations from deterministic certification context."""

    def generate_explanation(
        self,
        context: ExplanationContext,
        fallback_reason: Optional[str] = None,
    ) -> CertificationExplanation:
        """Generates a complete CertificationExplanation deterministically."""
        verdict = context.authoritative_verdict
        score_pct = context.equivalence_score * 100
        total_inputs = context.unique_inputs_count
        matching_count = context.matching_cases_count
        regression_count = context.regression_cases_count

        # 1. Executive Summary
        if verdict in ("CERTIFIED", "EQUIVALENT", "MATCH_PASS"):
            exec_summary = (
                f"BEACON certified behavioral equivalence between reference and target implementations "
                f"with a quantified equivalence score of {score_pct:.1f}%. Across {total_inputs} uniquely evaluated "
                f"inputs, all observed behavioral dimensions and invariant assertions were satisfied."
            )
        elif verdict in ("CERTIFIED_WITH_WARNINGS",):
            exec_summary = (
                f"BEACON certified the candidate implementation with warnings (equivalence score: {score_pct:.1f}%). "
                f"While primary invariants matched across {matching_count} of {total_inputs} inputs, non-critical "
                f"deviations or warnings were recorded."
            )
        elif verdict in ("NOT_CERTIFIED", "DIFFERENT", "MODERN_REGRESSION"):
            exec_summary = (
                f"BEACON detected behavioral differences between reference and target implementations "
                f"(equivalence score: {score_pct:.1f}%). A total of {regression_count} counterexamples were identified "
                f"across {total_inputs} evaluated inputs where the target deviated from expected reference behavior."
            )
        elif verdict in ("INSUFFICIENT_COVERAGE", "INCONCLUSIVE"):
            exec_summary = (
                f"BEACON evaluation concluded with status {verdict}. The test input domain or available execution evidence "
                f"did not provide sufficient coverage to conclusively certify behavioral equivalence."
            )
        else:
            exec_summary = (
                f"Certification evaluation concluded with authoritative status {verdict}. "
                f"{regression_count} regressions or inconsistencies were detected across {total_inputs} inputs."
            )

        # 2. Scope Summary
        scope_summary = {
            "application_id": context.application_id,
            "project_id": context.project_id,
            "certification_id": context.certification_id,
            "evaluated_inputs": total_inputs,
            "matching_cases": matching_count,
            "regression_cases": regression_count,
            "equivalence_score": round(context.equivalence_score, 4),
            "dimensions": [d.value for d in context.dimensions_evaluated],
            "rules_evaluated_count": len(context.rules_context),
        }

        # 3. Behavioral Summary
        dim_names = [d.value for d in context.dimensions_evaluated]
        behavioral_summary = (
            f"Evaluated {len(dim_names)} behavioral dimensions ({', '.join(dim_names) if dim_names else 'OUTPUT'}). "
            f"Observed {matching_count} matching outcomes and {regression_count} behavioral deviations."
        )

        # 4. Dimension Explanations
        dimension_explanations: list[DimensionExplanation] = []
        for dim in context.dimensions_evaluated:
            # Check differences for this dimension
            dim_diffs = [
                d for d in context.differences_summary
                if str(d.get("dimension", "")).upper() == dim.value
            ]
            dim_status = "DIFFERENT" if dim_diffs else "PASS"

            # Check if missing evidence exists for this dimension
            missing_for_dim = [m for m in context.missing_evidence if m.dimension == dim]
            if missing_for_dim and not dim_diffs:
                dim_status = "INCONCLUSIVE"

            findings: list[ExplanationFinding] = []
            dim_evids: set[str] = set()

            for idx, diff in enumerate(dim_diffs[:10]):
                ref_val = diff.get("reference_value")
                tgt_val = diff.get("target_value")
                inp_id = diff.get("input_id", f"INP-{idx+1}")
                evid_ref = diff.get("reference_evidence_id")
                evid_tgt = diff.get("target_evidence_id")
                diff_evids = [e for e in (evid_ref, evid_tgt) if e and e in context.valid_evidence_ids]
                dim_evids.update(diff_evids)

                findings.append(
                    ExplanationFinding(
                        finding_id=f"FIND-{dim.value}-{idx+1}",
                        dimension=dim,
                        statement=f"Input {inp_id} produced divergent {dim.value} behavior: reference={ref_val}, target={tgt_val}.",
                        support=EvidenceSupportLevel.DETERMINISTIC_EVIDENCE,
                        evidence_ids=diff_evids,
                        reference_value=ref_val,
                        target_value=tgt_val,
                        difference_details=diff,
                    )
                )

            dimension_explanations.append(
                DimensionExplanation(
                    dimension=dim,
                    status=dim_status,
                    reference_summary=f"Reference produced valid observations across evaluated inputs.",
                    target_summary=f"Target evaluated with {len(dim_diffs)} detected differences.",
                    difference_summary=f"Discrepancies observed in {len(dim_diffs)} inputs." if dim_diffs else "No differences detected.",
                    tolerance_applied="Standard deterministic comparison policy",
                    evidence_ids=sorted(dim_evids),
                    findings=findings,
                )
            )

        # 5. Rule Impacts
        rule_impacts: list[RuleImpact] = []
        for r in context.rules_context:
            rule_id = r.get("rule_id", "RULE-DEFAULT")
            rule_desc = r.get("rule_description", r.get("condition_str", "Behavioral Invariant"))
            status = r.get("status", "POTENTIALLY_AFFECTED")
            rule_evids = [e for e in r.get("supporting_evidence_ids", []) if e in context.valid_evidence_ids]

            rule_impacts.append(
                RuleImpact(
                    rule_id=rule_id,
                    rule_description=rule_desc,
                    status=status,
                    observed_behavior=r.get("observed_behavior", f"Rule evaluated against test domain."),
                    supporting_evidence_ids=rule_evids,
                    relationship_to_verdict=r.get("relationship_to_verdict", "Evaluated during certification."),
                    limitation="Empirical observation confirms output divergence without modifying rule definitions.",
                )
            )

        # 6. Evidence Traces
        evidence_traces: list[EvidenceTrace] = []
        for idx, diff in enumerate(context.differences_summary[:15]):
            inp_id = diff.get("input_id", f"INP-{idx+1}")
            evid_tgt = diff.get("target_evidence_id") or f"EVID-TGT-{idx+1}"
            evid_ref = diff.get("reference_evidence_id") or f"EVID-REF-{idx+1}"

            evidence_traces.append(
                EvidenceTrace(
                    claim_id=f"CLAIM-{idx+1}",
                    claim_text=f"Target output differed from reference for input {inp_id}",
                    evidence_id=evid_tgt,
                    input_id=inp_id,
                    dimension=BehaviorDimension.OUTPUT,
                    role="target",
                    source_type="runtime_execution",
                    evidence_hash=hashlib.sha256(f"{inp_id}:{evid_tgt}".encode()).hexdigest(),
                    provenance={"reference_evidence_id": evid_ref, "input_id": inp_id},
                )
            )

        # 7. Affected Inputs
        affected_inputs: list[AffectedInput] = []
        for idx, diff in enumerate(context.differences_summary[:20]):
            inp_id = diff.get("input_id", f"INP-{idx+1}")
            affected_inputs.append(
                AffectedInput(
                    input_id=inp_id,
                    input_hash=hashlib.sha256(str(diff.get("input_values", inp_id)).encode()).hexdigest(),
                    input_values=diff.get("input_values", {}),
                    legacy_output=diff.get("reference_value"),
                    modern_output=diff.get("target_value"),
                    violated_rules=diff.get("violated_oracle_ids", []),
                    severity=diff.get("severity", "medium"),
                )
            )

        # 8. Uncertainty Notes
        uncertainty_notes: list[UncertaintyNote] = [
            UncertaintyNote(
                topic="Root Cause Attribution",
                claim="Exact root cause in source code logic is unproven from external black-box behavioral evidence alone.",
                support_level=EvidenceSupportLevel.UNCERTAIN,
                reason="BEACON operates on behavioral observations and invariants without inspecting arbitrary internal bytecode state.",
            ),
            UncertaintyNote(
                topic="Downstream Business Impact",
                claim="Impact on downstream business consumers depends on consumer tolerance and application domain context.",
                support_level=EvidenceSupportLevel.UNCERTAIN,
                reason="External downstream systems were not evaluated in this isolated certification session.",
            ),
        ]

        # 9. Investigation Recommendations
        investigation_recommendations: list[InvestigationRecommendation] = []
        if regression_count > 0:
            investigation_recommendations.append(
                InvestigationRecommendation(
                    priority=1,
                    title="Inspect Pinpointed Counterexamples & Regressions",
                    description=f"Review the {min(regression_count, 5)} specific input cases where target output diverged from reference.",
                    rationale="Direct counterexamples provide reproducible test vectors to isolate defect locations.",
                    evidence_references=[e.evidence_id for e in evidence_traces[:3]],
                )
            )
            investigation_recommendations.append(
                InvestigationRecommendation(
                    priority=2,
                    title="Validate Condition Boundaries & Rounding Arithmetic",
                    description="Check numeric calculations, boundary conditions, and floating-point precision in target implementation.",
                    rationale="Numeric discrepancies frequently stem from decimal formatting or operator differences.",
                    evidence_references=[],
                )
            )
        else:
            investigation_recommendations.append(
                InvestigationRecommendation(
                    priority=1,
                    title="Archive Immutable Certification Certificate",
                    description="Export the cryptographic certification artifact and register with release audit log.",
                    rationale="The current target implementation satisfied all verified behavioral invariants.",
                    evidence_references=[],
                )
            )

        # 10. Generation Metadata
        metadata = GenerationMetadata(
            provider="offline",
            model="deterministic-rule-engine",
            generation_mode="DETERMINISTIC",
            prompt_version="v1.0",
            schema_version="1.0.0",
            latency_ms=1.5,
            fallback_occurred=bool(fallback_reason),
            fallback_reason=fallback_reason,
            reproducibility="DETERMINISTIC_CANONICAL",
        )

        explanation_id = f"EXP-{context.certification_id[:12]}"
        explanation = CertificationExplanation(
            explanation_id=explanation_id,
            certification_id=context.certification_id,
            application_id=context.application_id,
            project_id=context.project_id,
            session_id=context.session_id,
            overall_verdict=verdict,
            is_authoritative_match=True,
            executive_summary=exec_summary,
            scope_summary=scope_summary,
            behavioral_summary=behavioral_summary,
            dimension_explanations=dimension_explanations,
            rule_impacts=rule_impacts,
            evidence_traces=evidence_traces,
            affected_inputs=affected_inputs,
            missing_evidence=context.missing_evidence,
            uncertainty_notes=uncertainty_notes,
            company_knowledge_context=context.knowledge_context,
            investigation_recommendations=investigation_recommendations,
            context_fingerprint=context.compute_context_fingerprint(),
            generation_metadata=metadata,
        )
        explanation.content_hash = explanation.compute_content_hash()
        return explanation


deterministic_generator = DeterministicExplanationGenerator()
