"""BEACON V2 — Application & Adapter Pre-Flight Validation Engine.

Performs structured pre-flight readiness checks on ApplicationSpecs,
Implementation Adapters, runtime dependencies, working directories, and input contracts
prior to certification sweeps.

IMPORTANT: Pre-flight determines *execution readiness* only.
It does NOT perform behavioral evaluation or certification.
"""

import logging
from typing import Any, Optional, Union
from pydantic import BaseModel, Field

from application.models import ApplicationRole, ApplicationSpec, ImplementationTarget
from common.contracts import (
    AdapterHealth,
    AdapterHealthStatus,
    AdapterRegistry,
    adapter_registry,
    ImplementationAdapter,
)

logger = logging.getLogger("beacon.execution.preflight")


class PreFlightCheck(BaseModel):
    """Result of a single pre-flight diagnostic check."""
    check_name: str
    target: str
    passed: bool
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class PreFlightResult(BaseModel):
    """Aggregate result of all pre-flight readiness checks."""
    is_ready: bool
    application_id: str
    checks: list[PreFlightCheck] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reference_adapter_status: Optional[AdapterHealth] = None
    target_adapters_status: list[AdapterHealth] = Field(default_factory=list)


class PreFlightValidator:
    """Validates that an ApplicationSpec and its associated adapters can execute cleanly."""

    def __init__(self, registry: Optional[AdapterRegistry] = None):
        self.registry = registry or adapter_registry

    def validate(
        self,
        spec: ApplicationSpec,
        reference_adapter: Optional[ImplementationAdapter] = None,
        target_adapters: Optional[list[ImplementationAdapter]] = None,
        allow_synthetic_inputs: Optional[bool] = None,
    ) -> PreFlightResult:
        checks: list[PreFlightCheck] = []
        errors: list[str] = []
        warnings: list[str] = []

        # 1. Validate ApplicationSpec structure
        if not spec.application_id:
            errors.append("ApplicationSpec application_id cannot be empty.")
            checks.append(PreFlightCheck(
                check_name="spec_id_check",
                target="spec",
                passed=False,
                message="application_id is missing",
            ))
        else:
            checks.append(PreFlightCheck(
                check_name="spec_id_check",
                target="spec",
                passed=True,
                message=f"Application ID '{spec.application_id}' is valid.",
            ))

        # 2. Validate Reference Implementation & Adapter
        ref_health: Optional[AdapterHealth] = None
        if reference_adapter:
            ref_health = reference_adapter.health_check() if hasattr(reference_adapter, "health_check") else (
                AdapterHealth(adapter_id=getattr(reference_adapter, "name", "ref_adp"))
            )
            if not ref_health.is_ready:
                errors.append(f"Reference adapter '{reference_adapter.name}' is not ready: {ref_health.diagnostics}")
            checks.append(PreFlightCheck(
                check_name="reference_adapter_health",
                target=reference_adapter.name,
                passed=ref_health.is_ready,
                message=ref_health.diagnostics,
                details=ref_health.details,
            ))
        else:
            ref_target = spec.get_reference_target()
            if not ref_target.entrypoint:
                errors.append("Reference implementation target has no valid entrypoint.")
                checks.append(PreFlightCheck(
                    check_name="reference_entrypoint_check",
                    target="reference",
                    passed=False,
                    message="Reference implementation entrypoint is missing.",
                ))
            else:
                checks.append(PreFlightCheck(
                    check_name="reference_entrypoint_check",
                    target="reference",
                    passed=True,
                    message="Reference target entrypoint specified.",
                ))

        # 3. Validate Target Implementations & Adapters
        targets_health: list[AdapterHealth] = []
        if target_adapters:
            for adp in target_adapters:
                h = adp.health_check() if hasattr(adp, "health_check") else AdapterHealth(adapter_id=getattr(adp, "name", "target_adp"))
                targets_health.append(h)
                if not h.is_ready:
                    errors.append(f"Target adapter '{adp.name}' is not ready: {h.diagnostics}")
                checks.append(PreFlightCheck(
                    check_name="target_adapter_health",
                    target=adp.name,
                    passed=h.is_ready,
                    message=h.diagnostics,
                    details=h.details,
                ))
        else:
            targets = spec.get_target_candidates()
            if not targets:
                errors.append("No target candidates defined in ApplicationSpec.")
                checks.append(PreFlightCheck(
                    check_name="target_candidates_check",
                    target="targets",
                    passed=False,
                    message="ApplicationSpec has zero target implementations.",
                ))
            else:
                for idx, t in enumerate(targets):
                    if not t.entrypoint:
                        errors.append(f"Target implementation #{idx} ({t.name}) has no valid entrypoint.")
                    checks.append(PreFlightCheck(
                        check_name="target_entrypoint_check",
                        target=t.name,
                        passed=bool(t.entrypoint),
                        message=f"Target {t.name} entrypoint check.",
                    ))

        # 4. Validate Input Source (Explicit Dataset, InputContract fields, or Explicit Synthetic Fallback)
        from pathlib import Path
        has_dataset = False
        dataset_desc = ""

        # 4A. Check dataset_config
        if spec.dataset_config:
            if spec.dataset_config.dataset_path:
                p = Path(spec.dataset_config.dataset_path)
                if not p.exists():
                    errors.append(f"Configured dataset_path does not exist: '{spec.dataset_config.dataset_path}'")
                    checks.append(PreFlightCheck(
                        check_name="input_source_check",
                        target="dataset",
                        passed=False,
                        message=f"Dataset file '{spec.dataset_config.dataset_path}' does not exist.",
                    ))
                else:
                    has_dataset = True
                    dataset_desc = f"path '{p.name}'"
            elif getattr(spec.dataset_config, "dataset_id", None):
                ds_id = spec.dataset_config.dataset_id
                try:
                    from ingestion.dataset_registry import user_dataset_registry
                    if not user_dataset_registry.get_dataset(ds_id):
                        errors.append(f"Configured dataset_id '{ds_id}' not found in registry.")
                        checks.append(PreFlightCheck(
                            check_name="input_source_check",
                            target="dataset",
                            passed=False,
                            message=f"Dataset '{ds_id}' not found in registry.",
                        ))
                    else:
                        has_dataset = True
                        dataset_desc = f"registered dataset '{ds_id}'"
                except Exception:
                    has_dataset = True
                    dataset_desc = f"registered dataset '{ds_id}'"
            elif spec.dataset_config.metadata.get("records"):
                has_dataset = True
                dataset_desc = f"inline records ({len(spec.dataset_config.metadata['records'])})"

        # 4B. Check spec metadata dataset references
        if not has_dataset and not any(c.check_name == "input_source_check" and not c.passed for c in checks):
            if spec.metadata.get("dataset_path"):
                p = Path(spec.metadata["dataset_path"])
                if not p.exists():
                    errors.append(f"Metadata dataset_path does not exist: '{spec.metadata['dataset_path']}'")
                    checks.append(PreFlightCheck(
                        check_name="input_source_check",
                        target="dataset",
                        passed=False,
                        message=f"Dataset file '{spec.metadata['dataset_path']}' does not exist.",
                    ))
                else:
                    has_dataset = True
                    dataset_desc = f"metadata dataset path '{p.name}'"
            elif spec.metadata.get("dataset_id"):
                has_dataset = True
                dataset_desc = f"metadata dataset '{spec.metadata['dataset_id']}'"
            elif spec.metadata.get("dataset_records"):
                has_dataset = True
                dataset_desc = "metadata inline dataset records"

        # 4C. Evaluate input source pass/fail
        if has_dataset and not any(c.check_name == "input_source_check" and not c.passed for c in checks):
            checks.append(PreFlightCheck(
                check_name="input_source_check",
                target="dataset",
                passed=True,
                message=f"Explicit dataset configured: {dataset_desc}.",
            ))
        elif not any(c.check_name == "input_source_check" and not c.passed for c in checks):
            # Check Input Contract
            if spec.input_contract and spec.input_contract.fields:
                checks.append(PreFlightCheck(
                    check_name="input_source_check",
                    target="input_contract",
                    passed=True,
                    message=f"Input contract defines {len(spec.input_contract.fields)} fields.",
                ))
            else:
                # No dataset and no input contract fields -> check explicit synthetic fallback
                effective_allow_synthetic = allow_synthetic_inputs
                if effective_allow_synthetic is None:
                    if "allow_synthetic_inputs" in spec.metadata:
                        effective_allow_synthetic = bool(spec.metadata["allow_synthetic_inputs"])
                    else:
                        from common.config import settings
                        if callable(getattr(settings, "get_allow_synthetic_inputs", None)):
                            effective_allow_synthetic = settings.get_allow_synthetic_inputs()
                        else:
                            effective_allow_synthetic = getattr(settings, "allow_synthetic_inputs", False)

                if effective_allow_synthetic:
                    warnings.append("TEST/DEVELOPMENT ONLY: No explicit input source; synthetic input fallback is explicitly enabled.")
                    checks.append(PreFlightCheck(
                        check_name="input_source_check",
                        target="synthetic_fallback",
                        passed=True,
                        message="Synthetic input fallback explicitly enabled for test/development.",
                    ))
                else:
                    errors.append(
                        f"ApplicationSpec '{spec.application_id}' has no valid input source: "
                        "no dataset provided, no explicit InputContract fields declared, and synthetic fallback is disabled."
                    )
                    checks.append(PreFlightCheck(
                        check_name="input_source_check",
                        target="input_source",
                        passed=False,
                        message="No valid input source configured.",
                    ))

        # 5. Validate Runtime Configuration if present
        if spec.runtime:
            if spec.runtime.working_directory:
                from .security import SandboxedPathValidator
                try:
                    SandboxedPathValidator.validate_working_directory(spec.runtime.working_directory)
                    checks.append(PreFlightCheck(
                        check_name="working_directory_check",
                        target="runtime",
                        passed=True,
                        message=f"Working directory '{spec.runtime.working_directory}' verified.",
                    ))
                except Exception as exc:
                    errors.append(f"Runtime working directory validation failed: {exc}")
                    checks.append(PreFlightCheck(
                        check_name="working_directory_check",
                        target="runtime",
                        passed=False,
                        message=str(exc),
                    ))

        is_ready = len(errors) == 0

        return PreFlightResult(
            is_ready=is_ready,
            application_id=spec.application_id,
            checks=checks,
            errors=errors,
            warnings=warnings,
            reference_adapter_status=ref_health,
            target_adapters_status=targets_health,
        )


preflight_validator = PreFlightValidator()
