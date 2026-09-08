"""BEACON V2 — Phase 6 Cross-Input Invariant Candidate Generator.

Discovers behavioral invariants that hold consistently across independent, diverse input observations.
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


class CrossInputCandidateGenerator(BaseCandidateGenerator):
    """Discovers cross-input behavioral stability, input-variation invariants, and response consistency."""

    generator_name = "cross_input_generator"
    discovery_method = DiscoveryMethod.CROSS_INPUT_ANALYSIS

    def generate_candidates(
        self,
        facts: list[ObservationFact],
        policy: DiscoveryPolicy,
        role_scope: str = "reference",
    ) -> list[DiscoveredCandidate]:
        candidates: list[DiscoveredCandidate] = []
        if not facts:
            return candidates

        valid_facts = [f for f in facts if f.is_valid and f.output_observed]
        if len(valid_facts) < policy.minimum_support_count:
            return candidates

        # Check unique input diversity
        unique_input_ids = {f.input_id for f in valid_facts}
        if len(unique_input_ids) < 2:
            # Need at least 2 independent input observations for genuine cross-input analysis
            return candidates

        # 1. Cross-Input Output Shape Stability across diverse inputs
        out_key_sets = [sorted(list(f.output_data.keys())) for f in valid_facts if f.output_data]
        if out_key_sets and len(out_key_sets) >= policy.minimum_support_count:
            first_keys = out_key_sets[0]
            if first_keys and all(ks == first_keys for ks in out_key_sets):
                canonical = f"cross_input_invariant(keys(output) == {first_keys})"
                candidates.append(
                    DiscoveredCandidate(
                        discovery_id=f"disc_{uuid.uuid4().hex[:10]}",
                        candidate_id="cand_cross_input_shape_stability",
                        rule_type=DiscoveredRuleType.CROSS_INPUT_INVARIANT,
                        canonical_expression=canonical,
                        normalized_expression=candidate_normalizer.normalize_expression(canonical),
                        description=f"Output key shape remains invariant across {len(unique_input_ids)} independent inputs: {first_keys}",
                        variables=["output.keys"],
                        source_fields=["output.keys"],
                        complexity=1,
                        role_scope=role_scope,
                        discovery_method=self.discovery_method,
                        policy_version=policy.policy_version,
                        provenance={"unique_inputs_count": len(unique_input_ids)},
                    )
                )

        # 2. Cross-Input Input -> Output Functional Consistency
        # Collect all numeric input keys with varying values
        numeric_input_keys = set()
        numeric_output_keys = set()
        for f in valid_facts:
            for k, v in f.input_data.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    numeric_input_keys.add(k)
            for k, v in f.output_data.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    numeric_output_keys.add(k)

        for ik in sorted(numeric_input_keys):
            for ok in sorted(numeric_output_keys):
                # Filter facts with both keys
                io_facts = [
                    f for f in valid_facts
                    if ik in f.input_data and ok in f.output_data
                    and isinstance(f.input_data[ik], (int, float)) and not isinstance(f.input_data[ik], bool)
                    and isinstance(f.output_data[ok], (int, float)) and not isinstance(f.output_data[ok], bool)
                ]
                if len(io_facts) < max(2, policy.minimum_support_count):
                    continue

                unique_in_vals = {f.input_data[ik] for f in io_facts}
                if len(unique_in_vals) < 2:
                    # Input did not vary
                    continue

                # Check if monotonic non-decreasing across varying inputs
                sorted_io = sorted(io_facts, key=lambda f: float(f.input_data[ik]))
                is_monotonic_inc = all(
                    float(sorted_io[i].output_data[ok]) <= float(sorted_io[i + 1].output_data[ok]) + policy.numeric_tolerance
                    for i in range(len(sorted_io) - 1)
                )
                if is_monotonic_inc and len(sorted_io) >= policy.minimum_support_count:
                    canonical = f"monotonic_non_decreasing(input.{ik} -> output.{ok})"
                    candidates.append(
                        DiscoveredCandidate(
                            discovery_id=f"disc_{uuid.uuid4().hex[:10]}",
                            candidate_id=f"cand_cross_input_mono_{ik}_{ok}",
                            rule_type=DiscoveredRuleType.CROSS_INPUT_INVARIANT,
                            canonical_expression=canonical,
                            normalized_expression=candidate_normalizer.normalize_expression(canonical),
                            description=f"Output field '{ok}' responds monotonically to changes in input field '{ik}' across {len(unique_in_vals)} distinct values",
                            variables=[f"input.{ik}", f"output.{ok}"],
                            source_fields=[f"input.{ik}", f"output.{ok}"],
                            complexity=2,
                            role_scope=role_scope,
                            discovery_method=self.discovery_method,
                            policy_version=policy.policy_version,
                            provenance={"distinct_input_values": len(unique_in_vals)},
                        )
                    )

        return candidates
