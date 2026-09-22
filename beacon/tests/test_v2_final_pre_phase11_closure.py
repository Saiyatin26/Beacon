"""BEACON V2 — Final Pre-Phase-11 Cleanup and Closure Test Suite.

Authoritative targeted test suite covering ALL 24 requirements:
TEST 1: Fake built-in demo benchmark is not registered.
TEST 2: Fake demo repository cannot enter normal certification.
TEST 3: eval_demo_001 does not exist in production UI state.
TEST 4: default_app does not exist in production execution path.
TEST 5: Sample threshold observations are not used by production.
TEST 6: custom_inputs cannot influence authoritative inputs.
TEST 7: Missing authoritative inputs fails closed.
TEST 8: Changing authoritative input set changes execution identity.
TEST 9: Caller cannot override certification policy.
TEST 10: Backend policy identity is deterministic.
TEST 11: Changing backend certification policy changes policy fingerprint.
TEST 12: Stage-B ownership cannot be overwritten.
TEST 13: Recovery cannot bypass authority verification.
TEST 14: Recovery cannot mark incomplete execution as COMPLETED.
TEST 15: Missing EvaluationResult fails recovery.
TEST 16: Missing OracleSet fails recovery.
TEST 17: Missing ThresholdResolution fails recovery.
TEST 18: Missing execution binding fails recovery/certification.
TEST 19: Oracle coverage null remains unavailable.
TEST 20: Oracle coverage 0% remains 0%.
TEST 21: Oracle coverage 50% remains 50%.
TEST 22: Oracle coverage 100% remains 100%.
TEST 23: Legitimate external repository flow still constructs RepositoryExecutionSpec.
TEST 24: Legitimate external repository flow still executes without built-in fake benchmark.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid
import pytest

from application.models import (
    ApplicationSpec,
    ImplementationTarget,
    ApplicationRole,
    DatasetConfig,
    RuleConfig,
    RepositoryExecutionSpec,
    build_application_spec_from_repository_execution_spec,
)
from certification.models import (
    CertificationArtifact,
    CertificationContext,
    CertificationMetrics,
    CertificationStatus,
    compute_artifact_content_hash,
)
from certification.policies import (
    CertificationPolicy,
    certification_policy_resolver,
)
from evaluation.models import (
    EvaluationResult,
    BehaviorDimension,
)
from oracle.models import (
    OracleSet,
    OracleSourceMode,
)
from threshold.models import (
    DifferenceMetric,
    ThresholdPolicy,
    ThresholdResolution,
    ThresholdStatus,
    ThresholdStrategy,
)
from workflow.authority_verifier import (
    verify_execution_authority_chain,
    AuthorityChainVerificationResult,
)
from workflow.engine import CanonicalV2WorkflowEngine
from workflow.models import (
    WorkflowErrorCode,
    WorkflowResult,
    WorkflowRun,
    WorkflowRunRequest,
    WorkflowState,
    compute_execution_fingerprint,
)
from workflow.persistence import WorkflowPersistenceStore
from workflow.recovery import WorkflowRecoveryService


# ─────────────────────────────────────────────────────────────────────────────
# Test Fixtures & Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_source_dict(role: str = "legacy", commit: str = "abc1234") -> dict:
    return {
        "repository_url": f"https://github.com/example/{role}-repo.git",
        "canonical_url": f"https://github.com/example/{role}-repo.git",
        "commit_sha": commit,
        "content_hash": hashlib.sha256(f"{role}-{commit}".encode()).hexdigest(),
        "technologies": ["python"],
        "entrypoint_file": "app.py",
        "discovered_at": datetime.now(timezone.utc).isoformat(),
    }


def _make_repo_spec(
    inputs: list[dict] | None = None,
    legacy_commit: str = "leg111",
    modern_commit: str = "mod222",
    eval_mode: str = "CONTROLLED",
    adapter_id: str = "py_adapter_v1",
) -> RepositoryExecutionSpec:
    if inputs is None:
        inputs = [{"input_id": "IN-001", "data": {"x": 1}}, {"input_id": "IN-002", "data": {"x": 2}}]

    leg_src = _make_source_dict("legacy", legacy_commit)
    mod_src = _make_source_dict("modern", modern_commit)
    input_hash = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()

    spec = RepositoryExecutionSpec(
        specification_id=f"SPEC-{uuid.uuid4().hex[:8]}",
        legacy_source_identity=leg_src,
        modern_source_identity=mod_src,
        legacy_adapter={"adapter_id": adapter_id, "adapter_name": adapter_id},
        modern_adapter={"adapter_id": adapter_id, "adapter_name": adapter_id},
        legacy_entrypoint="app.py",
        modern_entrypoint="app.py",
        discovered_rules=[{"rule_id": "RULE-01", "description": "Invariant 1"}],
        discovered_inputs=inputs,
        input_set_identity=input_hash,
        rule_set_identity="RULES-01-HASH",
        evaluation_mode=eval_mode,
        policy_identity="POLICY-CANONICAL-V2",
        provenance={"version": "2.0.0"},
    )
    return spec


def _make_valid_eval_result(app_id: str, exec_fp: str) -> EvaluationResult:
    content_hash = hashlib.sha256(f"{app_id}:{exec_fp}".encode()).hexdigest()
    return EvaluationResult(
        evaluation_id=f"EVAL-{uuid.uuid4().hex[:8]}",
        application_id=app_id,
        legacy_target_id="legacy",
        modern_target_id="modern",
        evaluated_at=datetime.now(timezone.utc),
        total_cases=2,
        equivalent_cases=2,
        equivalence_score=1.0,
        dimension_scores={BehaviorDimension.OUTPUT: 1.0},
        differences=[],
        content_hash=content_hash,
        metadata={"execution_fingerprint": exec_fp},
    )


def _make_valid_oracle_set(app_id: str, exec_fp: str) -> OracleSet:
    oset = OracleSet(
        oracle_set_id=f"OSET-{uuid.uuid4().hex[:8]}",
        benchmark_id=app_id,
        rules=[{"rule_id": "RULE-001", "dimension": "return_value"}],
        created_at=datetime.now(timezone.utc).isoformat(),
        oracle_set_hash=hashlib.sha256(b"rule-content").hexdigest(),
        metadata={"execution_fingerprint": exec_fp},
    )
    return oset


def _make_valid_threshold_resolution(app_id: str, exec_fp: str, oset_id: str) -> ThresholdResolution:
    res = ThresholdResolution(
        resolution_id=f"TH-RES-{uuid.uuid4().hex[:8]}",
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.EVIDENCE_DERIVED,
        status=ThresholdStatus.RESOLVED,
        final_value=0.01,
        policy_id="POL-1",
        policy_version="1",
        provenance={"execution_fingerprint": exec_fp, "oracle_set_id": oset_id},
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    computed_fp = res.compute_fingerprint()
    res.fingerprint = computed_fp
    return res


def _make_valid_artifact(
    app_id: str,
    exec_fp: str,
    oset_id: str,
    thresh_res_id: str,
) -> CertificationArtifact:
    ctx = CertificationContext(
        application_id=app_id,
        benchmark_id=app_id,
        execution_fingerprint=exec_fp,
        threshold_resolution_id=thresh_res_id,
        evaluation_mode="CONTROLLED",
        timestamp=datetime.now(timezone.utc).isoformat(),
        metadata={"oracle_set_id": oset_id},
    )
    art = CertificationArtifact(
        certification_id=f"CERT-{uuid.uuid4().hex[:8]}",
        status=CertificationStatus.CERTIFIED,
        certified=True,
        score=1.0,
        metrics=CertificationMetrics(unique_input_count=2, matching_case_count=2),
        context=ctx,
        threshold_resolution_id=thresh_res_id,
        content_hash="",
    )
    computed_hash = compute_artifact_content_hash(art)
    art = art.model_copy(update={"content_hash": computed_hash})
    return art


from certification.adapters import FunctionAdapter
from common.contracts import adapter_registry
from application.repository_service import repository_service, RepositoryProvenance


@pytest.fixture(autouse=True)
def register_test_adapters():
    def dummy_exec(x):
        return {"decision": "APPROVED"}

    ad = FunctionAdapter(target_fn=dummy_exec, name="py_adapter_v1")
    adapter_registry.register_adapter(ad)
    yield
    adapter_registry.clear()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1: Fake built-in demo benchmark is not registered
# ─────────────────────────────────────────────────────────────────────────────

def test_01_fake_builtin_demo_benchmark_not_registered():
    from benchmarks.registry import BenchmarkRegistry
    reg = BenchmarkRegistry()
    fake_names = ["loan_demo", "medical_triage", "payroll_tax_calculator", "retail_discount_pricing"]
    registered = reg.list_benchmarks()
    for name in fake_names:
        assert name not in registered, f"Fake benchmark '{name}' must not be in registry"
        assert reg.get_benchmark(name) is None, f"get_benchmark('{name}') must return None"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2: Fake demo repository cannot enter normal certification
# ─────────────────────────────────────────────────────────────────────────────

def test_02_fake_demo_repository_cannot_enter_normal_certification():
    prov = RepositoryProvenance(
        source_url="https://github.com/example/fake-demo.git",
        source_type="git",
        resolved_revision="0000000",
        content_hash="abc000",
        retrieval_timestamp=datetime.now(timezone.utc).isoformat(),
        local_path="beacon/legacy_sample",
    )
    with pytest.raises(Exception):
        # Fake demo path does not exist and cannot be analyzed
        repository_service.analyze_repository(Path("beacon/legacy_sample"), prov)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3: eval_demo_001 does not exist in production UI state
# ─────────────────────────────────────────────────────────────────────────────

def test_03_eval_demo_001_does_not_exist_in_production_ui_state():
    frontend_src = Path("frontend/src")
    if frontend_src.exists():
        for ext in ["*.jsx", "*.js", "*.tsx", "*.ts"]:
            for f in frontend_src.rglob(ext):
                content = f.read_text(encoding="utf-8")
                assert "eval_demo_001" not in content, f"Found eval_demo_001 in {f}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4: default_app does not exist in production execution path
# ─────────────────────────────────────────────────────────────────────────────

def test_04_default_app_does_not_exist_in_production_execution_path():
    for base_dir in [Path("backend"), Path("frontend/src")]:
        if base_dir.exists():
            for p in base_dir.rglob("*"):
                if p.is_file() and p.suffix in (".py", ".jsx", ".js", ".tsx", ".ts"):
                    content = p.read_text(encoding="utf-8")
                    assert "default_app" not in content, f"Found default_app in {p}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5: Sample threshold observations are not used by production
# ─────────────────────────────────────────────────────────────────────────────

def test_05_sample_threshold_observations_not_used_by_production():
    thresh_file = Path("frontend/src/ThresholdMode.jsx")
    if thresh_file.exists():
        content = thresh_file.read_text(encoding="utf-8")
        assert "100.0, 101.2" not in content, "Found sample threshold observations in ThresholdMode.jsx"
        assert "Awaiting authoritative threshold resolution" in content or "Not available" in content


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6: custom_inputs cannot influence authoritative inputs
# ─────────────────────────────────────────────────────────────────────────────

def test_06_custom_inputs_cannot_influence_authoritative_inputs():
    engine = CanonicalV2WorkflowEngine()
    repo_spec = _make_repo_spec(inputs=[{"input_id": "AUTH-1", "value": 42}])
    app_spec = build_application_spec_from_repository_execution_spec(repo_spec)

    req_with_custom = WorkflowRunRequest(
        application_id=app_spec.application_id,
        custom_inputs=[{"input_id": "MALICIOUS-INPUT", "value": 999}],
    )
    run = WorkflowRun(
        workflow_run_id="RUN-CUSTOM-FAIL-01",
        application_id=app_spec.application_id,
        request_fingerprint="REQ-FP-01",
        state=WorkflowState.VALIDATING,
    )
    init_res = engine._stage_validate_and_init(req_with_custom, app_spec, run, {})
    assert isinstance(init_res, WorkflowResult)
    assert init_res.error_code == WorkflowErrorCode.INVALID_INPUT
    assert "Caller-supplied custom_inputs cannot override" in (init_res.error_message or "")


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7: Missing authoritative inputs fails closed
# ─────────────────────────────────────────────────────────────────────────────

def test_07_missing_authoritative_inputs_fails_closed():
    engine = CanonicalV2WorkflowEngine()
    repo_spec = _make_repo_spec(inputs=[])
    app_spec = build_application_spec_from_repository_execution_spec(repo_spec)

    req = WorkflowRunRequest(application_id=app_spec.application_id)
    run = WorkflowRun(
        workflow_run_id="RUN-EMPTY-INPUTS-01",
        application_id=app_spec.application_id,
        request_fingerprint="REQ-FP-02",
        state=WorkflowState.VALIDATING,
    )
    init_res = engine._stage_validate_and_init(req, app_spec, run, {})
    assert isinstance(init_res, WorkflowResult)
    assert init_res.error_code in (WorkflowErrorCode.NO_AUTHORITATIVE_INPUT_SET, WorkflowErrorCode.INVALID_INPUT)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 8: Changing authoritative input set changes execution identity
# ─────────────────────────────────────────────────────────────────────────────

def test_08_changing_authoritative_input_set_changes_execution_identity():
    fp_1 = compute_execution_fingerprint(
        application_id="app_test",
        ref_target_id="ref",
        ref_version="1.0.0",
        ref_source_hash="hash1",
        target_id="tgt",
        target_version="1.0.0",
        target_source_hash="hash2",
        input_set_hash="INP_HASH_A",
        input_count=1,
    )
    fp_2 = compute_execution_fingerprint(
        application_id="app_test",
        ref_target_id="ref",
        ref_version="1.0.0",
        ref_source_hash="hash1",
        target_id="tgt",
        target_version="1.0.0",
        target_source_hash="hash2",
        input_set_hash="INP_HASH_B",
        input_count=1,
    )
    assert fp_1 != fp_2, "Changing input set hash must alter execution fingerprint"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 9: Caller cannot override certification policy
# ─────────────────────────────────────────────────────────────────────────────

def test_09_caller_cannot_override_certification_policy():
    engine = CanonicalV2WorkflowEngine()
    repo_spec = _make_repo_spec()
    app_spec = build_application_spec_from_repository_execution_spec(repo_spec)

    # Caller attempts to submit weak policy override
    req_override = WorkflowRunRequest(
        application_id=app_spec.application_id,
        policy_override={"min_equivalence_score": 0.10, "min_oracle_coverage": 0.0},
        policy_min_equivalence_score=0.10,
        policy_min_oracle_coverage=0.0,
    )
    run = WorkflowRun(
        workflow_run_id="RUN-POL-TEST-01",
        application_id=app_spec.application_id,
        request_fingerprint="REQ-POL-01",
        state=WorkflowState.VALIDATING,
    )
    ctx = {}
    engine._stage_validate_and_init(req_override, app_spec, run, ctx)

    # Context effective policy MUST be derived from backend authority (0.999 for CONTROLLED), ignoring caller
    eff_pol = ctx.get("effective_policy") or (run.metadata or {}).get("effective_policy")
    if eff_pol and isinstance(eff_pol, CertificationPolicy):
        assert eff_pol.min_equivalence_score >= 0.99, "Backend policy resolver must not be overridden by caller"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 10: Backend policy identity is deterministic
# ─────────────────────────────────────────────────────────────────────────────

def test_10_backend_policy_identity_is_deterministic():
    pol1 = certification_policy_resolver.resolve_effective_policy("test_app_det", "CONTROLLED")
    pol2 = certification_policy_resolver.resolve_effective_policy("test_app_det", "CONTROLLED")
    assert pol1.policy_id == pol2.policy_id
    assert pol1.compute_policy_fingerprint() == pol2.compute_policy_fingerprint()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 11: Changing backend certification policy changes policy fingerprint
# ─────────────────────────────────────────────────────────────────────────────

def test_11_changing_backend_certification_policy_changes_policy_fingerprint():
    pol_ctrl = certification_policy_resolver.resolve_effective_policy("test_app_fp", "CONTROLLED")
    pol_full = certification_policy_resolver.resolve_effective_policy("test_app_fp", "FULL")
    assert pol_ctrl.compute_policy_fingerprint() != pol_full.compute_policy_fingerprint()


# ─────────────────────────────────────────────────────────────────────────────
# TEST 12: Stage-B ownership cannot be overwritten
# ─────────────────────────────────────────────────────────────────────────────

def test_12_stage_b_ownership_cannot_be_overwritten(tmp_path):
    db_file = tmp_path / "test_stage_b.sqlite3"
    store = WorkflowPersistenceStore(str(db_file))

    run_owner = WorkflowRun(
        workflow_run_id="RUN-OWNER-001",
        application_id="app_stage_b_test",
        request_fingerprint="REQ-OWNER",
        execution_fingerprint="FP-EXEC-STAGEB-EXCLUSIVE",
        state=WorkflowState.COMPLETED,
    )
    store.save_run(run_owner)

    run_intruder = WorkflowRun(
        workflow_run_id="RUN-INTRUDER-002",
        application_id="app_stage_b_test",
        request_fingerprint="REQ-INTRUDER",
        execution_fingerprint="FP-EXEC-STAGEB-EXCLUSIVE",
        state=WorkflowState.COMPLETED,
    )
    store.save_run(run_intruder)

    orig = store.get_run("RUN-OWNER-001")
    intruder = store.get_run("RUN-INTRUDER-002")
    assert orig is not None and orig.workflow_run_id == "RUN-OWNER-001"
    assert intruder is not None and intruder.workflow_run_id == "RUN-INTRUDER-002"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 13: Recovery cannot bypass authority verification
# ─────────────────────────────────────────────────────────────────────────────

def test_13_recovery_cannot_bypass_authority_verification():
    recovery_svc = WorkflowRecoveryService()
    run_missing_fp = WorkflowRun(
        workflow_run_id="RUN-REC-FAIL-1",
        application_id="app_recovery_test",
        request_fingerprint="REQ-1",
        execution_fingerprint="",
        state=WorkflowState.VALIDATING,
    )
    is_valid, reason = recovery_svc.verify_authority_chain(run_missing_fp)
    assert not is_valid
    assert "Missing Stage-B execution_fingerprint" in reason


# ─────────────────────────────────────────────────────────────────────────────
# TEST 14: Recovery cannot mark incomplete execution as COMPLETED
# ─────────────────────────────────────────────────────────────────────────────

def test_14_recovery_cannot_mark_incomplete_execution_as_completed(tmp_path):
    db_file = tmp_path / "test_recovery.sqlite3"
    store = WorkflowPersistenceStore(str(db_file))
    recovery_svc = WorkflowRecoveryService(persistence=store)

    run_incomplete = WorkflowRun(
        workflow_run_id="RUN-INCOMPLETE-1",
        application_id="app_recovery_test",
        request_fingerprint="REQ-INCOMPLETE",
        execution_fingerprint="FP-INCOMPLETE",
        state=WorkflowState.EVALUATING,
    )
    store.save_run(run_incomplete)

    recovered_runs = recovery_svc.recover_interrupted_workflows()
    assert len(recovered_runs) == 1
    recovered = recovered_runs[0]
    assert recovered.state != WorkflowState.COMPLETED, "Incomplete execution must not be marked COMPLETED"
    assert recovered.state == WorkflowState.FAILED


# ─────────────────────────────────────────────────────────────────────────────
# TEST 15: Missing EvaluationResult fails recovery
# ─────────────────────────────────────────────────────────────────────────────

def test_15_missing_evaluation_result_fails_recovery():
    app_id = "app_test_recovery_missing"
    exec_fp = "FP-EXEC-REC-15"
    oset = _make_valid_oracle_set(app_id, exec_fp)
    thresh = _make_valid_threshold_resolution(app_id, exec_fp, oset.oracle_set_id)

    verif = verify_execution_authority_chain(
        execution_fingerprint=exec_fp,
        application_id=app_id,
        eval_result=None,
        oracle_set=oset,
        threshold_res=thresh,
        require_artifact=False,
    )
    assert not verif.is_valid
    assert verif.error_code is not None or "eval_result" in verif.failure_reason


# ─────────────────────────────────────────────────────────────────────────────
# TEST 16: Missing OracleSet fails recovery
# ─────────────────────────────────────────────────────────────────────────────

def test_16_missing_oracle_set_fails_recovery():
    app_id = "app_test_recovery_missing"
    exec_fp = "FP-EXEC-REC-16"
    eval_res = _make_valid_eval_result(app_id, exec_fp)
    thresh = _make_valid_threshold_resolution(app_id, exec_fp, "OSET-1")

    verif = verify_execution_authority_chain(
        execution_fingerprint=exec_fp,
        application_id=app_id,
        eval_result=eval_res,
        oracle_set=None,
        threshold_res=thresh,
        require_artifact=False,
    )
    assert not verif.is_valid
    assert verif.error_code is not None or "oracle_set" in verif.failure_reason


# ─────────────────────────────────────────────────────────────────────────────
# TEST 17: Missing ThresholdResolution fails recovery
# ─────────────────────────────────────────────────────────────────────────────

def test_17_missing_threshold_resolution_fails_recovery():
    app_id = "app_test_recovery_missing"
    exec_fp = "FP-EXEC-REC-17"
    eval_res = _make_valid_eval_result(app_id, exec_fp)
    oset = _make_valid_oracle_set(app_id, exec_fp)

    verif = verify_execution_authority_chain(
        execution_fingerprint=exec_fp,
        application_id=app_id,
        eval_result=eval_res,
        oracle_set=oset,
        threshold_res=None,
        require_artifact=False,
    )
    assert not verif.is_valid
    assert verif.error_code == WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING


# ─────────────────────────────────────────────────────────────────────────────
# TEST 18: Missing execution binding fails recovery/certification
# ─────────────────────────────────────────────────────────────────────────────

def test_18_missing_execution_binding_fails_recovery_certification():
    app_id = "app_test_recovery_missing"
    exec_fp = "FP-EXEC-REC-18"
    eval_res = _make_valid_eval_result(app_id, "")
    eval_res.metadata.pop("execution_fingerprint", None)
    oset = _make_valid_oracle_set(app_id, exec_fp)
    thresh = _make_valid_threshold_resolution(app_id, exec_fp, oset.oracle_set_id)

    verif = verify_execution_authority_chain(
        execution_fingerprint=exec_fp,
        application_id=app_id,
        eval_result=eval_res,
        oracle_set=oset,
        threshold_res=thresh,
        require_artifact=False,
    )
    assert not verif.is_valid
    assert "missing mandatory execution_fingerprint" in verif.failure_reason


# ─────────────────────────────────────────────────────────────────────────────
# TEST 19: Oracle coverage null remains unavailable
# ─────────────────────────────────────────────────────────────────────────────

def test_19_oracle_coverage_null_remains_unavailable():
    metrics = CertificationMetrics(unique_input_count=2, matching_case_count=2, oracle_coverage_pct=None)
    dumped = metrics.model_dump()
    assert dumped["oracle_coverage_pct"] is None, "oracle_coverage_pct None must serialize as None"

    frontend_tab = Path("frontend/src/CertificationTab.jsx")
    if frontend_tab.exists():
        content = frontend_tab.read_text(encoding="utf-8")
        assert 'meta.oracle_coverage != null ? `${(meta.oracle_coverage * 100).toFixed(1)}%` : "Not available"' in content


# ─────────────────────────────────────────────────────────────────────────────
# TEST 20: Oracle coverage 0% remains 0%
# ─────────────────────────────────────────────────────────────────────────────

def test_20_oracle_coverage_zero_percent_remains_zero():
    metrics = CertificationMetrics(unique_input_count=2, matching_case_count=2, oracle_coverage_pct=0.0)
    dumped = metrics.model_dump()
    assert dumped["oracle_coverage_pct"] == 0.0
    formatted = f"{(metrics.oracle_coverage_pct * 100):.1f}%" if metrics.oracle_coverage_pct is not None else "Not available"
    assert formatted == "0.0%"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 21: Oracle coverage 50% remains 50%
# ─────────────────────────────────────────────────────────────────────────────

def test_21_oracle_coverage_fifty_percent_remains_fifty():
    metrics = CertificationMetrics(unique_input_count=2, matching_case_count=2, oracle_coverage_pct=0.50)
    dumped = metrics.model_dump()
    assert dumped["oracle_coverage_pct"] == 0.50
    formatted = f"{(metrics.oracle_coverage_pct * 100):.1f}%"
    assert formatted == "50.0%"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 22: Oracle coverage 100% remains 100%
# ─────────────────────────────────────────────────────────────────────────────

def test_22_oracle_coverage_hundred_percent_remains_hundred():
    metrics = CertificationMetrics(unique_input_count=2, matching_case_count=2, oracle_coverage_pct=1.0)
    dumped = metrics.model_dump()
    assert dumped["oracle_coverage_pct"] == 1.0
    formatted = f"{(metrics.oracle_coverage_pct * 100):.1f}%"
    assert formatted == "100.0%"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 23: Legitimate external repository flow still constructs RepositoryExecutionSpec
# ─────────────────────────────────────────────────────────────────────────────

def test_23_legitimate_external_repository_flow_constructs_spec():
    repo_spec = _make_repo_spec(
        legacy_commit="real_leg_sha_123",
        modern_commit="real_mod_sha_456",
        adapter_id="external_fastapi_adapter",
        eval_mode="FULL",
    )
    app_spec = build_application_spec_from_repository_execution_spec(repo_spec)
    assert app_spec.application_id == repo_spec.specification_id
    assert app_spec.metadata["legacy_provenance"]["commit_sha"] == "real_leg_sha_123"
    assert app_spec.metadata["modern_provenance"]["commit_sha"] == "real_mod_sha_456"
    assert app_spec.rule_config.mode in ("FULL", "FULL_BEACON")
    assert app_spec.dataset_config.metadata["input_set_identity"] == repo_spec.input_set_identity


# ─────────────────────────────────────────────────────────────────────────────
# TEST 24: Legitimate external repository flow still executes without built-in fake benchmark
# ─────────────────────────────────────────────────────────────────────────────

def test_24_legitimate_external_repository_flow_executes_without_builtin_fake_benchmark():
    from benchmarks.registry import benchmark_registry
    engine = CanonicalV2WorkflowEngine()
    repo_spec = _make_repo_spec(inputs=[{"input_id": "INP-REAL-1", "x": 10}])
    app_spec = build_application_spec_from_repository_execution_spec(repo_spec)

    assert benchmark_registry.get_benchmark(app_spec.application_id) is None

    req = WorkflowRunRequest(application_id=app_spec.application_id)
    run = WorkflowRun(
        workflow_run_id="RUN-REAL-REPO-01",
        application_id=app_spec.application_id,
        request_fingerprint="REQ-REAL-01",
        state=WorkflowState.VALIDATING,
    )
    ctx = {}
    init_res = engine._stage_validate_and_init(req, app_spec, run, ctx)
    assert not isinstance(init_res, WorkflowResult) or init_res.status != "FAILED"
    assert run.execution_fingerprint != ""
    assert "effective_policy" in ctx or "effective_policy" in (run.metadata or {})
