"""BEACON V2 — Phase 6 Type & Shape Invariant Candidate Generator.

Discovers stable structural properties, object key shapes, and primitive types across execution outputs.
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


class TypeShapeCandidateGenerator(BaseCandidateGenerator):
    """Discovers stable data types and object key shape invariants."""

    generator_name = "type_shape_generator"
    discovery_method = DiscoveryMethod.TYPE_SHAPE_ANALYSIS

    def generate_candidates(
        self,
        facts: list[ObservationFact],
        policy: DiscoveryPolicy,
        role_scope: str = "reference",
    ) -> list[DiscoveredCandidate]:
        candidates: list[DiscoveredCandidate] = []
        if not facts:
            return candidates

        # 1. Output field type invariants
        output_keys = set()
        for f in facts:
            output_keys.update(f.output_data.keys())

        for ok in sorted(output_keys):
            types_observed = set()
            count = 0
            for f in facts:
                if ok in f.output_data and f.output_data[ok] is not None:
                    val = f.output_data[ok]
                    count += 1
                    if isinstance(val, bool):
                        types_observed.add("boolean")
                    elif isinstance(val, int):
                        types_observed.add("integer")
                    elif isinstance(val, float):
                        types_observed.add("number")
                    elif isinstance(val, str):
                        types_observed.add("string")
                    elif isinstance(val, list):
                        types_observed.add("array")
                    elif isinstance(val, dict):
                        types_observed.add("object")

            if count >= policy.minimum_support_count and len(types_observed) == 1:
                t_name = list(types_observed)[0]
                canonical = f"typeof(output.{ok}) == '{t_name}'"
                cand = DiscoveredCandidate(
                    discovery_id=f"disc_{uuid.uuid4().hex[:10]}",
                    candidate_id=f"cand_type_{ok}_{t_name}",
                    rule_type=DiscoveredRuleType.TYPE_SHAPE_INVARIANT,
                    canonical_expression=canonical,
                    normalized_expression=candidate_normalizer.normalize_expression(canonical),
                    description=f"Output field '{ok}' is consistently of type '{t_name}'",
                    variables=[f"output.{ok}"],
                    source_fields=[f"output.{ok}"],
                    complexity=1,
                    role_scope=role_scope,
                    discovery_method=self.discovery_method,
                    policy_version=policy.policy_version,
                )
                candidates.append(cand)

        # 2. Output key shape consistency
        if facts and all(isinstance(f.output_data, dict) and len(f.output_data) > 0 for f in facts):
            first_keys = sorted(list(facts[0].output_data.keys()))
            if all(sorted(list(f.output_data.keys())) == first_keys for f in facts):
                if len(facts) >= policy.minimum_support_count:
                    keys_str = ", ".join(f"'{k}'" for k in first_keys)
                    canonical = f"keys(output) == [{keys_str}]"
                    cand = DiscoveredCandidate(
                        discovery_id=f"disc_{uuid.uuid4().hex[:10]}",
                        candidate_id="cand_shape_output_keys",
                        rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
                        canonical_expression=canonical,
                        normalized_expression=candidate_normalizer.normalize_expression(canonical),
                        description=f"Output structure consistently contains exact key set [{keys_str}]",
                        variables=[f"output.{k}" for k in first_keys],
                        source_fields=[f"output.{k}" for k in first_keys],
                        complexity=2,
                        role_scope=role_scope,
                        discovery_method=self.discovery_method,
                        policy_version=policy.policy_version,
                    )
                    candidates.append(cand)

        return candidates
