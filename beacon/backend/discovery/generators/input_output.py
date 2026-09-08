"""BEACON V2 — Phase 6 Input -> Output Candidate Generator.

Discovers deterministic mathematical, copy, and constant relationships between input and output fields.
"""

from typing import Any

from ..models import (
    CandidateValidationStatus,
    DiscoveredCandidate,
    DiscoveredRuleType,
    DiscoveryMethod,
    DiscoveryPolicy,
    ObservationFact,
)
from ..normalizer import candidate_normalizer
from .base import BaseCandidateGenerator


class InputOutputCandidateGenerator(BaseCandidateGenerator):
    """Discovers deterministic Input-to-Output mappings and formula relationships."""

    generator_name = "input_output_generator"
    discovery_method = DiscoveryMethod.DIRECT_RELATION

    def generate_candidates(
        self,
        facts: list[ObservationFact],
        policy: DiscoveryPolicy,
        role_scope: str = "reference",
    ) -> list[DiscoveredCandidate]:
        candidates: list[DiscoveredCandidate] = []
        if not facts:
            return candidates

        # 1. Collect all distinct input keys and output keys across facts
        input_keys = set()
        output_keys = set()
        for f in facts:
            input_keys.update(f.input_data.keys())
            output_keys.update(f.output_data.keys())

        # 2. Check for Output == Constant
        for ok in sorted(output_keys):
            values = [f.output_data.get(ok) for f in facts if ok in f.output_data]
            if len(values) >= policy.minimum_support_count:
                first_val = values[0]
                if all(v == first_val for v in values):
                    # Format constant representation
                    val_repr = repr(first_val) if isinstance(first_val, str) else str(first_val)
                    canonical = f"output.{ok} == {val_repr}"
                    cand = DiscoveredCandidate(
                        candidate_id=f"cand_io_const_{ok}",
                        rule_type=DiscoveredRuleType.INPUT_OUTPUT_RELATION,
                        canonical_expression=canonical,
                        normalized_expression=candidate_normalizer.normalize_expression(canonical),
                        description=f"Output field '{ok}' is consistently equal to constant {val_repr}",
                        variables=[f"output.{ok}"],
                        source_fields=[f"output.{ok}"],
                        complexity=1,
                        role_scope=role_scope,
                        discovery_method=self.discovery_method,
                        policy_version=policy.policy_version,
                    )
                    candidates.append(cand)

        # 3. Check for Output.field == Input.field (Direct Copy)
        for ok in sorted(output_keys):
            for ik in sorted(input_keys):
                pairs = [
                    (f.input_data.get(ik), f.output_data.get(ok))
                    for f in facts
                    if ik in f.input_data and ok in f.output_data
                ]
                if len(pairs) >= policy.minimum_support_count:
                    if all(inp_val == out_val for inp_val, out_val in pairs):
                        canonical = f"output.{ok} == input.{ik}"
                        cand = DiscoveredCandidate(
                            candidate_id=f"cand_io_copy_{ok}_{ik}",
                            rule_type=DiscoveredRuleType.INPUT_OUTPUT_RELATION,
                            canonical_expression=canonical,
                            normalized_expression=candidate_normalizer.normalize_expression(canonical),
                            description=f"Output field '{ok}' directly reflects input field '{ik}'",
                            variables=[f"output.{ok}", f"input.{ik}"],
                            source_fields=[f"output.{ok}", f"input.{ik}"],
                            complexity=2,
                            role_scope=role_scope,
                            discovery_method=self.discovery_method,
                            policy_version=policy.policy_version,
                        )
                        candidates.append(cand)

        # 4. Check for Linear Formula Relationship (y = a * x + b) if enabled
        if policy.enable_formula_discovery:
            for ok in sorted(output_keys):
                for ik in sorted(input_keys):
                    numeric_pairs = [
                        (float(f.input_data[ik]), float(f.output_data[ok]))
                        for f in facts
                        if ik in f.input_data
                        and ok in f.output_data
                        and isinstance(f.input_data[ik], (int, float))
                        and isinstance(f.output_data[ok], (int, float))
                        and not isinstance(f.input_data[ik], bool)
                        and not isinstance(f.output_data[ok], bool)
                    ]
                    if len(numeric_pairs) >= max(3, policy.minimum_support_count):
                        # Try to fit linear relation y = a * x + b
                        # Check distinct x values
                        distinct_x = len(set(x for x, y in numeric_pairs))
                        if distinct_x >= 2:
                            x0, y0 = numeric_pairs[0]
                            x1, y1 = numeric_pairs[1]
                            dx = x1 - x0
                            if abs(dx) > policy.numeric_tolerance:
                                a = (y1 - y0) / dx
                                b = y0 - a * x0
                                # Check if all pairs satisfy y == a*x + b within tolerance
                                fits_all = all(
                                    abs(y - (a * x + b)) < policy.numeric_tolerance
                                    for x, y in numeric_pairs
                                )
                                if fits_all and (abs(a - 1.0) > policy.numeric_tolerance or abs(b) > policy.numeric_tolerance):
                                    # Format canonical formula
                                    a_str = f"{int(a)}" if a.is_integer() else f"{a:.4f}"
                                    b_str = f"{int(b)}" if b.is_integer() else f"{b:.4f}"

                                    if abs(b) < policy.numeric_tolerance:
                                        canonical = f"output.{ok} == {a_str} * input.{ik}"
                                    elif b > 0:
                                        canonical = f"output.{ok} == {a_str} * input.{ik} + {b_str}"
                                    else:
                                        canonical = f"output.{ok} == {a_str} * input.{ik} - {abs(float(b_str))}"

                                    cand = DiscoveredCandidate(
                                        candidate_id=f"cand_io_formula_{ok}_{ik}",
                                        rule_type=DiscoveredRuleType.INPUT_OUTPUT_RELATION,
                                        canonical_expression=canonical,
                                        normalized_expression=candidate_normalizer.normalize_expression(canonical),
                                        description=f"Output field '{ok}' satisfies linear relation with input field '{ik}': {canonical}",
                                        variables=[f"output.{ok}", f"input.{ik}"],
                                        source_fields=[f"output.{ok}", f"input.{ik}"],
                                        complexity=3,
                                        role_scope=role_scope,
                                        discovery_method=self.discovery_method,
                                        policy_version=policy.policy_version,
                                    )
                                    candidates.append(cand)

        return candidates
