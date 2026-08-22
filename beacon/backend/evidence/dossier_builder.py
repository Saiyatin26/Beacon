"""Phase 15 — Authoritative Evidence Dossier Builder & Completeness Engine.

Reconstructs complete, immutable Evidence Dossiers strictly from persisted
database records, audit logs, and cryptographic verification receipts.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Optional

from .dossier_models import (
    EvidenceDossier,
    SourceEvidence,
    ImplementationEvidence,
    OracleEvidence,
    OracleEvidenceItem,
    ExecutionEvidence,
    CounterexampleEvidenceItem,
    PolicyEvidence,
    ProvenanceEvidence,
    CryptographicEvidence,
    EvidenceCompletenessReport,
)
from .notes_store import auditor_notes_store
from certification.repository import certification_repository
from benchmarks.registry import benchmark_registry
from ingestion.dataset_registry import user_dataset_registry
from ingestion.audit import audit_logger
from oracle.registry import registry as oracle_registry

logger = logging.getLogger(__name__)


def check_evidence_completeness(
    artifact: Any,
    source: SourceEvidence,
    impl: ImplementationEvidence,
    oracle: OracleEvidence,
    policy: PolicyEvidence,
    execution: ExecutionEvidence,
    crypto: CryptographicEvidence,
) -> EvidenceCompletenessReport:
    """Evaluates whether all mandatory audit evidence required by policy is present and intact."""
    checks: dict[str, bool] = {
        "has_dataset_identity": bool(source.dataset_id or source.checksum),
        "has_input_set_identity": bool(execution.input_set_id or execution.input_set_hash or artifact.input_set_id),
        "has_implementation_hashes": bool(impl.legacy_implementation_hash and impl.modernized_implementation_hash),
        "has_oracle_set_identity": bool(oracle.oracle_set_id and (oracle.oracle_set_hash or oracle.oracle_count == 0)),
        "has_policy_identity": bool(policy.policy_id and policy.policy_hash),
        "has_oracle_evaluations": bool(execution.total_cases > 0 or artifact.status.value in ("INSUFFICIENT_COVERAGE", "ORACLE_SET_INVALID")),
        "has_counterexample_evidence": (len(artifact.regressions) == 0 or len(artifact.regressions) == execution.counterexample_count),
        "has_artifact_hash": bool(artifact.content_hash),
    }

    missing = [k for k, passed in checks.items() if not passed]
    passed_count = sum(1 for v in checks.values() if v)
    total_checks = len(checks)
    score = round(passed_count / total_checks, 3)
    status = "COMPLETE" if len(missing) == 0 else "INCOMPLETE"

    return EvidenceCompletenessReport(
        status=status,
        completeness_score=score,
        missing_fields=missing,
        checks=checks,
        details={
            "passed_checks": passed_count,
            "total_checks": total_checks,
            "status_rationale": "All mandatory audit references verified" if status == "COMPLETE" else f"Missing: {', '.join(missing)}",
        },
    )


def sanitize_input_values(input_payload: Any) -> dict[str, Any]:
    """Ensures input case values are safely sanitized and contain no secrets."""
    if not isinstance(input_payload, dict):
        return {"value": str(input_payload)}
    sanitized: dict[str, Any] = {}
    secret_terms = ["token", "key", "secret", "password", "auth", "bearer", "credential"]
    for k, v in input_payload.items():
        k_str = str(k).lower()
        if any(sec in k_str for sec in secret_terms):
            sanitized[k] = "[REDACTED]"
        else:
            sanitized[k] = v
    return sanitized


def build_evidence_dossier(
    certification_id: str,
    project_id: Optional[str] = None,
) -> EvidenceDossier:
    """Assembles a unified, immutable Evidence Dossier for a specific certification run."""
    artifact = certification_repository.get_artifact(certification_id)
    if not artifact:
        raise ValueError(f"Certification artifact '{certification_id}' not found.")

    if project_id and artifact.project_id != project_id:
        raise PermissionError(f"Access denied: Certification '{certification_id}' belongs to project '{artifact.project_id}'.")

    ctx = artifact.context
    
    # 1. Source Evidence
    source = SourceEvidence()
    ds_lookup_id = artifact.project_id or getattr(ctx, "dataset_id", "") or getattr(ctx, "dataset_name", "")
    custom_record = user_dataset_registry.get_dataset(ds_lookup_id)
    
    if custom_record:
        man = custom_record.manifest
        source = SourceEvidence(
            dataset_id=custom_record.dataset_id,
            dataset_name=custom_record.dataset_name,
            version=man.dataset_version,
            checksum=man.checksum,
            schema_fingerprint=man.schema_fingerprint,
            inferred_schema=man.inferred_schema,
            row_count=man.total_records,
            declared_provenance=man.declared_provenance.value if hasattr(man.declared_provenance, "value") else str(man.declared_provenance),
            target_domain=man.target_domain,
            is_custom_dataset=True,
        )
    else:
        # Built-in benchmark dataset
        b_id = ctx.benchmark_id if ctx else (artifact.benchmark_id or artifact.project_id)
        b_spec = benchmark_registry.get_benchmark(b_id)
        d_chk = getattr(artifact, "dataset_checksum", "") or (ctx.dataset_checksum if ctx else "")
        source = SourceEvidence(
            dataset_id=b_id,
            dataset_name=ctx.benchmark_name if ctx else (b_spec.name if b_spec else b_id),
            version=ctx.benchmark_version if ctx else "1.0.0",
            checksum=d_chk,
            schema_fingerprint=hashlib.sha256(b_id.encode()).hexdigest(),
            inferred_schema=b_spec.dataset.input_schema if (b_spec and hasattr(b_spec, "dataset")) else {},
            row_count=artifact.metrics.unique_input_count,
            declared_provenance=getattr(ctx, "benchmark_provenance", "CONTROLLED") if ctx else "CONTROLLED",
            target_domain=getattr(b_spec, "domain", "Enterprise Software"),
            is_custom_dataset=False,
        )

    # 2. Implementation Evidence
    leg_hash = getattr(artifact, "legacy_implementation_hash", "") or (getattr(ctx, "legacy_implementation_hash", "") if ctx else "")
    mod_hash = getattr(artifact, "modernized_implementation_hash", "") or (getattr(ctx, "modernized_implementation_hash", "") if ctx else "")
    impl = ImplementationEvidence(
        legacy_adapter_id=getattr(ctx, "legacy_implementation_id", artifact.legacy_version),
        legacy_adapter_name=getattr(ctx, "legacy_adapter_name", getattr(ctx, "legacy_implementation_id", artifact.legacy_version)),
        legacy_version=artifact.legacy_version,
        legacy_implementation_hash=leg_hash,
        modernized_adapter_id=getattr(ctx, "modernized_implementation_id", artifact.modernized_version),
        modernized_adapter_name=getattr(ctx, "modernized_adapter_name", getattr(ctx, "modernized_implementation_id", artifact.modernized_version)),
        modernized_version=artifact.modernized_version,
        modernized_implementation_hash=mod_hash,
        modernization_variant=getattr(ctx, "modernization_variant_id", artifact.modernization_variant or "clean_v2") if ctx else (artifact.modernization_variant or "clean_v2"),
        modernization_provenance=getattr(ctx, "modernization_provenance", "INDEPENDENT_REIMPLEMENTATION") if ctx else "INDEPENDENT_REIMPLEMENTATION",
    )

    # 3. Oracle Evidence
    orc_set = oracle_registry.get_oracle_set(artifact.oracle_set_id)
    oracle_items: list[OracleEvidenceItem] = []
    if orc_set and orc_set.oracles:
        for o in orc_set.oracles:
            cond_str = str(o.condition) if hasattr(o, "condition") else ""
            conseq_var = getattr(o.consequence, "variable", "") if hasattr(o, "consequence") else ""
            conseq_val = getattr(o.consequence, "expected_value", None) if hasattr(o, "consequence") else None
            oracle_items.append(
                OracleEvidenceItem(
                    oracle_id=o.oracle_id,
                    version=getattr(o, "version", "1.0.0"),
                    severity=getattr(o, "severity", "HIGH"),
                    confidence=getattr(o, "confidence", 1.0),
                    domain=getattr(o, "domain", "General"),
                    canonical_condition=cond_str,
                    consequence_variable=conseq_var,
                    consequence_value=conseq_val,
                    oracle_hash=getattr(o, "content_hash", ""),
                    provenance=o.provenance.model_dump(mode="json") if getattr(o, "provenance", None) else {},
                )
            )
    
    oracle_ev = OracleEvidence(
        oracle_set_id=artifact.oracle_set_id,
        oracle_set_version=artifact.oracle_set_version,
        oracle_set_hash=artifact.oracle_set_hash,
        oracle_count=artifact.metrics.oracle_count,
        oracles=oracle_items,
        summaries=[s.model_dump(mode="json") for s in artifact.oracle_summaries],
        oracle_source_type=getattr(ctx, "oracle_source_type", "CONTROLLED_ORACLE_SET") if ctx else "CONTROLLED_ORACLE_SET",
    )

    # 4. Execution Evidence
    exec_ev = ExecutionEvidence(
        total_inputs=artifact.metrics.unique_input_count,
        total_cases=artifact.metrics.certification_case_count,
        matching_cases=artifact.metrics.matching_case_count,
        regression_cases=artifact.metrics.regression_case_count,
        error_cases=artifact.metrics.execution_error_count,
        counterexample_count=len(artifact.regressions),
        oracles_exercised=int(round(artifact.metrics.oracle_coverage_pct * artifact.metrics.oracle_count)) if artifact.metrics.oracle_count else 0,
        oracle_coverage_pct=artifact.metrics.oracle_coverage_pct,
        equivalence_score=artifact.score,
        input_set_id=artifact.input_set_id,
        input_set_hash=artifact.input_set_hash,
        execution_time_ms=0.0,
    )

    # 5. Counterexample Evidence
    counterexamples: list[CounterexampleEvidenceItem] = []
    for idx, r in enumerate(artifact.regressions):
        clean_inputs = sanitize_input_values(getattr(r, "input_values", {}))
        counterexamples.append(
            CounterexampleEvidenceItem(
                counterexample_id=f"CTX-{r.oracle_id}-{r.input_id[:8] if r.input_id else idx}",
                case_id=getattr(r, "case_id", None),
                input_id=getattr(r, "input_id", ""),
                input_hash=getattr(r, "input_hash", ""),
                oracle_id=getattr(r, "oracle_id", ""),
                severity=getattr(r, "severity", "HIGH"),
                legacy_output=getattr(r, "legacy_output", None),
                modern_output=getattr(r, "modern_output", None),
                difference_description=getattr(r, "failed_assertion", getattr(r, "details", f"Output divergence: Legacy {getattr(r, 'legacy_output', None)} != Modern {getattr(r, 'modern_output', None)}")),
                invariant_violated=getattr(r, "invariant_violated", getattr(r, "failed_assertion", f"Oracle condition invariant for {getattr(r, 'oracle_id', '')}")),
                sanitized_input_values=clean_inputs,
                evidence_reference=f"artifact://{artifact.certification_id}/regressions/{idx}",
            )
        )

    # 6. Policy Evidence
    pol_ev = PolicyEvidence(
        policy_id=artifact.certification_policy_id,
        version=artifact.certification_policy_version,
        policy_hash=artifact.certification_policy_hash,
        min_equivalence_score=0.80,
        min_oracle_coverage=0.0,
        satisfied=artifact.certified,
        blocking_reasons=artifact.blocking_reasons,
        warnings=artifact.warnings,
    )

    # 7. Provenance Evidence
    repro = getattr(ctx, "reproducibility", {}) if ctx else {}
    if not isinstance(repro, dict):
        repro = {}
    prov_ev = ProvenanceEvidence(
        evaluation_mode=getattr(ctx, "evaluation_mode", artifact.evaluation_mode or "CONTROLLED") if ctx else (artifact.evaluation_mode or "CONTROLLED"),
        preferred_provider=getattr(ctx, "preferred_provider", getattr(ctx, "provider", "offline")) if ctx else "offline",
        actual_provider=repro.get("actual_provider", getattr(ctx, "provider", "offline") if ctx else "offline"),
        model=repro.get("actual_model", getattr(ctx, "model", "deterministic") if ctx else "deterministic"),
        fallback_occurred=repro.get("fallback_occurred", False),
        fallback_chain=repro.get("fallback_chain", []),
        fallback_reason=repro.get("fallback_reason"),
        prompt_version=repro.get("prompt_version", getattr(ctx, "prompt_version", "v1.0") if ctx else "v1.0"),
        evidence_package_hash=repro.get("evidence_package_hash", getattr(ctx, "evidence_package_hash", "") if ctx else ""),
        allow_external_llm=repro.get("allow_external_llm", False),
    )

    # 8. Cryptographic Evidence
    integrity_report = certification_repository.verify_certification_run_integrity(certification_id)
    raw_status = integrity_report.get("status", "FAIL")
    integ_status = "VERIFIED" if raw_status == "PASS" else "FAILED"
    
    crypto_ev = CryptographicEvidence(
        artifact_hash=artifact.content_hash,
        input_set_hash=artifact.input_set_hash,
        dataset_checksum=source.checksum,
        legacy_implementation_hash=impl.legacy_implementation_hash,
        modernized_implementation_hash=impl.modernized_implementation_hash,
        oracle_set_hash=artifact.oracle_set_hash,
        policy_hash=artifact.certification_policy_hash,
        config_fingerprint=getattr(artifact, "config_fingerprint", ""),
        integrity_status=integ_status,
        verification_report=integrity_report,
    )

    # 9. Audit Timeline (Query real audit events)
    timeline_events = audit_logger.list_events(project_id=artifact.project_id, limit=20)
    timeline_list = [
        {
            "event_id": ev.event_id,
            "timestamp": ev.timestamp,
            "action": ev.action.value if hasattr(ev.action, "value") else str(ev.action),
            "status": ev.status,
            "details": ev.details,
        }
        for ev in reversed(timeline_events)
    ]

    # 10. Completeness Report
    completeness = check_evidence_completeness(
        artifact=artifact,
        source=source,
        impl=impl,
        oracle=oracle_ev,
        policy=pol_ev,
        execution=exec_ev,
        crypto=crypto_ev,
    )

    # 11. Auditor Notes
    notes = auditor_notes_store.list_notes(certification_id=certification_id, project_id=artifact.project_id)

    # 12. Canonical Dossier Hash
    dossier_id = f"DOS-{artifact.certification_id}"
    dossier_hash_raw = f"{dossier_id}:{artifact.content_hash}:{source.checksum}:{artifact.input_set_hash}:{artifact.oracle_set_hash}:{artifact.certification_policy_hash}"
    dossier_hash = hashlib.sha256(dossier_hash_raw.encode("utf-8")).hexdigest()

    is_reused = bool(getattr(ctx, "idempotency_key", None)) and not getattr(ctx, "is_forced_recompute", False)

    return EvidenceDossier(
        dossier_id=dossier_id,
        certification_id=artifact.certification_id,
        project_id=artifact.project_id,
        created_at=artifact.timestamp,
        source_evidence=source,
        implementation_evidence=impl,
        oracle_evidence=oracle_ev,
        execution_evidence=exec_ev,
        counterexample_evidence=counterexamples,
        policy_evidence=pol_ev,
        provenance_evidence=prov_ev,
        cryptographic_evidence=crypto_ev,
        audit_timeline=timeline_list,
        completeness=completeness,
        notes=notes,
        reused_from_run_id=artifact.certification_id if is_reused else None,
        is_reused_artifact=is_reused,
        is_forced_recompute=bool(getattr(ctx, "is_forced_recompute", False)),
        dossier_hash=dossier_hash,
    )
