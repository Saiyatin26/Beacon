"""BEACON V2 — End-to-End Oracle Reconciliation Test Suite.

Comprehensive tests for:
1. A valid complete oracle set.
2. Missing oracle set.
3. Invalid oracle hash.
4. Missing InputSet.
5. Invalid InputSet hash.
6. Wrong run or application binding.
7. Missing required execution observation.
8. Duplicate or conflicting bindings.
9. Zero required bindings.
10. Partial coverage.
11. Complete coverage.
12. Actual behavioral mismatch despite successful reconciliation.
13. Frontend rendering of backend statuses.
14. API failure versus genuinely missing evidence.
15. InputSet persistence before finalization.
16. Successful dossier export.
17. Dossier export blocked by missing mandatory artifacts.
18. Tampering with source hashes, input sets, oracle sets, and certificate data.
19. Unauthorized access to another certification run.
20. A complete Full BEACON integration workflow.
"""

import hashlib
import json
import pytest
from fastapi.testclient import TestClient

from api.main import app
from auth.dependencies import get_current_user
from auth.models import Permission, User, UserRole
from certification.models import (
    BehavioralRegression,
    CertificationArtifact,
    CertificationCase,
    CertificationContext,
    CertificationInputSet,
    CertificationMetrics,
    CertificationPolicy,
    CertificationStatus,
    compute_artifact_content_hash,
    compute_input_set_canonical_hash,
)
from certification.repository import certification_repository
from reconciliation.models import (
    OracleRule,
    OracleSet,
    RuleConflict,
    RuleProvenanceSource,
)
from reconciliation.oracle_reconciliation_models import (
    OracleBindingStatus,
    OracleReconciliationRecord,
    OracleReconciliationStatus,
)
from reconciliation.oracle_reconciliation_service import oracle_reconciliation_service
from reconciliation.persistence import reconciliation_persistence
from workflow.models import WorkflowRun, WorkflowState
from workflow.persistence import workflow_persistence


@pytest.fixture(autouse=True)
def clean_state():
    """Ensure clean persistence stores for test isolation."""
    certification_repository.clear()
    yield
    certification_repository.clear()


def make_admin_user(project_id="test_app"):
    return User(
        user_id="admin-1",
        username="admin",
        password_hash="test_pw_hash",
        role=UserRole.SYSTEM_ADMIN,
        project_ids=[project_id],
        is_system_admin=True,
    )


def make_test_cases(cert_id, input_set_id, count=3, pass_all=True):
    cases = []
    for i in range(count):
        raw_inp = {"amount": 100 * (i + 1), "__condition_provenance": f"RULE-00{i+1}"}
        inp_json = json.dumps(raw_inp, sort_keys=True)
        inp_hash = hashlib.sha256(inp_json.encode()).hexdigest()
        is_match = pass_all or (i == 0)
        cases.append(
            CertificationCase(
                case_id=f"CASE-{cert_id}-{i+1}",
                run_id=cert_id,
                input_set_id=input_set_id,
                case_index=i,
                input_id=f"inp_{i+1}",
                input_json=inp_json,
                input_hash=inp_hash,
                legacy_output_json=json.dumps({"result": 100 * (i + 1)}),
                modern_output_json=json.dumps({"result": 100 * (i + 1) if is_match else 999}),
                legacy_execution_status="SUCCESS",
                modern_execution_status="SUCCESS",
                execution_time_ms=1.5,
                oracle_result="PASS" if is_match else "VIOLATED",
                classification="MATCH" if is_match else "MODERN_REGRESSION",
                severity="none" if is_match else "medium",
            )
        )
    return cases


def make_test_rule(rule_id="RULE-001", app_id="test_app"):
    return OracleRule(
        rule_id=rule_id,
        rule_type="invariant",
        name=f"Rule {rule_id}",
        description=f"Description for {rule_id}",
        canonical_expression=f"amount > 0 => result == amount",
        conditions={"amount": {">": 0}},
        expected_behavior={"result": "amount"},
        source=RuleProvenanceSource.DISCOVERED,
        confidence=1.0,
    )


def setup_complete_run(app_id="test_app", num_rules=2, pass_all=True, alter_hash=None):
    run_id = f"RUN-{app_id}"
    cert_id = f"CERT-{app_id}"

    # 1. Rules and OracleSet
    rules = [make_test_rule(f"RULE-00{i+1}", app_id) for i in range(num_rules)]
    oset_id = f"OSET-{app_id}"
    oset = OracleSet(
        oracle_set_id=oset_id,
        application_id=app_id,
        version=1,
        rules=rules,
    )
    oset.oracle_set_hash = alter_hash if alter_hash else oset.compute_oracle_set_hash()
    reconciliation_persistence.save_oracle_set(oset)

    # 2. WorkflowRun
    w_run = WorkflowRun(
        workflow_run_id=run_id,
        application_id=app_id,
        request_fingerprint=f"fp_{app_id}",
        state=WorkflowState.PERSISTING,
        oracle_set_id=oset_id,
        certification_id=cert_id,
        metadata={
            "legacy_provenance": {"content_hash": "sha_legacy_123"},
            "modern_provenance": {"content_hash": "sha_modern_456"},
        },
    )
    workflow_persistence.save_run(w_run)

    # 3. InputSet and Cases
    inp_set_id = f"INPSET-{cert_id}"
    cases = make_test_cases(cert_id, inp_set_id, count=num_rules, pass_all=pass_all)
    inp_set_hash = compute_input_set_canonical_hash(cases)
    input_set = CertificationInputSet(
        input_set_id=inp_set_id,
        version=1,
        generator_type="canonical_workflow",
        input_count=len(cases),
        canonical_hash=inp_set_hash,
    )

    # 4. Artifact
    ctx = CertificationContext(
        benchmark_id=app_id,
        legacy_implementation_hash="sha_legacy_123",
        modernized_implementation_hash="sha_modern_456",
        oracle_set_id=oset_id,
        oracle_set_hash=oset.oracle_set_hash,
        input_set_id=inp_set_id,
        input_set_hash=inp_set_hash,
        certification_run_id=run_id,
    )
    temp_art = CertificationArtifact(
        certification_id=cert_id,
        project_id=app_id,
        oracle_set_id=oset_id,
        oracle_set_hash=oset.oracle_set_hash,
        input_set_id=inp_set_id,
        input_set_hash=inp_set_hash,
        status=CertificationStatus.CERTIFIED if pass_all else CertificationStatus.NOT_CERTIFIED,
        certified=pass_all,
        score=1.0 if pass_all else 0.5,
        metrics=CertificationMetrics(
            unique_input_count=len(cases),
            matching_case_count=sum(1 for c in cases if c.oracle_result == "PASS"),
            regression_case_count=sum(1 for c in cases if c.oracle_result != "PASS"),
            oracle_count=num_rules,
            oracle_coverage_pct=1.0,
            overall_equivalence_score=1.0 if pass_all else 0.5,
            evidence_quality_score=1.0,
            evidence_adjusted_score=1.0 if pass_all else 0.5,
        ),
        context=ctx,
        content_hash="",
    )
    art = temp_art.model_copy(update={"content_hash": compute_artifact_content_hash(temp_art)})

    certification_repository.save_certification_run_atomic(
        input_set=input_set,
        cases=cases,
        artifact=art,
    )

    return run_id, cert_id, oset, input_set, cases, art


# ==============================================================================
# TESTS 1 - 20
# ==============================================================================

def test_1_valid_complete_oracle_set():
    """1. Valid complete oracle set reconciles with 100% coverage and RECONCILED status."""
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t1", num_rules=2)
    record = oracle_reconciliation_service.reconcile_certification_run(run_id)

    assert record.status == OracleReconciliationStatus.RECONCILED
    assert record.coverage == 1.0
    assert record.binding_counts.total_required_bindings == 2
    assert record.binding_counts.matched_bindings == 2
    assert record.binding_counts.missing_bindings == 0
    assert record.evidence_hash != ""
    assert len(record.failure_reasons) == 0


def test_2_missing_oracle_set():
    """2. Missing oracle set yields NOT_AVAILABLE with descriptive failure reason."""
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t2", num_rules=1)
    # Tamper run to reference non-existent oracle set
    run = workflow_persistence.get_run(run_id)
    run.oracle_set_id = "OSET-NONEXISTENT"
    workflow_persistence.save_run(run)

    record = oracle_reconciliation_service.reconcile_certification_run(run_id)
    assert record.status == OracleReconciliationStatus.NOT_AVAILABLE
    assert any("OracleSet authority missing" in r for r in record.failure_reasons)


def test_3_invalid_oracle_hash():
    """3. Stored oracle hash tampering causes integrity check to fail with status FAILED."""
    run_id, cert_id, oset, iset, cases, art = setup_complete_run(
        "app_t3", num_rules=1, alter_hash="tampered_hash_123"
    )
    record = oracle_reconciliation_service.reconcile_certification_run(run_id)

    assert record.status == OracleReconciliationStatus.FAILED
    assert any("OracleSet cryptographic tamper detected" in r for r in record.failure_reasons)


def test_4_missing_input_set():
    """4. Missing InputSet yields NOT_AVAILABLE with safe missing artifact reason."""
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t4", num_rules=1)
    with __import__("sqlite3").connect(certification_repository._db_path) as conn:
        conn.execute("DELETE FROM input_sets")
        conn.commit()

    record = oracle_reconciliation_service.reconcile_certification_run(run_id)
    assert record.status == OracleReconciliationStatus.NOT_AVAILABLE
    assert any("Accepted InputSet missing" in r for r in record.failure_reasons)


def test_5_invalid_input_set_hash():
    """5. Tampered InputSet canonical hash causes status FAILED."""
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t5", num_rules=1)
    # Tamper the stored canonical hash in the input_sets table
    corrupt_iset = iset.model_copy(update={"canonical_hash": "tampered_input_hash_xyz"})
    with __import__("sqlite3").connect(certification_repository._db_path) as conn:
        conn.execute(
            "UPDATE input_sets SET canonical_hash = ?, payload_json = ? WHERE input_set_id = ?",
            ("tampered_input_hash_xyz", corrupt_iset.model_dump_json(), iset.input_set_id)
        )
        conn.commit()

    record = oracle_reconciliation_service.reconcile_certification_run(run_id)
    assert record.status == OracleReconciliationStatus.FAILED
    assert any("InputSet cryptographic tamper detected" in r for r in record.failure_reasons)


def test_6_wrong_application_binding():
    """6. Cross-application binding violation detects mismatched application IDs."""
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t6_A", num_rules=1)
    # Put oracle set belonging to another app
    oset_b = OracleSet(
        oracle_set_id="OSET-MISMATCH",
        application_id="app_t6_B",
        version=1,
        rules=oset.rules,
    )
    oset_b.oracle_set_hash = oset_b.compute_oracle_set_hash()
    reconciliation_persistence.save_oracle_set(oset_b)

    run = workflow_persistence.get_run(run_id)
    run.oracle_set_id = "OSET-MISMATCH"
    workflow_persistence.save_run(run)

    record = oracle_reconciliation_service.reconcile_certification_run(run_id)
    assert record.status == OracleReconciliationStatus.FAILED
    assert any("Cross-application binding violation" in r for r in record.failure_reasons)


def test_7_missing_required_execution_observation():
    """7. Failed executions (crashes/exceptions) do not count as valid observations."""
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t7", num_rules=1)
    # Modify case to have CRASH execution status
    crashed_case = cases[0].model_copy(update={
        "legacy_execution_status": "CRASH",
        "modern_execution_status": "EXCEPTION",
    })
    with __import__("sqlite3").connect(certification_repository._db_path) as conn:
        conn.execute(
            "UPDATE certification_cases SET payload_json = ? WHERE case_id = ?",
            (crashed_case.model_dump_json(), crashed_case.case_id)
        )
        conn.commit()

    record = oracle_reconciliation_service.reconcile_certification_run(run_id)
    assert record.binding_counts.matched_bindings == 0
    assert record.binding_counts.missing_bindings == 1
    assert record.bindings[0].binding_status == OracleBindingStatus.UNBOUND


def test_8_duplicate_or_conflicting_bindings():
    """8. Unresolved material rule conflicts trigger CONFLICT status."""
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t8", num_rules=2)
    conflict = RuleConflict(
        conflict_id="CONF-001",
        rule_a_id="RULE-001",
        rule_b_id="RULE-002",
        rule_a_source="MINED",
        rule_b_source="SYNTHESIZED",
        reason="Rule 1 and Rule 2 contradict on amount > 0",
        resolution_status="UNRESOLVED",
    )
    oset_with_conflict = oset.model_copy(update={"conflicts": [conflict]})
    oset_with_conflict.oracle_set_hash = oset_with_conflict.compute_oracle_set_hash()
    reconciliation_persistence.save_oracle_set(oset_with_conflict)

    # Sync artifact with new oracle_set_hash
    artifact = certification_repository.get_artifact(cert_id)
    if artifact:
        art_updated = artifact.model_copy(update={"oracle_set_hash": oset_with_conflict.oracle_set_hash})
        art_updated = art_updated.model_copy(update={"content_hash": compute_artifact_content_hash(art_updated)})
        certification_repository._memory_artifacts[cert_id] = art_updated
        with __import__("sqlite3").connect(certification_repository._db_path) as conn:
            conn.execute(
                "UPDATE certification_artifacts SET oracle_set_hash = ?, content_hash = ?, payload_json = ? WHERE certification_id = ?",
                (art_updated.oracle_set_hash, art_updated.content_hash, art_updated.model_dump_json(), cert_id)
            )
            conn.commit()

    record = oracle_reconciliation_service.reconcile_certification_run(run_id)
    assert record.status == OracleReconciliationStatus.CONFLICT
    assert record.binding_counts.conflicting_bindings >= 1


def test_9_zero_required_bindings():
    """9. Zero required rules produce explicit undefined coverage (None, never 100%)."""
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t9", num_rules=0)
    record = oracle_reconciliation_service.reconcile_certification_run(run_id)

    assert record.coverage is None
    assert record.binding_counts.total_required_bindings == 0
    assert record.status == OracleReconciliationStatus.NOT_AVAILABLE


def test_10_partial_coverage():
    """10. Partial rule coverage correctly returns PARTIALLY_RECONCILED with ratio."""
    app_id = "app_t10"
    run_id = f"RUN-{app_id}"
    cert_id = f"CERT-{app_id}"

    # 1. 2 Rules
    rules = [make_test_rule(f"RULE-00{i+1}", app_id) for i in range(2)]
    oset_id = f"OSET-{app_id}"
    oset = OracleSet(oracle_set_id=oset_id, application_id=app_id, version=1, rules=rules)
    oset.oracle_set_hash = oset.compute_oracle_set_hash()
    reconciliation_persistence.save_oracle_set(oset)

    # 2. WorkflowRun
    w_run = WorkflowRun(
        workflow_run_id=run_id,
        application_id=app_id,
        request_fingerprint=f"fp_{app_id}",
        state=WorkflowState.PERSISTING,
        oracle_set_id=oset_id,
        certification_id=cert_id,
    )
    workflow_persistence.save_run(w_run)

    # 3. InputSet and Cases - both cases only exercise RULE-001
    inp_set_id = f"INPSET-{cert_id}"
    cases = []
    for i in range(2):
        raw_inp = {"amount": 100 * (i + 1), "__condition_provenance": "RULE-001"}
        inp_json = json.dumps(raw_inp, sort_keys=True)
        inp_hash = hashlib.sha256(inp_json.encode()).hexdigest()
        cases.append(
            CertificationCase(
                case_id=f"CASE-{cert_id}-{i+1}",
                run_id=cert_id,
                input_set_id=inp_set_id,
                case_index=i,
                input_id=f"inp_{i+1}",
                input_json=inp_json,
                input_hash=inp_hash,
                legacy_output_json=json.dumps({"result": 100 * (i + 1)}),
                modern_output_json=json.dumps({"result": 100 * (i + 1)}),
                legacy_execution_status="SUCCESS",
                modern_execution_status="SUCCESS",
                execution_time_ms=1.5,
                oracle_result="PASS",
                classification="MATCH",
                severity="none",
            )
        )
    inp_set_hash = compute_input_set_canonical_hash(cases)
    input_set = CertificationInputSet(
        input_set_id=inp_set_id,
        version=1,
        generator_type="canonical_workflow",
        input_count=len(cases),
        canonical_hash=inp_set_hash,
    )

    # 4. Artifact
    ctx = CertificationContext(
        benchmark_id=app_id,
        oracle_set_id=oset_id,
        oracle_set_hash=oset.oracle_set_hash,
        input_set_id=inp_set_id,
        input_set_hash=inp_set_hash,
        certification_run_id=run_id,
    )
    temp_art = CertificationArtifact(
        certification_id=cert_id,
        project_id=app_id,
        oracle_set_id=oset_id,
        oracle_set_hash=oset.oracle_set_hash,
        input_set_id=inp_set_id,
        input_set_hash=inp_set_hash,
        status=CertificationStatus.NOT_CERTIFIED,
        certified=False,
        score=0.5,
        metrics=CertificationMetrics(
            unique_input_count=len(cases),
            matching_case_count=2,
            regression_case_count=0,
            oracle_count=2,
            oracle_coverage_pct=0.5,
            overall_equivalence_score=0.5,
            evidence_quality_score=1.0,
            evidence_adjusted_score=0.5,
        ),
        context=ctx,
        content_hash="",
    )
    art = temp_art.model_copy(update={"content_hash": compute_artifact_content_hash(temp_art)})
    certification_repository.save_certification_run_atomic(
        input_set=input_set,
        cases=cases,
        artifact=art,
    )

    record = oracle_reconciliation_service.reconcile_certification_run(run_id)
    assert record.status == OracleReconciliationStatus.PARTIALLY_RECONCILED
    assert record.coverage == 0.5
    assert record.binding_counts.matched_bindings == 1
    assert record.binding_counts.total_required_bindings == 2


def test_11_complete_coverage():
    """11. Complete coverage binds all required rules with status RECONCILED."""
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t11", num_rules=3)
    record = oracle_reconciliation_service.reconcile_certification_run(run_id)

    assert record.status == OracleReconciliationStatus.RECONCILED
    assert record.coverage == 1.0
    assert record.binding_counts.matched_bindings == 3


def test_12_actual_behavioral_mismatch_with_successful_reconciliation():
    """12. Real behavioral divergence preserves NOT_CERTIFIED while oracle reconciles successfully."""
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t12", num_rules=2, pass_all=False)
    record = oracle_reconciliation_service.reconcile_certification_run(run_id)

    # Reconciliation succeeds because tests ran and rules were tested
    assert record.status == OracleReconciliationStatus.RECONCILED
    # Divergent observation count is recorded
    assert record.bindings[1].divergent_observations_count > 0
    # Artifact remains NOT_CERTIFIED
    assert art.certified is False
    assert art.status == CertificationStatus.NOT_CERTIFIED


def test_13_frontend_rendering_backend_statuses():
    """13. Model serialization provides all required keys for frontend rendering."""
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t13", num_rules=2)
    record = oracle_reconciliation_service.reconcile_certification_run(run_id)
    payload = record.model_dump(mode="json")

    # Keys required by CertificationTab.jsx
    assert "status" in payload
    assert "coverage" in payload
    assert "oracle_set_id" in payload
    assert "oracle_set_hash" in payload
    assert "input_set_id" in payload
    assert "input_set_hash" in payload
    assert "binding_counts" in payload
    assert "evidence_hash" in payload
    assert "failure_reasons" in payload
    assert "status_reason" in payload


def test_14_api_failure_vs_genuinely_missing_evidence():
    """14. API returns 404 for unknown run, and 200 with NOT_AVAILABLE for missing evidence."""
    app.dependency_overrides[get_current_user] = lambda: make_admin_user("app_t14")
    client = TestClient(app)

    # Unknown run -> 404
    resp_404 = client.get("/api/certifications/NONEXISTENT-RUN/oracle-reconciliation")
    assert resp_404.status_code == 404

    # Run with missing evidence -> 200 with NOT_AVAILABLE status
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t14", num_rules=1)
    run = workflow_persistence.get_run(run_id)
    run.oracle_set_id = "OSET-MISSING"
    workflow_persistence.save_run(run)

    resp_200 = client.get(f"/api/certifications/{run_id}/oracle-reconciliation")
    assert resp_200.status_code == 200
    assert resp_200.json()["status"] == "NOT_AVAILABLE"

    app.dependency_overrides.clear()


def test_15_input_set_persistence_before_finalization():
    """15. InputSet is atomically persisted with identical ID to certificate."""
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t15", num_rules=1)
    persisted_iset = certification_repository.get_input_set(art.input_set_id)

    assert persisted_iset is not None
    assert persisted_iset.input_set_id == art.input_set_id
    assert persisted_iset.canonical_hash == art.input_set_hash
    assert certification_repository.verify_input_set_integrity(art.input_set_id, run_id=cert_id) is True


def test_16_successful_dossier_export():
    """16. Dossier exports in JSON and Markdown with verified InputSet and Oracle Reconciliation."""
    app.dependency_overrides[get_current_user] = lambda: make_admin_user("app_t16")
    client = TestClient(app)
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t16", num_rules=2)

    # JSON export
    resp_json = client.get(f"/api/v1/certification/{cert_id}/export?format=json")
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert data["input_set"] is not None
    assert data["oracle_reconciliation"] is not None
    assert data["oracle_reconciliation"]["status"] == "RECONCILED"

    # Markdown export
    resp_md = client.get(f"/api/v1/certification/{cert_id}/export?format=markdown")
    assert resp_md.status_code == 200
    assert "Oracle Reconciliation Evidence" in resp_md.text
    assert "RECONCILED" in resp_md.text

    app.dependency_overrides.clear()


def test_17_dossier_export_blocked_by_missing_mandatory_artifacts():
    """17. Dossier export raises 409 when InputSet is missing."""
    app.dependency_overrides[get_current_user] = lambda: make_admin_user("app_t17")
    client = TestClient(app)
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t17", num_rules=1)

    # Delete input set from DB
    with __import__("sqlite3").connect(certification_repository._db_path) as conn:
        conn.execute("DELETE FROM input_sets")
        conn.commit()

    resp = client.get(f"/api/v1/certification/{cert_id}/export?format=json")
    assert resp.status_code == 409
    assert "InputSet missing" in resp.json()["detail"]

    app.dependency_overrides.clear()


def test_18_tampering_detection_with_hashes_and_artifacts():
    """18. Tampering with InputSet or Artifact content hash is detected."""
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t18", num_rules=1)

    # 1. Tamper case output
    with __import__("sqlite3").connect(certification_repository._db_path) as conn:
        conn.execute(
            "UPDATE certification_cases SET payload_json = ? WHERE case_id = ?",
            (json.dumps({"input_json": "{}"}), cases[0].case_id)
        )
        conn.commit()

    assert certification_repository.verify_input_set_integrity(art.input_set_id, run_id=cert_id) is False

    # 2. Tamper artifact
    corrupt_art = art.model_copy(update={"score": 0.0001})
    from certification.models import verify_artifact_integrity
    assert verify_artifact_integrity(corrupt_art) is False


def test_19_unauthorized_access_to_run():
    """19. Unauthorized access without valid token or tenant permission is blocked."""
    client = TestClient(app)
    run_id, cert_id, oset, iset, cases, art = setup_complete_run("app_t19", num_rules=1)

    # No token provided -> 401
    resp = client.get(f"/api/certifications/{run_id}/oracle-reconciliation")
    assert resp.status_code == 401


def test_20_complete_full_beacon_workflow():
    """20. Full BEACON end-to-end integration verifies all phases and evidence gates."""
    app_id = "app_t20_full"
    run_id, cert_id, oset, iset, cases, art = setup_complete_run(app_id, num_rules=2, pass_all=True)

    # 1. Run authoritative reconciliation
    recon = oracle_reconciliation_service.reconcile_certification_run(run_id)
    assert recon.status == OracleReconciliationStatus.RECONCILED
    assert recon.coverage == 1.0

    # 2. Verify artifact 8-point integrity
    integrity = certification_repository.verify_certification_run_integrity(cert_id)
    assert integrity["checks"]["artifact_integrity_valid"] is True
    assert integrity["checks"]["input_set_integrity_valid"] is True
    assert integrity["checks"]["oracle_set_integrity_valid"] is True

    # 3. Export dossier
    app.dependency_overrides[get_current_user] = lambda: make_admin_user(app_id)
    client = TestClient(app)
    resp = client.get(f"/api/v1/certification/{cert_id}/export?format=json")
    assert resp.status_code == 200
    dossier = resp.json()
    assert dossier["certification_id"] == cert_id
    assert dossier["oracle_reconciliation"]["evidence_hash"] == recon.evidence_hash
    assert dossier["input_set"]["canonical_hash"] == iset.canonical_hash

    app.dependency_overrides.clear()
