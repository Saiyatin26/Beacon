"""BEACON V2 — Phase 6 State Invariant & Transition Candidate Generator.

Discovers state persistence invariants and state mutation patterns from verified Phase 3 snapshots.
"""

from typing import Any
import uuid

from ..models import (
    DiscoveredCandidate,
    DiscoveredRuleType,
    DiscoveryMethod,
    DiscoveryPolicy,
    ObservationFact,
)
from ..normalizer import candidate_normalizer
from .base import BaseCandidateGenerator


class StateCandidateGenerator(BaseCandidateGenerator):
    """Discovers state invariance and state mutation hypotheses from Phase 3 state evidence."""

    generator_name = "state_generator"
    discovery_method = DiscoveryMethod.STATE_DELTA_ANALYSIS

    def generate_candidates(
        self,
        facts: list[ObservationFact],
        policy: DiscoveryPolicy,
        role_scope: str = "reference",
    ) -> list[DiscoveredCandidate]:
        candidates: list[DiscoveredCandidate] = []
        if not facts or not policy.enable_state_discovery:
            return candidates

        valid_state_facts = [f for f in facts if f.state_valid]
        if len(valid_state_facts) < policy.minimum_support_count:
            return candidates

        # 1. State Invariant: All valid state observations showed NO mutation
        if all(not f.state_mutated for f in valid_state_facts):
            canonical = "state.mutated == false"
            candidates.append(
                DiscoveredCandidate(
                    discovery_id=f"disc_{uuid.uuid4().hex[:10]}",
                    candidate_id="cand_state_invariant_no_change",
                    rule_type=DiscoveredRuleType.STATE_INVARIANT,
                    canonical_expression=canonical,
                    normalized_expression=candidate_normalizer.normalize_expression(canonical),
                    description="Execution preserves state invariance without database or filesystem mutation",
                    variables=["state.mutated"],
                    source_fields=["state.snapshot_before", "state.snapshot_after"],
                    complexity=1,
                    role_scope=role_scope,
                    discovery_method=self.discovery_method,
                    policy_version=policy.policy_version,
                )
            )

        # 2. State Transition: All valid state observations showed state mutation
        elif all(f.state_mutated for f in valid_state_facts):
            canonical = "state.mutated == true"
            candidates.append(
                DiscoveredCandidate(
                    discovery_id=f"disc_{uuid.uuid4().hex[:10]}",
                    candidate_id="cand_state_transition_mutated",
                    rule_type=DiscoveredRuleType.STATE_TRANSITION,
                    canonical_expression=canonical,
                    normalized_expression=candidate_normalizer.normalize_expression(canonical),
                    description="Execution consistently causes persistent state mutation",
                    variables=["state.mutated"],
                    source_fields=["state.snapshot_before", "state.snapshot_after"],
                    complexity=1,
                    role_scope=role_scope,
                    discovery_method=self.discovery_method,
                    policy_version=policy.policy_version,
                )
            )

        return candidates
