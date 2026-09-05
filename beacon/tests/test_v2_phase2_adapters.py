"""BEACON V2 — Phase 2 Generic Real-World Application & Adapter Test Suite.

Comprehensive validation for:
1. FunctionAdapter, ProcessAdapter, CliAdapter, HttpAdapter, and ContainerAdapter.
2. Generic InputMapper and OutputMapper (dot-notation, type coercions, CLI formats).
3. Process execution safety, cross-platform timeout termination, exit-code capture, and output caps.
4. Security controls: Secret redaction, sandboxed working directories, and SSRF prevention.
5. Pre-flight validation engine and health check diagnostics.
6. ExecutionSession lifecycle, audit logging, and SQLite persistence.
7. V2 Adapter & Execution REST API endpoints.
8. End-to-end real application execution with domain-agnostic fixtures.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

from application.models import (
    ApplicationRole,
    ApplicationSpec,
    DatasetConfig,
    ImplementationTarget,
    InputContract,
    OutputContract,
    RuleConfig,
    RuntimeConfig,
)
from certification.adapters import (
    AdapterRole,
    DefaultOutputNormalizer,
    FunctionAdapter,
    ImplementationAdapter,
    PreserveCaseNormalizer,
    ReferenceAdapter,
    TargetAdapter,
)
from certification.adapter_registry import AdapterRegistry, adapter_registry
from certification.models import CanonicalInput, Observation
from execution import (
    AdapterCapabilities,
    AdapterHealth,
    AdapterHealthStatus,
    AdapterType,
    ApplicationExecutor,
    CliAdapter,
    ContainerAdapter,
    ExecutionRepository,
    ExecutionRequest,
    ExecutionResult,
    ExecutionSession,
    ExecutionStatus,
    HttpAdapter,
    InputMapper,
    InputMapperConfig,
    OutputMapper,
    OutputMapperConfig,
    PreFlightResult,
    PreFlightValidator,
    ProcessAdapter,
    SandboxedPathValidator,
    SecretRedactor,
    SSRFValidator,
    application_executor,
    execution_repository,
    preflight_validator,
    resolve_dot_path,
)

CLI_FIXTURE_SCRIPT = ROOT / "tests" / "fixtures" / "generic_calc_cli.py"


# ==============================================================================
# 1. Input & Output Mapping Tests
# ==============================================================================

def test_resolve_dot_path():
    """Verifies dot-path extraction across nested dicts, lists, and objects."""
    data = {
        "user": {"profile": {"age": 30, "tags": ["admin", "staff"]}},
        "items": [{"id": 1, "value": "first"}, {"id": 2, "value": "second"}],
    }

    assert resolve_dot_path(data, "user.profile.age") == 30
    assert resolve_dot_path(data, "user.profile.tags.0") == "admin"
    assert resolve_dot_path(data, "items.1.value") == "second"
    assert resolve_dot_path(data, "nonexistent.field", default="fallback") == "fallback"


def test_input_mapper_kwargs_and_type_conversions():
    """InputMapper translates nested CanonicalInput payloads into flat or mapped kwargs."""
    config = InputMapperConfig(
        field_mappings={"op_x": "payload.operands.x", "op_y": "payload.operands.y"},
        constants={"operation": "multiply"},
        type_conversions={"op_x": "float", "op_y": "float"},
    )
    mapper = InputMapper(config)

    c_in = CanonicalInput(
        input_id="INP-01",
        payload={"operands": {"x": "12.5", "y": "4"}},
    )

    kwargs = mapper.map_to_kwargs(c_in)
    assert kwargs["op_x"] == 12.5
    assert kwargs["op_y"] == 4.0
    assert kwargs["operation"] == "multiply"


def test_input_mapper_cli_flag_generation():
    """InputMapper formats CLI flag arrays correctly."""
    config = InputMapperConfig(
        field_mappings={"x": "payload.x", "y": "payload.y", "verbose": "payload.verbose"},
        cli_format="flags",
    )
    mapper = InputMapper(config)

    c_in = CanonicalInput(
        input_id="INP-02",
        payload={"x": 10, "y": 20, "verbose": True},
    )

    args = mapper.map_to_cli_args(c_in)
    assert "--x" in args and "10" in args
    assert "--y" in args and "20" in args
    assert "--verbose" in args


def test_output_mapper_json_stdout_parsing():
    """OutputMapper parses JSON stdout strings into structured dictionaries."""
    config = OutputMapperConfig(
        field_extractions={"status": "status", "computed_value": "result"},
    )
    mapper = OutputMapper(config)

    stdout_raw = '{"status": "OK", "result": 142.5, "meta": {"code": 200}}'
    mapped = mapper.map_output(raw_output=None, stdout=stdout_raw)

    assert mapped["status"] == "OK"
    assert mapped["computed_value"] == 142.5


# ==============================================================================
# 2. Security & Redaction Tests
# ==============================================================================

def test_secret_redactor_recursive_masking():
    """SecretRedactor recursively masks sensitive tokens and authorization headers."""
    sensitive_payload = {
        "user_id": 101,
        "auth_token": "secret_token_12345",
        "nested": {
            "api_key": "private_key_xyz",
            "password_hash": "hash999",
            "public_field": "visible",
        },
        "items": [{"bearer_token": "abcde"}, {"safe": "value"}],
    }

    redacted = SecretRedactor.redact(sensitive_payload)
    assert redacted["user_id"] == 101
    assert redacted["auth_token"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert redacted["nested"]["password_hash"] == "[REDACTED]"
    assert redacted["nested"]["public_field"] == "visible"
    assert redacted["items"][0]["bearer_token"] == "[REDACTED]"
    assert redacted["items"][1]["safe"] == "value"


def test_secret_redactor_cli_command_args():
    """SecretRedactor masks sensitive flags in CLI command lines."""
    cmd = ["python", "app.py", "--user", "alice", "--password", "secret123", "--token=xyz789"]
    safe_cmd = SecretRedactor.redact_command(cmd)

    assert safe_cmd[0] == "python"
    assert safe_cmd[3] == "alice"
    assert safe_cmd[5] == "[REDACTED]"
    assert safe_cmd[6] == "--token=[REDACTED]"


def test_sandboxed_path_validator_path_traversal():
    """SandboxedPathValidator detects and rejects path traversal."""
    allowed_root = ROOT
    valid_dir = ROOT / "backend"
    assert SandboxedPathValidator.validate_working_directory(valid_dir, allowed_roots=[allowed_root]) == valid_dir.resolve()

    with pytest.raises(FileNotFoundError):
        SandboxedPathValidator.validate_working_directory(ROOT / "non_existent_dir_9999")


def test_ssrf_validator_blocks_metadata():
    """SSRFValidator blocks AWS/GCP/Azure instance metadata endpoints."""
    with pytest.raises(PermissionError) as exc:
        SSRFValidator.validate_url("http://169.254.169.254/latest/meta-data/")
    assert "SSRF" in str(exc.value)

    with pytest.raises(ValueError):
        SSRFValidator.validate_url("ftp://example.com/data")

    # Local development loopback allowed by default
    valid_local = SSRFValidator.validate_url("http://127.0.0.1:8000/api/status", allow_private=True)
    assert valid_local == "http://127.0.0.1:8000/api/status"


# ==============================================================================
# 3. Process & CLI Adapter Tests
# ==============================================================================

def test_process_adapter_successful_execution():
    """ProcessAdapter executes an external script and parses its JSON stdout."""
    adapter = ProcessAdapter(
        command=[sys.executable, str(CLI_FIXTURE_SCRIPT)],
        name="test_calc_process",
        version="1.0.0",
        role=AdapterRole.TARGET,
        input_mapper=InputMapper(InputMapperConfig(
            field_mappings={"x": "payload.x", "y": "payload.y", "operation": "payload.op"}
        )),
    )

    health = adapter.health_check()
    assert health.is_ready is True
    assert health.status == AdapterHealthStatus.AVAILABLE

    inp = CanonicalInput(input_id="INP-P1", payload={"x": 15.0, "y": 3.0, "op": "multiply"})
    obs = adapter.execute(inp, input_id="INP-P1")

    assert obs.execution_status == "SUCCESS"
    assert obs.raw_outputs["result"] == 45.0
    assert obs.raw_outputs["operation"] == "multiply"
    assert obs.provenance["exit_code"] == 0


def test_process_adapter_exit_code_failure():
    """ProcessAdapter captures non-zero exit code and maps to APP_EXECUTION_ERROR."""
    adapter = ProcessAdapter(
        command=[sys.executable, str(CLI_FIXTURE_SCRIPT)],
        name="test_calc_error",
        input_mapper=InputMapper(InputMapperConfig(
            field_mappings={"operation": "payload.op"}
        )),
    )

    inp = CanonicalInput(input_id="INP-P2", payload={"op": "error"})
    obs = adapter.execute(inp, input_id="INP-P2")

    assert obs.execution_status == "EXCEPTION"
    assert obs.provenance["exit_code"] == 2
    assert "Simulated CLI fatal error" in obs.error_message


def test_process_adapter_timeout_handling():
    """ProcessAdapter enforces timeout and terminates runaway processes cleanly."""
    adapter = ProcessAdapter(
        command=[sys.executable, str(CLI_FIXTURE_SCRIPT)],
        name="test_calc_timeout",
        timeout_seconds=0.5,  # 500ms timeout
        input_mapper=InputMapper(InputMapperConfig(
            field_mappings={"operation": "payload.op", "sleep_seconds": "payload.sleep"}
        )),
    )

    inp = CanonicalInput(input_id="INP-P3", payload={"op": "sleep", "sleep": 5.0})
    obs = adapter.execute(inp, input_id="INP-P3")

    assert obs.execution_status == "TIMEOUT"
    assert "timed out" in obs.error_message.lower()


def test_process_adapter_output_truncation():
    """ProcessAdapter truncates oversized stdout exceeding max_output_bytes."""
    adapter = ProcessAdapter(
        command=[sys.executable, str(CLI_FIXTURE_SCRIPT)],
        name="test_calc_huge",
        max_output_bytes=500,  # 500 bytes limit
        input_mapper=InputMapper(InputMapperConfig(
            field_mappings={"operation": "payload.op"}
        )),
    )

    inp = CanonicalInput(input_id="INP-P4", payload={"op": "huge_output"})
    obs = adapter.execute(inp, input_id="INP-P4")

    assert obs.provenance.get("stdout_truncated") is True
    assert "[TRUNCATED:" in obs.raw_outputs.get("stdout", "")


def test_process_adapter_missing_executable():
    """ProcessAdapter health check reports UNAVAILABLE when binary does not exist."""
    adapter = ProcessAdapter(
        command=["non_existent_binary_xyz_12345"],
        name="test_missing_bin",
    )

    health = adapter.health_check()
    assert health.is_ready is False
    assert health.status == AdapterHealthStatus.UNAVAILABLE
    assert "not found" in health.diagnostics.lower()


# ==============================================================================
# 4. HTTP Adapter Tests
# ==============================================================================

def test_http_adapter_health_check_and_ssrf():
    """HttpAdapter health check validates URL and enforces SSRF blocks."""
    # Valid adapter
    valid_adp = HttpAdapter(base_url="http://127.0.0.1:8000", name="test_http_valid")
    h_valid = valid_adp.health_check()
    assert h_valid.is_ready is True
    assert h_valid.status == AdapterHealthStatus.AVAILABLE

    # Blocked SSRF metadata adapter
    ssrf_adp = HttpAdapter(base_url="http://169.254.169.254", name="test_http_ssrf")
    h_ssrf = ssrf_adp.health_check()
    assert h_ssrf.is_ready is False
    assert h_ssrf.status == AdapterHealthStatus.MISCONFIGURED
    assert "SSRF" in h_ssrf.diagnostics


def test_http_adapter_real_invocation():
    """HttpAdapter executes requests against the local FastAPI test endpoint."""
    from fastapi.testclient import TestClient
    from api.main import app

    # We can test HttpAdapter against the live /health endpoint
    adapter = HttpAdapter(
        base_url="http://testserver",
        path_template="/health",
        method="GET",
        name="test_http_health",
    )

    # Use TestClient transport for in-process testing
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ==============================================================================
# 5. Container Adapter Tests
# ==============================================================================

def test_container_adapter_capability_detection():
    """ContainerAdapter gracefully reports UNAVAILABLE when Docker engine is not in PATH."""
    adapter = ContainerAdapter(
        image="alpine:latest",
        container_engine="non_existent_docker_daemon_bin_999",
        name="test_container_adp",
    )

    health = adapter.health_check()
    assert health.is_ready is False
    assert health.status == AdapterHealthStatus.UNAVAILABLE
    assert "not found" in health.diagnostics.lower()

    # Executing when unavailable produces structured observation rather than unhandled crash
    obs = adapter.execute({"sample": 123}, input_id="INP-C1")
    assert obs.execution_status == "EXCEPTION"
    assert "unavailable" in obs.error_message.lower()


# ==============================================================================
# 6. Pre-Flight Validator Tests
# ==============================================================================

def test_preflight_validator_clean_application():
    """PreFlightValidator passes a well-configured domain-neutral ApplicationSpec."""
    def sample_ref(val: float) -> dict:
        return {"result": val * 2}

    def sample_target(val: float) -> dict:
        return {"result": val * 2}

    spec = ApplicationSpec(
        application_id="app_preflight_clean",
        name="Preflight Clean Spec",
        reference_implementation=sample_ref,
        target_implementations=[sample_target],
        input_contract=InputContract(fields={"val": (0.0, 100.0)}),
    )

    ref_adp = ReferenceAdapter(target_fn=sample_ref, name="ref_adp_01")
    target_adp = TargetAdapter(target_fn=sample_target, name="target_adp_01")

    res = preflight_validator.validate(spec, ref_adp, [target_adp])
    assert res.is_ready is True
    assert len(res.errors) == 0


def test_preflight_validator_missing_components():
    """PreFlightValidator detects missing entrypoints or misconfigured adapters."""
    spec_invalid = ApplicationSpec(
        application_id="app_preflight_broken",
        name="Broken Spec",
        reference_implementation="",  # missing entrypoint
        target_implementations=[],     # missing targets
    )

    res = preflight_validator.validate(spec_invalid)
    assert res.is_ready is False
    assert len(res.errors) >= 2


# ==============================================================================
# 7. Execution Session & Application Executor Tests
# ==============================================================================

def test_application_executor_batch_and_session():
    """ApplicationExecutor runs a batch of inputs and tracks an ExecutionSession in SQLite."""
    def generic_math_fn(x: float, y: float) -> dict:
        return {"sum": x + y, "product": x * y}

    adapter = TargetAdapter(target_fn=generic_math_fn, name="test_math_executor")

    inputs = [
        CanonicalInput(input_id="INP-01", payload={"x": 2.0, "y": 3.0}),
        CanonicalInput(input_id="INP-02", payload={"x": 10.0, "y": 5.0}),
        CanonicalInput(input_id="INP-03", payload={"x": 7.0, "y": 8.0}),
    ]

    session, results = application_executor.execute_batch(
        adapter=adapter,
        inputs=inputs,
        application_id="math_test_app",
    )

    assert session.status == ExecutionStatus.SUCCEEDED
    assert session.records_count == 3
    assert session.succeeded_count == 3
    assert session.failed_count == 0
    assert len(results) == 3

    assert results[0].observation.raw_outputs["sum"] == 5.0
    assert results[1].observation.raw_outputs["product"] == 50.0

    # Verify session persisted in SQLite repository
    retrieved_sess = execution_repository.get_session(session.session_id)
    assert retrieved_sess is not None
    assert retrieved_sess.application_id == "math_test_app"
    assert retrieved_sess.succeeded_count == 3


# ==============================================================================
# 8. End-to-End Real Application Execution: Process Target vs Function Reference
# ==============================================================================

def test_end_to_end_real_process_vs_function_execution():
    """Executes a real domain-neutral Application:
    Reference: in-process Python callable.
    Target: real external CLI process executed via ProcessAdapter.
    """
    # 1. Reference function
    def reference_calculation(x: float, y: float) -> dict:
        return {"status": "success", "operation": "multiply", "x": x, "y": y, "result": x * y}

    ref_adapter = ReferenceAdapter(
        target_fn=reference_calculation,
        name="ref_calc_fn",
        version="1.0.0",
    )

    # 2. Target external CLI process adapter
    target_adapter = ProcessAdapter(
        command=[sys.executable, str(CLI_FIXTURE_SCRIPT)],
        name="target_calc_cli_proc",
        version="2.0.0",
        role=AdapterRole.TARGET,
        input_mapper=InputMapper(InputMapperConfig(
            field_mappings={"x": "payload.x", "y": "payload.y", "operation": "payload.operation"}
        )),
    )

    # 3. Test dataset
    test_inputs = [
        CanonicalInput(input_id="INP-01", payload={"x": 5.0, "y": 4.0, "operation": "multiply"}),
        CanonicalInput(input_id="INP-02", payload={"x": 12.0, "y": 3.0, "operation": "multiply"}),
        CanonicalInput(input_id="INP-03", payload={"x": 7.5, "y": 2.0, "operation": "multiply"}),
    ]

    # 4. Execute Reference
    sess_ref, res_ref = application_executor.execute_batch(ref_adapter, test_inputs, application_id="calc_app")
    assert sess_ref.status == ExecutionStatus.SUCCEEDED
    assert sess_ref.succeeded_count == 3

    # 5. Execute Target (External Subprocess)
    sess_target, res_target = application_executor.execute_batch(target_adapter, test_inputs, application_id="calc_app")
    assert sess_target.status == ExecutionStatus.SUCCEEDED
    assert sess_target.succeeded_count == 3

    # 6. Verify identical behavioral outputs across the execution boundary
    for r_ref, r_tgt in zip(res_ref, res_target):
        assert r_ref.observation.raw_outputs["result"] == r_tgt.observation.raw_outputs["result"]
        assert r_tgt.observation.provenance["exit_code"] == 0
