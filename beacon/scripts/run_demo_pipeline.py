"""Run the BEACON sample pipeline from the command line.

Default mode is fully local: it generates traces, deterministically mines and
validates Python decision rules, certifies the intentionally buggy sample, and
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
from ingestion.legacy_parser import load_source
from ingestion.trace_loader import load_traces
from mining.offline_miner import mine_python_decision_rules
from oracle.synthesizer import synthesize_oracle

import legacy_loan_approval
import modern_loan_approval
from generate_traces import generate_traces


FIELD_BOUNDS = {
    "credit_score": (400, 820),
    "debt_ratio": (0.0, 0.9),
    "annual_income": (10_000, 150_000),
}


def get_validated_invariants(traces):
    source = load_source(ROOT / "legacy_sample" / "legacy_loan_approval.py")
    if os.getenv("MINE_WITH_LLM") == "1":
        from mining.pipeline import mine_one_invariant
        print("Running cloud LLM invariant mining.\n")
        return [mine_one_invariant(
            source_code=source,
            traces=traces,
            legacy_fn=legacy_loan_approval.evaluate_loan,
            field_bounds=FIELD_BOUNDS,
            already_validated=[],
            use_atlas=bool(os.getenv("MONGODB_ATLAS_URI")),
        )]

    print("Running deterministic local invariant mining and validation.\n")
    return mine_python_decision_rules(
        source, traces, legacy_loan_approval.evaluate_loan, FIELD_BOUNDS
    )


def main():
    trace_path = ROOT / "legacy_sample" / "trace_log.json"
    if not trace_path.exists():
        trace_path.write_text(json.dumps(generate_traces(), indent=2))
        print("Generated sample traces.\n")
    traces = load_traces(trace_path)

    invariants = get_validated_invariants(traces)
    oracles = [synthesize_oracle(invariant) for invariant in invariants if invariant.graduated]
    print(f"Graduated invariants: {[oracle.invariant_id for oracle in oracles]}\n")
    if not oracles:
        raise RuntimeError("No invariants graduated; certification cannot run.")

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
