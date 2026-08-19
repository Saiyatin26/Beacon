"""Phase 10 — BEACON Command Line Interface (CLI).

Enables running deterministic behavioral certifications, viewing certificates,
and checking post-migration drift from the terminal.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

from certification import (
    CertificationPolicy,
    CertificationStatus,
    LegacyAdapter,
    ModernizedAdapter,
    certification_engine,
    certification_repository,
    generate_html_report,
    generate_markdown_report,
)
from oracle import registry, synthesize_oracle
from ingestion.legacy_parser import load_source, extract_ast_structure
from ingestion.trace_loader import load_traces
from evidence.builder import build_evidence_package
from mining.pipeline import run_mining_pipeline
import legacy_loan_approval
import modern_loan_approval
from generate_traces import generate_traces


def _setup_demo_oracles() -> str:
    """Helper to initialize demo oracles and freeze an OracleSet if none exist."""
    sets = registry.list_oracle_sets()
    if sets:
        return sets[0].oracle_set_id

    legacy_file = str(ROOT / "legacy_sample" / "legacy_loan_approval.py")
    static_result = extract_ast_structure(legacy_file)

    trace_file = ROOT / "legacy_sample" / "trace_log.json"
    if not trace_file.exists():
        trace_file.write_text(json.dumps(generate_traces(n_random=500), indent=2))
    traces = load_traces(trace_file)

    evidence_pkg = build_evidence_package(static_result, traces)
    graduated, _ = run_mining_pipeline(
        evidence_package=evidence_pkg,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds={"credit_score": (400, 820), "debt_ratio": (0.0, 0.9), "annual_income": (10000, 150000)},
        use_atlas=False,
        use_llm=False,
    )

    oracles = [synthesize_oracle(inv) for inv in graduated]
    for o in oracles:
        registry.register_oracle(o)

    oracle_set = registry.create_oracle_set(
        name="LoanApprovalCoreSuite",
        oracle_ids=[o.oracle_id for o in oracles],
        domain="loan_approval",
    )
    return oracle_set.oracle_set_id


def cmd_certify(args):
    """Executes behavioral certification."""
    set_id = args.oracle_set_id or _setup_demo_oracles()
    oracle_set = registry.get_oracle_set(set_id)
    if not oracle_set:
        print(f"Error: OracleSet '{set_id}' not found.", file=sys.stderr)
        sys.exit(1)

    legacy_adp = LegacyAdapter(target_fn=legacy_loan_approval.evaluate_loan, name="legacy_ref", version=args.legacy_version)
    modern_fn = legacy_loan_approval.evaluate_loan if args.implementation == "equivalent" else modern_loan_approval.evaluate_loan
    modern_adp = ModernizedAdapter(target_fn=modern_fn, name="modern_cand", version=args.modernized_version)

    policy = CertificationPolicy(
        min_equivalence_score=args.min_score,
        allow_warnings=args.allow_warnings,
    )

    artifact = certification_engine.certify(
        project_id=args.project_id,
        legacy_adapter=legacy_adp,
        modern_adapter=modern_adp,
        oracle_set=oracle_set,
        policy=policy,
        n_samples=args.samples,
        seed=args.seed,
    )

    if args.format == "json":
        print(artifact.model_dump_json(indent=2))
    elif args.format == "html":
        print(generate_html_report(artifact))
    else:
        print(generate_markdown_report(artifact))


def main():
    parser = argparse.ArgumentParser(prog="beacon", description="BEACON Behavioral Equivalence Certification CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    cert_parser = subparsers.add_parser("certify", help="Run behavioral equivalence certification")
    cert_parser.add_argument("--project-id", default="loan_approval_project", help="Project identifier")
    cert_parser.add_argument("--legacy-version", default="1.0.0", help="Legacy implementation version")
    cert_parser.add_argument("--modernized-version", default="2.0.0", help="Modernized implementation version")
    cert_parser.add_argument("--oracle-set-id", help="Frozen OracleSet ID")
    cert_parser.add_argument("--implementation", choices=["equivalent", "buggy"], default="buggy", help="Implementation target")
    cert_parser.add_argument("--format", choices=["text", "json", "html"], default="text", help="Output format")
    cert_parser.add_argument("--samples", type=int, default=50, help="Number of test samples")
    cert_parser.add_argument("--min-score", type=float, default=0.80, help="Minimum certification threshold")
    cert_parser.add_argument("--allow-warnings", action="store_true", help="Allow non-critical warnings")
    cert_parser.add_argument("--seed", type=int, default=42, help="Deterministic seed")

    args = parser.parse_args()
    if args.command == "certify":
        cmd_certify(args)


if __name__ == "__main__":
    main()
