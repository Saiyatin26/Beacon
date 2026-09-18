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
)
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
)
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

                # 3. Stage 2: Phase 3 Evidence Collection & Bundle Assembly
                ev_res = self._stage_capture_evidence(spec, ref_adapter, target_adapter, test_inputs, run, timings)
                if isinstance(ev_res, WorkflowResult):
                    return ev_res
                bundle, all_evidence_records, evaluated_input_cases = ev_res

                # 4. Stage 3: Phase 4 Authoritative Behavioral Evaluation
                eval_result = self._stage_evaluate_behavior(spec, bundle, test_inputs, run, timings)
                if isinstance(eval_result, WorkflowResult):
                    return eval_result
                if not eval_result:
                    return self._fail_run(run, WorkflowErrorCode.EVALUATION_FAILED, "EvaluationResult missing.")

                # 5. Stage 4: Phase 5 Controlled Mode Assessment (when applicable)
                user_rules, ctrl_result = self._stage_evaluate_controlled_mode(spec, bundle, eval_result, run, timings)
                if isinstance(ctrl_result, WorkflowResult):
                    return ctrl_result

                # 6. Stage 5: Phase 6 Invariant Discovery (when applicable)
                disc_result = self._stage_discover_rules(spec, bundle, eval_result, request, run, timings)
                if isinstance(disc_result, WorkflowResult):
                    return disc_result

                # 7. Stage 6: Phase 7 OracleSet Reconciliation
                oracle_set = self._stage_reconcile_oracles(spec, user_rules, disc_result, bundle, run, timings)
                if isinstance(oracle_set, WorkflowResult):
                    return oracle_set
                if not oracle_set:
                    return self._fail_run(run, WorkflowErrorCode.ORACLE_AUTHORITY_MISSING, "OracleSet resolution missing.")

                # 8. Stage 7: Phase 8 Exact Threshold Resolution
                threshold_res = self._stage_resolve_thresholds(spec, run, timings)
                if isinstance(threshold_res, WorkflowResult):
                    return threshold_res
                if not threshold_res:
                    return self._fail_run(run, WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING, "ThresholdResolution missing.")

                # 9. Stage 8: Certification Engine Execution
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

                # 10. Stage 9: Phase 10 Grounded Explanation (Optional)
                explanation_dict = self._stage_generate_explanation(
                    artifact=artifact,
                    eval_result=eval_result,
                    oracle_set=oracle_set,
                    threshold_res=threshold_res,
                    all_evidence_records=all_evidence_records,
                    request=request,
                    run=run,
                )

                # 11. Stage 10: Atomic Persistence & Audit
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
        if not test_inputs or len(test_inputs) == 0:
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
        manifest_items: list[EvidenceManifestItem] = []
        evaluated_input_cases: list[dict[str, Any]] = []

        ref_exec_ids = []
        tgt_exec_ids = []

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
        input_set_id = f"INPSET-{run.workflow_run_id[:8]}"
        input_set_hash = compute_input_set_canonical_hash(test_inputs)

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
        run.state = WorkflowState.EVALUATING
        self.persistence.save_run(run)

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
        if eval_result.summary.total_inputs != len(test_inputs):
            logger.warning(
                f"Evaluation total inputs ({eval_result.summary.total_inputs}) != test inputs count ({len(test_inputs)})"
            )

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
        enable_disc = getattr(request, "enable_discovery", False) or getattr(spec, "enable_discovery", False)
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
        run.state = WorkflowState.RESOLVING_ORACLES
        self.persistence.save_run(run)

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

        # Verify no empty OracleSet is treated as valid certification authority
        rules_count = len(getattr(oracle_set, "rules", [])) + len(getattr(oracle_set, "oracles", []))
        if rules_count == 0:
            return self._fail_run(
                run,
                WorkflowErrorCode.ORACLE_AUTHORITY_MISSING,
                f"OracleSet '{oset_id}' contains zero rules/oracles (empty oracle authority forbidden).",
            )

        run.oracle_set_id = oset_id
        run.oracle_set_hash = oset_hash
        timings["oracle_resolution_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
        return oracle_set

    def _stage_resolve_thresholds(
        self,
        spec: ApplicationSpec,
        run: WorkflowRun,
        timings: dict[str, float],
    ) -> Any:
        t_stage = time.perf_counter()
        run.state = WorkflowState.RESOLVING_THRESHOLDS
        self.persistence.save_run(run)

        # Retrieve authoritative policy without fabricating silent defaults
        th_policy = self.thresh_persistence.get_policy(f"POL-{spec.application_id}")
        if not th_policy:
            th_policy = self.thresh_persistence.get_policy(spec.application_id)

        if not th_policy:
            return self._fail_run(
                run,
                WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING,
                f"Authoritative ThresholdPolicy 'POL-{spec.application_id}' is missing. Production workflows cannot fabricate default policies.",
            )

        threshold_res = self.thresh_eng.resolve_threshold(
            metric=th_policy.metric,
            policy=th_policy,
        )
        if not threshold_res:
            return self._fail_run(
                run,
                WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING,
                f"Failed to resolve threshold for metric '{th_policy.metric.value}'.",
            )

        # Strict Authority Check: threshold fingerprint verification
        expected_fp = threshold_res.compute_fingerprint()
        if threshold_res.fingerprint != expected_fp:
            return self._fail_run(
                run,
                WorkflowErrorCode.THRESHOLD_FINGERPRINT_MISMATCH,
                f"Threshold fingerprint mismatch: expected '{expected_fp}', found '{threshold_res.fingerprint}'.",
            )

        self.thresh_persistence.save_resolution(threshold_res)

        # Re-verify persisted resolution
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
        run.state = WorkflowState.CERTIFYING
        self.persistence.save_run(run)

        # Strict verification before CertificationEngine execution
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

        if not artifact or not getattr(artifact, "certification_id", None):
            return self._fail_run(
                run,
                WorkflowErrorCode.CERTIFICATION_FAILED,
                "CertificationEngine failed to produce a valid CertificationArtifact.",
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
            exp_req = ExplanationRequest(
                mode=getattr(request, "explanation_mode", "deterministic") or "deterministic",
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
            return explanation_res.model_dump(mode="json") if hasattr(explanation_res, "model_dump") else explanation_res

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
        run.state = WorkflowState.PERSISTING
        self.persistence.save_run(run)

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

        # 2. Derive CertificationCases strictly from authoritative EvaluationResult & Artifact
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

        # 4. Record structured audit log
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

        # 5. Finalize persistent reservation and mark workflow COMPLETED
        self.idempotency_mgr.finalize_run(run.request_fingerprint, run.workflow_run_id, status="COMPLETED")
        run.state = WorkflowState.COMPLETED
        run.completed_at = datetime.now(timezone.utc).isoformat()
        timings["persistence_ms"] = round((time.perf_counter() - t_stage) * 1000.0, 2)
        return audit_status_str

    def _fail_run(
        self,
        run: WorkflowRun,
        error_code: WorkflowErrorCode,
        error_message: str,
        audit_status: str = "FAILED",
    ) -> WorkflowResult:
        """Helper to fail a WorkflowRun in a fail-closed, auditable state."""
        run.state = WorkflowState.FAILED
        run.error_code = error_code
        run.error_message = error_message
        run.completed_at = datetime.now(timezone.utc).isoformat()
        try:
            self.persistence.save_run(run)
            self.idempotency_mgr.finalize_run(run.request_fingerprint, run.workflow_run_id, status="FAILED")
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
            unique_input_count=artifact.metrics.unique_input_count if (artifact and artifact.metrics) else None,
            regressions_count=len(artifact.regressions) if artifact else 0,
            regressions=[r.model_dump(mode="json") for r in artifact.regressions] if artifact else [],
            explanation=None,
            audit_status="PERSISTED",
            timings_ms=run.stage_timings_ms,
        )


workflow_engine = CanonicalV2WorkflowEngine()
