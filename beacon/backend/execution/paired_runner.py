"""BEACON V2 — Phase 3 Paired Execution Coordinator & Evidence Engine.

Orchestrates the synchronized execution of Reference and Target applications against
the identical immutable InputSet, enforcing controlled multi-stage lifecycles, readiness
verification, correlation tracking, modular evidence capture, failure policies, and dual persistence.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import platform
import sys
import time
from typing import Any, Optional, Union
from pydantic import BaseModel

from application.models import ApplicationSpec
from common.contracts import (

    AdapterRole,
    AdapterType,
    CanonicalInput,
    ExecutionStatus,
    ImplementationAdapter,
    Observation,
)
from .evidence_models import (
    DatabaseEvidence,
    ErrorEvidence,
    EvidenceBundle,
    EvidenceCaptureStatus,
    EvidenceConfiguration,
    EvidenceManifest,
    EvidencePersistenceStatus,
    EvidenceRecord,
    EvidenceType,

    FileEvidence,
    HttpEvidence,
    LogEvidence,
    MetadataEvidence,
    OutputEvidence,
    RuntimeEvidence,
    TraceEvent,
    TraceEvidence,
    compute_content_hash,
)
from .evidence_normalizer import EvidenceNormalizer, evidence_normalizer
from .evidence_providers import (
    DatabaseEvidenceProvider,
    EvidenceProvider,
    FileEvidenceProvider,
    HttpEvidenceProvider,
    LogEvidenceProvider,
    OutputEvidenceProvider,
    RuntimeEvidenceProvider,
    TraceEvidenceProvider,
)
from .evidence_store import EvidenceStore, evidence_store
from .input_set import CanonicalInputItem, InputSet
from .paired_models import (
    PairedExecutionItemResult,
    PairedExecutionRequest,
    PairedExecutionSession,
    PairedExecutionStatus,
)
from .preflight import PreFlightResult, PreFlightValidator, preflight_validator
from .readiness import ReadinessChecker, ReadinessConfig, ReadinessResult, ReadinessStrategy
from .runner import ApplicationExecutor, application_executor
from .security import SecretRedactor

logger = logging.getLogger("beacon.execution.paired_runner")


class PairedExecutionCoordinator:
    """Coordinates paired reference and target execution with rich evidence capture."""

    def __init__(
        self,
        executor: Optional[ApplicationExecutor] = None,
        validator: Optional[PreFlightValidator] = None,
        store: Optional[EvidenceStore] = None,
        normalizer: Optional[EvidenceNormalizer] = None,
    ):
        self.executor = executor or application_executor
        self.validator = validator or preflight_validator
        self.store = store or evidence_store
        self.normalizer = normalizer or evidence_normalizer

    def execute_paired(
        self,
        request: PairedExecutionRequest,
        spec: Optional[ApplicationSpec] = None,
    ) -> tuple[PairedExecutionSession, EvidenceBundle]:
        """Executes the full Phase 3 paired execution lifecycle."""
        # 1. Resolve Application Spec and Adapters
        app_spec = spec
        if not app_spec and request.application_id:
            from application.repository import application_repository
            app_spec = application_repository.get_application(request.application_id)

        if app_spec:
            from application.resolver import ApplicationResolutionError, application_resolver

        ref_adp = request.reference_adapter
        target_adp = request.target_adapter

        if app_spec and (not ref_adp or not target_adp):
            r, t = application_resolver.resolve_adapters(app_spec)
            ref_adp = ref_adp or r
            target_adp = target_adp or t


        if not ref_adp or not target_adp:
            raise ValueError(
                f"Both Reference and Target adapters are required for paired execution. "
                f"Resolved: ref={ref_adp}, target={target_adp}"
            )

        ref_name = getattr(ref_adp, "name", "reference_impl")
        target_name = getattr(target_adp, "name", "target_impl")

        # 2. Resolve or Build Immutable InputSet (Canonicalize Once)
        if request.input_set_id:
            input_set = self.store.get_input_set(request.input_set_id)
            if not input_set:
                raise ValueError(f"Configured input_set_id '{request.input_set_id}' not found.")
        elif request.custom_inputs:
            input_set = InputSet.from_inputs(
                inputs=request.custom_inputs,
                source="custom_inputs",
                provenance={"request_correlation_id": request.correlation_id},
            )
        elif app_spec:
            resolved_inputs = application_resolver.resolve_inputs(
                app_spec,
                allow_synthetic_inputs=request.allow_synthetic_inputs,
            )
            input_set = InputSet.from_inputs(
                inputs=resolved_inputs,
                source=f"application_spec:{app_spec.application_id}",
                provenance={"spec_id": app_spec.application_id},
            )
        else:
            raise ValueError("No input source available: provide input_set_id, custom_inputs, or valid ApplicationSpec.")

        # Persist the immutable InputSet
        self.store.save_input_set(input_set)

        # 3. Create Session with Correlation Identifiers
        session = PairedExecutionSession(
            application_id=request.application_id or getattr(app_spec, "application_id", "unnamed_app"),
            correlation_id=request.correlation_id or f"CORR-{hashlib.sha256(f'{time.time()}_{ref_name}'.encode()).hexdigest()[:12]}",
            reference_adapter_name=ref_name,
            target_adapter_name=target_name,
            input_set_id=input_set.input_set_id,
            input_set_hash=input_set.content_hash,
            total_inputs=input_set.input_count,
            reproducibility_metadata={
                "os": platform.platform(),
                "python": sys.version.split(" ")[0],
                "time_utc": datetime.now(timezone.utc).isoformat(),
                "timeout_seconds": request.timeout_seconds,
            },
        )
        session.started_at = datetime.now(timezone.utc).isoformat()
        session.status = PairedExecutionStatus.PREPARING
        self.store.save_session(session)

        logger.info(f"[SESSION {session.session_id}] Creating paired execution (correlation={session.correlation_id})")
        logger.info(f"[SESSION {session.session_id}] Input set linked: {input_set.input_set_id} ({input_set.input_count} inputs)")

        # 4. Setup Evidence Providers & Normalization Collection
        ev_cfg = request.evidence_config or EvidenceConfiguration()
        trace_provider = TraceEvidenceProvider()
        output_provider = OutputEvidenceProvider()
        log_provider = LogEvidenceProvider()
        http_provider = HttpEvidenceProvider()
        file_provider = FileEvidenceProvider(paths=ev_cfg.filesystem_paths if ev_cfg.capture_filesystem else [])
        db_provider = DatabaseEvidenceProvider(config=ev_cfg.database_config if ev_cfg.capture_database else None)
        runtime_provider = RuntimeEvidenceProvider()

        records: list[EvidenceRecord] = []
        ref_exec_ids: list[str] = []
        target_exec_ids: list[str] = []
        item_results: list[PairedExecutionItemResult] = []

        # Record Initial Trace Event
        trace_provider.record_event(
            event_type="SESSION_CREATED",
            details={"session_id": session.session_id, "correlation_id": session.correlation_id},
        )

        # 5. Preflight Validation
        if app_spec:
            preflight_spec = app_spec.model_copy(deep=True)
            if input_set and input_set.input_count > 0:
                preflight_spec.metadata["dataset_records"] = [item.payload for item in input_set.inputs]

            preflight = self.executor.preflight_check(
                preflight_spec,
                reference_adapter=ref_adp,
                target_adapters=[target_adp],
                allow_synthetic_inputs=request.allow_synthetic_inputs,
            )

            if not preflight.is_ready:
                err_msg = f"Preflight validation failed: {'; '.join(preflight.errors)}"
                logger.error(f"[SESSION {session.session_id}] {err_msg}")
                session.error_summary = err_msg
                session.mark_completed(PairedExecutionStatus.FAILED)
                
                # Add Error Evidence
                rec = self.normalizer.normalize_record(
                    evidence_type=EvidenceType.ERROR,
                    payload=ErrorEvidence(category="PREFLIGHT_ERROR", message=err_msg, phase="PREFLIGHT"),
                    session_id=session.session_id,
                    application_id=session.application_id,
                    role="system",
                    source="preflight_validator",
                )
                records.append(rec)
                self.store.save_record(rec)

                bundle = self.normalizer.build_bundle(
                    session_id=session.session_id,
                    correlation_id=session.correlation_id,
                    application_id=session.application_id,
                    input_set_id=input_set.input_set_id,
                    input_set_hash=input_set.content_hash,
                    records=records,
                    is_partial=True,
                    error_summary=err_msg,
                )
                session.bundle_id = bundle.bundle_id
                session.bundle_hash = bundle.bundle_hash
                self.store.save_session(session)
                self.store.save_bundle(bundle)
                return session, bundle

        # ======================================================================
        # 6. REFERENCE APPLICATION LIFECYCLE
        # ======================================================================
        session.status = PairedExecutionStatus.REFERENCE_STARTING
        self.store.save_session(session)
        logger.info(f"[SESSION {session.session_id}][REFERENCE] Starting application '{ref_name}'")
        trace_provider.record_event("REFERENCE_STARTING", details={"adapter": ref_name})

        ref_fatal_error: Optional[str] = None
        ref_ctx = {"session_id": session.session_id, "correlation_id": session.correlation_id, "role": "reference"}
        ref_proc = None

        # Reference Configure, Prepare, and Start
        try:
            if hasattr(ref_adp, "configure"):
                ref_adp.configure(ref_ctx)
            if hasattr(ref_adp, "prepare"):
                ref_adp.prepare(ref_ctx)
            if hasattr(ref_adp, "start"):
                ref_proc = ref_adp.start(ref_ctx)
        except Exception as exc:
            ref_fatal_error = f"Reference adapter startup failed: {exc}"
            logger.error(f"[SESSION {session.session_id}][REFERENCE] {ref_fatal_error}")

        # Reference Readiness Check
        if not ref_fatal_error and request.readiness_config_ref:
            readiness_res = ReadinessChecker.wait_until_ready(
                request.readiness_config_ref, adapter=ref_adp, process=ref_proc
            )
            if not readiness_res.ready:
                ref_fatal_error = f"Reference readiness failed ({readiness_res.strategy.value}): {readiness_res.diagnostics}"
                logger.error(f"[SESSION {session.session_id}][REFERENCE] {ref_fatal_error}")
            else:
                logger.info(f"[SESSION {session.session_id}][REFERENCE] Application READY in {readiness_res.duration_ms}ms")
                trace_provider.record_event("REFERENCE_READY", details={"duration_ms": readiness_res.duration_ms})
        elif not ref_fatal_error:
            logger.info(f"[SESSION {session.session_id}][REFERENCE] Application READY")
            trace_provider.record_event("REFERENCE_READY")

        session.status = PairedExecutionStatus.REFERENCE_RUNNING
        self.store.save_session(session)

        # Execute Inputs on Reference (Identical Canonical Inputs)
        ref_observations: dict[str, Observation] = {}
        ref_durations: dict[str, float] = {}

        if not ref_fatal_error:
            for item in input_set.inputs:
                input_copy = item.to_canonical_input()
                logger.info(f"[SESSION {session.session_id}][REFERENCE][INPUT {item.input_id}] Executing")
                trace_provider.record_event("REFERENCE_EXECUTE_INPUT", details={"input_id": item.input_id})

                # Capture Before
                before_ctx = {
                    "session_id": session.session_id,
                    "correlation_id": session.correlation_id,
                    "input_id": item.input_id,
                    "role": "reference",
                    "adapter": ref_adp,
                }
                if ev_cfg.capture_filesystem:
                    file_provider.capture_before(before_ctx)
                if ev_cfg.capture_database:
                    db_provider.capture_before(before_ctx)

                # Execute Single
                res = self.executor.execute_single(
                    adapter=ref_adp,
                    input_data=input_copy,
                    input_id=item.input_id,
                    session_id=session.session_id,
                    application_id=session.application_id,
                    manage_lifecycle=False,
                )

                ref_exec_ids.append(res.execution_id)
                obs = res.to_observation(input_id=item.input_id)
                ref_observations[item.input_id] = obs
                ref_durations[item.input_id] = res.duration_ms

                # Capture Evidence
                after_ctx = dict(before_ctx)
                after_ctx["execution_id"] = res.execution_id
                item_ev_ids: list[str] = []

                # Output Evidence
                if ev_cfg.capture_output:
                    out_data = output_provider.capture_after(obs, after_ctx)
                    out_rec = self.normalizer.normalize_record(
                        evidence_type=EvidenceType.OUTPUT,
                        payload=out_data,
                        session_id=session.session_id,
                        execution_id=res.execution_id,
                        application_id=session.application_id,
                        role="reference",
                        input_id=item.input_id,
                        source=ref_name,
                    )
                    records.append(out_rec)
                    item_ev_ids.append(out_rec.evidence_id)
                    self.store.save_record(out_rec)

                # Error Evidence if applicable
                if res.status not in (ExecutionStatus.SUCCEEDED,):
                    err_rec = self.normalizer.normalize_record(
                        evidence_type=EvidenceType.ERROR,
                        payload=ErrorEvidence(
                            category=res.status.value,
                            message=res.error_message or "Reference execution failed",
                            phase="REFERENCE_EXECUTION",
                            exception_type=res.error_type,
                            execution_id=res.execution_id,
                        ),
                        session_id=session.session_id,
                        execution_id=res.execution_id,
                        application_id=session.application_id,
                        role="reference",
                        input_id=item.input_id,
                        source=ref_name,
                    )
                    records.append(err_rec)
                    item_ev_ids.append(err_rec.evidence_id)
                    self.store.save_record(err_rec)

                # Log Evidence
                if ev_cfg.capture_logs:
                    log_data = log_provider.capture_after(obs, after_ctx)
                    log_rec = self.normalizer.normalize_record(
                        evidence_type=EvidenceType.LOG,
                        payload=log_data,
                        session_id=session.session_id,
                        execution_id=res.execution_id,
                        application_id=session.application_id,
                        role="reference",
                        input_id=item.input_id,
                        source=ref_name,
                    )
                    records.append(log_rec)
                    item_ev_ids.append(log_rec.evidence_id)
                    self.store.save_record(log_rec)

                # Runtime Evidence
                if ev_cfg.capture_runtime:
                    rt_data = runtime_provider.capture_after(obs, after_ctx)
                    rt_rec = self.normalizer.normalize_record(
                        evidence_type=EvidenceType.RUNTIME,
                        payload=rt_data,
                        session_id=session.session_id,
                        execution_id=res.execution_id,
                        application_id=session.application_id,
                        role="reference",
                        input_id=item.input_id,
                        source=ref_name,
                    )
                    records.append(rt_rec)
                    item_ev_ids.append(rt_rec.evidence_id)
                    self.store.save_record(rt_rec)

                # Filesystem Evidence
                if ev_cfg.capture_filesystem:
                    fs_data = file_provider.capture_after(obs, after_ctx)
                    fs_rec = self.normalizer.normalize_record(
                        evidence_type=EvidenceType.FILESYSTEM,
                        payload=fs_data,
                        session_id=session.session_id,
                        execution_id=res.execution_id,
                        application_id=session.application_id,
                        role="reference",
                        input_id=item.input_id,
                        source=ref_name,
                    )
                    records.append(fs_rec)
                    item_ev_ids.append(fs_rec.evidence_id)
                    self.store.save_record(fs_rec)

                # HTTP Evidence
                if ev_cfg.capture_http:
                    http_data = http_provider.capture_after(obs, after_ctx)
                    if http_data.get("status") != EvidenceCaptureStatus.NOT_SUPPORTED.value:
                        http_rec = self.normalizer.normalize_record(
                            evidence_type=EvidenceType.HTTP,
                            payload=http_data,
                            session_id=session.session_id,
                            execution_id=res.execution_id,
                            application_id=session.application_id,
                            role="reference",
                            input_id=item.input_id,
                            source=ref_name,
                        )
                        records.append(http_rec)
                        item_ev_ids.append(http_rec.evidence_id)
                        self.store.save_record(http_rec)

                # Database Evidence
                if ev_cfg.capture_database:
                    db_data = db_provider.capture_after(obs, after_ctx)
                    db_rec = self.normalizer.normalize_record(
                        evidence_type=EvidenceType.DATABASE,
                        payload=db_data,
                        session_id=session.session_id,
                        execution_id=res.execution_id,
                        application_id=session.application_id,
                        role="reference",
                        input_id=item.input_id,
                        source=ref_name,
                    )
                    records.append(db_rec)
                    item_ev_ids.append(db_rec.evidence_id)
                    self.store.save_record(db_rec)

                # Initialize Paired Item Result
                item_results.append(
                    PairedExecutionItemResult(
                        input_id=item.input_id,
                        correlation_id=session.correlation_id,
                        reference_execution_id=res.execution_id,
                        reference_status=res.status.value,
                        reference_duration_ms=res.duration_ms,
                        reference_exit_code=res.exit_code,
                        evidence_ids=item_ev_ids,
                    )
                )

        # Reference Stop & Cleanup
        session.status = PairedExecutionStatus.REFERENCE_CLEANUP
        try:
            if hasattr(ref_adp, "stop"):
                ref_adp.stop(ref_ctx)
        except Exception as stop_exc:
            logger.warning(f"[SESSION {session.session_id}][REFERENCE] Stop error: {stop_exc}")

        try:
            if hasattr(ref_adp, "cleanup"):
                ref_adp.cleanup()
            logger.info(f"[SESSION {session.session_id}][REFERENCE] Cleanup complete")
            trace_provider.record_event("REFERENCE_CLEANUP_COMPLETE")
        except Exception as cleanup_exc:
            logger.warning(f"[SESSION {session.session_id}][REFERENCE] Cleanup error: {cleanup_exc}")
            clean_rec = self.normalizer.normalize_record(
                evidence_type=EvidenceType.ERROR,
                payload=ErrorEvidence(
                    category="CLEANUP_ERROR",
                    message=str(cleanup_exc),
                    phase="REFERENCE_CLEANUP",
                ),
                session_id=session.session_id,
                application_id=session.application_id,
                role="reference",
                source=ref_name,
            )
            records.append(clean_rec)
            self.store.save_record(clean_rec)


        # ======================================================================
        # 7. REFERENCE FAILURE POLICY CHECK
        # ======================================================================
        if ref_fatal_error:
            logger.error(
                f"[SESSION {session.session_id}] Reference execution halted. "
                "Halting before target run to prevent ungrounded paired comparison."
            )
            session.error_summary = ref_fatal_error
            session.mark_completed(PairedExecutionStatus.FAILED)

            rec = self.normalizer.normalize_record(
                evidence_type=EvidenceType.ERROR,
                payload=ErrorEvidence(
                    category="REFERENCE_FATAL_ERROR",
                    message=ref_fatal_error,
                    phase="REFERENCE_LIFECYCLE",
                ),
                session_id=session.session_id,
                application_id=session.application_id,
                role="reference",
                source=ref_name,
            )
            records.append(rec)
            self.store.save_record(rec)

            bundle = self.normalizer.build_bundle(
                session_id=session.session_id,
                correlation_id=session.correlation_id,
                application_id=session.application_id,
                input_set_id=input_set.input_set_id,
                input_set_hash=input_set.content_hash,
                records=records,
                reference_execution_ids=ref_exec_ids,
                is_partial=True,
                error_summary=ref_fatal_error,
            )
            session.bundle_id = bundle.bundle_id
            session.bundle_hash = bundle.bundle_hash
            self.store.save_session(session)
            self.store.save_bundle(bundle)
            return session, bundle

        # ======================================================================
        # 8. TARGET APPLICATION LIFECYCLE
        # ======================================================================
        session.status = PairedExecutionStatus.TARGET_STARTING
        self.store.save_session(session)
        logger.info(f"[SESSION {session.session_id}][TARGET] Starting application '{target_name}'")
        trace_provider.record_event("TARGET_STARTING", details={"adapter": target_name})

        target_fatal_error: Optional[str] = None
        target_ctx = {"session_id": session.session_id, "correlation_id": session.correlation_id, "role": "target"}
        target_proc = None

        # Target Configure, Prepare, and Start
        try:
            if hasattr(target_adp, "configure"):
                target_adp.configure(target_ctx)
            if hasattr(target_adp, "prepare"):
                target_adp.prepare(target_ctx)
            if hasattr(target_adp, "start"):
                target_proc = target_adp.start(target_ctx)
        except Exception as exc:
            target_fatal_error = f"Target adapter startup failed: {exc}"
            logger.error(f"[SESSION {session.session_id}][TARGET] {target_fatal_error}")

        # Target Readiness Check
        if not target_fatal_error and request.readiness_config_target:
            readiness_res = ReadinessChecker.wait_until_ready(
                request.readiness_config_target, adapter=target_adp, process=target_proc
            )
            if not readiness_res.ready:
                target_fatal_error = f"Target readiness failed ({readiness_res.strategy.value}): {readiness_res.diagnostics}"
                logger.error(f"[SESSION {session.session_id}][TARGET] {target_fatal_error}")
            else:
                logger.info(f"[SESSION {session.session_id}][TARGET] Application READY in {readiness_res.duration_ms}ms")
                trace_provider.record_event("TARGET_READY", details={"duration_ms": readiness_res.duration_ms})
        elif not target_fatal_error:
            logger.info(f"[SESSION {session.session_id}][TARGET] Application READY")
            trace_provider.record_event("TARGET_READY")

        session.status = PairedExecutionStatus.TARGET_RUNNING
        self.store.save_session(session)

        # Execute Inputs on Target (Identical Canonical Inputs!)
        if not target_fatal_error:
            for idx, item in enumerate(input_set.inputs):
                input_copy = item.to_canonical_input()
                logger.info(f"[SESSION {session.session_id}][TARGET][INPUT {item.input_id}] Executing")
                trace_provider.record_event("TARGET_EXECUTE_INPUT", details={"input_id": item.input_id})

                # Capture Before
                before_ctx = {
                    "session_id": session.session_id,
                    "correlation_id": session.correlation_id,
                    "input_id": item.input_id,
                    "role": "target",
                    "adapter": target_adp,
                }
                if ev_cfg.capture_filesystem:
                    file_provider.capture_before(before_ctx)
                if ev_cfg.capture_database:
                    db_provider.capture_before(before_ctx)

                # Execute Single
                res = self.executor.execute_single(
                    adapter=target_adp,
                    input_data=input_copy,
                    input_id=item.input_id,
                    session_id=session.session_id,
                    application_id=session.application_id,
                    manage_lifecycle=False,
                )

                target_exec_ids.append(res.execution_id)
                obs = res.to_observation(input_id=item.input_id)

                # Capture Evidence
                after_ctx = dict(before_ctx)
                after_ctx["execution_id"] = res.execution_id
                target_ev_ids: list[str] = []

                # Output Evidence
                if ev_cfg.capture_output:
                    out_data = output_provider.capture_after(obs, after_ctx)
                    out_rec = self.normalizer.normalize_record(
                        evidence_type=EvidenceType.OUTPUT,
                        payload=out_data,
                        session_id=session.session_id,
                        execution_id=res.execution_id,
                        application_id=session.application_id,
                        role="target",
                        input_id=item.input_id,
                        source=target_name,
                    )
                    records.append(out_rec)
                    target_ev_ids.append(out_rec.evidence_id)
                    self.store.save_record(out_rec)

                # Error Evidence if applicable
                if res.status not in (ExecutionStatus.SUCCEEDED,):
                    err_rec = self.normalizer.normalize_record(
                        evidence_type=EvidenceType.ERROR,
                        payload=ErrorEvidence(
                            category=res.status.value,
                            message=res.error_message or "Target execution failed",
                            phase="TARGET_EXECUTION",
                            exception_type=res.error_type,
                            execution_id=res.execution_id,
                        ),
                        session_id=session.session_id,
                        execution_id=res.execution_id,
                        application_id=session.application_id,
                        role="target",
                        input_id=item.input_id,
                        source=target_name,
                    )
                    records.append(err_rec)
                    target_ev_ids.append(err_rec.evidence_id)
                    self.store.save_record(err_rec)

                # Log Evidence
                if ev_cfg.capture_logs:
                    log_data = log_provider.capture_after(obs, after_ctx)
                    log_rec = self.normalizer.normalize_record(
                        evidence_type=EvidenceType.LOG,
                        payload=log_data,
                        session_id=session.session_id,
                        execution_id=res.execution_id,
                        application_id=session.application_id,
                        role="target",
                        input_id=item.input_id,
                        source=target_name,
                    )
                    records.append(log_rec)
                    target_ev_ids.append(log_rec.evidence_id)
                    self.store.save_record(log_rec)

                # Runtime Evidence
                if ev_cfg.capture_runtime:
                    rt_data = runtime_provider.capture_after(obs, after_ctx)
                    rt_rec = self.normalizer.normalize_record(
                        evidence_type=EvidenceType.RUNTIME,
                        payload=rt_data,
                        session_id=session.session_id,
                        execution_id=res.execution_id,
                        application_id=session.application_id,
                        role="target",
                        input_id=item.input_id,
                        source=target_name,
                    )
                    records.append(rt_rec)
                    target_ev_ids.append(rt_rec.evidence_id)
                    self.store.save_record(rt_rec)

                # Filesystem Evidence
                if ev_cfg.capture_filesystem:
                    fs_data = file_provider.capture_after(obs, after_ctx)
                    fs_rec = self.normalizer.normalize_record(
                        evidence_type=EvidenceType.FILESYSTEM,
                        payload=fs_data,
                        session_id=session.session_id,
                        execution_id=res.execution_id,
                        application_id=session.application_id,
                        role="target",
                        input_id=item.input_id,
                        source=target_name,
                    )
                    records.append(fs_rec)
                    target_ev_ids.append(fs_rec.evidence_id)
                    self.store.save_record(fs_rec)

                # HTTP Evidence
                if ev_cfg.capture_http:
                    http_data = http_provider.capture_after(obs, after_ctx)
                    if http_data.get("status") != EvidenceCaptureStatus.NOT_SUPPORTED.value:
                        http_rec = self.normalizer.normalize_record(
                            evidence_type=EvidenceType.HTTP,
                            payload=http_data,
                            session_id=session.session_id,
                            execution_id=res.execution_id,
                            application_id=session.application_id,
                            role="target",
                            input_id=item.input_id,
                            source=target_name,
                        )
                        records.append(http_rec)
                        target_ev_ids.append(http_rec.evidence_id)
                        self.store.save_record(http_rec)

                # Database Evidence
                if ev_cfg.capture_database:
                    db_data = db_provider.capture_after(obs, after_ctx)
                    db_rec = self.normalizer.normalize_record(
                        evidence_type=EvidenceType.DATABASE,
                        payload=db_data,
                        session_id=session.session_id,
                        execution_id=res.execution_id,
                        application_id=session.application_id,
                        role="target",
                        input_id=item.input_id,
                        source=target_name,
                    )
                    records.append(db_rec)
                    target_ev_ids.append(db_rec.evidence_id)
                    self.store.save_record(db_rec)

                # Update Paired Item Result
                if idx < len(item_results):
                    item_results[idx].target_execution_id = res.execution_id
                    item_results[idx].target_status = res.status.value
                    item_results[idx].target_duration_ms = res.duration_ms
                    item_results[idx].target_exit_code = res.exit_code
                    item_results[idx].evidence_ids.extend(target_ev_ids)

        # Target Stop & Cleanup
        session.status = PairedExecutionStatus.TARGET_CLEANUP
        try:
            if hasattr(target_adp, "stop"):
                target_adp.stop(target_ctx)
        except Exception as stop_exc:
            logger.warning(f"[SESSION {session.session_id}][TARGET] Stop error: {stop_exc}")

        try:
            if hasattr(target_adp, "cleanup"):
                target_adp.cleanup()
            logger.info(f"[SESSION {session.session_id}][TARGET] Cleanup complete")
            trace_provider.record_event("TARGET_CLEANUP_COMPLETE")
        except Exception as cleanup_exc:
            logger.warning(f"[SESSION {session.session_id}][TARGET] Cleanup error: {cleanup_exc}")
            clean_rec = self.normalizer.normalize_record(
                evidence_type=EvidenceType.ERROR,
                payload=ErrorEvidence(
                    category="CLEANUP_ERROR",
                    message=str(cleanup_exc),
                    phase="TARGET_CLEANUP",
                ),
                session_id=session.session_id,
                application_id=session.application_id,
                role="target",
                source=target_name,
            )
            records.append(clean_rec)
            self.store.save_record(clean_rec)


        # Target Failure Policy: Record error if target fatal failure occurred
        if target_fatal_error:
            logger.error(f"[SESSION {session.session_id}] Target failure encountered: {target_fatal_error}")
            session.error_summary = target_fatal_error
            rec = self.normalizer.normalize_record(
                evidence_type=EvidenceType.ERROR,
                payload=ErrorEvidence(
                    category="TARGET_FATAL_ERROR",
                    message=target_fatal_error,
                    phase="TARGET_LIFECYCLE",
                ),
                session_id=session.session_id,
                application_id=session.application_id,
                role="target",
                source=target_name,
            )
            records.append(rec)
            self.store.save_record(rec)

        # ======================================================================
        # 9. CAPTURE SESSION-LEVEL TRACE & METADATA EVIDENCE
        # ======================================================================
        logger.info(f"[SESSION {session.session_id}] Finalizing evidence bundle")
        trace_provider.record_event("SESSION_FINALIZING")

        if ev_cfg.capture_traces:
            trace_data = trace_provider.capture_after(None, {"session_id": session.session_id})
            trace_rec = self.normalizer.normalize_record(
                evidence_type=EvidenceType.TRACE,
                payload=trace_data,
                session_id=session.session_id,
                application_id=session.application_id,
                role="system",
                source="coordinator",
            )
            records.append(trace_rec)
            self.store.save_record(trace_rec)

        meta_rec = self.normalizer.normalize_record(
            evidence_type=EvidenceType.METADATA,
            payload=MetadataEvidence(
                configuration_snapshot=SecretRedactor.redact({
                    "timeout_seconds": request.timeout_seconds,
                    "evidence_config": ev_cfg.model_dump(),
                    "reference_adapter": ref_name,
                    "target_adapter": target_name,
                }),
                reproducibility_metadata=session.reproducibility_metadata,
                tags=["phase3", "paired_execution"],
            ),
            session_id=session.session_id,
            application_id=session.application_id,
            role="system",
            source="coordinator",
        )
        records.append(meta_rec)
        self.store.save_record(meta_rec)

        # ======================================================================
        # 10. COMPILE BUNDLE & FINALIZE SESSION
        # ======================================================================
        is_partial = bool(session.error_summary or any(
            r.reference_status not in ("SUCCEEDED", None) or r.target_status not in ("SUCCEEDED", None)
            for r in item_results
        ))

        bundle = self.normalizer.build_bundle(
            session_id=session.session_id,
            correlation_id=session.correlation_id,
            application_id=session.application_id,
            input_set_id=input_set.input_set_id,
            input_set_hash=input_set.content_hash,
            records=records,
            reference_execution_ids=ref_exec_ids,
            target_execution_ids=target_exec_ids,
            is_partial=is_partial,
            error_summary=session.error_summary,
        )

        session.bundle_id = bundle.bundle_id
        session.bundle_hash = bundle.bundle_hash
        session.executed_inputs = len(item_results)
        session.paired_results = item_results

        if session.error_summary:
            session.mark_completed(PairedExecutionStatus.PARTIAL if item_results else PairedExecutionStatus.FAILED)
        elif is_partial:
            session.mark_completed(PairedExecutionStatus.PARTIAL)
        else:
            session.mark_completed(PairedExecutionStatus.COMPLETED)


        self.store.save_session(session)
        saved_bundle = self.store.save_bundle(bundle)

        if saved_bundle.persistence_status == EvidencePersistenceStatus.FAILED:
            session.error_summary = f"Evidence bundle persistence failed: {saved_bundle.persistence_error}"
            session.mark_completed(PairedExecutionStatus.PARTIAL if item_results else PairedExecutionStatus.FAILED)
            self.store.save_session(session)


        logger.info(
            f"[SESSION {session.session_id}] Session complete (status={session.status.value}, "
            f"bundle_hash={bundle.bundle_hash[:12]}, evidence_count={len(records)})"
        )
        return session, saved_bundle


    def execute_sweep(
        self,
        request: PairedExecutionRequest,
        spec: Optional[ApplicationSpec] = None,
        iterations: int = 3,
    ) -> list[tuple[PairedExecutionSession, EvidenceBundle]]:
        """Executes repeated paired execution runs (sweeps) with distinct session and execution IDs."""
        sweep_results: list[tuple[PairedExecutionSession, EvidenceBundle]] = []
        for i in range(iterations):
            sweep_req = request.model_copy(deep=True)
            sweep_req.correlation_id = f"{request.correlation_id or 'SWEEP'}-iter-{i+1}"
            session, bundle = self.execute_paired(sweep_req, spec=spec)
            sweep_results.append((session, bundle))
        return sweep_results


paired_execution_coordinator = PairedExecutionCoordinator()
