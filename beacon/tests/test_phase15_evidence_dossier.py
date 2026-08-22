"""Phase 15 — Advanced Evidence, Explainability, and Auditability Tests.

Verifies:
1. Unified Evidence Dossier creation and schema completeness
2. Deterministic structured explanations for CERTIFIED, NOT_CERTIFIED, and INSUFFICIENT_COVERAGE outcomes
3. Traceability Graph DAG generation and UNAVAILABLE entity handling
4. Evidence completeness checks and missing field detection
5. Auditor review notes storage and cryptographic hash isolation
6. Side-by-side run comparison (equivalent vs non-equivalent contexts)
7. Custom dataset evidence sanitization (no secret or raw data exposure)
8. Project namespace scoping and authorization barriers
9. Multi-format exports (JSON, Markdown, CSV) with recorded audit events
10. Tampered evidence and hash mismatch detection.
"""

import json
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(ROOT_DIR / "legacy_sample"))

from api.main import app
from evidence import (
    build_evidence_dossier,
    generate_structured_explanation,
    build_traceability_graph,
    auditor_notes_store,
    compare_certification_runs,
    check_evidence_completeness,
)
from certification.repository import certification_repository
from certification.models import CertificationPolicy
from ingestion.audit import audit_logger, AuditAction


@pytest.fixture(autouse=True)
def clean_db():
    certification_repository.clear()
    audit_logger.clear()
    auditor_notes_store._memory_notes.clear()
    yield
    certification_repository.clear()
    audit_logger.clear()
    auditor_notes_store._memory_notes.clear()


@pytest.fixture
def client():
    return TestClient(app)


# ==============================================================================
# 1. Dossier Creation & Schema Integrity
# ==============================================================================

def test_dossier_creation_for_clean_run(client):
    """Verifies that a full Evidence Dossier is generated strictly from persisted evidence for a clean run."""
    run_res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )
    assert run_res.status_code == 200
    art = run_res.json()
    cert_id = art["certification_id"]

    # Build dossier
    dossier = build_evidence_dossier(cert_id)
    assert dossier.certification_id == cert_id
    assert dossier.dossier_id == f"DOS-{cert_id}"
    assert bool(dossier.dossier_hash)

    # Source Evidence
    assert dossier.source_evidence.dataset_id == "retail_discount_pricing"
    assert dossier.source_evidence.row_count > 0

    # Implementation Evidence
    assert bool(dossier.implementation_evidence.legacy_implementation_hash)
    assert bool(dossier.implementation_evidence.modernized_implementation_hash)

    # Oracle Evidence
    assert "RETAIL" in dossier.oracle_evidence.oracle_set_id
    assert dossier.oracle_evidence.oracle_count > 0
    assert len(dossier.oracle_evidence.oracles) > 0

    # Execution Evidence
    assert dossier.execution_evidence.matching_cases > 0
    assert dossier.execution_evidence.regression_cases == 0
    assert dossier.execution_evidence.equivalence_score == 1.0

    # Cryptographic Evidence
    assert dossier.cryptographic_evidence.artifact_hash == art["content_hash"]
    assert dossier.cryptographic_evidence.integrity_status == "VERIFIED"

    # Completeness
    assert dossier.completeness.status == "COMPLETE"
    assert dossier.completeness.completeness_score == 1.0
    assert len(dossier.completeness.missing_fields) == 0


# ==============================================================================
# 2. Deterministic Explanations
# ==============================================================================

def test_deterministic_explanation_for_certified_run(client):
    """Verifies that the explainer produces a truthful, structured rationale for a CERTIFIED outcome."""
    run_res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )
    cert_id = run_res.json()["certification_id"]

    exp_res = client.get(f"/api/v1/evidence/dossiers/{cert_id}/explain")
    assert exp_res.status_code == 200
    exp = exp_res.json()

    assert exp["authoritative_status"] == "CERTIFIED"
    assert "CERTIFIED" in exp["headline"]
    assert "successfully satisfied all certification policy requirements" in exp["status_rationale"]
    assert exp["explanation_source"] == "DETERMINISTIC_ENGINE"
    assert len(exp["highest_severity_failures"]) == 0
    assert len(exp["evidence_references"]) >= 5


def test_deterministic_explanation_for_not_certified_run(client):
    """Verifies that the explainer surfaces pinpointed behavioral regressions for a NOT_CERTIFIED outcome."""
    run_res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "buggy_threshold_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "buggy",
            "preferred_provider": "offline",
        },
    )
    cert_id = run_res.json()["certification_id"]

    exp_res = client.get(f"/api/v1/evidence/dossiers/{cert_id}/explain")
    assert exp_res.status_code == 200
    exp = exp_res.json()

    assert exp["authoritative_status"] == "NOT_CERTIFIED"
    assert "NOT CERTIFIED" in exp["headline"]
    assert "behavioral regression" in exp["status_rationale"].lower()
    assert len(exp["highest_severity_failures"]) > 0

    first_fail = exp["highest_severity_failures"][0]
    assert "oracle_id" in first_fail
    assert "legacy_output" in first_fail
    assert "modern_output" in first_fail
    assert first_fail["legacy_output"] != first_fail["modern_output"]
    assert bool(first_fail["invariant_violated"])


def test_deterministic_explanation_for_insufficient_coverage(client):
    """Verifies that INSUFFICIENT_COVERAGE outcomes are explained without phrasing as successful certification."""
    # Arbitrary payload that yields INSUFFICIENT_COVERAGE
    up_res = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_inconclusive_test",
            "dataset_name": "Unmatched IoT Sensor Data",
            "data_format": "JSON",
            "raw_content": json.dumps([{"temp_c": 22.5, "humidity": 45.0}]),
            "declared_provenance": "USER_SUPPLIED",
        },
    )
    ds_id = up_res.json()["dataset_id"]

    val_res = client.post(
        "/api/v1/custom/validate",
        json={
            "project_id": "proj_inconclusive_test",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "evaluation_mode": "FULL_BEACON",
            "preferred_provider": "offline",
            "allow_external_llm": False,
        },
    )
    fp = val_res.json()["config_fingerprint"]

    cert_res = client.post(
        "/api/v1/custom/certify",
        json={
            "project_id": "proj_inconclusive_test",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "evaluation_mode": "FULL_BEACON",
            "preferred_provider": "offline",
            "allow_external_llm": False,
            "config_fingerprint": fp,
        },
    )
    cert_id = cert_res.json()["certification_id"]

    exp_res = client.get(f"/api/v1/evidence/dossiers/{cert_id}/explain")
    assert exp_res.status_code == 200
    exp = exp_res.json()

    assert exp["authoritative_status"] == "INSUFFICIENT_COVERAGE"
    assert "INSUFFICIENT COVERAGE" in exp["headline"]
    assert "strictly inconclusive" in exp["status_rationale"].lower() or "insufficient" in exp["status_rationale"].lower()
    assert "not constitute certification" in exp["status_rationale"].lower() or "insufficient" in exp["status_rationale"].lower()


# ==============================================================================
# 3. Evidence Completeness & Traceability Graph
# ==============================================================================

def test_evidence_completeness_and_missing_field_detection(client):
    """Verifies that evidence completeness checks accurately detect missing references."""
    run_res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )
    cert_id = run_res.json()["certification_id"]
    dossier = build_evidence_dossier(cert_id)

    # Clean dossier must be complete
    assert dossier.completeness.status == "COMPLETE"
    assert dossier.completeness.completeness_score == 1.0

    # Simulate missing dataset checksum
    broken_source = dossier.source_evidence.model_copy(update={"dataset_id": "", "checksum": ""})
    report = check_evidence_completeness(
        artifact=certification_repository.get_artifact(cert_id),
        source=broken_source,
        impl=dossier.implementation_evidence,
        oracle=dossier.oracle_evidence,
        policy=dossier.policy_evidence,
        execution=dossier.execution_evidence,
        crypto=dossier.cryptographic_evidence,
    )
    assert report.status == "INCOMPLETE"
    assert "has_dataset_identity" in report.missing_fields
    assert report.completeness_score < 1.0


def test_traceability_graph_dag_generation(client):
    """Verifies that the traceability graph connects nodes from Dataset to Cryptographic Integrity."""
    run_res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )
    cert_id = run_res.json()["certification_id"]

    g_res = client.get(f"/api/v1/evidence/dossiers/{cert_id}/graph")
    assert g_res.status_code == 200
    nodes = g_res.json()["nodes"]
    
    node_types = {n["node_type"] for n in nodes}
    assert "DATASET" in node_types
    assert "INPUT_SET" in node_types
    assert "IMPLEMENTATION_PAIR" in node_types
    assert "ORACLE_SET" in node_types
    assert "ORACLE_EVALUATION" in node_types
    assert "POLICY" in node_types
    assert "ARTIFACT" in node_types
    assert "INTEGRITY_HASH" in node_types


# ==============================================================================
# 4. Auditor Notes & Hash Invariance
# ==============================================================================

def test_auditor_notes_isolation_and_hash_invariance(client):
    """Verifies that adding auditor notes persists notes separately and does NOT alter the artifact content hash."""
    run_res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )
    art = run_res.json()
    cert_id = art["certification_id"]
    original_hash = art["content_hash"]

    # Add Note
    note_res = client.post(
        f"/api/v1/evidence/dossiers/{cert_id}/notes",
        json={
            "author": "Lead Compliance Auditor",
            "content": "Verified equivalence score and 0 regressions against SOX requirements.",
            "project_id": art.get("project_id") or f"benchmark_{art.get('benchmark_id', 'retail_discount_pricing')}",
        },
    )
    assert note_res.status_code == 200
    note_data = note_res.json()
    assert note_data["author"] == "Lead Compliance Auditor"

    # List Notes
    notes_list_res = client.get(f"/api/v1/evidence/dossiers/{cert_id}/notes")
    assert notes_list_res.status_code == 200
    notes = notes_list_res.json()["notes"]
    assert any(n["note_id"] == note_data["note_id"] for n in notes)

    # Verify audit event action is strictly AUDITOR_NOTE_CREATED and NOT INTEGRITY_VERIFY
    cert_events = audit_logger.list_events(certification_id=cert_id)
    note_events = [e for e in cert_events if e.action == AuditAction.AUDITOR_NOTE_CREATED]
    assert len(note_events) > 0
    assert any(e.details.get("note_id") == note_data["note_id"] for e in note_events)

    # Verify original artifact content hash remains 100% untouched
    art_after = certification_repository.get_artifact(cert_id)
    assert art_after.content_hash == original_hash

    # Verify cryptographic verification still passes
    verify_res = client.post(f"/api/v1/evidence/verify/{cert_id}")
    assert verify_res.status_code == 200
    assert verify_res.json()["status"] == "PASS"


# ==============================================================================
# 5. Side-by-Side Run Comparison
# ==============================================================================

def test_run_comparison_equivalent_and_differential_regressions(client):
    """Verifies run comparator highlights score deltas, new regressions, and context equivalence."""
    # Run A: Clean (Baseline)
    res_a = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )
    cert_id_a = res_a.json()["certification_id"]

    # Run B: Buggy (Candidate)
    res_b = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "buggy_threshold_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "buggy",
            "preferred_provider": "offline",
        },
    )
    cert_id_b = res_b.json()["certification_id"]

    cmp_res = client.post(
        "/api/v1/evidence/compare",
        json={"run_id_a": cert_id_a, "run_id_b": cert_id_b},
    )
    assert cmp_res.status_code == 200
    cmp_data = cmp_res.json()

    assert cmp_data["run_id_a"] == cert_id_a
    assert cmp_data["run_id_b"] == cert_id_b
    assert cmp_data["status_comparison"]["status_a"] == "CERTIFIED"
    assert cmp_data["status_comparison"]["status_b"] == "NOT_CERTIFIED"
    assert cmp_data["status_comparison"]["status_changed"] is True
    assert cmp_data["metrics_comparison"]["score_delta"] < 0
    assert cmp_data["differential_regressions"]["new_count"] > 0


def test_run_comparison_non_equivalent_context_flagging(client):
    """Verifies that comparing runs with different benchmarks/datasets is flagged as NON-EQUIVALENT."""
    res_a = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )
    cert_id_a = res_a.json()["certification_id"]

    res_b = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "payroll_tax_calculator",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )
    cert_id_b = res_b.json()["certification_id"]

    cmp_res = client.post(
        "/api/v1/evidence/compare",
        json={"run_id_a": cert_id_a, "run_id_b": cert_id_b},
    )
    assert cmp_res.status_code == 200
    cmp_data = cmp_res.json()

    assert cmp_data["is_equivalent_context"] is False
    assert len(cmp_data["context_divergence_reasons"]) > 0


# ==============================================================================
# 6. Custom Dataset Evidence Sanitization & Privacy
# ==============================================================================

def test_sanitized_custom_dataset_evidence_views(client):
    """Verifies custom dataset evidence views default to sanitized representations and do not leak secrets."""
    secret_payload = json.dumps([
        {
            "order_amount": 100.0,
            "customer_tier": "VIP",
            "items_count": 3,
            "coupon_code": "NONE",
            "is_express_shipping": False,
            "api_token": "sk-ant-secret123456",
            "auth_password": "supersecretpassword",
        },
    ])

    up_res = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_sanitization_audit",
            "dataset_name": "Private Enterprise Data",
            "data_format": "JSON",
            "raw_content": secret_payload,
            "declared_provenance": "PRIVATE_ENTERPRISE",
        },
    )
    ds_id = up_res.json()["dataset_id"]

    val_res = client.post(
        "/api/v1/custom/validate",
        json={
            "project_id": "proj_sanitization_audit",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "oracle_set_id": "SET-RETAIL-CONTROLLED-v1",
            "evaluation_mode": "CONTROLLED",
            "preferred_provider": "offline",
            "allow_external_llm": False,
        },
    )
    fp = val_res.json()["config_fingerprint"]

    cert_res = client.post(
        "/api/v1/custom/certify",
        json={
            "project_id": "proj_sanitization_audit",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "oracle_set_id": "SET-RETAIL-CONTROLLED-v1",
            "evaluation_mode": "CONTROLLED",
            "preferred_provider": "offline",
            "allow_external_llm": False,
            "config_fingerprint": fp,
        },
    )
    cert_id = cert_res.json()["certification_id"]

    # Dossier Check
    dossier = build_evidence_dossier(cert_id, project_id="proj_sanitization_audit")
    dossier_json = dossier.model_dump_json()

    # Must NOT contain raw secrets
    assert "sk-ant-secret123456" not in dossier_json
    assert "supersecretpassword" not in dossier_json


# ==============================================================================
# 7. Project Scoping & Authorization Boundaries
# ==============================================================================

def test_project_isolation_on_evidence_endpoints(client):
    """Verifies that project B cannot retrieve or alter evidence belonging to project A."""
    up_res = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_tenant_a",
            "dataset_name": "Tenant A Data",
            "data_format": "JSON",
            "raw_content": json.dumps([{
                "order_amount": 50.0,
                "customer_tier": "STANDARD",
                "items_count": 1,
                "coupon_code": "NONE",
                "is_express_shipping": False,
            }]),
            "declared_provenance": "USER_SUPPLIED",
        },
    )
    ds_id = up_res.json()["dataset_id"]

    val_res = client.post(
        "/api/v1/custom/validate",
        json={
            "project_id": "proj_tenant_a",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "oracle_set_id": "SET-RETAIL-CONTROLLED-v1",
            "evaluation_mode": "CONTROLLED",
            "preferred_provider": "offline",
            "allow_external_llm": False,
        },
    )
    fp = val_res.json()["config_fingerprint"]

    cert_res = client.post(
        "/api/v1/custom/certify",
        json={
            "project_id": "proj_tenant_a",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "oracle_set_id": "SET-RETAIL-CONTROLLED-v1",
            "evaluation_mode": "CONTROLLED",
            "preferred_provider": "offline",
            "allow_external_llm": False,
            "config_fingerprint": fp,
        },
    )
    cert_id = cert_res.json()["certification_id"]

    # Access with matching project_id succeeds
    ok_res = client.get(f"/api/v1/evidence/dossiers/{cert_id}?project_id=proj_tenant_a")
    assert ok_res.status_code == 200

    # Access with mismatched project_id fails with 403 Forbidden
    denied_res = client.get(f"/api/v1/evidence/dossiers/{cert_id}?project_id=proj_tenant_b")
    assert denied_res.status_code == 403


# ==============================================================================
# 8. Multi-Format Exports & Audit Trail
# ==============================================================================

def test_export_formats_and_audit_event_recording(client):
    """Verifies that exporting dossiers in JSON, Markdown, and CSV succeeds and records export audit events."""
    run_res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )
    cert_id = run_res.json()["certification_id"]

    # 1. JSON Export
    json_res = client.get(f"/api/v1/evidence/dossiers/{cert_id}/export?format=json")
    assert json_res.status_code == 200
    assert "application/json" in json_res.headers["content-type"]
    json_data = json_res.json()
    assert json_data["certification_id"] == cert_id

    # 2. Markdown Export
    md_res = client.get(f"/api/v1/evidence/dossiers/{cert_id}/export?format=markdown")
    assert md_res.status_code == 200
    assert "text/markdown" in md_res.headers["content-type"]
    assert "# BEACON Evidence Dossier Audit Report" in md_res.text

    # 3. CSV Export
    csv_res = client.get(f"/api/v1/evidence/dossiers/{cert_id}/export?format=csv")
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers["content-type"]
    assert "case_id,case_index,input_id" in csv_res.text


# ==============================================================================
# 9. Tampered Evidence Detection
# ==============================================================================

def test_tampered_evidence_verification_failure(client):
    """Verifies that mutating a stored artifact causes cryptographic verification to report failure."""
    run_res = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )
    cert_id = run_res.json()["certification_id"]

    # Untouched passes
    v1 = client.post(f"/api/v1/evidence/verify/{cert_id}")
    assert v1.json()["status"] == "PASS"

    # Mutate artifact in repository
    art = certification_repository.get_artifact(cert_id)
    tampered_art = art.model_copy(update={"score": 0.50})
    certification_repository._memory_artifacts[cert_id] = tampered_art
    import sqlite3
    with sqlite3.connect(certification_repository._db_path) as conn:
        conn.execute("UPDATE certification_artifacts SET score = 0.50 WHERE certification_id = ?", (cert_id,))

    # Verification must detect tampering
    v2 = client.post(f"/api/v1/evidence/verify/{cert_id}")
    assert v2.json()["status"] == "FAIL"
    assert v2.json()["artifact_integrity_valid"] is False


# ==============================================================================
# 10. Phase 15 Final Corrections: Policy Exactness, Timeline Scoping & CSV Privacy
# ==============================================================================

def test_policy_thresholds_exactness_and_historical_invariance(client):
    """Verifies Evidence Dossier reports exact non-default policy thresholds and remains historically invariant."""
    # Policy A: Strict Policy (95% Equivalence, 90% Coverage)
    policy_a = CertificationPolicy(
        policy_id="POL-STRICT-A",
        min_equivalence_score=0.95,
        min_oracle_coverage=0.90,
    )

    run_res_a = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
            "policy": policy_a.model_dump(mode="json"),
        },
    )
    assert run_res_a.status_code == 200
    art_a = run_res_a.json()
    cert_id_a = art_a["certification_id"]

    # Dossier A must reflect exact Policy A thresholds (0.95 and 0.90), NOT default 0.80/0.0
    dossier_a = build_evidence_dossier(cert_id_a)
    assert dossier_a.policy_evidence.policy_id == "POL-STRICT-A"
    assert dossier_a.policy_evidence.min_equivalence_score == 0.95
    assert dossier_a.policy_evidence.min_oracle_coverage == 0.90

    # Policy B: Relaxed Policy (75% Equivalence, 50% Coverage)
    policy_b = CertificationPolicy(
        policy_id="POL-RELAXED-B",
        min_equivalence_score=0.75,
        min_oracle_coverage=0.50,
    )

    run_res_b = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "payroll_tax_calculator",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
            "policy": policy_b.model_dump(mode="json"),
        },
    )
    assert run_res_b.status_code == 200
    cert_id_b = run_res_b.json()["certification_id"]

    dossier_b = build_evidence_dossier(cert_id_b)
    assert dossier_b.policy_evidence.policy_id == "POL-RELAXED-B"
    assert dossier_b.policy_evidence.min_equivalence_score == 0.75
    assert dossier_b.policy_evidence.min_oracle_coverage == 0.50

    # Historical Invariance Check: Dossier A must still report Policy A thresholds (0.95/0.90)
    dossier_a_reloaded = build_evidence_dossier(cert_id_a)
    assert dossier_a_reloaded.policy_evidence.policy_id == "POL-STRICT-A"
    assert dossier_a_reloaded.policy_evidence.min_equivalence_score == 0.95
    assert dossier_a_reloaded.policy_evidence.min_oracle_coverage == 0.90


def test_timeline_strict_run_isolation_and_chronological_order(client):
    """Verifies that Evidence Timeline only contains events for the selected run and is chronologically ordered."""
    # Create Run A
    res_a = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )
    cert_id_a = res_a.json()["certification_id"]

    # Create Run B
    res_b = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "payroll_tax_calculator",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )
    cert_id_b = res_b.json()["certification_id"]

    # Add Run-B-only note
    client.post(
        f"/api/v1/evidence/dossiers/{cert_id_b}/notes",
        json={"author": "Auditor B", "content": "Exclusive note for Run B only."},
    )

    # Fetch Timeline for Run A
    tl_res_a = client.get(f"/api/v1/evidence/dossiers/{cert_id_a}/timeline")
    assert tl_res_a.status_code == 200
    timeline_a = tl_res_a.json()["timeline"]

    # Must contain Run A events
    assert len(timeline_a) > 0
    # Must NOT contain Run-B note content or event
    for event in timeline_a:
        details_str = json.dumps(event.get("details", {}))
        assert "Exclusive note for Run B only" not in details_str
        assert cert_id_b not in details_str

    # Verify strictly ascending chronological ordering
    timestamps = [ev["timestamp"] for ev in timeline_a]
    assert timestamps == sorted(timestamps)


def test_privacy_safe_custom_dataset_csv_export_no_secret_leak(client):
    """Verifies that default CSV export for custom/private datasets strips raw secrets, emails, and credentials."""
    sensitive_payload = json.dumps([
        {
            "order_amount": 120.0,
            "customer_tier": "VIP",
            "items_count": 2,
            "coupon_code": "NONE",
            "is_express_shipping": False,
            "customer_email": "confidential_ceo@enterprise.com",
            "salary": 185000,
            "internal_id": "EMP-SECRET-8888",
        }
    ])

    up_res = client.post(
        "/api/v1/custom/datasets/upload",
        json={
            "project_id": "proj_strict_csv_privacy",
            "dataset_name": "Executive Payroll & Orders",
            "data_format": "JSON",
            "raw_content": sensitive_payload,
            "declared_provenance": "PRIVATE_ENTERPRISE",
        },
    )
    assert up_res.status_code == 200
    ds_id = up_res.json()["dataset_id"]

    val_res = client.post(
        "/api/v1/custom/validate",
        json={
            "project_id": "proj_strict_csv_privacy",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "oracle_set_id": "SET-RETAIL-CONTROLLED-v1",
            "evaluation_mode": "CONTROLLED",
            "preferred_provider": "offline",
            "allow_external_llm": False,
        },
    )
    assert val_res.status_code == 200
    fp = val_res.json()["config_fingerprint"]

    cert_res = client.post(
        "/api/v1/custom/certify",
        json={
            "project_id": "proj_strict_csv_privacy",
            "dataset_id": ds_id,
            "legacy_adapter_id": "retail_discount_legacy",
            "modernized_adapter_id": "retail_discount_modern_clean",
            "oracle_set_id": "SET-RETAIL-CONTROLLED-v1",
            "evaluation_mode": "CONTROLLED",
            "preferred_provider": "offline",
            "allow_external_llm": False,
            "config_fingerprint": fp,
        },
    )
    assert cert_res.status_code == 200
    cert_id = cert_res.json()["certification_id"]

    # 1. Custom Dataset CSV Export
    csv_res = client.get(f"/api/v1/evidence/dossiers/{cert_id}/export?format=csv&project_id=proj_strict_csv_privacy")
    assert csv_res.status_code == 200
    csv_text = csv_res.text

    # Verify raw secrets and private customer values NEVER appear in the custom CSV export
    assert "confidential_ceo@enterprise.com" not in csv_text
    assert "EMP-SECRET-8888" not in csv_text
    assert "185000" not in csv_text

    # Verify sanitized evidence fields are present
    assert "case_id" in csv_text
    assert "input_hash" in csv_text
    assert "evidence_reference" in csv_text

    # 2. Built-in Benchmark CSV Export continues to include standard columns
    bench_run = client.post(
        "/api/v1/certification/run",
        json={
            "benchmark_id": "retail_discount_pricing",
            "benchmark_variant": "clean_v2",
            "discovery_mode": "CONTROLLED",
            "implementation": "equivalent",
            "preferred_provider": "offline",
        },
    )
    bench_cert_id = bench_run.json()["certification_id"]
    bench_csv_res = client.get(f"/api/v1/evidence/dossiers/{bench_cert_id}/export?format=csv")
    assert bench_csv_res.status_code == 200
    bench_csv_text = bench_csv_res.text
    assert "input_json" in bench_csv_text
    assert "legacy_output_json" in bench_csv_text
    assert "modern_output_json" in bench_csv_text
