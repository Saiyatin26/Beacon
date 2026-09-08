"""BEACON V2 — Phase 6 Candidate Validator.

Empirically evaluates candidate rule hypotheses against the ObservationMatrix, computing deterministic
support counts, contradiction counts, unknown counts, support ratios, and confidence scores.
"""

import re
from typing import Any, Optional

from .models import (
    CandidateValidationStatus,
    DiscoveredCandidate,
    DiscoveredRuleType,
    DiscoveryPolicy,
    ObservationFact,
)


class CandidateValidator:
    """Validates candidate hypotheses against observations, distinguishing support, contradiction, and unknown."""

    def validate_candidate(
        self,
        candidate: DiscoveredCandidate,
        facts: list[ObservationFact],
        policy: DiscoveryPolicy,
    ) -> DiscoveredCandidate:
        """Evaluates a candidate against all facts in scope, mutating and returning its empirical statistics."""
        support_count = 0
        contradiction_count = 0
        unknown_count = 0
        supporting_inputs = set()
        supporting_evidence_ids = set()

        expr = candidate.canonical_expression
        rule_type = candidate.rule_type

        for fact in facts:
            # Check if fact is valid / not an adaptation failure
            if not fact.is_valid:
                unknown_count += 1
                continue

            # Evaluate fact against candidate expression
            eval_res = self._evaluate_fact(candidate, fact, policy)

            if eval_res is True:
                support_count += 1
                supporting_inputs.add(fact.input_id)
                supporting_evidence_ids.update(fact.evidence_ids)
            elif eval_res is False:
                contradiction_count += 1
            elif eval_res is None:
                # Inconclusive / unknown / not applicable
                unknown_count += 1

        total_obs = len(facts)
        applicable_count = support_count + contradiction_count
        support_ratio = (support_count / total_obs) if total_obs > 0 else 0.0
        confidence = (support_count / applicable_count) if applicable_count > 0 else 0.0

        # Determine validation status
        if applicable_count == 0:
            status = CandidateValidationStatus.INCONCLUSIVE
        elif contradiction_count > 0:
            status = CandidateValidationStatus.CONTRADICTED if confidence < 0.5 else CandidateValidationStatus.WEAK
        elif support_count >= policy.minimum_support_count and confidence >= policy.minimum_confidence:
            status = CandidateValidationStatus.VALIDATED
        else:
            status = CandidateValidationStatus.INSUFFICIENT_COVERAGE

        candidate.support_count = support_count
        candidate.contradiction_count = contradiction_count
        candidate.unknown_count = unknown_count
        candidate.applicable_count = applicable_count
        candidate.observation_count = total_obs
        candidate.support_ratio = round(support_ratio, 4)
        candidate.confidence = round(confidence, 4)
        candidate.validation_status = status
        candidate.input_ids = sorted(list(supporting_inputs))
        candidate.evidence_ids = sorted(list(supporting_evidence_ids))

        return candidate

    def _evaluate_fact(
        self,
        candidate: DiscoveredCandidate,
        fact: ObservationFact,
        policy: DiscoveryPolicy,
    ) -> Optional[bool]:
        """Evaluates whether a single fact supports (True), contradicts (False), or is unknown/not applicable (None)."""
        expr = candidate.canonical_expression

        # 1. Output Formula: output.y == a * input.x (+/- b)
        m_form = re.match(r"^output\.([a-zA-Z0-9_]+)\s*==\s*([0-9\.\-]+)\s*\*\s*input\.([a-zA-Z0-9_]+)(?:\s*([\+\-])\s*([0-9\.\-]+))?$", expr)
        if m_form:
            of = m_form.group(1)
            a = float(m_form.group(2))
            if_ = m_form.group(3)
            sign = m_form.group(4)
            b = float(m_form.group(5)) if m_form.group(5) else 0.0
            if sign == "-":
                b = -b

            if of not in fact.output_data or if_ not in fact.input_data:
                return None
            ov = fact.output_data[of]
            iv = fact.input_data[if_]
            if not isinstance(ov, (int, float)) or not isinstance(iv, (int, float)) or isinstance(ov, bool) or isinstance(iv, bool):
                return False
            expected = a * float(iv) + b
            return abs(float(ov) - expected) < policy.numeric_tolerance

        # 2. Output Copy: output.x == input.y
        m_copy = re.match(r"^output\.([a-zA-Z0-9_]+)\s*==\s*input\.([a-zA-Z0-9_]+)$", expr)
        if m_copy:
            of = m_copy.group(1)
            if_ = m_copy.group(2)
            if of not in fact.output_data or if_ not in fact.input_data:
                return None
            return fact.output_data[of] == fact.input_data[if_]

        # 3. Output Constant: output.x == val
        m_const = re.match(r"^output\.([a-zA-Z0-9_]+)\s*==\s*(.+)$", expr)
        if m_const:
            field = m_const.group(1)
            raw_target = m_const.group(2).strip()
            if field not in fact.output_data:
                return None
            actual_val = fact.output_data[field]
            target_val = self._parse_literal(raw_target)
            return actual_val == target_val

        # 4. Type Invariant: typeof(output.x) == 'int'
        m_type = re.match(r"^typeof\(output\.([a-zA-Z0-9_]+)\)\s*==\s*'([a-zA-Z0-9_]+)'$", expr)
        if m_type:
            of = m_type.group(1)
            expected_t = m_type.group(2)
            if of not in fact.output_data or fact.output_data[of] is None:
                return None
            actual_val = fact.output_data[of]
            actual_t = self._get_type_name(actual_val)
            return actual_t == expected_t

        # 5. Field Presence: exists(output.x)
        m_exists = re.match(r"^exists\(output\.([a-zA-Z0-9_]+)\)$", expr)
        if m_exists:
            of = m_exists.group(1)
            return of in fact.output_data

        # 6. Non-Null: output.x != null
        m_nn = re.match(r"^output\.([a-zA-Z0-9_]+)\s*!=\s*null$", expr)
        if m_nn:
            of = m_nn.group(1)
            if of not in fact.output_data:
                return None
            return fact.output_data[of] is not None

        # 7. Relational Invariants: f1 <= f2, f1 >= f2
        m_rel = re.match(r"^(input|output)\.([a-zA-Z0-9_]+)\s*(<=|>=)\s*(input|output)\.([a-zA-Z0-9_]+)$", expr)
        if m_rel:
            z1, f1, op, z2, f2 = m_rel.group(1), m_rel.group(2), m_rel.group(3), m_rel.group(4), m_rel.group(5)
            d1 = fact.input_data if z1 == "input" else fact.output_data
            d2 = fact.input_data if z2 == "input" else fact.output_data
            if f1 not in d1 or f2 not in d2:
                return None
            v1, v2 = d1[f1], d2[f2]
            if not isinstance(v1, (int, float)) or not isinstance(v2, (int, float)) or isinstance(v1, bool) or isinstance(v2, bool):
                return False
            if op == "<=":
                return float(v1) <= float(v2) + policy.numeric_tolerance
            elif op == ">=":
                return float(v1) >= float(v2) - policy.numeric_tolerance

        # 8. Error Behavior: has_error == false / true
        if expr == "has_error == false":
            if fact.has_error is None or not fact.is_valid:
                return None
            return fact.has_error is False
        elif expr == "has_error == true":
            if fact.has_error is None or not fact.is_valid:
                return None
            return fact.has_error is True

        m_err_cat = re.match(r"^error\.category\s*==\s*'(.+)'$", expr)
        if m_err_cat:
            cat = m_err_cat.group(1)
            if fact.has_error is not True:
                return None
            return fact.error_data.get("category") == cat

        # 9. State Invariant & Transition Rules
        if expr == "state.mutated == false":
            if not fact.state_valid or fact.state_mutated is None:
                return None
            return fact.state_mutated is False
        elif expr == "state.mutated == true":
            if not fact.state_valid or fact.state_mutated is None:
                return None
            return fact.state_mutated is True

        # State Table Row Count Delta / Invariant: state_after.tbl.row_count == state_before.tbl.row_count (+/- delta)
        m_st_tbl = re.match(r"^state_after\.([a-zA-Z0-9_]+)\.row_count\s*==\s*state_before\.([a-zA-Z0-9_]+)\.row_count(?:\s*([\+\-])\s*([0-9]+))?$", expr)
        if m_st_tbl:
            tbl_a, tbl_b = m_st_tbl.group(1), m_st_tbl.group(2)
            sign, d_str = m_st_tbl.group(3), m_st_tbl.group(4)
            delta = int(d_str) if d_str else 0
            if sign == "-":
                delta = -delta

            if not fact.state_valid or fact.state_before is None or fact.state_after is None:
                return None
            ca = self._extract_state_count(fact.state_after.get(tbl_a))
            cb = self._extract_state_count(fact.state_before.get(tbl_b))
            if ca is None or cb is None:
                return None
            return ca == (cb + delta)

        # State Scalar Field Delta / Invariant: state_after.fld == state_before.fld (+/- delta)
        m_st_fld = re.match(r"^state_after\.([a-zA-Z0-9_]+)\s*==\s*state_before\.([a-zA-Z0-9_]+)(?:\s*([\+\-])\s*([0-9\.\-]+))?$", expr)
        if m_st_fld:
            fa, fb = m_st_fld.group(1), m_st_fld.group(2)
            sign, d_str = m_st_fld.group(3), m_st_fld.group(4)
            delta = float(d_str) if d_str else 0.0
            if sign == "-":
                delta = -delta

            if not fact.state_valid or fact.state_before is None or fact.state_after is None:
                return None
            if fa not in fact.state_after or fb not in fact.state_before:
                return None
            va = fact.state_after[fa]
            vb = fact.state_before[fb]
            if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and not isinstance(va, bool) and not isinstance(vb, bool):
                return abs(float(va) - (float(vb) + delta)) < policy.numeric_tolerance
            return va == vb

        # 10. Cross-Input Invariants
        if expr.startswith("cross_input_invariant(keys(output)"):
            if not fact.output_observed or not fact.output_data:
                return None
            m_k = re.match(r"^cross_input_invariant\(keys\(output\)\s*==\s*\[(.*)\]\)$", expr)
            if m_k:
                raw_ks = [k.strip().strip("'").strip('"') for k in m_k.group(1).split(",") if k.strip()]
                return sorted(list(fact.output_data.keys())) == sorted(raw_ks)
            return True

        if expr.startswith("monotonic_non_decreasing("):
            m_m = re.match(r"^monotonic_non_decreasing\(input\.([a-zA-Z0-9_]+)\s*->\s*output\.([a-zA-Z0-9_]+)\)$", expr)
            if m_m:
                ik, ok = m_m.group(1), m_m.group(2)
                if ik not in fact.input_data or ok not in fact.output_data:
                    return None
                return True

        # 11. Workflow Invariants: workflow.event('A') precedes workflow.event('B')
        m_wf_prec = re.match(r"^workflow\.event\('(.+?)'\)\s+precedes\s+workflow\.event\('(.+?)'\)$", expr)
        if m_wf_prec:
            ev_a = m_wf_prec.group(1)
            ev_b = m_wf_prec.group(2)
            if not fact.workflow_events:
                return None
            if ev_a not in fact.workflow_events or ev_b not in fact.workflow_events:
                return None
            return fact.workflow_events.index(ev_a) < fact.workflow_events.index(ev_b)

        # 12. Boundary Transitions:
        # transition(input.x >= T) -> has_error == true/false
        m_trans_err = re.match(r"^transition\(input\.([a-zA-Z0-9_]+)\s*>=\s*([0-9\.\-]+)\)\s*->\s*has_error\s*==\s*(true|false)$", expr)
        if m_trans_err:
            ik = m_trans_err.group(1)
            t_val = float(m_trans_err.group(2))
            expected_err = m_trans_err.group(3) == "true"
            if ik not in fact.input_data or not isinstance(fact.input_data[ik], (int, float)) or isinstance(fact.input_data[ik], bool):
                return None
            if fact.has_error is None:
                return None
            iv = float(fact.input_data[ik])
            if iv >= t_val:
                return fact.has_error == expected_err
            else:
                return fact.has_error != expected_err

        # transition(input.x >= T) -> output.y == val
        m_trans_out = re.match(r"^transition\(input\.([a-zA-Z0-9_]+)\s*>=\s*([0-9\.\-]+)\)\s*->\s*output\.([a-zA-Z0-9_]+)\s*==\s*(.+)$", expr)
        if m_trans_out:
            ik = m_trans_out.group(1)
            t_val = float(m_trans_out.group(2))
            ok = m_trans_out.group(3)
            raw_target = m_trans_out.group(4).strip()
            target_val = self._parse_literal(raw_target)

            if ik not in fact.input_data or not isinstance(fact.input_data[ik], (int, float)) or isinstance(fact.input_data[ik], bool):
                return None
            if ok not in fact.output_data:
                return None
            iv = float(fact.input_data[ik])
            ov = fact.output_data[ok]
            if iv >= t_val:
                return ov == target_val
            else:
                return ov != target_val

        # Generic default: if unable to evaluate deterministically
        return None

    def _extract_state_count(self, tbl_val: Any) -> Optional[int]:
        """Extracts integer row count from table representation."""
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

    def _parse_literal(self, s: str) -> Any:
        """Parses literal value from string representation."""
        s = s.strip()
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False
        if s.lower() in ("null", "none"):
            return None
        if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
            return s[1:-1]
        try:
            if "." in s:
                return float(s)
            return int(s)
        except ValueError:
            return s

    def _get_type_name(self, val: Any) -> str:
        """Gets string type identifier for a Python value."""
        if isinstance(val, bool):
            return "boolean"
        if isinstance(val, int):
            return "integer"
        if isinstance(val, float):
            return "number"
        if isinstance(val, str):
            return "string"
        if isinstance(val, list):
            return "array"
        if isinstance(val, dict):
            return "object"
        return "unknown"


candidate_validator = CandidateValidator()
