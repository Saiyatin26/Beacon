"""Phase 10 Final Hardening Test Suite.

Validates the four key hardening requirements:
1. Implementation-independent AdapterRegistry and generic API resolution (non-loan application)
2. Complete canonical artifact content hashing and tamper detection across all material fields
3. Pure OracleDefinition and OracleSet immutability throughout Phase 8/9/10
4. Semantic consistency in certification statuses and blocking gates
"""

import json
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))

from api.main import app
from auth import auth_repository, create_access_token
from certification import (
    CertificationArtifact,
    CertificationPolicy,
    CertificationStatus,
    FunctionAdapter,
    LegacyAdapter,
    ModernizedAdapter,
    adapter_registry,
    certification_engine,
    certification_repository,
    compute_artifact_content_hash,
    verify_artifact_integrity,
)
from oracle import (
    OracleDefinition,
    OraclePredicate,
    OracleSet,
    OracleStatus,
    compile_candidate_to_oracle,
    registry,
)
from common.models import CandidateInvariant

client = TestClient(app)


def _make_dummy_oracle(
    oracle_id: str,
    variable: str = "spo2",
    operator: str = "<",
    threshold: float = 90.0,
    consequence_var: str = "triage",
    consequence_val: str = "EMERGENCY",
    severity: str = "critical",
    confidence: float = 0.95,
) -> OracleDefinition:
    candidate = CandidateInvariant(
        invariant_id=oracle_id,
        condition=f"{variable} {operator} {threshold}",
        consequence=f"{consequence_var} == '{consequence_val}'",
        confidence=confidence,
        severity=severity,
        domain="medical_triage",
        evidence_ids=["MED-EVID-1"],
        source_lines=[15],
        status="VALIDATED",
    )
    return compile_candidate_to_oracle(candidate)


@pytest.fixture(autouse=True)
def clean_state():
    registry.clear()
    certification_repository.clear()
    adapter_registry.clear()
    yield
    registry.clear()
    certification_repository.clear()
    adapter_registry.clear()
    from benchmarks.registry import benchmark_registry
    benchmark_registry.refresh()


# ==============================================================================
# 1. Implementation-Independent AdapterRegistry & Generic Non-Loan API
# ==============================================================================

def test_generic_non_loan_adapter_registration_and_api():
    """Proves that a non-loan domain (medical triage) can be registered and certified via API."""
    # 1. Register non-loan oracle
    orc = _make_dummy_oracle("orc-triage-1")
    registry.register_oracle(orc)
    oracle_set = registry.create_oracle_set(
        name="TriageSet",
        oracle_ids=[orc.oracle_id],
        domain="medical_triage",
    )

    # 2. Define non-loan implementations
    def triage_legacy(spo2=98, pulse=75, **kwargs):
        if spo2 < 90:
            return {"triage": "EMERGENCY"}
        return {"triage": "ROUTINE"}

    def triage_modern(spo2=98, pulse=75, **kwargs):
        if spo2 < 90:
            return {"triage": "EMERGENCY"}
        return {"triage": "ROUTINE"}

    # 3. Register in AdapterRegistry
    adapter_registry.register_adapter(
        LegacyAdapter(target_fn=triage_legacy, name="medical_triage_legacy", version="1.0.0")
    )
    adapter_registry.register_adapter(
        ModernizedAdapter(target_fn=triage_modern, name="medical_triage_modern", version="2.0.0")
    )

    # 4. Invoke generic certification API route with auth headers
    admin_user = auth_repository.get_user_by_username("admin_harden")
    if not admin_user:
        admin_user = auth_repository.create_user(
            user_id="USR-ADMIN-HARDEN",
            username="admin_harden",
            password="AdminPass2026!",
            full_name="Admin Harden",
            email="admin_harden@beacon.local",
            is_system_admin=True,
        )
    token = create_access_token(admin_user)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/certification/run", headers=headers, json={
        "project_id": "hospital_systems_triage",
        "legacy_target": "medical_triage_legacy",
        "modernized_target": "medical_triage_modern",
        "legacy_version": "1.0.0",
        "modernized_version": "2.0.0",
        "oracle_set_id": oracle_set.oracle_set_id,
        "n_samples": 30,
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "CERTIFIED"
    assert data["certified"] is True
    assert data["score"] == 1.0
    assert data["project_id"] == "hospital_systems_triage"
    assert data["oracle_set_id"] == oracle_set.oracle_set_id


# ==============================================================================
# 2. Cryptographically Complete & Tamper-Evident Artifact Content Hashing
# ==============================================================================

def test_artifact_content_hashing_and_tamper_detection():
    """Verifies that altering any material field changes the content hash and fails integrity verification."""
    orc = _make_dummy_oracle("orc-tamper")
    registry.register_oracle(orc)
    oracle_set = registry.create_oracle_set(name="TamperSet", oracle_ids=[orc.oracle_id])

    def sample_fn(spo2=98, **kwargs):
        return {"triage": "EMERGENCY" if spo2 < 90 else "ROUTINE"}

    legacy_adp = LegacyAdapter(target_fn=sample_fn, version="1.0.0")
    modern_adp = ModernizedAdapter(target_fn=sample_fn, version="2.0.0")

    artifact = certification_engine.certify(
        project_id="test_tamper_project",
        legacy_adapter=legacy_adp,
        modern_adapter=modern_adp,
        oracle_set=oracle_set,
        field_bounds={"spo2": (70.0, 100.0)},
        n_samples=25,
    )

    # 1. Initial valid artifact integrity
    assert verify_artifact_integrity(artifact) is True
    original_hash = artifact.content_hash

    # 2. Tampering with status
    tampered_status = artifact.model_copy(update={"status": CertificationStatus.NOT_CERTIFIED})
    assert verify_artifact_integrity(tampered_status) is False
    assert compute_artifact_content_hash(tampered_status) != original_hash

    # 3. Tampering with score
    tampered_score = artifact.model_copy(update={"score": 0.50})
    assert verify_artifact_integrity(tampered_score) is False

    # 4. Tampering with metrics
    mod_metrics = artifact.metrics.model_copy(update={"matching_probes": 999})
    tampered_metrics = artifact.model_copy(update={"metrics": mod_metrics})
    assert verify_artifact_integrity(tampered_metrics) is False

    # 5. Tampering with oracle_summaries
    tampered_summaries = artifact.model_copy(update={"oracle_summaries": []})
    assert verify_artifact_integrity(tampered_summaries) is False

    # 6. Repository rejects saving tampered artifact
    with pytest.raises(ValueError, match="Integrity violation"):
        certification_repository.save_artifact(tampered_status)


# ==============================================================================
# 3. Oracle and OracleSet Pure Immutability
# ==============================================================================

def test_oracle_and_oracle_set_immutability():
    """Confirms OracleDefinition and OracleSet reject in-place mutation and preserve historical records."""
    orc = _make_dummy_oracle("orc-immut", threshold=90.0)
    registry.register_oracle(orc)

    # In-place mutation of OracleDefinition raises ValidationError/TypeError
    with pytest.raises((ValidationError, TypeError)):
        orc.status = OracleStatus.INACTIVE

    # Registering a modified oracle with same oracle_id creates version 2 and leaves version 1 superseded immutably
    new_pred = OraclePredicate(variable="spo2", operator="<", value=85.0)
    orc_v2 = orc.model_copy(update={"condition": new_pred, "content_hash": "different_hash_abc123"})
    registered_v2 = registry.register_oracle(orc_v2)
    assert registered_v2.version == 2
    assert registered_v2.status == OracleStatus.ACTIVE

    v1_lookup = registry.get_oracle(orc.oracle_id, version=1)
    assert v1_lookup is not None
    assert v1_lookup.version == 1
    assert v1_lookup.status == OracleStatus.SUPERSEDED

    # Frozen OracleSet rejects in-place modification
    oracle_set = registry.create_oracle_set(name="ImmSet", oracle_ids=[orc.oracle_id])
    with pytest.raises((ValidationError, TypeError)):
        oracle_set.name = "MutatedName"


# ==============================================================================
# 4. Certification Status Alignment
# ==============================================================================

def test_blocking_statuses_prevent_certified_flag():
    """Proves that a reference inconsistency or mutual violation strictly yields certified=False."""
    orc = _make_dummy_oracle("orc-block", threshold=90.0)
    registry.register_oracle(orc)
    oracle_set = registry.create_oracle_set(name="BlockSet", oracle_ids=[orc.oracle_id])

    # Reference implementation flawed (never triggers EMERGENCY)
    def flawed_legacy(spo2=98, **kwargs):
        return {"triage": "ROUTINE"}

    def correct_modern(spo2=98, **kwargs):
        return {"triage": "EMERGENCY" if spo2 < 90 else "ROUTINE"}

    artifact = certification_engine.certify(
        project_id="test_block",
        legacy_adapter=LegacyAdapter(target_fn=flawed_legacy),
        modern_adapter=ModernizedAdapter(target_fn=correct_modern),
        oracle_set=oracle_set,
        field_bounds={"spo2": (70.0, 100.0)},
        n_samples=25,
    )

    assert artifact.status == CertificationStatus.REFERENCE_INCONSISTENT
    assert artifact.certified is False
