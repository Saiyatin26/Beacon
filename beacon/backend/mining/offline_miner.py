import hashlib
from typing import Optional

from common.models import CandidateInvariant
from evidence.models import UnifiedEvidencePackage
from .base_generator import CandidateGenerator
from .normalizer import normalize_condition


class OfflineCandidateGenerator(CandidateGenerator):
    """Deterministic local invariant miner extracting candidates directly from UnifiedEvidencePackage."""

    def propose_candidates(self, evidence_package: UnifiedEvidencePackage) -> list[CandidateInvariant]:
        candidates: list[CandidateInvariant] = []
        
        # Build lookup for correlated conditions using normalized expressions
        corr_by_norm = {
            normalize_condition(c.condition_expr): c
            for c in evidence_package.correlated_conditions
        }

        for static_item in evidence_package.static_evidence_items:
            if static_item.type == "STATIC_CONDITION" and static_item.condition:
                norm_cond = normalize_condition(static_item.condition)

                # Find outcome in static analysis result or correlated dynamic outcomes
                outcome: Optional[str] = None
                if evidence_package.static_analysis:
                    for cond in evidence_package.static_analysis.conditions:
                        if normalize_condition(cond.expression) == norm_cond:
                            outcome = cond.outcome
                            break

                # If static analysis didn't determine outcome, infer from observed correlated outcomes
                corr = corr_by_norm.get(norm_cond)
                if not outcome and corr and corr.observed_outcomes:
                    outcome = max(corr.observed_outcomes.items(), key=lambda x: x[1])[0]

                if outcome:
                    invariant_id = "local-" + hashlib.sha1(norm_cond.encode()).hexdigest()[:8]
                    
                    evidence_ids = [static_item.evidence_id]
                    execution_ids: list[str] = []
                    if corr:
                        dyn_ids = [d.evidence_id for d in corr.dynamic_items]
                        evidence_ids.extend(dyn_ids[:20])
                        execution_ids.extend(corr.execution_ids[:20])

                    reproducibility = {
                        "generator_type": "offline",
                        "package_id": evidence_package.package_id,
                        "source_file": evidence_package.source_file,
                    }

                    candidates.append(CandidateInvariant(
                        invariant_id=invariant_id,
                        condition=norm_cond,
                        raw_condition=static_item.condition,
                        consequence=outcome,
                        source_file=evidence_package.source_file,
                        source_lines=[static_item.line] if static_item.line else [],
                        severity="critical" if outcome.upper() in ("REJECT", "ERROR", "FAIL") else "medium",
                        evidence_ids=list(dict.fromkeys(evidence_ids)),
                        execution_ids=list(dict.fromkeys(execution_ids)),
                        generation_method="offline",
                        timestamp=evidence_package.timestamp,
                        rationale="Deterministic extraction from AST condition and correlated runtime evidence.",
                        reproducibility=reproducibility,
                    ))

        return candidates
