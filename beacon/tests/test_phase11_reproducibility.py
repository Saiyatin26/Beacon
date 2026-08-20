import pytest
import sqlite3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

from certification.models import CertificationInputSet, CertificationCase, CertificationArtifact
from certification.repository import certification_repository
from certification.certification_engine import certification_engine
from certification.input_generator import generate_certification_test_suite
from certification.adapters import LegacyAdapter, ModernizedAdapter
from oracle.models import OracleDefinition, OracleSet, OraclePredicate, OracleConsequence
from oracle.registry import registry
import legacy_loan_approval
import modern_loan_approval

@pytest.fixture(autouse=True)
def clean_repo():
    certification_repository.clear()
    yield
    certification_repository.clear()

def get_dummy_oracle_set():
    from oracle.models import OracleProvenance
    oracle1 = OracleDefinition(
        oracle_id="ORC-DUMMY-1",
        invariant_id="INV-1",
        condition=OraclePredicate(variable="credit_score", operator=">=", value=700),
        consequence=OracleConsequence(variable="approved", value=True),
        confidence=0.9,
        domain="Loan approval",
        input_schema={},
        output_schema={},
        provenance=OracleProvenance(invariant_id="INV-1", source_file="test", confidence=0.9, severity="high"),
        raw_condition="credit_score >= 700",
        canonical_condition="credit_score >= 700"
    )
    from oracle.serializer import compute_oracle_set_hash
    oracle_set_hash = compute_oracle_set_hash([oracle1.content_hash])
    return OracleSet(oracle_set_id="SET-DUMMY", name="Dummy Set", oracle_set_hash=oracle_set_hash, oracles=[oracle1])

def test_deterministic_input_generation():
    oracle_set = get_dummy_oracle_set()
    bounds = {"credit_score": (400, 820)}
    
    # Run 1
    inputs1 = generate_certification_test_suite(oracle_set.oracles, bounds, n_diverse_samples=50, seed=42)
    ids1 = [inp.input_id for inp in inputs1]
    
    # Run 2 with same seed
    inputs2 = generate_certification_test_suite(oracle_set.oracles, bounds, n_diverse_samples=50, seed=42)
    ids2 = [inp.input_id for inp in inputs2]
    
    # Run 3 with diff seed
    inputs3 = generate_certification_test_suite(oracle_set.oracles, bounds, n_diverse_samples=50, seed=99)
    ids3 = [inp.input_id for inp in inputs3]
    
    assert ids1 == ids2
    assert ids1 != ids3

def test_complete_case_persistence():
    oracle_set = get_dummy_oracle_set()
    legacy_adapter = LegacyAdapter(target_fn=legacy_loan_approval.evaluate_loan, name="loan_legacy", version="1.0.0")
    modern_adapter = ModernizedAdapter(target_fn=modern_loan_approval.evaluate_loan, name="loan_modern", version="2.0.0")
    
    artifact = certification_engine.certify(
        project_id="test_proj",
        legacy_adapter=legacy_adapter,
        modern_adapter=modern_adapter,
        oracle_set=oracle_set,
        n_samples=10,
        seed=101
    )
    
    cases = certification_repository.list_certification_cases(artifact.certification_id, limit=1000)
    assert len(cases) == artifact.metrics.total_inputs
    assert len(cases) > 0
    
    for c in cases:
        assert c.input_set_id == artifact.input_set_id
        assert c.legacy_output_json
        assert c.modern_output_json
        assert c.classification in ["MATCH", "MODERN_REGRESSION", "REFERENCE_INCONSISTENT", "MUTUAL_VIOLATION", "NOT_APPLICABLE"]

def test_aggregate_metrics_match_persisted_cases():
    oracle_set = get_dummy_oracle_set()
    legacy_adapter = LegacyAdapter(target_fn=legacy_loan_approval.evaluate_loan, name="loan_legacy", version="1.0.0")
    modern_adapter = ModernizedAdapter(target_fn=modern_loan_approval.evaluate_loan, name="loan_modern", version="2.0.0")
    
    artifact = certification_engine.certify(
        project_id="test_proj",
        legacy_adapter=legacy_adapter,
        modern_adapter=modern_adapter,
        oracle_set=oracle_set,
        n_samples=20,
        seed=102
    )
    
    cases = certification_repository.list_certification_cases(artifact.certification_id, limit=1000)
    
    matching_cases = sum(1 for c in cases if c.classification == "MATCH")
    regression_cases = sum(1 for c in cases if c.classification == "MODERN_REGRESSION")
    
    assert artifact.metrics.matching_probes == matching_cases
    assert artifact.metrics.modern_regressions == regression_cases

def test_legacy_partial_runs():
    from certification.models import CertificationMetrics
    # Insert an artifact without cases
    art = CertificationArtifact(
        certification_id="CERT-LEGACY-001",
        project_id="legacy_proj",
        oracle_set_id="SET-1",
        metrics=CertificationMetrics(total_inputs=100, matching_probes=100),
        reproducibility_state="LEGACY_PARTIAL",
        content_hash="dummy"
    )
    certification_repository._memory_artifacts[art.certification_id] = art
    
    cases = certification_repository.list_certification_cases(art.certification_id)
    assert len(cases) == 0

def dummy_medical_triage(inputs):
    return {"priority": "HIGH" if inputs.get("heart_rate", 0) > 100 else "LOW"}

def test_non_loan_adapter_persistence():
    from oracle.models import OracleProvenance
    oracle1 = OracleDefinition(
        oracle_id="ORC-MED-1",
        invariant_id="INV-MED",
        condition=OraclePredicate(variable="heart_rate", operator=">", value=100),
        consequence=OracleConsequence(variable="priority", value="HIGH"),
        confidence=1.0,
        domain="Medical",
        input_schema={},
        output_schema={},
        provenance=OracleProvenance(invariant_id="INV-MED", source_file="test", confidence=1.0, severity="high"),
        raw_condition="heart_rate > 100",
        canonical_condition="heart_rate > 100"
    )
    from oracle.serializer import compute_oracle_set_hash
    oracle_set_hash = compute_oracle_set_hash([oracle1.content_hash])
    oracle_set = OracleSet(oracle_set_id="SET-MED", name="Medical Set", oracle_set_hash=oracle_set_hash, oracles=[oracle1])
    
    legacy_adapter = LegacyAdapter(target_fn=dummy_medical_triage, name="med_legacy", version="1.0")
    modern_adapter = ModernizedAdapter(target_fn=dummy_medical_triage, name="med_modern", version="2.0")
    
    artifact = certification_engine.certify(
        project_id="test_med",
        legacy_adapter=legacy_adapter,
        modern_adapter=modern_adapter,
        oracle_set=oracle_set,
        field_bounds={"heart_rate": (60, 150)},
        n_samples=10,
        seed=200
    )
    
    cases = certification_repository.list_certification_cases(artifact.certification_id)
    assert len(cases) > 0
    assert "heart_rate" in cases[0].input_json

def test_tamper_detection_on_persisted_cases():
    oracle_set = get_dummy_oracle_set()
    legacy_adapter = LegacyAdapter(target_fn=legacy_loan_approval.evaluate_loan, name="loan_legacy", version="1.0.0")
    modern_adapter = ModernizedAdapter(target_fn=modern_loan_approval.evaluate_loan, name="loan_modern", version="2.0.0")
    
    artifact = certification_engine.certify(
        project_id="test_tamper",
        legacy_adapter=legacy_adapter,
        modern_adapter=modern_adapter,
        oracle_set=oracle_set,
        n_samples=5,
        seed=300
    )
    
    # Tamper with the artifact hash to ensure integrity fails on load
    with sqlite3.connect(certification_repository._db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT payload_json FROM certification_artifacts WHERE certification_id = ?", (artifact.certification_id,))
        row = cursor.fetchone()
        if row:
            payload = json.loads(row[0])
            payload["content_hash"] = "tampered"
            conn.execute("UPDATE certification_artifacts SET payload_json = ? WHERE certification_id = ?", (json.dumps(payload), artifact.certification_id))
        conn.commit()
    
    certification_repository._memory_artifacts.pop(artifact.certification_id, None)
    
    loaded = certification_repository.get_artifact(artifact.certification_id)
    assert loaded is not None
    
    from certification.models import verify_artifact_integrity
    assert verify_artifact_integrity(loaded) is False
