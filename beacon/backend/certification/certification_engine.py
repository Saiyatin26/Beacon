"""Phase 10 — Quantified Behavioral Equivalence Certification Engine.

Consumes Phase-8 frozen Oracle Sets and Phase-9 comparison evidence, verifies
integrity hashes, evaluates versioned Certification Policies, and generates
immutable cryptographic CertificationArtifact certificates.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Optional, Union
import uuid

from oracle.models import OracleDefinition, OracleSet
from oracle.serializer import compute_oracle_set_hash
from .adapters import ImplementationAdapter, LegacyAdapter, ModernizedAdapter
from .engine import CrossVersionCertificationEngine
from .input_generator import generate_certification_test_suite
from .models import (
    BehavioralRegression,
    CertificationArtifact,
    CertificationCase,
    CertificationInputSet,
    CertificationMetrics,
    CertificationPolicy,
    CertificationStatus,
    CertificationTestInput,
    CrossVersionCertificationReport,
    PerOracleCertificationSummary,
    compute_artifact_content_hash,
    compute_input_set_canonical_hash,
    verify_artifact_integrity,
    verify_input_set_integrity,
)
from .repository import certification_repository

logger = logging.getLogger(__name__)


class CertificationEngine:
    """Core Phase 10 Certification Engine."""

    def __init__(self, cross_version_engine: Optional[CrossVersionCertificationEngine] = None):
        self.cross_version_engine = cross_version_engine or CrossVersionCertificationEngine()

    def certify(
        self,
        project_id: str,
        legacy_adapter: ImplementationAdapter,
        modern_adapter: ImplementationAdapter,
        oracle_set: OracleSet,
        policy: Optional[CertificationPolicy] = None,
        test_inputs: Optional[list[CertificationTestInput]] = None,
        field_bounds: Optional[dict[str, tuple[float, float]]] = None,
        domain_of: Optional[dict[str, str]] = None,
        n_samples: int = 100,
        seed: int = 42,
    ) -> CertificationArtifact:
        """Executes full policy-driven behavioral certification and produces an immutable CertificationArtifact."""
        cert_policy = policy or CertificationPolicy()
        pol_hash = cert_policy.compute_hash()
        timestamp = datetime.now(timezone.utc).isoformat()
        cert_id = f"CERT-{uuid.uuid4().hex[:8]}"

        # 1. OracleSet Integrity and Content Hash Verification
        if not oracle_set.oracles:
            raise ValueError(f"OracleSet #{oracle_set.oracle_set_id} contains no oracles.")

        content_hashes = [o.content_hash for o in oracle_set.oracles]
        expected_set_hash = compute_oracle_set_hash(content_hashes)

        if expected_set_hash != oracle_set.oracle_set_hash:
            logger.error(
                f"OracleSet integrity failure: stored hash '{oracle_set.oracle_set_hash}' "
                f"does not match calculated hash '{expected_set_hash}'"
            )
            invalid_cert_id = f"CERT-ERR-{uuid.uuid4().hex[:8]}"
            temp_err = CertificationArtifact(
                certification_id=invalid_cert_id,
                project_id=project_id,
                legacy_version=legacy_adapter.version,
                modernized_version=modern_adapter.version,
                oracle_set_id=oracle_set.oracle_set_id,
                oracle_set_version=oracle_set.version,
                oracle_set_hash=oracle_set.oracle_set_hash,
                input_set_id="",
                input_set_hash="",
                certification_policy_id=cert_policy.policy_id,
                certification_policy_version=cert_policy.version,
                certification_policy_hash=pol_hash,
                certification_engine_version="1.0.0",
                timestamp=timestamp,
                status=CertificationStatus.ORACLE_SET_INVALID,
                certified=False,
                score=0.0,
                metrics=CertificationMetrics(),
                domain_scores={},
                oracle_summaries=[],
                regressions=[],
                reference_inconsistencies=[],
                warnings=[],
                blocking_reasons=["OracleSet integrity verification failed: hash mismatch"],
                content_hash="",
            )
            err_artifact = temp_err.model_copy(update={"content_hash": compute_artifact_content_hash(temp_err)})
            return certification_repository.save_artifact(err_artifact)

        # 2. Input Suite Resolution and Input Set Hashing
        from .input_generator import _extract_predicates

        default_base_bounds = {
            "credit_score": (400.0, 820.0),
            "debt_ratio": (0.0, 0.9),
            "annual_income": (10_000.0, 150_000.0),
        }

        if field_bounds:
            bounds = dict(field_bounds)
        else:
            bounds = dict(default_base_bounds)

        # Discover any additional variables in oracle conditions
        for orc in oracle_set.oracles:
            for pred in _extract_predicates(orc.condition):
                if pred.variable not in bounds:
                    val = pred.value
                    if isinstance(val, (int, float)):
                        if val > 0:
                            bounds[pred.variable] = (0.0, float(val * 2.0))
                        else:
                            bounds[pred.variable] = (float(val - 100.0), float(val + 100.0))
                    else:
                        bounds[pred.variable] = (0.0, 100.0)

        inputs = test_inputs
        if inputs is None:
            inputs = generate_certification_test_suite(
                oracles=oracle_set.oracles,
                field_bounds=bounds,
                n_diverse_samples=n_samples,
                seed=seed,
            )

        # Compute complete canonical dataset hash
        input_set_hash = compute_input_set_canonical_hash(inputs)
        input_set_id = f"INPSET-{input_set_hash[:8]}"

        input_set = CertificationInputSet(
            input_set_id=input_set_id,
            version=1,
            generator_type="deterministic_phase11",
            generator_config={"field_bounds": bounds, "n_samples": n_samples},
            seed=seed,
            input_count=len(inputs),
            canonical_hash=input_set_hash,
            created_at=timestamp,
            provenance={}
        )

        # 3. Cross-Version Execution via Phase 9 Engine
        phase9_report: CrossVersionCertificationReport = self.cross_version_engine.certify_equivalence(
            oracles=oracle_set,
            legacy_adapter=legacy_adapter,
            modern_adapter=modern_adapter,
            test_inputs=inputs,
            field_bounds=bounds,
            domain_of=domain_of,
            n_samples=n_samples,
            seed=seed,
        )

        # 4. Compile Per-Oracle Summaries and Certification Cases
        oracle_summaries: list[PerOracleCertificationSummary] = []
        critical_failures_count = 0
        non_critical_failures_count = 0
        oracles_exercised_count = 0

        # Group regressions by oracle_id and input_id
        regs_by_oracle: dict[str, list[BehavioralRegression]] = {}
        regs_by_input: dict[str, list[BehavioralRegression]] = {}
        for reg in phase9_report.regressions:
            regs_by_oracle.setdefault(reg.oracle_id, []).append(reg)
            regs_by_input.setdefault(reg.input_id, []).append(reg)

        cases_to_save: list[CertificationCase] = []
        for i, comp_rec in enumerate(phase9_report.comparison_records):
            input_regs = regs_by_input.get(comp_rec.input_id, [])
            violated_oracles = [r.oracle_id for r in input_regs]

            sev = "none"
            if input_regs:
                if any(r.severity == "critical" for r in input_regs):
                    sev = "critical"
                elif any(r.severity == "high" for r in input_regs):
                    sev = "high"
                elif any(r.severity == "medium" for r in input_regs):
                    sev = "medium"
                else:
                    sev = "low"

            leg_out = (
                json.dumps(comp_rec.legacy_observation.raw_outputs, sort_keys=True, separators=(",", ":"))
                if comp_rec.legacy_observation
                else "{}"
            )
            mod_out = (
                json.dumps(comp_rec.modern_observation.raw_outputs, sort_keys=True, separators=(",", ":"))
                if comp_rec.modern_observation
                else "{}"
            )
            exec_time = 0.0
            if comp_rec.legacy_observation:
                exec_time += comp_rec.legacy_observation.execution_time_ms
            if comp_rec.modern_observation:
                exec_time += comp_rec.modern_observation.execution_time_ms

            case = CertificationCase(
                case_id=f"CASE-{cert_id}-{i}",
                run_id=cert_id,
                input_set_id=input_set_id,
                case_index=i,
                input_json=json.dumps(comp_rec.input_values, sort_keys=True, separators=(",", ":")),
                input_hash=comp_rec.input_id,
                legacy_output_json=leg_out,
                modern_output_json=mod_out,
                execution_time_ms=exec_time,
                oracle_result="VIOLATED" if input_regs else "PASS",
                classification=comp_rec.equivalence_outcome,
                severity=sev,
                violated_oracle_ids=violated_oracles,
            )
            cases_to_save.append(case)

        # Reproducibility Verification
        reproducibility_valid = True
        reproducibility_reasons = []

        if len(cases_to_save) != len(inputs) or len(cases_to_save) != input_set.input_count:
            reproducibility_valid = False
            reproducibility_reasons.append(
                f"Evaluated input count ({len(inputs)}) does not match case count ({len(cases_to_save)})"
            )

        for c in cases_to_save:
            if c.run_id != cert_id or c.input_set_id != input_set_id:
                reproducibility_valid = False
                reproducibility_reasons.append(f"Case #{c.case_index} reference mismatch (run_id/input_set_id)")
            if not c.input_json or not c.input_hash:
                reproducibility_valid = False
                reproducibility_reasons.append(f"Case #{c.case_index} missing input data or hash")
            if c.legacy_output_json is None or c.modern_output_json is None:
                reproducibility_valid = False
                reproducibility_reasons.append(f"Case #{c.case_index} missing execution outputs")
            if not c.oracle_result or not c.classification:
                reproducibility_valid = False
                reproducibility_reasons.append(f"Case #{c.case_index} missing oracle result or classification")

        reconstructed_hash = compute_input_set_canonical_hash(cases_to_save)
        if reconstructed_hash != input_set.canonical_hash:
            reproducibility_valid = False
            reproducibility_reasons.append(
                f"Reconstructed input set hash mismatch: expected {input_set.canonical_hash}, got {reconstructed_hash}"
            )

        repro_state = "FULLY_REPRODUCIBLE" if reproducibility_valid else "LEGACY_PARTIAL"


        for oracle in oracle_set.oracles:
            m = phase9_report.oracle_metrics.get(oracle.oracle_id)
            if not m:
                continue

            # Determine oracle status
            if m.modern_regressions > 0:
                orc_status = "REGRESSION"
                if oracle.severity in ("critical", "high"):
                    critical_failures_count += m.modern_regressions
                else:
                    non_critical_failures_count += m.modern_regressions
            elif m.reference_inconsistencies > 0:
                orc_status = "REFERENCE_INCONSISTENT"
            elif m.mutual_violations > 0:
                orc_status = "MUTUAL_VIOLATION"
            elif m.execution_errors > 0 or m.invalid_inputs > 0:
                orc_status = "ERROR"
            elif m.applicable_probes < cert_policy.min_applicable_probes_per_oracle:
                orc_status = "INSUFFICIENT_COVERAGE"
            else:
                orc_status = "PASS"

            exercised_probes = m.matching_probes + m.modern_regressions + m.reference_inconsistencies + m.mutual_violations
            if exercised_probes >= cert_policy.min_applicable_probes_per_oracle:
                oracles_exercised_count += 1

            oracle_summaries.append(PerOracleCertificationSummary(
                oracle_id=oracle.oracle_id,
                oracle_version=oracle.version,
                oracle_hash=oracle.content_hash,
                severity=oracle.severity,
                confidence=oracle.confidence,
                domain=oracle.domain,
                condition_str=oracle.canonical_condition,
                consequence_str=f"{oracle.consequence.variable} == '{oracle.consequence.value}'",
                total_probes=m.total_probes,
                applicable_probes=m.applicable_probes,
                matching_probes=m.matching_probes,
                legacy_passes=m.legacy_passes,
                modern_passes=m.modern_passes,
                modern_regressions=m.modern_regressions,
                reference_inconsistencies=m.reference_inconsistencies,
                mutual_violations=m.mutual_violations,
                invalid_inputs=m.invalid_inputs,
                execution_errors=m.execution_errors,
                not_applicable=m.not_applicable,
                oracle_equivalence_rate=m.oracle_equivalence_rate,
                oracle_status=orc_status,
                counterexamples=regs_by_oracle.get(oracle.oracle_id, []),
            ))

        # 5. Compile Quantitative Certification Metrics
        oracle_count = len(oracle_set.oracles)
        coverage_pct = round(oracles_exercised_count / oracle_count, 4) if oracle_count > 0 else 0.0

        metrics = CertificationMetrics(
            total_inputs=phase9_report.total_probes,
            applicable_inputs=phase9_report.total_applicable_probes,
            not_applicable=phase9_report.total_not_applicable,
            matching_probes=phase9_report.total_matching_probes,
            modern_regressions=phase9_report.total_regressions,
            reference_inconsistencies=phase9_report.total_reference_inconsistencies,
            mutual_violations=phase9_report.total_mutual_violations,
            invalid_inputs=phase9_report.total_invalid_inputs,
            execution_errors=phase9_report.total_execution_errors,
            critical_failures=critical_failures_count,
            non_critical_failures=non_critical_failures_count,
            oracle_count=oracle_count,
            oracles_exercised=oracles_exercised_count,
            oracle_coverage_pct=coverage_pct,
            overall_equivalence_score=phase9_report.overall_equivalence_score,
        )

        # 6. Apply Certification Policy Decision Flow
        blocking_reasons: list[str] = []
        warnings: list[str] = []
        final_status: CertificationStatus = CertificationStatus.CERTIFIED

        # Flow Step 1: Coverage Check
        if coverage_pct < cert_policy.min_oracle_coverage:
            blocking_reasons.append(
                f"Insufficient oracle coverage: {oracles_exercised_count}/{oracle_count} oracles exercised "
                f"({coverage_pct * 100:.1f}% vs required {cert_policy.min_oracle_coverage * 100:.1f}%)"
            )
            final_status = CertificationStatus.INSUFFICIENT_COVERAGE

        # Flow Step 2: Reference Inconsistency Check
        elif cert_policy.block_on_reference_inconsistent and metrics.reference_inconsistencies > 0:
            blocking_reasons.append(
                f"Reference implementation contradicts frozen validated oracles ({metrics.reference_inconsistencies} occurrences)"
            )
            final_status = CertificationStatus.REFERENCE_INCONSISTENT

        # Flow Step 3: Modernized Critical Regression / Mutual Violation / Low Score Check
        elif cert_policy.block_on_critical_regression and metrics.critical_failures > 0:
            blocking_reasons.append(
                f"Modernized implementation contains {metrics.critical_failures} critical behavioral regressions"
            )
            final_status = CertificationStatus.NOT_CERTIFIED

        elif cert_policy.block_on_mutual_violation and metrics.mutual_violations > 0:
            blocking_reasons.append(
                f"Mutual behavioral violation detected on {metrics.mutual_violations} probes"
            )
            final_status = CertificationStatus.NOT_CERTIFIED

        elif metrics.overall_equivalence_score < cert_policy.min_equivalence_score:
            blocking_reasons.append(
                f"Equivalence score ({metrics.overall_equivalence_score * 100:.1f}%) below policy threshold "
                f"({cert_policy.min_equivalence_score * 100:.1f}%)"
            )
            final_status = CertificationStatus.NOT_CERTIFIED

        elif metrics.execution_errors > cert_policy.max_permitted_execution_errors:
            blocking_reasons.append(
                f"Execution errors ({metrics.execution_errors}) exceed policy limit ({cert_policy.max_permitted_execution_errors})"
            )
            final_status = CertificationStatus.NOT_CERTIFIED

        elif metrics.invalid_inputs > cert_policy.max_permitted_invalid_inputs:
            blocking_reasons.append(
                f"Invalid inputs ({metrics.invalid_inputs}) exceed policy limit ({cert_policy.max_permitted_invalid_inputs})"
            )
            final_status = CertificationStatus.NOT_CERTIFIED

        # Flow Step 4: Non-Critical Warnings Check
        elif metrics.non_critical_failures > 0:
            warnings.append(f"{metrics.non_critical_failures} non-critical behavioral regressions detected")
            if cert_policy.allow_warnings:
                final_status = CertificationStatus.CERTIFIED_WITH_WARNINGS
            else:
                blocking_reasons.append("Non-critical regressions disallowed by current policy")
                final_status = CertificationStatus.NOT_CERTIFIED

        # Flow Step 5: Full Pass
        else:
            final_status = CertificationStatus.CERTIFIED

        is_certified = final_status in (CertificationStatus.CERTIFIED, CertificationStatus.CERTIFIED_WITH_WARNINGS)

        # 7. Create Immutable Artifact and Compute Canonical Content Hash
        temp_artifact = CertificationArtifact(
            certification_id=cert_id,
            project_id=project_id,
            legacy_version=legacy_adapter.version,
            modernized_version=modern_adapter.version,
            oracle_set_id=oracle_set.oracle_set_id,
            oracle_set_version=oracle_set.version,
            oracle_set_hash=oracle_set.oracle_set_hash,
            input_set_id=input_set_id,
            input_set_hash=input_set_hash,
            certification_policy_id=cert_policy.policy_id,
            certification_policy_version=cert_policy.version,
            certification_policy_hash=pol_hash,
            certification_engine_version="1.0.0",
            timestamp=timestamp,
            reproducibility_state=repro_state,
            status=final_status,
            certified=is_certified,
            score=metrics.overall_equivalence_score,
            metrics=metrics,
            domain_scores=phase9_report.domain_scores,
            oracle_summaries=oracle_summaries,
            regressions=phase9_report.regressions,
            reference_inconsistencies=phase9_report.reference_inconsistencies,
            warnings=warnings,
            blocking_reasons=blocking_reasons,
            content_hash="",
        )

        cert_content_hash = compute_artifact_content_hash(temp_artifact)
        artifact = temp_artifact.model_copy(update={"content_hash": cert_content_hash})

        return certification_repository.save_certification_run_atomic(input_set, cases_to_save, artifact)


# Module-level default certification engine singleton
certification_engine = CertificationEngine()
