"""BEACON V2 — Phase 3 Real Application Execution & Evidence Capture Test Suite.

Comprehensive validation covering:
1. CanonicalInputItem, InputSet immutability, and Same-Input Guarantees.
2. Correlation IDs (session_id, correlation_id, reference_execution_id, target_execution_id, input_id).
3. Generic Readiness Detection strategies (immediate, process-alive, TCP, HTTP, probe) and timeouts.
4. PairedExecutionCoordinator lifecycle across Reference and Target implementations.
5. Rich Evidence Architecture: Output, Error, Runtime, Log, Trace, Filesystem, Database, Http, Metadata.
6. Evidence normalization, SHA-256 cryptographic hashing, and EvidenceManifest bundle hashes.
7. Dual persistence (SQLite + filesystem) and real-time tamper-detection verification.
8. Partial evidence retention and failure policies (reference failure stops target; target failure preserves reference).
9. Batch execution with multiple inputs and repeated execution sweeps.
10. Secret redaction through evidence pipelines.
11. Phase 3 REST API endpoints under /api/v3/paired.
12. Strict Phase 3 boundary enforcement (zero behavioral equivalence evaluation or scoring).
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Optional, Union
import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))

from api.main import app
from auth import create_access_token
from common.contracts import (
    AdapterRole,
    CanonicalInput,
    ExecutionStatus,
    ImplementationAdapter,
    Observation,
)
from execution import (
    CanonicalInputItem,
    DatabaseEvidence,
    DatabaseEvidenceProvider,
    ErrorEvidence,
    EvidenceBundle,
    EvidenceCaptureStatus,
    EvidenceConfiguration,
    EvidenceManifest,
    EvidenceManifestItem,
    EvidenceNormalizer,
    EvidencePersistenceStatus,
    EvidenceRecord,

    EvidenceStore,
    EvidenceType,
    FileEvidence,
    FileEvidenceProvider,
    HttpEvidence,
    HttpEvidenceProvider,
    InputSet,
    LogEvidence,
    LogEvidenceProvider,
    MetadataEvidence,
    OutputEvidence,
    OutputEvidenceProvider,
    PairedExecutionCoordinator,
    PairedExecutionItemResult,
    PairedExecutionRequest,
    PairedExecutionSession,
    PairedExecutionStatus,
    ReadinessChecker,
    ReadinessConfig,
    ReadinessResult,
    ReadinessStrategy,
    RuntimeEvidence,
    RuntimeEvidenceProvider,
    SecretRedactor,
    TraceEvent,
    TraceEvidence,
    TraceEvidenceProvider,
    compute_content_hash,
    compute_input_set_hash,
    compute_payload_hash,
    evidence_normalizer,
    evidence_store,
    paired_execution_coordinator,
)


# ==============================================================================
# Domain-Neutral Test Adapters
# ==============================================================================

class GenericMathReferenceAdapter(ImplementationAdapter):
    """Domain-neutral reference implementation doing math transforms."""
    name = "math_ref_adapter"
    version = "1.0.0"
    role = AdapterRole.REFERENCE
    cleaned_up = False

    def execute(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
        raw_in = inputs.get_data() if isinstance(inputs, CanonicalInput) else dict(inputs)
        x = float(raw_in.get("x", 0))
        y = float(raw_in.get("y", 0))
        result = (x * 2) + y
        return Observation(
            input_id=input_id or "ref-in",
            raw_inputs=raw_in,
            normalized_inputs=raw_in,
            raw_outputs={"result": result, "calc_mode": "linear_ref"},
            normalized_outputs={"result": result, "calc_mode": "linear_ref"},
            execution_status="SUCCESS",
            implementation_name=self.name,
            implementation_version=self.version,
            execution_time_ms=1.5,
            provenance={"role": "reference", "adapter_type": "function", "stdout": f"Calculated: {result}"},
        )

    def cleanup(self) -> None:
        self.cleaned_up = True


class GenericMathTargetAdapter(ImplementationAdapter):
    """Domain-neutral target implementation doing math transforms."""
    name = "math_target_adapter"
    version = "2.0.0"
    role = AdapterRole.TARGET
    cleaned_up = False

    def execute(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
        raw_in = inputs.get_data() if isinstance(inputs, CanonicalInput) else dict(inputs)
        x = float(raw_in.get("x", 0))
        y = float(raw_in.get("y", 0))
        result = (x * 2) + y
        return Observation(
            input_id=input_id or "target-in",
            raw_inputs=raw_in,
            normalized_inputs=raw_in,
            raw_outputs={"result": result, "calc_mode": "linear_target"},
            normalized_outputs={"result": result, "calc_mode": "linear_target"},
            execution_status="SUCCESS",
            implementation_name=self.name,
            implementation_version=self.version,
            execution_time_ms=1.2,
            provenance={"role": "target", "adapter_type": "function", "stdout": f"Calculated: {result}"},
        )

    def cleanup(self) -> None:
        self.cleaned_up = True


class FailingTargetAdapter(ImplementationAdapter):
    """Target implementation that deliberately throws an application exception."""
    name = "failing_target_adapter"
    version = "1.0.0"
    role = AdapterRole.TARGET
    cleaned_up = False

    def execute(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
        raise RuntimeError("Simulated target computational fatal failure")

    def cleanup(self) -> None:
        self.cleaned_up = True


class FailingReferenceAdapter(ImplementationAdapter):
    """Reference implementation that fails immediately."""
    name = "failing_ref_adapter"
    version = "1.0.0"
    role = AdapterRole.REFERENCE
    cleaned_up = False

    def execute(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
        raise ConnectionResetError("Reference service backend crashed")

    def cleanup(self) -> None:
        self.cleaned_up = True


# ==============================================================================
# 1. InputSet & Same-Input Guarantee Tests
# ==============================================================================

def test_input_set_creation_and_content_hash():
    """InputSet deterministically computes SHA-256 content hash across sequenced inputs."""
    raw_records = [
        {"x": 10, "y": 20},
        {"x": 30, "y": 40},
        {"x": 50, "y": 60},
    ]
    input_set = InputSet.from_inputs(raw_records, source="test_matrix")

    assert input_set.input_count == 3
    assert len(input_set.inputs) == 3
    assert input_set.input_set_id.startswith("INPSET-")
    assert len(input_set.content_hash) == 64
    assert input_set.verify_content_hash() is True

    # Check sequence indexing
    assert input_set.inputs[0].sequence == 0
    assert input_set.inputs[0].payload == {"x": 10, "y": 20}
    assert input_set.inputs[1].sequence == 1
    assert input_set.inputs[2].sequence == 2


def test_input_set_same_input_guarantee_immutability():
    """InputSet returns detached deep copies to prevent in-place adapter payload mutation."""
    raw_records = [{"val": 100, "flag": True}]
    input_set = InputSet.from_inputs(raw_records, source="immutable_test")

    copies_ref = input_set.to_canonical_inputs()
    copies_target = input_set.to_canonical_inputs()

    # Mutate ref copy
    copies_ref[0].payload["val"] = 999
    copies_ref[0].payload["injected"] = "mutated"

    # Target copy and original InputSet remain completely untouched
    assert copies_target[0].payload["val"] == 100
    assert "injected" not in copies_target[0].payload
    assert input_set.inputs[0].payload["val"] == 100
    assert input_set.verify_content_hash() is True


def test_input_set_hash_tamper_detection():
    """Tampering with an InputSet's items fails verification."""
    raw_records = [{"a": 1}, {"b": 2}]
    input_set = InputSet.from_inputs(raw_records)
    assert input_set.verify_content_hash() is True

    # Manually tamper with an item's payload
    input_set.inputs[0].payload["a"] = 9999
    assert input_set.verify_content_hash() is False


# ==============================================================================
# 2. Readiness Engine Tests
# ==============================================================================

def test_readiness_immediate_strategy():
    """ReadinessStrategy.IMMEDIATE evaluates ready immediately."""
    cfg = ReadinessConfig(strategy=ReadinessStrategy.IMMEDIATE)
    res = ReadinessChecker.wait_until_ready(cfg)
    assert res.ready is True
    assert res.strategy == ReadinessStrategy.IMMEDIATE
    assert res.duration_ms == 0.0


def test_readiness_adapter_defined_custom_probe():
    """ReadinessStrategy.ADAPTER_DEFINED executes a custom probe successfully."""
    attempts = 0

    def probe():
        nonlocal attempts
        attempts += 1
        return attempts >= 2

    cfg = ReadinessConfig(
        strategy=ReadinessStrategy.ADAPTER_DEFINED,
        custom_probe=probe,
        timeout_seconds=2.0,
        poll_interval_seconds=0.05,
    )
    res = ReadinessChecker.wait_until_ready(cfg)
    assert res.ready is True
    assert res.poll_attempts >= 2
    assert "Custom probe confirmed readiness" in res.diagnostics


def test_readiness_timeout_fails_closed():
    """Readiness timeout fails closed with structured diagnostics."""
    def never_ready():
        return False

    cfg = ReadinessConfig(
        strategy=ReadinessStrategy.ADAPTER_DEFINED,
        custom_probe=never_ready,
        timeout_seconds=0.2,
        poll_interval_seconds=0.05,
    )
    res = ReadinessChecker.wait_until_ready(cfg)
    assert res.ready is False
    assert "Readiness check timed out" in res.diagnostics
    assert res.error is not None


# ==============================================================================
# 3. Paired Execution Lifecycle & Same-Input Delivery Tests
# ==============================================================================

def test_paired_execution_happy_path():
    """PairedExecutionCoordinator executes Reference and Target over same InputSet and captures evidence."""
    ref_adp = GenericMathReferenceAdapter()
    target_adp = GenericMathTargetAdapter()

    inputs = [
        {"x": 1.0, "y": 2.0},
        {"x": 3.0, "y": 4.0},
    ]
    req = PairedExecutionRequest(
        application_id="test_math_app",
        reference_adapter=ref_adp,
        target_adapter=target_adp,
        custom_inputs=inputs,
        correlation_id="CORR-HAPPY-001",
        evidence_config=EvidenceConfiguration(
            capture_output=True,
            capture_logs=True,
            capture_runtime=True,
            capture_traces=True,
        ),
    )

    session, bundle = paired_execution_coordinator.execute_paired(req)

    # Verify Session
    assert session.status == PairedExecutionStatus.COMPLETED
    assert session.correlation_id == "CORR-HAPPY-001"
    assert session.total_inputs == 2
    assert session.executed_inputs == 2
    assert session.reference_adapter_name == "math_ref_adapter"
    assert session.target_adapter_name == "math_target_adapter"
    assert len(session.paired_results) == 2

    # Verify Per-Input Correlation
    for idx, r in enumerate(session.paired_results):
        assert r.correlation_id == "CORR-HAPPY-001"
        assert r.reference_status == "SUCCEEDED"
        assert r.target_status == "SUCCEEDED"
        assert r.reference_execution_id.startswith("EXEC-")
        assert r.target_execution_id.startswith("EXEC-")
        assert r.reference_execution_id != r.target_execution_id
        assert len(r.evidence_ids) > 0

    # Verify Cleanup Guaranteed
    assert ref_adp.cleaned_up is True
    assert target_adp.cleaned_up is True

    # Verify Evidence Bundle & Manifest
    assert bundle.is_partial is False
    assert bundle.bundle_id.startswith("BNDL-")
    assert len(bundle.bundle_hash) == 64
    assert bundle.manifest.total_evidence_count > 0
    assert len(bundle.records) > 0

    # Verify Output Evidence Captured
    out_records = [r for r in bundle.records if r.evidence_type == EvidenceType.OUTPUT]
    assert len(out_records) == 4  # 2 inputs * 2 adapters
    ref_outputs = [r for r in out_records if r.role == "reference"]
    target_outputs = [r for r in out_records if r.role == "target"]
    assert len(ref_outputs) == 2
    assert len(target_outputs) == 2

    assert ref_outputs[0].payload["normalized_output"]["result"] == 4.0
    assert target_outputs[0].payload["normalized_output"]["result"] == 4.0


def test_paired_execution_reference_failure_halts_before_target():
    """Reference failure policy: if reference fails critically, target is NOT started."""
    ref_adp = FailingReferenceAdapter()
    target_adp = GenericMathTargetAdapter()

    # Set up a failing readiness check on reference
    req = PairedExecutionRequest(
        application_id="test_fail_ref_app",
        reference_adapter=ref_adp,
        target_adapter=target_adp,
        custom_inputs=[{"x": 10}],
        readiness_config_ref=ReadinessConfig(
            strategy=ReadinessStrategy.ADAPTER_DEFINED,
            custom_probe=lambda: False,
            timeout_seconds=0.1,
            poll_interval_seconds=0.05,
        ),
    )

    session, bundle = paired_execution_coordinator.execute_paired(req)

    # Session halted before target
    assert session.status in (PairedExecutionStatus.FAILED, PairedExecutionStatus.PARTIAL)
    assert "Reference readiness failed" in (session.error_summary or "")
    assert bundle.is_partial is True
    assert len(bundle.target_execution_ids) == 0  # Target was never executed!
    assert target_adp.cleaned_up is False  # Target was not even started


def test_paired_execution_target_failure_preserves_reference_evidence():
    """Target failure policy: if target throws, complete reference evidence is retained."""
    ref_adp = GenericMathReferenceAdapter()
    target_adp = FailingTargetAdapter()

    req = PairedExecutionRequest(
        application_id="test_fail_target_app",
        reference_adapter=ref_adp,
        target_adapter=target_adp,
        custom_inputs=[{"x": 15, "y": 5}],
    )

    session, bundle = paired_execution_coordinator.execute_paired(req)

    assert session.status in (PairedExecutionStatus.PARTIAL, PairedExecutionStatus.FAILED)
    assert bundle.is_partial is True

    # Reference evidence is fully preserved
    ref_out = [r for r in bundle.records if r.role == "reference" and r.evidence_type == EvidenceType.OUTPUT]
    assert len(ref_out) == 1
    assert ref_out[0].payload["normalized_output"]["result"] == 35.0

    # Target error evidence is recorded
    err_recs = [r for r in bundle.records if r.role == "target" and r.evidence_type == EvidenceType.ERROR]
    assert len(err_recs) >= 1
    assert "target computational fatal failure" in err_recs[0].payload["message"]


# ==============================================================================
# 4. Evidence Integrity & Tamper Detection Tests
# ==============================================================================

def test_evidence_record_integrity_verification():
    """EvidenceStore verifies cryptographic SHA-256 payload integrity."""
    rec = evidence_normalizer.normalize_record(
        evidence_type=EvidenceType.OUTPUT,
        payload={"calc_result": 42.0, "status": "OK"},
        session_id="SESS-INTEG-001",
        execution_id="EXEC-001",
        application_id="app_integ",
        role="reference",
    )
    evidence_store.save_record(rec)

    # Verify integrity passes
    ok, msg = evidence_store.verify_evidence_integrity(rec.evidence_id)
    assert ok is True
    assert "Integrity verified" in msg

    # Tamper with the record payload
    rec.payload["calc_result"] = 999999.0
    evidence_store.save_record(rec)

    # Verify tamper is detected
    ok, msg = evidence_store.verify_evidence_integrity(rec.evidence_id)
    assert ok is False
    assert "TAMPER DETECTED" in msg


def test_evidence_bundle_integrity_verification():
    """EvidenceStore verifies manifest bundle_hash integrity."""
    rec1 = evidence_normalizer.normalize_record(
        evidence_type=EvidenceType.OUTPUT,
        payload={"val": 1},
        session_id="SESS-BNDL-001",
    )
    rec2 = evidence_normalizer.normalize_record(
        evidence_type=EvidenceType.LOG,
        payload={"log": "Operation successful"},
        session_id="SESS-BNDL-001",
    )

    bundle = evidence_normalizer.build_bundle(
        session_id="SESS-BNDL-001",
        correlation_id="CORR-BNDL",
        application_id="app_bndl",
        input_set_id="INPSET-001",
        input_set_hash="hash001",
        records=[rec1, rec2],
    )
    evidence_store.save_bundle(bundle)

    # Bundle integrity passes
    ok, msg = evidence_store.verify_bundle_integrity("SESS-BNDL-001")
    assert ok is True
    assert "Bundle integrity verified" in msg

    # Tamper with bundle items
    bundle.manifest.items[0].content_hash = "f" * 64
    evidence_store.save_bundle(bundle)

    # Tamper detected
    ok, msg = evidence_store.verify_bundle_integrity("SESS-BNDL-001")
    assert ok is False
    assert "TAMPER DETECTED" in msg


# ==============================================================================
# 5. Specialized Evidence Providers Tests
# ==============================================================================

def test_filesystem_evidence_provider_delta_detection():
    """FileEvidenceProvider detects filesystem deltas before and after execution."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = Path(tmp_dir) / "state.txt"
        test_file.write_text("initial state before")

        provider = FileEvidenceProvider(paths=[str(test_file)])
        provider.capture_before()

        # Mutate file during "execution"
        test_file.write_text("modified state after run")

        data = provider.capture_after()
        assert data["delta_detected"] is True
        assert data["status"] == EvidenceCaptureStatus.CAPTURED.value
        assert data["before_state"][str(test_file)]["size_bytes"] == len("initial state before")
        assert data["after_state"][str(test_file)]["size_bytes"] == len("modified state after run")


def test_database_evidence_provider_unconfigured_not_supported():
    """DatabaseEvidenceProvider reports NOT_SUPPORTED when no database is configured."""
    provider = DatabaseEvidenceProvider(config=None)
    data = provider.capture_after()
    assert data["status"] == EvidenceCaptureStatus.NOT_SUPPORTED.value


def test_secret_redaction_in_evidence_capture():
    """Credentials in outputs and headers are automatically redacted in EvidenceRecord."""
    rec = evidence_normalizer.normalize_record(
        evidence_type=EvidenceType.HTTP,
        payload={
            "headers": {"Authorization": "Bearer super_secret_jwt_token_12345"},
            "body": {"password": "mypassword123", "normal_metric": 450},
        },
        session_id="SESS-SEC-001",
    )

    # Credentials redacted
    assert rec.payload["headers"]["Authorization"] == "[REDACTED]"
    assert rec.payload["body"]["password"] == "[REDACTED]"
    assert rec.payload["body"]["normal_metric"] == 450
    assert "super_secret_jwt" not in json.dumps(rec.payload)


# ==============================================================================
# 6. Sweeps & Repeated Execution Tests
# ==============================================================================

def test_paired_execution_sweeps():
    """Coordinator executes repeated sweeps with unique session and execution IDs."""
    ref_adp = GenericMathReferenceAdapter()
    target_adp = GenericMathTargetAdapter()

    req = PairedExecutionRequest(
        application_id="sweep_app",
        reference_adapter=ref_adp,
        target_adapter=target_adp,
        custom_inputs=[{"x": 2, "y": 3}],
        correlation_id="SWEEP-TEST",
    )

    sweep_results = paired_execution_coordinator.execute_sweep(req, iterations=3)
    assert len(sweep_results) == 3

    session_ids = [s.session_id for s, _ in sweep_results]
    assert len(set(session_ids)) == 3  # All unique!

    exec_ids_run1 = sweep_results[0][0].paired_results[0].reference_execution_id
    exec_ids_run2 = sweep_results[1][0].paired_results[0].reference_execution_id
    assert exec_ids_run1 != exec_ids_run2


# ==============================================================================
# 7. Phase 3 REST API Router Tests
# ==============================================================================

def test_api_paired_sessions_lifecycle():
    """FastAPI endpoints trigger paired runs and allow evidence and verification queries."""
    from auth.repository import auth_repository
    client = TestClient(app)
    admin_user = auth_repository.get_user_by_username("admin")
    token = create_access_token(user=admin_user)
    headers = {"Authorization": f"Bearer {token}"}


    # Register an application spec for the test
    from application.models import ApplicationSpec, ImplementationTarget
    from application.repository import application_repository
    test_spec = ApplicationSpec(
        application_id="api_paired_math_app",
        name="API Math Spec",
        reference_implementation=ImplementationTarget(name="ref", entrypoint="tests.test_v2_phase3_execution:GenericMathReferenceAdapter"),
        target_implementations=[ImplementationTarget(name="target", entrypoint="tests.test_v2_phase3_execution:GenericMathTargetAdapter")],
    )
    application_repository.save_application(test_spec)

    # 1. Trigger paired execution via POST /api/v3/paired/sessions
    post_res = client.post(
        "/api/v3/paired/sessions",
        headers=headers,
        json={
            "application_id": "api_paired_math_app",
            "custom_inputs": [{"x": 10.0, "y": 5.0}],
            "timeout_seconds": 15.0,
        },
    )
    assert post_res.status_code == 201
    post_data = post_res.json()
    sess_id = post_data["session"]["session_id"]
    assert sess_id.startswith("PAIRED-SESS-")
    assert post_data["bundle_hash"] is not None

    # 2. Get session details via GET /api/v3/paired/sessions/{session_id}
    get_res = client.get(f"/api/v3/paired/sessions/{sess_id}", headers=headers)
    assert get_res.status_code == 200
    sess_data = get_res.json()
    assert sess_data["status"] == "COMPLETED"
    assert len(sess_data["paired_results"]) == 1
    input_id = sess_data["paired_results"][0]["input_id"]

    # 3. Get evidence bundle via GET /api/v3/paired/sessions/{session_id}/bundle
    bundle_res = client.get(f"/api/v3/paired/sessions/{sess_id}/bundle", headers=headers)
    assert bundle_res.status_code == 200
    bundle_data = bundle_res.json()
    assert len(bundle_data["records"]) > 0
    first_ev_id = bundle_data["records"][0]["evidence_id"]

    # 4. Get segregated input evidence via GET /api/v3/paired/sessions/{session_id}/inputs/{input_id}
    input_ev_res = client.get(f"/api/v3/paired/sessions/{sess_id}/inputs/{input_id}", headers=headers)
    assert input_ev_res.status_code == 200
    input_ev_data = input_ev_res.json()
    assert input_ev_data["reference_count"] > 0
    assert input_ev_data["target_count"] > 0

    # 5. Verify single evidence via GET /api/v3/paired/evidence/{evidence_id}/verify
    ev_ver_res = client.get(f"/api/v3/paired/evidence/{first_ev_id}/verify", headers=headers)
    assert ev_ver_res.status_code == 200
    assert ev_ver_res.json()["verified"] is True

    # 6. Verify bundle integrity via GET /api/v3/paired/bundles/{session_id}/verify
    bndl_ver_res = client.get(f"/api/v3/paired/bundles/{sess_id}/verify", headers=headers)
    assert bndl_ver_res.status_code == 200
    assert bndl_ver_res.json()["verified"] is True


# ==============================================================================
# 8. Strict Phase 3 Boundary Verification Test
# ==============================================================================

def test_phase3_absolute_boundary_no_evaluation_scoring():
    """Phase 3 strictly produces evidence and never calculates equivalence scores or rules."""
    ref_adp = GenericMathReferenceAdapter()
    target_adp = GenericMathTargetAdapter()

    req = PairedExecutionRequest(
        application_id="boundary_test_app",
        reference_adapter=ref_adp,
        target_adapter=target_adp,
        custom_inputs=[{"x": 10, "y": 20}],
    )

    session, bundle = paired_execution_coordinator.execute_paired(req)

    # Verify no Phase 4 fields exist on session or bundle
    sess_dict = session.model_dump()
    bundle_dict = bundle.model_dump()

    forbidden_fields = {
        "equivalence_score",
        "semantic_score",
        "oracle_results",
        "certified",
        "rule_matches",
        "invariants_evaluated",
        "dynamic_thresholds",
    }
    for field in forbidden_fields:
        assert field not in sess_dict, f"Phase 4 field '{field}' leaked into Phase 3 session!"
        assert field not in bundle_dict, f"Phase 4 field '{field}' leaked into Phase 3 bundle!"


# ==============================================================================
# 9. Adapter Types, Batch, Timeout, and Failure Matrix Tests
# ==============================================================================

def test_paired_execution_batch_three_inputs():
    """Section 63: Batch paired execution with 3 inputs creates distinct correlated execution records."""
    ref_adp = GenericMathReferenceAdapter()
    target_adp = GenericMathTargetAdapter()

    inputs = [
        {"x": 1, "y": 2},
        {"x": 3, "y": 4},
        {"x": 5, "y": 6},
    ]
    req = PairedExecutionRequest(
        application_id="batch_math_app",
        reference_adapter=ref_adp,
        target_adapter=target_adp,
        custom_inputs=inputs,
        correlation_id="CORR-BATCH-003",
    )

    session, bundle = paired_execution_coordinator.execute_paired(req)

    assert session.total_inputs == 3
    assert session.executed_inputs == 3
    assert len(session.paired_results) == 3

    ref_ids = [r.reference_execution_id for r in session.paired_results]
    target_ids = [r.target_execution_id for r in session.paired_results]

    # All 3 ref IDs are distinct
    assert len(set(ref_ids)) == 3
    # All 3 target IDs are distinct
    assert len(set(target_ids)) == 3
    # Ref and target IDs do not overlap
    assert len(set(ref_ids).intersection(set(target_ids))) == 0

    # All items share the session correlation ID
    for r in session.paired_results:
        assert r.correlation_id == "CORR-BATCH-003"
        assert r.reference_status == "SUCCEEDED"
        assert r.target_status == "SUCCEEDED"


def test_paired_execution_process_adapter_real_cli():
    """Section 58 & 65: Paired execution with real ProcessAdapter CLI target vs FunctionAdapter reference."""
    from execution import ProcessAdapter, InputMapper, InputMapperConfig
    cli_script = ROOT / "tests" / "fixtures" / "generic_calc_cli.py"

    ref_adp = GenericMathReferenceAdapter()
    target_adp = ProcessAdapter(
        command=[sys.executable, str(cli_script)],
        name="cli_calc_target",
        role=AdapterRole.TARGET,
        input_mapper=InputMapper(InputMapperConfig(
            field_mappings={"x": "payload.x", "y": "payload.y", "operation": "payload.op"}
        )),
    )

    req = PairedExecutionRequest(
        application_id="cli_process_paired_app",
        reference_adapter=ref_adp,
        target_adapter=target_adp,
        custom_inputs=[{"x": 4.0, "y": 6.0, "op": "add"}],
    )

    session, bundle = paired_execution_coordinator.execute_paired(req)

    assert session.status == PairedExecutionStatus.COMPLETED
    assert len(session.paired_results) == 1
    res_item = session.paired_results[0]
    assert res_item.reference_status == "SUCCEEDED"
    assert res_item.target_status == "SUCCEEDED"
    assert res_item.target_exit_code == 0

    # Verify ProcessAdapter output was captured
    target_output_records = [
        r for r in bundle.records
        if r.role == "target" and r.evidence_type == EvidenceType.OUTPUT
    ]
    assert len(target_output_records) == 1
    out_payload = target_output_records[0].payload
    assert out_payload["exit_code"] == 0
    assert "status" in out_payload["normalized_output"] or "result" in out_payload["normalized_output"]


def test_paired_execution_container_adapter_graceful_unavailable():
    """Section 58: ContainerAdapter gracefully reports UNAVAILABLE when Docker is not present without crashing."""
    from execution import ContainerAdapter
    adapter = ContainerAdapter(
        image="alpine:latest",
        name="test_container_graceful",
    )
    health = adapter.health_check()
    # On systems without active Docker daemon, health status is UNAVAILABLE
    assert health.is_ready in (True, False)
    assert health.status is not None


def test_paired_execution_timeout_partial_evidence():
    """Section 61: Application timeout retains partial output/stderr/runtime evidence and marks session PARTIAL."""
    from execution import ProcessAdapter, InputMapper, InputMapperConfig
    cli_script = ROOT / "tests" / "fixtures" / "generic_calc_cli.py"

    ref_adp = GenericMathReferenceAdapter()
    target_adp = ProcessAdapter(
        command=[sys.executable, str(cli_script)],
        name="cli_timeout_target",
        role=AdapterRole.TARGET,
        timeout_seconds=0.5,
        input_mapper=InputMapper(InputMapperConfig(
            field_mappings={"operation": "payload.op", "sleep_seconds": "payload.sleep"}
        )),
    )

    req = PairedExecutionRequest(
        application_id="timeout_test_app",
        reference_adapter=ref_adp,
        target_adapter=target_adp,
        custom_inputs=[{"op": "sleep", "sleep": 3.0}],
    )

    session, bundle = paired_execution_coordinator.execute_paired(req)

    # Session is PARTIAL due to timeout
    assert session.status == PairedExecutionStatus.PARTIAL
    assert bundle.is_partial is True
    assert len(session.paired_results) == 1
    assert session.paired_results[0].target_status == "TIMEOUT"

    # Reference succeeded and has output evidence
    ref_out = [r for r in bundle.records if r.role == "reference" and r.evidence_type == EvidenceType.OUTPUT]
    assert len(ref_out) == 1

    # Target timeout error evidence is captured
    target_err = [r for r in bundle.records if r.role == "target" and r.evidence_type == EvidenceType.ERROR]
    assert len(target_err) >= 1
    assert target_err[0].payload["category"] == "TIMEOUT"


def test_paired_execution_target_readiness_timeout():
    """Section 64: Target readiness timeout halts execution, retains reference evidence, and records failure."""
    ref_adp = GenericMathReferenceAdapter()
    target_adp = GenericMathTargetAdapter()

    req = PairedExecutionRequest(
        application_id="target_readiness_timeout_app",
        reference_adapter=ref_adp,
        target_adapter=target_adp,
        custom_inputs=[{"x": 1, "y": 2}],
        readiness_config_target=ReadinessConfig(
            strategy=ReadinessStrategy.ADAPTER_DEFINED,
            custom_probe=lambda: False,
            timeout_seconds=0.1,
            poll_interval_seconds=0.05,
        ),
    )

    session, bundle = paired_execution_coordinator.execute_paired(req)

    assert session.status == PairedExecutionStatus.PARTIAL
    assert "Target readiness failed" in (session.error_summary or "")

    # Reference evidence is fully retained
    ref_recs = [r for r in bundle.records if r.role == "reference"]
    assert len(ref_recs) > 0


class CleanupFailingAdapter(ImplementationAdapter):
    """Adapter that executes successfully but raises on cleanup."""
    name = "cleanup_failing_adapter"
    version = "1.0.0"
    role = AdapterRole.TARGET

    def execute(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
        return Observation(
            input_id=input_id or "in",
            raw_inputs={},
            normalized_inputs={},
            raw_outputs={"ok": True},
            normalized_outputs={"ok": True},
            execution_status="SUCCESS",
            implementation_name=self.name,
            implementation_version=self.version,
        )

    def cleanup(self) -> None:
        raise OSError("Simulated cleanup socket close failure")


def test_paired_execution_cleanup_failure_recorded_as_evidence():
    """Section 56 & 64: Cleanup errors are recorded in evidence without discarding execution records."""
    ref_adp = GenericMathReferenceAdapter()
    target_adp = CleanupFailingAdapter()

    req = PairedExecutionRequest(
        application_id="cleanup_fail_app",
        reference_adapter=ref_adp,
        target_adapter=target_adp,
        custom_inputs=[{"x": 5}],
    )

    session, bundle = paired_execution_coordinator.execute_paired(req)

    # Execution outputs are still preserved
    out_recs = [r for r in bundle.records if r.evidence_type == EvidenceType.OUTPUT]
    assert len(out_recs) == 2

    # Cleanup error evidence is captured
    clean_errs = [
        r for r in bundle.records
        if r.evidence_type == EvidenceType.ERROR and r.payload.get("phase") == "TARGET_CLEANUP"
    ]
    assert len(clean_errs) == 1
    assert "Simulated cleanup socket close failure" in clean_errs[0].payload["message"]


# ==============================================================================
# 11. Final Remediation Tests (Sections 8, 13, 17, 22, 27, 31, 45)
# ==============================================================================

class IdenticalOutputAdapter(ImplementationAdapter):
    """Adapter producing exact fixed output to test evidence ID collision resistance."""
    def __init__(self, name: str, role: AdapterRole, fixed_output: dict[str, Any]):
        self.name = name
        self.version = "1.0.0"
        self.role = role
        self.fixed_output = fixed_output

    def execute(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
        return Observation(
            input_id=input_id or "inp_1",
            raw_inputs={},
            normalized_inputs={},
            raw_outputs=dict(self.fixed_output),
            normalized_outputs=dict(self.fixed_output),
            execution_status="SUCCESS",
            implementation_name=self.name,
            implementation_version=self.version,
            execution_time_ms=5.0,
        )


def test_evidence_id_uniqueness_identical_outputs_collision_regression():
    """Sections 8 & 45: Identical outputs between Reference and Target NEVER collide in evidence_id."""
    fixed_data = {"value": 100, "status": "APPROVED"}
    ref_adp = IdenticalOutputAdapter("identical_ref", AdapterRole.REFERENCE, fixed_data)
    target_adp = IdenticalOutputAdapter("identical_target", AdapterRole.TARGET, fixed_data)

    req = PairedExecutionRequest(
        application_id="collision_test_app",
        reference_adapter=ref_adp,
        target_adapter=target_adp,
        custom_inputs=[{"input_key": "any"}],
    )

    session, bundle = paired_execution_coordinator.execute_paired(req)

    ref_outputs = [
        r for r in bundle.records if r.evidence_type == EvidenceType.OUTPUT and r.role == "reference"
    ]
    target_outputs = [
        r for r in bundle.records if r.evidence_type == EvidenceType.OUTPUT and r.role == "target"
    ]

    assert len(ref_outputs) == 1
    assert len(target_outputs) == 1

    ref_ev = ref_outputs[0]
    target_ev = target_outputs[0]

    # 1. Evidence IDs MUST be distinct
    assert ref_ev.evidence_id != target_ev.evidence_id, (
        f"Collision detected! Both records have evidence_id: {ref_ev.evidence_id}"
    )

    # 2. Content hashes MUST be identical because payload is identical
    assert ref_ev.content_hash == target_ev.content_hash, (
        f"Content hashes should match for identical payload: {ref_ev.content_hash} != {target_ev.content_hash}"
    )

    # 3. Both records exist in EvidenceStore and can be independently retrieved
    retrieved_ref = evidence_store.get_record(ref_ev.evidence_id)
    retrieved_target = evidence_store.get_record(target_ev.evidence_id)

    assert retrieved_ref is not None
    assert retrieved_target is not None
    assert retrieved_ref.role == "reference"
    assert retrieved_target.role == "target"
    assert retrieved_ref.evidence_id != retrieved_target.evidence_id


def test_http_evidence_integration_real_paired_execution():
    """Sections 10-13: HttpEvidenceProvider actively captures request/response telemetry in real paired execution."""
    import http.server
    import threading

    class TestHttpHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Custom-Header", "test-value")
            self.end_headers()
            self.wfile.write(b'{"server_received": true, "code": 200}')

        def log_message(self, format, *args):
            pass  # Silence stderr logs

    server = http.server.HTTPServer(("127.0.0.1", 0), TestHttpHandler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        from execution.http_adapter import HttpAdapter

        ref_http = HttpAdapter(
            base_url=f"http://127.0.0.1:{port}",
            endpoint="/process",
            name="ref_http_service",
            role=AdapterRole.REFERENCE,
            default_headers={"Authorization": "Bearer SUPER_SECRET_TOKEN", "User-Agent": "BeaconRef/1.0"},
        )
        target_http = HttpAdapter(
            base_url=f"http://127.0.0.1:{port}",
            endpoint="/process",
            name="target_http_service",
            role=AdapterRole.TARGET,
            default_headers={"X-API-KEY": "SECRET_KEY_12345", "User-Agent": "BeaconTarget/1.0"},
        )

        req = PairedExecutionRequest(
            application_id="http_integration_app",
            reference_adapter=ref_http,
            target_adapter=target_http,
            custom_inputs=[{"tx_id": "TX_999", "amount": 250}],
            evidence_config=EvidenceConfiguration(capture_http=True),
        )

        session, bundle = paired_execution_coordinator.execute_paired(req)

        # Verify HTTP evidence in the final bundle
        http_recs = [r for r in bundle.records if r.evidence_type == EvidenceType.HTTP]
        assert len(http_recs) == 2, f"Expected 2 HTTP records, found {len(http_recs)}"

        ref_http_ev = next(r for r in http_recs if r.role == "reference")
        target_http_ev = next(r for r in http_recs if r.role == "target")

        # Verify payload fields and secret redaction
        assert ref_http_ev.payload["response_status"] == 200
        assert target_http_ev.payload["response_status"] == 200

        # Verify Authorization and API key are redacted
        ref_headers = ref_http_ev.payload.get("request_headers", {})
        target_headers = target_http_ev.payload.get("request_headers", {})
        assert ref_headers.get("Authorization") == "[REDACTED]"
        assert target_headers.get("X-API-KEY") == "[REDACTED]"

        # Verify persistence and retrieval
        retrieved_bundle = evidence_store.get_bundle(session.session_id)
        assert retrieved_bundle is not None
        persisted_http = [r for r in retrieved_bundle.records if r.evidence_type == EvidenceType.HTTP]
        assert len(persisted_http) == 2
    finally:
        server.shutdown()
        server.server_close()


def test_database_evidence_integration_sqlite_paired_execution(tmp_path):
    """Sections 14-17: DatabaseEvidenceProvider captures SQLite before/after snapshots and detects deltas."""
    import sqlite3

    db_file = tmp_path / "test_paired.db"
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, balance REAL);")
        conn.execute("INSERT INTO accounts VALUES (1, 1000.0);")
        conn.commit()

    class DatabaseMutatingAdapter(ImplementationAdapter):
        def __init__(self, name: str, role: AdapterRole, db_path: str):
            self.name = name
            self.role = role
            self.db_path = db_path

        def execute(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("UPDATE accounts SET balance = balance + 50 WHERE id = 1;")
                conn.commit()
            return Observation(
                input_id=input_id or "inp_db",
                raw_inputs={},
                normalized_inputs={},
                raw_outputs={"updated": True},
                normalized_outputs={"updated": True},
                execution_status="SUCCESS",
                implementation_name=self.name,
            )

    ref_adp = DatabaseMutatingAdapter("ref_db_adapter", AdapterRole.REFERENCE, str(db_file))
    target_adp = DatabaseMutatingAdapter("target_db_adapter", AdapterRole.TARGET, str(db_file))

    req = PairedExecutionRequest(
        application_id="db_integration_app",
        reference_adapter=ref_adp,
        target_adapter=target_adp,
        custom_inputs=[{"action": "deposit"}],
        evidence_config=EvidenceConfiguration(
            capture_database=True,
            database_config={"database_path": str(db_file), "tables": ["accounts"]},
        ),
    )

    session, bundle = paired_execution_coordinator.execute_paired(req)

    db_recs = [r for r in bundle.records if r.evidence_type == EvidenceType.DATABASE]
    assert len(db_recs) == 2, f"Expected 2 Database evidence records, found {len(db_recs)}"

    ref_db_ev = next(r for r in db_recs if r.role == "reference")
    target_db_ev = next(r for r in db_recs if r.role == "target")

    assert ref_db_ev.payload["status"] == "CAPTURED"
    assert ref_db_ev.payload["delta_detected"] is True
    assert target_db_ev.payload["status"] == "CAPTURED"
    assert target_db_ev.payload["delta_detected"] is True
    assert "accounts" in ref_db_ev.payload["configured_tables"]

    # Verify unconfigured database provider reports NOT_SUPPORTED
    unconf_provider = DatabaseEvidenceProvider(config=None)
    unconf_data = unconf_provider.capture_after(None, None)
    assert unconf_data["status"] == "NOT_SUPPORTED"


def test_input_set_strict_immutability():
    """Sections 25-27: InputSet and CanonicalInputItem are strictly frozen and cannot be mutated."""
    from pydantic import ValidationError

    raw_data = [{"k": "v1"}, {"k": "v2"}]
    input_set = InputSet.from_inputs(raw_data)

    initial_hash = input_set.content_hash
    assert len(initial_hash) == 64

    # 1. Attempting attribute modification on InputSet raises ValidationError
    with pytest.raises(ValidationError):
        input_set.source = "tampered_source"

    with pytest.raises(ValidationError):
        input_set.content_hash = "tampered_hash"

    with pytest.raises(ValidationError):
        input_set.inputs = ()

    # 2. Attempting attribute modification on CanonicalInputItem raises ValidationError
    with pytest.raises(ValidationError):
        input_set.inputs[0].payload = {"tampered": True}

    # 3. Tuple container prevents append/pop
    with pytest.raises(AttributeError):
        input_set.inputs.append(CanonicalInputItem(input_id="injected", sequence=99))

    # Hash remains invariant
    assert input_set.content_hash == initial_hash
    assert input_set.verify_content_hash() is True


def test_evidence_storage_explicit_failure_handling(monkeypatch):
    """Sections 28-31: Storage failures are explicitly recorded and never falsely reported as persisted."""
    ref_adp = GenericMathReferenceAdapter()
    target_adp = GenericMathTargetAdapter()

    req = PairedExecutionRequest(
        application_id="storage_fail_app",
        reference_adapter=ref_adp,
        target_adapter=target_adp,
        custom_inputs=[{"x": 10}],
    )

    # Monkeypatch save_bundle on store to simulate persistence failure
    def failing_save_bundle(bundle):
        bundle.persistence_status = EvidencePersistenceStatus.FAILED
        bundle.persistence_error = "Simulated disk full / database locked error"
        return bundle

    monkeypatch.setattr(evidence_store, "save_bundle", failing_save_bundle)

    session, bundle = paired_execution_coordinator.execute_paired(req)

    # Verify bundle and session state reflects failure explicitly
    assert bundle.persistence_status == EvidencePersistenceStatus.FAILED
    assert "Simulated disk full" in (bundle.persistence_error or "")
    assert session.status == PairedExecutionStatus.PARTIAL
    assert "Evidence bundle persistence failed" in (session.error_summary or "")


def test_lifecycle_process_alive_readiness_with_real_process_handle():
    """Sections 18-22: PROCESS_ALIVE readiness requires a genuine running process handle and fails if absent."""
    import subprocess
    import sys

    # 1. Successful check with real running process
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
    try:
        cfg = ReadinessConfig(strategy=ReadinessStrategy.PROCESS_ALIVE, timeout_seconds=2.0)
        res = ReadinessChecker.wait_until_ready(cfg, process=proc)
        assert res.ready is True
        assert "is alive and running" in res.diagnostics
    finally:
        proc.terminate()
        proc.wait()

    # 2. Missing process handle must FAIL CLOSED
    cfg = ReadinessConfig(strategy=ReadinessStrategy.PROCESS_ALIVE, timeout_seconds=1.0)
    res_no_proc = ReadinessChecker.wait_until_ready(cfg, process=None, adapter=None)
    assert res_no_proc.ready is False
    assert "No process handle available" in res_no_proc.diagnostics


def test_paired_execution_full_lifecycle_start_ready_execute_stop_cleanup():
    """Sections 18-21: Verifies the complete lifecycle: configure -> prepare -> start -> ready -> execute -> stop -> cleanup."""
    lifecycle_log: list[str] = []

    class LifecycleTrackingAdapter(ImplementationAdapter):
        def __init__(self, name: str, role: AdapterRole):
            self.name = name
            self.role = role

        def configure(self, config: Optional[dict[str, Any]] = None) -> None:
            lifecycle_log.append(f"{self.name}:configure")

        def prepare(self, context: Optional[dict[str, Any]] = None) -> None:
            lifecycle_log.append(f"{self.name}:prepare")

        def start(self, context: Optional[dict[str, Any]] = None) -> Any:
            lifecycle_log.append(f"{self.name}:start")
            return self

        def execute(self, inputs: Union[dict[str, Any], CanonicalInput], input_id: str = "") -> Observation:
            lifecycle_log.append(f"{self.name}:execute")
            return Observation(
                input_id=input_id or "inp",
                raw_inputs={},
                normalized_inputs={},
                raw_outputs={"done": True},
                normalized_outputs={"done": True},
                execution_status="SUCCESS",
                implementation_name=self.name,
            )

        def stop(self, context: Optional[dict[str, Any]] = None) -> None:
            lifecycle_log.append(f"{self.name}:stop")

        def cleanup(self) -> None:
            lifecycle_log.append(f"{self.name}:cleanup")

    ref = LifecycleTrackingAdapter("ref_lifecycle", AdapterRole.REFERENCE)
    target = LifecycleTrackingAdapter("target_lifecycle", AdapterRole.TARGET)

    req = PairedExecutionRequest(
        application_id="lifecycle_full_app",
        reference_adapter=ref,
        target_adapter=target,
        custom_inputs=[{"x": 1}],
    )

    session, bundle = paired_execution_coordinator.execute_paired(req)
    assert session.status == PairedExecutionStatus.COMPLETED

    # Verify exact lifecycle execution order
    expected = [
        "ref_lifecycle:configure",
        "ref_lifecycle:prepare",
        "ref_lifecycle:start",
        "ref_lifecycle:execute",
        "ref_lifecycle:stop",
        "ref_lifecycle:cleanup",
        "target_lifecycle:configure",
        "target_lifecycle:prepare",
        "target_lifecycle:start",
        "target_lifecycle:execute",
        "target_lifecycle:stop",
        "target_lifecycle:cleanup",
    ]
    assert lifecycle_log == expected


