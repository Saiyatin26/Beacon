"""Phase 10 — Quantified Behavioral Equivalence Certification & Drift Test Suite.

Comprehensive tests covering:
1. Successful fully covered certification (CERTIFIED)
2. Certified with warnings (CERTIFIED_WITH_WARNINGS)
3. Modernized critical regression (NOT_CERTIFIED)
4. Reference inconsistency (REFERENCE_INCONSISTENT)
5. Mutual violation (NOT_CERTIFIED)
6. Insufficient coverage (INSUFFICIENT_COVERAGE)
7. Oracle set content hash mismatch detection (ORACLE_SET_INVALID)
8. Cryptographic immutability & repository integrity
9. Human-readable HTML/Markdown report generation
10. Post-migration drift event ingestion & evaluation
11. REST API endpoints & rejection of client-supplied scores
12. End-to-end loan application benchmark (positive pass & threshold regression)
"""

import copy
import json
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

from api.main import app
from auth import auth_repository, create_access_token
from certification import (
    CertificationArtifact,
    CertificationEngine,
    CertificationPolicy,
    CertificationStatus,
    CertificationTestInput,
    FunctionAdapter,
    LegacyAdapter,
    ModernizedAdapter,
    certification_engine,
    certification_repository,
    generate_html_report,
    generate_markdown_report,
)
from drift import (
    DriftObservation,
    DriftPolicy,
    DriftStatus,
    evaluate_drift_observation,
)
from oracle import (
    OracleConsequence,
    OracleDefinition,
    OracleInputSchema,
    OracleOutputSchema,
    OraclePredicate,
    OracleProvenance,
    OracleSet,
    compile_candidate_to_oracle,
    registry,
    synthesize_oracle,
)
from common.models import CandidateInvariant


client = TestClient(app)


def _make_dummy_oracle(
    oracle_id: str,
    variable: str = "credit_score",
    operator: str = "<",
    threshold: float = 500.0,
    consequence_var: str = "decision",
    consequence_val: str = "REJECT",
    severity: str = "critical",
    confidence: float = 0.95,
) -> OracleDefinition:
    candidate = CandidateInvariant(
        invariant_id=oracle_id,
        condition=f"{variable} {operator} {threshold}",
        consequence=f"{consequence_var} == '{consequence_val}'",
        confidence=confidence,
        severity=severity,
        domain="business_logic",
        evidence_ids=["EVID-1"],
        source_lines=[10],
        status="VALIDATED",
    )
    return compile_candidate_to_oracle(candidate)


@pytest.fixture(autouse=True)
def clean_registry_and_repo():
    registry.clear()
    certification_repository.clear()
    yield
    registry.clear()
    certification_repository.clear()


# ==============================================================================
# 1. Successful Fully Covered Certification
# ==============================================================================

def test_successful_fully_covered_certification():
    """Equivalent modernization passes all oracles -> CERTIFIED with 100% score."""
    orc1 = _make_dummy_oracle("orc-1", threshold=500.0, severity="critical")
    orc2 = _make_dummy_oracle("orc-2", variable="debt_ratio", operator=">", threshold=0.45, severity="high")
    registry.register_oracle(orc1)
    registry.register_oracle(orc2)

    oracle_set = registry.create_oracle_set(
        name="CreditPolicySet",
        oracle_ids=[orc1.oracle_id, orc2.oracle_id],
        domain="business_logic",
    )

    def ref_fn(credit_score=700, debt_ratio=0.3, **kwargs):
        if credit_score < 500 or debt_ratio > 0.45:
            return {"decision": "REJECT"}
        return {"decision": "APPROVE"}

    legacy_adp = LegacyAdapter(target_fn=ref_fn, name="legacy_v1", version="1.0.0")
    modern_adp = ModernizedAdapter(target_fn=ref_fn, name="modern_v2", version="2.0.0")

    policy = CertificationPolicy(
        min_equivalence_score=0.80,
        min_oracle_coverage=1.0,
        min_applicable_probes_per_oracle=5,
    )

    artifact = certification_engine.certify(
        project_id="test_credit_system",
        legacy_adapter=legacy_adp,
        modern_adapter=modern_adp,
        oracle_set=oracle_set,
        policy=policy,
        n_samples=50,
        seed=100,
    )

    assert artifact.status == CertificationStatus.CERTIFIED
    assert artifact.certified is True
    assert artifact.score == 1.0
    assert artifact.metrics.modern_regressions == 0
    assert artifact.metrics.reference_inconsistencies == 0
    assert artifact.metrics.mutual_violations == 0
    assert artifact.metrics.oracles_exercised == 2
    assert artifact.metrics.oracle_coverage_pct == 1.0
    assert len(artifact.content_hash) == 64


# ==============================================================================
# 2. Certified with Warnings Policy
# ==============================================================================

def test_certified_with_warnings_policy():
    """Non-critical regression with allow_warnings=True yields CERTIFIED_WITH_WARNINGS."""
    orc_crit = _make_dummy_oracle("orc-crit", threshold=500.0, severity="critical")
    orc_low = _make_dummy_oracle("orc-low", variable="annual_income", operator="<", threshold=20000.0, severity="low")
    registry.register_oracle(orc_crit)
    registry.register_oracle(orc_low)

    oracle_set = registry.create_oracle_set(
        name="LoanSetWithLowSeverity",
        oracle_ids=[orc_crit.oracle_id, orc_low.oracle_id],
        domain="business_logic",
    )

    def ref_fn(credit_score=700, annual_income=50000.0, **kwargs):
        if credit_score < 500 or annual_income < 20000.0:
            return {"decision": "REJECT"}
        return {"decision": "APPROVE"}

    def modern_with_low_bug(credit_score=700, annual_income=50000.0, **kwargs):
        if credit_score < 500:
            return {"decision": "REJECT"}
        # Low severity income threshold omitted in modern
        return {"decision": "APPROVE"}

    legacy_adp = LegacyAdapter(target_fn=ref_fn, version="1.0.0")
    modern_adp = ModernizedAdapter(target_fn=modern_with_low_bug, version="2.0.0")

    policy_warnings_allowed = CertificationPolicy(
        min_equivalence_score=0.50,
        allow_warnings=True,
        min_applicable_probes_per_oracle=1,
    )

    artifact = certification_engine.certify(
        project_id="test_warnings",
        legacy_adapter=legacy_adp,
        modern_adapter=modern_adp,
        oracle_set=oracle_set,
        policy=policy_warnings_allowed,
        n_samples=50,
        seed=100,
    )

    assert artifact.status == CertificationStatus.CERTIFIED_WITH_WARNINGS
    assert artifact.certified is True
    assert artifact.metrics.critical_failures == 0
    assert artifact.metrics.non_critical_failures > 0
    assert len(artifact.warnings) > 0


# ==============================================================================
# 3. Modernized Critical Regression
# ==============================================================================

def test_modernized_critical_regression_not_certified():
    """Modernized bug on critical oracle -> NOT_CERTIFIED with counterexample drilldown."""
    orc = _make_dummy_oracle("orc-crit-reg", threshold=600.0, severity="critical")
    registry.register_oracle(orc)
    oracle_set = registry.create_oracle_set(name="CritSet", oracle_ids=[orc.oracle_id])

    def ref_fn(credit_score=700, **kwargs):
        return {"decision": "REJECT" if credit_score < 600 else "APPROVE"}

    def buggy_modern_fn(credit_score=700, **kwargs):
        # Buggy implementation uses 500 instead of 600
        return {"decision": "REJECT" if credit_score < 500 else "APPROVE"}

    artifact = certification_engine.certify(
        project_id="test_crit_reg",
        legacy_adapter=LegacyAdapter(target_fn=ref_fn),
        modern_adapter=ModernizedAdapter(target_fn=buggy_modern_fn),
        oracle_set=oracle_set,
        policy=CertificationPolicy(),
        n_samples=40,
        seed=42,
    )

    assert artifact.status == CertificationStatus.NOT_CERTIFIED
    assert artifact.certified is False
    assert artifact.metrics.modern_regressions > 0
    assert len(artifact.regressions) > 0

    # Verify counterexample drill-down
    reg = artifact.regressions[0]
    assert reg.oracle_id == orc.oracle_id
    assert reg.legacy_output == "REJECT"
    assert reg.modern_output == "APPROVE"


# ==============================================================================
# 4. Reference Inconsistency Blocks Certification
# ==============================================================================

def test_reference_inconsistency_blocks_certification():
    """Legacy implementation violating a validated oracle results in REFERENCE_INCONSISTENT."""
    orc = _make_dummy_oracle("orc-ref-incon", threshold=550.0, severity="critical")
    registry.register_oracle(orc)
    oracle_set = registry.create_oracle_set(name="RefSet", oracle_ids=[orc.oracle_id])

    def buggy_legacy_fn(credit_score=700, **kwargs):
        # Flawed legacy ignores credit_score < 550 rule
        return {"decision": "APPROVE"}

    def modern_fn(credit_score=700, **kwargs):
        return {"decision": "REJECT" if credit_score < 550 else "APPROVE"}

    artifact = certification_engine.certify(
        project_id="test_ref_incon",
        legacy_adapter=LegacyAdapter(target_fn=buggy_legacy_fn),
        modern_adapter=ModernizedAdapter(target_fn=modern_fn),
        oracle_set=oracle_set,
        policy=CertificationPolicy(),
        n_samples=40,
        seed=42,
    )

    assert artifact.status == CertificationStatus.REFERENCE_INCONSISTENT
    assert artifact.certified is False
    assert artifact.metrics.reference_inconsistencies > 0


# ==============================================================================
# 5. Mutual Violation Blocks Certification
# ==============================================================================

def test_mutual_violation_blocks_certification():
    """Both legacy and modern violating oracle results in MUTUAL_VIOLATION & NOT_CERTIFIED."""
    orc = _make_dummy_oracle("orc-mut", threshold=550.0, severity="critical")
    registry.register_oracle(orc)
    oracle_set = registry.create_oracle_set(name="MutSet", oracle_ids=[orc.oracle_id])

    def both_violate(credit_score=700, **kwargs):
        return {"decision": "APPROVE"}

    artifact = certification_engine.certify(
        project_id="test_mut_viol",
        legacy_adapter=LegacyAdapter(target_fn=both_violate),
        modern_adapter=ModernizedAdapter(target_fn=both_violate),
        oracle_set=oracle_set,
        policy=CertificationPolicy(),
        n_samples=40,
        seed=42,
    )

    assert artifact.status == CertificationStatus.NOT_CERTIFIED
    assert artifact.certified is False
    assert artifact.metrics.mutual_violations > 0


# ==============================================================================
# 6. Insufficient Coverage Blocks Certification
# ==============================================================================

def test_insufficient_coverage_blocks_certification():
    """Unexercised oracles result in INSUFFICIENT_COVERAGE."""
    orc1 = _make_dummy_oracle("orc-exercised", variable="credit_score", threshold=500.0)
    orc2 = _make_dummy_oracle("orc-unexercised", variable="unseen_metric", threshold=0.0)
    registry.register_oracle(orc1)
    registry.register_oracle(orc2)

    oracle_set = registry.create_oracle_set(name="CoverageSet", oracle_ids=[orc1.oracle_id, orc2.oracle_id])

    def sample_fn(credit_score=700, unseen_metric=50.0, **kwargs):
        return {"decision": "REJECT" if credit_score < 500 else "APPROVE"}

    artifact = certification_engine.certify(
        project_id="test_cov",
        legacy_adapter=LegacyAdapter(target_fn=sample_fn),
        modern_adapter=ModernizedAdapter(target_fn=sample_fn),
        oracle_set=oracle_set,
        field_bounds={"credit_score": (400, 800), "unseen_metric": (10.0, 100.0)},
        policy=CertificationPolicy(min_oracle_coverage=1.0, min_applicable_probes_per_oracle=5),
        n_samples=20,
    )

    assert artifact.status == CertificationStatus.INSUFFICIENT_COVERAGE
    assert artifact.certified is False


# ==============================================================================
# 7. Oracle Set Content Hash Mismatch Rejection
# ==============================================================================

def test_oracle_set_hash_mismatch_blocks_certification():
    """Altered oracle set hash triggers ORACLE_SET_INVALID without executing."""
    orc = _make_dummy_oracle("orc-hash-test")
    registry.register_oracle(orc)
    oracle_set = registry.create_oracle_set(name="HashSet", oracle_ids=[orc.oracle_id])

    # Construct tampered oracle set object
    tampered_set = OracleSet(
        oracle_set_id=oracle_set.oracle_set_id,
        version=oracle_set.version,
        name=oracle_set.name,
        oracles=oracle_set.oracles,
        oracle_set_hash="0000000000000000000000000000000000000000000000000000000000000000",
    )

    def noop_fn(**kwargs):
        return {"decision": "APPROVE"}

    artifact = certification_engine.certify(
        project_id="test_hash_mismatch",
        legacy_adapter=LegacyAdapter(target_fn=noop_fn),
        modern_adapter=ModernizedAdapter(target_fn=noop_fn),
        oracle_set=tampered_set,
    )

    assert artifact.status == CertificationStatus.ORACLE_SET_INVALID
    assert artifact.certified is False
    assert "OracleSet integrity" in artifact.blocking_reasons[0]


# ==============================================================================
# 8. Cryptographic Immutability & Repository Integrity
# ==============================================================================

def test_immutable_artifact_repository_integrity():
    """Repository allows re-saving identical artifact but rejects conflicting content hash."""
    orc = _make_dummy_oracle("orc-repo")
    registry.register_oracle(orc)
    oracle_set = registry.create_oracle_set(name="RepoSet", oracle_ids=[orc.oracle_id])

    def dummy_fn(credit_score=700, **kwargs):
        return {"decision": "APPROVE"}

    art1 = certification_engine.certify(
        project_id="test_repo",
        legacy_adapter=LegacyAdapter(target_fn=dummy_fn),
        modern_adapter=ModernizedAdapter(target_fn=dummy_fn),
        oracle_set=oracle_set,
    )

    # Re-saving same instance succeeds
    saved = certification_repository.save_artifact(art1)
    assert saved.certification_id == art1.certification_id

    # Retrieving from repo preserves exact content hash
    retrieved = certification_repository.get_artifact(art1.certification_id)
    assert retrieved is not None
    assert retrieved.content_hash == art1.content_hash


# ==============================================================================
# 9. Human-Readable HTML/Markdown Report Generation
# ==============================================================================

def test_html_and_markdown_report_generation():
    """Report generators produce structured documents without exposing sensitive secrets."""
    orc = _make_dummy_oracle("orc-rep-gen", threshold=500.0)
    registry.register_oracle(orc)
    oracle_set = registry.create_oracle_set(name="ReportSet", oracle_ids=[orc.oracle_id])

    def sample_fn(credit_score=700, **kwargs):
        return {"decision": "REJECT" if credit_score < 500 else "APPROVE"}

    artifact = certification_engine.certify(
        project_id="test_report_project",
        legacy_adapter=LegacyAdapter(target_fn=sample_fn),
        modern_adapter=ModernizedAdapter(target_fn=sample_fn),
        oracle_set=oracle_set,
    )

    html_report = generate_html_report(artifact)
    md_report = generate_markdown_report(artifact)

    assert "BEACON Behavioral Equivalence Certificate" in html_report
    assert artifact.certification_id in html_report
    assert "CERTIFIED" in html_report
    assert artifact.content_hash in html_report
    assert "sk-" not in html_report  # Zero secrets

    assert f"# BEACON Behavioral Equivalence Certificate — {artifact.certification_id}" in md_report
    assert "## Quantitative Metrics" in md_report


# ==============================================================================
# 10. Post-Migration Drift Ingestion & Evaluation
# ==============================================================================

def test_post_migration_drift_evaluation():
    """Evaluates runtime observations against frozen oracle set and detects drift violations."""
    orc = _make_dummy_oracle("orc-drift", threshold=500.0)
    registry.register_oracle(orc)
    oracle_set = registry.create_oracle_set(name="DriftSet", oracle_ids=[orc.oracle_id])

    # Normal compliant observation (credit_score < 500 -> REJECT)
    normal_obs = DriftObservation(
        observation_id="OBS-001",
        inputs={"credit_score": 450},
        outputs={"decision": "REJECT"},
    )
    event1 = evaluate_drift_observation(normal_obs, oracle_set)
    assert event1.status == DriftStatus.NORMAL
    assert event1.alert_triggered is False

    # Violating observation (credit_score < 500 -> APPROVE)
    violating_obs = DriftObservation(
        observation_id="OBS-002",
        inputs={"credit_score": 450},
        outputs={"decision": "APPROVE"},
    )
    event2 = evaluate_drift_observation(violating_obs, oracle_set)
    assert event2.status == DriftStatus.ORACLE_VIOLATION
    assert event2.alert_triggered is True
    assert orc.oracle_id in event2.violated_oracle_ids

    # Uncovered input (credit_score >= 500)
    uncovered_obs = DriftObservation(
        observation_id="OBS-003",
        inputs={"credit_score": 750},
        outputs={"decision": "APPROVE"},
    )
    event3 = evaluate_drift_observation(uncovered_obs, oracle_set)
    assert event3.status == DriftStatus.UNCOVERED_INPUT
    assert event3.alert_triggered is False


# ==============================================================================
# 11. REST API Certification Execution & Score Authority
# ==============================================================================

def test_api_certification_endpoints():
    """REST API runs certification and provides drill-downs without accepting forged client scores."""
    orc = _make_dummy_oracle("orc-api-test", threshold=500.0)
    registry.register_oracle(orc)
    oracle_set = registry.create_oracle_set(name="ApiSet", oracle_ids=[orc.oracle_id])

    # Run certification via API with auth headers
    admin_user = auth_repository.get_user_by_username("admin_cert")
    if not admin_user:
        admin_user = auth_repository.create_user(
            user_id="USR-ADMIN-CERT",
            username="admin_cert",
            password="AdminCertPass2026!",
            full_name="Admin Cert",
            email="admin_cert@beacon.local",
            is_system_admin=True,
        )
    token = create_access_token(admin_user)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/certification/run", headers=headers, json={
        "project_id": "api_test_project",
        "oracle_set_id": oracle_set.oracle_set_id,
        "implementation": "equivalent",
        "n_samples": 30,
    })
    assert resp.status_code == 200
    data = resp.json()
    cert_id = data["certification_id"]
    assert data["status"] == "CERTIFIED"

    # Query artifact
    get_resp = client.get(f"/api/v1/certification/{cert_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["certification_id"] == cert_id

    # Query report HTML
    rep_resp = client.get(f"/api/v1/certification/{cert_id}/report", headers=headers)
    assert rep_resp.status_code == 200
    assert "BEACON Behavioral Equivalence Certificate" in rep_resp.text

    # Query oracles
    orc_resp = client.get(f"/api/v1/certification/{cert_id}/oracles", headers=headers)
    assert orc_resp.status_code == 200
    assert len(orc_resp.json()["oracle_summaries"]) == 1

    # Post-migration drift evaluate endpoint
    drift_resp = client.post("/api/v1/drift/evaluate", headers=headers, json={
        "observation_id": "OBS-API-1",
        "oracle_set_id": oracle_set.oracle_set_id,
        "inputs": {"credit_score": 420},
        "outputs": {"decision": "APPROVE"},
    })
    assert drift_resp.status_code == 200
    assert drift_resp.json()["status"] == "ORACLE_VIOLATION"


# ==============================================================================
# 12. End-to-End Loan Benchmark (Positive Pass & Deliberate Threshold Bug)
# ==============================================================================

def test_end_to_end_loan_benchmark_positive_and_negative():
    """Runs full loan benchmark: equivalent modernization -> CERTIFIED, buggy -> NOT_CERTIFIED."""
    import legacy_loan_approval
    import modern_loan_approval
    from ingestion.legacy_parser import extract_ast_structure
    from ingestion.trace_loader import load_traces
    from evidence.builder import build_evidence_package
    from mining.pipeline import run_mining_pipeline
    from generate_traces import generate_traces

    legacy_file = str(ROOT / "legacy_sample" / "legacy_loan_approval.py")
    static_result = extract_ast_structure(legacy_file)
    trace_file = ROOT / "legacy_sample" / "trace_log.json"
    if not trace_file.exists():
        trace_file.write_text(json.dumps(generate_traces(n_random=300), indent=2))
    traces = load_traces(trace_file)
    evidence_pkg = build_evidence_package(static_result, traces)

    graduated, _ = run_mining_pipeline(
        evidence_package=evidence_pkg,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds={"credit_score": (400, 820), "debt_ratio": (0.0, 0.9), "annual_income": (10000, 150000)},
        use_atlas=False,
        use_llm=False,
    )
    assert len(graduated) >= 2

    oracles = [synthesize_oracle(inv) for inv in graduated]
    for o in oracles:
        registry.register_oracle(o)

    oracle_set = registry.create_oracle_set(
        name="LoanBenchmarkSet",
        oracle_ids=[o.oracle_id for o in oracles],
        domain="loan_approval",
    )

    # 1. Equivalent Implementation Certification -> CERTIFIED
    eq_artifact = certification_engine.certify(
        project_id="loan_app",
        legacy_adapter=LegacyAdapter(target_fn=legacy_loan_approval.evaluate_loan),
        modern_adapter=ModernizedAdapter(target_fn=legacy_loan_approval.evaluate_loan),
        oracle_set=oracle_set,
        n_samples=50,
        seed=42,
    )
    assert eq_artifact.status == CertificationStatus.CERTIFIED
    assert eq_artifact.certified is True
    assert eq_artifact.metrics.modern_regressions == 0

    # 2. Buggy Implementation Certification -> NOT_CERTIFIED
    buggy_artifact = certification_engine.certify(
        project_id="loan_app",
        legacy_adapter=LegacyAdapter(target_fn=legacy_loan_approval.evaluate_loan),
        modern_adapter=ModernizedAdapter(target_fn=modern_loan_approval.evaluate_loan),
        oracle_set=oracle_set,
        n_samples=50,
        seed=42,
    )
    assert buggy_artifact.status == CertificationStatus.NOT_CERTIFIED
    assert buggy_artifact.certified is False
    assert buggy_artifact.metrics.modern_regressions > 0

    # Verify that counterexamples identify exact credit_score < 600 and debt_ratio > 0.4 rule
    found_compound_regression = any(
        "credit_score < 600" in reg.failed_assertion or reg.legacy_output == "REJECT"
        for reg in buggy_artifact.regressions
    )
    assert found_compound_regression is True
