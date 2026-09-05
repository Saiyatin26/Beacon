"""BEACON V2 — Application Execution Runner.

Orchestrates the lifecycle of running inputs across Reference and Target implementation
adapters, recording execution sessions, enforcing timeouts, capturing errors,
and returning canonical Observation streams.
"""

from datetime import datetime, timezone
import hashlib
import logging
import time
from typing import Any, Optional, Union

from application.models import ApplicationRole, ApplicationSpec
from certification.adapters import ImplementationAdapter
from certification.models import CanonicalInput, Observation
from .mapping import InputMapper, OutputMapper
from .models import ExecutionRequest, ExecutionResult, ExecutionSession, ExecutionStatus
from .preflight import PreFlightResult, PreFlightValidator, preflight_validator
from .repository import ExecutionRepository, execution_repository

logger = logging.getLogger("beacon.execution.runner")


class ApplicationExecutor:
    """Orchestrates the execution of ApplicationSpec models and Implementation Adapters."""

    def __init__(
        self,
        repository: Optional[ExecutionRepository] = None,
        validator: Optional[PreFlightValidator] = None,
    ):
        self.repository = repository or execution_repository
        self.validator = validator or preflight_validator

    def preflight_check(
        self,
        spec: ApplicationSpec,
        reference_adapter: Optional[ImplementationAdapter] = None,
        target_adapters: Optional[list[ImplementationAdapter]] = None,
    ) -> PreFlightResult:
        """Runs pre-flight readiness checks on the application and adapters."""
        return self.validator.validate(spec, reference_adapter, target_adapters)

    def execute_single(
        self,
        adapter: ImplementationAdapter,
        input_data: Union[CanonicalInput, dict[str, Any]],
        input_id: str = "",
        session_id: Optional[str] = None,
        application_id: str = "",
    ) -> ExecutionResult:
        """Executes a single input against an ImplementationAdapter with full lifecycle tracking."""
        exec_id = f"EXEC-{hashlib.sha256(f'{adapter.name}_{time.perf_counter()}'.encode()).hexdigest()[:12]}"
        actual_input_id = input_id or (input_data.input_id if isinstance(input_data, CanonicalInput) else exec_id)

        logger.info(f"[PHASE 02] EXECUTION_START | adapter={adapter.name} | input_id={actual_input_id}")
        start_time = time.perf_counter()

        try:
            # 1. Lifecycle Prepare
            adapter.prepare()

            # 2. Lifecycle Execute
            obs = adapter.execute(input_data, input_id=actual_input_id)
            duration_ms = obs.execution_time_ms or round((time.perf_counter() - start_time) * 1000, 3)

            # 3. Lifecycle Evidence Capture
            adapter.capture_evidence(obs)

            # 4. Map Status
            if obs.execution_status == "SUCCESS":
                status = ExecutionStatus.SUCCEEDED
            elif obs.execution_status == "TIMEOUT":
                status = ExecutionStatus.TIMEOUT
            elif obs.execution_status == "APP_EXECUTION_ERROR":
                status = ExecutionStatus.APP_EXECUTION_ERROR
            elif obs.execution_status == "VALIDATION_ERROR":
                status = ExecutionStatus.VALIDATION_ERROR
            else:
                status = ExecutionStatus.FAILED

            result = ExecutionResult(
                execution_id=exec_id,
                session_id=session_id,
                application_id=application_id,
                implementation_id=adapter.name,
                role=adapter.role,
                status=status,
                observation=obs,
                stdout=obs.provenance.get("stdout"),
                stderr=obs.provenance.get("stderr"),
                exit_code=obs.provenance.get("exit_code"),
                duration_ms=duration_ms,
                error_type=obs.provenance.get("error_type"),
                error_message=obs.error_message,
                implementation_identity={"name": adapter.name, "version": adapter.version, "hash": adapter.implementation_hash},
                runtime_identity={"role": str(adapter.role)},
            )

            # Persist result
            self.repository.save_result(result)
            return result

        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 3)
            logger.error(f"[PHASE 02] ADAPTER_ERROR | adapter={adapter.name} | error={exc}")
            obs = Observation(
                input_id=actual_input_id,
                raw_inputs=input_data.get_data() if isinstance(input_data, CanonicalInput) else dict(input_data),
                normalized_inputs=input_data.get_data() if isinstance(input_data, CanonicalInput) else dict(input_data),
                raw_outputs={"error": str(exc)},
                normalized_outputs={"error": str(exc)},
                execution_status="EXCEPTION",
                implementation_name=adapter.name,
                implementation_version=adapter.version,
                execution_time_ms=duration_ms,
                error_message=str(exc),
                provenance={"adapter_error": True, "role": str(adapter.role)},
            )

            result = ExecutionResult(
                execution_id=exec_id,
                session_id=session_id,
                application_id=application_id,
                implementation_id=adapter.name,
                role=adapter.role,
                status=ExecutionStatus.ADAPTER_ERROR,
                observation=obs,
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
                error_message=str(exc),
                implementation_identity={"name": adapter.name, "version": adapter.version, "hash": adapter.implementation_hash},
            )
            self.repository.save_result(result)
            return result

        finally:
            # 5. Lifecycle Cleanup (Guaranteed execution in finally block)
            try:
                adapter.cleanup()
            except Exception as cleanup_exc:
                logger.warning(f"Adapter '{adapter.name}' cleanup notice: {cleanup_exc}")

    def execute_batch(
        self,
        adapter: ImplementationAdapter,
        inputs: list[Union[CanonicalInput, dict[str, Any]]],
        application_id: str = "",
    ) -> tuple[ExecutionSession, list[ExecutionResult]]:
        """Executes an ordered batch of inputs within a tracked ExecutionSession."""
        session = ExecutionSession(
            application_id=application_id or adapter.name,
            adapter_id=adapter.name,
            role=adapter.role,
            records_count=len(inputs),
            implementation_identity={"name": adapter.name, "version": adapter.version, "hash": adapter.implementation_hash},
            runtime_identity={"role": str(adapter.role)},
        )
        self.repository.save_session(session)

        results: list[ExecutionResult] = []
        for idx, inp in enumerate(inputs):
            inp_id = inp.input_id if isinstance(inp, CanonicalInput) else f"INP-{idx+1:04d}"
            res = self.execute_single(
                adapter=adapter,
                input_data=inp,
                input_id=inp_id,
                session_id=session.session_id,
                application_id=application_id,
            )
            results.append(res)
            if res.status == ExecutionStatus.SUCCEEDED:
                session.succeeded_count += 1
            elif res.status == ExecutionStatus.TIMEOUT:
                session.timeout_count += 1
            else:
                session.failed_count += 1

        session.mark_completed()
        self.repository.save_session(session)
        logger.info(
            f"[PHASE 02] BATCH_COMPLETED | session={session.session_id} | total={len(inputs)} "
            f"| succeeded={session.succeeded_count} | failed={session.failed_count} | timeout={session.timeout_count}"
        )
        return session, results


application_executor = ApplicationExecutor()
