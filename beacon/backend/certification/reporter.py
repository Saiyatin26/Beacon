"""Stage 4 — persists a CertificationRun to Atlas (certification_runs_col)
and formats it for console/dashboard display."""

from common.db import certification_runs_col
from common.models import CertificationRun


def save_run(run: CertificationRun) -> None:
    certification_runs_col().insert_one(run.model_dump())


def print_report(run: CertificationRun) -> None:
    print(f"\nBEHAVIORAL EQUIVALENCE REPORT — run {run.run_id}")
    print(f"Overall Equivalence Score: {run.equivalence_score * 100:.1f}%\n")

    if run.domain_scores:
        print("By domain:")
        for domain, score in run.domain_scores.items():
            print(f"  {domain:<28} {score * 100:.0f}%")
        print()

    print(f"Checked: {run.total_checked}   Violated: {run.total_violated}\n")

    for v in run.violations:
        print(f"Invariant #{v.invariant_id}")
        print(f"  Expected:       {v.expected}")
        print(f"  Legacy output:  {v.legacy_output}")
        print(f"  Modern output:  {v.modern_output}")
        print(f"  Counterexample: {v.counterexample}")
        print(f"  Confidence: {v.confidence:.2f}   Severity: {v.severity}\n")
