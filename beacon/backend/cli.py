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

from certification import (
    CertificationPolicy,
    CertificationStatus,
    certification_engine,
    certification_repository,
    generate_html_report,
    generate_markdown_report,
)
from certification.adapter_registry import adapter_registry
from oracle import registry


def cmd_certify(args):
    """Executes behavioral certification."""
    oracle_set = registry.get_oracle_set(args.oracle_set_id) if args.oracle_set_id else None
    if not oracle_set:
        print(f"Error: Valid --oracle-set-id must be provided.", file=sys.stderr)
        sys.exit(1)

    legacy_adp = adapter_registry.get_adapter(args.legacy_adapter)
    if not legacy_adp:
        print(f"Error: Legacy adapter '{args.legacy_adapter}' not found in registry.", file=sys.stderr)
        sys.exit(1)

    modern_adp = adapter_registry.get_adapter(args.modern_adapter)
    if not modern_adp:
        print(f"Error: Modern adapter '{args.modern_adapter}' not found in registry.", file=sys.stderr)
        sys.exit(1)

    policy = CertificationPolicy(
        min_equivalence_score=args.min_score,
        allow_warnings=args.allow_warnings,
    )

    from threshold.engine import ThresholdEngine
    from threshold.models import DifferenceMetric, ThresholdPolicy, ThresholdStrategy
    from threshold.persistence import threshold_persistence

    thresh_engine = ThresholdEngine()
    th_policy = threshold_persistence.get_policy(f"POL-{args.project_id}")
    if not th_policy:
        th_policy = ThresholdPolicy(
            policy_id=f"POL-{args.project_id}",
            version="1.0.0",
            metric=DifferenceMetric.ABSOLUTE_DIFF,
            strategy=ThresholdStrategy.FIXED,
            parameters={"value": 0.0},
        )
        threshold_persistence.save_policy(th_policy)

    threshold_res = thresh_engine.resolve_threshold(
        metric=th_policy.metric,
        policy=th_policy,
    )
    threshold_persistence.save_resolution(threshold_res)

    artifact = certification_engine.certify(
        project_id=args.project_id,
        legacy_adapter=legacy_adp,
        modern_adapter=modern_adp,
        oracle_set=oracle_set,
        policy=policy,
        threshold_resolution=threshold_res,
        n_samples=args.samples,
        seed=args.seed,
    )

    certification_repository.save_artifact(artifact)

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
    cert_parser.add_argument("--project-id", default="cert_project", help="Project identifier")
    cert_parser.add_argument("--legacy-adapter", required=True, help="Legacy adapter name in registry")
    cert_parser.add_argument("--modern-adapter", required=True, help="Modernized adapter name in registry")
    cert_parser.add_argument("--oracle-set-id", required=True, help="Frozen OracleSet ID")
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
