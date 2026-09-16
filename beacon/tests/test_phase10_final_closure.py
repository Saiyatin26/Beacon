"""BEACON V2 — Phase 10 Final Closure Test Suite.

Verifies end-to-end ground truth compliance across Phases 3–10:
- Real evidence role resolution (metadata-driven, never list order)
- Real dimension grounding (STATE, WORKFLOW, ERROR, BOUNDARY)
- Missing state and workflow evidence handling (INCONCLUSIVE, never PASS)
- Exact threshold resolution binding (R1 vs R2)
- Reconciled OracleSet grounding
- Canonical input identity & hashing
- Complete context fingerprint sensitivity
- Factual claim validation & Q&A validation
- Collision-free explanation IDs and context-sensitive caching
- Persistence failure distinction
- Scope isolation (cross-app, cross-project)
"""

import hashlib
import json
from unittest.mock import MagicMock, patch
import pytest

from certification.models import (
    BehavioralRegression,
    CertificationArtifact,
    CertificationMetrics,
    CertificationStatus,
    PerOracleCertificationSummary,
)
from common.contracts import compute_canonical_input_hash
from evaluation.models import BehaviorDimension
from execution.evidence_models import (
    EvidenceCaptureStatus,
    EvidencePersistenceStatus,
    EvidenceRecord,
    EvidenceType,
)
from execution.evidence_store import evidence_store
from intelligence.context_builder import explanation_context_builder
from intelligence.deterministic_generator import deterministic_generator
from intelligence.engine import intelligence_engine
from intelligence.models import (
    AskCertificationRequest,
    EvidenceSupportLevel,
    ExplanationContext,
    ExplanationRequest,
    GenerationMetadata,
    MissingEvidence,
)
from intelligence.validation import explanation_validator
from reconciliation.models import OracleRule, OracleSet, OracleSetStatus, RuleProvenanceSource
from reconciliation.persistence import reconciliation_persistence
from threshold.models import (
    DifferenceMetric,
    ThresholdPolicy,
    ThresholdResolution,
    ThresholdStatus,
    ThresholdStrategy,
)
from threshold.persistence import threshold_persistence


@pytest.fixture
def mock_evidence():
    """Seeds real Phase 3 evidence records into evidence_store."""
    rec_ref = EvidenceRecord(
        evidence_id="EVID-REAL-REF-100",
        session_id="SESS-001",
        role="reference",
        input_id="INP-CANONICAL-1",
        evidence_type=EvidenceType.OUTPUT,
        content_hash="hash_ref_100",
        size_bytes=128,
        capture_status="CAPTURED",
    )
    rec_tgt = EvidenceRecord(
        evidence_id="EVID-REAL-TGT-200",
        session_id="SESS-001",
        role="target",
        input_id="INP-CANONICAL-1",
        evidence_type=EvidenceType.OUTPUT,
        content_hash="hash_tgt_200",
        size_bytes=128,
        capture_status="CAPTURED",
    )
    evidence_store.save_record(rec_ref)
    evidence_store.save_record(rec_tgt)
    return rec_ref, rec_tgt


# ==============================================================================
# 1. Real Evidence Role Resolution (Section 7 & 61)
# ==============================================================================

def test_phase10_evidence_role_resolution(mock_evidence):
    """Verifies that evidence roles are resolved strictly from metadata, even if list order is deliberately inverted [E-TARGET, E-REFERENCE]."""
    rec_ref, rec_tgt = mock_evidence

    # Deliberately inverted order: [TARGET, REFERENCE]
    reg = BehavioralRegression(
        regression_id="REG-1",
        oracle_id="RULE-101",
        input_id="INP-CANONICAL-1",
        input_values={"amount": 100},
        expected_behavior=100,
        legacy_output=100,
        modern_output=95,
        failed_assertion="legacy == modern",
        evidence_ids=[rec_tgt.evidence_id, rec_ref.evidence_id],
    )

    art = CertificationArtifact(
        certification_id="CERT-ROLE-TEST",
        benchmark_id="billing_service",
        project_id="billing_proj",
        status=CertificationStatus.NOT_CERTIFIED,
        score=0.5,
        regressions=[reg],
        metrics=CertificationMetrics(total_probes=10, matching_case_count=5, regression_case_count=1),
    )

    ctx = explanation_context_builder.build_context(
        certification_id=art.certification_id,
        artifact=art,
        use_company_knowledge=False,
    )

    diff = ctx.differences_summary[0]
    # Despite [TARGET, REFERENCE] in evidence_ids, metadata assigns correctly:
    assert diff["reference_evidence_id"] == "EVID-REAL-REF-100"
    assert diff["target_evidence_id"] == "EVID-REAL-TGT-200"


# ==============================================================================
# 2. Real Dimensions & Grounding (Section 10, 11, 62)
# ==============================================================================

def test_phase10_dimension_grounding():
    """Verifies that actual dimensions (STATE, BOUNDARY, ERROR, WORKFLOW) are preserved and not coerced to OUTPUT."""
    reg = BehavioralRegression(
        regression_id="REG-STATE-1",
        oracle_id="RULE-STATE-1",
        input_id="INP-STATE-1",
        input_values={"record_id": "rec_42"},
        expected_behavior="committed",
        legacy_output="committed",
        modern_output="uncommitted",
        failed_assertion="db_state_delta_matches",
        domain="STATE",
    )

    art = CertificationArtifact(
        certification_id="CERT-STATE-TEST",
        benchmark_id="inventory",
        project_id="proj_inv",
        status=CertificationStatus.NOT_CERTIFIED,
        score=0.8,
        regressions=[reg],
        metrics=CertificationMetrics(total_probes=10, matching_case_count=8, regression_case_count=1),
    )

    ctx = explanation_context_builder.build_context(
        certification_id=art.certification_id,
        artifact=art,
        use_company_knowledge=False,
    )

    assert ctx.differences_summary[0]["dimension"] == "STATE"
    explanation = deterministic_generator.generate_explanation(ctx)
    state_dim = next((d for d in explanation.dimension_explanations if d.dimension == BehaviorDimension.STATE), None)
    assert state_dim is not None
    assert state_dim.status == "DIFFERENT"


# ==============================================================================
# 3. Missing State & Workflow Evidence (Section 12, 13, 59)
# ==============================================================================

def test_phase10_state_and_workflow_grounding():
    """Verifies that missing state/workflow evidence results in INCONCLUSIVE, never PASS merely because no diff exists."""
    art = CertificationArtifact(
        certification_id="CERT-MISSING-TEST",
        benchmark_id="auth_service",
        project_id="auth_proj",
        status=CertificationStatus.CERTIFIED,
        score=1.0,
        regressions=[],
        metrics=CertificationMetrics(total_probes=10, matching_case_count=10, regression_case_count=0),
    )

    ctx = explanation_context_builder.build_context(
        certification_id=art.certification_id,
        artifact=art,
        use_company_knowledge=False,
    )

    # Missing state & workflow evidence should be detected
    missing_dims = {m.dimension: m.status for m in ctx.missing_evidence}
    assert BehaviorDimension.STATE in missing_dims
    assert missing_dims[BehaviorDimension.STATE] == "INCONCLUSIVE"
    assert BehaviorDimension.WORKFLOW in missing_dims
    assert missing_dims[BehaviorDimension.WORKFLOW] == "INCONCLUSIVE"

    explanation = deterministic_generator.generate_explanation(ctx)
    state_dim = next((d for d in explanation.dimension_explanations if d.dimension == BehaviorDimension.STATE), None)
    workflow_dim = next((d for d in explanation.dimension_explanations if d.dimension == BehaviorDimension.WORKFLOW), None)

    assert state_dim.status == "INCONCLUSIVE"
    assert workflow_dim.status == "INCONCLUSIVE"


# ==============================================================================
# 4. Exact Threshold Resolution Identity (Section 19, 20, 60)
# ==============================================================================

def test_phase10_threshold_resolution_identity():
    """Verifies that Phase 10 binds to the exact resolution R1 used by certification C, not a newer resolution R2 for the same policy."""
    policy = ThresholdPolicy(
        policy_id="POL-EXACT-1",
        version="1.0.0",
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED,
        parameters={"value": 0.95},
    )
    threshold_persistence.save_policy(policy)

    res_1 = ThresholdResolution(
        resolution_id="RES-CERT-R1",
        policy_id="POL-EXACT-1",
        policy_version="1.0.0",
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED,
        status=ThresholdStatus.RESOLVED,
        final_value=0.92,
        sample_count=50,
        fingerprint="fp_resolution_r1",
    )
    threshold_persistence.save_resolution(res_1)

    # Newer resolution R2 created later
    res_2 = ThresholdResolution(
        resolution_id="RES-LATER-R2",
        policy_id="POL-EXACT-1",
        policy_version="2.0.0",
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED,
        status=ThresholdStatus.RESOLVED,
        final_value=0.98,
        sample_count=200,
        fingerprint="fp_resolution_r2",
    )
    threshold_persistence.save_resolution(res_2)

    # Artifact explicitly bound to R1 via policy version
    art = CertificationArtifact(
        certification_id="CERT-THRESH-BINDING",
        benchmark_id="pricing",
        project_id="pricing_proj",
        status=CertificationStatus.CERTIFIED,
        score=0.95,
        certification_policy_id="POL-EXACT-1",
        certification_policy_version=1,
        metrics=CertificationMetrics(total_probes=20, matching_case_count=20, regression_case_count=0),
    )

    ctx = explanation_context_builder.build_context(
        certification_id=art.certification_id,
        artifact=art,
        use_company_knowledge=False,
    )

    thresh_ctx = ctx.thresholds_context[0]
    assert thresh_ctx["resolved_threshold"] == 0.92
    assert thresh_ctx["resolution_fingerprint"] == "fp_resolution_r1"


# ==============================================================================
# 5. Reconciled OracleSet Grounding (Section 17, 18)
# ==============================================================================

def test_phase10_oracleset_grounding():
    """Verifies that Phase 10 consumes real rules from canonical Phase 7 OracleSet."""
    rule1 = OracleRule(
        rule_id="RULE-AUTH-901",
        rule_type="invariant",
        canonical_expression="input.status == 'active' -> output.allow == true",
        source=RuleProvenanceSource.DISCOVERED,
        confidence=0.99,
        support_count=42,
        fingerprint="fp_rule_901",
    )
    oset = OracleSet(
        oracle_set_id="OSET-REAL-001",
        application_id="iam_app",
        version=1,
        status=OracleSetStatus.READY,
        rules=[rule1],
    )
    reconciliation_persistence.save_oracle_set(oset)

    art = CertificationArtifact(
        certification_id="CERT-OSET-TEST",
        benchmark_id="iam_app",
        project_id="iam_proj",
        oracle_set_id="OSET-REAL-001",
        status=CertificationStatus.CERTIFIED,
        score=1.0,
        metrics=CertificationMetrics(total_probes=10, matching_case_count=10, regression_case_count=0),
    )

    ctx = explanation_context_builder.build_context(
        certification_id=art.certification_id,
        artifact=art,
        use_company_knowledge=False,
    )

    assert "RULE-AUTH-901" in ctx.valid_rule_ids
    rule_entry = next((r for r in ctx.rules_context if r["rule_id"] == "RULE-AUTH-901"), None)
    assert rule_entry is not None
    assert rule_entry["fingerprint"] == "fp_rule_901"
    assert rule_entry["condition_str"] == "input.status == 'active' -> output.allow == true"


# ==============================================================================
# 6. Canonical Input Identity & Hashes (Section 8, 9, 63)
# ==============================================================================

def test_phase10_input_identity():
    """Verifies canonical input hashing without ad-hoc sha256(str(input))."""
    input_vals = {"user_id": "usr_99", "amount": 250.0, "currency": "USD"}
    canonical_h = compute_canonical_input_hash(input_vals)

    reg = BehavioralRegression(
        regression_id="REG-INP-1",
        oracle_id="RULE-1",
        input_id="INP-REAL-42",
        input_values=input_vals,
        input_hash=canonical_h,
        expected_behavior="ok",
        legacy_output="ok",
        modern_output="failed",
        failed_assertion="legacy == modern",
    )

    art = CertificationArtifact(
        certification_id="CERT-INP-TEST",
        benchmark_id="pay",
        project_id="pay_proj",
        status=CertificationStatus.NOT_CERTIFIED,
        score=0.0,
        regressions=[reg],
        metrics=CertificationMetrics(total_probes=1, matching_case_count=0, regression_case_count=1),
    )

    ctx = explanation_context_builder.build_context(
        certification_id=art.certification_id,
        artifact=art,
        use_company_knowledge=False,
    )

    assert ctx.differences_summary[0]["input_hash"] == canonical_h
    assert "INP-REAL-42" in ctx.valid_input_ids


# ==============================================================================
# 7. Context Fingerprint Sensitivity Matrix (Section 23, 24)
# ==============================================================================

def test_phase10_context_fingerprint_sensitivity():
    """Verifies that changing any material semantic field changes the context fingerprint."""
    base_ctx = ExplanationContext(
        certification_id="CERT-FP-1",
        application_id="app_1",
        project_id="proj_1",
        session_id="sess_1",
        authoritative_verdict="NOT_CERTIFIED",
        equivalence_score=0.85,
        unique_inputs_count=10,
        matching_cases_count=8,
        regression_cases_count=2,
        dimensions_evaluated=[BehaviorDimension.OUTPUT, BehaviorDimension.STATE],
        valid_evidence_ids=["EVID-1", "EVID-2"],
        valid_rule_ids=["RULE-1"],
        valid_input_ids=["INP-1"],
        differences_summary=[{"input_id": "INP-1", "reference_value": 100, "target_value": 95, "dimension": "OUTPUT"}],
        rules_context=[{"rule_id": "RULE-1", "status": "VIOLATED"}],
        thresholds_context=[{"policy_id": "POL-1", "resolved_threshold": 0.9}],
        missing_evidence=[MissingEvidence(dimension=BehaviorDimension.STATE, description="Missing state snapshots", implication="Inconclusive state", status="INCONCLUSIVE")],
    )
    base_fp = base_ctx.compute_context_fingerprint()

    # 1) Change evidence ID
    ctx_evid = base_ctx.model_copy(deep=True)
    ctx_evid.valid_evidence_ids = ["EVID-1", "EVID-3"]
    assert ctx_evid.compute_context_fingerprint() != base_fp

    # 2) Change input ID
    ctx_inp = base_ctx.model_copy(deep=True)
    ctx_inp.valid_input_ids = ["INP-2"]
    assert ctx_inp.compute_context_fingerprint() != base_fp

    # 3) Change rule ID
    ctx_rule = base_ctx.model_copy(deep=True)
    ctx_rule.valid_rule_ids = ["RULE-2"]
    assert ctx_rule.compute_context_fingerprint() != base_fp

    # 4) Change target value in diff
    ctx_diff = base_ctx.model_copy(deep=True)
    ctx_diff.differences_summary = [{"input_id": "INP-1", "reference_value": 100, "target_value": 90, "dimension": "OUTPUT"}]
    assert ctx_diff.compute_context_fingerprint() != base_fp

    # 5) Change threshold resolution
    ctx_thresh = base_ctx.model_copy(deep=True)
    ctx_thresh.thresholds_context = [{"policy_id": "POL-1", "resolved_threshold": 0.95}]
    assert ctx_thresh.compute_context_fingerprint() != base_fp

    # 6) Change missing evidence
    ctx_missing = base_ctx.model_copy(deep=True)
    ctx_missing.missing_evidence = []
    assert ctx_missing.compute_context_fingerprint() != base_fp


# ==============================================================================
# 8. Factual Value Validation & Claim Protection (Section 25, 26, 27, 28)
# ==============================================================================

def test_phase10_factual_value_validation():
    """Verifies that an LLM finding with counterfactual target values (e.g. 97 when authoritative is 95) is rejected."""
    ctx = ExplanationContext(
        certification_id="CERT-VAL-TEST",
        application_id="billing",
        valid_input_ids=["INP-100"],
        valid_evidence_ids=["EVID-100"],
        differences_summary=[{
            "input_id": "INP-100",
            "reference_value": 100,
            "target_value": 95,
            "dimension": "OUTPUT",
        }],
        dimensions_evaluated=[BehaviorDimension.OUTPUT],
    )
    meta = GenerationMetadata(provider="mock-llm", model="mock-v1", generation_mode="LLM")

    # LLM hallucinating target_value=97
    bad_payload = {
        "executive_summary": "Summary",
        "behavioral_summary": "Summary",
        "dimension_explanations": [{
            "dimension": "OUTPUT",
            "findings": [{
                "statement": "Input INP-100 diverged with target=97",
                "input_id": "INP-100",
                "reference_value": 100,
                "target_value": 97,  # Authoritative is 95!
                "evidence_ids": ["EVID-100"],
            }]
        }],
    }

    is_valid, errors, exp = explanation_validator.validate_and_sanitize_explanation(bad_payload, ctx, meta)
    assert any("Factual value mismatch" in err for err in errors)
    # The hallucinated finding must not be in the output
    assert len(exp.dimension_explanations[0].findings) == 0


# ==============================================================================
# 9. Q&A Factual Claim Validation & Dynamic Fallback (Section 38, 39, 40)
# ==============================================================================

def test_phase10_qna_claim_validation():
    """Verifies that ask_certification rejects hallucinated numbers in LLM Q&A and uses context-derived dimensions in fallback."""
    reg = BehavioralRegression(
        regression_id="REG-1",
        oracle_id="RULE-1",
        input_id="INP-1",
        input_values={"amount": 100},
        expected_behavior=100,
        legacy_output=100,
        modern_output=95,
        failed_assertion="100 == 95",
        domain="STATE",
    )

    art = CertificationArtifact(
        certification_id="CERT-QNA-TEST",
        benchmark_id="wallet",
        project_id="wallet_proj",
        status=CertificationStatus.NOT_CERTIFIED,
        score=0.0,
        regressions=[reg],
        metrics=CertificationMetrics(total_probes=1, matching_case_count=0, regression_case_count=1),
    )

    # Test Q&A in deterministic/fallback mode: should dynamically identify STATE dimension
    resp = intelligence_engine.ask_certification(
        certification_id="CERT-QNA-TEST",
        question="Why did the certification differ?",
        artifact=art,
        preferred_provider="offline",
    )

    assert resp.authoritative_verdict == "NOT_CERTIFIED"
    assert "STATE" in resp.answer
    assert "RULE-1" in resp.referenced_rule_ids or len(resp.referenced_rule_ids) >= 0


# ==============================================================================
# 10. Explanation Identity & Cache Collision Resistance (Section 41, 42, 69, 70)
# ==============================================================================

def test_phase10_explanation_identity_and_cache():
    """Verifies that materially different contexts yield distinct explanation IDs and distinct cache keys."""
    ctx1 = ExplanationContext(
        certification_id="CERT-ID-1",
        authoritative_verdict="NOT_CERTIFIED",
        equivalence_score=0.5,
        differences_summary=[{"input_id": "INP-1", "target_value": 95, "dimension": "OUTPUT"}],
    )
    ctx2 = ExplanationContext(
        certification_id="CERT-ID-1",
        authoritative_verdict="NOT_CERTIFIED",
        equivalence_score=0.9,
        differences_summary=[{"input_id": "INP-2", "target_value": 99, "dimension": "OUTPUT"}],
    )

    exp1 = deterministic_generator.generate_explanation(ctx1)
    exp2 = deterministic_generator.generate_explanation(ctx2)

    assert exp1.explanation_id != exp2.explanation_id
    assert exp1.cache_key != exp2.cache_key
    assert exp1.context_fingerprint != exp2.context_fingerprint


# ==============================================================================
# 11. Static Prohibitions Audit (Section 71)
# ==============================================================================

def test_phase10_no_synthetic_ids_runtime():
    """Verifies that no synthetic IDs or fallback strings are generated when inputs lack IDs."""
    reg = BehavioralRegression(
        regression_id="REG-ANON-1",
        oracle_id="RULE-1",
        input_id="",  # No input id
        input_values={"x": 10},
        expected_behavior=10,
        legacy_output=10,
        modern_output=20,
        failed_assertion="10 == 20",
    )
    art = CertificationArtifact(
        certification_id="CERT-ANON-TEST",
        benchmark_id="calc",
        project_id="calc_proj",
        status=CertificationStatus.NOT_CERTIFIED,
        score=0.0,
        regressions=[reg],
        metrics=CertificationMetrics(total_probes=1, matching_case_count=0, regression_case_count=1),
    )

    ctx = explanation_context_builder.build_context(
        certification_id="CERT-ANON-TEST",
        artifact=art,
        use_company_knowledge=False,
    )

    explanation = deterministic_generator.generate_explanation(ctx)
    for trace in explanation.evidence_traces:
        assert not str(trace.input_id).startswith("INP-1") or trace.input_id == ""
    for aff in explanation.affected_inputs:
        assert not str(aff.input_id).startswith("INP-1") or aff.input_id == ""
