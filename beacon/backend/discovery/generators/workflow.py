"""BEACON V2 — Phase 6 Workflow Sequence Candidate Generator.

Discovers event orderings, predecessor/successor relationships, and sequence patterns from trace evidence.
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


class WorkflowCandidateGenerator(BaseCandidateGenerator):
    """Discovers workflow sequences and step ordering invariants from trace events."""

    generator_name = "workflow_generator"
    discovery_method = DiscoveryMethod.SEQUENCE_MINING

    def generate_candidates(
        self,
        facts: list[ObservationFact],
        policy: DiscoveryPolicy,
        role_scope: str = "reference",
    ) -> list[DiscoveredCandidate]:
        candidates: list[DiscoveredCandidate] = []
        if not facts or not policy.enable_sequence_discovery:
            return candidates

        trace_facts = [f for f in facts if f.workflow_events]
        if len(trace_facts) < policy.minimum_support_count:
            return candidates

        # 1. Check for Predecessor / Successor relationships
        # Collect all unique event types
        all_event_types = set()
        for f in trace_facts:
            all_event_types.update(f.workflow_events)

        event_list = sorted(list(all_event_types))

        for i in range(len(event_list)):
            for j in range(len(event_list)):
                if i == j:
                    continue
                ev_a = event_list[i]
                ev_b = event_list[j]

                # Check if ev_a precedes ev_b across all traces where both appear
                co_occurring = [f for f in trace_facts if ev_a in f.workflow_events and ev_b in f.workflow_events]
                if len(co_occurring) >= policy.minimum_support_count:
                    all_precedes = all(
                        f.workflow_events.index(ev_a) < f.workflow_events.index(ev_b)
                        for f in co_occurring
                    )
                    if all_precedes:
                        canonical = f"workflow.event('{ev_a}') precedes workflow.event('{ev_b}')"
                        candidates.append(
                            DiscoveredCandidate(
                                discovery_id=f"disc_{uuid.uuid4().hex[:10]}",
                                candidate_id=f"cand_wf_prec_{ev_a}_{ev_b}",
                                rule_type=DiscoveredRuleType.WORKFLOW_INVARIANT,
                                canonical_expression=canonical,
                                normalized_expression=candidate_normalizer.normalize_expression(canonical),
                                description=f"Lifecycle event '{ev_a}' consistently precedes '{ev_b}'",
                                variables=[f"workflow.event('{ev_a}')", f"workflow.event('{ev_b}')"],
                                source_fields=["workflow.events"],
                                complexity=2,
                                role_scope=role_scope,
                                discovery_method=self.discovery_method,
                                policy_version=policy.policy_version,
                            )
                        )

        # 2. Check for exact repeated sequence across all traces
        if len(trace_facts) >= policy.minimum_support_count:
            first_seq = trace_facts[0].workflow_events
            if all(f.workflow_events == first_seq for f in trace_facts):
                seq_str = " -> ".join(first_seq)
                canonical = f"workflow.sequence == [{seq_str}]"
                candidates.append(
                    DiscoveredCandidate(
                        discovery_id=f"disc_{uuid.uuid4().hex[:10]}",
                        candidate_id="cand_wf_exact_seq",
                        rule_type=DiscoveredRuleType.WORKFLOW_INVARIANT,
                        canonical_expression=canonical,
                        normalized_expression=candidate_normalizer.normalize_expression(canonical),
                        description=f"Execution trace consistently follows exact event sequence: {seq_str}",
                        variables=["workflow.sequence"],
                        source_fields=["workflow.events"],
                        complexity=len(first_seq),
                        role_scope=role_scope,
                        discovery_method=self.discovery_method,
                        policy_version=policy.policy_version,
                    )
                )

        return candidates
