"""BEACON V2 — Phase 6 Error Behavior Candidate Generator.

Discovers deterministic error occurrence, error categorization, and conditional rejection patterns.
"""

from typing import Any

from ..models import (
    DiscoveredCandidate,
    DiscoveredRuleType,
    DiscoveryMethod,
    DiscoveryPolicy,
    ObservationFact,
)
from ..normalizer import candidate_normalizer
from .base import BaseCandidateGenerator


class ErrorBehaviorCandidateGenerator(BaseCandidateGenerator):
    """Discovers error categories, success invariants, and conditional failure rules."""

    generator_name = "error_behavior_generator"
    discovery_method = DiscoveryMethod.ERROR_ANALYSIS

    def generate_candidates(
        self,
        facts: list[ObservationFact],
        policy: DiscoveryPolicy,
        role_scope: str = "reference",
    ) -> list[DiscoveredCandidate]:
        candidates: list[DiscoveredCandidate] = []
        if not facts:
            return candidates

        # 1. Universal Success Invariant (No Error) — requires explicit False observations, not None or missing
        valid_success_facts = [f for f in facts if f.is_valid and f.has_error is False]
        if len(valid_success_facts) == len(facts) and len(valid_success_facts) >= policy.minimum_support_count:
            canonical = "has_error == false"
            candidates.append(
                DiscoveredCandidate(
                    candidate_id="cand_err_no_error",
                    rule_type=DiscoveredRuleType.ERROR_BEHAVIOR,
                    canonical_expression=canonical,
                    normalized_expression=candidate_normalizer.normalize_expression(canonical),
                    description="Execution consistently completes without application or process errors",
                    variables=["error.has_error"],
                    source_fields=["error.has_error"],
                    complexity=1,
                    role_scope=role_scope,
                    discovery_method=self.discovery_method,
                    policy_version=policy.policy_version,
                )
            )

        # 2. Consistent Error Category when error occurs
        error_facts = [f for f in facts if f.is_valid and f.has_error is True]
        if len(error_facts) >= policy.minimum_support_count:
            categories = [f.error_data.get("category") for f in error_facts if "category" in f.error_data]
            if categories and all(c == categories[0] for c in categories):
                cat_val = categories[0]
                canonical = f"error.category == '{cat_val}'"
                candidates.append(
                    DiscoveredCandidate(
                        candidate_id=f"cand_err_cat_{cat_val}",
                        rule_type=DiscoveredRuleType.ERROR_BEHAVIOR,
                        canonical_expression=canonical,
                        normalized_expression=candidate_normalizer.normalize_expression(canonical),
                        description=f"Occurring errors consistently belong to category '{cat_val}'",
                        variables=["error.category"],
                        source_fields=["error.category"],
                        complexity=1,
                        role_scope=role_scope,
                        discovery_method=self.discovery_method,
                        policy_version=policy.policy_version,
                    )
                )

        return candidates
