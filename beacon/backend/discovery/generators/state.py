"""BEACON V2 — Phase 6 State Invariant & Transition Candidate Generator.

Discovers state persistence invariants, entity count delta transitions, and relational state properties
from verified Phase 3 snapshots.
"""

from typing import Any, Optional
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
    """Discovers state invariance, entity delta transitions, and relational state properties from Phase 3 state evidence."""

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

        valid_state_facts = [f for f in facts if f.is_valid and f.state_valid and f.state_before is not None and f.state_after is not None]
        if len(valid_state_facts) < policy.minimum_support_count:
            return candidates

        # 1. State Invariant: Overall mutation status
        if all(f.state_mutated is False for f in valid_state_facts):
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
        elif all(f.state_mutated is True for f in valid_state_facts):
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

        # 2. Entity / Table Row Count Deltas and Invariants
        # Collect table or collection names present across before and after states
        table_keys = set()
        for f in valid_state_facts:
            table_keys.update(f.state_before.keys())
            table_keys.update(f.state_after.keys())

        for tbl in sorted(table_keys):
            deltas: list[int] = []
            all_valid_counts = True

            for f in valid_state_facts:
                c_before = self._extract_count(f.state_before.get(tbl))
                c_after = self._extract_count(f.state_after.get(tbl))
                if c_before is None or c_after is None:
                    all_valid_counts = False
                    break
                deltas.append(c_after - c_before)

            if all_valid_counts and len(deltas) >= policy.minimum_support_count:
                # Check if delta is consistent across all observations
                first_delta = deltas[0]
                if all(d == first_delta for d in deltas):
                    if first_delta == 0:
                        canonical = f"state_after.{tbl}.row_count == state_before.{tbl}.row_count"
                        rule_type = DiscoveredRuleType.STATE_INVARIANT
                        desc = f"Entity/table '{tbl}' row count is invariant across execution"
                    elif first_delta > 0:
                        canonical = f"state_after.{tbl}.row_count == state_before.{tbl}.row_count + {first_delta}"
                        rule_type = DiscoveredRuleType.STATE_TRANSITION
                        desc = f"Entity/table '{tbl}' row count increases deterministically by {first_delta}"
                    else:
                        canonical = f"state_after.{tbl}.row_count == state_before.{tbl}.row_count - {abs(first_delta)}"
                        rule_type = DiscoveredRuleType.STATE_TRANSITION
                        desc = f"Entity/table '{tbl}' row count decreases deterministically by {abs(first_delta)}"

                    candidates.append(
                        DiscoveredCandidate(
                            discovery_id=f"disc_{uuid.uuid4().hex[:10]}",
                            candidate_id=f"cand_state_count_{tbl}_{first_delta}",
                            rule_type=rule_type,
                            canonical_expression=canonical,
                            normalized_expression=candidate_normalizer.normalize_expression(canonical),
                            description=desc,
                            variables=[f"state_after.{tbl}.row_count", f"state_before.{tbl}.row_count"],
                            source_fields=[f"state_after.{tbl}", f"state_before.{tbl}"],
                            complexity=2 if first_delta != 0 else 1,
                            role_scope=role_scope,
                            discovery_method=self.discovery_method,
                            policy_version=policy.policy_version,
                        )
                    )

        # 3. Scalar Field State Invariants (e.g. for key-value state snapshots)
        scalar_keys = set()
        for f in valid_state_facts:
            for k, v in f.state_before.items():
                if isinstance(v, (int, float, str, bool)):
                    scalar_keys.add(k)

        for sk in sorted(scalar_keys):
            field_deltas: list[float] = []
            all_scalars_present = True

            for f in valid_state_facts:
                v_before = f.state_before.get(sk)
                v_after = f.state_after.get(sk)
                if v_before is None or v_after is None:
                    all_scalars_present = False
                    break
                if isinstance(v_before, (int, float)) and isinstance(v_after, (int, float)) and not isinstance(v_before, bool) and not isinstance(v_after, bool):
                    field_deltas.append(float(v_after) - float(v_before))
                elif v_before == v_after:
                    field_deltas.append(0.0)
                else:
                    all_scalars_present = False
                    break

            if all_scalars_present and len(field_deltas) >= policy.minimum_support_count:
                first_d = field_deltas[0]
                if all(abs(d - first_d) < policy.numeric_tolerance for d in field_deltas):
                    if abs(first_d) < policy.numeric_tolerance:
                        canonical = f"state_after.{sk} == state_before.{sk}"
                        rule_type = DiscoveredRuleType.STATE_INVARIANT
                        desc = f"State attribute '{sk}' remains invariant across execution"
                    elif first_d > 0:
                        canonical = f"state_after.{sk} == state_before.{sk} + {int(first_d) if first_d.is_integer() else first_d}"
                        rule_type = DiscoveredRuleType.STATE_TRANSITION
                        desc = f"State attribute '{sk}' transitions by +{first_d}"
                    else:
                        canonical = f"state_after.{sk} == state_before.{sk} - {int(abs(first_d)) if abs(first_d).is_integer() else abs(first_d)}"
                        rule_type = DiscoveredRuleType.STATE_TRANSITION
                        desc = f"State attribute '{sk}' transitions by -{abs(first_d)}"

                    candidates.append(
                        DiscoveredCandidate(
                            discovery_id=f"disc_{uuid.uuid4().hex[:10]}",
                            candidate_id=f"cand_state_field_{sk}_{int(first_d) if isinstance(first_d, float) and first_d.is_integer() else first_d}",
                            rule_type=rule_type,
                            canonical_expression=canonical,
                            normalized_expression=candidate_normalizer.normalize_expression(canonical),
                            description=desc,
                            variables=[f"state_after.{sk}", f"state_before.{sk}"],
                            source_fields=[f"state_after.{sk}", f"state_before.{sk}"],
                            complexity=2 if abs(first_d) >= policy.numeric_tolerance else 1,
                            role_scope=role_scope,
                            discovery_method=self.discovery_method,
                            policy_version=policy.policy_version,
                        )
                    )

        return candidates

    def _extract_count(self, tbl_val: Any) -> Optional[int]:
        """Extracts integer row/entity count from table snapshot structure or integer."""
        if isinstance(tbl_val, int) and not isinstance(tbl_val, bool):
            return tbl_val
        if isinstance(tbl_val, dict):
            rc = tbl_val.get("row_count")
            if isinstance(rc, int) and not isinstance(rc, bool):
                return rc
            rows = tbl_val.get("rows")
            if isinstance(rows, list):
                return len(rows)
        return None
