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
    CertificationContext,
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
from ingestion.audit import audit_logger, AuditAction
from operations.logging_config import log_operational_event

logger = logging.getLogger(__name__)


class CertificationEngine:
    """Core Phase 10 Certification Engine."""

    def __init__(self, cross_version_engine: Optional[CrossVersionCertificationEngine] = None):
        self.cross_version_engine = cross_version_engine or CrossVersionCertificationEngine()

    def certify(
        self,
        project_id: str = "default",
        legacy_adapter: Optional[ImplementationAdapter] = None,
        modern_adapter: Optional[ImplementationAdapter] = None,
        reference_adapter: Optional[ImplementationAdapter] = None,
        target_adapter: Optional[ImplementationAdapter] = None,
        modernized_adapter: Optional[ImplementationAdapter] = None,
        candidate_adapter: Optional[ImplementationAdapter] = None,
        application_id: Optional[str] = None,
        oracle_set: Optional[OracleSet] = None,
        policy: Optional[CertificationPolicy] = None,
        test_inputs: Optional[list[CertificationTestInput]] = None,
        field_bounds: Optional[dict[str, tuple[float, float]]] = None,
        domain_of: Optional[dict[str, str]] = None,
        context: Optional[CertificationContext] = None,
        threshold_resolution: Optional[Any] = None,
        n_samples: int = 100,
        seed: int = 42,
    ) -> CertificationArtifact:
        """Executes full policy-driven behavioral certification and produces an immutable CertificationArtifact."""
        legacy_adapter = legacy_adapter or reference_adapter
        modern_adapter = modern_adapter or target_adapter or modernized_adapter or candidate_adapter
        if application_id and project_id == "default":
            project_id = application_id

        if threshold_resolution and context:
            context.threshold_resolution_id = getattr(threshold_resolution, "resolution_id", None)
            context.threshold_resolution_fingerprint = getattr(threshold_resolution, "fingerprint", None)

        cert_policy = policy or CertificationPolicy()
        pol_hash = cert_policy.compute_hash()
        timestamp = datetime.now(timezone.utc).isoformat()
        cert_id = f"CERT-{uuid.uuid4().hex[:8]}"

        log_operational_event(
            event="certification_engine_started",
            logger_name="beacon.execution",
            operation="CERTIFICATION",
            step="ENGINE",
            certification_run_id=cert_id,
            benchmark_id=project_id,
            evaluation_mode=getattr(context, "evaluation_mode", "CONTROLLED") if context else "CONTROLLED",
            target_variant=getattr(context, "modernization_variant_id", "") if context else "",
            oracles=len(oracle_set.oracles),
            message=f"[CERTIFICATION ENGINE] START | run={cert_id} | oracles={len(oracle_set.oracles)}",
        )

        audit_logger.log(
            project_id=project_id,
            action=AuditAction.CERTIFICATION_START,
            status="INFO",
            certification_id=cert_id,
            details={
                "legacy_version": getattr(legacy_adapter, "version", "1.0.0"),
                "modernized_version": getattr(modern_adapter, "version", "2.0.0"),
                "oracle_set_id": getattr(oracle_set, "oracle_set_id", ""),
                "policy_id": cert_policy.policy_id,
                "min_equivalence_score": cert_policy.min_equivalence_score,
                "min_oracle_coverage": cert_policy.min_oracle_coverage,
            },
        )

        # 1. OracleSet Integrity and Content Hash Verification
        if not oracle_set.oracles:
            logger.warning(
                f"OracleSet #{oracle_set.oracle_set_id} contains no oracles. "
                "Behavioral equivalence coverage is insufficient to certify."
            )
            empty_cert_id = cert_id
            ic_context = context or CertificationContext(
                benchmark_id=project_id,
                benchmark_version="1.0.0",
                benchmark_name=project_id,
                benchmark_provenance="CONTROLLED",
                evaluation_mode="CONTROLLED",
                modernization_variant_id=getattr(modern_adapter, "name", "modern_equiv"),
                modernization_variant_name=getattr(modern_adapter, "name", "Modernized Implementation"),
                legacy_implementation_id=getattr(legacy_adapter, "name", "legacy"),
                modernized_implementation_id=getattr(modern_adapter, "name", "modern"),
            )
            ic_context.policy_id = cert_policy.policy_id
            ic_context.policy_version = getattr(cert_policy, "version", 1)
            ic_context.policy_hash = pol_hash
            ic_context.policy_min_equivalence_score = cert_policy.min_equivalence_score
            ic_context.policy_min_oracle_coverage = cert_policy.min_oracle_coverage
            ic_context.policy_min_applicable_probes_per_oracle = cert_policy.min_applicable_probes_per_oracle
            ic_context.policy_allow_warnings = cert_policy.allow_warnings
            ic_context.policy_block_on_critical_regression = cert_policy.block_on_critical_regression
            ic_context.policy_block_on_reference_inconsistent = cert_policy.block_on_reference_inconsistent
            ic_context.policy_block_on_mutual_violation = cert_policy.block_on_mutual_violation
            ic_context.policy_rules = cert_policy.model_dump(mode="json")
            ic_context.certification_run_id = empty_cert_id
            ic_context.run_timestamp = timestamp
            ic_context.run_status = "INSUFFICIENT_COVERAGE"

            temp_ic = CertificationArtifact(
                certification_id=empty_cert_id,
                project_id=project_id,
                legacy_version=legacy_adapter.version,
                modernized_version=modern_adapter.version,
                oracle_set_id=oracle_set.oracle_set_id,
                oracle_set_version=getattr(oracle_set, "version", "1.0.0"),
                oracle_set_hash=oracle_set.oracle_set_hash,
                input_set_id="",
                input_set_hash="",
                certification_policy_id=cert_policy.policy_id,
                certification_policy_version=cert_policy.version,
                certification_policy_hash=pol_hash,
                certification_engine_version="1.0.0",
                timestamp=timestamp,
                status=CertificationStatus.INSUFFICIENT_COVERAGE,
                certified=False,
                score=0.0,
                metrics=CertificationMetrics(
                    unique_input_count=len(test_inputs) if test_inputs else 0,
                    oracle_count=0,
                    oracle_coverage_pct=0.0,
                ),
                domain_scores={},
                oracle_summaries=[],
                regressions=[],
                reference_inconsistencies=[],
                warnings=[],
                blocking_reasons=["Insufficient oracle coverage: 0 oracles available to evaluate behavioral equivalence"],
                content_hash="",
                context=ic_context,
            )
            ic_hash = compute_artifact_content_hash(temp_ic)
            ic_context.certification_artifact_hash = ic_hash
            ic_artifact = temp_ic.model_copy(update={"content_hash": ic_hash, "context": ic_context})

            audit_logger.log(
                project_id=project_id,
                action=AuditAction.CERTIFICATION_COMPLETE,
                status="INFO",
                certification_id=empty_cert_id,
                details={
                    "status": "INSUFFICIENT_COVERAGE",
                    "score": 0.0,
                    "reason": "0 oracles available",
                },
            )
            log_operational_event(
                event="certification_policy_decision",
                logger_name="beacon.execution",
                operation="CERTIFICATION",
                step="POLICY",
                certification_run_id=empty_cert_id,
                outcome="INSUFFICIENT_COVERAGE",
                message="[PHASE 09] DECISION | result=INSUFFICIENT_COVERAGE | reason=no oracles",
            )
            return certification_repository.save_artifact(ic_artifact)

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
            log_operational_event(
                event="oracle_set_integrity_failed",
                level=logging.ERROR,
                logger_name="beacon.execution",
                operation="CERTIFICATION",
                step="ORACLE_SET",
                certification_run_id=invalid_cert_id,
                outcome="ABORTED",
                message="[PHASE 05] ERROR | OracleSet hash verification failed | certification aborted",
            )
            return certification_repository.save_artifact(err_artifact)

        log_operational_event(
            event="oracle_set_validated",
            logger_name="beacon.execution",
            operation="CERTIFICATION",
            step="ORACLE_SET",
            phase="05",
            certification_run_id=cert_id,
            oracles=len(oracle_set.oracles),
            message=f"[PHASE 05] COMPLETE | OracleSet={oracle_set.oracle_set_id} | oracles={len(oracle_set.oracles)}",
        )

        # 2. Input Suite Resolution and Input Set Hashing
        from .input_generator import _extract_predicates

        bounds = dict(field_bounds) if field_bounds else {}

        # Discover any additional variables and ranges from oracle conditions
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

        # Discover parameter names from callable adapters if present
        for adp in (legacy_adapter, modern_adapter):
            if adp is not None:
                fn = getattr(adp, "target_fn", getattr(adp, "_target_fn", None))
                if callable(fn):
                    import inspect
                    try:
                        sig = inspect.signature(fn)
                        for p_name, param in sig.parameters.items():
                            if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
                                if p_name not in bounds:
                                    bounds[p_name] = (0.0, 100000.0)
                    except Exception:
                        pass

        if not bounds:
            bounds = {"x": (0.0, 100.0)}

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
        log_operational_event(
            event="input_set_prepared",
            logger_name="beacon.execution",
            operation="CERTIFICATION",
            step="INPUT_PREPARATION",
            phase="02",
            certification_run_id=cert_id,
            cases=len(inputs),
            message=f"[PHASE 02] COMPLETE | unique_inputs={len(inputs)} | input_set={input_set_id}",
        )

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
        for idx, inp in enumerate(inputs):
            input_recs = [cr for cr in phase9_report.comparison_records if cr.input_id == inp.input_id]
            input_regs = regs_by_input.get(inp.input_id, [])
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

            # Aggregate classification across oracles for this input
            classifications = [cr.equivalence_outcome for cr in input_recs]
            if "MODERN_REGRESSION" in classifications:
                classification = "MODERN_REGRESSION"
            elif "REFERENCE_INCONSISTENT" in classifications:
                classification = "REFERENCE_INCONSISTENT"
            elif "MUTUAL_VIOLATION" in classifications:
                classification = "MUTUAL_VIOLATION"
            elif "MATCH" in classifications:
                classification = "MATCH"
            elif "NOT_APPLICABLE" in classifications:
                classification = "NOT_APPLICABLE"
            else:
                classification = classifications[0] if classifications else "MATCH"

            sample_rec = input_recs[0] if input_recs else None
            leg_obs = sample_rec.legacy_observation if sample_rec else None
            mod_obs = sample_rec.modern_observation if sample_rec else None

            leg_out = (
                json.dumps(leg_obs.raw_outputs, sort_keys=True, separators=(",", ":"))
                if leg_obs and leg_obs.raw_outputs
                else "{}"
            )
            mod_out = (
                json.dumps(mod_obs.raw_outputs, sort_keys=True, separators=(",", ":"))
                if mod_obs and mod_obs.raw_outputs
                else "{}"
            )
            exec_time = 0.0
            if leg_obs:
                exec_time += leg_obs.execution_time_ms
            if mod_obs:
                exec_time += mod_obs.execution_time_ms

            inp_hash = getattr(inp, "input_hash", "") or compute_canonical_input_hash(inp.values)

            case = CertificationCase(
                case_id=f"CASE-{cert_id}-{idx}",
                run_id=cert_id,
                input_set_id=input_set_id,
                case_index=idx,
                input_id=inp.input_id,
                input_json=json.dumps(inp.values, sort_keys=True, separators=(",", ":")),
                input_hash=inp_hash,
                legacy_output_json=leg_out,
                modern_output_json=mod_out,
                execution_time_ms=exec_time,
                oracle_result="VIOLATED" if input_regs else "PASS",
                classification=classification,
                severity=sev,
                violated_oracle_ids=violated_oracles,
            )
            cases_to_save.append(case)

        # Ensure regressions are linked to case_id and input_hash
        for reg in phase9_report.regressions:
            matching_case = next((c for c in cases_to_save if c.input_id == reg.input_id or c.input_hash == reg.input_id), None)
            if matching_case:
                reg.case_id = matching_case.case_id
                reg.input_hash = matching_case.input_hash
            elif not reg.input_hash and reg.input_values:
                canon = json.dumps(reg.input_values, sort_keys=True, separators=(",", ":"))
                reg.input_hash = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]

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
        u_inputs = len(inputs)
        c_cases = len(cases_to_save)
        o_evals = phase9_report.total_applicable_probes
        m_cases = sum(1 for c in cases_to_save if c.classification == "MATCH")
        r_cases = sum(1 for c in cases_to_save if c.classification == "MODERN_REGRESSION")
        e_errors = sum(1 for c in cases_to_save if c.classification in ("ERROR", "EXECUTION_ERROR"))
        c_count = len(phase9_report.regressions)
        coverage_pct = round(oracles_exercised_count / oracle_count, 4) if oracle_count > 0 else 0.0

        metrics = CertificationMetrics(
            unique_input_count=u_inputs,
            certification_case_count=c_cases,
            oracle_count=oracle_count,
            oracle_evaluation_count=o_evals,
            matching_case_count=m_cases,
            regression_case_count=r_cases,
            execution_error_count=e_errors,
            counterexample_count=c_count,
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
            oracles_exercised=oracles_exercised_count,
            oracle_coverage_pct=coverage_pct,
            overall_equivalence_score=phase9_report.overall_equivalence_score,
        )

        log_operational_event(
            event="certification_metrics_compiled",
            logger_name="beacon.execution",
            operation="CERTIFICATION",
            step="METRICS",
            phase="06",
            certification_run_id=cert_id,
            cases=c_cases,
            matching=m_cases,
            regressions=r_cases,
            message=(
                f"[PHASE 06] METRICS | cases={c_cases} | matching={m_cases} "
                f"| regressions={r_cases} | score={metrics.overall_equivalence_score:.4f}"
            ),
        )

        # 6. Apply Certification Policy Decision Flow
        blocking_reasons: list[str] = []
        warnings: list[str] = []
        final_status: CertificationStatus = CertificationStatus.CERTIFIED

        # Flow Step 1: Coverage Check
        if oracle_count == 0:
            blocking_reasons.append(
                "Insufficient oracle coverage: 0 oracles available to evaluate behavioral equivalence"
            )
            final_status = CertificationStatus.INSUFFICIENT_COVERAGE
        elif coverage_pct < cert_policy.min_oracle_coverage:
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
        log_operational_event(
            event="certification_policy_decision",
            logger_name="beacon.execution",
            operation="CERTIFICATION",
            step="POLICY",
            phase="09",
            certification_run_id=cert_id,
            outcome=final_status.value,
            cases=c_cases,
            regressions=r_cases,
            message=f"[PHASE 09] DECISION | result={final_status.value} | score={metrics.overall_equivalence_score:.4f}",
        )

        # 7. Create Immutable Artifact and Compute Canonical Content Hash
        leg_impl_hash = getattr(legacy_adapter, "implementation_hash", "") or getattr(legacy_adapter, "version", "1.0.0")
        mod_impl_hash = getattr(modern_adapter, "implementation_hash", "") or getattr(modern_adapter, "version", "2.0.0")

        final_context = context or CertificationContext(
            benchmark_id=project_id,
            benchmark_version="1.0.0",
            benchmark_name=project_id,
            benchmark_provenance="CONTROLLED",
            evaluation_mode="CONTROLLED",
            modernization_variant_id=getattr(modern_adapter, "name", "modern_equiv"),
            modernization_variant_name=getattr(modern_adapter, "name", "Modernized Implementation"),
            legacy_implementation_id=getattr(legacy_adapter, "name", "legacy"),
            modernized_implementation_id=getattr(modern_adapter, "name", "modern"),
        )
        final_context.legacy_implementation_id = getattr(legacy_adapter, "name", "legacy_adapter")
        final_context.legacy_implementation_hash = leg_impl_hash
        final_context.modernized_implementation_id = getattr(modern_adapter, "name", "modern_adapter")
        final_context.modernized_implementation_hash = mod_impl_hash
        final_context.certification_run_id = cert_id
        final_context.certification_artifact_id = cert_id
        final_context.input_set_id = input_set_id
        final_context.input_set_hash = input_set_hash
        final_context.oracle_set_id = oracle_set.oracle_set_id
        final_context.oracle_set_hash = oracle_set.oracle_set_hash
        final_context.policy_id = cert_policy.policy_id
        final_context.policy_version = getattr(cert_policy, "version", 1)
        final_context.policy_hash = pol_hash
        final_context.policy_min_equivalence_score = cert_policy.min_equivalence_score
        final_context.policy_min_oracle_coverage = cert_policy.min_oracle_coverage
        final_context.policy_min_applicable_probes_per_oracle = cert_policy.min_applicable_probes_per_oracle
        final_context.policy_allow_warnings = cert_policy.allow_warnings
        final_context.policy_block_on_critical_regression = cert_policy.block_on_critical_regression
        final_context.policy_block_on_reference_inconsistent = cert_policy.block_on_reference_inconsistent
        final_context.policy_block_on_mutual_violation = cert_policy.block_on_mutual_violation
        final_context.policy_rules = cert_policy.model_dump(mode="json")
        final_context.run_timestamp = timestamp
        final_context.run_status = final_status.value
        # Assign disambiguated metrics to context
        final_context.unique_input_count = u_inputs
        final_context.certification_case_count = c_cases
        final_context.oracle_count = oracle_count
        final_context.oracle_evaluation_count = o_evals
        final_context.matching_case_count = m_cases
        final_context.regression_case_count = r_cases
        final_context.execution_error_count = e_errors
        final_context.counterexample_count = c_count

        temp_artifact = CertificationArtifact(
            certification_id=cert_id,
            project_id=project_id,
            benchmark_id=final_context.benchmark_id,
            evaluation_mode=final_context.evaluation_mode,
            modernization_variant=final_context.modernization_variant_id,
            dataset_checksum=final_context.dataset_checksum,
            oracle_source_type=final_context.oracle_source_type,
            legacy_implementation_hash=leg_impl_hash,
            modernized_implementation_hash=mod_impl_hash,
            idempotency_key=final_context.idempotency_key,
            request_identity=final_context.request_identity,
            is_forced_recompute=final_context.is_forced_recompute,
            context=final_context,
            legacy_version=legacy_adapter.version,
            modernized_version=modern_adapter.version,
            oracle_set_id=oracle_set.oracle_set_id,
            oracle_set_version=oracle_set.version,
            oracle_set_hash=oracle_set.oracle_set_hash,
            input_set_id=input_set_id,
            input_set_hash=input_set_hash,
            certification_policy_id=cert_policy.policy_id,
            certification_policy_version=cert_policy.version,
            threshold_resolution_id=getattr(threshold_resolution, "resolution_id", None) if threshold_resolution else getattr(final_context, "threshold_resolution_id", None),
            threshold_resolution_fingerprint=getattr(threshold_resolution, "fingerprint", None) if threshold_resolution else getattr(final_context, "threshold_resolution_fingerprint", None),
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
        final_context.certification_artifact_hash = cert_content_hash
        artifact = temp_artifact.model_copy(update={"content_hash": cert_content_hash, "context": final_context})
        log_operational_event(
            event="certification_hashes_generated",
            logger_name="beacon.execution",
            operation="CERTIFICATION",
            step="CRYPTOGRAPHIC_INTEGRITY",
            phase="08",
            certification_run_id=cert_id,
            message=f"[PHASE 08] COMPLETE | artifact_hash={cert_content_hash[:16]}... | input_set_hash={input_set_hash[:16]}...",
        )

        saved_artifact = certification_repository.save_certification_run_atomic(input_set, cases_to_save, artifact)

        audit_logger.log(
            project_id=project_id,
            action=AuditAction.CERTIFICATION_COMPLETE,
            status="SUCCESS" if is_certified else "INFO",
            certification_id=cert_id,
            details={
                "status": final_status.value,
                "score": metrics.overall_equivalence_score,
                "matching_cases": m_cases,
                "regressions": r_cases,
                "coverage_pct": coverage_pct,
            },
        )

        return saved_artifact


# Module-level default certification engine singleton
certification_engine = CertificationEngine()
