"""BEACON V2 — Phase 6 Nullability & Presence Pattern Generator.

Discovers non-nullness, explicit presence, and empty-state invariants across execution outputs.
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


class NullabilityCandidateGenerator(BaseCandidateGenerator):
    """Discovers field presence, nullability, and non-empty invariants."""

    generator_name = "nullability_generator"
    discovery_method = DiscoveryMethod.STRUCTURAL_INVARIANT

    def generate_candidates(
        self,
        facts: list[ObservationFact],
        policy: DiscoveryPolicy,
        role_scope: str = "reference",
    ) -> list[DiscoveredCandidate]:
        candidates: list[DiscoveredCandidate] = []
        if not facts:
            return candidates

        output_keys = set()
        for f in facts:
            output_keys.update(f.output_data.keys())

        for ok in sorted(output_keys):
            present_facts = [f for f in facts if ok in f.output_data]
            if len(present_facts) >= policy.minimum_support_count and len(present_facts) == len(facts):
                # 1. Field is always present
                canonical_pres = f"exists(output.{ok})"
                candidates.append(
                    DiscoveredCandidate(
                        discovery_id=f"disc_{uuid.uuid4().hex[:10]}",
                        candidate_id=f"cand_exists_{ok}",
                        rule_type=DiscoveredRuleType.NULLABILITY_PATTERN,
                        canonical_expression=canonical_pres,
                        normalized_expression=candidate_normalizer.normalize_expression(canonical_pres),
                        description=f"Output field '{ok}' is consistently present in all observations",
                        variables=[f"output.{ok}"],
                        source_fields=[f"output.{ok}"],
                        complexity=1,
                        role_scope=role_scope,
                        discovery_method=self.discovery_method,
                        policy_version=policy.policy_version,
                    )
                )

                # 2. Field is always non-null
                non_null_facts = [f for f in present_facts if f.output_data[ok] is not None]
                if len(non_null_facts) == len(present_facts) and len(non_null_facts) >= policy.minimum_support_count:
                    canonical_nn = f"output.{ok} != null"
                    candidates.append(
                        DiscoveredCandidate(
                            discovery_id=f"disc_{uuid.uuid4().hex[:10]}",
                            candidate_id=f"cand_notnull_{ok}",
                            rule_type=DiscoveredRuleType.NULLABILITY_PATTERN,
                            canonical_expression=canonical_nn,
                            normalized_expression=candidate_normalizer.normalize_expression(canonical_nn),
                            description=f"Output field '{ok}' is consistently non-null",
                            variables=[f"output.{ok}"],
                            source_fields=[f"output.{ok}"],
                            complexity=1,
                            role_scope=role_scope,
                            discovery_method=self.discovery_method,
                            policy_version=policy.policy_version,
                        )
                    )

        return candidates
