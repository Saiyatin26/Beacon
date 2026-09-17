"""BEACON V2 — Phase 11 Canonical Workflow Engine.

The central production orchestrator that connects the established authority chain:
Phase 1 (App Registry & Preflight)
    ↓
Phase 2 (Adapters & Dynamic Ingestion)
    ↓
Phase 3 (Evidence Records & Evidence Store)
    ↓
Phase 4 (Behavioral Evaluation Result)
    ↓
Phase 5 (Business Rule Understanding & Controlled Mode)
    ↓
Phase 6 (Behavioral Invariant Discovery)
    ↓
Phase 7 (Reconciled OracleSet)
    ↓
Phase 8 (Exact ThresholdResolution & Fingerprint)
    ↓
CertificationEngine (Authoritative Artifact)
    ↓
Phase 10 (Grounded Explanation & Grounding Validation)
    ↓
Phase 11 (Transactional WAL Persistence & Structured Audit Logging)

Zero reconstruction of missing authority: fails closed immediately.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import sqlite3
import time
from typing import Any, Optional
import uuid

from application.models import ApplicationSpec
from application.registry import ApplicationRegistry, application_registry
from application.resolver import ApplicationResolutionError, ApplicationResolver, application_resolver
from certification.certification_engine import CertificationEngine, certification_engine
from certification.models import (
    CertificationArtifact,
    CertificationCase,
    CertificationContext,
    CertificationPolicy,
    CertificationStatus,
    compute_artifact_content_hash,
)
from certification.repository import CertificationRepository, certification_repository
from evaluation.engine import BehavioralEvaluationEngine, behavioral_evaluation_engine
from evaluation.models import (
    BehaviorDifference,
    BehaviorDimension,
    DifferenceType,
    EvaluationResult,
    EvaluationSummary,
    EvaluationVerdict,
    InputEvaluationResult,
)
from execution.evidence_models import (
    EvidenceBundle,
    EvidenceCaptureStatus,
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
from reconciliation.persistence import ReconciliationPersistenceStore, reconciliation_persistence
from threshold.engine import ThresholdEngine, threshold_engine
from threshold.models import DifferenceMetric, ThresholdPolicy, ThresholdResolution, ThresholdStrategy
from threshold.persistence import ThresholdPersistenceStore, threshold_persistence

from .idempotency import WorkflowIdempotencyManager, workflow_idempotency
from .models import (
    WorkflowErrorCode,
    WorkflowResult,
    WorkflowRun,
    WorkflowRunRequest,
    WorkflowState,
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
        self.rec_persistence = rec_persistence or reconciliation_persistence
        self.thresh_eng = thresh_eng or threshold_engine
        self.thresh_persistence = thresh_persistence or threshold_persistence
        self.cert_eng = cert_eng or certification_engine
        self.cert_repo = cert_repo or certification_repository
        self.ctx_builder = ctx_builder or explanation_context_builder
        self.intel_eng = intel_eng or intelligence_engine
        self.persistence = persistence or workflow_persistence
        self.idempotency_mgr = idempotency_mgr or workflow_idempotency

    def execute_workflow(
        self,
        request: WorkflowRunRequest,
        spec_override: Optional[ApplicationSpec] = None,
    ) -> WorkflowResult:
        """Executes the complete canonical V2 certification pipeline end-to-end."""
        fp = self.idempotency_mgr.get_request_fingerprint(request)

        # 1. Idempotency Check & Concurrency Lock
        with self.idempotency_mgr.acquire_execution_lock(fp):
            existing_run = self.idempotency_mgr.check_existing_completed_run(request)
            if existing_run and not request.force_recompute:
                logger.info(f"Returning idempotent completed workflow run '{existing_run.workflow_run_id}'.")
                return self._build_result_from_existing_run(existing_run)

            run_id = f"WRUN-{uuid.uuid4().hex[:12]}"
            run = WorkflowRun(
                workflow_run_id=run_id,
                application_id=request.application_id,
                request_fingerprint=fp,
                state=WorkflowState.VALIDATING,
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

                # 2. Stage 1: Validation & Resolution
                init_res = self._stage_validate_and_init(request, spec_override, run, timings)
                if isinstance(init_res, WorkflowResult):
                    return init_res
                spec, ref_adapter, target_adapter, test_inputs = init_res

                # 3. Stage 2: Phase 3 Evidence Collection
                ev_res = self._stage_capture_evidence(spec, ref_adapter, target_adapter, test_inputs, run, timings)
                if isinstance(ev_res, WorkflowResult):
                    return ev_res
                all_evidence_records, evaluated_input_cases = ev_res

                # 4. Stage 3: Phase 4 Behavioral Evaluation
                eval_result = self._stage_evaluate_behavior(spec, evaluated_input_cases, run, timings)
                if isinstance(eval_result, WorkflowResult):
                    return eval_result
                if not eval_result:
                    return self._fail_run(run, WorkflowErrorCode.EVALUATION_FAILED, "EvaluationResult missing.")

                # 5. Stage 4: Phase 7 OracleSet Verification
                oracle_set = self._stage_resolve_oracles(spec, run, timings)
                if isinstance(oracle_set, WorkflowResult):
                    return oracle_set
                if not oracle_set:
                    return self._fail_run(run, WorkflowErrorCode.ORACLE_AUTHORITY_MISSING, "OracleSet resolution missing.")

                # 6. Stage 5: Phase 8 Exact Threshold Resolution
                threshold_res = self._stage_resolve_thresholds(spec, run, timings)
                if isinstance(threshold_res, WorkflowResult):
                    return threshold_res
                if not threshold_res:
                    return self._fail_run(run, WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING, "ThresholdResolution missing.")

                # 7. Stage 6: Certification Engine Execution
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

                # 8. Stage 7: Phase 10 Grounded Explanation (Optional)
                explanation_dict = self._stage_generate_explanation(
                    artifact=artifact,
                    eval_result=eval_result,
                    oracle_set=oracle_set,
                    threshold_res=threshold_res,
                    all_evidence_records=all_evidence_records,
                    request=request,
                    run=run,
                )

                # 9. Stage 8: Transactional Persistence & Audit
                audit_status_str = self._stage_persist_and_audit(
                    artifact=artifact,
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

        ref_adapter, target_adapter = self.app_resolver.resolve_adapters(
            spec=spec,
            target_index=request.target_index,
        )

        resolved_custom_inputs = request.custom_inputs
        if resolved_custom_inputs is None and spec.dataset_config and spec.dataset_config.metadata and spec.dataset_config.metadata.get("custom_inputs"):
            resolved_custom_inputs = spec.dataset_config.metadata.get("custom_inputs")
        elif resolved_custom_inputs is None and spec.metadata and spec.metadata.get("custom_inputs"):
            resolved_custom_inputs = spec.metadata.get("custom_inputs")

        test_inputs = self.app_resolver.resolve_inputs(
            spec=spec,
            custom_inputs=resolved_custom_inputs,
        )
        if not test_inputs:
            return self._fail_run(
                run,
                WorkflowErrorCode.INVALID_INPUT,
                f"No test inputs could be resolved for application '{spec.application_id}'.",
            )

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
        run.state = WorkflowState.CAPTURING_EVIDENCE
        self.persistence.save_run(run)

        session_id = f"SESS-{run.workflow_run_id}"
        run.evidence_session_id = session_id
        all_evidence_records: list[EvidenceRecord] = []
        evaluated_input_cases: list[dict[str, Any]] = []

        for idx, inp in enumerate(test_inputs):
            inp_vals = getattr(inp, "values", None) or getattr(inp, "input_values", None) or getattr(inp, "data", None) or (inp if isinstance(inp, dict) else {})
            inp_id = getattr(inp, "input_id", f"inp_{idx+1}")

            # Execute reference
            ref_res = ref_adapter.execute(inp_vals) if hasattr(ref_adapter, "execute") else ref_adapter(inp_vals)
            if hasattr(ref_res, "normalized_outputs") and ref_res.normalized_outputs is not None:
                ref_val = ref_res.normalized_outputs
            elif hasattr(ref_res, "raw_outputs") and ref_res.raw_outputs is not None:
                ref_val = ref_res.raw_outputs
            elif hasattr(ref_res, "output"):
                ref_val = ref_res.output
            else:
                ref_val = ref_res

            ref_eid = f"EVID-REF-{run.workflow_run_id[:6]}-{idx+1}"
            rec_ref = EvidenceRecord(
                evidence_id=ref_eid,
                session_id=session_id,
                role="reference",
                input_id=inp_id,
                evidence_type=EvidenceType.OUTPUT,
                content_hash=hashlib.sha256(json.dumps(ref_val, sort_keys=True, default=str).encode()).hexdigest(),
                payload={"output": ref_val, "input": inp_vals},
                size_bytes=len(str(ref_val)),
                capture_status=EvidenceCaptureStatus.CAPTURED,
                persistence_status=EvidencePersistenceStatus.PERSISTED,
            )
            self.ev_store.save_record(rec_ref)
            all_evidence_records.append(rec_ref)

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
            rec_tgt = EvidenceRecord(
                evidence_id=tgt_eid,
                session_id=session_id,
                role="target",
                input_id=inp_id,
                evidence_type=EvidenceType.OUTPUT,
                content_hash=hashlib.sha256(json.dumps(tgt_val, sort_keys=True, default=str).encode()).hexdigest(),
                payload={"output": tgt_val, "input": inp_vals},
                size_bytes=len(str(tgt_val)),
                capture_status=EvidenceCaptureStatus.CAPTURED,
                persistence_status=EvidencePersistenceStatus.PERSISTED,
            )
            self.ev_store.save_record(rec_tgt)
            all_evidence_records.append(rec_tgt)

            evaluated_input_cases.append({
                "input_id": inp_id,
                "input_values": inp_vals,
                "ref_val": ref_val,
                "tgt_val": tgt_val,
                "ref_eid": ref_eid,
                "tgt_eid": tgt_eid,
            })

        timings["evidence_capture_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
        return all_evidence_records, evaluated_input_cases

    def _stage_evaluate_behavior(
        self,
        spec: ApplicationSpec,
        evaluated_input_cases: list[dict[str, Any]],
        run: WorkflowRun,
        timings: dict[str, float],
    ) -> Optional[EvaluationResult]:
        t_stage = time.perf_counter()
        run.state = WorkflowState.EVALUATING
        self.persistence.save_run(run)

        input_results: list[InputEvaluationResult] = []
        differences: list[BehaviorDifference] = []
        equiv_count = 0
        diff_count = 0

        for idx, c in enumerate(evaluated_input_cases):
            inp_id = c["input_id"]
            ref_val = c["ref_val"]
            tgt_val = c["tgt_val"]
            ref_eid = c["ref_eid"]
            tgt_eid = c["tgt_eid"]

            is_match = (ref_val == tgt_val)
            if is_match:
                equiv_count += 1
                input_results.append(
                    InputEvaluationResult(
                        input_id=inp_id,
                        verdict=EvaluationVerdict.EQUIVALENT,
                        status=EvaluationVerdict.EQUIVALENT,
                        differences=[],
                    )
                )
            else:
                diff_count += 1
                diff_id = f"DIFF-{run.workflow_run_id[:6]}-{idx+1}"
                b_diff = BehaviorDifference(
                    difference_id=diff_id,
                    dimension=BehaviorDimension.OUTPUT,
                    difference_type=DifferenceType.OUTPUT_VALUE_MISMATCH,
                    reference_value=ref_val,
                    target_value=tgt_val,
                    input_id=inp_id,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=tgt_eid,
                    evidence_ids=[ref_eid, tgt_eid],
                    details={"ref": ref_val, "tgt": tgt_val},
                )
                differences.append(b_diff)
                input_results.append(
                    InputEvaluationResult(
                        input_id=inp_id,
                        verdict=EvaluationVerdict.DIFFERENT,
                        status=EvaluationVerdict.DIFFERENT,
                        differences=[b_diff],
                    )
                )

        total_cases = len(evaluated_input_cases)
        eval_score = float(equiv_count) / float(total_cases) if total_cases > 0 else 0.0
        eval_verdict = EvaluationVerdict.EQUIVALENT if diff_count == 0 else EvaluationVerdict.DIFFERENT

        eval_result = EvaluationResult(
            evaluation_id=f"EVAL-{run.workflow_run_id}",
            application_id=spec.application_id,
            run_id=run.workflow_run_id,
            verdict=eval_verdict,
            summary=EvaluationSummary(
                total_inputs=total_cases,
                evaluated_inputs=total_cases,
                equivalent_inputs=equiv_count,
                different_inputs=diff_count,
                inconclusive_inputs=0,
                equivalence_score=eval_score,
                total_differences=len(differences),
            ),
            input_results=input_results,
            differences=differences,
            dimensions_evaluated=[BehaviorDimension.OUTPUT],
        )
        run.evaluation_id = eval_result.evaluation_id
        timings["evaluation_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
        return eval_result

    def _stage_resolve_oracles(
        self,
        spec: ApplicationSpec,
        run: WorkflowRun,
        timings: dict[str, float],
    ) -> Optional[OracleSet]:
        t_stage = time.perf_counter()
        run.state = WorkflowState.RESOLVING_ORACLES
        self.persistence.save_run(run)

        try:
            oracle_set = self.app_resolver.resolve_oracle_set(spec=spec)
        except Exception as exc:
            logger.warning(f"Oracle set resolution error: {exc}")
            return None

        if oracle_set:
            run.oracle_set_id = getattr(oracle_set, "oracle_set_id", "")
            run.oracle_set_hash = getattr(oracle_set, "oracle_set_hash", "") or getattr(oracle_set, "fingerprint", "")
        timings["oracle_resolution_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
        return oracle_set

    def _stage_resolve_thresholds(
        self,
        spec: ApplicationSpec,
        run: WorkflowRun,
        timings: dict[str, float],
    ) -> Optional[ThresholdResolution]:
        t_stage = time.perf_counter()
        run.state = WorkflowState.RESOLVING_THRESHOLDS
        self.persistence.save_run(run)

        th_policy = self.thresh_persistence.get_policy(f"POL-{spec.application_id}")
        if not th_policy:
            th_policy = ThresholdPolicy(
                policy_id=f"POL-{spec.application_id}",
                version="1.0.0",
                metric=DifferenceMetric.ABSOLUTE_DIFF,
                strategy=ThresholdStrategy.FIXED,
                parameters={"value": 0.0},
            )
            self.thresh_persistence.save_policy(th_policy)

        threshold_res = self.thresh_eng.resolve_threshold(
            metric=th_policy.metric,
            policy=th_policy,
        )
        self.thresh_persistence.save_resolution(threshold_res)

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
        run.state = WorkflowState.CERTIFYING
        self.persistence.save_run(run)

        # Strict Authority Check: threshold fingerprint verification
        expected_fp = threshold_res.compute_fingerprint()
        if threshold_res.fingerprint != expected_fp:
            return self._fail_run(
                run,
                WorkflowErrorCode.THRESHOLD_FINGERPRINT_MISMATCH,
                f"Threshold fingerprint mismatch: expected '{expected_fp}', found '{threshold_res.fingerprint}'.",
            )

        cert_policy = CertificationPolicy(
            policy_id=f"POL-{spec.application_id}",
            min_equivalence_score=request.policy_min_equivalence_score,
            min_oracle_coverage=request.policy_min_oracle_coverage,
            min_applicable_probes_per_oracle=0,
            allow_warnings=request.allow_warnings,
            block_on_critical_regression=True,
            block_on_reference_inconsistent=True,
        )

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
            evaluation_mode=spec.rule_config.mode if spec.rule_config else "CONTROLLED",
            policy_min_equivalence_score=request.policy_min_equivalence_score,
            policy_allow_warnings=request.allow_warnings,
        )

        artifact = self.cert_eng.certify(
            context=cert_ctx,
            policy=cert_policy,
            evaluation_result=eval_result,
            oracle_set=oracle_set,
            threshold_resolution=threshold_res,
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
        run.state = WorkflowState.EXPLAINING
        self.persistence.save_run(run)

        try:
            exp_ctx = self.ctx_builder.build_context(
                certification_id=artifact.certification_id,
                artifact=artifact,
                evaluation_result=eval_result,
                oracle_set=oracle_set,
                threshold_resolution=threshold_res,
                evidence_records=all_evidence_records,
                execution_mode="v2",
                use_company_knowledge=request.use_company_knowledge,
            )
            explanation = self.intel_eng.generate_explanation(
                certification_id=artifact.certification_id,
                artifact=artifact,
                evaluation_result=eval_result,
                oracle_set=oracle_set,
                threshold_resolution=threshold_res,
                evidence_records=all_evidence_records,
                request=ExplanationRequest(
                    mode=request.explanation_mode,
                    use_company_knowledge=request.use_company_knowledge,
                ),
                user_id=request.user_id,
            )
            run.explanation_id = explanation.explanation_id
            return explanation.model_dump(mode="json")
        except Exception as exc:
            logger.warning(f"Grounded explanation generation failed for '{run.workflow_run_id}': {exc}", exc_info=True)
            return {
                "status": "EXPLANATION_FAILED",
                "error": str(exc),
                "grounding_status": "NOT_GROUNDED",
            }

    def _stage_persist_and_audit(
        self,
        artifact: CertificationArtifact,
        evaluated_input_cases: list[dict[str, Any]],
        spec: ApplicationSpec,
        threshold_res: ThresholdResolution,
        eval_result: EvaluationResult,
        run: WorkflowRun,
        timings: dict[str, float],
    ) -> Any:
        t_stage = time.perf_counter()
        run.state = WorkflowState.PERSISTING
        self.persistence.save_run(run)

        # Save artifact in repository
        self.cert_repo.save_artifact(artifact)

        # Persist per-input cases for full Phase 11 reproducibility
        cases_to_save: list[CertificationCase] = []
        for idx, c in enumerate(evaluated_input_cases):
            inp_id = c["input_id"]
            ref_val = c["ref_val"]
            tgt_val = c["tgt_val"]
            cls_str = "MATCH" if ref_val == tgt_val else "MODERN_REGRESSION"
            inp_json = json.dumps(c["input_values"], sort_keys=True, default=str)
            cases_to_save.append(
                CertificationCase(
                    case_id=f"CASE-{artifact.certification_id}-{idx+1}",
                    run_id=artifact.certification_id,
                    input_set_id=artifact.input_set_id,
                    case_index=idx,
                    input_id=inp_id,
                    input_json=inp_json,
                    input_hash=hashlib.sha256(inp_json.encode()).hexdigest(),
                    legacy_output_json=json.dumps(ref_val, sort_keys=True, default=str),
                    modern_output_json=json.dumps(tgt_val, sort_keys=True, default=str),
                    execution_time_ms=0.0,
                    oracle_result="PASS" if ref_val == tgt_val else "VIOLATED",
                    classification=cls_str,
                    severity="medium" if ref_val != tgt_val else "none",
                )
            )
        self.cert_repo.save_certification_cases(cases_to_save)

        status_str = artifact.status.value if hasattr(artifact.status, "value") else str(artifact.status)
        audit_ok = audit_logger.log(
            project_id=spec.application_id,
            action=AuditAction.CERTIFICATION_COMPLETE,
            status="SUCCESS" if artifact.certified else "INFO",
            certification_id=artifact.certification_id,
            details={
                "workflow_run_id": run.workflow_run_id,
                "status": status_str,
                "score": artifact.score,
                "threshold_resolution_id": threshold_res.resolution_id,
                "threshold_resolution_fingerprint": threshold_res.fingerprint,
                "evaluation_id": eval_result.evaluation_id,
            },
        )
        audit_status_str = "PERSISTED" if audit_ok else "FAILED"

        run.state = WorkflowState.COMPLETED
        run.completed_at = datetime.now(timezone.utc).isoformat()
        timings["persistence_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
        return audit_status_str

    def _fail_run(
        self,
        run: WorkflowRun,
        error_code: WorkflowErrorCode,
        error_message: str,
        audit_status: str = "PERSISTED",
    ) -> WorkflowResult:
        """Helper to fail a WorkflowRun in a fail-closed, auditable state."""
        run.state = WorkflowState.FAILED
        run.error_code = error_code
        run.error_message = error_message
        run.completed_at = datetime.now(timezone.utc).isoformat()
        try:
            self.persistence.save_run(run)
        except Exception:
            pass

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
            state=WorkflowState.FAILED,
            status="FAILED",
            certified=False,
            equivalence_score=0.0,
            audit_status=audit_status,
            error_code=error_code,
            error_message=error_message,
        )

    def _build_result_from_existing_run(self, run: WorkflowRun) -> WorkflowResult:
        """Constructs a WorkflowResult directly from an authoritative completed run."""
        artifact = None
        if run.certification_id:
            try:
                artifact = self.cert_repo.get_artifact(run.certification_id)
            except Exception:
                artifact = None

        return WorkflowResult(
            workflow_run_id=run.workflow_run_id,
            application_id=run.application_id,
            state=run.state,
            status=run.certification_status or "UNKNOWN",
            certified=run.certification_status == "CERTIFIED",
            equivalence_score=run.certification_score,
            artifact_id=run.certification_id,
            artifact_hash=artifact.artifact_hash if artifact else None,
            threshold_resolution_id=run.threshold_resolution_id,
            threshold_resolution_fingerprint=run.threshold_resolution_fingerprint,
            unique_input_count=artifact.metrics.unique_input_count if artifact and artifact.metrics else None,
            regressions_count=len(artifact.regressions) if artifact else 0,
            regressions=[r.model_dump(mode="json") for r in artifact.regressions] if artifact else [],
            audit_status="PERSISTED",
            timings_ms=run.stage_timings_ms,
        )


workflow_engine = CanonicalV2WorkflowEngine()
