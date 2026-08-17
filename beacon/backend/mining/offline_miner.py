import hashlib
import uuid
from typing import Callable

from common.models import CandidateInvariant, ValidatedInvariant
from evidence.models import UnifiedEvidencePackage
from .base_generator import CandidateGenerator


class OfflineCandidateGenerator(CandidateGenerator):
    """Deterministic local invariant miner for decision rules."""

    def propose_candidates(self, evidence_package: UnifiedEvidencePackage) -> list[CandidateInvariant]:
        candidates: list[CandidateInvariant] = []
        
        # We can extract deterministic candidates by looking for static conditions that have an associated outcome.
        # But we need to link them to evidence IDs.
        for static_item in evidence_package.static_evidence_items:
            if static_item.type == "STATIC_CONDITION":
                # Find outcome in original analysis result
                outcome = None
                if evidence_package.static_analysis:
                    for cond in evidence_package.static_analysis.conditions:
                        if cond.expression == static_item.condition:
                            outcome = cond.outcome
                            break
                
                if outcome:
                    invariant_id = "local-" + hashlib.sha1(static_item.condition.encode()).hexdigest()[:8]
                    candidates.append(CandidateInvariant(
                        invariant_id=invariant_id,
                        condition=static_item.condition,
                        consequence=outcome,
                        severity="critical" if outcome == "REJECT" else "medium",
                        evidence_ids=[static_item.evidence_id],
                        generation_method="offline",
                        timestamp=evidence_package.timestamp,
                        source_lines=[static_item.line] if static_item.line else [],
                        rationale="Deterministic extraction from AST if-branch assignment."
                    ))

        return candidates
