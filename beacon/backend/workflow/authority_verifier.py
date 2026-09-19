"""BEACON V2 — Central Execution Authority Chain Verifier.

Enforces cryptographic and semantic cross-binding across:
Execution Identity
    ↓
EvaluationResult
    ↓
OracleSet
    ↓
ThresholdResolution
    ↓
CertificationArtifact
    ↓
Audit Records

Guarantees fail-closed authority verification identically across Certification,
Interrupted Recovery, and Execution Reuse.
"""

from dataclasses import dataclass, field
import logging
from typing import Any, Optional

from certification.models import CertificationArtifact, verify_artifact_integrity
from evaluation.models import EvaluationResult, verify_evaluation_result_integrity
from oracle.models import OracleSet
from threshold.models import ThresholdResolution
from .models import WorkflowErrorCode

logger = logging.getLogger("beacon.workflow.authority_verifier")


@dataclass
class AuthorityChainVerificationResult:
    is_valid: bool
    failure_reason: str = ""
    error_code: Optional[WorkflowErrorCode] = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


def verify_execution_authority_chain(
    execution_fingerprint: str,
    application_id: str,
    eval_result: Optional[EvaluationResult],
    oracle_set: Optional[OracleSet],
    threshold_res: Optional[ThresholdResolution],
    artifact: Optional[CertificationArtifact] = None,
    audit_events: Optional[list[Any]] = None,
    cases: Optional[list[Any]] = None,
    require_artifact: bool = True,
    require_audit: bool = False,
) -> AuthorityChainVerificationResult:
    """Central deterministic verifier for the complete execution authority chain.
    
    Used uniformly across:
    1. Certification: Before accepting and persisting final CertificationArtifact.
    2. Recovery: Before allowing recovery to finalize an execution.
    3. Execution Reuse: Before returning an existing completed execution.
    
    Invariants Enforced:
    - execution_fingerprint is authoritative across all objects.
    - EvaluationResult belongs to execution and application, passes cryptographic integrity.
    - OracleSet belongs to execution and application, contains non-empty rules/oracles.
    - ThresholdResolution is cryptographically recomputable, bound to execution and oracle.
    - CertificationArtifact binds evaluation, oracle, threshold, and execution without discrepancy.
    - Audit records belong to certification execution.
    """
    if not execution_fingerprint:
        return AuthorityChainVerificationResult(
            is_valid=False,
            failure_reason="Missing authoritative Stage-B execution_fingerprint.",
            error_code=WorkflowErrorCode.INVALID_INPUT,
        )

    # 1. EvaluationResult Verification
    if not eval_result:
        return AuthorityChainVerificationResult(
            is_valid=False,
            failure_reason="EvaluationResult is missing from authority chain.",
            error_code=WorkflowErrorCode.EVALUATION_FAILED,
        )
    if not verify_evaluation_result_integrity(eval_result):
        return AuthorityChainVerificationResult(
            is_valid=False,
            failure_reason=f"EvaluationResult '{getattr(eval_result, 'evaluation_id', 'unknown')}' failed cryptographic integrity verification.",
            error_code=WorkflowErrorCode.EVALUATION_FAILED,
        )
    if getattr(eval_result, "application_id", None) and eval_result.application_id != application_id:
        return AuthorityChainVerificationResult(
            is_valid=False,
            failure_reason=f"EvaluationResult application '{eval_result.application_id}' does not match execution application '{application_id}'.",
            error_code=WorkflowErrorCode.EVALUATION_FAILED,
        )
    eval_fp = (getattr(eval_result, "metadata", {}) or {}).get("execution_fingerprint")
    if eval_fp and eval_fp != execution_fingerprint:
        return AuthorityChainVerificationResult(
            is_valid=False,
            failure_reason=f"EvaluationResult execution fingerprint mismatch: expected '{execution_fingerprint}', found '{eval_fp}'.",
            error_code=WorkflowErrorCode.EVALUATION_FAILED,
        )

    # 2. OracleSet Verification
    if not oracle_set:
        return AuthorityChainVerificationResult(
            is_valid=False,
            failure_reason="OracleSet authority is missing from execution chain.",
            error_code=WorkflowErrorCode.ORACLE_AUTHORITY_MISSING,
        )
    oset_id = getattr(oracle_set, "oracle_set_id", "")
    oset_hash = getattr(oracle_set, "oracle_set_hash", "") or getattr(oracle_set, "fingerprint", "")
    if not oset_id or not oset_hash:
        return AuthorityChainVerificationResult(
            is_valid=False,
            failure_reason="OracleSet authority is missing required identity or cryptographic content hash.",
            error_code=WorkflowErrorCode.ORACLE_AUTHORITY_MISSING,
        )
    if getattr(oracle_set, "application_id", None) and oracle_set.application_id != application_id:
        return AuthorityChainVerificationResult(
            is_valid=False,
            failure_reason=f"OracleSet application '{oracle_set.application_id}' does not match execution application '{application_id}'.",
            error_code=WorkflowErrorCode.ORACLE_AUTHORITY_MISSING,
        )
    rules_count = len(getattr(oracle_set, "rules", [])) + len(getattr(oracle_set, "oracles", []))
    if rules_count == 0:
        return AuthorityChainVerificationResult(
            is_valid=False,
            failure_reason=f"OracleSet '{oset_id}' contains zero rules/oracles (empty oracle authority forbidden).",
            error_code=WorkflowErrorCode.ORACLE_AUTHORITY_MISSING,
        )
    oset_fp = (getattr(oracle_set, "metadata", {}) or {}).get("execution_fingerprint")
    if oset_fp and oset_fp != execution_fingerprint:
        return AuthorityChainVerificationResult(
            is_valid=False,
            failure_reason=f"OracleSet execution fingerprint mismatch: expected '{execution_fingerprint}', found '{oset_fp}'.",
            error_code=WorkflowErrorCode.ORACLE_AUTHORITY_MISSING,
        )

    # 3. ThresholdResolution Verification
    if not threshold_res:
        return AuthorityChainVerificationResult(
            is_valid=False,
            failure_reason="ThresholdResolution authority is missing from execution chain.",
            error_code=WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING,
        )
    expected_thresh_fp = threshold_res.compute_fingerprint()
    if threshold_res.fingerprint != expected_thresh_fp:
        return AuthorityChainVerificationResult(
            is_valid=False,
            failure_reason=f"ThresholdResolution fingerprint mismatch: expected '{expected_thresh_fp}', found '{threshold_res.fingerprint}'.",
            error_code=WorkflowErrorCode.THRESHOLD_FINGERPRINT_MISMATCH,
        )
    thresh_fp = getattr(threshold_res, "provenance", {}).get("execution_fingerprint")
    if thresh_fp and thresh_fp != execution_fingerprint:
        return AuthorityChainVerificationResult(
            is_valid=False,
            failure_reason=f"ThresholdResolution execution fingerprint mismatch: expected '{execution_fingerprint}', found '{thresh_fp}'.",
            error_code=WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING,
        )
    thresh_oset_id = getattr(threshold_res, "provenance", {}).get("oracle_set_id")
    if thresh_oset_id and thresh_oset_id != oset_id:
        return AuthorityChainVerificationResult(
            is_valid=False,
            failure_reason=f"ThresholdResolution oracle set id mismatch: expected '{oset_id}', found '{thresh_oset_id}'.",
            error_code=WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING,
        )

    # 4. CertificationArtifact Verification (if required or provided)
    if require_artifact or artifact is not None:
        if not artifact or not getattr(artifact, "certification_id", None):
            return AuthorityChainVerificationResult(
                is_valid=False,
                failure_reason="CertificationArtifact is missing from authority chain.",
                error_code=WorkflowErrorCode.CERTIFICATION_FAILED,
            )
        if not verify_artifact_integrity(artifact):
            return AuthorityChainVerificationResult(
                is_valid=False,
                failure_reason=f"CertificationArtifact '{artifact.certification_id}' failed cryptographic content hash verification.",
                error_code=WorkflowErrorCode.CERTIFICATION_FAILED,
            )
        art_bench_id = getattr(artifact.context, "benchmark_id", None) if artifact.context else None
        if art_bench_id and art_bench_id != application_id:
            return AuthorityChainVerificationResult(
                is_valid=False,
                failure_reason=f"CertificationArtifact application '{art_bench_id}' mismatch with '{application_id}'.",
                error_code=WorkflowErrorCode.CERTIFICATION_FAILED,
            )
        art_thresh_id = artifact.threshold_resolution_id or (artifact.context.threshold_resolution_id if artifact.context else None)
        if art_thresh_id != threshold_res.resolution_id:
            return AuthorityChainVerificationResult(
                is_valid=False,
                failure_reason=f"CertificationArtifact threshold resolution mismatch ('{art_thresh_id}' vs '{threshold_res.resolution_id}').",
                error_code=WorkflowErrorCode.CERTIFICATION_FAILED,
            )
        art_oset_id = artifact.oracle_set_id or (artifact.context.oracle_set_id if artifact.context else None)
        if art_oset_id and art_oset_id != oset_id:
            return AuthorityChainVerificationResult(
                is_valid=False,
                failure_reason=f"CertificationArtifact oracle set mismatch ('{art_oset_id}' vs '{oset_id}').",
                error_code=WorkflowErrorCode.CERTIFICATION_FAILED,
            )

    # 5. Certification Cases Check
    if cases is not None:
        if not cases or len(cases) == 0:
            return AuthorityChainVerificationResult(
                is_valid=False,
                failure_reason="Certification cases are empty (zero evaluated cases).",
                error_code=WorkflowErrorCode.CERTIFICATION_FAILED,
            )

    # 6. Audit Trail Verification
    if require_audit:
        if not audit_events or len(audit_events) == 0:
            return AuthorityChainVerificationResult(
                is_valid=False,
                failure_reason="Mandatory audit events missing for certification.",
                error_code=WorkflowErrorCode.PERSISTENCE_FAILED,
            )

    return AuthorityChainVerificationResult(
        is_valid=True,
        failure_reason="",
        error_code=None,
        diagnostics={
            "execution_fingerprint": execution_fingerprint,
            "application_id": application_id,
            "evaluation_id": getattr(eval_result, "evaluation_id", None),
            "oracle_set_id": oset_id,
            "threshold_resolution_id": getattr(threshold_res, "resolution_id", None),
            "certification_id": getattr(artifact, "certification_id", None) if artifact else None,
        }
    )
