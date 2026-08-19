"""Phase 9 — Cross-Version Behavioral Equivalence Certification Engine.

Executes shared test inputs across Legacy and Modernized adapters, evaluates
both against Phase-8 Language-Independent Oracles, classifies 4-way behavioral
outcomes, produces regression counterexamples, and aggregates equivalence metrics.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Optional, Union
import uuid

from common.config import settings
from oracle.evaluator import evaluate_oracle
from oracle.models import OracleDefinition, OracleSet
from .adapters import ImplementationAdapter, LegacyAdapter, ModernizedAdapter
from .input_generator import generate_certification_test_suite
from .models import (
    BehavioralRegression,
    CertificationTestInput,
    ComparisonRecord,
    CrossVersionCertificationReport,
    OracleEquivalenceMetrics,
)

logger = logging.getLogger(__name__)


class CrossVersionCertificationEngine:
    """Core Certification Engine for Cross-Version Behavioral Equivalence."""

    def certify_equivalence(
        self,
        oracles: Union[OracleSet, list[OracleDefinition]],
        legacy_adapter: ImplementationAdapter,
        modern_adapter: ImplementationAdapter,
        test_inputs: Optional[list[CertificationTestInput]] = None,
        field_bounds: Optional[dict[str, tuple[float, float]]] = None,
        domain_of: Optional[dict[str, str]] = None,
        n_samples: int = 100,
        seed: int = 42,
    ) -> CrossVersionCertificationReport:
        """Executes full cross-version equivalence certification and builds a comprehensive report."""
        # 1. Resolve Oracles and OracleSet Metadata
        oracle_set_id = ""
        oracle_set_hash = ""
        resolved_oracles: list[OracleDefinition] = []

        if isinstance(oracles, OracleSet):
            oracle_set_id = oracles.oracle_set_id
            oracle_set_hash = oracles.oracle_set_hash
            resolved_oracles = oracles.oracles
        else:
            resolved_oracles = list(oracles)
            if resolved_oracles:
                from oracle.serializer import compute_oracle_set_hash
                oracle_set_hash = compute_oracle_set_hash([o.content_hash for o in resolved_oracles])

        # 2. Build or Use Shared Test Input Suite
        bounds = field_bounds or {
            "credit_score": (400, 820),
            "debt_ratio": (0.0, 0.9),
            "annual_income": (10_000, 150_000),
        }

        inputs = test_inputs
        if inputs is None:
            inputs = generate_certification_test_suite(
                oracles=resolved_oracles,
                field_bounds=bounds,
                n_diverse_samples=n_samples,
                seed=seed,
            )

        # 3. Side-by-Side Execution & Evaluation Loop
        comparison_records: list[ComparisonRecord] = []
        regressions: list[BehavioralRegression] = []
        reference_inconsistencies: list[dict[str, Any]] = []
        metrics_by_oracle: dict[str, OracleEquivalenceMetrics] = {
            o.oracle_id: OracleEquivalenceMetrics(oracle_id=o.oracle_id) for o in resolved_oracles
        }

        total_probes_count = 0
        total_applicable_count = 0

        for oracle in resolved_oracles:
            m = metrics_by_oracle[oracle.oracle_id]

            for test_inp in inputs:
                total_probes_count += 1
                m.total_probes += 1

                # Execute Legacy and Modern Adapters on identical input
                legacy_obs = legacy_adapter.execute(test_inp.values, input_id=test_inp.input_id)
                modern_obs = modern_adapter.execute(test_inp.values, input_id=test_inp.input_id)

                # Evaluate observations against Phase-8 Oracle AST
                legacy_eval = evaluate_oracle(
                    oracle,
                    inputs=legacy_obs.normalized_inputs,
                    outputs=legacy_obs.normalized_outputs,
                )
                modern_eval = evaluate_oracle(
                    oracle,
                    inputs=modern_obs.normalized_inputs,
                    outputs=modern_obs.normalized_outputs,
                )

                # Four-Way Behavioral Classification
                outcome = "NOT_APPLICABLE"

                if legacy_eval.status == "NOT_APPLICABLE" and modern_eval.status == "NOT_APPLICABLE":
                    outcome = "NOT_APPLICABLE"
                    m.not_applicable += 1

                elif (
                    legacy_eval.status in ("EVALUATION_ERROR", "INVALID_INPUT")
                    or modern_eval.status in ("EVALUATION_ERROR", "INVALID_INPUT")
                    or legacy_obs.execution_status == "EXCEPTION"
                    or modern_obs.execution_status == "EXCEPTION"
                ):
                    outcome = "EXECUTION_ERROR"
                    m.execution_errors += 1
                    total_applicable_count += 1
                    m.applicable_probes += 1

                elif legacy_eval.status == "PASS" and modern_eval.status == "PASS":
                    outcome = "MATCH_PASS"
                    m.applicable_probes += 1
                    total_applicable_count += 1
                    m.legacy_passes += 1
                    m.modern_passes += 1

                elif legacy_eval.status == "PASS" and modern_eval.status == "FAIL":
                    outcome = "MODERN_REGRESSION"
                    m.applicable_probes += 1
                    total_applicable_count += 1
                    m.legacy_passes += 1
                    m.modern_regressions += 1

                    # Generate concrete BehavioralRegression counterexample
                    reg_id = f"REG-{uuid.uuid4().hex[:8]}"
                    reg = BehavioralRegression(
                        regression_id=reg_id,
                        oracle_id=oracle.oracle_id,
                        oracle_version=oracle.version,
                        input_id=test_inp.input_id,
                        input_values=test_inp.values,
                        expected_behavior=oracle.consequence.value,
                        legacy_output=legacy_obs.raw_outputs.get(oracle.consequence.variable, legacy_obs.raw_outputs),
                        modern_output=modern_obs.raw_outputs.get(oracle.consequence.variable, modern_obs.raw_outputs),
                        failed_assertion=f"Expected {oracle.consequence.variable} == '{oracle.consequence.value}'",
                        legacy_version=legacy_adapter.version,
                        modern_version=modern_adapter.version,
                        severity=oracle.severity,
                        domain=oracle.domain,
                        confidence=oracle.confidence,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                    regressions.append(reg)

                elif legacy_eval.status == "FAIL" and modern_eval.status == "PASS":
                    outcome = "REFERENCE_INCONSISTENT"
                    m.applicable_probes += 1
                    total_applicable_count += 1
                    m.modern_passes += 1
                    m.reference_inconsistencies += 1

                    reference_inconsistencies.append({
                        "oracle_id": oracle.oracle_id,
                        "input_id": test_inp.input_id,
                        "input_values": test_inp.values,
                        "legacy_output": legacy_obs.raw_outputs,
                        "expected": oracle.consequence.value,
                        "notice": "Legacy reference violated the frozen validated oracle.",
                    })

                elif legacy_eval.status == "FAIL" and modern_eval.status == "FAIL":
                    outcome = "MUTUAL_VIOLATION"
                    m.applicable_probes += 1
                    total_applicable_count += 1
                    m.mutual_violations += 1

                # Record granular comparison record for audit trail
                comp_rec = ComparisonRecord(
                    comparison_id=f"CMP-{uuid.uuid4().hex[:8]}",
                    oracle_id=oracle.oracle_id,
                    oracle_version=oracle.version,
                    oracle_set_hash=oracle_set_hash,
                    input_id=test_inp.input_id,
                    input_values=test_inp.values,
                    legacy_observation=legacy_obs,
                    modern_observation=modern_obs,
                    legacy_eval_report=legacy_eval,
                    modern_eval_report=modern_eval,
                    equivalence_outcome=outcome,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                comparison_records.append(comp_rec)

            # Compute individual oracle equivalence rate
            if m.applicable_probes > 0:
                m.oracle_equivalence_rate = round(
                    max(0.0, (m.applicable_probes - m.modern_regressions - m.execution_errors) / m.applicable_probes), 4
                )
            else:
                m.oracle_equivalence_rate = 1.0

        # 4. Overall Weighted Equivalence Score Calculation
        numerator = 0.0
        denominator = 0.0

        for oracle in resolved_oracles:
            m = metrics_by_oracle[oracle.oracle_id]
            sev_weight = settings.severity_weights.get(oracle.severity, 2.0)
            weight = sev_weight * oracle.confidence

            # Pass indicator is 1.0 if zero regressions and at least one pass, else ratio
            pass_i = 1.0 if (m.applicable_probes > 0 and m.modern_regressions == 0 and m.execution_errors == 0) else m.oracle_equivalence_rate

            numerator += weight * pass_i
            denominator += weight

        overall_score = round(numerator / denominator, 4) if denominator > 0 else 1.0

        # 5. Domain Breakdown
        domain_mapping = domain_of or {}
        domain_accum: dict[str, tuple[float, float]] = {}

        for oracle in resolved_oracles:
            dom = domain_mapping.get(oracle.oracle_id, oracle.domain)
            m = metrics_by_oracle[oracle.oracle_id]
            sev_weight = settings.severity_weights.get(oracle.severity, 2.0)
            weight = sev_weight * oracle.confidence
            pass_i = 1.0 if (m.applicable_probes > 0 and m.modern_regressions == 0 and m.execution_errors == 0) else m.oracle_equivalence_rate

            curr_num, curr_den = domain_accum.get(dom, (0.0, 0.0))
            domain_accum[dom] = (curr_num + weight * pass_i, curr_den + weight)

        domain_scores = {
            dom: round(num / den, 4) if den > 0 else 1.0
            for dom, (num, den) in domain_accum.items()
        }

        # 6. Build Final Certification Report
        cert_id = f"RUN-{uuid.uuid4().hex[:8]}"
        is_certified = (overall_score >= settings.confidence_threshold) and (len(regressions) == 0)

        return CrossVersionCertificationReport(
            certification_id=cert_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            oracle_set_id=oracle_set_id,
            oracle_set_hash=oracle_set_hash,
            legacy_version=legacy_adapter.version,
            modern_version=modern_adapter.version,
            overall_equivalence_score=overall_score,
            domain_scores=domain_scores,
            oracle_metrics=metrics_by_oracle,
            regressions=regressions,
            reference_inconsistencies=reference_inconsistencies,
            comparison_records=comparison_records,
            total_probes=total_probes_count,
            total_applicable_probes=total_applicable_count,
            total_regressions=len(regressions),
            total_reference_inconsistencies=len(reference_inconsistencies),
            certified=is_certified,
        )


certification_engine = CrossVersionCertificationEngine()
