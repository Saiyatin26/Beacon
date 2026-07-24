"""End-to-end BEACON demo, matching the architecture doc's worked example
(Section 7.4, Invariant #147). Runs entirely against the sample legacy/modern
loan-approval apps with mocked trace generation and mocked execution — no
Atlas/Claude credentials required to see the certification + drift mechanism
work (set MINE_WITH_LLM=1 and fill in .env to exercise the real Stage 2 LLM
call and Atlas storage instead of the offline fallback below).

Run: python3 scripts/run_demo_pipeline.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

from ingestion.trace_loader import load_traces
from ingestion.legacy_parser import load_source
from common.models import ValidatedInvariant
from oracle.synthesizer import synthesize_oracle
from certification.runner import certify
from certification.reporter import print_report
from drift.sampler import sample_traffic
from drift.monitor import check_drift

import legacy_loan_approval
import modern_loan_approval
from generate_traces import generate_traces

FIELD_BOUNDS = {
    "credit_score": (400, 820),
    "debt_ratio": (0.0, 0.9),
    "annual_income": (10000, 150000),
}
DOMAIN_OF = {}  # invariant_id -> domain label; populate as invariants are tagged


def get_validated_invariants(traces) -> list[ValidatedInvariant]:
    """Runs Stage 2 for real if MINE_WITH_LLM=1 and credentials are set;
    otherwise falls back to the known invariant hard-coded here so the rest of
    the pipeline (Stages 3-5) can be demoed without API keys."""
    if os.getenv("MINE_WITH_LLM") == "1":
        from mining.pipeline import mine_one_invariant
        source = load_source(ROOT / "legacy_sample" / "legacy_loan_approval.py")
        validated = mine_one_invariant(
            source_code=source,
            traces=traces,
            legacy_fn=legacy_loan_approval.evaluate_loan,
            field_bounds=FIELD_BOUNDS,
            already_validated=[],
            use_atlas=bool(os.getenv("MONGODB_ATLAS_URI")),
        )
        return [validated]

    print("MINE_WITH_LLM not set — using a pre-mined invariant for the demo.\n"
          "Set MINE_WITH_LLM=1 with ANTHROPIC_API_KEY in .env to run Stage 2 for real.\n")
    return [ValidatedInvariant(
        invariant_id="147",
        condition="credit_score < 600 and debt_ratio > 0.4",
        consequence="REJECT",
        severity="critical",
        confidence=0.94,
        graduated=True,
    )]


def main():
    traces = load_traces(ROOT / "legacy_sample" / "trace_log.json") if \
        (ROOT / "legacy_sample" / "trace_log.json").exists() else \
        [t for t in [] ]  # generated below if missing

    if not traces:
        print("No trace_log.json found — generating traces now.\n")
        generate_traces_out = generate_traces()
        import json
        (ROOT / "legacy_sample" / "trace_log.json").write_text(json.dumps(generate_traces_out))
        traces = load_traces(ROOT / "legacy_sample" / "trace_log.json")

    validated_invariants = get_validated_invariants(traces)
    graduated = [v for v in validated_invariants if v.graduated]
    print(f"Graduated invariants: {[v.invariant_id for v in graduated]}\n")

    oracles = [synthesize_oracle(v) for v in graduated]

    # Stage 4 — certify the (deliberately buggy) modernized implementation.
    run = certify(
        oracles=oracles,
        modern_fn=modern_loan_approval.evaluate_loan,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        domain_of=DOMAIN_OF,
    )
    print_report(run)

    # Stage 5 — simulate a drift check against the same (buggy) deployment.
    if os.getenv("MONGODB_ATLAS_URI"):
        check_drift(
            oracles=oracles,
            deployed_fn=modern_loan_approval.evaluate_loan,
            field_bounds=FIELD_BOUNDS,
            baseline_score=run.equivalence_score,
        )
    else:
        print("MONGODB_ATLAS_URI not set — skipping Stage 5 drift persistence "
              "(scoring logic itself has no Atlas dependency, only storage does).")


if __name__ == "__main__":
    main()
