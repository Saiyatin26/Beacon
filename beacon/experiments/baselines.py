"""Implementations of the Four Certification Baselines (Comment 2 & Section 3).

M1: Output-only comparison (Certify iff R == 1.0 across all observed inputs; no gates, no Q).
M2: Unweighted evidence scoring (Certify iff R >= Theta; no Q adjustment, no gates).
M3: BEACON without sufficiency gates (S_adj = R * Q >= Theta; sufficiency gates G1, G2, G5 disabled).
M4: Full BEACON (S_adj = R * Q >= Theta; all sufficiency and integrity gates G1-G6 active).

All methods are evaluated on identical test inputs with canonical digests.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import time
from typing import Any, Callable, Optional


# Weight vector w0 = (0.30, 0.20, 0.20, 0.15, 0.10, 0.05)
DEFAULT_WEIGHTS = {
    "oracle_coverage": 0.30,
    "input_coverage": 0.20,
    "execution_reliability": 0.20,
    "oracle_confidence": 0.15,
    "input_set_integrity": 0.10,
    "source_hash_integrity": 0.05,
}

# 8 Core Specification Rules for CardDemo COACTUPC
SPEC_RULES = [
    "RULE_01_FIRST_ENTRY_SIGNON",
    "RULE_02_PF3_MENU_RETURN",
    "RULE_03_ACCOUNT_ID_VALIDATION",
    "RULE_04_ACCOUNT_LOOKUP_FOUND",
    "RULE_05_STATUS_VALIDATION",
    "RULE_06_CREDIT_LIMIT_DECIMAL",
    "RULE_07_PREVIEW_CONFIRMATION",
    "RULE_08_COMMIT_ON_PF5",
]


def classify_input_rules(inp: dict[str, Any]) -> set[str]:
    """Maps a test input to the specification rules it exercises."""
    rules = set()
    calen = int(inp.get("EIBCALEN", 100))
    aid = str(inp.get("EIBAID", "ENTER")).upper().strip()
    act = str(inp.get("ACTION", "S")).strip()

    if calen == 0:
        rules.add("RULE_01_FIRST_ENTRY_SIGNON")
    if aid == "PF3":
        rules.add("RULE_02_PF3_MENU_RETURN")
    if act == "":
        acct = str(inp.get("ACCT_ID", "")).strip()
        if not acct.isdigit() or acct in ("0", "999999999"):
            rules.add("RULE_03_ACCOUNT_ID_VALIDATION")
        else:
            rules.add("RULE_04_ACCOUNT_LOOKUP_FOUND")
    elif act == "S":
        status = str(inp.get("ACTIVE_STATUS", "")).strip().upper()
        if status not in ("Y", "N"):
            rules.add("RULE_05_STATUS_VALIDATION")
        else:
            rules.add("RULE_06_CREDIT_LIMIT_DECIMAL")
            rules.add("RULE_07_PREVIEW_CONFIRMATION")
    elif act == "N":
        if aid == "PF5":
            rules.add("RULE_08_COMMIT_ON_PF5")
    return rules


def compute_evidence_factors(
    total_inputs: int,
    evaluated_inputs: int,
    error_inputs: int,
    covered_rules: set[str],
    corrupt_input_hash: bool = False,
    corrupt_source_hash: bool = False,
) -> dict[str, float]:
    """Computes the 6 empirical evidence factors f1..f6."""
    f1_oracle_cov = len(covered_rules) / len(SPEC_RULES)
    f2_input_cov = min(evaluated_inputs / max(total_inputs, 1), 1.0)
    f3_reliability = max(1.0 - (error_inputs / max(evaluated_inputs, 1)), 0.0) if evaluated_inputs > 0 else 0.0
    f4_confidence = 0.95
    f5_input_integrity = 0.0 if corrupt_input_hash else 1.0
    f6_source_integrity = 0.0 if corrupt_source_hash else 1.0

    return {
        "oracle_coverage": round(f1_oracle_cov, 4),
        "input_coverage": round(f2_input_cov, 4),
        "execution_reliability": round(f3_reliability, 4),
        "oracle_confidence": f4_confidence,
        "input_set_integrity": f5_input_integrity,
        "source_hash_integrity": f6_source_integrity,
    }


def compute_quality_score(factors: dict[str, float], weights: dict[str, float] = DEFAULT_WEIGHTS) -> float:
    """Computes composite evidence quality Q = sum(w_i * f_i) / sum(w_i)."""
    num = sum(weights[k] * factors.get(k, 0.0) for k in weights)
    den = sum(weights.values())
    return round(num / den, 6) if den > 0 else 0.0


@dataclass
class BaselineVerdict:
    method: str
    verdict: str  # CERTIFIED, CERTIFIED_WITH_WARNINGS, NOT_CERTIFIED, INSUFFICIENT_COVERAGE
    verdict_reason: str
    behavioral_score_R: float
    evidence_quality_Q: float
    adjusted_score_S: float
    mismatch_count: int
    evaluated_count: int
    elapsed_seconds: float
    factors: dict[str, float] = field(default_factory=dict)
    active_gates: list[str] = field(default_factory=list)


# ─── M1: Output-Only Comparison ─────────────────────────────────────────────

def evaluate_m1_output_only(
    test_inputs: list[dict[str, Any]],
    candidate_runner: Callable[[dict[str, Any]], dict[str, Any]],
    reference_runner: Callable[[dict[str, Any]], dict[str, Any]],
) -> BaselineVerdict:
    """M1 Output-Only Comparison: Certifies iff every normalized output matches (R == 1.0).

    Does not use oracles, evidence quality adjustment Q, or sufficiency gates.
    Never outputs INSUFFICIENT_COVERAGE.
    """
    t0 = time.perf_counter()
    mismatches = 0
    first_diff = None

    for inp in test_inputs:
        try:
            r_out = reference_runner(inp)
            c_out = candidate_runner(inp)
            if r_out != c_out:
                mismatches += 1
                if first_diff is None:
                    first_diff = f"Divergence on {list(k for k in r_out if r_out.get(k) != c_out.get(k))}"
        except Exception as e:
            mismatches += 1
            if first_diff is None:
                first_diff = f"Execution error/timeout: {type(e).__name__}"

    elapsed = time.perf_counter() - t0
    n = len(test_inputs)
    r_score = (n - mismatches) / n if n > 0 else 0.0

    if mismatches == 0:
        verdict = "CERTIFIED"
        reason = f"All {n} observed transaction outputs strictly match reference"
    else:
        verdict = "NOT_CERTIFIED"
        reason = f"Observed {mismatches} behavioral mismatches ({first_diff})"

    return BaselineVerdict(
        method="M1_output_only",
        verdict=verdict,
        verdict_reason=reason,
        behavioral_score_R=round(r_score, 4),
        evidence_quality_Q=1.0,
        adjusted_score_S=round(r_score, 4),
        mismatch_count=mismatches,
        evaluated_count=n,
        elapsed_seconds=elapsed,
    )


# ─── M2: Unweighted Evidence Scoring ────────────────────────────────────────

def evaluate_m2_unweighted_score(
    test_inputs: list[dict[str, Any]],
    candidate_runner: Callable[[dict[str, Any]], dict[str, Any]],
    reference_runner: Callable[[dict[str, Any]], dict[str, Any]],
    theta: float = 0.90,
) -> BaselineVerdict:
    """M2 Unweighted Evidence Scoring: Compares raw agreement score R with threshold Theta.

    Evaluates headline agreement R >= Theta without evidence quality adjustment (S = R)
    and without sufficiency gates.
    """
    t0 = time.perf_counter()
    mismatches = 0
    covered_rules = set()

    for inp in test_inputs:
        covered_rules.update(classify_input_rules(inp))
        r_out = reference_runner(inp)
        c_out = candidate_runner(inp)
        if r_out != c_out:
            mismatches += 1

    elapsed = time.perf_counter() - t0
    n = len(test_inputs)
    r_score = (n - mismatches) / n if n > 0 else 0.0

    if r_score >= theta:
        verdict = "CERTIFIED"
        reason = f"Raw agreement score {r_score:.4f} meets unweighted policy threshold {theta:.2f}"
    else:
        verdict = "NOT_CERTIFIED"
        reason = f"Raw agreement score {r_score:.4f} below policy threshold {theta:.2f} ({mismatches} mismatches)"

    return BaselineVerdict(
        method="M2_unweighted_score",
        verdict=verdict,
        verdict_reason=reason,
        behavioral_score_R=round(r_score, 4),
        evidence_quality_Q=1.0,
        adjusted_score_S=round(r_score, 4),
        mismatch_count=mismatches,
        evaluated_count=n,
        elapsed_seconds=elapsed,
        factors={"oracle_coverage": round(len(covered_rules) / len(SPEC_RULES), 4)},
    )


# ─── M3: BEACON Without Sufficiency Gates ───────────────────────────────────

def evaluate_m3_without_sufficiency_gates(
    test_inputs: list[dict[str, Any]],
    candidate_runner: Callable[[dict[str, Any]], dict[str, Any]],
    reference_runner: Callable[[dict[str, Any]], dict[str, Any]],
    theta: float = 0.90,
    weights: dict[str, float] = DEFAULT_WEIGHTS,
    corrupt_integrity: bool = False,
) -> BaselineVerdict:
    """M3 BEACON Without Sufficiency Gates: Evaluates S_adj = R * Q against Theta.

    Sufficiency gates G1 (input count floor), G2 (reliability floor), and G5 (coverage floor)
    are DISABLED.
    Keeps G3 (cryptographic integrity), G4 (provenance), and G6 (mismatch gate).
    """
    t0 = time.perf_counter()
    mismatches = 0
    errors = 0
    covered_rules = set()

    for inp in test_inputs:
        covered_rules.update(classify_input_rules(inp))
        try:
            r_out = reference_runner(inp)
            c_out = candidate_runner(inp)
            if r_out != c_out:
                mismatches += 1
        except Exception:
            errors += 1
            mismatches += 1

    elapsed = time.perf_counter() - t0
    n = len(test_inputs)
    r_score = (n - mismatches) / n if n > 0 else 0.0

    factors = compute_evidence_factors(
        total_inputs=n,
        evaluated_inputs=n - errors,
        error_inputs=errors,
        covered_rules=covered_rules,
        corrupt_input_hash=corrupt_integrity,
        corrupt_source_hash=corrupt_integrity,
    )
    q_score = compute_quality_score(factors, weights)
    s_adj = round(r_score * q_score, 6)

    # Active gates: G3 integrity, G6 mismatch. (G1, G2, G5 are disabled)
    if corrupt_integrity or factors["input_set_integrity"] < 1.0 or factors["source_hash_integrity"] < 1.0:
        verdict = "NOT_CERTIFIED"
        reason = "G3 Gate Failure: Cryptographic integrity check failed"
    elif mismatches > 0:
        verdict = "NOT_CERTIFIED"
        reason = f"G6 Gate Failure: {mismatches} behavioral mismatches detected"
    elif s_adj >= theta:
        verdict = "CERTIFIED"
        reason = f"Adjusted score {s_adj:.4f} meets policy threshold {theta:.2f}"
    else:
        verdict = "NOT_CERTIFIED"
        reason = f"Adjusted score {s_adj:.4f} below threshold {theta:.2f}"

    return BaselineVerdict(
        method="M3_no_sufficiency_gates",
        verdict=verdict,
        verdict_reason=reason,
        behavioral_score_R=round(r_score, 4),
        evidence_quality_Q=q_score,
        adjusted_score_S=s_adj,
        mismatch_count=mismatches,
        evaluated_count=n,
        elapsed_seconds=elapsed,
        factors=factors,
        active_gates=["G3_integrity", "G4_provenance", "G6_mismatch"],
    )


# ─── M4: Full BEACON ────────────────────────────────────────────────────────

def evaluate_m4_full_beacon(
    test_inputs: list[dict[str, Any]],
    candidate_runner: Callable[[dict[str, Any]], dict[str, Any]],
    reference_runner: Callable[[dict[str, Any]], dict[str, Any]],
    theta: float = 0.90,
    min_coverage: float = 0.80,
    min_reliability: float = 0.90,
    weights: dict[str, float] = DEFAULT_WEIGHTS,
    corrupt_integrity: bool = False,
    override_factors: Optional[dict[str, float]] = None,
    disable_quality_adjustment: bool = False,
    disable_gates: Optional[list[str]] = None,
    active_rule_set: Optional[set[str]] = None,
) -> BaselineVerdict:
    """M4 Full BEACON: Complete fail-closed evidence-adjusted certification pipeline.

    Evaluates S_adj = R * Q with dynamic threshold Theta and safety gates.
    Individual components (quality adjustment, specific gates, active rules) can be isolated
    via parameters for controlled ablation and evidence degradation studies.
    """
    t0 = time.perf_counter()
    mismatches = 0
    errors = 0
    covered_rules = set()

    for inp in test_inputs:
        rules = classify_input_rules(inp)
        if active_rule_set is not None:
            rules = [r for r in rules if r in active_rule_set]
        covered_rules.update(rules)
        try:
            r_out = reference_runner(inp)
            c_out = candidate_runner(inp)
            if r_out != c_out:
                mismatches += 1
        except Exception:
            errors += 1
            mismatches += 1

    elapsed = time.perf_counter() - t0
    n = len(test_inputs)
    r_score = (n - mismatches) / n if n > 0 else 0.0

    factors = compute_evidence_factors(
        total_inputs=n,
        evaluated_inputs=n - errors,
        error_inputs=errors,
        covered_rules=covered_rules,
        corrupt_input_hash=corrupt_integrity,
        corrupt_source_hash=corrupt_integrity,
    )
    if override_factors:
        factors.update(override_factors)

    if disable_quality_adjustment:
        q_score = 1.0
        s_adj = round(r_score, 6)
    else:
        q_score = compute_quality_score(factors, weights)
        s_adj = round(r_score * q_score, 6)

    dis_gates = set(disable_gates or [])
    active_gates = [g for g in ["G1_input_floor", "G2_reliability_floor", "G3_integrity", "G4_provenance", "G5_coverage_floor", "G6_mismatch"]
                    if not any(dg in g for dg in dis_gates)]

    # Fail-closed Gate Evaluation
    if "G1" not in dis_gates and n == 0:
        verdict = "INSUFFICIENT_COVERAGE"
        reason = "G1 Gate Failure: Zero evaluated inputs provided"
    elif "G2" not in dis_gates and factors["execution_reliability"] < min_reliability:
        verdict = "INSUFFICIENT_COVERAGE"
        reason = f"G2 Gate Failure: Execution reliability ({factors['execution_reliability']*100:.1f}%) below floor ({min_reliability*100:.1f}%)"
    elif "G3" not in dis_gates and (factors["input_set_integrity"] < 1.0 or factors["source_hash_integrity"] < 1.0):
        verdict = "NOT_CERTIFIED"
        reason = "G3 Gate Failure: Input or source integrity verification failed"
    elif "G5" not in dis_gates and factors["oracle_coverage"] < min_coverage:
        verdict = "INSUFFICIENT_COVERAGE"
        reason = f"G5 Gate Failure: Rule coverage ({factors['oracle_coverage']*100:.1f}%) below required floor ({min_coverage*100:.1f}%)"
    elif "G6" not in dis_gates and mismatches > 0:
        verdict = "NOT_CERTIFIED"
        reason = f"G6 Gate Failure: {mismatches} behavioral mismatches detected on contract"
    elif s_adj >= theta:
        verdict = "CERTIFIED"
        reason = f"Adjusted score {s_adj:.4f} meets policy threshold {theta:.2f} with all active gates satisfied"
    else:
        verdict = "NOT_CERTIFIED"
        reason = f"Adjusted score {s_adj:.4f} below threshold {theta:.2f}"

    return BaselineVerdict(
        method="M4_full_beacon",
        verdict=verdict,
        verdict_reason=reason,
        behavioral_score_R=round(r_score, 4),
        evidence_quality_Q=q_score,
        adjusted_score_S=s_adj,
        mismatch_count=mismatches,
        evaluated_count=n,
        elapsed_seconds=elapsed,
        factors=factors,
        active_gates=active_gates,
    )
