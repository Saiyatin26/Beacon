"""BEACON V2 — Phase 10 Final Closure & Adversarial Verification Test Suite.

Covers all required closure test cases (Tests A through W), complete data chain integration,
and Q&A grounding validation as specified in Phase 10 Master Remediation.
"""

import hashlib
import json
from unittest.mock import MagicMock, patch
import pytest

from certification.models import (
    BehavioralRegression,
    CertificationArtifact,
    CertificationContext,
    CertificationMetrics,
    CertificationStatus,
    PerOracleCertificationSummary,
)
from certification.certification_engine import CertificationEngine, certification_engine
from common.contracts import compute_canonical_input_hash
from evaluation.models import (
    BehaviorDifference,
    BehaviorDimension,
    DifferenceType,
    DimensionEvaluationSummary,
    EvaluationResult,
    EvaluationSummary,
    EvaluationVerdict,
    InputEvaluationResult,
)
from execution.evidence_models import (
    EvidenceBundle,
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
    GroundingClaim,
    GroundingClaimType,
    MissingEvidence,
)
from intelligence.persistence import IntelligencePersistenceStore
from intelligence.validation import grounding_validator
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


# ==============================================================================
# Test A: Missing Phase 3 Evidence
# ==============================================================================

def test_a_missing_phase3_evidence():
    """Certification exists but Phase 3 evidence is absent -> INCONCLUSIVE/missing evidence, never PASS."""
    art = CertificationArtifact(
        certification_id="CERT-NO-EVID-A",
        project_id="app_a",
        status=CertificationStatus.NOT_CERTIFIED,
        score=0.0,
        regressions=[],
        metrics=CertificationMetrics(unique_input_count=1, matching_case_count=0, regression_case_count=0),
    )

    ctx = explanation_context_builder.build_context(
        certification_id="CERT-NO-EVID-A",
        artifact=art,
        use_company_knowledge=False,
    )

    # Missing state and workflow evidence must be flagged
    missing_dims = {m.dimension for m in ctx.missing_evidence}
    assert BehaviorDimension.STATE in missing_dims
    assert BehaviorDimension.WORKFLOW in missing_dims

    exp = deterministic_generator.generate_explanation(ctx)
    state_dim = next((d for d in exp.dimension_explanations if d.dimension == BehaviorDimension.STATE), None)
    assert state_dim.status == "INCONCLUSIVE"


# ==============================================================================
# Test B: Actual Reference/Target Roles in Shuffled Order
# ==============================================================================

def test_b_shuffled_evidence_roles():
    """Create evidence in shuffled order: [TARGET, REFERENCE, TARGET, REFERENCE] -> role resolution remains correct."""
    rec_ref1 = EvidenceRecord(
        evidence_id="EVID-R1",
        session_id="SESS-B",
        role="reference",
        input_id="INP-1",
        evidence_type=EvidenceType.OUTPUT,
        content_hash="h_r1",
        size_bytes=10,
        capture_status="CAPTURED",
    )
    rec_tgt1 = EvidenceRecord(
        evidence_id="EVID-T1",
        session_id="SESS-B",
        role="target",
        input_id="INP-1",
        evidence_type=EvidenceType.OUTPUT,
        content_hash="h_t1",
        size_bytes=10,
        capture_status="CAPTURED",
    )
    evidence_store.save_record(rec_ref1)
    evidence_store.save_record(rec_tgt1)

    reg = BehavioralRegression(
        regression_id="REG-B",
        oracle_id="RULE-1",
        input_id="INP-1",
        input_values={"x": 1},
        expected_behavior=1,
        legacy_output=1,
        modern_output=2,
        failed_assertion="1 == 2",
        evidence_ids=["EVID-T1", "EVID-R1"],  # Deliberately [TARGET, REFERENCE]
    )
    art = CertificationArtifact(
        certification_id="CERT-B",
        project_id="app_b",
        status=CertificationStatus.NOT_CERTIFIED,
        score=0.0,
        regressions=[reg],
        metrics=CertificationMetrics(unique_input_count=1, matching_case_count=0, regression_case_count=1),
    )

    ctx = explanation_context_builder.build_context(
        certification_id="CERT-B",
        artifact=art,
        use_company_knowledge=False,
    )

    diff = ctx.differences_summary[0]
    assert diff["reference_evidence_id"] == "EVID-R1"
    assert diff["target_evidence_id"] == "EVID-T1"


# ==============================================================================
# Test C: Misleading Evidence IDs (EVID-legacy-999 with actual role = TARGET)
# ==============================================================================

def test_c_misleading_evidence_ids():
    """Identifier has misleading name 'EVID-legacy-999' but actual record role is 'target' -> resolved as TARGET."""
    rec = EvidenceRecord(
        evidence_id="EVID-legacy-999",
        session_id="SESS-C",
        role="target",  # ACTUAL ROLE IS TARGET
        input_id="INP-C",
        evidence_type=EvidenceType.OUTPUT,
        content_hash="h_c",
        size_bytes=10,
        capture_status="CAPTURED",
    )
    evidence_store.save_record(rec)

    reg = BehavioralRegression(
        regression_id="REG-C",
        oracle_id="RULE-1",
        input_id="INP-C",
        input_values={"x": 1},
        expected_behavior=1,
        legacy_output=1,
        modern_output=2,
        failed_assertion="1 == 2",
        evidence_ids=["EVID-legacy-999"],
    )
    art = CertificationArtifact(
        certification_id="CERT-C",
        project_id="app_c",
        status=CertificationStatus.NOT_CERTIFIED,
        score=0.0,
        regressions=[reg],
        metrics=CertificationMetrics(unique_input_count=1, matching_case_count=0, regression_case_count=1),
    )

    ctx = explanation_context_builder.build_context(
        certification_id="CERT-C",
        artifact=art,
        use_company_knowledge=False,
    )

    diff = ctx.differences_summary[0]
    # Despite 'legacy' in ID string, metadata proves it is TARGET:
    assert diff["target_evidence_id"] == "EVID-legacy-999"
    assert diff["reference_evidence_id"] is None


# ==============================================================================
# Test D: List-Position Trap
# ==============================================================================

def test_d_list_position_trap():
    """Shuffled evidence ID order in difference record yields identical explanation."""
    rec_ref = EvidenceRecord(
        evidence_id="E-REF", session_id="SESS-D", role="reference", input_id="INP-D",
        evidence_type=EvidenceType.OUTPUT, content_hash="h1", size_bytes=10, capture_status="CAPTURED"
    )
    rec_tgt = EvidenceRecord(
        evidence_id="E-TGT", session_id="SESS-D", role="target", input_id="INP-D",
        evidence_type=EvidenceType.OUTPUT, content_hash="h2", size_bytes=10, capture_status="CAPTURED"
    )
    evidence_store.save_record(rec_ref)
    evidence_store.save_record(rec_tgt)

    reg1 = BehavioralRegression(
        regression_id="REG-D", oracle_id="R1", input_id="INP-D", input_values={"x": 1},
        expected_behavior=1, legacy_output=1, modern_output=2, failed_assertion="1==2",
        evidence_ids=["E-REF", "E-TGT"]
    )
    reg2 = BehavioralRegression(
        regression_id="REG-D", oracle_id="R1", input_id="INP-D", input_values={"x": 1},
        expected_behavior=1, legacy_output=1, modern_output=2, failed_assertion="1==2",
        evidence_ids=["E-TGT", "E-REF"]  # Inverted
    )

    art1 = CertificationArtifact(
        certification_id="CERT-D1", project_id="app_d", status=CertificationStatus.NOT_CERTIFIED,
        score=0.0, regressions=[reg1], metrics=CertificationMetrics(unique_input_count=1, matching_case_count=0, regression_case_count=1)
    )
    art2 = CertificationArtifact(
        certification_id="CERT-D2", project_id="app_d", status=CertificationStatus.NOT_CERTIFIED,
        score=0.0, regressions=[reg2], metrics=CertificationMetrics(unique_input_count=1, matching_case_count=0, regression_case_count=1)
    )

    ctx1 = explanation_context_builder.build_context("CERT-D1", artifact=art1, use_company_knowledge=False)
    ctx2 = explanation_context_builder.build_context("CERT-D2", artifact=art2, use_company_knowledge=False)

    assert ctx1.differences_summary[0]["reference_evidence_id"] == ctx2.differences_summary[0]["reference_evidence_id"]
    assert ctx1.differences_summary[0]["target_evidence_id"] == ctx2.differences_summary[0]["target_evidence_id"]


# ==============================================================================
# Test E & F: State and Workflow Missing Evidence
# ==============================================================================

def test_e_state_missing_inconclusive():
    """OUTPUT = EQUIVALENT, STATE = no evidence -> STATE = INCONCLUSIVE, not PASS."""
    art = CertificationArtifact(
        certification_id="CERT-E", project_id="app_e", status=CertificationStatus.CERTIFIED,
        score=1.0, regressions=[], metrics=CertificationMetrics(unique_input_count=5, matching_case_count=5, regression_case_count=0)
    )
    ctx = explanation_context_builder.build_context("CERT-E", artifact=art, use_company_knowledge=False)
    exp = deterministic_generator.generate_explanation(ctx)

    state_dim = next(d for d in exp.dimension_explanations if d.dimension == BehaviorDimension.STATE)
    assert state_dim.status == "INCONCLUSIVE"


def test_f_workflow_missing_inconclusive():
    """Workflow trace telemetry absent -> WORKFLOW = INCONCLUSIVE."""
    art = CertificationArtifact(
        certification_id="CERT-F", project_id="app_f", status=CertificationStatus.CERTIFIED,
        score=1.0, regressions=[], metrics=CertificationMetrics(unique_input_count=5, matching_case_count=5, regression_case_count=0)
    )
    ctx = explanation_context_builder.build_context("CERT-F", artifact=art, use_company_knowledge=False)
    exp = deterministic_generator.generate_explanation(ctx)

    wf_dim = next(d for d in exp.dimension_explanations if d.dimension == BehaviorDimension.WORKFLOW)
    assert wf_dim.status == "INCONCLUSIVE"


# ==============================================================================
# Test G: ERROR Dimension Preserved
# ==============================================================================

def test_g_error_dimension_preserved():
    """Reference succeeds and Target errors -> dimension = ERROR, not OUTPUT."""
    diff = BehaviorDifference(
        difference_id="DIFF-ERR-1",
        dimension=BehaviorDimension.ERROR,
        difference_type=DifferenceType.SUCCESS_ERROR_MISMATCH,
        input_id="INP-ERR-1",
        reference_value="200 OK",
        target_value="500 INTERNAL ERROR",
    )
    eval_res = EvaluationResult(
        evaluation_id="EVAL-G",
        verdict=EvaluationVerdict.DIFFERENT,
        status=EvaluationVerdict.DIFFERENT,
        differences=[diff],
    )

    ctx = explanation_context_builder.build_context(
        certification_id="CERT-G",
        evaluation_result=eval_res,
        use_company_knowledge=False,
    )

    assert ctx.differences_summary[0]["dimension"] == "ERROR"
    exp = deterministic_generator.generate_explanation(ctx)
    err_dim = next(d for d in exp.dimension_explanations if d.dimension == BehaviorDimension.ERROR)
    assert err_dim.status == "DIFFERENT"


# ==============================================================================
# Test H & I: Phase 7 OracleSet Exact Consumption & Missing OracleSet
# ==============================================================================

def test_h_oracleset_exact_consumption():
    """Phase 10 directly follows persisted Phase 7 OracleSet."""
    rule = OracleRule(
        rule_id="RULE-CANONICAL-777",
        rule_type="invariant",
        canonical_expression="amount > 100 -> discount == 0.1",
        source=RuleProvenanceSource.DISCOVERED,
        confidence=0.98,
        support_count=50,
        fingerprint="fp_777",
    )
    oset = OracleSet(
        oracle_set_id="OSET-H-1",
        application_id="app_h",
        version=1,
        status=OracleSetStatus.READY,
        rules=[rule],
    )
    reconciliation_persistence.save_oracle_set(oset)

    art = CertificationArtifact(
        certification_id="CERT-H",
        project_id="app_h",
        oracle_set_id="OSET-H-1",
        status=CertificationStatus.CERTIFIED,
        score=1.0,
        metrics=CertificationMetrics(unique_input_count=1, matching_case_count=1, regression_case_count=0),
    )

    ctx = explanation_context_builder.build_context("CERT-H", artifact=art, use_company_knowledge=False)
    assert "RULE-CANONICAL-777" in ctx.valid_rule_ids
    rule_entry = next(r for r in ctx.rules_context if r["rule_id"] == "RULE-CANONICAL-777")
    assert rule_entry["fingerprint"] == "fp_777"


# ==============================================================================
# Test J, K, L: Threshold Resolution Binding & Fingerprint Verification
# ==============================================================================

def test_j_threshold_exact_binding():
    """Certification bound to RES-001 (0.92) vs newer RES-002 (0.98) -> uses 0.92."""
    policy = ThresholdPolicy(
        policy_id="POL-J", version="1.0.0", metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED, parameters={"value": 0.95}
    )
    threshold_persistence.save_policy(policy)

    res1 = ThresholdResolution(
        resolution_id="RES-001", policy_id="POL-J", policy_version="1.0.0",
        metric=DifferenceMetric.ABSOLUTE_DIFF, strategy=ThresholdStrategy.FIXED,
        status=ThresholdStatus.RESOLVED, final_value=0.92, sample_count=50, fingerprint="fp_res1"
    )
    res2 = ThresholdResolution(
        resolution_id="RES-002", policy_id="POL-J", policy_version="2.0.0",
        metric=DifferenceMetric.ABSOLUTE_DIFF, strategy=ThresholdStrategy.FIXED,
        status=ThresholdStatus.RESOLVED, final_value=0.98, sample_count=200, fingerprint="fp_res2"
    )
    threshold_persistence.save_resolution(res1)
    threshold_persistence.save_resolution(res2)

    art = CertificationArtifact(
        certification_id="CERT-J", project_id="app_j", status=CertificationStatus.CERTIFIED,
        score=0.95, certification_policy_id="POL-J", certification_policy_version=1,
        threshold_resolution_id="RES-001", threshold_resolution_fingerprint="fp_res1",
        metrics=CertificationMetrics(unique_input_count=10, matching_case_count=10, regression_case_count=0)
    )

    ctx = explanation_context_builder.build_context("CERT-J", artifact=art, use_company_knowledge=False)
    thresh = ctx.thresholds_context[0]
    assert thresh["resolved_threshold"] == 0.92
    assert thresh["resolution_fingerprint"] == "fp_res1"


def test_k_threshold_fingerprint_mismatch():
    """Threshold resolution with fingerprint mismatch produces THRESHOLD_CONTEXT error."""
    policy = ThresholdPolicy(
        policy_id="POL-K", version="1.0.0", metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED, parameters={"value": 0.95}
    )
    threshold_persistence.save_policy(policy)

    res = ThresholdResolution(
        resolution_id="RES-K", policy_id="POL-K", policy_version="1.0.0",
        metric=DifferenceMetric.ABSOLUTE_DIFF, strategy=ThresholdStrategy.FIXED,
        status=ThresholdStatus.RESOLVED, final_value=0.92, sample_count=50, fingerprint="actual_fp"
    )
    threshold_persistence.save_resolution(res)

    # Create artifact mock with conflicting fingerprint
    art_mock = MagicMock(
        certification_id="CERT-K",
        project_id="app_k",
        benchmark_id=None,
        status=CertificationStatus.CERTIFIED,
        score=0.95,
        certification_policy_id="POL-K",
        certification_policy_version=1,
        metrics=CertificationMetrics(unique_input_count=10, matching_case_count=10, regression_case_count=0),
        regressions=[],
        oracle_summaries=[],
        context=None,
        threshold_resolution_id="RES-K",
        threshold_resolution_fingerprint="tampered_fp",
    )
    ctx = explanation_context_builder.build_context("CERT-K", artifact=art_mock, use_company_knowledge=False)

    thresh = ctx.thresholds_context[0]
    assert thresh.get("status") == "ERROR"


# ==============================================================================
# Test M, N, O: Grounding Claim Validation (Fail-Closed)
# ==============================================================================

def test_m_invalid_evidence_reference_rejected():
    """LLM claim referencing non-existent evidence E-999 is rejected, not silently filtered."""
    ctx = ExplanationContext(
        certification_id="CERT-M",
        valid_evidence_ids=["E-100"],
        dimensions_evaluated=[BehaviorDimension.OUTPUT],
    )
    claim = GroundingClaim(
        claim_type=GroundingClaimType.EVIDENCE_REFERENCE,
        evidence_ids=["E-100", "E-999"],  # E-999 is invalid!
        statement="Behavior verified by E-999",
    )

    is_valid, errors, validated = grounding_validator.validate_claims([claim], ctx)
    assert not is_valid
    assert any("UNSUPPORTED_EVIDENCE_REFERENCE" in err for err in errors)
    assert len(validated) == 0


def test_n_invalid_rule_reference_rejected():
    """LLM claim referencing non-existent rule RULE-999 is rejected."""
    ctx = ExplanationContext(
        certification_id="CERT-N",
        valid_rule_ids=["RULE-100"],
        dimensions_evaluated=[BehaviorDimension.OUTPUT],
    )
    claim = GroundingClaim(
        claim_type=GroundingClaimType.RULE_REFERENCE,
        rule_id="RULE-999",
        statement="Invariant RULE-999 violated",
    )

    is_valid, errors, validated = grounding_validator.validate_claims([claim], ctx)
    assert not is_valid
    assert any("UNSUPPORTED_RULE_REFERENCE" in err for err in errors)
    assert len(validated) == 0


def test_o_incorrect_numeric_claim_rejected():
    """Authoritative target is 95, LLM claims target is 97 -> claim rejected."""
    ctx = ExplanationContext(
        certification_id="CERT-O",
        valid_input_ids=["INP-100"],
        differences_summary=[{"input_id": "INP-100", "target_value": 95, "reference_value": 100, "dimension": "OUTPUT"}],
        dimensions_evaluated=[BehaviorDimension.OUTPUT],
    )
    claim = GroundingClaim(
        claim_type=GroundingClaimType.NUMERIC_VALUE,
        input_id="INP-100",
        role="TARGET",
        value=97,  # False claim
    )

    is_valid, errors, validated = grounding_validator.validate_claims([claim], ctx)
    assert not is_valid
    assert any("NUMERIC_VALUE_MISMATCH" in err for err in errors)


# ==============================================================================
# Test P & Q: Conservative Dimension & Status Handling
# ==============================================================================

def test_p_no_differences_does_not_mean_pass():
    """Dimension with no difference records but missing evidence remains INCONCLUSIVE."""
    ctx = ExplanationContext(
        certification_id="CERT-P",
        dimensions_evaluated=[BehaviorDimension.OUTPUT, BehaviorDimension.STATE],
        differences_summary=[],
        missing_evidence=[MissingEvidence(dimension=BehaviorDimension.STATE, description="Missing state snapshots", implication="Inconclusive", status="INCONCLUSIVE")],
    )
    exp = deterministic_generator.generate_explanation(ctx)
    state_dim = next(d for d in exp.dimension_explanations if d.dimension == BehaviorDimension.STATE)
    assert state_dim.status == "INCONCLUSIVE"


def test_q_missing_dimension_rejected():
    """Invalid dimension like 'MAGIC_DIM' is rejected by validator without coercing to OUTPUT."""
    ctx = ExplanationContext(
        certification_id="CERT-Q",
        dimensions_evaluated=[BehaviorDimension.OUTPUT],
    )
    meta = GenerationMetadata(provider="offline", model="deterministic", generation_mode="LLM")
    raw_payload = {
        "executive_summary": "Summary",
        "dimension_explanations": [{"dimension": "MAGIC_DIM", "findings": []}]
    }

    is_valid, errors, exp = grounding_validator.validate_and_sanitize_explanation(raw_payload, ctx, meta)
    assert any("INVALID_DIMENSION" in err for err in errors)
    assert len(exp.dimension_explanations) == 0


# ==============================================================================
# Test R & S: Persistence and Audit Failure Reporting
# ==============================================================================

def test_r_persistence_failure_explicit():
    """When persistence fails, explanation reflects persistence_status = 'FAILED'."""
    store = IntelligencePersistenceStore(db_path="/invalid_dir/forbidden.sqlite3")
    store.persistence_available = False

    ctx = ExplanationContext(certification_id="CERT-R", dimensions_evaluated=[BehaviorDimension.OUTPUT])
    exp = deterministic_generator.generate_explanation(ctx)
    saved = store.save_explanation(exp)

    assert saved.persistence_status == "FAILED"


def test_s_audit_failure_explicit():
    """When audit persistence fails, log_audit_event returns False."""
    store = IntelligencePersistenceStore(db_path="/invalid_dir/forbidden.sqlite3")
    store.persistence_available = False

    success = store.log_audit_event(
        audit_id="AUD-S", user_id="user_s", certification_id="CERT-S",
        application_id="app_s", mode="DETERMINISTIC", provider="offline",
        model="deterministic", context_fingerprint="fp_s", fallback_used=False
    )
    assert success is False


# ==============================================================================
# Test T & U: Explanation Identity and Deterministic Fingerprint
# ==============================================================================

def test_t_explanation_identity():
    """Same certification with distinct contexts yields distinct explanation IDs."""
    ctx1 = ExplanationContext(certification_id="CERT-T", equivalence_score=0.5, differences_summary=[{"input_id": "INP-1", "dimension": "OUTPUT"}])
    ctx2 = ExplanationContext(certification_id="CERT-T", equivalence_score=0.9, differences_summary=[{"input_id": "INP-2", "dimension": "OUTPUT"}])

    exp1 = deterministic_generator.generate_explanation(ctx1)
    exp2 = deterministic_generator.generate_explanation(ctx2)

    assert exp1.explanation_id != exp2.explanation_id
    assert exp1.cache_key != exp2.cache_key


def test_u_deterministic_context_fingerprint():
    """Same authoritative context constructed twice yields identical context fingerprint."""
    ctx1 = ExplanationContext(certification_id="CERT-U", equivalence_score=0.8, valid_evidence_ids=["E-1", "E-2"])
    ctx2 = ExplanationContext(certification_id="CERT-U", equivalence_score=0.8, valid_evidence_ids=["E-2", "E-1"])

    assert ctx1.compute_context_fingerprint() == ctx2.compute_context_fingerprint()


# ==============================================================================
# Test V & W: Phase 9 Optionality and Domain Agnosticity
# ==============================================================================

def test_v_phase9_absent_works_normally():
    """When company knowledge is absent, Phase 10 operates normally without errors."""
    ctx = ExplanationContext(certification_id="CERT-V", dimensions_evaluated=[BehaviorDimension.OUTPUT], knowledge_context=None)
    exp = deterministic_generator.generate_explanation(ctx)
    assert exp.overall_verdict is not None
    assert exp.company_knowledge_context is None


def test_w_domain_independence():
    """Generic input values (x, y, z) evaluated with zero domain coupling."""
    diff = BehaviorDifference(
        difference_id="DIFF-W",
        dimension=BehaviorDimension.OUTPUT,
        difference_type=DifferenceType.OUTPUT_VALUE_MISMATCH,
        input_id="inp_alpha",
        reference_value={"x": 10, "state_flag": True},
        target_value={"x": 20, "state_flag": True},
    )
    eval_res = EvaluationResult(
        evaluation_id="EVAL-W",
        application_id="generic_service_omega",
        verdict=EvaluationVerdict.DIFFERENT,
        status=EvaluationVerdict.DIFFERENT,
        differences=[diff],
    )

    ctx = explanation_context_builder.build_context("CERT-W", evaluation_result=eval_res, use_company_knowledge=False)
    exp = deterministic_generator.generate_explanation(ctx)

    assert exp.overall_verdict == "DIFFERENT"
    assert exp.application_id == "generic_service_omega"


# ==============================================================================
# Complete Data Chain Integration Test (Section 42)
# ==============================================================================

def test_complete_phase3_to_10_data_chain_integration():
    """Direct integration test verifying authoritative flow:
    Phase 3 Evidence -> Phase 4 Evaluation -> Phase 7 OracleSet -> Phase 8 Threshold -> Phase 10 Context -> Explanation.
    """
    # 1. Phase 3 Evidence
    rec_ref = EvidenceRecord(
        evidence_id="EVID-CHAIN-REF-01",
        session_id="SESS-CHAIN-01",
        role="reference",
        input_id="INP-CHAIN-01",
        evidence_type=EvidenceType.OUTPUT,
        content_hash="h_chain_ref",
        size_bytes=64,
        capture_status="CAPTURED",
    )
    rec_tgt = EvidenceRecord(
        evidence_id="EVID-CHAIN-TGT-01",
        session_id="SESS-CHAIN-01",
        role="target",
        input_id="INP-CHAIN-01",
        evidence_type=EvidenceType.OUTPUT,
        content_hash="h_chain_tgt",
        size_bytes=64,
        capture_status="CAPTURED",
    )
    evidence_store.save_record(rec_ref)
    evidence_store.save_record(rec_tgt)

    # 2. Phase 4 Evaluation
    diff = BehaviorDifference(
        difference_id="DIFF-CHAIN-01",
        dimension=BehaviorDimension.OUTPUT,
        difference_type=DifferenceType.NUMERIC_TOLERANCE_EXCEEDED,
        input_id="INP-CHAIN-01",
        reference_value=100.0,
        target_value=95.0,
        reference_evidence_id="EVID-CHAIN-REF-01",
        target_evidence_id="EVID-CHAIN-TGT-01",
    )
    eval_result = EvaluationResult(
        evaluation_id="EVAL-CHAIN-01",
        application_id="app_chain_service",
        verdict=EvaluationVerdict.DIFFERENT,
        status=EvaluationVerdict.DIFFERENT,
        differences=[diff],
    )

    # 3. Phase 7 OracleSet
    rule = OracleRule(
        rule_id="RULE-CHAIN-01",
        rule_type="invariant",
        canonical_expression="input.amount > 0 -> output.total == input.amount",
        source=RuleProvenanceSource.USER_DEFINED,
        confidence=1.0,
        support_count=100,
        fingerprint="fp_rule_chain_01",
    )
    oset = OracleSet(
        oracle_set_id="OSET-CHAIN-01",
        application_id="app_chain_service",
        version=1,
        status=OracleSetStatus.READY,
        rules=[rule],
    )
    reconciliation_persistence.save_oracle_set(oset)

    # 4. Phase 8 Exact Threshold Resolution
    policy = ThresholdPolicy(
        policy_id="POL-CHAIN-01",
        version="1.0.0",
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED,
        parameters={"value": 1.0},
    )
    threshold_persistence.save_policy(policy)

    resolution = ThresholdResolution(
        resolution_id="RES-CHAIN-01",
        policy_id="POL-CHAIN-01",
        policy_version="1.0.0",
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED,
        status=ThresholdStatus.RESOLVED,
        final_value=1.0,
        sample_count=50,
        fingerprint="fp_res_chain_01",
    )
    threshold_persistence.save_resolution(resolution)

    # 5. Phase 10 Authoritative Explanation Context Synthesis
    ctx = explanation_context_builder.build_context(
        certification_id="CERT-CHAIN-01",
        evidence_records=[rec_ref, rec_tgt],
        evaluation_result=eval_result,
        oracle_set=oset,
        threshold_resolution=resolution,
        use_company_knowledge=False,
    )

    # 6. Verify Context Correctness
    assert ctx.authoritative_verdict == "DIFFERENT"
    assert "EVID-CHAIN-REF-01" in ctx.valid_evidence_ids
    assert "EVID-CHAIN-TGT-01" in ctx.valid_evidence_ids
    assert "RULE-CHAIN-01" in ctx.valid_rule_ids
    assert "INP-CHAIN-01" in ctx.valid_input_ids
    assert ctx.thresholds_context[0]["resolved_threshold"] == 1.0
    assert ctx.thresholds_context[0]["resolution_fingerprint"] == "fp_res_chain_01"

    # 7. Generate Deterministic Explanation
    explanation = deterministic_generator.generate_explanation(ctx)

    assert explanation.overall_verdict == "DIFFERENT"
    assert len(explanation.dimension_explanations) > 0
    out_dim = next(d for d in explanation.dimension_explanations if d.dimension == BehaviorDimension.OUTPUT)
    assert out_dim.status == "DIFFERENT"
    assert out_dim.findings[0].reference_value == 100.0
    assert out_dim.findings[0].target_value == 95.0


# ==============================================================================
# Additional Adversarial & Structural Verification Tests (Section 31)
# ==============================================================================

def test_unknown_evidence_role_inconclusive():
    """When evidence record role is unknown/ambiguous, role is not inferred or guessed."""
    rec = EvidenceRecord(
        evidence_id="EVID-UNKNOWN-ROLE-1",
        session_id="SESS-UNK",
        role="unspecified_ambiguous_role",
        input_id="INP-UNK",
        evidence_type=EvidenceType.OUTPUT,
        content_hash="h_unk",
        size_bytes=10,
        capture_status="CAPTURED",
    )
    evidence_store.save_record(rec)

    art = CertificationArtifact(
        certification_id="CERT-UNK-ROLE",
        project_id="app_unk",
        status=CertificationStatus.NOT_CERTIFIED,
        score=0.5,
        regressions=[
            BehavioralRegression(
                regression_id="REG-UNK",
                oracle_id="RULE-1",
                input_id="INP-UNK",
                input_values={"a": 1},
                expected_behavior=1,
                legacy_output=1,
                modern_output=2,
                failed_assertion="1 == 2",
                evidence_ids=["EVID-UNKNOWN-ROLE-1"],
            )
        ],
        metrics=CertificationMetrics(unique_input_count=1, matching_case_count=0, regression_case_count=1),
    )

    ctx = explanation_context_builder.build_context("CERT-UNK-ROLE", artifact=art, use_company_knowledge=False)
    diff = ctx.differences_summary[0]
    # Role cannot be established from metadata, so neither ref nor tgt is assigned
    assert diff["reference_evidence_id"] is None
    assert diff["target_evidence_id"] is None


def test_nonfunctional_dimension_preserved():
    """When Phase 4 evaluates NONFUNCTIONAL dimension, Phase 10 strictly preserves it."""
    diff = BehaviorDifference(
        difference_id="DIFF-NONFUNC-1",
        dimension=BehaviorDimension.NONFUNCTIONAL,
        difference_type=DifferenceType.OUTPUT_VALUE_MISMATCH,
        input_id="INP-NF-1",
        reference_value="12ms",
        target_value="450ms",
        details={"metric": "latency", "threshold_ms": 100},
    )
    eval_res = EvaluationResult(
        evaluation_id="EVAL-NF-1",
        application_id="perf_service",
        verdict=EvaluationVerdict.DIFFERENT,
        status=EvaluationVerdict.DIFFERENT,
        differences=[diff],
    )

    ctx = explanation_context_builder.build_context("CERT-NF", evaluation_result=eval_res, use_company_knowledge=False)
    assert ctx.differences_summary[0]["dimension"] == "NONFUNCTIONAL"
    assert BehaviorDimension.NONFUNCTIONAL in ctx.dimensions_evaluated

    exp = deterministic_generator.generate_explanation(ctx)
    nf_dim = next((d for d in exp.dimension_explanations if d.dimension == BehaviorDimension.NONFUNCTIONAL), None)
    assert nf_dim is not None
    assert nf_dim.status == "DIFFERENT"


def test_state_evidence_projected_with_delta():
    """Actual database state evidence records are projected into ExplanationContext."""
    rec_state = EvidenceRecord(
        evidence_id="EVID-DB-STATE-1",
        session_id="SESS-STATE-1",
        role="target",
        input_id="INP-STATE-1",
        evidence_type=EvidenceType.DATABASE,
        content_hash="h_db_state",
        size_bytes=128,
        capture_status="CAPTURED",
        payload={"table": "accounts", "mutation": "UPDATE balance SET amount = 500 WHERE id = 1"},
    )
    evidence_store.save_record(rec_state)

    ctx = explanation_context_builder.build_context(
        certification_id="CERT-STATE-EVID",
        evidence_records=[rec_state],
        use_company_knowledge=False,
    )

    # State missing evidence must NOT be marked inconclusive because state records were collected
    state_missing = next((m for m in ctx.missing_evidence if m.dimension == BehaviorDimension.STATE), None)
    assert state_missing is None
    assert "EVID-DB-STATE-1" in ctx.valid_evidence_ids


def test_workflow_trace_projected_with_steps():
    """Actual trace execution evidence is recognized and prevents missing workflow inconclusive flag."""
    rec_trace = EvidenceRecord(
        evidence_id="EVID-TRACE-01",
        session_id="SESS-TRACE-01",
        role="target",
        input_id="INP-TR-1",
        evidence_type=EvidenceType.TRACE,
        content_hash="h_trace",
        size_bytes=256,
        capture_status="CAPTURED",
        payload={"spans": [{"name": "auth_check", "status": "OK"}, {"name": "process_tx", "status": "FAILED"}]},
    )
    evidence_store.save_record(rec_trace)

    ctx = explanation_context_builder.build_context(
        certification_id="CERT-TRACE-EVID",
        evidence_records=[rec_trace],
        use_company_knowledge=False,
    )

    wf_missing = next((m for m in ctx.missing_evidence if m.dimension == BehaviorDimension.WORKFLOW), None)
    assert wf_missing is None
    assert "EVID-TRACE-01" in ctx.valid_evidence_ids


def test_claim_specific_evidence_grounding():
    """Claim referencing valid but unassociated evidence fails grounding validation."""
    ctx = ExplanationContext(
        certification_id="CERT-CLAIM-SPEC",
        valid_evidence_ids=["EVID-VAL-1", "EVID-VAL-2"],
        valid_input_ids=["INP-001"],
        differences_summary=[
            {
                "input_id": "INP-001",
                "reference_value": 100,
                "target_value": 95,
                "evidence_ids": ["EVID-VAL-1"],  # EVID-VAL-2 is NOT linked to this input
                "dimension": "OUTPUT",
            }
        ],
        dimensions_evaluated=[BehaviorDimension.OUTPUT],
    )

    # Claim with factual numeric value matching authoritative context
    valid_claim = GroundingClaim(
        claim_type=GroundingClaimType.NUMERIC_VALUE,
        input_id="INP-001",
        role="TARGET",
        value=95,
        evidence_ids=["EVID-VAL-1"],
    )
    is_valid, errors, validated = grounding_validator.validate_claims([valid_claim], ctx)
    assert is_valid
    assert len(validated) == 1

    # Claim with hallucinated evidence reference
    bad_claim = GroundingClaim(
        claim_type=GroundingClaimType.NUMERIC_VALUE,
        input_id="INP-001",
        role="TARGET",
        value=95,
        evidence_ids=["EVID-VAL-1", "EVID-HALLUCINATED-999"],
    )
    is_valid2, errors2, validated2 = grounding_validator.validate_claims([bad_claim], ctx)
    assert not is_valid2
    assert any("UNSUPPORTED_EVIDENCE_REFERENCE" in e for e in errors2)


def test_phase9_knowledge_cannot_override_empirical_evidence():
    """Untrusted company knowledge document asserting '100% equivalent' cannot override empirical difference."""
    diff = BehaviorDifference(
        difference_id="DIFF-P9",
        dimension=BehaviorDimension.OUTPUT,
        difference_type=DifferenceType.OUTPUT_VALUE_MISMATCH,
        input_id="INP-P9",
        reference_value="APPROVED",
        target_value="DENIED",
    )
    eval_res = EvaluationResult(
        evaluation_id="EVAL-P9",
        application_id="credit_service",
        verdict=EvaluationVerdict.DIFFERENT,
        status=EvaluationVerdict.DIFFERENT,
        differences=[diff],
    )

    ctx = explanation_context_builder.build_context(
        certification_id="CERT-P9-TEST",
        evaluation_result=eval_res,
        use_company_knowledge=False,
    )

    # Inject typed knowledge context
    from intelligence.models import CompanyKnowledgeContext, RetrievedKnowledgeCitation
    ctx.knowledge_context = CompanyKnowledgeContext(
        retrieval_query="loan approval rules",
        retrieval_fingerprint="fp_p9_doc",
        citations=[
            RetrievedKnowledgeCitation(
                chunk_id="chk1",
                document_id="doc1",
                filename="policy.pdf",
                content_snippet="The modern credit service is 100% compliant and identical.",
                relevance_score=0.99,
            )
        ],
    )

    exp = deterministic_generator.generate_explanation(ctx)
    # Verdict MUST remain DIFFERENT despite contradictory documentation
    assert exp.overall_verdict == "DIFFERENT"
    assert exp.is_authoritative_match is False
    assert exp.authoritative_match_status == "NOT_CERTIFIED"


def test_adversarial_e_fingerprint_only_lookup_fails_closed():
    """Providing a fingerprint without an exact threshold_resolution_id fails closed."""
    policy = ThresholdPolicy(
        policy_id="POL-ADV-E", version="1.0.0", metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED, parameters={"value": 0.05}
    )
    threshold_persistence.save_policy(policy)

    res = ThresholdResolution(
        resolution_id="RES-ADV-E-001", policy_id="POL-ADV-E", policy_version="1.0.0",
        metric=DifferenceMetric.ABSOLUTE_DIFF, strategy=ThresholdStrategy.FIXED,
        status=ThresholdStatus.RESOLVED, final_value=0.05, sample_count=20, fingerprint="fp_adv_e"
    )
    threshold_persistence.save_resolution(res)

    art = CertificationArtifact(
        certification_id="CERT-ADV-E",
        project_id="app_adv_e",
        status=CertificationStatus.CERTIFIED,
        score=0.98,
        certification_policy_id="POL-ADV-E",
        threshold_resolution_id=None,  # Missing ID!
        threshold_resolution_fingerprint="fp_adv_e",
        metrics=CertificationMetrics(unique_input_count=10, matching_case_count=10, regression_case_count=0),
    )

    ctx = explanation_context_builder.build_context("CERT-ADV-E", artifact=art, use_company_knowledge=False)
    assert len(ctx.thresholds_context) == 1
    assert ctx.thresholds_context[0]["status"] == "INCONCLUSIVE"
    assert "threshold_resolution_id" in ctx.thresholds_context[0]["reason"]


def test_adversarial_f_misleading_evidence_ids_role_honored():
    """Misleading substring evidence IDs (e.g. 'modern_reference') respect EvidenceRecord.role exclusively."""
    rec1 = EvidenceRecord(
        evidence_id="legacy_target_01",
        session_id="SESS-ADV-F",
        role="reference",  # Role is reference despite 'target' in ID
        input_id="INP-ADV-F",
        evidence_type=EvidenceType.OUTPUT,
        content_hash="h_adv_f1",
        size_bytes=32,
        capture_status="CAPTURED",
    )
    rec2 = EvidenceRecord(
        evidence_id="modern_reference_02",
        session_id="SESS-ADV-F",
        role="target",  # Role is target despite 'reference' in ID
        input_id="INP-ADV-F",
        evidence_type=EvidenceType.OUTPUT,
        content_hash="h_adv_f2",
        size_bytes=32,
        capture_status="CAPTURED",
    )
    evidence_store.save_record(rec1)
    evidence_store.save_record(rec2)

    diff = BehaviorDifference(
        difference_id="DIFF-ADV-F",
        dimension=BehaviorDimension.OUTPUT,
        difference_type=DifferenceType.OUTPUT_VALUE_MISMATCH,
        input_id="INP-ADV-F",
        reference_value="A",
        target_value="B",
        evidence_ids=["legacy_target_01", "modern_reference_02"],
    )
    eval_res = EvaluationResult(
        evaluation_id="EVAL-ADV-F",
        application_id="adv_f_service",
        verdict=EvaluationVerdict.DIFFERENT,
        status=EvaluationVerdict.DIFFERENT,
        differences=[diff],
    )

    ctx = explanation_context_builder.build_context(
        "CERT-ADV-F",
        evidence_records=[rec1, rec2],
        evaluation_result=eval_res,
        use_company_knowledge=False,
    )

    diff_summary = ctx.differences_summary[0]
    assert diff_summary["reference_evidence_id"] == "legacy_target_01"
    assert diff_summary["target_evidence_id"] == "modern_reference_02"


def test_adversarial_g_shuffled_evidence_records_order_independent():
    """Shuffling evidence records list has zero impact on role assignment."""
    rec_ref = EvidenceRecord(
        evidence_id="EVID-SHUFFLE-REF",
        session_id="SESS-G",
        role="reference",
        input_id="INP-G",
        evidence_type=EvidenceType.OUTPUT,
        content_hash="href_g",
        size_bytes=10,
        capture_status="CAPTURED",
    )
    rec_tgt = EvidenceRecord(
        evidence_id="EVID-SHUFFLE-TGT",
        session_id="SESS-G",
        role="target",
        input_id="INP-G",
        evidence_type=EvidenceType.OUTPUT,
        content_hash="htgt_g",
        size_bytes=10,
        capture_status="CAPTURED",
    )
    evidence_store.save_record(rec_ref)
    evidence_store.save_record(rec_tgt)

    diff = BehaviorDifference(
        difference_id="DIFF-G",
        dimension=BehaviorDimension.OUTPUT,
        difference_type=DifferenceType.OUTPUT_VALUE_MISMATCH,
        input_id="INP-G",
        reference_value=1,
        target_value=2,
        evidence_ids=["EVID-SHUFFLE-REF", "EVID-SHUFFLE-TGT"],
    )
    eval_res = EvaluationResult(
        evaluation_id="EVAL-G",
        application_id="shuffle_service",
        verdict=EvaluationVerdict.DIFFERENT,
        status=EvaluationVerdict.DIFFERENT,
        differences=[diff],
    )

    # Pass in reverse order: target first, reference second
    ctx = explanation_context_builder.build_context(
        "CERT-G",
        evidence_records=[rec_tgt, rec_ref],
        evaluation_result=eval_res,
        use_company_knowledge=False,
    )

    diff_summary = ctx.differences_summary[0]
    assert diff_summary["reference_evidence_id"] == "EVID-SHUFFLE-REF"
    assert diff_summary["target_evidence_id"] == "EVID-SHUFFLE-TGT"


def test_adversarial_k_artifact_evaluation_conflict_preserves_phase4():
    """When CertificationArtifact claims NOT_CERTIFIED but EvaluationResult proves EQUIVALENT, Phase 4 truth is preserved."""
    eval_res = EvaluationResult(
        evaluation_id="EVAL-K-CONFLICT",
        application_id="conflict_svc",
        verdict=EvaluationVerdict.EQUIVALENT,
        status=EvaluationVerdict.EQUIVALENT,
        differences=[],
        summary=EvaluationSummary(
            total_inputs=10,
            evaluated_inputs=10,
            equivalent_inputs=10,
            different_inputs=0,
            inconclusive_inputs=0,
        ),
    )
    art = CertificationArtifact(
        certification_id="CERT-K-CONFLICT",
        project_id="conflict_svc",
        status=CertificationStatus.NOT_CERTIFIED,
        score=0.2,
        metrics=CertificationMetrics(unique_input_count=10, matching_case_count=2, regression_case_count=8),
    )

    ctx = explanation_context_builder.build_context(
        "CERT-K-CONFLICT",
        artifact=art,
        evaluation_result=eval_res,
        use_company_knowledge=False,
    )

    # Phase 4 is authoritative for behavioral evaluation facts
    assert ctx.authoritative_verdict == "EQUIVALENT"
    assert ctx.matching_cases_count == 10
    assert ctx.regression_cases_count == 0


# ==============================================================================
# Cross-Phase Evidence Resolution & Projection Tests
# ==============================================================================

def test_unresolved_candidate_evidence_tracked_and_fails_grounding():
    """Unresolvable evidence ID in a difference is excluded from valid set, tracked in unresolved, and fails claim grounding."""
    # EVID-REAL is real Phase 3 record
    rec = EvidenceRecord(
        evidence_id="EVID-REAL",
        session_id="SESS-UNRES",
        role="reference",
        input_id="INP-U1",
        evidence_type=EvidenceType.OUTPUT,
        content_hash="h_u1",
        size_bytes=10,
        capture_status="CAPTURED",
    )
    evidence_store.save_record(rec)

    # Difference claims EVID-REAL and EVID-GHOST
    diff = BehaviorDifference(
        difference_id="DIFF-U1",
        dimension=BehaviorDimension.OUTPUT,
        difference_type=DifferenceType.OUTPUT_VALUE_MISMATCH,
        input_id="INP-U1",
        reference_value="A",
        target_value="B",
        reference_evidence_id="EVID-REAL",
        target_evidence_id="EVID-GHOST",  # Non-existent ghost record!
        evidence_ids=["EVID-REAL", "EVID-GHOST"],
    )
    eval_res = EvaluationResult(
        evaluation_id="EVAL-UNRES",
        verdict=EvaluationVerdict.DIFFERENT,
        status=EvaluationVerdict.DIFFERENT,
        differences=[diff],
    )

    ctx = explanation_context_builder.build_context(
        "CERT-UNRES",
        evidence_records=[rec],
        evaluation_result=eval_res,
        use_company_knowledge=False,
    )

    assert "EVID-REAL" in ctx.valid_evidence_ids
    assert "EVID-GHOST" not in ctx.valid_evidence_ids
    assert "EVID-GHOST" in ctx.unresolved_evidence_ids

    # Claim asserting EVID-GHOST is strictly rejected by grounding validator
    claim = GroundingClaim(
        claim_type=GroundingClaimType.EVIDENCE_REFERENCE,
        statement="Target behavior captured by EVID-GHOST",
        evidence_ids=["EVID-GHOST"],
    )
    is_valid, errors, validated = grounding_validator.validate_claims([claim], ctx)
    assert not is_valid
    assert any("UNSUPPORTED_EVIDENCE_REFERENCE" in err for err in errors)


def test_state_evidence_fact_projection_changes_and_no_changes():
    """Physical state evidence records (database & filesystem) are projected into StateEvidenceFacts."""
    rec_db = EvidenceRecord(
        evidence_id="EVID-DB-MUTATION",
        session_id="SESS-STATE",
        role="target",
        input_id="INP-S1",
        evidence_type=EvidenceType.DATABASE,
        payload={
            "table": "accounts",
            "table_row_counts_before": {"accounts": 100},
            "table_row_counts_after": {"accounts": 101},
            "delta": {"inserted_id": "ACC-999"},
            "delta_detected": True,
        },
        content_hash="h_db1",
        size_bytes=50,
        capture_status="CAPTURED",
    )
    rec_fs = EvidenceRecord(
        evidence_id="EVID-FS-IDENTICAL",
        session_id="SESS-STATE",
        role="reference",
        input_id="INP-S1",
        evidence_type=EvidenceType.FILESYSTEM,
        payload={
            "configured_paths": ["/tmp/data"],
            "delta_detected": False,
        },
        content_hash="h_fs1",
        size_bytes=30,
        capture_status="CAPTURED",
    )

    ctx = explanation_context_builder.build_context(
        "CERT-STATE",
        evidence_records=[rec_db, rec_fs],
        use_company_knowledge=False,
    )

    assert len(ctx.state_facts) == 2
    db_fact = next(s for s in ctx.state_facts if s.evidence_id == "EVID-DB-MUTATION")
    assert db_fact.resource == "accounts"
    assert db_fact.delta_detected is True
    assert db_fact.role == "target"

    fs_fact = next(s for s in ctx.state_facts if s.evidence_id == "EVID-FS-IDENTICAL")
    assert fs_fact.delta_detected is False
    assert fs_fact.role == "reference"

    # Explanation generation preserves state_facts
    exp = deterministic_generator.generate_explanation(ctx)
    assert len(exp.state_facts) == 2


def test_workflow_trace_fact_projection_and_qa_intent():
    """TRACE evidence records are projected into WorkflowTraceFacts and queried via Q&A."""
    rec_trace = EvidenceRecord(
        evidence_id="EVID-TRACE-01",
        session_id="SESS-TRACE",
        role="target",
        input_id="INP-W1",
        evidence_type=EvidenceType.TRACE,
        payload={
            "events": [
                {"sequence": 1, "event_type": "VALIDATE_INPUT", "details": {"action": "schema_validation"}},
                {"sequence": 2, "event_type": "INVOKE_PAYMENT", "details": {"action": "charge_card", "divergence": "card_type_mismatch"}},
            ]
        },
        content_hash="h_trace1",
        size_bytes=80,
        capture_status="CAPTURED",
    )

    ctx = explanation_context_builder.build_context(
        "CERT-TRACE",
        evidence_records=[rec_trace],
        use_company_knowledge=False,
    )

    assert len(ctx.workflow_facts) == 2
    step2 = next(w for w in ctx.workflow_facts if w.sequence == 2)
    assert step2.event_type == "INVOKE_PAYMENT"
    assert step2.observed_divergence == "card_type_mismatch"

    # Q&A intent routing for workflow
    ans = intelligence_engine.ask_certification(
        certification_id="CERT-TRACE",
        question="Which workflow step differed in execution?",
        evidence_records=[rec_trace],
        use_company_knowledge=False,
        preferred_provider="offline",
    )
    assert "INVOKE_PAYMENT" in ans.answer or "VALIDATE_INPUT" in ans.answer
    assert "EVID-TRACE-01" in ans.referenced_evidence_ids


def test_qa_intent_routing_threshold():
    """Threshold questions route to exact ThresholdResolution authority."""
    res = ThresholdResolution(
        resolution_id="RES-QA-THRESH",
        policy_id="POL-QA",
        policy_version="1.0.0",
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED,
        status=ThresholdStatus.RESOLVED,
        final_value=0.045,
        sample_count=100,
        fingerprint="fp_qa_thresh",
        fallback_used=True,
        fallback_reason="Bootstrap sample window was small",
    )
    threshold_persistence.save_resolution(res)

    art = CertificationArtifact(
        certification_id="CERT-QA-THRESH",
        project_id="qa_app",
        status=CertificationStatus.CERTIFIED,
        score=0.99,
        certification_policy_id="POL-QA",
        threshold_resolution_id="RES-QA-THRESH",
        threshold_resolution_fingerprint="fp_qa_thresh",
        metrics=CertificationMetrics(unique_input_count=10, matching_case_count=10, regression_case_count=0),
    )

    ans = intelligence_engine.ask_certification(
        certification_id="CERT-QA-THRESH",
        question="What threshold was used for this certification?",
        artifact=art,
        threshold_resolution=res,
        use_company_knowledge=False,
        preferred_provider="offline",
    )
    assert "0.045" in ans.answer
    assert "RES-QA-THRESH" in ans.answer
    assert "Bootstrap sample window was small" in ans.answer


def test_is_authoritative_match_three_states():
    """Verify distinct is_authoritative_match and authoritative_match_status values across all verdict types."""
    # 1. CERTIFIED -> True, CERTIFIED
    art_pass = CertificationArtifact(
        certification_id="CERT-P", project_id="app_p", status=CertificationStatus.CERTIFIED,
        score=1.0, metrics=CertificationMetrics(unique_input_count=5, matching_case_count=5, regression_case_count=0),
    )
    ctx_pass = explanation_context_builder.build_context("CERT-P", artifact=art_pass, use_company_knowledge=False)
    exp_pass = deterministic_generator.generate_explanation(ctx_pass)
    assert exp_pass.is_authoritative_match is True
    assert exp_pass.authoritative_match_status == "CERTIFIED"

    # 2. NOT_CERTIFIED -> False, NOT_CERTIFIED
    art_fail = CertificationArtifact(
        certification_id="CERT-F", project_id="app_f", status=CertificationStatus.NOT_CERTIFIED,
        score=0.0, metrics=CertificationMetrics(unique_input_count=5, matching_case_count=0, regression_case_count=5),
    )
    ctx_fail = explanation_context_builder.build_context("CERT-F", artifact=art_fail, use_company_knowledge=False)
    exp_fail = deterministic_generator.generate_explanation(ctx_fail)
    assert exp_fail.is_authoritative_match is False
    assert exp_fail.authoritative_match_status == "NOT_CERTIFIED"

    # 3. INCONCLUSIVE -> False, INCONCLUSIVE
    eval_incon = EvaluationResult(
        evaluation_id="EVAL-INCON",
        verdict=EvaluationVerdict.INCONCLUSIVE,
        status=EvaluationVerdict.INCONCLUSIVE,
    )
    ctx_incon = explanation_context_builder.build_context("CERT-I", evaluation_result=eval_incon, use_company_knowledge=False)
    exp_incon = deterministic_generator.generate_explanation(ctx_incon)
    assert exp_incon.is_authoritative_match is False
    assert exp_incon.authoritative_match_status == "INCONCLUSIVE"


def test_full_real_end_to_end_phase3_to_phase10_chain():
    """Real end-to-end integration: Phase 3 -> Phase 4 -> Phase 7 -> Phase 8 -> Certification -> Phase 10 Explanation -> Validation -> Persistence -> Audit."""
    from certification.certification_engine import CertificationEngine
    from certification.models import CertificationContext, CertificationPolicy
    from execution.evidence_models import EvidenceManifest, EvidenceManifestItem

    # 1. Phase 3: Create real paired evidence
    rec_ref = EvidenceRecord(
        evidence_id="EVID-E2E-REF-01",
        session_id="SESS-E2E",
        role="reference",
        input_id="INP-E2E-1",
        evidence_type=EvidenceType.OUTPUT,
        payload={"output": {"price": 100}},
        content_hash="h_e2e_ref",
        size_bytes=30,
        capture_status="CAPTURED",
    )
    rec_tgt = EvidenceRecord(
        evidence_id="EVID-E2E-TGT-01",
        session_id="SESS-E2E",
        role="target",
        input_id="INP-E2E-1",
        evidence_type=EvidenceType.OUTPUT,
        payload={"output": {"price": 100}},
        content_hash="h_e2e_tgt",
        size_bytes=30,
        capture_status="CAPTURED",
    )
    evidence_store.save_record(rec_ref)
    evidence_store.save_record(rec_tgt)
    manifest = EvidenceManifest(
        session_id="SESS-E2E",
        correlation_id="CORR-E2E",
        application_id="e2e_app",
        input_set_id="INP-SET-E2E",
        input_set_hash="h_inp_set_e2e",
        items=[
            EvidenceManifestItem(
                evidence_id="EVID-E2E-REF-01",
                evidence_type=EvidenceType.OUTPUT,
                role="reference",
                input_id="INP-E2E-1",
                content_hash="h_e2e_ref",
                size_bytes=30,
                capture_status=EvidenceCaptureStatus.CAPTURED,
                persistence_status=EvidencePersistenceStatus.PERSISTED,
            ),
            EvidenceManifestItem(
                evidence_id="EVID-E2E-TGT-01",
                evidence_type=EvidenceType.OUTPUT,
                role="target",
                input_id="INP-E2E-1",
                content_hash="h_e2e_tgt",
                size_bytes=30,
                capture_status=EvidenceCaptureStatus.CAPTURED,
                persistence_status=EvidencePersistenceStatus.PERSISTED,
            ),
        ],
    )
    bundle = EvidenceBundle(
        bundle_id="BUNDLE-E2E",
        session_id="SESS-E2E",
        correlation_id="CORR-E2E",
        application_id="e2e_app",
        input_set_id="INP-SET-E2E",
        manifest=manifest,
        records=[rec_ref, rec_tgt],
    )
    evidence_store.save_bundle(bundle)

    # 2. Phase 4: Create EvaluationResult with nonfunctional dimension preserved
    eval_res = EvaluationResult(
        evaluation_id="EVAL-E2E-01",
        application_id="e2e_app",
        verdict=EvaluationVerdict.EQUIVALENT,
        status=EvaluationVerdict.EQUIVALENT,
        dimensions_evaluated=[BehaviorDimension.OUTPUT, BehaviorDimension.NONFUNCTIONAL],
        differences=[],
        summary=EvaluationSummary(
            total_inputs=1,
            evaluated_inputs=1,
            equivalent_inputs=1,
            different_inputs=0,
            inconclusive_inputs=0,
            dimension_summaries={
                BehaviorDimension.OUTPUT: DimensionEvaluationSummary(
                    dimension=BehaviorDimension.OUTPUT,
                    total_evaluated=1,
                    equivalent_count=1,
                    different_count=0,
                    overall_verdict=EvaluationVerdict.EQUIVALENT,
                ),
                BehaviorDimension.NONFUNCTIONAL: DimensionEvaluationSummary(
                    dimension=BehaviorDimension.NONFUNCTIONAL,
                    total_evaluated=1,
                    equivalent_count=1,
                    different_count=0,
                    overall_verdict=EvaluationVerdict.EQUIVALENT,
                ),
            },
        ),
    )

    # 3. Phase 7: Create and persist OracleSet
    rule = OracleRule(
        rule_id="RULE-E2E-1",
        rule_type="invariant",
        canonical_expression="price == 100",
        source=RuleProvenanceSource.DISCOVERED,
        confidence=1.0,
        support_count=10,
        fingerprint="fp_rule_e2e",
    )
    oset = OracleSet(
        oracle_set_id="OSET-E2E-01",
        application_id="e2e_app",
        version=1,
        status=OracleSetStatus.READY,
        rules=[rule],
    )
    reconciliation_persistence.save_oracle_set(oset)

    # 4. Phase 8: Create and persist ThresholdResolution
    policy = ThresholdPolicy(
        policy_id="POL-E2E",
        version="1.0.0",
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED,
        parameters={"value": 0.05},
    )
    threshold_persistence.save_policy(policy)

    thresh_res = ThresholdResolution(
        resolution_id="RES-E2E-01",
        policy_id="POL-E2E",
        policy_version="1.0.0",
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED,
        status=ThresholdStatus.RESOLVED,
        final_value=0.05,
        sample_count=50,
        fingerprint="fp_res_e2e_01",
    )
    threshold_persistence.save_resolution(thresh_res)

    # 5. Certification: Run certify() with real Phase 8 resolution bound
    cert_engine = CertificationEngine()
    cert_ctx = CertificationContext(
        certification_id="CERT-E2E-FULL-01",
        project_id="e2e_app",
        session_id="SESS-E2E",
        policy=CertificationPolicy(policy_id="POL-E2E", max_allowed_regressions=0, min_equivalence_score=0.95),
        created_at="2026-09-17T00:00:00Z",
        created_by="e2e_tester",
    )
    artifact = cert_engine.certify(
        context=cert_ctx,
        evaluation_result=eval_res,
        oracle_set=oset,
        threshold_resolution=thresh_res,
    )

    # Assert immutably bound in CertificationArtifact
    assert artifact.threshold_resolution_id == "RES-E2E-01"
    assert artifact.threshold_resolution_fingerprint == "fp_res_e2e_01"

    # 6. Phase 10: Build ExplanationContext
    exp_ctx = explanation_context_builder.build_context(
        certification_id="CERT-E2E-FULL-01",
        artifact=artifact,
        evidence_bundle=bundle,
        evaluation_result=eval_res,
        oracle_set=oset,
        threshold_resolution=thresh_res,
        use_company_knowledge=False,
    )

    # Assert exact identity binding equality across entire chain
    assert thresh_res.resolution_id == artifact.threshold_resolution_id == exp_ctx.thresholds_context[0]["resolution_id"]
    assert thresh_res.fingerprint == artifact.threshold_resolution_fingerprint == exp_ctx.thresholds_context[0]["resolution_fingerprint"]

    # 7. Generate explanation, validate, persist and audit
    explanation = intelligence_engine.generate_explanation(
        certification_id="CERT-E2E-FULL-01",
        request=ExplanationRequest(mode="deterministic", use_company_knowledge=False),
        artifact=artifact,
        evidence_bundle=bundle,
        evaluation_result=eval_res,
        oracle_set=oset,
        threshold_resolution=thresh_res,
        user_id="e2e_tester",
    )

    assert explanation.overall_verdict == "EQUIVALENT"
    assert explanation.is_authoritative_match is True
    assert explanation.authoritative_match_status == "CERTIFIED"
    assert explanation.persistence_status == "SUCCESS"
    assert BehaviorDimension.NONFUNCTIONAL in [d.dimension for d in explanation.dimension_explanations]


def test_missing_threshold_resolution_fails_closed_in_v2_direct_path():
    """Mandatory Master Test: EvaluationResult has 0 differences, ThresholdResolution is None.
    
    Strict V2 CertificationEngine MUST produce INCONCLUSIVE / Fail-Closed.
    It MUST NOT produce CERTIFIED or an implicit perfect score.
    """
    eval_res = EvaluationResult(
        evaluation_id="EVAL-ZERO-DIFF",
        application_id="app_zero_diff",
        run_id="RUN-ZERO-DIFF",
        verdict=EvaluationVerdict.EQUIVALENT,
        summary=EvaluationSummary(
            total_inputs=10,
            evaluated_inputs=10,
            equivalent_inputs=10,
            different_inputs=0,
            inconclusive_inputs=0,
            equivalence_score=1.0,
            total_differences=0,
        ),
        input_results=[
            InputEvaluationResult(
                input_id=f"inp_{i}",
                verdict=EvaluationVerdict.EQUIVALENT,
                status=EvaluationVerdict.EQUIVALENT,
                differences=[],
            ) for i in range(10)
        ],
        differences=[],
    )

    cert_engine = CertificationEngine()
    cert_ctx = CertificationContext(
        certification_id="CERT-NO-THRESH",
        project_id="app_zero_diff",
        evaluation_mode="CONTROLLED",
    )

    # Call certify with zero differences but NO ThresholdResolution
    artifact = cert_engine.certify(
        context=cert_ctx,
        evaluation_result=eval_res,
        threshold_resolution=None,
    )

    # Must be INCONCLUSIVE and NOT CERTIFIED
    assert artifact.status == CertificationStatus.INCONCLUSIVE
    assert artifact.certified is False
    assert artifact.score == 0.0
    assert len(artifact.blocking_reasons) > 0
    assert "ThresholdResolution" in artifact.blocking_reasons[0]


def test_missing_evaluation_result_fails_closed_in_v2_direct_path():
    """Mandatory Test: EvaluationResult is None, ThresholdResolution is valid.
    
    Strict V2 CertificationEngine MUST produce INCONCLUSIVE / Fail-Closed.
    It MUST NOT produce CERTIFIED or an implicit score of 1.0 or fake 0 regressions.
    ExplanationContext MUST represent metrics as None/unavailable, not fake numeric facts.
    """
    thresh_res = ThresholdResolution(
        resolution_id="RES-VALID-101",
        policy_id="POL-101",
        policy_version="1.0.0",
        metric=DifferenceMetric.PERCENTAGE_DIFF,
        strategy=ThresholdStrategy.FIXED,
        final_value=0.05,
        status=ThresholdStatus.RESOLVED,
        fingerprint="fp_valid_101",
        sample_count=100,
        effective_threshold=0.05,
    )

    cert_engine = CertificationEngine()
    cert_ctx = CertificationContext(
        certification_id="CERT-NO-EVAL",
        project_id="app_no_eval",
        evaluation_mode="CONTROLLED",
    )

    # 1. CertificationEngine with EvaluationResult = None
    artifact = cert_engine.certify(
        context=cert_ctx,
        evaluation_result=None,
        threshold_resolution=thresh_res,
    )

    assert artifact.status == CertificationStatus.INCONCLUSIVE
    assert artifact.certified is False
    assert artifact.score == 0.0
    assert len(artifact.blocking_reasons) > 0
    assert "EvaluationResult" in artifact.blocking_reasons[0]

    # 2. ExplanationContextBuilder with EvaluationResult = None in strict V2
    ctx = explanation_context_builder.build_context(
        certification_id="CERT-NO-EVAL",
        artifact=artifact,
        evaluation_result=None,
        threshold_resolution=thresh_res,
        execution_mode="v2",
        use_company_knowledge=False,
    )

    assert ctx.authoritative_verdict == "INCONCLUSIVE"
    assert ctx.unique_inputs_count is None
    assert ctx.matching_cases_count is None
    assert ctx.regression_cases_count is None
    assert ctx.equivalence_score is None

    # Must contain missing evaluation evidence disclosure
    missing_outputs = [m for m in ctx.missing_evidence if m.dimension == BehaviorDimension.OUTPUT]
    assert len(missing_outputs) > 0
    assert "EvaluationResult" in missing_outputs[0].description

    # 3. DeterministicExplanationGenerator with missing EvaluationResult context
    exp = deterministic_generator.generate_explanation(ctx)
    assert exp.overall_verdict == "INCONCLUSIVE"
    assert exp.is_authoritative_match is False
    assert exp.authoritative_match_status == "INCONCLUSIVE"
    assert exp.scope_summary.get("evaluated_inputs") is None
    assert exp.scope_summary.get("equivalence_score") is None
    assert "unavailable" in exp.behavioral_summary.lower()



