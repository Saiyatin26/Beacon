"""BEACON V2 — Phase 6 Relational Invariant Candidate Generator.

Discovers mathematical and relational ordering invariants (<=, >=, subset) between observable fields.
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


class RelationalCandidateGenerator(BaseCandidateGenerator):
    """Discovers inequalities (<=, >=) and relational ordering invariants."""

    generator_name = "relational_generator"
    discovery_method = DiscoveryMethod.RELATIONAL_ANALYSIS

    def generate_candidates(
        self,
        facts: list[ObservationFact],
        policy: DiscoveryPolicy,
        role_scope: str = "reference",
    ) -> list[DiscoveredCandidate]:
        candidates: list[DiscoveredCandidate] = []
        if not facts:
            return candidates

        # Gather numeric fields across input and output
        numeric_fields: dict[str, list[tuple[str, float]]] = {}  # field_name -> [(input_id, val)]

        for f in facts:
            for ik, iv in f.input_data.items():
                if isinstance(iv, (int, float)) and not isinstance(iv, bool):
                    fname = f"input.{ik}"
                    numeric_fields.setdefault(fname, []).append((f.input_id, float(iv)))
            for ok, ov in f.output_data.items():
                if isinstance(ov, (int, float)) and not isinstance(ov, bool):
                    fname = f"output.{ok}"
                    numeric_fields.setdefault(fname, []).append((f.input_id, float(ov)))

        field_names = sorted(list(numeric_fields.keys()))

        # Check all pairs of fields
        for i in range(len(field_names)):
            for j in range(i + 1, len(field_names)):
                f1 = field_names[i]
                f2 = field_names[j]

                # Map input_id -> val
                m1 = dict(numeric_fields[f1])
                m2 = dict(numeric_fields[f2])
                common_ids = set(m1.keys()) & set(m2.keys())

                if len(common_ids) >= policy.minimum_support_count:
                    pairs = [(m1[cid], m2[cid]) for cid in common_ids]
                    # Check strictly f1 <= f2 or f2 <= f1 (avoid trivial f1 == f2 covered by IO generator)
                    all_le = all(v1 <= v2 + policy.numeric_tolerance for v1, v2 in pairs)
                    all_ge = all(v1 >= v2 - policy.numeric_tolerance for v1, v2 in pairs)
                    all_eq = all(abs(v1 - v2) < policy.numeric_tolerance for v1, v2 in pairs)

                    if not all_eq:
                        if all_le:
                            canonical = f"{f1} <= {f2}"
                            candidates.append(
                                DiscoveredCandidate(
                                    candidate_id=f"cand_rel_le_{f1}_{f2}",
                                    rule_type=DiscoveredRuleType.RELATIONAL_INVARIANT,
                                    canonical_expression=canonical,
                                    normalized_expression=candidate_normalizer.normalize_expression(canonical),
                                    description=f"Field '{f1}' is consistently less than or equal to '{f2}'",
                                    variables=[f1, f2],
                                    source_fields=[f1, f2],
                                    complexity=2,
                                    role_scope=role_scope,
                                    discovery_method=self.discovery_method,
                                    policy_version=policy.policy_version,
                                )
                            )
                        elif all_ge:
                            canonical = f"{f1} >= {f2}"
                            candidates.append(
                                DiscoveredCandidate(
                                    candidate_id=f"cand_rel_ge_{f1}_{f2}",
                                    rule_type=DiscoveredRuleType.RELATIONAL_INVARIANT,
                                    canonical_expression=canonical,
                                    normalized_expression=candidate_normalizer.normalize_expression(canonical),
                                    description=f"Field '{f1}' is consistently greater than or equal to '{f2}'",
                                    variables=[f1, f2],
                                    source_fields=[f1, f2],
                                    complexity=2,
                                    role_scope=role_scope,
                                    discovery_method=self.discovery_method,
                                    policy_version=policy.policy_version,
                                )
                            )

        return candidates
