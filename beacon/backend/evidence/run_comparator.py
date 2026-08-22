"""Phase 15 — Multi-Run Evidence Comparator.

Compares two certification runs side-by-side:
- Dataset identity, checksum, and schema
- Implementation adapter bytecode hashes
- OracleSet identity and content hashes
- Policy definitions and thresholds
- Disambiguated metrics, scores, and coverage
- Differential regression analysis (new, fixed, persistent counterexamples)
- Context equivalence detection and idempotency relationships.

Comparison is strictly an analytical reporting tool and NEVER overrides
or recomputes certification decisions.
"""

from typing import Any, Optional
from certification.repository import certification_repository


def compare_certification_runs(
    run_id_a: str,
    run_id_b: str,
    project_id: Optional[str] = None,
) -> dict[str, Any]:
    """Compares two historical certification runs and produces a differential audit report."""
    art_a = certification_repository.get_artifact(run_id_a)
    if not art_a:
        raise ValueError(f"Certification run '{run_id_a}' not found.")
    
    art_b = certification_repository.get_artifact(run_id_b)
    if not art_b:
        raise ValueError(f"Certification run '{run_id_b}' not found.")

    # Project scoping check
    if project_id:
        if art_a.project_id != project_id:
            raise PermissionError(f"Access denied: Run '{run_id_a}' does not belong to project '{project_id}'.")
        if art_b.project_id != project_id:
            raise PermissionError(f"Access denied: Run '{run_id_b}' does not belong to project '{project_id}'.")

    # 1. Context Equivalence Check
    divergence_reasons: list[str] = []
    
    # Dataset comparison
    ctx_a = art_a.context
    ctx_b = art_b.context
    ds_chk_a = getattr(art_a, "dataset_checksum", "") or (ctx_a.dataset_checksum if ctx_a else "")
    ds_chk_b = getattr(art_b, "dataset_checksum", "") or (ctx_b.dataset_checksum if ctx_b else "")
    dataset_match = (ds_chk_a == ds_chk_b and bool(ds_chk_a))
    if not dataset_match and (ds_chk_a or ds_chk_b):
        divergence_reasons.append(f"Datasets differ: '{ds_chk_a[:12]}...' vs '{ds_chk_b[:12]}...'")

    # Implementations comparison
    leg_h_a = getattr(art_a, "legacy_implementation_hash", "") or (ctx_a.legacy_implementation_hash if ctx_a else "")
    leg_h_b = getattr(art_b, "legacy_implementation_hash", "") or (ctx_b.legacy_implementation_hash if ctx_b else "")
    mod_h_a = getattr(art_a, "modernized_implementation_hash", "") or (ctx_a.modernized_implementation_hash if ctx_a else "")
    mod_h_b = getattr(art_b, "modernized_implementation_hash", "") or (ctx_b.modernized_implementation_hash if ctx_b else "")
    impl_match = (leg_h_a == leg_h_b and mod_h_a == mod_h_b)
    if not impl_match:
        divergence_reasons.append("Implementation adapter hashes differ between runs.")

    # OracleSet comparison
    orc_match = (art_a.oracle_set_hash == art_b.oracle_set_hash and bool(art_a.oracle_set_hash))
    if not orc_match:
        divergence_reasons.append(f"OracleSets differ: '{art_a.oracle_set_id}' vs '{art_b.oracle_set_id}'")

    # Policy comparison
    pol_match = (art_a.certification_policy_hash == art_b.certification_policy_hash)
    if not pol_match:
        divergence_reasons.append(f"Policies differ: '{art_a.certification_policy_id}' vs '{art_b.certification_policy_id}'")

    is_equivalent_context = (len(divergence_reasons) == 0)

    # 2. Idempotency & Reuse Relationship
    is_identical_artifact = (art_a.certification_id == art_b.certification_id or art_a.content_hash == art_b.content_hash)
    is_reused_execution = (
        is_equivalent_context and is_identical_artifact and
        getattr(art_b.context, "idempotency_key", None) == getattr(art_a.context, "idempotency_key", None)
    )
    is_forced_recompute = bool(getattr(art_b.context, "is_forced_recompute", False))

    # 3. Disambiguated Metrics Comparison
    status_a = art_a.status.value if hasattr(art_a.status, "value") else str(art_a.status)
    status_b = art_b.status.value if hasattr(art_b.status, "value") else str(art_b.status)
    
    score_delta = art_b.score - art_a.score
    cov_a = art_a.metrics.oracle_coverage_pct
    cov_b = art_b.metrics.oracle_coverage_pct
    cov_delta = cov_b - cov_a

    # 4. Differential Regression Analysis
    regs_a_keys = {f"{r.oracle_id}:{r.input_hash or r.input_id}" for r in art_a.regressions}
    regs_b_keys = {f"{r.oracle_id}:{r.input_hash or r.input_id}" for r in art_b.regressions}

    fixed_regressions = [
        {"oracle_id": r.oracle_id, "input_id": r.input_id, "severity": r.severity, "legacy_output": r.legacy_output, "modern_output": r.modern_output}
        for r in art_a.regressions
        if f"{r.oracle_id}:{r.input_hash or r.input_id}" not in regs_b_keys
    ]
    new_regressions = [
        {"oracle_id": r.oracle_id, "input_id": r.input_id, "severity": r.severity, "legacy_output": r.legacy_output, "modern_output": r.modern_output}
        for r in art_b.regressions
        if f"{r.oracle_id}:{r.input_hash or r.input_id}" not in regs_a_keys
    ]
    persistent_regressions = [
        {"oracle_id": r.oracle_id, "input_id": r.input_id, "severity": r.severity}
        for r in art_b.regressions
        if f"{r.oracle_id}:{r.input_hash or r.input_id}" in regs_a_keys
    ]

    return {
        "run_id_a": run_id_a,
        "run_id_b": run_id_b,
        "timestamp_a": art_a.timestamp,
        "timestamp_b": art_b.timestamp,
        "is_equivalent_context": is_equivalent_context,
        "context_divergence_reasons": divergence_reasons,
        "relationship": {
            "identical_artifact": is_identical_artifact,
            "reused_execution": is_reused_execution,
            "forced_recompute": is_forced_recompute,
        },
        "identities": {
            "dataset_match": dataset_match,
            "dataset_a": {"checksum": ds_chk_a, "name": ctx_a.benchmark_name if ctx_a else ""},
            "dataset_b": {"checksum": ds_chk_b, "name": ctx_b.benchmark_name if ctx_b else ""},
            "implementations_match": impl_match,
            "oracle_set_match": orc_match,
            "policy_match": pol_match,
        },
        "status_comparison": {
            "status_a": status_a,
            "status_b": status_b,
            "status_changed": (status_a != status_b),
            "certified_a": art_a.certified,
            "certified_b": art_b.certified,
        },
        "metrics_comparison": {
            "score_a": art_a.score,
            "score_b": art_b.score,
            "score_delta": round(score_delta, 4),
            "coverage_pct_a": cov_a,
            "coverage_pct_b": cov_b,
            "coverage_delta": round(cov_delta, 4),
            "total_cases_a": art_a.metrics.certification_case_count,
            "total_cases_b": art_b.metrics.certification_case_count,
            "matches_a": art_a.metrics.matching_case_count,
            "matches_b": art_b.metrics.matching_case_count,
            "regressions_a": len(art_a.regressions),
            "regressions_b": len(art_b.regressions),
        },
        "differential_regressions": {
            "fixed_count": len(fixed_regressions),
            "new_count": len(new_regressions),
            "persistent_count": len(persistent_regressions),
            "fixed_regressions": fixed_regressions,
            "new_regressions": new_regressions,
        },
    }
