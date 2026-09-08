"""BEACON V2 — Phase 6 Boundary Behavior Candidate Generator.

Discovers empirical transition points and piecewise behavioral shifts across numeric input distributions.
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


class BoundaryCandidateGenerator(BaseCandidateGenerator):
    """Discovers empirical behavioral boundary transition points across numeric inputs."""

    generator_name = "boundary_generator"
    discovery_method = DiscoveryMethod.BOUNDARY_ANALYSIS

    def generate_candidates(
        self,
        facts: list[ObservationFact],
        policy: DiscoveryPolicy,
        role_scope: str = "reference",
    ) -> list[DiscoveredCandidate]:
        candidates: list[DiscoveredCandidate] = []
        if not facts or not policy.enable_boundary_discovery:
            return candidates

        # Find all numeric input fields
        numeric_input_keys = set()
        for f in facts:
            for k, v in f.input_data.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    numeric_input_keys.add(k)

        for ik in sorted(numeric_input_keys):
            # Sort facts by this input key
            sorted_facts = [
                f for f in facts
                if ik in f.input_data and isinstance(f.input_data[ik], (int, float)) and not isinstance(f.input_data[ik], bool)
            ]
            sorted_facts.sort(key=lambda f: float(f.input_data[ik]))

            if len(sorted_facts) < max(4, policy.minimum_support_count * 2):
                continue

            # Check for transition in has_error (e.g. error below T, success above T)
            error_states = [f.has_error for f in sorted_facts]
            if True in error_states and False in error_states:
                # Look for a clean single transition point
                for idx in range(1, len(sorted_facts)):
                    left_errs = set(error_states[:idx])
                    right_errs = set(error_states[idx:])
                    if len(left_errs) == 1 and len(right_errs) == 1 and left_errs != right_errs:
                        t_val = sorted_facts[idx].input_data[ik]
                        t_val_str = str(t_val)
                        canonical = f"transition(input.{ik} >= {t_val_str}) -> has_error == {str(list(right_errs)[0]).lower()}"
                        candidates.append(
                            DiscoveredCandidate(
                                discovery_id=f"disc_{uuid.uuid4().hex[:10]}",
                                candidate_id=f"cand_bound_err_{ik}_{t_val_str}",
                                rule_type=DiscoveredRuleType.BOUNDARY_BEHAVIOR,
                                canonical_expression=canonical,
                                normalized_expression=candidate_normalizer.normalize_expression(canonical),
                                description=f"Observed behavioral error transition point near input.{ik} == {t_val_str}",
                                variables=[f"input.{ik}", "error.has_error"],
                                source_fields=[f"input.{ik}", "error.has_error"],
                                complexity=2,
                                role_scope=role_scope,
                                discovery_method=self.discovery_method,
                                policy_version=policy.policy_version,
                            )
                        )
                        break

        return candidates
