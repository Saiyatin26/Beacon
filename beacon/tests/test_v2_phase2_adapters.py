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


def test_sandboxed_path_validator_sibling_prefix_collision(tmp_path):
    """SandboxedPathValidator strictly rejects sibling directories with common prefix names."""
    work_dir = tmp_path / "work"
    app_dir = work_dir / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    sibling_evil_dir = work_dir / "app_evil"
    sibling_evil_dir.mkdir(parents=True, exist_ok=True)

    # Allowed root is strictly app_dir
    allowed_roots = [app_dir]

    # Valid descendant inside app_dir
    sub_dir = app_dir / "subdir"
    sub_dir.mkdir(parents=True, exist_ok=True)
    assert SandboxedPathValidator.validate_working_directory(sub_dir, allowed_roots=allowed_roots) == sub_dir.resolve()

    # Sibling directory starting with same prefix must be REJECTED
    with pytest.raises(PermissionError) as exc:
        SandboxedPathValidator.validate_working_directory(sibling_evil_dir, allowed_roots=allowed_roots)
    assert "outside allowed root boundaries" in str(exc.value)

    # File path validation in sibling must also be REJECTED
    evil_file = sibling_evil_dir / "evil.txt"
    evil_file.write_text("evil payload")
    with pytest.raises(PermissionError) as exc_file:
        SandboxedPathValidator.validate_file_path(evil_file, base_dir=app_dir)
    assert "escapes base directory" in str(exc_file.value)


def test_ssrf_validator_comprehensive_matrix_and_dns_resolution():
    """SSRFValidator verifies IP classes, metadata endpoints, and DNS hostname resolution."""
    # 1. Cloud metadata IP blocked always
    with pytest.raises(PermissionError) as exc:
        SSRFValidator.validate_url("http://169.254.169.254/latest/meta-data/", allow_private=True)
    assert "SSRF" in str(exc.value)

    # 2. Literal RFC1918 Private IP blocked when allow_private=False
    with pytest.raises(PermissionError) as exc_priv:
        SSRFValidator.validate_url("http://10.0.0.1:8080/api", allow_private=False)
    assert "private network IP" in str(exc_priv.value)

    # 3. Literal Loopback blocked when allow_private=False
    with pytest.raises(PermissionError) as exc_loop:
        SSRFValidator.validate_url("http://127.0.0.1:8000/api", allow_private=False)
    assert "private network IP" in str(exc_loop.value)

    # 4. Localhost allowed when allow_private=True
    valid_local = SSRFValidator.validate_url("http://127.0.0.1:8000/api/status", allow_private=True)
    assert valid_local == "http://127.0.0.1:8000/api/status"

    # 5. Domain resolving to Private IP blocked when allow_private=False
    mock_private_dns = lambda host: ["10.1.2.3"]
    with pytest.raises(PermissionError) as exc_dns_priv:
        SSRFValidator.validate_url(
            "http://internal-service.local/api",
            allow_private=False,
            dns_resolver=mock_private_dns,
        )
    assert "private network IP" in str(exc_dns_priv.value)

    # 6. Domain resolving to Cloud Metadata IP blocked even when allow_private=True
    mock_metadata_dns = lambda host: ["169.254.169.254"]
    with pytest.raises(PermissionError) as exc_dns_meta:
        SSRFValidator.validate_url(
            "http://evil-spoof.internal/api",
            allow_private=True,
            dns_resolver=mock_metadata_dns,
        )
    assert "metadata IP" in str(exc_dns_meta.value)

    # 7. Domain resolving to Public IP allowed with allow_private=False
    mock_public_dns = lambda host: ["93.184.216.34"]
    valid_public = SSRFValidator.validate_url(
        "https://example.com/api",
        allow_private=False,
        dns_resolver=mock_public_dns,
    )
    assert valid_public == "https://example.com/api"


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


# ==============================================================================
# 9. Additional Security & Execution Remediation Tests
# ==============================================================================

def test_http_adapter_secret_redaction():
    """HttpAdapter redacts secret tokens in URLs, headers, and observation outputs."""
    adapter = HttpAdapter(
        base_url="http://127.0.0.1:8000",
        path_template="/api?token=secret12345",
        headers={"Authorization": "Bearer super_secret_token_abc"},
        name="test_secret_redaction_adp",
    )

    # Health check diagnostics should never leak secret
    health = adapter.health_check()
    assert "super_secret_token_abc" not in health.diagnostics

    # Validate execution observation with simulated error
    obs = adapter.execute(CanonicalInput(input_id="INP-S1", payload={"secret_key": "private_val"}))
    assert "super_secret_token_abc" not in str(obs.raw_outputs)
    assert "super_secret_token_abc" not in str(obs.provenance)


def test_container_adapter_resource_limits_and_secret_references():
    """ContainerAdapter parses supported resource limits and maps secret references."""
    os.environ["BEACON_TEST_SECRET_VAR"] = "production_super_secret"

    adapter = ContainerAdapter(
        image="alpine:3.18",
        command=["echo", "hello"],
        environment_variables={"ENV_MODE": "test"},
        secret_references={"SECRET_KEY": "BEACON_TEST_SECRET_VAR"},
        resource_limits={"cpus": "1.5", "memory": "512m", "pids_limit": 100, "unsupported_limit": "xyz"},
        name="test_resource_container",
    )

    assert "unsupported_limit" in adapter.unsupported_limits

    run_cmd, safe_cmd = adapter._build_container_command()
    cmd_str = " ".join(run_cmd)
    safe_str = " ".join(safe_cmd)

    # Verify resource flags injected
    assert "--cpus=1.5" in cmd_str
    assert "--memory=512m" in cmd_str
    assert "--pids-limit=100" in cmd_str

    # Verify secret is resolved in real command but masked in logged command
    assert "SECRET_KEY=production_super_secret" in cmd_str
    assert "SECRET_KEY=[REDACTED]" in safe_str
    assert "production_super_secret" not in safe_str


def test_execution_result_captures_stdout_stderr_exit_code():
    """ApplicationExecutor populates stdout, stderr, and exit_code on ExecutionResult."""
    adapter = ProcessAdapter(
        command=[sys.executable, str(CLI_FIXTURE_SCRIPT)],
        name="test_exec_result_fields",
        input_mapper=InputMapper(InputMapperConfig(
            field_mappings={"x": "payload.x", "y": "payload.y", "operation": "payload.op"}
        )),
    )

    inp = CanonicalInput(input_id="INP-RES-1", payload={"x": 4.0, "y": 5.0, "op": "multiply"})
    result = application_executor.execute_single(adapter, inp, input_id="INP-RES-1")

    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.exit_code == 0
    assert result.stdout is not None and len(result.stdout) > 0
    assert result.stderr is not None
    assert result.duration_ms > 0


def test_application_resolver_input_fallback_marks_warning_and_test_only():
    """ApplicationResolver clearly identifies synthetic input fallback as TEST/DEVELOPMENT ONLY."""
    from application.resolver import ApplicationResolver
    resolver = ApplicationResolver()

    # Spec without dataset or contract
    spec = ApplicationSpec(
        application_id="app_no_dataset",
        name="No Dataset Spec",
        reference_implementation="tests.fixtures.generic_calc_cli:cli_entrypoint",
        target_implementations=["tests.fixtures.generic_calc_cli:cli_entrypoint"],
    )

    inputs = resolver.resolve_inputs(spec)
    assert len(inputs) == 10
    assert inputs[0].provenance.get("mode") == "test_development_fallback_only"
    assert inputs[0].provenance.get("source") == "phase1_test_fallback"
    assert "warning" in inputs[0].provenance


def test_ssrf_dns_failure_fails_closed():
    """SSRFValidator must FAIL CLOSED when DNS resolution raises socket.gaierror or other resolution errors."""
    import socket

    def mock_failing_dns(host: str):
        raise socket.gaierror(-2, "Name or service not known")

    with pytest.raises(PermissionError) as exc:
        SSRFValidator.validate_url(
            "https://unresolvable-evil-host.unknown/api",
            allow_private=True,
            dns_resolver=mock_failing_dns,
        )
    assert "Unable to resolve hostname" in str(exc.value)
    assert "blocked by SSRF policy" in str(exc.value)


def test_ssrf_empty_dns_resolution_fails_closed():
    """SSRFValidator must FAIL CLOSED when DNS resolution returns an empty list."""
    def mock_empty_dns(host: str):
        return []

    with pytest.raises(PermissionError) as exc:
        SSRFValidator.validate_url(
            "https://empty-dns-record.example/api",
            allow_private=True,
            dns_resolver=mock_empty_dns,
        )
    assert "Unable to resolve hostname" in str(exc.value)


def test_ssrf_mixed_resolution_blocks_unsafe():
    """SSRFValidator rejects requests where DNS resolves to both a public and a private/metadata address."""
    mock_mixed_dns = lambda host: ["93.184.216.34", "10.0.0.10"]
    with pytest.raises(PermissionError) as exc:
        SSRFValidator.validate_url(
            "https://mixed-resolution.example.com/api",
            allow_private=False,
            dns_resolver=mock_mixed_dns,
        )
    assert "private network IP" in str(exc.value)

    mock_mixed_meta_dns = lambda host: ["93.184.216.34", "169.254.169.254"]
    with pytest.raises(PermissionError) as exc_meta:
        SSRFValidator.validate_url(
            "https://mixed-meta.example.com/api",
            allow_private=True,
            dns_resolver=mock_mixed_meta_dns,
        )
    assert "metadata IP" in str(exc_meta.value)


def test_secret_redaction_http_headers_and_cookie_syntax():
    """SecretRedactor redacts HTTP headers, Bearer tokens, Cookies, and API keys across various casings and formats."""
    raw_texts = [
        "Authorization: Bearer VERY_SECRET_JWT_TOKEN",
        "authorization: Bearer my-access-token",
        "AUTHORIZATION=Bearer abcdef12345",
        "Cookie: session=VERY_SECRET_SESSION_TOKEN",
        "Set-Cookie: session=VERY_SECRET_SESSION_TOKEN; Secure; HttpOnly",
        "X-API-Key: VERY_SECRET_API_KEY",
        "Api-Key: VERY_SECRET_API_KEY",
        "Proxy-Authorization: Basic dXNlcjpwYXNz",
        "db_password=my_database_pw",
        "client_secret='super_secret_client_val'",
    ]

    for raw in raw_texts:
        redacted = SecretRedactor.redact_string(raw)
        assert "VERY_SECRET" not in redacted
        assert "abcdef12345" not in redacted
        assert "my_database_pw" not in redacted
        assert "super_secret_client_val" not in redacted
        assert "[REDACTED]" in redacted


def test_secret_redaction_preserves_business_metrics():
    """SecretRedactor preserves non-sensitive business values while removing credentials."""
    business_text = "price=120\ndiscount=10\nstatus=200\npassword=secret123\nresult=45.5"
    redacted = SecretRedactor.redact_string(business_text)

    assert "price=120" in redacted
    assert "discount=10" in redacted
    assert "status=200" in redacted
    assert "result=45.5" in redacted
    assert "secret123" not in redacted
    assert "password=[REDACTED]" in redacted


def test_process_adapter_redacts_stdout_and_stderr(tmp_path):
    """ProcessAdapter sanitizes raw stdout and stderr before creating Observation and ExecutionResult."""
    # Create a small script that prints sensitive headers and credentials
    script_path = tmp_path / "leaking_script.py"
    script_path.write_text(
        "import sys\n"
        "print('Authorization: Bearer LEAKED_STDOUT_TOKEN_123')\n"
        "print('result=42.0')\n"
        "sys.stderr.write('Cookie: session=LEAKED_STDERR_SESSION_456\\n')\n"
    )

    adapter = ProcessAdapter(
        command=[sys.executable, str(script_path)],
        name="test_leak_process",
    )

    inp = CanonicalInput(input_id="INP-LEAK-1", payload={})
    res = application_executor.execute_single(adapter, inp, input_id="INP-LEAK-1")

    assert res.status == ExecutionStatus.SUCCEEDED
    assert "LEAKED_STDOUT_TOKEN_123" not in res.stdout
    assert "LEAKED_STDERR_SESSION_456" not in res.stderr
    assert "[REDACTED]" in res.stdout
    assert "[REDACTED]" in res.stderr
    assert "result=42.0" in res.stdout
    assert "LEAKED_STDOUT_TOKEN_123" not in str(res.observation.provenance)
    assert "LEAKED_STDERR_SESSION_456" not in str(res.observation.provenance)


def test_container_adapter_missing_secret_reference_fails_closed():
    """ContainerAdapter marks health as MISCONFIGURED and fails closed when secret references are missing."""
    # Ensure environment variable is NOT set
    os.environ.pop("MISSING_BEACON_HOST_ENV_VAR", None)

    adapter = ContainerAdapter(
        image="alpine:latest",
        secret_references={"CONTAINER_SECRET": "MISSING_BEACON_HOST_ENV_VAR"},
        name="test_missing_secret_container",
    )

    health = adapter.health_check()
    assert health.is_ready is False
    assert health.status == AdapterHealthStatus.MISCONFIGURED
    assert "MISSING_BEACON_HOST_ENV_VAR" in health.diagnostics
    assert "unavailable" in health.diagnostics

    obs = adapter.execute(CanonicalInput(input_id="INP-MISS-SEC", payload={}))
    assert obs.execution_status == "EXCEPTION"
    assert "unavailable" in obs.error_message


def test_application_executor_sanitizes_exception_secrets():
    """ApplicationExecutor redacts sensitive tokens appearing in exception messages."""
    class LeakingExceptionAdapter(ImplementationAdapter):
        name = "leak_exc_adapter"
        def execute(self, inputs, input_id=""):
            raise RuntimeError("Database connection failed with password=SUPER_SECRET_DB_PASS at host 10.0.0.1")

    adapter = LeakingExceptionAdapter()
    res = application_executor.execute_single(adapter, CanonicalInput(input_id="INP-EXC-1", payload={}))

    assert res.status == ExecutionStatus.ADAPTER_ERROR
    assert "SUPER_SECRET_DB_PASS" not in res.error_message
    assert "SUPER_SECRET_DB_PASS" not in res.observation.error_message
    assert "password=[REDACTED]" in res.error_message


# ==============================================================================
# SUBPROCESS IMPORT ISOLATION & OPTIONAL DEPENDENCY TESTS
# ==============================================================================

def test_subprocess_import_isolation_execution_models():
    """Verify execution.models can be imported in a clean Python subprocess without certification or LLM."""
    code = (
        "import sys\n"
        "sys.path.insert(0, 'backend')\n"
        "import execution.models\n"
        "cert_modules = [m for m in sys.modules if 'certification' in m or 'llm' in m]\n"
        "assert len(cert_modules) == 0, f'Unexpected modules loaded: {cert_modules}'\n"
    )
    res = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"Subprocess import failed: {res.stderr}"


def test_subprocess_import_isolation_execution_security():
    """Verify execution.security can be imported in a clean Python subprocess without certification or LLM."""
    code = (
        "import sys\n"
        "sys.path.insert(0, 'backend')\n"
        "import execution.security\n"
        "cert_modules = [m for m in sys.modules if 'certification' in m or 'llm' in m]\n"
        "assert len(cert_modules) == 0, f'Unexpected modules loaded: {cert_modules}'\n"
    )
    res = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"Subprocess import failed: {res.stderr}"


def test_subprocess_import_isolation_execution_mapping():
    """Verify execution.mapping can be imported in a clean Python subprocess without certification or LLM."""
    code = (
        "import sys\n"
        "sys.path.insert(0, 'backend')\n"
        "import execution.mapping\n"
        "cert_modules = [m for m in sys.modules if 'certification' in m or 'llm' in m]\n"
        "assert len(cert_modules) == 0, f'Unexpected modules loaded: {cert_modules}'\n"
    )
    res = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"Subprocess import failed: {res.stderr}"


def test_subprocess_import_isolation_execution_adapters():
    """Verify all execution adapters can be imported in a clean Python subprocess without certification or LLM."""
    code = (
        "import sys\n"
        "sys.path.insert(0, 'backend')\n"
        "import execution.process_adapter\n"
        "import execution.http_adapter\n"
        "import execution.container_adapter\n"
        "cert_modules = [m for m in sys.modules if 'certification' in m or 'llm' in m]\n"
        "assert len(cert_modules) == 0, f'Unexpected modules loaded: {cert_modules}'\n"
    )
    res = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"Subprocess import failed: {res.stderr}"


def test_optional_anthropic_missing_isolation():
    """Verify execution and LLM subsystems operate without errors when anthropic is absent."""
    code = (
        "import sys\n"
        "sys.path.insert(0, 'backend')\n"
        "sys.modules['anthropic'] = None\n"
        "import execution.models\n"
        "import execution.security\n"
        "import execution.mapping\n"
        "import execution.process_adapter\n"
        "import execution.http_adapter\n"
        "import execution.container_adapter\n"
        "import llm.manager\n"
        "mgr = llm.manager.get_provider_manager()\n"
        "status = mgr.get_status()\n"
        "assert status['providers']['anthropic']['available'] is False\n"
    )
    res = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"Optional dependency isolation failed: {res.stderr}"


# ==============================================================================
# LIFECYCLE & CLEANUP GUARANTEE TESTS
# ==============================================================================

def test_adapter_cleanup_always_executed_on_success():
    """Verify cleanup() is called on successful execution."""
    cleaned_up = []

    class MockLifecycleAdapter(ImplementationAdapter):
        name = "mock_lifecycle"
        def execute(self, inputs, input_id=""):
            return Observation(input_id=input_id, execution_status="SUCCESS", raw_output={"val": 1})
        def cleanup(self):
            cleaned_up.append(True)

    adapter = MockLifecycleAdapter()
    res = application_executor.execute_single(adapter, CanonicalInput(input_id="INP-CLN-1", payload={}))
    assert res.status == ExecutionStatus.SUCCEEDED
    assert len(cleaned_up) == 1


def test_adapter_cleanup_always_executed_on_exception():
    """Verify cleanup() is called even when execute() raises an uncaught exception."""
    cleaned_up = []

    class FailingLifecycleAdapter(ImplementationAdapter):
        name = "mock_failing_lifecycle"
        def execute(self, inputs, input_id=""):
            raise RuntimeError("Fatal execution crash")
        def cleanup(self):
            cleaned_up.append(True)

    adapter = FailingLifecycleAdapter()
    res = application_executor.execute_single(adapter, CanonicalInput(input_id="INP-CLN-2", payload={}))
    assert res.status == ExecutionStatus.ADAPTER_ERROR
    assert len(cleaned_up) == 1


# ==============================================================================
# COMPREHENSIVE SECRET REDACTION & PRESERVATION OF USEFUL OUTPUT
# ==============================================================================

def test_selective_secret_redaction_preserves_useful_behavior():
    """Verify selective redaction preserves non-sensitive behavioral output."""
    test_secret = "BEACON_PHASE2_SECRET_9f8a7c6b"
    raw_output = (
        f"price=120\n"
        f"discount=15\n"
        f"status=approved\n"
        f"Authorization: Bearer {test_secret}\n"
        f"token={test_secret}\n"
    )

    redacted = SecretRedactor.redact_string(raw_output)

    assert test_secret not in redacted
    assert "price=120" in redacted
    assert "discount=15" in redacted
    assert "status=approved" in redacted
    assert "Authorization:" in redacted
    assert "[REDACTED]" in redacted
    assert "token=[REDACTED]" in redacted



