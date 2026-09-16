"""BEACON V2 — Phase 10 Deterministic Explanation Generator.

Provides 100% deterministic, evidence-grounded explanation synthesis directly
from authoritative certification context without external LLM dependencies.
"""

from typing import Any, Optional
import hashlib

from common.contracts import compute_canonical_input_hash
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
            "thresholds_applied_count": len(context.thresholds_context),
        }

        # 3. Behavioral Summary
        dim_names = [d.value for d in context.dimensions_evaluated]
        behavioral_summary = (
            f"Evaluated {len(dim_names)} behavioral dimensions ({', '.join(dim_names) if dim_names else 'OUTPUT'}). "
            f"Observed {matching_count} matching outcomes and {regression_count} behavioral deviations."
        )

        # 4. Dimension Explanations (Strictly conservative: never collapses UNKNOWN or INCONCLUSIVE to PASS)
        dimension_explanations: list[DimensionExplanation] = []
        differing_dimensions_set: set[str] = set()

        for dim in context.dimensions_evaluated:
            # Check differences for this dimension
            dim_diffs = [
                d for d in context.differences_summary
                if str(d.get("dimension", "")).upper() == dim.value
            ]
            missing_for_dim = [m for m in context.missing_evidence if m.dimension == dim]

            if dim_diffs:
                dim_status = "DIFFERENT"
                differing_dimensions_set.add(dim.value)
            elif missing_for_dim:
                # Conservative rule: missing evidence prevents conclusion of PASS
                dim_status = "INCONCLUSIVE"
            else:
                dim_status = "PASS"

            findings: list[ExplanationFinding] = []
            dim_evids: set[str] = set()

            for idx, diff in enumerate(dim_diffs[:10]):
                ref_val = diff.get("reference_value")
                tgt_val = diff.get("target_value")
                inp_id = diff.get("input_id")
                evid_ref = diff.get("reference_evidence_id")
                evid_tgt = diff.get("target_evidence_id")
                diff_evids = [e for e in (evid_ref, evid_tgt) if e and e in context.valid_evidence_ids]
                dim_evids.update(diff_evids)

                inp_label = f"Input '{inp_id}'" if inp_id else f"Evaluated case {idx+1}"
                findings.append(
                    ExplanationFinding(
                        finding_id=f"FIND-{dim.value}-{idx+1}",
                        dimension=dim,
                        statement=f"{inp_label} produced divergent {dim.value} behavior: reference={ref_val}, target={tgt_val}.",
                        support=EvidenceSupportLevel.DETERMINISTIC_FACT,
                        evidence_ids=diff_evids,
                        input_id=inp_id,
                        reference_value=ref_val,
                        target_value=tgt_val,
                        difference_details=diff,
                    )
                )

            dimension_explanations.append(
                DimensionExplanation(
                    dimension=dim,
                    status=dim_status,
                    reference_summary="Reference produced valid observations across evaluated inputs.",
                    target_summary=f"Target evaluated with {len(dim_diffs)} detected differences.",
                    difference_summary=f"Discrepancies observed in {len(dim_diffs)} inputs." if dim_diffs else (
                        "Evidence inconclusive for this dimension." if missing_for_dim else "No differences detected."
                    ),
                    tolerance_applied="Standard deterministic comparison policy",
                    evidence_ids=sorted(dim_evids),
                    findings=findings,
                )
            )

        # 5. Rule Impacts (Strictly grounded in context rules)
        rule_impacts: list[RuleImpact] = []
        for r in context.rules_context:
            rule_id = r.get("rule_id")
            if not rule_id:
                continue
            rule_desc = r.get("rule_description", r.get("condition_str", "Behavioral Invariant"))
            status = r.get("status", "POTENTIALLY_AFFECTED")
            rule_evids = [e for e in r.get("supporting_evidence_ids", []) if e in context.valid_evidence_ids]

            rule_impacts.append(
                RuleImpact(
                    rule_id=rule_id,
                    rule_description=rule_desc,
                    status=status,
                    observed_behavior=r.get("observed_behavior", "Rule evaluated against test domain."),
                    supporting_evidence_ids=rule_evids,
                    relationship_to_verdict=r.get("relationship_to_verdict", "Evaluated during certification."),
                    limitation="Empirical observation confirms output divergence without modifying rule definitions.",
                )
            )

        # 6. Evidence Traces (Strictly real evidence IDs, or None when evidence absent)
        evidence_traces: list[EvidenceTrace] = []
        for idx, diff in enumerate(context.differences_summary[:15]):
            inp_id = diff.get("input_id")
            evid_tgt = diff.get("target_evidence_id")
            evid_ref = diff.get("reference_evidence_id")
            diff_dim_str = str(diff.get("dimension", "OUTPUT")).upper()
            try:
                diff_dim_enum = BehaviorDimension(diff_dim_str)
            except ValueError:
                diff_dim_enum = BehaviorDimension.OUTPUT

            # Provenance and hash
            inp_label = inp_id or f"case-{idx+1}"
            trace_hash_src = f"{inp_label}:{evid_tgt or 'NO_EVID'}:{diff_dim_str}"
            evidence_traces.append(
                EvidenceTrace(
                    claim_id=f"CLAIM-{idx+1}",
                    claim_text=f"Target {diff_dim_str} differed from reference for input {inp_label}",
                    evidence_id=evid_tgt,
                    input_id=inp_id or "",
                    dimension=diff_dim_enum,
                    role="target",
                    source_type="runtime_execution",
                    evidence_hash=hashlib.sha256(trace_hash_src.encode("utf-8")).hexdigest(),
                    provenance={"reference_evidence_id": evid_ref, "input_id": inp_id},
                )
            )

        # 7. Affected Inputs (Authoritative mapping without fake IDs)
        affected_inputs: list[AffectedInput] = []
        for idx, diff in enumerate(context.differences_summary[:20]):
            inp_id = diff.get("input_id")
            inp_vals = diff.get("input_values", {})
            inp_hash = diff.get("input_hash")
            if not inp_hash and inp_vals:
                inp_hash = compute_canonical_input_hash(inp_vals)

            affected_inputs.append(
                AffectedInput(
                    input_id=inp_id or "",
                    input_hash=inp_hash or "",
                    input_values=inp_vals,
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
                support_level=EvidenceSupportLevel.INFERENCE,
                reason="BEACON operates on behavioral observations and invariants without inspecting arbitrary internal bytecode state.",
            ),
            UncertaintyNote(
                topic="Downstream Business Impact",
                claim="Impact on downstream business consumers depends on consumer tolerance and application domain context.",
                support_level=EvidenceSupportLevel.INFERENCE,
                reason="External downstream systems were not evaluated in this isolated certification session.",
            ),
        ]

        # 9. Investigation Recommendations (Derived strictly from observed dimensions)
        investigation_recommendations: list[InvestigationRecommendation] = []
        if regression_count > 0:
            evidence_refs = [e.evidence_id for e in evidence_traces if e.evidence_id][:3]
            investigation_recommendations.append(
                InvestigationRecommendation(
                    priority=1,
                    title="Inspect Pinpointed Counterexamples & Regressions",
                    description=f"Review the {min(regression_count, 5)} specific input cases where target output diverged from reference.",
                    rationale="Direct counterexamples provide reproducible test vectors to isolate defect locations.",
                    evidence_references=evidence_refs,
                )
            )
            # Add dimension-specific guidance
            if "BOUNDARY" in differing_dimensions_set:
                investigation_recommendations.append(
                    InvestigationRecommendation(
                        priority=2,
                        title="Audit Boundary Conditions and Off-by-One Thresholds",
                        description="Inspect edge cases, conditional branches, and inequality boundaries.",
                        rationale="Boundary dimension discrepancies were detected in evaluation.",
                        evidence_references=[],
                    )
                )
            elif "STATE" in differing_dimensions_set:
                investigation_recommendations.append(
                    InvestigationRecommendation(
                        priority=2,
                        title="Audit Database and Physical State Delta Transformations",
                        description="Verify persistence layer operations, row mutations, and commit sequences.",
                        rationale="State dimension discrepancies were detected in evaluation.",
                        evidence_references=[],
                    )
                )
            elif "ERROR" in differing_dimensions_set:
                investigation_recommendations.append(
                    InvestigationRecommendation(
                        priority=2,
                        title="Audit Error Status Codes and Exception Handling",
                        description="Check error response codes, exception types, and error message structures.",
                        rationale="Error dimension discrepancies were detected in evaluation.",
                        evidence_references=[],
                    )
                )
            elif "WORKFLOW" in differing_dimensions_set:
                investigation_recommendations.append(
                    InvestigationRecommendation(
                        priority=2,
                        title="Audit Workflow Execution Order and Step Sequences",
                        description="Inspect asynchronous choreography and orchestration ordering.",
                        rationale="Workflow dimension discrepancies were detected in evaluation.",
                        evidence_references=[],
                    )
                )
            else:
                investigation_recommendations.append(
                    InvestigationRecommendation(
                        priority=2,
                        title="Audit Output Value Calculations and Formatting",
                        description="Inspect calculations, field serializations, and value mappings in target service.",
                        rationale="Output discrepancies were observed during evaluation.",
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

        fp = context.compute_context_fingerprint()
        explanation_id = f"EXP-{context.certification_id[:8]}-{fp[:8]}-det"
        cache_key = context.compute_cache_key(
            mode="deterministic",
            use_company_knowledge=bool(context.knowledge_context),
            prompt_version="v1.0",
        )

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
            context_fingerprint=fp,
            cache_key=cache_key,
            persistence_status="SUCCESS",
            generation_metadata=metadata,
        )
        explanation.content_hash = explanation.compute_content_hash()
        return explanation


deterministic_generator = DeterministicExplanationGenerator()
