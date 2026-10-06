"""BEACON V2 — Phase 11 Canonical Workflow Engine.

The central production orchestrator that connects the established authority chain:
Phase 1 (App Registry & Preflight)
    ↓
Phase 2 (Adapters & Dynamic Ingestion)
    ↓
Phase 3 (Evidence Records, Manifest & EvidenceBundle)
    ↓
Phase 4 (BehavioralEvaluationEngine — Authoritative EvaluationResult)
    ↓
Phase 5 (ControlledAssessmentEngine — Controlled Mode Assessment)
    ↓
Phase 6 (RuleDiscoveryEngine — Candidate Discovery)
    ↓
Phase 7 (RuleReconciliationEngine — Authoritative OracleSet)
    ↓
Phase 8 (ThresholdEngine — Exact ThresholdResolution & Fingerprint)
    ↓
CertificationEngine (Authoritative CertificationArtifact)
    ↓
Phase 10 (Grounded Explanation & Grounding Validation)
    ↓
Phase 11 (Atomic SQLite Persistence & Structured Audit Logging)

Zero reconstruction of missing authority: fails closed immediately.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import sqlite3
import time
from typing import Any, Optional
import uuid

from application.models import ApplicationSpec
from application.registry import ApplicationRegistry, application_registry
from application.resolver import ApplicationResolutionError, ApplicationResolver, application_resolver
from certification.certification_engine import CertificationEngine, certification_engine
from certification.models import (
    BehavioralRegression,
    CertificationArtifact,
    CertificationCase,
    CertificationContext,
    CertificationInputSet,
    CertificationPolicy,
    CertificationStatus,
    CertificationTestInput,
    compute_artifact_content_hash,
    compute_input_set_canonical_hash,
    verify_artifact_integrity,
)
from certification.policies import certification_policy_resolver
from certification.repository import CertificationRepository, certification_repository
from discovery.engine import RuleDiscoveryEngine
from discovery.models import DiscoveryResult
from evaluation.engine import BehavioralEvaluationEngine, behavioral_evaluation_engine
from evaluation.models import (
    BehaviorDifference,
    BehaviorDimension,
    DifferenceType,
    EvaluationResult,
    EvaluationSummary,
    EvaluationVerdict,
    InputEvaluationResult,
    verify_evaluation_result_integrity,
)
from evaluation.persistence import EvaluationPersistenceStore, evaluation_persistence
from execution.evidence_models import (
    EvidenceBundle,
    EvidenceCaptureStatus,
    EvidenceManifest,
    EvidenceManifestItem,
    EvidencePersistenceStatus,
    EvidenceRecord,
    EvidenceType,
)
from execution.evidence_store import EvidenceStore, evidence_store
from ingestion.audit import AuditAction, audit_logger
from intelligence.context_builder import ExplanationContextBuilder, explanation_context_builder
from intelligence.engine import IntelligenceEngine, intelligence_engine
from intelligence.models import CertificationExplanation, ExplanationRequest
from operations.logging_config import log_operational_event
from oracle.models import OracleSet
from reconciliation.engine import RuleReconciliationEngine
from reconciliation.persistence import ReconciliationPersistenceStore, reconciliation_persistence
from rules.engine import ControlledAssessmentEngine
from rules.models import (
    BusinessRule,
    CompoundRuleCondition,
    ControlledEvaluationResult,
    ExpectedBehavior,
    ExpectedBehaviorType,
    RuleOperator,
    RulePredicate,
    RuleSeverity,
    RuleSource,
    UnaryRuleCondition,
)
from rules.registry import RuleRegistry, rule_registry
from threshold.engine import ThresholdEngine, threshold_engine
from threshold.models import (
    DifferenceMetric,
    EstimatorType,
    OutlierPolicy,
    ThresholdPolicy,
    ThresholdResolution,
    ThresholdStatus,
    ThresholdStrategy,
    ThresholdStrategyProposal,
    ThresholdValidationPolicy,
)
from threshold.persistence import ThresholdPersistenceStore, threshold_persistence

from .authority_verifier import verify_execution_authority_chain
from .idempotency import WorkflowIdempotencyManager, workflow_idempotency
from .models import (
    FinalizationState,
    WorkflowErrorCode,
    WorkflowResult,
    WorkflowRun,
    WorkflowRunRequest,
    WorkflowState,
    WorkflowStateTransitionError,
    compute_execution_fingerprint,
    transition_workflow_state,
)
from .persistence import WorkflowPersistenceStore, workflow_persistence

logger = logging.getLogger("beacon.workflow.engine")


class CanonicalV2WorkflowEngine:
    """The authoritative end-to-end production workflow engine for BEACON V2."""

    def __init__(
        self,
        app_registry: Optional[ApplicationRegistry] = None,
        app_resolver: Optional[ApplicationResolver] = None,
        ev_store: Optional[EvidenceStore] = None,
        eval_eng: Optional[BehavioralEvaluationEngine] = None,
        eval_persistence: Optional[EvaluationPersistenceStore] = None,
        controlled_eng: Optional[ControlledAssessmentEngine] = None,
        rules_registry: Optional[RuleRegistry] = None,
        discovery_eng: Optional[RuleDiscoveryEngine] = None,
        reconcile_eng: Optional[RuleReconciliationEngine] = None,
        rec_persistence: Optional[ReconciliationPersistenceStore] = None,
        thresh_eng: Optional[ThresholdEngine] = None,
        thresh_persistence: Optional[ThresholdPersistenceStore] = None,
        cert_eng: Optional[CertificationEngine] = None,
        cert_repo: Optional[CertificationRepository] = None,
        ctx_builder: Optional[ExplanationContextBuilder] = None,
        intel_eng: Optional[IntelligenceEngine] = None,
        persistence: Optional[WorkflowPersistenceStore] = None,
        idempotency_mgr: Optional[WorkflowIdempotencyManager] = None,
    ):
        self.app_registry = app_registry or application_registry
        self.app_resolver = app_resolver or application_resolver
        self.ev_store = ev_store or evidence_store
        self.eval_eng = eval_eng or behavioral_evaluation_engine
        self.eval_persistence = eval_persistence or evaluation_persistence
        self.controlled_eng = controlled_eng or ControlledAssessmentEngine()
        self.rules_registry = rules_registry or rule_registry
        self.discovery_eng = discovery_eng or RuleDiscoveryEngine()
        self.reconcile_eng = reconcile_eng or RuleReconciliationEngine()
        self.rec_persistence = rec_persistence or reconciliation_persistence
        self.thresh_eng = thresh_eng or threshold_engine
        self.thresh_persistence = thresh_persistence or threshold_persistence
        self.cert_eng = cert_eng or certification_engine
        self.cert_repo = cert_repo or certification_repository
        self.ctx_builder = ctx_builder or explanation_context_builder
        self.intel_eng = intel_eng or intelligence_engine
        self.persistence = persistence or workflow_persistence
        self.idempotency_mgr = idempotency_mgr or workflow_idempotency

    def transition_state(
        self,
        run: WorkflowRun,
        target_state: WorkflowState,
        reason: str = "",
        metadata: Optional[dict[str, Any]] = None,
        is_recovery: bool = False,
    ) -> WorkflowRun:
        """Central authoritative state transition method."""
        transition_workflow_state(run, target_state, reason=reason, metadata=metadata, is_recovery=is_recovery)
        self.persistence.save_run(run)
        return run

    def execute_workflow(
        self,
        request: WorkflowRunRequest,
        spec_override: Optional[ApplicationSpec] = None,
    ) -> WorkflowResult:
        """Executes the complete canonical V2 certification pipeline end-to-end with authoritative Stage-B idempotency."""
        # 1. Determine Stage A request identity (used for request deduplication and candidate discovery only)
        stage_a_fp = self.idempotency_mgr.get_request_fingerprint(request)

        # 2. Create Candidate Run ID & Acquire Initial Stage-A Reservation
        run_id = f"WRUN-{uuid.uuid4().hex[:12]}"

        with self.idempotency_mgr.acquire_execution_lock(stage_a_fp, run_id=run_id, force_recompute=request.force_recompute) as (res_ok, existing_owner_id, existing_status):
            if not res_ok:
                if existing_status == "IN_PROGRESS":
                    log_operational_event(
                        event="workflow_concurrency_conflict",
                        logger_name="beacon.workflow",
                        operation="CERTIFICATION_WORKFLOW",
                        step="LOCK",
                        workflow_run_id=run_id,
                        application_id=request.application_id,
                        error_code=WorkflowErrorCode.CONCURRENCY_CONFLICT.value,
                        message=f"Concurrent execution in progress by run '{existing_owner_id}'.",
                    )
                    return WorkflowResult(
                        workflow_run_id=run_id,
                        application_id=request.application_id,
                        state=WorkflowState.FAILED,
                        status="FAILED",
                        certified=False,
                        equivalence_score=None,
                        error_code=WorkflowErrorCode.CONCURRENCY_CONFLICT,
                        error_message=f"Concurrent execution in progress by run '{existing_owner_id}'.",
                        audit_status="FAILED",
                    )

            run = WorkflowRun(
                workflow_run_id=run_id,
                application_id=request.application_id,
                request_fingerprint=stage_a_fp,
                state=WorkflowState.INITIALIZED,
                metadata={"user_id": request.user_id, "idempotency_key": request.idempotency_key},
            )

            t0 = time.perf_counter()
            timings: dict[str, float] = {}

            log_operational_event(
                event="workflow_started",
                logger_name="beacon.workflow",
                operation="CERTIFICATION_WORKFLOW",
                step="START",
                workflow_run_id=run_id,
                application_id=request.application_id,
                message=f"[WORKFLOW START] run={run_id} | app={request.application_id}",
            )

            try:
                self.persistence.save_run(run)

                # 3. Stage 1: Validation & Resolution (Resolves concrete execution inputs and computes Stage-B fingerprint)
                self.transition_state(run, WorkflowState.VALIDATING, "Validating request and resolving application targets")
                init_res = self._stage_validate_and_init(request, spec_override, run, timings)
                if isinstance(init_res, WorkflowResult):
                    return init_res
                spec, ref_adapter, target_adapter, test_inputs = init_res

                # 3.1 Stage-A -> Stage-B Atomic Binding
                bound_ok, bound_owner, bound_status = self.idempotency_mgr.bind_execution_identity(
                    request_fingerprint=stage_a_fp,
                    execution_fingerprint=run.execution_fingerprint,
                    workflow_run_id=run.workflow_run_id,
                    force_recompute=request.force_recompute,
                )
                if not bound_ok:
                    if bound_status == "COMPLETED" and not request.force_recompute:
                        existing_run = self.persistence.get_run(bound_owner)
                        if existing_run and existing_run.execution_fingerprint == run.execution_fingerprint:
                            verified_res = self._verify_and_build_existing_run(existing_run)
                            if verified_res:
                                logger.info(f"Reusing verified completed run '{existing_run.workflow_run_id}' for Stage-B execution identity.")
                                self.idempotency_mgr.finalize_run(
                                    fingerprint=stage_a_fp,
                                    run_id=existing_run.workflow_run_id,
                                    status="COMPLETED",
                                )
                                return verified_res
                    if bound_status == "IN_PROGRESS" and not request.force_recompute:
                        log_operational_event(
                            event="workflow_concurrency_conflict",
                            logger_name="beacon.workflow",
                            operation="CERTIFICATION_WORKFLOW",
                            step="STAGE_B_BINDING",
                            workflow_run_id=run_id,
                            application_id=request.application_id,
                            error_code=WorkflowErrorCode.CONCURRENCY_CONFLICT.value,
                            message=f"Concurrent execution in progress for execution fingerprint '{run.execution_fingerprint[:12]}' by run '{bound_owner}'.",
                        )
                        return self._fail_run(
                            run,
                            WorkflowErrorCode.CONCURRENCY_CONFLICT,
                            f"Concurrent execution in progress for execution fingerprint '{run.execution_fingerprint[:12]}' by run '{bound_owner}'.",
                        )

                # 3.2 Authoritative Stage-B Idempotency Check (Completed Run Reuse)
                if not request.force_recompute:
                    existing_completed = self.idempotency_mgr.find_completed_execution(run.execution_fingerprint)
                    if existing_completed:
                        verified_res = self._verify_and_build_existing_run(existing_completed)
                        if verified_res:
                            logger.info(
                                f"Reusing verified completed run '{existing_completed.workflow_run_id}' "
                                f"matching Stage-B execution identity '{run.execution_fingerprint[:12]}'."
                            )
                            self.idempotency_mgr.finalize_run(
                                fingerprint=run.request_fingerprint,
                                run_id=existing_completed.workflow_run_id,
                                status="COMPLETED",
                            )
                            return verified_res

                # 4. Stage 2: Phase 3 Evidence Collection & Bundle Assembly
                self.transition_state(run, WorkflowState.CAPTURING_EVIDENCE, "Capturing execution evidence and generating EvidenceManifest")
                ev_res = self._stage_capture_evidence(spec, ref_adapter, target_adapter, test_inputs, run, timings)
                if isinstance(ev_res, WorkflowResult):
                    return ev_res
                bundle, all_evidence_records, evaluated_input_cases = ev_res

                # 5. Stage 3: Phase 4 Authoritative Behavioral Evaluation
                self.transition_state(run, WorkflowState.EVALUATING, "Executing Phase 4 BehavioralEvaluationEngine")
                eval_result = self._stage_evaluate_behavior(spec, bundle, test_inputs, run, timings)
                if isinstance(eval_result, WorkflowResult):
                    return eval_result
                if not eval_result:
                    return self._fail_run(run, WorkflowErrorCode.EVALUATION_FAILED, "EvaluationResult missing.")

                # 6. Stage 4: Phase 5 Controlled Mode Assessment (when applicable)
                user_rules, ctrl_result = self._stage_evaluate_controlled_mode(spec, bundle, eval_result, run, timings)
                if isinstance(ctrl_result, WorkflowResult):
                    return ctrl_result

                # 7. Stage 5: Phase 6 Invariant Discovery (when applicable)
                disc_result = self._stage_discover_rules(spec, bundle, eval_result, request, run, timings)
                if isinstance(disc_result, WorkflowResult):
                    return disc_result

                # 8. Stage 6: Phase 7 OracleSet Reconciliation
                self.transition_state(run, WorkflowState.RESOLVING_ORACLES, "Reconciling authoritative OracleSet via Phase 7")
                oracle_set = self._stage_reconcile_oracles(spec, user_rules, disc_result, bundle, run, timings)
                if isinstance(oracle_set, WorkflowResult):
                    return oracle_set
                if not oracle_set:
                    return self._fail_run(run, WorkflowErrorCode.ORACLE_AUTHORITY_MISSING, "OracleSet resolution missing.")

                # 9. Stage 7: Phase 8 Exact Threshold Resolution (Automatic Evidence-Based)
                self.transition_state(run, WorkflowState.RESOLVING_THRESHOLDS, "Resolving and verifying Phase 8 ThresholdResolution")
                threshold_res = self._stage_resolve_thresholds(spec, bundle, eval_result, all_evidence_records, run, timings)
                if isinstance(threshold_res, WorkflowResult):
                    return threshold_res
                if not threshold_res:
                    return self._fail_run(run, WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING, "ThresholdResolution missing.")

                # 10. Stage 8: Certification Engine Execution
                self.transition_state(run, WorkflowState.CERTIFYING, "Executing deterministic CertificationEngine")
                artifact = self._stage_execute_certification(
                    spec=spec,
                    ref_adapter=ref_adapter,
                    target_adapter=target_adapter,
                    test_inputs=test_inputs,
                    eval_result=eval_result,
                    oracle_set=oracle_set,
                    threshold_res=threshold_res,
                    request=request,
                    run=run,
                    timings=timings,
                )
                if isinstance(artifact, WorkflowResult):
                    return artifact

                # 11. Stage 9: Phase 10 Grounded Explanation (Optional)
                explanation_dict = None
                if request.explain:
                    self.transition_state(run, WorkflowState.EXPLAINING, "Generating grounded explanation")
                    explanation_dict = self._stage_generate_explanation(
                        artifact=artifact,
                        eval_result=eval_result,
                        oracle_set=oracle_set,
                        threshold_res=threshold_res,
                        all_evidence_records=all_evidence_records,
                        request=request,
                        run=run,
                    )

                # 12. Stage 10: Atomic Persistence & Audit
                self.transition_state(run, WorkflowState.PERSISTING, "Persisting certification data and mandatory audit")
                audit_status_str = self._stage_persist_and_audit(
                    artifact=artifact,
                    test_inputs=test_inputs,
                    evaluated_input_cases=evaluated_input_cases,
                    spec=spec,
                    threshold_res=threshold_res,
                    eval_result=eval_result,
                    run=run,
                    timings=timings,
                )
                if isinstance(audit_status_str, WorkflowResult):
                    return audit_status_str

                total_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                timings["total_workflow_ms"] = total_ms
                run.stage_timings_ms = timings
                self.persistence.save_run(run)

                status_str = artifact.status.value if hasattr(artifact.status, "value") else str(artifact.status)
                log_operational_event(
                    event="workflow_completed",
                    logger_name="beacon.workflow",
                    operation="CERTIFICATION_WORKFLOW",
                    step="COMPLETED",
                    workflow_run_id=run_id,
                    application_id=request.application_id,
                    status=status_str,
                    score=artifact.score,
                    duration_ms=total_ms,
                    message=f"[WORKFLOW COMPLETED] run={run_id} | status={status_str} | score={artifact.score:.4f} | latency={total_ms}ms",
                )

                return WorkflowResult(
                    workflow_run_id=run_id,
                    application_id=spec.application_id,
                    state=WorkflowState.COMPLETED,
                    status=status_str,
                    certified=bool(artifact.certified),
                    equivalence_score=artifact.score,
                    artifact_id=artifact.artifact_id,
                    artifact_hash=artifact.artifact_hash,
                    threshold_resolution_id=threshold_res.resolution_id,
                    threshold_resolution_fingerprint=threshold_res.fingerprint,
                    unique_input_count=artifact.metrics.unique_input_count if artifact.metrics else len(test_inputs),
                    regressions_count=len(artifact.regressions),
                    regressions=[r.model_dump(mode="json") for r in artifact.regressions],
                    explanation=explanation_dict,
                    audit_status=audit_status_str,
                    timings_ms=timings,
                )

            except ApplicationResolutionError as exc:
                logger.warning(f"Workflow resolution failed for '{request.application_id}': {exc}")
                return self._fail_run(run, WorkflowErrorCode.ADAPTER_RESOLUTION_FAILED, str(exc))
            except sqlite3.OperationalError as exc:
                logger.error(f"Workflow persistence failed for '{request.application_id}': {exc}", exc_info=True)
                return self._fail_run(run, WorkflowErrorCode.PERSISTENCE_FAILED, str(exc), audit_status="PERSISTENCE_FAILED")
            except Exception as exc:
                logger.error(f"Workflow execution failed unexpectedly for '{request.application_id}': {exc}", exc_info=True)
                return self._fail_run(run, WorkflowErrorCode.INTERNAL_ERROR, f"Unexpected workflow failure: {str(exc)}")

    # --------------------------------------------------------------------------
    # STAGE IMPLEMENTATIONS
    # --------------------------------------------------------------------------

    def _stage_validate_and_init(
        self,
        request: WorkflowRunRequest,
        spec_override: Optional[ApplicationSpec],
        run: WorkflowRun,
        timings: dict[str, float],
    ) -> Any:
        t_stage = time.perf_counter()
        spec = spec_override or self.app_registry.get_application(request.application_id)
        if not spec:
            return self._fail_run(
                run,
                WorkflowErrorCode.APPLICATION_NOT_FOUND,
                f"Application '{request.application_id}' not found in registry.",
            )

        # Resolve authoritative input set (prioritizing discovered/authoritative inputs over caller overrides)
        is_repo_spec = bool(
            (spec.metadata and (spec.metadata.get("specification_fingerprint") or spec.metadata.get("discovered_inputs") or spec.metadata.get("authoritative_input_set")))
            or (spec.dataset_config and spec.dataset_config.metadata and (spec.dataset_config.metadata.get("authoritative_input_set") or spec.dataset_config.metadata.get("discovered_inputs")))
        )
        if request.custom_inputs:
            return self._fail_run(
                run,
                WorkflowErrorCode.INVALID_INPUT,
                "Caller-supplied custom_inputs cannot override repository-discovered inputs in production certification.",
            )

        authoritative_inputs = request.authoritative_input_set
        if authoritative_inputs is None and spec.metadata and spec.metadata.get("authoritative_input_set"):
            authoritative_inputs = spec.metadata.get("authoritative_input_set")
        elif authoritative_inputs is None and spec.dataset_config and spec.dataset_config.metadata and spec.dataset_config.metadata.get("authoritative_input_set"):
            authoritative_inputs = spec.dataset_config.metadata.get("authoritative_input_set")
        elif authoritative_inputs is None and spec.metadata and spec.metadata.get("discovered_inputs"):
            authoritative_inputs = spec.metadata.get("discovered_inputs")
        elif authoritative_inputs is None and spec.dataset_config and spec.dataset_config.metadata and spec.dataset_config.metadata.get("discovered_inputs"):
            authoritative_inputs = spec.dataset_config.metadata.get("discovered_inputs")

        if is_repo_spec and (not authoritative_inputs or len(authoritative_inputs) == 0):
            return self._fail_run(
                run,
                WorkflowErrorCode.NO_AUTHORITATIVE_INPUT_SET,
                f"No authoritative input set discovered for repository specification '{spec.application_id}'.",
            )

        ref_adapter, target_adapter = self.app_resolver.resolve_adapters(
            spec=spec,
            target_index=request.target_index,
        )

        test_inputs = self.app_resolver.resolve_inputs(
            spec=spec,
            custom_inputs=authoritative_inputs,
        )
        if not test_inputs or len(test_inputs) == 0:
            err_code = WorkflowErrorCode.NO_AUTHORITATIVE_INPUT_SET if is_repo_spec else WorkflowErrorCode.INVALID_INPUT
            return self._fail_run(
                run,
                err_code,
                f"No test inputs could be resolved for application '{spec.application_id}'.",
            )

        ref_target = spec.get_reference_target() if (spec and hasattr(spec, "get_reference_target")) else None
        tgt_targets = spec.get_target_candidates() if (spec and hasattr(spec, "get_target_candidates")) else []
        tgt_target = tgt_targets[request.target_index] if (request.target_index < len(tgt_targets)) else None

        ref_s_hash = (getattr(ref_target, "source_hash", "") or getattr(ref_adapter, "implementation_hash", "") or "") if ref_target else getattr(ref_adapter, "implementation_hash", "")
        tgt_s_hash = (getattr(tgt_target, "source_hash", "") or getattr(target_adapter, "implementation_hash", "") or "") if tgt_target else getattr(target_adapter, "implementation_hash", "")

        meta = getattr(spec, "metadata", {}) or {}
        legacy_src = meta.get("legacy_provenance") or {}
        modern_src = meta.get("modern_provenance") or {}
        eval_mode = meta.get("evaluation_mode") or getattr(request, "evaluation_mode", "CONTROLLED")
        spec_fp = meta.get("specification_fingerprint", "")

        # Resolve authoritative backend certification policy and policy fingerprint
        effective_cert_policy = certification_policy_resolver.resolve_effective_policy(
            application_id=spec.application_id,
            evaluation_mode=eval_mode,
        )
        policy_fp = effective_cert_policy.compute_policy_fingerprint()

        input_set_canonical_hash = compute_input_set_canonical_hash(test_inputs)
        exec_fp = compute_execution_fingerprint(
            application_id=spec.application_id,
            ref_target_id=getattr(ref_target, "target_id", "ref_default") if ref_target else getattr(ref_adapter, "name", "ref_default"),
            ref_version=getattr(ref_target, "version", "1.0.0") if ref_target else "1.0.0",
            ref_source_hash=ref_s_hash,
            target_id=getattr(tgt_target, "target_id", "tgt_default") if tgt_target else getattr(target_adapter, "name", "tgt_default"),
            target_version=getattr(tgt_target, "version", "1.0.0") if tgt_target else "1.0.0",
            target_source_hash=tgt_s_hash,
            input_set_hash=input_set_canonical_hash,
            input_count=len(test_inputs),
            policy_id=effective_cert_policy.policy_id,
            policy_fingerprint=policy_fp,
            rule_config_mode=spec.rule_config.mode if (spec and spec.rule_config) else "CONTROLLED",
            legacy_source_identity=legacy_src,
            modern_source_identity=modern_src,
            evaluation_mode=eval_mode,
            specification_fingerprint=spec_fp,
        )
        run.execution_fingerprint = exec_fp
        run.input_set_hash = input_set_canonical_hash
        run.input_set_id = f"INPSET-{spec.application_id}-{input_set_canonical_hash[:8]}"
        run.metadata["policy_fingerprint"] = policy_fp
        run.metadata["effective_policy"] = effective_cert_policy.model_dump()
        self.persistence.save_run(run)

        timings["validation_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
        return spec, ref_adapter, target_adapter, test_inputs

    def _stage_capture_evidence(
        self,
        spec: ApplicationSpec,
        ref_adapter: Any,
        target_adapter: Any,
        test_inputs: list[Any],
        run: WorkflowRun,
        timings: dict[str, float],
    ) -> Any:
        t_stage = time.perf_counter()
        session_id = f"SESS-{run.workflow_run_id}"
        run.evidence_session_id = session_id
        all_evidence_records: list[EvidenceRecord] = []
        manifest_items: list[EvidenceManifestItem] = []
        evaluated_input_cases: list[dict[str, Any]] = []

        ref_exec_ids = []
        tgt_exec_ids = []

        for idx, inp in enumerate(test_inputs):
            inp_vals = getattr(inp, "values", None) or getattr(inp, "input_values", None) or getattr(inp, "data", None) or (inp if isinstance(inp, dict) else {})
            inp_id = getattr(inp, "input_id", f"inp_{idx+1}")

            # Execute reference
            ref_res = ref_adapter.execute(inp_vals) if hasattr(ref_adapter, "execute") else ref_adapter(inp_vals)

            # Strict Fail-Closed Guard: genuine COBOL execution must not fail or crash
            if getattr(ref_res, "execution_status", "") == "EXCEPTION":
                if getattr(ref_adapter, "adapter_type", "") == "cobol_cics":
                    err_msg = getattr(ref_res, "error_message", "Genuine COBOL runtime execution failed")
                    logger.warning(f"Fail-closed guard triggered: genuine COBOL runtime execution failed on input {inp_id}: {err_msg}")
                    return self._fail_run(
                        run,
                        WorkflowErrorCode.CERTIFICATION_INCONCLUSIVE,
                        f"Genuine COBOL runtime execution failed on input '{inp_id}': {err_msg}. "
                        "Authoritative execution evidence could not be obtained from real COBOL program. "
                        "Certification is INCONCLUSIVE and never substitutes synthetic results.",
                        audit_status="PERSISTED",
                    )

            if hasattr(ref_res, "normalized_outputs") and ref_res.normalized_outputs is not None:
                ref_val = ref_res.normalized_outputs
            elif hasattr(ref_res, "raw_outputs") and ref_res.raw_outputs is not None:
                ref_val = ref_res.raw_outputs
            elif hasattr(ref_res, "output"):
                ref_val = ref_res.output
            else:
                ref_val = ref_res

            ref_eid = f"EVID-REF-{run.workflow_run_id[:6]}-{idx+1}"
            ref_exec_id = f"EXEC-REF-{run.workflow_run_id[:6]}-{idx+1}"
            ref_exec_ids.append(ref_exec_id)

            ref_payload = {
                "output": ref_val,
                "input": inp_vals,
                "raw_output": getattr(ref_res, "raw_outputs", ref_val),
            }

            rec_ref = EvidenceRecord(
                evidence_id=ref_eid,
                session_id=session_id,
                execution_id=ref_exec_id,
                application_id=spec.application_id,
                role="reference",
                input_id=inp_id,
                evidence_type=EvidenceType.OUTPUT,
                payload=ref_payload,
                capture_status=EvidenceCaptureStatus.CAPTURED,
                persistence_status=EvidencePersistenceStatus.PERSISTED,
            )
            self.ev_store.save_record(rec_ref)
            all_evidence_records.append(rec_ref)

            manifest_items.append(
                EvidenceManifestItem(
                    evidence_id=ref_eid,
                    evidence_type=EvidenceType.OUTPUT,
                    role="reference",
                    input_id=inp_id,
                    content_hash=rec_ref.content_hash,
                    size_bytes=rec_ref.size_bytes,
                    capture_status=EvidenceCaptureStatus.CAPTURED,
                    persistence_status=EvidencePersistenceStatus.PERSISTED,
                )
            )

            # Execute target
            tgt_res = target_adapter.execute(inp_vals) if hasattr(target_adapter, "execute") else target_adapter(inp_vals)
            if hasattr(tgt_res, "normalized_outputs") and tgt_res.normalized_outputs is not None:
                tgt_val = tgt_res.normalized_outputs
            elif hasattr(tgt_res, "raw_outputs") and tgt_res.raw_outputs is not None:
                tgt_val = tgt_res.raw_outputs
            elif hasattr(tgt_res, "output"):
                tgt_val = tgt_res.output
            else:
                tgt_val = tgt_res

            tgt_eid = f"EVID-TGT-{run.workflow_run_id[:6]}-{idx+1}"
            tgt_exec_id = f"EXEC-TGT-{run.workflow_run_id[:6]}-{idx+1}"
            tgt_exec_ids.append(tgt_exec_id)

            tgt_payload = {
                "output": tgt_val,
                "input": inp_vals,
                "raw_output": getattr(tgt_res, "raw_outputs", tgt_val),
            }

            rec_tgt = EvidenceRecord(
                evidence_id=tgt_eid,
                session_id=session_id,
                execution_id=tgt_exec_id,
                application_id=spec.application_id,
                role="target",
                input_id=inp_id,
                evidence_type=EvidenceType.OUTPUT,
                payload=tgt_payload,
                capture_status=EvidenceCaptureStatus.CAPTURED,
                persistence_status=EvidencePersistenceStatus.PERSISTED,
            )
            self.ev_store.save_record(rec_tgt)
            all_evidence_records.append(rec_tgt)

            manifest_items.append(
                EvidenceManifestItem(
                    evidence_id=tgt_eid,
                    evidence_type=EvidenceType.OUTPUT,
                    role="target",
                    input_id=inp_id,
                    content_hash=rec_tgt.content_hash,
                    size_bytes=rec_tgt.size_bytes,
                    capture_status=EvidenceCaptureStatus.CAPTURED,
                    persistence_status=EvidencePersistenceStatus.PERSISTED,
                )
            )

            evaluated_input_cases.append({
                "input_id": inp_id,
                "input_values": inp_vals,
                "ref_val": ref_val,
                "tgt_val": tgt_val,
                "ref_eid": ref_eid,
                "tgt_eid": tgt_eid,
            })

        # Assemble canonical EvidenceManifest & EvidenceBundle
        input_set_id = run.input_set_id or f"INPSET-{run.workflow_run_id[:8]}"
        input_set_hash = run.input_set_hash or compute_input_set_canonical_hash(test_inputs)

        manifest = EvidenceManifest(
            session_id=session_id,
            correlation_id=run.workflow_run_id,
            application_id=spec.application_id,
            input_set_id=input_set_id,
            input_set_hash=input_set_hash,
            items=manifest_items,
        )

        bundle = EvidenceBundle(
            bundle_id=f"BUNDLE-{run.workflow_run_id}",
            session_id=session_id,
            correlation_id=run.workflow_run_id,
            application_id=spec.application_id,
            input_set_id=input_set_id,
            reference_execution_ids=ref_exec_ids,
            target_execution_ids=tgt_exec_ids,
            manifest=manifest,
            bundle_hash=manifest.bundle_hash,
            records=all_evidence_records,
            persistence_status=EvidencePersistenceStatus.PERSISTED,
        )

        self.ev_store.save_bundle(bundle)

        # Verify bundle integrity
        recomputed_bundle_hash = manifest.compute_bundle_hash()
        if bundle.bundle_hash != recomputed_bundle_hash:
            return self._fail_run(
                run,
                WorkflowErrorCode.EVIDENCE_CAPTURE_FAILED,
                f"EvidenceBundle tamper detection: hash mismatch '{bundle.bundle_hash}' vs '{recomputed_bundle_hash}'.",
            )

        run.evidence_bundle_id = bundle.bundle_id
        timings["evidence_capture_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
        return bundle, all_evidence_records, evaluated_input_cases

    def _stage_evaluate_behavior(
        self,
        spec: ApplicationSpec,
        bundle: EvidenceBundle,
        test_inputs: list[Any],
        run: WorkflowRun,
        timings: dict[str, float],
    ) -> Any:
        t_stage = time.perf_counter()

        # Fail closed immediately if bundle hash does not match manifest
        if not bundle.manifest or bundle.bundle_hash != bundle.manifest.compute_bundle_hash():
            return self._fail_run(
                run,
                WorkflowErrorCode.EVIDENCE_TAMPERED,
                f"EvidenceBundle integrity failure: bundle_hash mismatch detected.",
            )

        # Invoke the authoritative Phase 4 BehavioralEvaluationEngine
        comparison_pol = getattr(spec, "comparison_policy", None) or "default_v2"
        try:
            eval_result = self.eval_eng.evaluate_bundle(
                bundle=bundle,
                policy=comparison_pol,
                verify_integrity=True,
            )
        except Exception as exc:
            logger.error(f"Phase 4 BehavioralEvaluationEngine failed for '{run.workflow_run_id}': {exc}", exc_info=True)
            return self._fail_run(run, WorkflowErrorCode.EVALUATION_FAILED, f"BehavioralEvaluationEngine failed: {str(exc)}")

        if not eval_result or not getattr(eval_result, "evaluation_id", None):
            return self._fail_run(run, WorkflowErrorCode.EVALUATION_FAILED, "EvaluationResult is missing or malformed.")

        # Fail closed on tamper / integrity issues reported by evaluation engine
        if eval_result.metadata and eval_result.metadata.get("integrity_issues_count", 0) > 0:
            return self._fail_run(
                run,
                WorkflowErrorCode.EVIDENCE_TAMPERED,
                f"Behavioral evaluation rejected bundle due to integrity violations: {eval_result.metadata.get('integrity_issues')}",
            )

        # Verify evaluation belongs to current application and inputs
        if getattr(eval_result, "application_id", None) and eval_result.application_id != spec.application_id:
            return self._fail_run(
                run,
                WorkflowErrorCode.EVALUATION_FAILED,
                f"EvaluationResult application_id '{eval_result.application_id}' does not match workflow '{spec.application_id}'.",
            )
        if len(getattr(eval_result, "input_results", [])) != len(test_inputs):
            return self._fail_run(
                run,
                WorkflowErrorCode.EVALUATION_FAILED,
                f"Evaluation total inputs ({len(getattr(eval_result, 'input_results', []))}) != test inputs count ({len(test_inputs)}).",
            )

        # Bind execution identity to EvaluationResult metadata
        if not hasattr(eval_result, "metadata") or eval_result.metadata is None:
            eval_result.metadata = {}
        eval_result.metadata["execution_fingerprint"] = run.execution_fingerprint

        # Persist EvaluationResult to authoritative Phase 4 persistence store
        self.eval_persistence.save_evaluation_result(eval_result)

        run.evaluation_id = eval_result.evaluation_id
        timings["evaluation_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
        return eval_result

    def _stage_evaluate_controlled_mode(
        self,
        spec: ApplicationSpec,
        bundle: EvidenceBundle,
        eval_result: EvaluationResult,
        run: WorkflowRun,
        timings: dict[str, float],
    ) -> Any:
        t_stage = time.perf_counter()
        is_controlled = bool(spec.rule_config and getattr(spec.rule_config, "mode", "").upper() == "CONTROLLED")
        user_rules: list[BusinessRule] = []

        try:
            user_rules = self.rules_registry.list_rules()
        except Exception:
            user_rules = []

        if not user_rules and spec.rule_config and spec.rule_config.rules:
            for r_item in spec.rule_config.rules:
                if isinstance(r_item, BusinessRule):
                    user_rules.append(r_item)
                elif isinstance(r_item, dict):
                    rule_id = str(r_item.get("rule_id", "RULE_UNKNOWN"))
                    name = str(r_item.get("name", rule_id))
                    
                    raw_cond = r_item.get("condition")
                    if isinstance(raw_cond, (RulePredicate, CompoundRuleCondition, UnaryRuleCondition)):
                        cond_node = raw_cond
                    elif isinstance(raw_cond, dict):
                        cond_node = raw_cond
                    elif isinstance(raw_cond, str):
                        cond_str = raw_cond.strip()
                        matched_c = False
                        for sym, op in [
                            (">=", RuleOperator.GTE),
                            ("<=", RuleOperator.LTE),
                            ("==", RuleOperator.EQ),
                            ("!=", RuleOperator.NE),
                            (">", RuleOperator.GT),
                            ("<", RuleOperator.LT),
                        ]:
                            if sym in cond_str:
                                parts = cond_str.split(sym, 1)
                                fld = parts[0].strip()
                                val_str = parts[1].strip()
                                if val_str.lower() == "true":
                                    val = True
                                elif val_str.lower() == "false":
                                    val = False
                                elif val_str.lower() in ("null", "none"):
                                    val = None
                                else:
                                    try:
                                        val = float(val_str) if "." in val_str else int(val_str)
                                    except ValueError:
                                        val = val_str.strip("'\"")
                                cond_node = RulePredicate(field=fld, operator=op, value=val)
                                matched_c = True
                                break
                        if not matched_c:
                            cond_node = RulePredicate(field=cond_str, operator=RuleOperator.EXISTS)
                    else:
                        cond_node = RulePredicate(field="unknown", operator=RuleOperator.EXISTS)

                    raw_conseq = r_item.get("expected_behavior") or r_item.get("consequence")
                    if isinstance(raw_conseq, ExpectedBehavior):
                        exp_behavior = raw_conseq
                    elif isinstance(raw_conseq, dict):
                        exp_behavior = ExpectedBehavior(**raw_conseq)
                    elif isinstance(raw_conseq, str):
                        c_str = raw_conseq.strip()
                        matched_b = False
                        for sym in ["==", ">=", "<=", "!=", ">", "<"]:
                            if sym in c_str:
                                parts = c_str.split(sym, 1)
                                tfld = parts[0].strip()
                                tval_str = parts[1].strip()
                                if tval_str.lower() == "true":
                                    tval = True
                                elif tval_str.lower() == "false":
                                    tval = False
                                elif tval_str.lower() in ("null", "none"):
                                    tval = None
                                else:
                                    try:
                                        tval = float(tval_str) if "." in tval_str else int(tval_str)
                                    except ValueError:
                                        tval = tval_str.strip("'\"")
                                exp_behavior = ExpectedBehavior(
                                    behavior_type=ExpectedBehaviorType.RETURN_VALUE,
                                    target_field=tfld,
                                    expected_value=tval,
                                )
                                matched_b = True
                                break
                        if not matched_b:
                            if c_str.lower() in ("accept", "pass", "ok"):
                                exp_behavior = ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT)
                            elif c_str.lower() in ("reject", "fail", "error"):
                                exp_behavior = ExpectedBehavior(behavior_type=ExpectedBehaviorType.REJECT)
                            else:
                                exp_behavior = ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT)
                    else:
                        exp_behavior = ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT)

                    raw_sev = str(r_item.get("severity", "CRITICAL")).upper()
                    sev = RuleSeverity[raw_sev] if raw_sev in RuleSeverity.__members__ else RuleSeverity.CRITICAL

                    user_rules.append(
                        BusinessRule(
                            rule_id=rule_id,
                            name=name,
                            condition=cond_node,
                            expected_behavior=exp_behavior,
                            severity=sev,
                            source=RuleSource.USER_DEFINED,
                        )
                    )

        if is_controlled or len(user_rules) > 0:
            try:
                ctrl_result = self.controlled_eng.evaluate_controlled_mode(
                    rules=user_rules,
                    bundle=bundle,
                    phase4_result=eval_result,
                )
                if not ctrl_result:
                    return self._fail_run(
                        run,
                        WorkflowErrorCode.RULE_VIOLATION_FAIL,
                        "Phase 5 ControlledAssessmentEngine returned null result for controlled application.",
                    )

                run.metadata["controlled_evaluation_id"] = ctrl_result.evaluation_id
                run.metadata["controlled_compliance_verdict"] = (
                    ctrl_result.overall_verdict.value
                    if hasattr(ctrl_result.overall_verdict, "value")
                    else str(ctrl_result.overall_verdict)
                )
                run.metadata["phase5_applicable"] = True
                timings["controlled_mode_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
                return user_rules, ctrl_result
            except Exception as exc:
                logger.error(f"Controlled mode evaluation error for '{run.workflow_run_id}': {exc}", exc_info=True)
                return self._fail_run(
                    run,
                    WorkflowErrorCode.RULE_VIOLATION_FAIL,
                    f"Controlled mode evaluation failed: {str(exc)}",
                )

        run.metadata["phase5_applicable"] = False
        run.metadata["controlled_mode_status"] = "NOT_APPLICABLE"
        timings["controlled_mode_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
        return user_rules, None

    def _stage_discover_rules(
        self,
        spec: ApplicationSpec,
        bundle: EvidenceBundle,
        eval_result: EvaluationResult,
        request: WorkflowRunRequest,
        run: WorkflowRun,
        timings: dict[str, float],
    ) -> Any:
        t_stage = time.perf_counter()
        enable_disc = (
            getattr(request, "enable_discovery", False)
            or getattr(spec, "enable_discovery", False)
            or getattr(request, "evaluation_mode", "") == "FULL_BEACON"
            or bool(spec.rule_config and getattr(spec.rule_config, "mode", "") == "FULL_BEACON")
        )
        if enable_disc:
            try:
                disc_result = self.discovery_eng.discover_rules(
                    bundle=bundle,
                    phase4_result=eval_result,
                    persist=True,
                )
                if disc_result:
                    run.metadata["discovery_id"] = disc_result.discovery_id
                    run.metadata["discovered_candidate_count"] = len(disc_result.candidates)
                    run.metadata["phase6_applicable"] = True
                    timings["discovery_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
                    return disc_result
                else:
                    run.metadata["discovery_status"] = "DISCOVERY_UNAVAILABLE"
                    run.metadata["phase6_applicable"] = True
                    timings["discovery_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
                    return None
            except Exception as exc:
                logger.warning(f"Rule discovery failed for '{run.workflow_run_id}': {exc}")
                run.metadata["discovery_status"] = "DISCOVERY_UNAVAILABLE"
                run.metadata["phase6_applicable"] = True
                timings["discovery_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
                return None

        run.metadata["phase6_applicable"] = False
        timings["discovery_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
        return None

    def _stage_reconcile_oracles(
        self,
        spec: ApplicationSpec,
        user_rules: list[BusinessRule],
        disc_result: Optional[DiscoveryResult],
        bundle: EvidenceBundle,
        run: WorkflowRun,
        timings: dict[str, float],
    ) -> Any:
        t_stage = time.perf_counter()

        # Authoritative reconciliation through Phase 7 RuleReconciliationEngine
        recon_oracle_set: Optional[OracleSet] = None
        try:
            recon_res = self.reconcile_eng.reconcile(
                application_id=spec.application_id,
                user_rules=user_rules,
                discovery_result=disc_result,
                evidence_bundle=bundle,
                session_id=bundle.session_id,
                persist=True,
            )
            if recon_res and recon_res.oracle_set and (
                len(getattr(recon_res.oracle_set, "rules", [])) > 0
                or len(getattr(recon_res.oracle_set, "oracles", [])) > 0
            ):
                recon_oracle_set = recon_res.oracle_set
        except Exception as exc:
            logger.debug(f"Rule reconciliation note for '{spec.application_id}': {exc}")

        oracle_set = recon_oracle_set

        if not oracle_set:
            return self._fail_run(
                run,
                WorkflowErrorCode.ORACLE_AUTHORITY_MISSING,
                f"No authoritative OracleSet produced by reconciliation for application '{spec.application_id}'.",
            )

        oset_id = getattr(oracle_set, "oracle_set_id", "")
        oset_hash = getattr(oracle_set, "oracle_set_hash", "") or getattr(oracle_set, "fingerprint", "")
        if not oset_id or not oset_hash:
            return self._fail_run(
                run,
                WorkflowErrorCode.ORACLE_AUTHORITY_MISSING,
                f"OracleSet authority is missing required identity or cryptographic hash.",
            )

        if getattr(oracle_set, "application_id", None) and oracle_set.application_id != spec.application_id:
            return self._fail_run(
                run,
                WorkflowErrorCode.ORACLE_AUTHORITY_MISSING,
                f"OracleSet application_id '{oracle_set.application_id}' does not match workflow '{spec.application_id}'.",
            )

        # Verify no empty OracleSet is treated as valid certification authority
        rules_count = len(getattr(oracle_set, "rules", [])) + len(getattr(oracle_set, "oracles", []))
        if rules_count == 0:
            return self._fail_run(
                run,
                WorkflowErrorCode.ORACLE_AUTHORITY_MISSING,
                f"OracleSet '{oset_id}' contains zero rules/oracles (empty oracle authority forbidden).",
            )

        # Bind execution identity to OracleSet metadata
        new_meta = dict(getattr(oracle_set, "metadata", {}) or {})
        new_meta["execution_fingerprint"] = run.execution_fingerprint
        oracle_set = oracle_set.model_copy(update={"metadata": new_meta})
        self.rec_persistence.save_oracle_set(oracle_set)

        run.oracle_set_id = oset_id
        run.oracle_set_hash = oset_hash
        timings["oracle_resolution_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
        return oracle_set

    def _stage_resolve_thresholds(
        self,
        spec: ApplicationSpec,
        bundle: EvidenceBundle,
        eval_result: EvaluationResult,
        all_evidence_records: list[EvidenceRecord],
        run: WorkflowRun,
        timings: dict[str, float],
    ) -> Any:
        t_stage = time.perf_counter()

        # 1. Extract clean numerical reference observations (Anti-Target-Contamination: Reference ONLY)
        clean_observations: list[float] = []
        ev_ids: list[str] = []
        ref_exec_ids = set(bundle.reference_execution_ids) if bundle else set()

        for rec in (all_evidence_records or []):
            rec_role = getattr(rec, "role", "")
            rec_exec_id = getattr(rec, "execution_id", "")
            if rec_role == "reference" or (rec_exec_id and rec_exec_id in ref_exec_ids):
                rec_id = getattr(rec, "record_id", None) or getattr(rec, "evidence_id", "")
                if rec_id:
                    ev_ids.append(rec_id)
                out = getattr(rec, "output", None)
                if out is None and hasattr(rec, "payload") and isinstance(rec.payload, dict):
                    out = rec.payload.get("output")
                rec_obs_found = False
                if isinstance(out, (int, float)) and not (isinstance(out, bool) or math.isnan(out) or math.isinf(out)):
                    clean_observations.append(float(out))
                    rec_obs_found = True
                elif isinstance(out, dict):
                    for v in out.values():
                        if isinstance(v, (int, float)) and not (isinstance(v, bool) or math.isnan(v) or math.isinf(v)):
                            clean_observations.append(float(v))
                            rec_obs_found = True
                if not rec_obs_found and out is not None:
                    # In accordance with Normative Contract (PDF Sections 4.1 & 9):
                    # For discrete/categorical reference baseline executions, reference deviation is 0.0.
                    clean_observations.append(0.0)

        if not clean_observations and eval_result and getattr(eval_result, "input_results", None):
            for item_res in eval_result.input_results:
                ref_v = getattr(item_res, "reference_value", None)
                rec_obs_found = False
                if isinstance(ref_v, (int, float)) and not (isinstance(ref_v, bool) or math.isnan(ref_v) or math.isinf(ref_v)):
                    clean_observations.append(float(ref_v))
                    rec_obs_found = True
                elif isinstance(ref_v, dict):
                    for v in ref_v.values():
                        if isinstance(v, (int, float)) and not (isinstance(v, bool) or math.isnan(v) or math.isinf(v)):
                            clean_observations.append(float(v))
                            rec_obs_found = True
                if not rec_obs_found and ref_v is not None:
                    clean_observations.append(0.0)

        # 2. Retrieve authoritative policy or derive through advisory proposal + deterministic validation
        th_policy = self.thresh_persistence.get_policy(f"POL-{spec.application_id}")
        if not th_policy:
            th_policy = self.thresh_persistence.get_policy(spec.application_id)

        if not th_policy:
            # Check for candidate advisory strategy proposal in metadata
            ai_proposal_dict = (getattr(spec, "metadata", {}) or {}).get("threshold_strategy_proposal")
            proposal: Optional[ThresholdStrategyProposal] = None
            if ai_proposal_dict and isinstance(ai_proposal_dict, dict):
                try:
                    proposal = ThresholdStrategyProposal(**ai_proposal_dict)
                except Exception as pe:
                    logger.warning(f"Invalid advisory threshold proposal in metadata: {pe}")

            obs_count = len(clean_observations)
            if not proposal:
                # Derive evidence-grounded candidate proposal (PDF Sections 9 & 12)
                if obs_count >= 5:
                    is_zero_variance = (len(set(clean_observations)) <= 1)
                    proposal = ThresholdStrategyProposal(
                        strategy=ThresholdStrategy.EVIDENCE_DERIVED,
                        metric=DifferenceMetric.ABSOLUTE_DIFF,
                        candidate_parameters={"k": 1.5, "maximum_bound": 0.0 if is_zero_variance else None},
                        estimator=EstimatorType.IQR_ROBUST,
                        minimum_samples=min(obs_count, 5),
                        reasoning=f"Auto-derived proposal: empirical sample count ({obs_count} >= 5) permits robust IQR estimation.",
                        evidence_summary={"sample_count": obs_count, "zero_variance": is_zero_variance},
                        confidence=0.95,
                    )
                elif obs_count > 0:
                    is_zero_variance = (len(set(clean_observations)) <= 1)
                    proposal = ThresholdStrategyProposal(
                        strategy=ThresholdStrategy.EVIDENCE_DERIVED,
                        metric=DifferenceMetric.ABSOLUTE_DIFF,
                        candidate_parameters={"k": 1.0, "maximum_bound": 0.0 if is_zero_variance else None},
                        estimator=EstimatorType.RANGE_FRACTION,
                        minimum_samples=1,
                        reasoning=f"Auto-derived proposal: small sample count ({obs_count} < 5) uses RANGE bounded estimation.",
                        evidence_summary={"sample_count": obs_count, "zero_variance": is_zero_variance},
                        confidence=0.80,
                    )

            if proposal:
                val_policy = ThresholdValidationPolicy(
                    allowed_strategies=[
                        ThresholdStrategy.EVIDENCE_DERIVED,
                        ThresholdStrategy.STATISTICAL,
                        ThresholdStrategy.FIXED,
                    ],
                    min_k_multiplier=0.1,
                    max_k_multiplier=10.0,
                    min_required_samples=1,
                )
                is_valid, validated_pol, reason = val_policy.validate_proposal(
                    proposal=proposal,
                    sample_count=obs_count,
                    policy_id=f"POL-{spec.application_id}",
                )
                if is_valid and validated_pol:
                    th_policy = validated_pol
                else:
                    logger.warning(f"Threshold proposal validation note: {reason}")
            else:
                meta_th = (getattr(spec, "metadata", {}) or {}).get("threshold_policy")
                if meta_th and isinstance(meta_th, dict):
                    th_policy = ThresholdPolicy(**meta_th)
                else:
                    return self._fail_run(
                        run,
                        WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING,
                        f"Unable to resolve evidence-driven threshold: insufficient reference observations and no explicit threshold policy registered for '{spec.application_id}'. Magic/arbitrary fallback tolerances are forbidden.",
                    )
            self.thresh_persistence.save_policy(th_policy)

        # 3. Deterministic Threshold Resolution Engine Execution
        threshold_res = self.thresh_eng.resolve_threshold(
            metric=th_policy.metric,
            policy=th_policy,
            reference_observations=clean_observations,
            evidence_ids=ev_ids,
        )
        if not threshold_res or not getattr(threshold_res, "resolution_id", None):
            return self._fail_run(
                run,
                WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING,
                f"Failed to resolve threshold for metric '{th_policy.metric.value}'.",
            )

        if threshold_res.status == ThresholdStatus.INSUFFICIENT_EVIDENCE and not threshold_res.fallback_used:
            return self._fail_run(
                run,
                WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING,
                f"Threshold resolution failed-closed: insufficient reference samples ({threshold_res.sample_count} < {threshold_res.minimum_required_samples}) and no verified fallback policy. Arbitrary tolerance injection is forbidden.",
            )

        # Bind threshold to execution and oracle
        if not hasattr(threshold_res, "provenance") or not isinstance(threshold_res.provenance, dict):
            threshold_res.provenance = {}
        threshold_res.provenance["execution_fingerprint"] = run.execution_fingerprint
        threshold_res.provenance["oracle_set_id"] = getattr(run, "oracle_set_id", "")
        threshold_res.provenance["oracle_set_hash"] = getattr(run, "oracle_set_hash", "")

        # 4. Strict Authority Check: threshold fingerprint verification
        expected_fp = threshold_res.compute_fingerprint()
        if threshold_res.fingerprint != expected_fp:
            return self._fail_run(
                run,
                WorkflowErrorCode.THRESHOLD_FINGERPRINT_MISMATCH,
                f"Threshold fingerprint mismatch: expected '{expected_fp}', found '{threshold_res.fingerprint}'.",
            )

        self.thresh_persistence.save_resolution(threshold_res)

        # 5. Re-verify persisted resolution
        persisted_res = self.thresh_persistence.get_resolution(threshold_res.resolution_id)
        if not persisted_res or persisted_res.fingerprint != threshold_res.fingerprint:
            return self._fail_run(
                run,
                WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING,
                f"Persisted threshold resolution verification failed for resolution '{threshold_res.resolution_id}'.",
            )

        run.threshold_resolution_id = threshold_res.resolution_id
        run.threshold_resolution_fingerprint = threshold_res.fingerprint
        timings["threshold_resolution_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
        return threshold_res

    def _stage_execute_certification(
        self,
        spec: ApplicationSpec,
        ref_adapter: Any,
        target_adapter: Any,
        test_inputs: list[Any],
        eval_result: EvaluationResult,
        oracle_set: OracleSet,
        threshold_res: ThresholdResolution,
        request: WorkflowRunRequest,
        run: WorkflowRun,
        timings: dict[str, float],
    ) -> Any:
        t_stage = time.perf_counter()

        # 1. Strict pre-certification cross-binding verification via central verifier
        pre_verify = verify_execution_authority_chain(
            execution_fingerprint=run.execution_fingerprint,
            application_id=spec.application_id,
            eval_result=eval_result,
            oracle_set=oracle_set,
            threshold_res=threshold_res,
            artifact=None,
            require_artifact=False,
            require_audit=False,
        )
        if not pre_verify.is_valid:
            return self._fail_run(
                run,
                pre_verify.error_code or WorkflowErrorCode.CERTIFICATION_FAILED,
                f"Pre-certification authority verification failed: {pre_verify.failure_reason}",
            )

        # 2. Authoritative Effective Certification Policy
        eff_meta = (run.metadata or {}).get("effective_policy")
        if eff_meta and isinstance(eff_meta, dict):
            cert_policy = CertificationPolicy(**eff_meta)
        else:
            eval_mode = spec.rule_config.mode if (spec and spec.rule_config) else "CONTROLLED"
            cert_policy = certification_policy_resolver.resolve_effective_policy(
                application_id=spec.application_id,
                evaluation_mode=eval_mode,
            )

        # 3. Execution Context Cross-Binding
        cert_ctx = CertificationContext(
            benchmark_id=spec.application_id,
            benchmark_name=spec.name,
            benchmark_version=spec.version,
            legacy_implementation_id=getattr(ref_adapter, "name", "legacy_ref"),
            legacy_implementation_hash=getattr(ref_adapter, "implementation_hash", ""),
            modernized_implementation_id=getattr(target_adapter, "name", "modern_target"),
            modernized_implementation_hash=getattr(target_adapter, "implementation_hash", ""),
            oracle_set_id=getattr(oracle_set, "oracle_set_id", ""),
            oracle_set_hash=getattr(oracle_set, "oracle_set_hash", "") or getattr(oracle_set, "fingerprint", ""),
            evaluation_mode=cert_policy.evaluation_mode or "CONTROLLED",
            policy_id=cert_policy.policy_id,
            policy_version=cert_policy.version,
            policy_hash=cert_policy.policy_hash or cert_policy.compute_hash(),
            policy_min_equivalence_score=cert_policy.min_equivalence_score,
            policy_min_oracle_coverage=cert_policy.min_oracle_coverage,
            policy_allow_warnings=cert_policy.allow_warnings,
            execution_fingerprint=run.execution_fingerprint or "",
            evaluation_result_id=eval_result.evaluation_id,
            threshold_resolution_id=threshold_res.resolution_id,
            threshold_resolution_fingerprint=threshold_res.fingerprint,
        )

        artifact = self.cert_eng.certify(
            context=cert_ctx,
            policy=cert_policy,
            evaluation_result=eval_result,
            oracle_set=oracle_set,
            threshold_resolution=threshold_res,
        )

        if not artifact or not getattr(artifact, "certification_id", None):
            return self._fail_run(
                run,
                WorkflowErrorCode.CERTIFICATION_FAILED,
                "CertificationEngine failed to produce a valid CertificationArtifact.",
            )

        # 4. Comprehensive post-certification authority chain verification
        post_verify = verify_execution_authority_chain(
            execution_fingerprint=run.execution_fingerprint,
            application_id=spec.application_id,
            eval_result=eval_result,
            oracle_set=oracle_set,
            threshold_res=threshold_res,
            artifact=artifact,
            require_artifact=True,
            require_audit=False,
        )
        if not post_verify.is_valid:
            return self._fail_run(
                run,
                post_verify.error_code or WorkflowErrorCode.CERTIFICATION_FAILED,
                f"Post-certification authority chain verification failed: {post_verify.failure_reason}",
            )

        run.certification_id = artifact.certification_id
        status_str = artifact.status.value if hasattr(artifact.status, "value") else str(artifact.status)
        run.certification_status = status_str
        run.certification_score = artifact.score
        timings["certification_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
        return artifact

    def _stage_generate_explanation(
        self,
        artifact: CertificationArtifact,
        eval_result: EvaluationResult,
        oracle_set: OracleSet,
        threshold_res: ThresholdResolution,
        all_evidence_records: list[EvidenceRecord],
        request: WorkflowRunRequest,
        run: WorkflowRun,
    ) -> Optional[dict[str, Any]]:
        if not request.explain:
            return None

        t_stage = time.perf_counter()

        try:
            exp_req = ExplanationRequest(
                mode=getattr(request, "explanation_mode", "assisted") or "assisted",
                use_company_knowledge=getattr(request, "use_company_knowledge", False),
            )
            explanation_res = self.intel_eng.generate_explanation(
                certification_id=artifact.certification_id,
                artifact=artifact,
                evidence_records=all_evidence_records,
                evaluation_result=eval_result,
                oracle_set=oracle_set,
                threshold_resolution=threshold_res,
                request=exp_req,
            )

            run.explanation_id = getattr(explanation_res, "explanation_id", None)
            exp_dict = explanation_res.model_dump(mode="json") if hasattr(explanation_res, "model_dump") else dict(explanation_res)
            if "headline" not in exp_dict and "overall_verdict" in exp_dict:
                exp_dict["headline"] = f"Behavioral Equivalence Verdict: {exp_dict['overall_verdict']}"
            if "status_rationale" not in exp_dict and "executive_summary" in exp_dict:
                exp_dict["status_rationale"] = exp_dict["executive_summary"]
            if "key_findings" not in exp_dict or not exp_dict["key_findings"]:
                exp_dict["key_findings"] = [
                    rec.get("description", rec.get("title", ""))
                    for rec in exp_dict.get("investigation_recommendations", [])
                    if isinstance(rec, dict) and (rec.get("description") or rec.get("title"))
                ]
            return exp_dict

        except Exception as exc:
            logger.warning(f"Non-blocking grounded explanation failure for '{run.workflow_run_id}': {exc}")
            return {
                "status": "EXPLANATION_FAILED",
                "error": str(exc),
                "grounding_status": "NOT_GROUNDED",
            }

    def _stage_persist_and_audit(
        self,
        artifact: CertificationArtifact,
        test_inputs: list[Any],
        evaluated_input_cases: list[dict[str, Any]],
        spec: ApplicationSpec,
        threshold_res: ThresholdResolution,
        eval_result: EvaluationResult,
        run: WorkflowRun,
        timings: dict[str, float],
    ) -> Any:
        t_stage = time.perf_counter()

        # 1. Build canonical CertificationInputSet
        input_set_id = f"INPSET-{artifact.certification_id}"
        input_set_hash = compute_input_set_canonical_hash(test_inputs)
        input_set = CertificationInputSet(
            input_set_id=input_set_id,
            version=1,
            generator_type="canonical_workflow",
            input_count=len(test_inputs),
            canonical_hash=input_set_hash,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        # 2. Derive CertificationCases strictly from authoritative EvaluationResult & Artifact using input_id mapping
        input_data_map = {c["input_id"]: c for c in evaluated_input_cases}
        cases_to_save: list[CertificationCase] = []

        for idx, item_res in enumerate(eval_result.input_results):
            inp_id = item_res.input_id
            is_equiv = (item_res.verdict == EvaluationVerdict.EQUIVALENT)
            cls_str = "MATCH" if is_equiv else "MODERN_REGRESSION"
            case_data = input_data_map.get(inp_id, {})
            inp_vals = case_data.get("input_values", getattr(test_inputs[idx], "values", test_inputs[idx]) if idx < len(test_inputs) else {})
            inp_json = json.dumps(inp_vals, sort_keys=True, default=str)
            legacy_val = case_data.get("ref_val", "")
            modern_val = case_data.get("tgt_val", "")
            legacy_out_json = json.dumps(legacy_val, sort_keys=True, default=str)
            modern_out_json = json.dumps(modern_val, sort_keys=True, default=str)

            cases_to_save.append(
                CertificationCase(
                    case_id=f"CASE-{artifact.certification_id}-{idx+1}",
                    run_id=artifact.certification_id,
                    input_set_id=input_set_id,
                    case_index=idx,
                    input_id=inp_id,
                    input_json=inp_json,
                    input_hash=hashlib.sha256(inp_json.encode()).hexdigest(),
                    legacy_output_json=legacy_out_json,
                    modern_output_json=modern_out_json,
                    execution_time_ms=0.0,
                    oracle_result="PASS" if is_equiv else "VIOLATED",
                    classification=cls_str,
                    severity="none" if is_equiv else "medium",
                )
            )

        # 3. Atomically persist CertificationInputSet, Cases, and Artifact in a single SQLite transaction
        self.cert_repo.save_certification_run_atomic(
            input_set=input_set,
            cases=cases_to_save,
            artifact=artifact,
        )

        # 4. Verify persisted artifact and cases
        persisted_art = self.cert_repo.get_artifact(artifact.certification_id)
        if not persisted_art or persisted_art.artifact_hash != artifact.artifact_hash:
            raise WorkflowExecutionError(
                WorkflowErrorCode.PERSISTENCE_FAILED,
                f"Persisted artifact verification failed for '{artifact.certification_id}'."
            )
        persisted_cases = self.cert_repo.get_cases(artifact.certification_id)
        if len(persisted_cases) != len(cases_to_save):
            raise WorkflowExecutionError(
                WorkflowErrorCode.PERSISTENCE_FAILED,
                f"Persisted cases count mismatch: expected {len(cases_to_save)}, found {len(persisted_cases)}."
            )
        run.certification_id = artifact.certification_id
        run.finalization_state = FinalizationState.CERTIFICATION_VERIFIED
        self.persistence.save_run(run)

        # 5. Mandatory structured audit event logging
        logged_event = audit_logger.log(
            project_id=run.application_id,
            action=AuditAction.CERTIFICATION_COMPLETE,
            status="SUCCESS" if artifact.status == CertificationStatus.CERTIFIED else "FAILED",
            certification_id=artifact.certification_id,
            details={
                "workflow_run_id": run.workflow_run_id,
                "artifact_hash": artifact.artifact_hash,
                "unique_input_count": len(cases_to_save),
                "threshold_resolution_id": getattr(artifact, "threshold_resolution_id", None) or (artifact.context.threshold_resolution_id if artifact.context else None),
                "oracle_set_id": artifact.oracle_set_id,
                "evaluation_id": eval_result.evaluation_id,
                "target_index": getattr(artifact.context, "target_index", 0) if artifact.context else 0,
                "score": artifact.score,
                "user_id": run.metadata.get("user_id", "system"),
            },
        )
        if not logged_event:
            raise WorkflowExecutionError(
                WorkflowErrorCode.PERSISTENCE_FAILED,
                f"Mandatory audit logging failed for certification '{artifact.certification_id}'."
            )
        event_id = getattr(logged_event, "event_id", str(logged_event))

        # 6. Verify audit persistence from storage
        audit_events = audit_logger.list_events(certification_id=artifact.certification_id)
        audit_verified = any(
            (getattr(e, "event_id", None) == event_id or getattr(e, "certification_id", None) == artifact.certification_id)
            for e in audit_events
        )
        if not audit_verified:
            raise WorkflowExecutionError(
                WorkflowErrorCode.PERSISTENCE_FAILED,
                f"Mandatory audit verification failed for certification '{artifact.certification_id}'."
            )
        run.metadata["audit_persisted"] = True
        run.finalization_state = FinalizationState.AUDIT_VERIFIED
        self.persistence.save_run(run)

        # 7. Durable Finalization Pending
        run.finalization_state = FinalizationState.FINALIZATION_PENDING
        self.persistence.save_run(run)

        # 8. Finalize persistent Stage-B idempotency reservation
        self.idempotency_mgr.finalize_stage_b(
            execution_fingerprint=run.execution_fingerprint,
            run_id=run.workflow_run_id,
            status="COMPLETED",
            finalization_state="IDEMPOTENCY_FINALIZED",
            request_fingerprint=run.request_fingerprint,
        )
        run.finalization_state = FinalizationState.IDEMPOTENCY_FINALIZED
        self.persistence.save_run(run)

        # 9. Mark workflow COMPLETED via centralized state machine
        self.transition_state(
            run,
            WorkflowState.COMPLETED,
            reason="Certification, mandatory audit, and Stage-B idempotency durably finalized",
            metadata={"audit_persisted": True}
        )
        run.finalization_state = FinalizationState.COMPLETED
        self.persistence.save_run(run)
        timings["persistence_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
        return "PERSISTED"

    def _fail_run(
        self,
        run: WorkflowRun,
        error_code: WorkflowErrorCode,
        error_message: str,
        audit_status: str = "FAILED",
    ) -> WorkflowResult:
        """Helper to fail a WorkflowRun in a fail-closed, auditable state."""
        run.error_code = error_code
        run.error_message = error_message
        try:
            self.transition_state(
                run,
                WorkflowState.FAILED,
                reason=f"Failure: {error_code.value}: {error_message}",
                metadata={"error_code": error_code.value, "error_message": error_message}
            )
        except Exception as exc:
            logger.error(f"State transition to FAILED failed for run '{run.workflow_run_id}': {exc}")
            audit_status = "PERSISTENCE_FAILED"
            if not hasattr(run, "metadata") or run.metadata is None:
                run.metadata = {}
            run.metadata["persistence_failure"] = str(exc)
            error_message = f"{error_message} [STATE TRANSITION FAILED: {exc}]"
            try:
                run.completed_at = datetime.now(timezone.utc).isoformat()
                self.persistence.save_run(run)
            except Exception as save_err:
                logger.error(f"Failed to save failed run state '{run.workflow_run_id}': {save_err}")
                error_message = f"{error_message} [SAVE FAILED: {save_err}]"

        try:
            self.idempotency_mgr.finalize_run(
                fingerprint=run.request_fingerprint,
                run_id=run.workflow_run_id,
                status="FAILED",
                execution_fingerprint=run.execution_fingerprint,
                finalization_state="FAILED",
            )
        except Exception as idemp_err:
            logger.error(f"Failed to finalize idempotency reservation for failed run '{run.workflow_run_id}': {idemp_err}")
            audit_status = "PERSISTENCE_FAILED"
            if not hasattr(run, "metadata") or run.metadata is None:
                run.metadata = {}
            run.metadata["persistence_failure"] = str(idemp_err)
            error_message = f"{error_message} [FAILURE PERSISTENCE NOT CONFIRMED: {idemp_err}]"

        log_operational_event(
            event="workflow_failed",
            logger_name="beacon.workflow",
            operation="CERTIFICATION_WORKFLOW",
            step="FAILED",
            workflow_run_id=run.workflow_run_id,
            application_id=run.application_id,
            error_code=error_code.value,
            message=f"[WORKFLOW FAILED] run={run.workflow_run_id} | err={error_code.value}: {error_message}",
        )

        return WorkflowResult(
            workflow_run_id=run.workflow_run_id,
            application_id=run.application_id,
            state=run.state,
            status="FAILED",
            certified=False,
            equivalence_score=None,
            audit_status=audit_status,
            error_code=error_code,
            error_message=error_message,
        )

    def _verify_and_build_existing_run(self, run: WorkflowRun) -> Optional[WorkflowResult]:
        """Verifies the complete authoritative chain of an existing completed run before reusing."""
        if run.state != WorkflowState.COMPLETED:
            return None

        if not run.certification_id:
            return None

        if not run.execution_fingerprint:
            return None

        try:
            artifact = self.cert_repo.get_artifact(run.certification_id)
            if not artifact:
                return None

            eval_res = self.eval_persistence.get_evaluation_result(run.evaluation_id) if run.evaluation_id else None
            oset = self.rec_persistence.get_oracle_set(run.oracle_set_id) if run.oracle_set_id else None
            res = self.thresh_persistence.get_resolution(run.threshold_resolution_id) if run.threshold_resolution_id else None
            cases = self.cert_repo.list_certification_cases(run.certification_id)
            audit_events = audit_logger.list_events(certification_id=run.certification_id)

            # Strict cross-binding and integrity verification via central verifier
            verify_res = verify_execution_authority_chain(
                execution_fingerprint=run.execution_fingerprint,
                application_id=run.application_id,
                eval_result=eval_res,
                oracle_set=oset,
                threshold_res=res,
                artifact=artifact,
                cases=cases,
                audit_events=audit_events,
                require_artifact=True,
                require_audit=True,
            )
            if not verify_res.is_valid:
                logger.warning(f"Authority chain verification rejected existing run '{run.workflow_run_id}': {verify_res.failure_reason}")
                return None

            return WorkflowResult(
                workflow_run_id=run.workflow_run_id,
                application_id=run.application_id,
                state=run.state,
                status=run.certification_status or "UNKNOWN",
                certified=run.certification_status == "CERTIFIED",
                equivalence_score=run.certification_score,
                artifact_id=run.certification_id,
                artifact_hash=artifact.artifact_hash,
                threshold_resolution_id=run.threshold_resolution_id,
                threshold_resolution_fingerprint=run.threshold_resolution_fingerprint,
                unique_input_count=artifact.metrics.unique_input_count if artifact.metrics else len(cases),
                regressions_count=len(artifact.regressions) if artifact.regressions else 0,
                regressions=[r.model_dump(mode="json") for r in artifact.regressions] if artifact.regressions else [],
                explanation=None,
                audit_status="PERSISTED",
                timings_ms=run.stage_timings_ms,
            )
        except Exception as e:
            logger.warning(f"Failed to verify existing completed run '{run.workflow_run_id}': {e}")
            return None

    def _build_result_from_existing_run(self, run: WorkflowRun) -> Optional[WorkflowResult]:
        """Alias for _verify_and_build_existing_run."""
        return self._verify_and_build_existing_run(run)


workflow_engine = CanonicalV2WorkflowEngine()
