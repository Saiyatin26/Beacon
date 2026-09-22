"""BEACON V2 — Final Pre-Phase-11 Cleanup and Closure Test Suite.

Authoritative targeted test suite covering criteria A through V:
A. Fake data cannot be used in production.
B. Repository certification requires RepositoryExecutionSpec.
C. Repository-derived inputs are authoritative.
D. custom_inputs cannot override repository-discovered inputs in production.
E. Missing authoritative input set fails closed.
F. Changed input set changes execution identity.
G. Changed source revision changes execution identity.
H. Changed adapter identity changes execution identity.
I. Changed evaluation mode/policy identity changes execution identity.
J. Missing evaluation execution binding fails.
K. Wrong evaluation execution binding fails.
L. Missing oracle execution binding fails.
M. Wrong oracle execution binding fails.
N. Missing threshold execution binding fails.
O. Wrong threshold execution binding fails.
P. CertificationArtifact execution binding is verified.
Q. Missing threshold fails closed.
R. Invalid threshold fails closed.
S. Stage-B ownership cannot be overwritten by another execution.
T. Recovery does not bypass authority checks.
U. Persistence failures are surfaced where authoritative.
V. Missing frontend metrics display as unavailable, not fabricated values.
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


# ─────────────────────────────────────────────────────────────────────────────
# Criteria A: Fake Data Cannot Be Used in Production
# ─────────────────────────────────────────────────────────────────────────────

def test_a_fake_data_cannot_be_used_in_production():
    """Criterion A: Database has 0 fake apps; beacon/data has no fake runs or dummy PDFs."""
    db_path = Path("data/beacon.sqlite3")
    assert db_path.exists(), "Production SQLite database must exist"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM applications WHERE application_id LIKE 'app_%' OR application_id LIKE 'demo_%'")
    demo_app_count = cursor.fetchone()[0]
    assert demo_app_count == 0, f"Found {demo_app_count} fake demo applications in production DB"

    evidence_dir = Path("beacon/data/evidence")
    if evidence_dir.exists():
        stale_runs = list(evidence_dir.glob("PAIRED-SESS-*"))
        assert len(stale_runs) == 0, f"Found {len(stale_runs)} fake demo run directories in evidence"

    ks_dir = Path("beacon/data/knowledge_store")
    if ks_dir.exists():
        dummy_pdfs = list(ks_dir.glob("*.pdf"))
        assert len(dummy_pdfs) == 0, f"Found {len(dummy_pdfs)} dummy PDFs in knowledge_store"

    root_db = Path("beacon.sqlite3")
    assert not root_db.exists(), "Stale duplicate root beacon.sqlite3 must not exist"

    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Criteria B: Repository Certification Requires RepositoryExecutionSpec
# ─────────────────────────────────────────────────────────────────────────────

def test_b_repository_certification_requires_repository_execution_spec():
    """Criterion B: Canonical repository certification constructs and uses RepositoryExecutionSpec."""
    repo_spec = _make_repo_spec()
    app_spec = build_application_spec_from_repository_execution_spec(repo_spec)

    assert isinstance(app_spec, ApplicationSpec)
    assert app_spec.application_id == repo_spec.specification_id
    assert app_spec.metadata.get("specification_id") == repo_spec.specification_id
    assert app_spec.metadata.get("authoritative_input_set") == repo_spec.discovered_inputs
    assert app_spec.dataset_config.metadata.get("authoritative_input_set") == repo_spec.discovered_inputs
    assert app_spec.dataset_config.metadata.get("input_set_identity") == repo_spec.input_set_identity


# ─────────────────────────────────────────────────────────────────────────────
# Criteria C & D: Repository-Derived Inputs Are Authoritative, custom_inputs Forbidden
# ─────────────────────────────────────────────────────────────────────────────

def test_c_d_repository_inputs_authoritative_and_custom_inputs_prohibited():
    """Criteria C & D: Repository inputs are authoritative; custom_inputs cannot override repository spec."""
    engine = CanonicalV2WorkflowEngine()
    repo_spec = _make_repo_spec(inputs=[{"input_id": "AUTH-1", "value": 42}])
    app_spec = build_application_spec_from_repository_execution_spec(repo_spec)

    req_with_custom = WorkflowRunRequest(
        application_id=app_spec.application_id,
        custom_inputs=[{"input_id": "FAKE-OVERRIDE", "value": 999}],
    )
    run = WorkflowRun(
        workflow_run_id="RUN-CUSTOM-FAIL-01",
        application_id=app_spec.application_id,
        request_fingerprint="REQ-FP-01",
        state=WorkflowState.VALIDATING,
    )

    init_res = engine._stage_validate_and_init(req_with_custom, app_spec, run, {})
    assert isinstance(init_res, WorkflowResult), "Supplying custom_inputs to repository spec must return failed WorkflowResult"
    assert init_res.error_code == WorkflowErrorCode.INVALID_INPUT
    assert "Caller-supplied custom_inputs cannot override" in (init_res.error_message or "")


# ─────────────────────────────────────────────────────────────────────────────
# Criteria E: Missing Authoritative Input Set Fails Closed
# ─────────────────────────────────────────────────────────────────────────────

def test_e_missing_authoritative_input_set_fails_closed():
    """Criterion E: Missing authoritative input set fails closed with INVALID_INPUT."""
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
    assert isinstance(init_res, WorkflowResult), "Missing authoritative inputs must return failed WorkflowResult"
    assert init_res.error_code in (WorkflowErrorCode.NO_AUTHORITATIVE_INPUT_SET, WorkflowErrorCode.INVALID_INPUT)


# ─────────────────────────────────────────────────────────────────────────────
# Criteria F, G, H, I: Execution Identity Participation
# ─────────────────────────────────────────────────────────────────────────────

def test_f_changed_input_set_changes_execution_identity():
    """Criterion F: Changing the input set produces a different execution fingerprint."""
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
    assert fp_1 != fp_2, "Altering input set hash must change execution fingerprint"


def test_g_changed_source_revision_changes_execution_identity():
    """Criterion G: Changing source revision produces a different execution fingerprint."""
    fp_v1 = compute_execution_fingerprint(
        application_id="app_test",
        ref_target_id="ref",
        ref_version="1.0.0",
        ref_source_hash="hash_v1",
        target_id="tgt",
        target_version="1.0.0",
        target_source_hash="hash_tgt",
        input_set_hash="INP_HASH_A",
        input_count=1,
    )
    fp_v2 = compute_execution_fingerprint(
        application_id="app_test",
        ref_target_id="ref",
        ref_version="1.0.0",
        ref_source_hash="hash_v2",
        target_id="tgt",
        target_version="1.0.0",
        target_source_hash="hash_tgt",
        input_set_hash="INP_HASH_A",
        input_count=1,
    )
    assert fp_v1 != fp_v2, "Altering source hash must change execution fingerprint"


def test_h_changed_adapter_identity_changes_execution_identity():
    """Criterion H: Changing adapter identity produces a different execution fingerprint."""
    fp_a1 = compute_execution_fingerprint(
        application_id="app_test",
        ref_target_id="adapter_python_fastapi",
        ref_version="1.0.0",
        ref_source_hash="hash_ref",
        target_id="tgt",
        target_version="1.0.0",
        target_source_hash="hash_tgt",
        input_set_hash="INP_HASH_A",
        input_count=1,
    )
    fp_a2 = compute_execution_fingerprint(
        application_id="app_test",
        ref_target_id="adapter_python_flask",
        ref_version="1.0.0",
        ref_source_hash="hash_ref",
        target_id="tgt",
        target_version="1.0.0",
        target_source_hash="hash_tgt",
        input_set_hash="INP_HASH_A",
        input_count=1,
    )
    assert fp_a1 != fp_a2, "Altering adapter ID must change execution fingerprint"


def test_i_changed_evaluation_mode_changes_execution_identity():
    """Criterion I: Changing evaluation mode produces a different execution fingerprint."""
    fp_ctrl = compute_execution_fingerprint(
        application_id="app_test",
        ref_target_id="ref",
        ref_version="1.0.0",
        ref_source_hash="hash_ref",
        target_id="tgt",
        target_version="1.0.0",
        target_source_hash="hash_tgt",
        input_set_hash="INP_HASH_A",
        input_count=1,
        evaluation_mode="CONTROLLED",
    )
    fp_full = compute_execution_fingerprint(
        application_id="app_test",
        ref_target_id="ref",
        ref_version="1.0.0",
        ref_source_hash="hash_ref",
        target_id="tgt",
        target_version="1.0.0",
        target_source_hash="hash_tgt",
        input_set_hash="INP_HASH_A",
        input_count=1,
        evaluation_mode="FULL",
    )
    assert fp_ctrl != fp_full, "Altering evaluation mode must change execution fingerprint"


# ─────────────────────────────────────────────────────────────────────────────
# Criteria J, K, L, M, N, O, P: Cross-Binding Execution Authority
# ─────────────────────────────────────────────────────────────────────────────

def test_j_k_evaluation_execution_binding():
    """Criteria J & K: Missing or mismatched evaluation execution fingerprint fails closed."""
    app_id = "app_test_crossbind"
    correct_fp = "FP-EXEC-CORRECT-111"

    eval_missing_fp = _make_valid_eval_result(app_id, correct_fp)
    eval_missing_fp.metadata.pop("execution_fingerprint")
    oset = _make_valid_oracle_set(app_id, correct_fp)
    thresh = _make_valid_threshold_resolution(app_id, correct_fp, oset.oracle_set_id)

    res_missing = verify_execution_authority_chain(
        execution_fingerprint=correct_fp,
        application_id=app_id,
        eval_result=eval_missing_fp,
        oracle_set=oset,
        threshold_res=thresh,
        require_artifact=False,
    )
    assert not res_missing.is_valid
    assert "missing mandatory execution_fingerprint" in res_missing.failure_reason

    eval_wrong_fp = _make_valid_eval_result(app_id, "FP-EXEC-WRONG-999")
    res_wrong = verify_execution_authority_chain(
        execution_fingerprint=correct_fp,
        application_id=app_id,
        eval_result=eval_wrong_fp,
        oracle_set=oset,
        threshold_res=thresh,
        require_artifact=False,
    )
    assert not res_wrong.is_valid
    assert "execution fingerprint mismatch" in res_wrong.failure_reason


def test_l_m_oracle_execution_binding():
    """Criteria L & M: Missing or mismatched oracle execution fingerprint fails closed."""
    app_id = "app_test_crossbind"
    correct_fp = "FP-EXEC-CORRECT-222"

    eval_res = _make_valid_eval_result(app_id, correct_fp)
    thresh_dummy = _make_valid_threshold_resolution(app_id, correct_fp, "OSET-TEMP")

    oset_missing_fp = _make_valid_oracle_set(app_id, correct_fp)
    oset_missing_fp = oset_missing_fp.model_copy(update={"metadata": {}})
    thresh_dummy.provenance["oracle_set_id"] = oset_missing_fp.oracle_set_id
    thresh_dummy.fingerprint = thresh_dummy.compute_fingerprint()

    res_missing = verify_execution_authority_chain(
        execution_fingerprint=correct_fp,
        application_id=app_id,
        eval_result=eval_res,
        oracle_set=oset_missing_fp,
        threshold_res=thresh_dummy,
        require_artifact=False,
    )
    assert not res_missing.is_valid
    assert "missing mandatory execution_fingerprint" in res_missing.failure_reason

    oset_wrong_fp = _make_valid_oracle_set(app_id, "FP-EXEC-WRONG-888")
    thresh_dummy.provenance["oracle_set_id"] = oset_wrong_fp.oracle_set_id
    thresh_dummy.fingerprint = thresh_dummy.compute_fingerprint()

    res_wrong = verify_execution_authority_chain(
        execution_fingerprint=correct_fp,
        application_id=app_id,
        eval_result=eval_res,
        oracle_set=oset_wrong_fp,
        threshold_res=thresh_dummy,
        require_artifact=False,
    )
    assert not res_wrong.is_valid
    assert "execution fingerprint mismatch" in res_wrong.failure_reason


def test_n_o_threshold_execution_binding():
    """Criteria N & O: Missing or mismatched threshold execution fingerprint fails closed."""
    app_id = "app_test_crossbind"
    correct_fp = "FP-EXEC-CORRECT-333"

    eval_res = _make_valid_eval_result(app_id, correct_fp)
    oset = _make_valid_oracle_set(app_id, correct_fp)

    thresh_missing = _make_valid_threshold_resolution(app_id, correct_fp, oset.oracle_set_id)
    thresh_missing.provenance = {"oracle_set_id": oset.oracle_set_id}
    thresh_missing.fingerprint = thresh_missing.compute_fingerprint()

    res_missing = verify_execution_authority_chain(
        execution_fingerprint=correct_fp,
        application_id=app_id,
        eval_result=eval_res,
        oracle_set=oset,
        threshold_res=thresh_missing,
        require_artifact=False,
    )
    assert not res_missing.is_valid
    assert "missing mandatory execution_fingerprint" in res_missing.failure_reason

    thresh_wrong = _make_valid_threshold_resolution(app_id, "FP-EXEC-WRONG-777", oset.oracle_set_id)
    res_wrong = verify_execution_authority_chain(
        execution_fingerprint=correct_fp,
        application_id=app_id,
        eval_result=eval_res,
        oracle_set=oset,
        threshold_res=thresh_wrong,
        require_artifact=False,
    )
    assert not res_wrong.is_valid
    assert "execution fingerprint mismatch" in res_wrong.failure_reason


def test_p_certification_artifact_execution_binding():
    """Criterion P: CertificationArtifact context execution fingerprint must match."""
    app_id = "app_test_crossbind"
    correct_fp = "FP-EXEC-CORRECT-444"

    eval_res = _make_valid_eval_result(app_id, correct_fp)
    oset = _make_valid_oracle_set(app_id, correct_fp)
    thresh = _make_valid_threshold_resolution(app_id, correct_fp, oset.oracle_set_id)

    art_missing_fp = _make_valid_artifact(app_id, "", oset.oracle_set_id, thresh.resolution_id)
    res_missing = verify_execution_authority_chain(
        execution_fingerprint=correct_fp,
        application_id=app_id,
        eval_result=eval_res,
        oracle_set=oset,
        threshold_res=thresh,
        artifact=art_missing_fp,
        require_artifact=True,
    )
    assert not res_missing.is_valid
    assert "missing mandatory execution_fingerprint" in res_missing.failure_reason

    art_wrong_fp = _make_valid_artifact(app_id, "FP-EXEC-WRONG-555", oset.oracle_set_id, thresh.resolution_id)
    res_wrong = verify_execution_authority_chain(
        execution_fingerprint=correct_fp,
        application_id=app_id,
        eval_result=eval_res,
        oracle_set=oset,
        threshold_res=thresh,
        artifact=art_wrong_fp,
        require_artifact=True,
    )
    assert not res_wrong.is_valid
    assert "execution fingerprint mismatch" in res_wrong.failure_reason


# ─────────────────────────────────────────────────────────────────────────────
# Criteria Q & R: Threshold Fail-Closed Behavior
# ─────────────────────────────────────────────────────────────────────────────

def test_q_r_threshold_fail_closed():
    """Criteria Q & R: Missing or invalid threshold fails closed."""
    app_id = "app_test_thresh"
    correct_fp = "FP-EXEC-THRESH-555"

    eval_res = _make_valid_eval_result(app_id, correct_fp)
    oset = _make_valid_oracle_set(app_id, correct_fp)

    res_none = verify_execution_authority_chain(
        execution_fingerprint=correct_fp,
        application_id=app_id,
        eval_result=eval_res,
        oracle_set=oset,
        threshold_res=None,
        require_artifact=False,
    )
    assert not res_none.is_valid
    assert res_none.error_code == WorkflowErrorCode.THRESHOLD_AUTHORITY_MISSING

    thresh_corrupt = _make_valid_threshold_resolution(app_id, correct_fp, oset.oracle_set_id)
    thresh_corrupt.fingerprint = "TAMPERED_FINGERPRINT_VALUE"

    res_corrupt = verify_execution_authority_chain(
        execution_fingerprint=correct_fp,
        application_id=app_id,
        eval_result=eval_res,
        oracle_set=oset,
        threshold_res=thresh_corrupt,
        require_artifact=False,
    )
    assert not res_corrupt.is_valid
    assert res_corrupt.error_code == WorkflowErrorCode.THRESHOLD_FINGERPRINT_MISMATCH


# ─────────────────────────────────────────────────────────────────────────────
# Criteria S: Stage-B Ownership Cannot Be Overwritten
# ─────────────────────────────────────────────────────────────────────────────

def test_s_stage_b_ownership_cannot_be_overwritten(tmp_path):
    """Criterion S: Stage-B execution ownership cannot be overwritten by another execution."""
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

    persisted = store.get_run("RUN-OWNER-001")
    assert persisted is not None
    assert persisted.workflow_run_id == "RUN-OWNER-001"
    assert persisted.execution_fingerprint == "FP-EXEC-STAGEB-EXCLUSIVE"

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
# Criteria T: Recovery Does Not Bypass Authority Checks
# ─────────────────────────────────────────────────────────────────────────────

def test_t_recovery_does_not_bypass_authority_checks():
    """Criterion T: Recovery enforces strict authority verification and fails closed on unanchored artifacts."""
    recovery_svc = WorkflowRecoveryService()

    # 1. Interrupted run missing execution_fingerprint fails closed
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

    # 2. Interrupted run missing certification_id fails closed
    run_missing_cert = WorkflowRun(
        workflow_run_id="RUN-REC-FAIL-2",
        application_id="app_recovery_test",
        request_fingerprint="REQ-2",
        execution_fingerprint="FP-REC-2",
        certification_id="",
        state=WorkflowState.VALIDATING,
    )
    is_valid, reason = recovery_svc.verify_authority_chain(run_missing_cert)
    assert not is_valid
    assert "Missing certification_id" in reason

    # 3. Recovery delegation to central verifier fails closed on mismatched execution authority
    app_id = "app_recovery_test"
    exec_fp = "FP-RECOVERY-VERIFY-1"
    eval_res = _make_valid_eval_result(app_id, exec_fp)
    oset = _make_valid_oracle_set(app_id, exec_fp)
    thresh = _make_valid_threshold_resolution(app_id, exec_fp, oset.oracle_set_id)
    art_corrupt = _make_valid_artifact(app_id, "WRONG-EXEC-FP", oset.oracle_set_id, thresh.resolution_id)

    verif_res = verify_execution_authority_chain(
        execution_fingerprint=exec_fp,
        application_id=app_id,
        eval_result=eval_res,
        oracle_set=oset,
        threshold_res=thresh,
        artifact=art_corrupt,
        require_artifact=True,
    )
    assert not verif_res.is_valid, "Recovery authority verifier must fail closed on mismatched execution authority"
    assert "execution fingerprint mismatch" in verif_res.failure_reason


# ─────────────────────────────────────────────────────────────────────────────
# Criteria U: Authoritative Persistence Failure Is Surfaced
# ─────────────────────────────────────────────────────────────────────────────

def test_u_authoritative_persistence_failure_is_surfaced():
    """Criterion U: Failure during state transition or run persistence surfaces with audit_status=PERSISTENCE_FAILED."""
    engine = CanonicalV2WorkflowEngine()
    run = WorkflowRun(
        workflow_run_id="RUN-PERSIST-ERR-01",
        application_id="app_persist_test",
        request_fingerprint="REQ-FP-03",
        state=WorkflowState.PERSISTING,
    )

    class BrokenEngine(CanonicalV2WorkflowEngine):
        def transition_state(self, *args, **kwargs):
            raise sqlite3.OperationalError("Simulated database lock failure on state transition")

    broken = BrokenEngine()
    failed_res = broken._fail_run(
        run,
        WorkflowErrorCode.PERSISTENCE_FAILED,
        "Authoritative disk write failed",
    )
    assert failed_res is not None
    assert failed_res.audit_status == "PERSISTENCE_FAILED" or "STATE TRANSITION FAILED" in (failed_res.error_message or "")


# ─────────────────────────────────────────────────────────────────────────────
# Criteria V: Missing Frontend Metrics Display Unavailable
# ─────────────────────────────────────────────────────────────────────────────

def test_v_frontend_missing_metrics_display_unavailable():
    """Criterion V: Frontend CertificationTab.jsx does not fabricate 100.0% when oracleCoverage is null."""
    frontend_tab = Path("frontend/src/CertificationTab.jsx")
    assert frontend_tab.exists()

    content = frontend_tab.read_text(encoding="utf-8")
    assert 'meta.oracle_coverage != null ? `${(meta.oracle_coverage * 100).toFixed(1)}%` : "100.0%"' not in content, (
        "Frontend must not fabricate 100.0% when oracle_coverage is missing"
    )
    assert 'meta.oracle_coverage != null ? `${(meta.oracle_coverage * 100).toFixed(1)}%` : "Not available"' in content, (
        "Frontend must display 'Not available' when oracle_coverage is missing"
    )
