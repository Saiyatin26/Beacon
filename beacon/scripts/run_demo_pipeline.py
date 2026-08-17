"""Run the BEACON sample pipeline from the command line.

Default mode is fully local: it generates traces, builds the unified evidence package,
mines and validates Python decision rules, certifies the intentionally buggy sample, and
saves the report to SQLite. Set ``MINE_WITH_LLM=1`` with cloud credentials to
use the original LLM mining path instead.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

from certification.reporter import print_report
from certification.runner import certify
from common.local_store import local_store
from ingestion.legacy_parser import extract_ast_structure
from ingestion.trace_loader import load_traces
from evidence.builder import build_evidence_package
from mining.pipeline import run_mining_pipeline
from oracle.synthesizer import synthesize_oracle

import legacy_loan_approval
import modern_loan_approval
from generate_traces import generate_traces


FIELD_BOUNDS = {
    "credit_score": (400, 820),
    "debt_ratio": (0.0, 0.9),
    "annual_income": (10_000, 150_000),
}


def main():
    print("==================================================================")
    print("           BEACON DETERMINISTIC DEMONSTRATION RUNNER             ")
    print("==================================================================\n")

    trace_path = ROOT / "legacy_sample" / "trace_log.json"
    if not trace_path.exists():
        trace_path.write_text(json.dumps(generate_traces(), indent=2))
        print("Stage 1a: Generated synthetic trace log (legacy_sample/trace_log.json).")
    traces = load_traces(trace_path)
    print(f"Stage 1b: Loaded {len(traces)} execution traces into TraceEvent objects.")

    legacy_file = str(ROOT / "legacy_sample" / "legacy_loan_approval.py")
    static_result = extract_ast_structure(legacy_file)
    print(f"Stage 1c: Static AST extraction completed for {legacy_file}.")
    
    evidence_pkg = build_evidence_package(static_result, traces)
    print(f"Stage 1d: Built UnifiedEvidencePackage containing {len(evidence_pkg.correlated_conditions)} correlated facts.\n")

    use_llm = os.getenv("MINE_WITH_LLM") == "1"
    if use_llm:
        print("Running cloud LLM invariant mining.")
    else:
        print("Running deterministic local invariant mining and validation.")

    graduated, unconfirmed = run_mining_pipeline(
        evidence_package=evidence_pkg,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        already_validated=[],
        use_atlas=False,
        use_llm=use_llm,
    )
    
    print("\nStage 2: Mined & Validated Invariants:")
    for inv in graduated:
        print(f"  - [GRADUATED] Invariant #{inv.invariant_id}: IF {inv.condition} THEN {inv.consequence} (Confidence: {inv.confidence:.2f}, Severity: {inv.severity})")
    for un in unconfirmed:
        print(f"  - [UNCONFIRMED] Hypothesis #{un.invariant_id}: IF {un.condition} THEN {un.consequence} (Failed gate with Confidence: {un.confidence:.2f})")
    print()

    oracles = [synthesize_oracle(invariant) for invariant in graduated]
    print("Stage 3: Synthesized Executable Oracles:")
    for oracle in oracles:
        print(f"  - Oracle #{oracle.invariant_id}: Property -> \"{oracle.property}\"")
    print()

    if not oracles:
        raise RuntimeError("No invariants graduated; certification cannot run.")

    print("Stage 4: Certifying Modernized Application against Legacy System Oracles...")
    run = certify(
        oracles=oracles,
        modern_fn=modern_loan_approval.evaluate_loan,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        domain_of={oracle.invariant_id: "Loan approval" for oracle in oracles},
    )
    print_report(run)
    local_store.save_run(run)
    print("Saved this certification run to data/beacon.sqlite3 for the dashboard.")


if __name__ == "__main__":
    main()
