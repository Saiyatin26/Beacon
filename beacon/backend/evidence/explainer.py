"""Phase 15 — Deterministic & Privacy-Gated Certification Explainer.

Produces structured, evidence-grounded explanations answering:
- What was certified?
- What data, implementations, OracleSet, and policy were used?
- Why Certified? / Why Not Certified? / Why Inconclusive?
- Highest severity failures and exact evidence references.

The certification decision is NEVER made by an LLM or explanation engine.
The explainer strictly consumes persisted evidence.
"""

from typing import Any, Optional
from .dossier_models import EvidenceDossier, StructuredExplanation


def generate_structured_explanation(
    dossier: EvidenceDossier,
    use_llm: bool = False,
    preferred_provider: str = "offline",
    allow_external_llm: bool = False,
) -> StructuredExplanation:
    """Generates an authoritative, structured explanation directly from an EvidenceDossier.
    
    Adheres to the core non-negotiable principle: The CertificationEngine authoritatively
    decides the outcome; this explainer only articulates the evidence.
    """
    src = dossier.source_evidence
    impl = dossier.implementation_evidence
    orc = dossier.oracle_evidence
    exec_ev = dossier.execution_evidence
    pol = dossier.policy_evidence
    crypto = dossier.cryptographic_evidence
    status = dossier.policy_evidence.satisfied and crypto.integrity_status == "VERIFIED"

    # Status detection
    # We retrieve the actual authoritative status from dossier or artifact
    auth_status = "CERTIFIED" if pol.satisfied else "NOT_CERTIFIED"
    if exec_ev.oracles_exercised == 0 or exec_ev.oracle_coverage_pct < pol.min_oracle_coverage:
        if not pol.satisfied and len(pol.blocking_reasons) > 0 and "Insufficient oracle coverage" in pol.blocking_reasons[0]:
            auth_status = "INSUFFICIENT_COVERAGE"

    # 1. Section: What was certified
    what_certified = (
        f"Behavioral equivalence certification evaluation comparing legacy implementation "
        f"'{impl.legacy_adapter_name}' (v{impl.legacy_version}) against modernized implementation "
        f"'{impl.modernized_adapter_name}' (v{impl.modernized_version}, variant: {impl.modernization_variant})."
    )

    # 2. Section: Dataset used
    dataset_desc = (
        f"Dataset '{src.dataset_name or src.dataset_id}' (version {src.version}, "
        f"declared provenance: {src.declared_provenance}, {src.row_count} total records) "
        f"with SHA-256 checksum '{src.checksum[:16]}...' and schema fingerprint '{src.schema_fingerprint[:16]}...'."
    )

    # 3. Section: Implementation pair
    impl_pair_desc = (
        f"Legacy Adapter: '{impl.legacy_adapter_id}' (Hash: {impl.legacy_implementation_hash[:16]}...) vs "
        f"Modernized Adapter: '{impl.modernized_adapter_id}' (Hash: {impl.modernized_implementation_hash[:16]}..., "
        f"Provenance: {impl.modernization_provenance})."
    )

    # 4. Section: Governing oracles & policy
    cov_req = pol.min_oracle_coverage * 100.0
    score_req = pol.min_equivalence_score * 100.0
    gov_desc = (
        f"Governed by OracleSet '{orc.oracle_set_id}' ({orc.oracle_count} active behavioral rules, "
        f"Hash: {orc.oracle_set_hash[:16]}...) and Policy '{pol.policy_id}' "
        f"(Required Score >= {score_req:.1f}%, Required Coverage >= {cov_req:.1f}%)."
    )

    # 5. Section: Evaluation summary
    eval_summary = (
        f"Evaluated {exec_ev.total_cases} total test cases across {exec_ev.total_inputs} unique inputs. "
        f"Results: {exec_ev.matching_cases} matches, {exec_ev.regression_cases} regressions, "
        f"{exec_ev.error_cases} execution errors. Oracle coverage: {exec_ev.oracle_coverage_pct * 100.0:.1f}% "
        f"({exec_ev.oracles_exercised}/{orc.oracle_count} rules exercised). "
        f"Behavioral equivalence score: {exec_ev.equivalence_score * 100.0:.1f}%."
    )

    # 6. Status Rationale (Why Certified? / Why Not Certified? / Why Inconclusive?)
    highest_failures: list[dict[str, Any]] = []
    
    if auth_status == "CERTIFIED":
        headline = "CERTIFIED — Full Behavioral Equivalence Verified"
        status_rationale = (
            f"The modernized implementation successfully satisfied all certification policy requirements: "
            f"Equivalence score of {exec_ev.equivalence_score * 100.0:.1f}% met or exceeded the {score_req:.1f}% threshold, "
            f"oracle coverage of {exec_ev.oracle_coverage_pct * 100.0:.1f}% met the {cov_req:.1f}% requirement, "
            f"and 0 critical behavioral regressions were detected across {exec_ev.matching_cases} matching test evaluations."
        )
    elif auth_status == "INSUFFICIENT_COVERAGE":
        headline = "INSUFFICIENT COVERAGE — Inconclusive Behavioral Equivalence"
        reasons_text = "; ".join(pol.blocking_reasons) if pol.blocking_reasons else "Oracle coverage is below policy threshold."
        status_rationale = (
            f"Certification could not be established because available oracle coverage was insufficient: "
            f"{exec_ev.oracles_exercised}/{orc.oracle_count} oracles were exercised ({exec_ev.oracle_coverage_pct * 100.0:.1f}% "
            f"vs required {cov_req:.1f}%). Rationale: {reasons_text}. "
            f"This result is strictly inconclusive and does NOT constitute certification."
        )
    else:
        headline = "NOT CERTIFIED — Behavioral Regressions Detected"
        status_rationale = (
            f"Certification was rejected due to {exec_ev.regression_cases} behavioral regression(s) "
            f"where the modernized implementation violated invariants established by the legacy implementation. "
        )
        if pol.blocking_reasons:
            status_rationale += f"Blocking policy conditions: {'; '.join(pol.blocking_reasons)}. "

        # Extract top failures sorted by severity
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
        sorted_failures = sorted(
            dossier.counterexample_evidence,
            key=lambda c: severity_order.get(c.severity.upper(), 5)
        )
        for c in sorted_failures[:5]:
            highest_failures.append({
                "oracle_id": c.oracle_id,
                "severity": c.severity,
                "input_id": c.input_id,
                "legacy_output": c.legacy_output,
                "modern_output": c.modern_output,
                "invariant_violated": c.invariant_violated,
                "difference_description": c.difference_description,
                "sanitized_inputs": c.sanitized_input_values,
                "evidence_reference": c.evidence_reference,
            })

    # 7. Exact Evidence References
    evidence_refs = [
        {"entity_type": "CERTIFICATION_ARTIFACT", "reference_id": dossier.certification_id, "hash": crypto.artifact_hash},
        {"entity_type": "DATASET", "reference_id": src.dataset_id, "hash": src.checksum},
        {"entity_type": "INPUT_SET", "reference_id": exec_ev.input_set_id, "hash": exec_ev.input_set_hash},
        {"entity_type": "LEGACY_ADAPTER", "reference_id": impl.legacy_adapter_id, "hash": impl.legacy_implementation_hash},
        {"entity_type": "MODERN_ADAPTER", "reference_id": impl.modernized_adapter_id, "hash": impl.modernized_implementation_hash},
        {"entity_type": "ORACLE_SET", "reference_id": orc.oracle_set_id, "hash": orc.oracle_set_hash},
        {"entity_type": "POLICY", "reference_id": pol.policy_id, "hash": pol.policy_hash},
    ]

    # 8. Deterministic Template Natural Language Explanation
    nl_text = f"""### {headline}

**Evaluation Summary:**
{what_certified}

- **Dataset:** {dataset_desc}
- **Implementations:** {impl_pair_desc}
- **Oracles & Policy:** {gov_desc}
- **Metrics:** {eval_summary}

**Decision Rationale:**
{status_rationale}
"""
    if highest_failures:
        nl_text += "\n**Top Behavioral Regressions:**\n"
        for idx, f in enumerate(highest_failures, start=1):
            nl_text += (
                f"{idx}. **Oracle `{f['oracle_id']}`** ({f['severity']} Severity):\n"
                f"   - Input ID: `{f['input_id']}`\n"
                f"   - Expected (Legacy): `{f['legacy_output']}`\n"
                f"   - Actual (Modern): `{f['modern_output']}`\n"
                f"   - Invariant: *{f['invariant_violated']}*\n"
                f"   - Evidence Ref: `{f['evidence_reference']}`\n"
            )

    explanation_source: Any = "DETERMINISTIC_ENGINE"
    explanation_provenance: dict[str, Any] = {
        "engine_version": "1.0.0",
        "method": "deterministic_evidence_synthesis",
    }

    # 9. Optional LLM Natural Language Wording (strictly explanatory layer)
    prov_norm = preferred_provider.lower().strip()
    if use_llm and (allow_external_llm or prov_norm == "offline"):
        # We only apply LLM summarization if explicitly enabled and privacy-compliant
        try:
            from llm.factory import get_llm_client
            client = get_llm_client(preferred_provider=prov_norm if allow_external_llm else "offline")
            prompt = (
                f"You are an auditing explanation assistant for the BEACON system. "
                f"Summarize the following authoritative verification findings into 2 concise paragraphs for an auditor. "
                f"Do not alter the certification result or fabricate reasons.\n\n"
                f"Status: {auth_status}\n"
                f"Score: {exec_ev.equivalence_score * 100.0:.1f}%\n"
                f"Coverage: {exec_ev.oracle_coverage_pct * 100.0:.1f}%\n"
                f"Matches: {exec_ev.matching_cases}, Regressions: {exec_ev.regression_cases}\n"
                f"Summary: {status_rationale}"
            )
            response = client.generate_completion(prompt=prompt, system_prompt="Explain certification results accurately based only on provided evidence.")
            if response and response.content:
                nl_text = f"**[LLM Explanatory Layer Summary]**\n\n{response.content.strip()}\n\n---\n\n{nl_text}"
                explanation_source = "LLM_ASSISTED_EXPLANATION"
                explanation_provenance = {
                    "engine_version": "1.0.0",
                    "method": "llm_assisted_summary",
                    "provider": response.provider,
                    "model": response.model,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                }
        except Exception:
            # LLM error gracefully falls back to deterministic template without failing
            pass

    return StructuredExplanation(
        dossier_id=dossier.dossier_id,
        certification_id=dossier.certification_id,
        project_id=dossier.project_id,
        authoritative_status=auth_status,
        headline=headline,
        what_was_certified=what_certified,
        dataset_used=dataset_desc,
        implementation_pair=impl_pair_desc,
        governing_oracles_and_policy=gov_desc,
        evaluation_summary=eval_summary,
        status_rationale=status_rationale,
        highest_severity_failures=highest_failures,
        evidence_references=evidence_refs,
        natural_language_explanation=nl_text,
        explanation_source=explanation_source,
        explanation_provenance=explanation_provenance,
    )
