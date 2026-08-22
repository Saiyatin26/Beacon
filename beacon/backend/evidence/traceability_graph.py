"""Phase 15 — Evidence Traceability Graph Builder.

Constructs a deterministic DAG representing the complete chain of custody:
Dataset ──► Input Set ──► Implementation Pair ──► OracleSet ──► Oracle Evaluation
──► Counterexample/Match ──► Policy Evaluation ──► Certification Artifact ──► Cryptographic Hash.
"""

from typing import Optional
from .dossier_models import EvidenceDossier, EvidenceTraceNode


def build_traceability_graph(dossier: EvidenceDossier) -> list[EvidenceTraceNode]:
    """Constructs a directed graph of evidence nodes connecting every certification claim
    to its originating persisted entity or cryptographic hash.
    """
    nodes: list[EvidenceTraceNode] = []

    # 1. Dataset Node
    src = dossier.source_evidence
    has_dataset = bool(src.dataset_id or src.checksum)
    dataset_status = "AVAILABLE" if has_dataset else "UNAVAILABLE"
    nodes.append(
        EvidenceTraceNode(
            node_id="node_dataset",
            node_type="DATASET",
            label=f"Dataset: {src.dataset_name or src.dataset_id or 'Unknown'}",
            entity_id=src.dataset_id or None,
            status=dataset_status,
            details={
                "dataset_id": src.dataset_id,
                "version": src.version,
                "checksum": src.checksum,
                "row_count": src.row_count,
                "provenance": src.declared_provenance,
                "schema_fingerprint": src.schema_fingerprint,
                "is_custom": src.is_custom_dataset,
            } if has_dataset else {"reason": "Dataset identity or checksum unavailable"},
            target_nodes=["node_input_set"],
        )
    )

    # 2. Input Set Node
    exec_ev = dossier.execution_evidence
    has_input_set = bool(exec_ev.input_set_id or exec_ev.input_set_hash)
    nodes.append(
        EvidenceTraceNode(
            node_id="node_input_set",
            node_type="INPUT_SET",
            label=f"Input Set ({exec_ev.total_inputs} inputs)",
            entity_id=exec_ev.input_set_id or None,
            status="AVAILABLE" if has_input_set else "UNAVAILABLE",
            details={
                "input_set_id": exec_ev.input_set_id,
                "input_set_hash": exec_ev.input_set_hash,
                "total_inputs": exec_ev.total_inputs,
                "total_cases": exec_ev.total_cases,
            } if has_input_set else {"reason": "InputSet identity unavailable"},
            target_nodes=["node_impl_pair"],
        )
    )

    # 3. Implementation Pair Node
    impl = dossier.implementation_evidence
    has_impl = bool(impl.legacy_implementation_hash or impl.modernized_implementation_hash)
    nodes.append(
        EvidenceTraceNode(
            node_id="node_impl_pair",
            node_type="IMPLEMENTATION_PAIR",
            label=f"Implementation: {impl.legacy_adapter_name} vs {impl.modernized_adapter_name}",
            entity_id=f"{impl.legacy_adapter_id}:{impl.modernized_adapter_id}",
            status="AVAILABLE" if has_impl else "UNAVAILABLE",
            details={
                "legacy_adapter": impl.legacy_adapter_name,
                "legacy_hash": impl.legacy_implementation_hash,
                "legacy_version": impl.legacy_version,
                "modern_adapter": impl.modernized_adapter_name,
                "modern_hash": impl.modernized_implementation_hash,
                "modern_version": impl.modernized_version,
                "variant": impl.modernization_variant,
                "provenance": impl.modernization_provenance,
            } if has_impl else {"reason": "Implementation adapter hashes unavailable"},
            target_nodes=["node_oracle_set"],
        )
    )

    # 4. OracleSet Node
    orc = dossier.oracle_evidence
    has_oracles = bool(orc.oracle_set_id or orc.oracle_count > 0)
    nodes.append(
        EvidenceTraceNode(
            node_id="node_oracle_set",
            node_type="ORACLE_SET",
            label=f"OracleSet: {orc.oracle_set_id or 'SET-NONE'} ({orc.oracle_count} rules)",
            entity_id=orc.oracle_set_id or None,
            status="AVAILABLE" if has_oracles else "UNAVAILABLE",
            details={
                "oracle_set_id": orc.oracle_set_id,
                "oracle_set_hash": orc.oracle_set_hash,
                "oracle_count": orc.oracle_count,
                "version": orc.oracle_set_version,
                "source_type": orc.oracle_source_type,
            } if has_oracles else {"reason": "OracleSet record unavailable"},
            target_nodes=["node_oracle_eval"],
        )
    )

    # 5. Oracle Evaluation Node
    cov_pct = exec_ev.oracle_coverage_pct * 100.0
    nodes.append(
        EvidenceTraceNode(
            node_id="node_oracle_eval",
            node_type="ORACLE_EVALUATION",
            label=f"Evaluations ({exec_ev.oracles_exercised}/{orc.oracle_count} oracles, {cov_pct:.1f}% cov)",
            entity_id=f"EVAL-{dossier.certification_id}",
            status="PASSED" if exec_ev.matching_cases > 0 and exec_ev.regression_cases == 0 else ("FAILED" if exec_ev.regression_cases > 0 else "WARNING"),
            details={
                "matching_cases": exec_ev.matching_cases,
                "regression_cases": exec_ev.regression_cases,
                "error_cases": exec_ev.error_cases,
                "equivalence_score": exec_ev.equivalence_score,
                "coverage_pct": exec_ev.oracle_coverage_pct,
            },
            target_nodes=["node_counterexamples" if exec_ev.regression_cases > 0 else "node_policy"],
        )
    )

    # 6. Counterexamples / Regressions Node (if regressions exist)
    if exec_ev.regression_cases > 0:
        nodes.append(
            EvidenceTraceNode(
                node_id="node_counterexamples",
                node_type="COUNTEREXAMPLE_MATCH",
                label=f"Counterexamples ({len(dossier.counterexample_evidence)} regressions)",
                entity_id=f"CTX-{dossier.certification_id}",
                status="FAILED",
                details={
                    "counterexample_count": len(dossier.counterexample_evidence),
                    "items": [
                        {
                            "oracle_id": c.oracle_id,
                            "severity": c.severity,
                            "input_id": c.input_id,
                            "difference": c.difference_description,
                        }
                        for c in dossier.counterexample_evidence[:10]
                    ],
                },
                target_nodes=["node_policy"],
            )
        )

    # 7. Policy Evaluation Node
    pol = dossier.policy_evidence
    pol_status = "PASSED" if pol.satisfied else "FAILED"
    nodes.append(
        EvidenceTraceNode(
            node_id="node_policy",
            node_type="POLICY",
            label=f"Policy: {pol.policy_id} ({'SATISFIED' if pol.satisfied else 'VIOLATED'})",
            entity_id=pol.policy_id,
            status=pol_status,
            details={
                "policy_id": pol.policy_id,
                "policy_hash": pol.policy_hash,
                "min_equivalence_score": pol.min_equivalence_score,
                "min_oracle_coverage": pol.min_oracle_coverage,
                "satisfied": pol.satisfied,
                "blocking_reasons": pol.blocking_reasons,
                "warnings": pol.warnings,
            },
            target_nodes=["node_artifact"],
        )
    )

    # 8. Certification Artifact Node
    crypto = dossier.cryptographic_evidence
    art_status = "PASSED" if pol.satisfied else "FAILED"
    nodes.append(
        EvidenceTraceNode(
            node_id="node_artifact",
            node_type="ARTIFACT",
            label=f"Certificate: {dossier.certification_id} ({crypto.integrity_status})",
            entity_id=dossier.certification_id,
            status=art_status,
            details={
                "certification_id": dossier.certification_id,
                "project_id": dossier.project_id,
                "created_at": dossier.created_at,
                "artifact_hash": crypto.artifact_hash,
                "reused": dossier.is_reused_artifact,
            },
            target_nodes=["node_integrity"],
        )
    )

    # 9. Cryptographic Integrity Node
    nodes.append(
        EvidenceTraceNode(
            node_id="node_integrity",
            node_type="INTEGRITY_HASH",
            label=f"Cryptographic Hash ({crypto.integrity_status})",
            entity_id=crypto.artifact_hash[:16] if crypto.artifact_hash else None,
            status="PASSED" if crypto.integrity_status == "VERIFIED" else "FAILED",
            details={
                "artifact_hash": crypto.artifact_hash,
                "dataset_checksum": crypto.dataset_checksum,
                "oracle_set_hash": crypto.oracle_set_hash,
                "input_set_hash": crypto.input_set_hash,
                "legacy_hash": crypto.legacy_implementation_hash,
                "modern_hash": crypto.modernized_implementation_hash,
                "policy_hash": crypto.policy_hash,
                "integrity_status": crypto.integrity_status,
            },
            target_nodes=[],
        )
    )

    return nodes
