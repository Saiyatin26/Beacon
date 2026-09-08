"""BEACON V2 — Phase 6 Candidate Deduplication & Ranking.

Provides deterministic candidate deduplication, canonical sorting, and bounded ranking.
"""

from typing import Any
from .models import DiscoveredCandidate, DiscoveryPolicy


class CandidateRanker:
    """Deduplicates and deterministically ranks candidate rules and invariants."""

    def deduplicate_and_rank(
        self,
        candidates: list[DiscoveredCandidate],
        policy: DiscoveryPolicy,
    ) -> list[DiscoveredCandidate]:
        """Deduplicates candidates by canonical fingerprint and sorts them deterministically.

        Args:
            candidates: Raw generated and validated candidates.
            policy: Discovery policy specifying maximum_candidates and minimum thresholds.

        Returns:
            Deduplicated, ranked, and bounded list of DiscoveredCandidates.
        """
        # 1. Deduplicate by canonical fingerprint
        dedup_map: dict[str, DiscoveredCandidate] = {}

        for c in candidates:
            fp = c.fingerprint
            if fp not in dedup_map:
                dedup_map[fp] = c
            else:
                # Merge evidence IDs and input IDs
                existing = dedup_map[fp]
                combined_eids = sorted(list(set(existing.evidence_ids) | set(c.evidence_ids)))
                combined_iids = sorted(list(set(existing.input_ids) | set(c.input_ids)))
                existing.evidence_ids = combined_eids
                existing.input_ids = combined_iids
                # Retain highest support and confidence
                if c.support_count > existing.support_count:
                    existing.support_count = c.support_count
                    existing.support_ratio = c.support_ratio
                if c.confidence > existing.confidence:
                    existing.confidence = c.confidence
                    existing.validation_status = c.validation_status

        unique_candidates = list(dedup_map.values())

        # 2. Deterministic Ranking Key:
        # - Validation status priority (VALIDATED > WEAK > INSUFFICIENT_COVERAGE > CONTRADICTED > INCONCLUSIVE)
        # - Confidence (descending)
        # - Support count (descending)
        # - Complexity (ascending: prefer simpler)
        # - Contradiction count (ascending: fewer contradictions)
        # - Canonical expression (alphabetical tie-breaker)
        status_priority = {
            "VALIDATED": 5,
            "WEAK": 4,
            "INSUFFICIENT_COVERAGE": 3,
            "CONTRADICTED": 2,
            "INCONCLUSIVE": 1,
            "CANDIDATE": 0,
        }

        def ranking_key(cand: DiscoveredCandidate):
            st_val = cand.validation_status.value if hasattr(cand.validation_status, "value") else str(cand.validation_status)
            return (
                -status_priority.get(st_val, 0),
                -round(cand.confidence, 4),
                -cand.support_count,
                cand.complexity,
                cand.contradiction_count,
                cand.canonical_expression,
            )

        unique_candidates.sort(key=ranking_key)

        # 3. Bounded pruning by maximum_candidates
        return unique_candidates[: policy.maximum_candidates]


candidate_ranker = CandidateRanker()
