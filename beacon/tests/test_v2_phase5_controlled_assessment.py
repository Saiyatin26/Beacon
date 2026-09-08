"""BEACON V2 — Phase 5 Controlled Mode Assessment Integration Tests.

Validates end-to-end evaluation of user-defined business rules over Phase 3 evidence
bundles and Phase 4 behavioral results, proving conservative aggregation, false-pass
elimination, three-valued applicability, evidence sufficiency preconditions, traceability,
and deterministic reproducibility.
"""

from pathlib import Path
import sys
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api.main import app
from auth import create_access_token
from evaluation.engine import behavioral_evaluation_engine
from evaluation.models import BehaviorDimension, EvaluationVerdict
from evaluation.policies import DEFAULT_COMPARISON_POLICY
from execution.evidence_models import (
    DatabaseEvidence,
    EvidenceBundle,
    EvidenceCaptureStatus,
    EvidenceManifest,
    EvidenceRecord,
    EvidenceType,
    FileEvidence,
    FileStateSnapshot,
    HttpEvidence,
    OutputEvidence,
    TraceEvidence,
)
from rules.engine import controlled_assessment_engine
from rules.models import (
    BusinessRule,
    ExpectedBehavior,
    ExpectedBehaviorType,
    RuleComplianceVerdict,
    RuleOperator,
    RulePredicate,
    RuleSeverity,
)
from rules.registry import RulePersistenceError, rule_registry


class TestPhase5ControlledModeAssessment:
    """Tests Controlled Mode rule compliance evaluation over Phase 3 evidence and Phase 4 results."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture(autouse=True)
    def clean_registry(self):
        rule_registry.clear()
        yield
        rule_registry.clear()

    # 1. BOTH REFERENCE AND TARGET COMPLY (PASS)
    def test_e2e_both_implementations_comply_yields_pass(self):
        """When both Ref and Target satisfy the expected behavior, rule assessment yields PASS."""
        session_id = "sess_p5_1"
        app_id = "app_p5_1"

        # Evidence for input 'inp_adult' with age=25
        rec_r = EvidenceRecord(
            evidence_id="r_out_1",
            session_id=session_id,
            input_id="inp_adult",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "ELIGIBLE", "http_status": 200}, "normalized_output": {"status": "ELIGIBLE", "http_status": 200}, "age": 25},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_out_1",
            session_id=session_id,
            input_id="inp_adult",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "ELIGIBLE", "http_status": 200}, "normalized_output": {"status": "ELIGIBLE", "http_status": 200}, "age": 25},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_1",
            session_id=session_id,
            correlation_id="c_p5_1",
            application_id=app_id,
            input_set_id="is_p5_1",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_1", application_id=app_id, input_set_id="is_p5_1", input_set_hash="h_1", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        # Rule: IF age >= 18 THEN ACCEPT
        rule = BusinessRule(
            rule_id="RULE-AGE-01",
            name="Adult Age Eligibility",
            condition=RulePredicate(field="age", operator=RuleOperator.GTE, value=18),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        # Execute Phase 4
        p4_res = behavioral_evaluation_engine.evaluate_bundle(bundle, policy=DEFAULT_COMPARISON_POLICY)
        assert p4_res.verdict == EvaluationVerdict.EQUIVALENT

        # Execute Phase 5 Controlled Mode
        res = controlled_assessment_engine.evaluate_controlled_mode(
            rules=[rule],
            bundle=bundle,
            phase4_result=p4_res,
        )

        assert res.overall_verdict == RuleComplianceVerdict.PASS
        assert len(res.rule_assessments) == 1
        assm = res.rule_assessments[0]
        assert assm.applicability == "APPLICABLE"
        assert assm.condition_satisfied is True
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS
        assert assm.overall_rule_status == RuleComplianceVerdict.PASS
        assert assm.behavioral_equivalence == EvaluationVerdict.EQUIVALENT
        assert "r_out_1" in assm.reference_evidence_ids
        assert "t_out_1" in assm.target_evidence_ids

    # 2. SEPARATION OF PHASE 4 (EQUIVALENCE) VS PHASE 5 (COMPLIANCE)
    def test_both_violate_rule_yields_phase4_equivalent_and_phase5_fail(self):
        """Reference and Target behave identically (Phase 4: EQUIVALENT) but both violate rule (Phase 5: FAIL)."""
        session_id = "sess_p5_2"
        app_id = "app_p5_2"

        # Both return 500 error for an adult
        rec_r = EvidenceRecord(
            evidence_id="r_err_2",
            session_id=session_id,
            input_id="inp_adult",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"http_status": 500}, "normalized_output": {"http_status": 500}, "age": 30},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_err_2",
            session_id=session_id,
            input_id="inp_adult",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"http_status": 500}, "normalized_output": {"http_status": 500}, "age": 30},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_2",
            session_id=session_id,
            correlation_id="c_p5_2",
            application_id=app_id,
            input_set_id="is_p5_2",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_2", application_id=app_id, input_set_id="is_p5_2", input_set_hash="h_2", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-AGE-02",
            name="Adult Must Succeed",
            condition=RulePredicate(field="age", operator=RuleOperator.GTE, value=18),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        p4_res = behavioral_evaluation_engine.evaluate_bundle(bundle, policy=DEFAULT_COMPARISON_POLICY)
        assert p4_res.verdict == EvaluationVerdict.EQUIVALENT

        res = controlled_assessment_engine.evaluate_controlled_mode(
            rules=[rule],
            bundle=bundle,
            phase4_result=p4_res,
        )

        assert res.overall_verdict == RuleComplianceVerdict.FAIL
        assm = res.rule_assessments[0]
        assert assm.applicability == "APPLICABLE"
        assert assm.reference_compliance == RuleComplianceVerdict.FAIL
        assert assm.target_compliance == RuleComplianceVerdict.FAIL
        assert assm.behavioral_equivalence == EvaluationVerdict.EQUIVALENT

    # 3. DIFFERENT IMPLEMENTATIONS (Phase 4: DIFFERENT, Phase 5: Ref PASS, Target FAIL)
    def test_divergent_behavior_preserves_independent_compliance(self):
        """Reference passes rule while Target fails -> Phase 4 is DIFFERENT, Ref=PASS, Target=FAIL."""
        session_id = "sess_p5_3"
        app_id = "app_p5_3"

        rec_r = EvidenceRecord(
            evidence_id="r_out_3",
            session_id=session_id,
            input_id="inp_minor",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "REJECTED", "http_status": 400}, "normalized_output": {"status": "REJECTED", "http_status": 400}, "age": 16},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_out_3",
            session_id=session_id,
            input_id="inp_minor",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "APPROVED", "http_status": 200}, "normalized_output": {"status": "APPROVED", "http_status": 200}, "age": 16},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_3",
            session_id=session_id,
            correlation_id="c_p5_3",
            application_id=app_id,
            input_set_id="is_p5_3",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_3", application_id=app_id, input_set_id="is_p5_3", input_set_hash="h_3", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-MINORS-REJECT",
            name="Reject Minors",
            condition=RulePredicate(field="age", operator=RuleOperator.LT, value=18),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.REJECT),
        )

        p4_res = behavioral_evaluation_engine.evaluate_bundle(bundle, policy=DEFAULT_COMPARISON_POLICY)
        assert p4_res.verdict == EvaluationVerdict.DIFFERENT

        res = controlled_assessment_engine.evaluate_controlled_mode(
            rules=[rule],
            bundle=bundle,
            phase4_result=p4_res,
        )

        assert res.overall_verdict == RuleComplianceVerdict.FAIL
        assm = res.rule_assessments[0]
        assert assm.applicability == "APPLICABLE"
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.FAIL
        assert assm.behavioral_equivalence == EvaluationVerdict.DIFFERENT

    # 4. THREE-VALUED APPLICABILITY: MISSING REFERENCED FIELD -> UNKNOWN -> INCONCLUSIVE (Acceptance Scenario 2)
    def test_missing_referenced_input_field_yields_inconclusive_not_not_applicable(self):
        """When input is missing the referenced condition field, applicability is UNKNOWN and result is INCONCLUSIVE."""
        session_id = "sess_p5_missing"
        app_id = "app_p5_missing"

        # Input record has NO 'age' field
        rec_r = EvidenceRecord(
            evidence_id="r_out_m",
            session_id=session_id,
            input_id="inp_no_age",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK", "http_status": 200}, "normalized_output": {"status": "OK", "http_status": 200}},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_out_m",
            session_id=session_id,
            input_id="inp_no_age",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK", "http_status": 200}, "normalized_output": {"status": "OK", "http_status": 200}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_m",
            session_id=session_id,
            correlation_id="c_p5_m",
            application_id=app_id,
            input_set_id="is_p5_m",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_m", application_id=app_id, input_set_id="is_p5_m", input_set_hash="h_m", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-AGE-03",
            name="Age Requirement",
            condition=RulePredicate(field="age", operator=RuleOperator.GTE, value=18),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)

        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE
        assm = res.rule_assessments[0]
        assert assm.applicability == "UNKNOWN"
        assert assm.overall_rule_status == RuleComplianceVerdict.INCONCLUSIVE

    # 5. CONDITION IS FALSE -> NOT_APPLICABLE (Acceptance Scenario 4)
    def test_condition_false_yields_not_applicable_not_fail(self):
        """When rule condition is false (e.g. age=15 for age>=18 rule), rule is NOT_APPLICABLE."""
        session_id = "sess_p5_na"
        app_id = "app_p5_na"

        rec_r = EvidenceRecord(
            evidence_id="r_out_na",
            session_id=session_id,
            input_id="inp_minor",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "REJECTED", "http_status": 400}, "normalized_output": {"status": "REJECTED", "http_status": 400}, "age": 15},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_out_na",
            session_id=session_id,
            input_id="inp_minor",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "REJECTED", "http_status": 400}, "normalized_output": {"status": "REJECTED", "http_status": 400}, "age": 15},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_na",
            session_id=session_id,
            correlation_id="c_p5_na",
            application_id=app_id,
            input_set_id="is_p5_na",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_na", application_id=app_id, input_set_id="is_p5_na", input_set_hash="h_na", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-ADULT-ACCEPT",
            name="Adult Must Accept",
            condition=RulePredicate(field="age", operator=RuleOperator.GTE, value=18),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)

        assert res.overall_verdict == RuleComplianceVerdict.NOT_APPLICABLE
        assm = res.rule_assessments[0]
        assert assm.applicability == "NOT_APPLICABLE"
        assert assm.overall_rule_status == RuleComplianceVerdict.NOT_APPLICABLE

    # 6. FINAL ACCEPTANCE SCENARIO 1: VALID OUTPUT + INSUFFICIENT STATE EVIDENCE
    def test_acceptance_scenario_1_valid_output_and_insufficient_state(self):
        """Rule 1 checks output (PASS), Rule 2 checks state mutation (INCONCLUSIVE due to partial state evidence). Overall: INCONCLUSIVE."""
        session_id = "sess_p5_scen1"
        app_id = "app_p5_scen1"

        # Valid output records
        rec_r_out = EvidenceRecord(
            evidence_id="r_out_s1",
            session_id=session_id,
            input_id="inp_scen1",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK", "http_status": 200}, "normalized_output": {"status": "OK", "http_status": 200}, "amount": 500},
        )
        rec_t_out = EvidenceRecord(
            evidence_id="t_out_s1",
            session_id=session_id,
            input_id="inp_scen1",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK", "http_status": 200}, "normalized_output": {"status": "OK", "http_status": 200}, "amount": 500},
        )
        # Malformed / partial state evidence
        rec_r_db = EvidenceRecord(
            evidence_id="r_db_s1",
            session_id=session_id,
            input_id="inp_scen1",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.PARTIAL,
            payload={"queries": ["UPDATE accounts SET balance = balance - 500"]},
        )
        rec_t_db = EvidenceRecord(
            evidence_id="t_db_s1",
            session_id=session_id,
            input_id="inp_scen1",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.PARTIAL,
            payload={"queries": ["UPDATE accounts SET balance = balance - 500"]},
        )

        bundle = EvidenceBundle(
            bundle_id="bnd_p5_s1",
            session_id=session_id,
            correlation_id="c_p5_s1",
            application_id=app_id,
            input_set_id="is_p5_s1",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_s1", application_id=app_id, input_set_id="is_p5_s1", input_set_hash="h_s1", records=[rec_r_out, rec_t_out, rec_r_db, rec_t_db]),
            records=[rec_r_out, rec_t_out, rec_r_db, rec_t_db],
        )

        rule_out = BusinessRule(
            rule_id="RULE-OUTPUT-01",
            name="Output Must Succeed",
            condition=RulePredicate(field="amount", operator=RuleOperator.GT, value=0),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        rule_state = BusinessRule(
            rule_id="RULE-STATE-01",
            name="State Mutation Required",
            condition=RulePredicate(field="amount", operator=RuleOperator.GT, value=0),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(
            rules=[rule_out, rule_state],
            bundle=bundle,
        )

        # Output rule: PASS; State rule: INCONCLUSIVE; Overall: INCONCLUSIVE
        assm_out = next(a for a in res.rule_assessments if a.rule_id == "RULE-OUTPUT-01")
        assm_state = next(a for a in res.rule_assessments if a.rule_id == "RULE-STATE-01")

        assert assm_out.overall_rule_status == RuleComplianceVerdict.PASS
        assert assm_state.overall_rule_status == RuleComplianceVerdict.INCONCLUSIVE
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 7. FALSE-PASS ELIMINATION FOR NO_STATE_CHANGE WITH MISSING STATE EVIDENCE
    def test_no_state_change_with_missing_db_evidence_yields_inconclusive(self):
        """When a rule expects NO_STATE_CHANGE but state evidence is missing, result is INCONCLUSIVE (not PASS)."""
        session_id = "sess_p5_nostate"
        app_id = "app_p5_nostate"

        # Only output evidence captured; NO DB evidence captured at all
        rec_r = EvidenceRecord(
            evidence_id="r_out_ns",
            session_id=session_id,
            input_id="inp_ns",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"http_status": 200}, "normalized_output": {"http_status": 200}, "query_only": True},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_out_ns",
            session_id=session_id,
            input_id="inp_ns",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"http_status": 200}, "normalized_output": {"http_status": 200}, "query_only": True},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_ns",
            session_id=session_id,
            correlation_id="c_p5_ns",
            application_id=app_id,
            input_set_id="is_p5_ns",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_ns", application_id=app_id, input_set_id="is_p5_ns", input_set_hash="h_ns", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-NO-MUTATION",
            name="Read Queries Must Not Mutate State",
            condition=RulePredicate(field="query_only", operator=RuleOperator.EQ, value=True),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE
        assm = res.rule_assessments[0]
        assert assm.overall_rule_status == RuleComplianceVerdict.INCONCLUSIVE
        assert "state evidence is missing" in assm.details["reference_explanation"].lower()

    # 8. FALSE-PASS ELIMINATION FOR RETURN_STATUS WITH MISSING HTTP EVIDENCE
    def test_return_status_with_missing_http_evidence_yields_inconclusive(self):
        """When a rule expects RETURN_STATUS=400 but HTTP evidence is missing, result is INCONCLUSIVE."""
        session_id = "sess_p5_nohttp"
        app_id = "app_p5_nohttp"

        # Output record has no http_status or exit_code
        rec_r = EvidenceRecord(
            evidence_id="r_out_nh",
            session_id=session_id,
            input_id="inp_nh",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"result": "ok"}, "normalized_output": {"result": "ok"}, "invalid_input": True},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_out_nh",
            session_id=session_id,
            input_id="inp_nh",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"result": "ok"}, "normalized_output": {"result": "ok"}, "invalid_input": True},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_nh",
            session_id=session_id,
            correlation_id="c_p5_nh",
            application_id=app_id,
            input_set_id="is_p5_nh",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_nh", application_id=app_id, input_set_id="is_p5_nh", input_set_hash="h_nh", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-HTTP-400",
            name="Must Return 400",
            condition=RulePredicate(field="invalid_input", operator=RuleOperator.EQ, value=True),
            expected_behavior=ExpectedBehavior(
                behavior_type=ExpectedBehaviorType.RETURN_STATUS,
                expected_status_code=400,
            ),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 9. DETERMINISTIC EVALUATION FINGERPRINT
    def test_evaluation_fingerprint_reproducibility(self):
        """Running the same controlled evaluation twice produces identical evaluation fingerprints."""
        session_id = "sess_p5_det"
        app_id = "app_p5_det"

        rec_r = EvidenceRecord(
            evidence_id="r_out_d",
            session_id=session_id,
            input_id="inp_det",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"http_status": 200}, "normalized_output": {"http_status": 200}, "tier": "VIP"},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_out_d",
            session_id=session_id,
            input_id="inp_det",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"http_status": 200}, "normalized_output": {"http_status": 200}, "tier": "VIP"},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_det",
            session_id=session_id,
            correlation_id="c_p5_det",
            application_id=app_id,
            input_set_id="is_p5_det",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_det", application_id=app_id, input_set_id="is_p5_det", input_set_hash="h_d", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-VIP-01",
            name="VIP Discount",
            condition=RulePredicate(field="tier", operator=RuleOperator.EQ, value="VIP"),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res1 = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        res2 = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)

        assert res1.evaluation_fingerprint != ""
        assert res1.evaluation_fingerprint == res2.evaluation_fingerprint
        assert res1.overall_verdict == res2.overall_verdict

    # 10. MANDATORY FIELD-SOURCE ISOLATION E2E TEST (Section 30 & 54)
    def test_field_source_input_isolation_e2e(self):
        """Input is {}, Output is {'age': 25}. Rule with field_source='input' must evaluate to UNKNOWN -> INCONCLUSIVE."""
        session_id = "sess_p5_fsrc"
        app_id = "app_p5_fsrc"

        # Output record has raw_output = {'age': 25}, but input record has empty payload
        rec_r = EvidenceRecord(
            evidence_id="r_out_fs",
            session_id=session_id,
            input_id="inp_fsrc",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"age": 25, "status": "OK", "http_status": 200}},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_out_fs",
            session_id=session_id,
            input_id="inp_fsrc",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"age": 25, "status": "OK", "http_status": 200}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_fs",
            session_id=session_id,
            correlation_id="c_p5_fs",
            application_id=app_id,
            input_set_id="is_p5_fs",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_fs", application_id=app_id, input_set_id="is_p5_fs", input_set_hash="h_fs", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-SRC-INPUT",
            name="Age From Input Only",
            condition=RulePredicate(field="age", field_source="input", operator=RuleOperator.GTE, value=18),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE
        assm = res.rule_assessments[0]
        assert assm.applicability == "UNKNOWN"
        assert assm.overall_rule_status == RuleComplianceVerdict.INCONCLUSIVE

    # 11. MANDATORY POSITIVE FIELD-SOURCE E2E TEST (Section 31 & 55)
    def test_field_source_output_positive_e2e(self):
        """Input is {}, Output is {'result': 'APPROVED'}. Rule with field_source='output' must evaluate to TRUE -> PASS."""
        session_id = "sess_p5_fout"
        app_id = "app_p5_fout"

        rec_r = EvidenceRecord(
            evidence_id="r_out_fo",
            session_id=session_id,
            input_id="inp_fout",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"result": "APPROVED", "http_status": 200}},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_out_fo",
            session_id=session_id,
            input_id="inp_fout",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"result": "APPROVED", "http_status": 200}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_fo",
            session_id=session_id,
            correlation_id="c_p5_fo",
            application_id=app_id,
            input_set_id="is_p5_fo",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_fo", application_id=app_id, input_set_id="is_p5_fo", input_set_hash="h_fo", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-SRC-OUTPUT",
            name="Result From Output",
            condition=RulePredicate(field="result", field_source="output", operator=RuleOperator.EQ, value="APPROVED"),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.PASS
        assm = res.rule_assessments[0]
        assert assm.applicability == "APPLICABLE"
        assert assm.overall_rule_status == RuleComplianceVerdict.PASS

    # 12. MANDATORY ADAPTATION FAILURE PROPAGATION TEST (Section 16 & 52)
    def test_adaptation_failure_propagation_yields_inconclusive(self):
        """When an adaptation failure or partial capture status occurs for a required dimension, rule is INCONCLUSIVE."""
        session_id = "sess_p5_af"
        app_id = "app_p5_af"

        rec_r = EvidenceRecord(
            evidence_id="r_out_af",
            session_id=session_id,
            input_id="inp_af",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK", "http_status": 200}, "input": {"age": 25}},
        )
        # Target output record has PARTIAL capture status
        rec_t = EvidenceRecord(
            evidence_id="t_out_af",
            session_id=session_id,
            input_id="inp_af",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.PARTIAL,
            payload={"raw_output": {"status": "OK", "http_status": 200}, "input": {"age": 25}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_af",
            session_id=session_id,
            correlation_id="c_p5_af",
            application_id=app_id,
            input_set_id="is_p5_af",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_af", application_id=app_id, input_set_id="is_p5_af", input_set_hash="h_af", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-AF-01",
            name="Age Requirement",
            condition=RulePredicate(field="age", operator=RuleOperator.GTE, value=18),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE
        assm = res.rule_assessments[0]
        assert assm.target_compliance == RuleComplianceVerdict.INCONCLUSIVE
        assert res.summary.inconclusive_rule_count >= 1

    # 13. MANDATORY WORKFLOW_STEP MISSING TRACE TEST (Section 19 & 52)
    def test_workflow_step_with_missing_trace_evidence_yields_inconclusive(self):
        """When a rule expects WORKFLOW_STEP='AUDIT_LOG' but trace evidence is missing/partial, result is INCONCLUSIVE."""
        session_id = "sess_p5_trace"
        app_id = "app_p5_trace"

        rec_r = EvidenceRecord(
            evidence_id="r_out_tr",
            session_id=session_id,
            input_id="inp_tr",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK", "http_status": 200}, "op": "TRANSFER"},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_out_tr",
            session_id=session_id,
            input_id="inp_tr",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK", "http_status": 200}, "op": "TRANSFER"},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_tr",
            session_id=session_id,
            correlation_id="c_p5_tr",
            application_id=app_id,
            input_set_id="is_p5_tr",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_tr", application_id=app_id, input_set_id="is_p5_tr", input_set_hash="h_tr", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-WORKFLOW-01",
            name="Audit Trace Required",
            condition=RulePredicate(field="op", operator=RuleOperator.EQ, value="TRANSFER"),
            expected_behavior=ExpectedBehavior(
                behavior_type=ExpectedBehaviorType.WORKFLOW_STEP,
                expected_workflow_event="AUDIT_LOG",
            ),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE
        assm = res.rule_assessments[0]
        assert assm.overall_rule_status == RuleComplianceVerdict.INCONCLUSIVE
        assert "Trace evidence is missing" in assm.details["reference_explanation"]

    # 14. REST API ENDPOINTS AND DURABLE AUDIT PERSISTENCE
    def test_api_controlled_mode_endpoints_and_persistence(self, client):
        """Tests REST API rule CRUD and Controlled Mode execution with SQLite audit retrieval."""
        from auth.repository import auth_repository
        admin_user = auth_repository.get_user_by_username("admin")
        token = create_access_token(user=admin_user)
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create rule via API
        rule_payload = {
            "rule_id": "API-RULE-01",
            "name": "API Adult Eligibility",
            "condition": {"field": "age", "operator": "GTE", "value": 18},
            "expected_behavior": {"behavior_type": "ACCEPT"},
        }
        res_create = client.post("/api/v2/rules", json=rule_payload, headers=headers)
        assert res_create.status_code == 201
        created = res_create.json()
        assert created["rule_id"] == "API-RULE-01"
        assert created["fingerprint"] != ""

        # 2. Get rule
        res_get = client.get("/api/v2/rules/API-RULE-01", headers=headers)
        assert res_get.status_code == 200
        assert res_get.json()["version"] == 1

        # 3. Evaluate controlled mode via API
        bundle = {
            "bundle_id": "bnd_api_test",
            "session_id": "sess_api",
            "correlation_id": "c_api",
            "application_id": "app_api",
            "input_set_id": "is_api",
            "manifest": {
                "session_id": "sess_api",
                "correlation_id": "c_api",
                "application_id": "app_api",
                "input_set_id": "is_api",
                "input_set_hash": "h_api",
                "records": [
                    {
                        "evidence_id": "r1",
                        "session_id": "sess_api",
                        "input_id": "inp1",
                        "role": "reference",
                        "evidence_type": "OUTPUT",
                        "capture_status": "CAPTURED",
                        "payload": {"raw_output": {"status": "OK", "http_status": 200}, "input": {"age": 21}},
                    },
                    {
                        "evidence_id": "t1",
                        "session_id": "sess_api",
                        "input_id": "inp1",
                        "role": "target",
                        "evidence_type": "OUTPUT",
                        "capture_status": "CAPTURED",
                        "payload": {"raw_output": {"status": "OK", "http_status": 200}, "input": {"age": 21}},
                    },
                ],
            },
            "records": [
                {
                    "evidence_id": "r1",
                    "session_id": "sess_api",
                    "input_id": "inp1",
                    "role": "reference",
                    "evidence_type": "OUTPUT",
                    "capture_status": "CAPTURED",
                    "payload": {"raw_output": {"status": "OK", "http_status": 200}, "input": {"age": 21}},
                },
                {
                    "evidence_id": "t1",
                    "session_id": "sess_api",
                    "input_id": "inp1",
                    "role": "target",
                    "evidence_type": "OUTPUT",
                    "capture_status": "CAPTURED",
                    "payload": {"raw_output": {"status": "OK", "http_status": 200}, "input": {"age": 21}},
                },
            ],
        }

        res_eval = client.post(
            "/api/v2/controlled/evaluate",
            json={"rule_ids": ["API-RULE-01"], "bundle": bundle},
            headers=headers,
        )
        assert res_eval.status_code == 200
        eval_data = res_eval.json()
        assert eval_data["overall_verdict"] == "PASS"
        eval_id = eval_data["evaluation_id"]

        # 4. Retrieve evaluation from audit persistence
        res_fetch = client.get(f"/api/v2/controlled/evaluations/{eval_id}", headers=headers)
        assert res_fetch.status_code == 200
        fetched_eval = res_fetch.json()
        assert fetched_eval["evaluation_id"] == eval_id
        assert fetched_eval["overall_verdict"] == "PASS"

    # 15. REST API PERSISTENCE FAILURE RETURNS EXPLICIT ERROR
    def test_api_persistence_failure_returns_explicit_error(self, client):
        """When SQLite persistence fails during evaluation, API returns explicit HTTP 500 error."""
        from auth.repository import auth_repository
        admin_user = auth_repository.get_user_by_username("admin")
        token = create_access_token(user=admin_user)
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Statically validate rule first
        res_val = client.post(
            "/api/v2/rules/validate",
            json={"rule": {"rule_id": "R-TEST", "name": "Test", "condition": {"field": "x", "operator": "EQ", "value": 1}, "expected_behavior": {"behavior_type": "ACCEPT"}}},
            headers=headers,
        )
        assert res_val.status_code == 200
        assert res_val.json()["is_valid"] is True

        # 2. Test rule creation failure on SQLite error
        with patch.object(rule_registry, "register_rule", side_effect=RulePersistenceError("Disk write failed")):
            res_fail = client.post(
                "/api/v2/rules",
                json={"rule_id": "R-FAIL", "name": "Fail Test", "condition": {"field": "x", "operator": "EQ", "value": 1}, "expected_behavior": {"behavior_type": "ACCEPT"}},
                headers=headers,
            )
            assert res_fail.status_code == 500
            assert "Database persistence failure" in res_fail.json()["detail"]

    # 16. STATE EVIDENCE: DATABASE EQUAL BEFORE/AFTER YIELDS NO_STATE_CHANGE PASS (Section 11)
    def test_state_evidence_database_equal_before_after_yields_no_state_change_pass(self):
        """When both Ref and Target have valid equal before/after DB snapshots, NO_STATE_CHANGE evaluates to PASS."""
        session_id = "sess_p5_db_eq"
        app_id = "app_p5_db_eq"

        db_snap = {"accounts": [{"id": 1, "balance": 1000}]}
        rec_r_db = EvidenceRecord(
            evidence_id="r_db_eq",
            session_id=session_id,
            input_id="inp_db_eq",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": db_snap, "snapshot_after": db_snap},
        )
        rec_t_db = EvidenceRecord(
            evidence_id="t_db_eq",
            session_id=session_id,
            input_id="inp_db_eq",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": db_snap, "snapshot_after": db_snap},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_db_eq",
            session_id=session_id,
            correlation_id="c_p5_dbeq",
            application_id=app_id,
            input_set_id="is_p5_dbeq",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_dbeq", application_id=app_id, input_set_id="is_p5_dbeq", input_set_hash="h_dbeq", records=[rec_r_db, rec_t_db]),
            records=[rec_r_db, rec_t_db],
        )

        rule = BusinessRule(
            rule_id="RULE-DB-NO-MUTATION",
            name="Database Read Only",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.PASS
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS

    # 17. STATE EVIDENCE: DATABASE DIFFERENT BEFORE/AFTER YIELDS STATE_CHANGE PASS (Section 11)
    def test_state_evidence_database_different_before_after_yields_state_change_pass(self):
        """When both Ref and Target have valid different before/after DB snapshots, STATE_CHANGE evaluates to PASS."""
        session_id = "sess_p5_db_diff"
        app_id = "app_p5_db_diff"

        db_before = {"accounts": [{"id": 1, "balance": 1000}]}
        db_after = {"accounts": [{"id": 1, "balance": 900}]}

        rec_r_db = EvidenceRecord(
            evidence_id="r_db_diff",
            session_id=session_id,
            input_id="inp_db_diff",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": db_before, "snapshot_after": db_after},
        )
        rec_t_db = EvidenceRecord(
            evidence_id="t_db_diff",
            session_id=session_id,
            input_id="inp_db_diff",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": db_before, "snapshot_after": db_after},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_db_diff",
            session_id=session_id,
            correlation_id="c_p5_dbdiff",
            application_id=app_id,
            input_set_id="is_p5_dbdiff",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_dbdiff", application_id=app_id, input_set_id="is_p5_dbdiff", input_set_hash="h_dbdiff", records=[rec_r_db, rec_t_db]),
            records=[rec_r_db, rec_t_db],
        )

        rule = BusinessRule(
            rule_id="RULE-DB-MUTATE",
            name="Database Mutation Required",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.PASS
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS

    # 18. FALSE PASS 1: CAPTURED DB WITHOUT SNAPSHOTS (Section 3, 11, 23, 27) (MANDATORY)
    def test_false_pass_1_captured_db_without_snapshots_yields_inconclusive(self):
        """CAPTURED DB evidence with delta_detected=False but missing actual snapshots yields INCONCLUSIVE (not PASS)."""
        session_id = "sess_p5_fp1"
        app_id = "app_p5_fp1"

        # Evidence record has status CAPTURED, but NO snapshots / observation data
        rec_r = EvidenceRecord(
            evidence_id="r_db_fp1",
            session_id=session_id,
            input_id="inp_fp1",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={},  # No snapshot_before or snapshot_after
        )
        rec_t = EvidenceRecord(
            evidence_id="t_db_fp1",
            session_id=session_id,
            input_id="inp_fp1",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={},  # No snapshot_before or snapshot_after
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_fp1",
            session_id=session_id,
            correlation_id="c_p5_fp1",
            application_id=app_id,
            input_set_id="is_p5_fp1",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_fp1", application_id=app_id, input_set_id="is_p5_fp1", input_set_hash="h_fp1", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-FP1-NO-STATE-CHANGE",
            name="Must Not Mutate State",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.INCONCLUSIVE
        assert assm.target_compliance == RuleComplianceVerdict.INCONCLUSIVE
        assert "insufficient" in assm.details["reference_explanation"].lower() or "missing" in assm.details["reference_explanation"].lower()

    # 19. STATE EVIDENCE: ONE SIDE MISSING YIELDS INCONCLUSIVE (Section 11)
    def test_state_evidence_one_side_missing_yields_inconclusive(self):
        """Reference has valid DB snapshots but Target has none -> Target is INCONCLUSIVE, Overall is INCONCLUSIVE."""
        session_id = "sess_p5_db_oneside"
        app_id = "app_p5_db_oneside"

        db_snap = {"users": [{"id": 1}]}
        rec_r = EvidenceRecord(
            evidence_id="r_db_os",
            session_id=session_id,
            input_id="inp_db_os",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": db_snap, "snapshot_after": db_snap},
        )
        # Target has no state evidence at all (only output)
        rec_t_out = EvidenceRecord(
            evidence_id="t_out_os",
            session_id=session_id,
            input_id="inp_db_os",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK"}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_db_os",
            session_id=session_id,
            correlation_id="c_p5_dbos",
            application_id=app_id,
            input_set_id="is_p5_dbos",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_dbos", application_id=app_id, input_set_id="is_p5_dbos", input_set_hash="h_dbos", records=[rec_r, rec_t_out]),
            records=[rec_r, rec_t_out],
        )

        rule = BusinessRule(
            rule_id="RULE-DB-ONESIDE",
            name="State Integrity",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.INCONCLUSIVE

    # 20. STATE EVIDENCE: PARTIAL STATUS YIELDS INCONCLUSIVE (Section 11)
    def test_state_evidence_partial_status_yields_inconclusive(self):
        """When Database evidence has capture_status=PARTIAL, rule evaluation yields INCONCLUSIVE."""
        session_id = "sess_p5_db_part"
        app_id = "app_p5_db_part"

        rec_r = EvidenceRecord(
            evidence_id="r_db_part",
            session_id=session_id,
            input_id="inp_db_part",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.PARTIAL,
            payload={"snapshot_before": {"a": 1}, "snapshot_after": {"a": 1}},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_db_part",
            session_id=session_id,
            input_id="inp_db_part",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.PARTIAL,
            payload={"snapshot_before": {"a": 1}, "snapshot_after": {"a": 1}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_db_part",
            session_id=session_id,
            correlation_id="c_p5_dbpart",
            application_id=app_id,
            input_set_id="is_p5_dbpart",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_dbpart", application_id=app_id, input_set_id="is_p5_dbpart", input_set_hash="h_dbpart", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-DB-PARTIAL",
            name="No Mutation Rule",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 21. STATE EVIDENCE: FAILED STATUS YIELDS INCONCLUSIVE (Section 11)
    def test_state_evidence_failed_status_yields_inconclusive(self):
        """When Database evidence has capture_status=FAILED, rule evaluation yields INCONCLUSIVE."""
        session_id = "sess_p5_db_fail"
        app_id = "app_p5_db_fail"

        rec_r = EvidenceRecord(
            evidence_id="r_db_fl",
            session_id=session_id,
            input_id="inp_db_fl",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.FAILED,
            payload={},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_db_fl",
            session_id=session_id,
            input_id="inp_db_fl",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.FAILED,
            payload={},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_db_fl",
            session_id=session_id,
            correlation_id="c_p5_dbfl",
            application_id=app_id,
            input_set_id="is_p5_dbfl",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_dbfl", application_id=app_id, input_set_id="is_p5_dbfl", input_set_hash="h_dbfl", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-DB-FAIL",
            name="No Mutation Rule",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 22. STATE EVIDENCE: EXPLICITLY CAPTURED EMPTY DATABASE IS VALID (Section 11, 24)
    def test_state_evidence_explicitly_captured_empty_database_is_valid(self):
        """Explicitly captured empty database state ({}) is valid observational evidence and satisfies NO_STATE_CHANGE."""
        session_id = "sess_p5_db_empty"
        app_id = "app_p5_db_empty"

        rec_r = EvidenceRecord(
            evidence_id="r_db_emp",
            session_id=session_id,
            input_id="inp_db_emp",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": {}, "snapshot_after": {}},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_db_emp",
            session_id=session_id,
            input_id="inp_db_emp",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": {}, "snapshot_after": {}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_db_emp",
            session_id=session_id,
            correlation_id="c_p5_dbemp",
            application_id=app_id,
            input_set_id="is_p5_dbemp",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_dbemp", application_id=app_id, input_set_id="is_p5_dbemp", input_set_hash="h_dbemp", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-DB-EMPTY",
            name="Empty DB No Mutation",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.PASS
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS

    # 23. STATE EVIDENCE: FILESYSTEM EQUAL HASHES YIELDS NO_STATE_CHANGE PASS (Section 12)
    def test_state_evidence_filesystem_equal_hashes_yields_no_state_change_pass(self):
        """When before and after filesystem state hashes are equal, NO_STATE_CHANGE evaluates to PASS."""
        session_id = "sess_p5_fs_eq"
        app_id = "app_p5_fs_eq"

        file_state = {"/data/app.log": {"path": "/data/app.log", "sha256_hash": "hash_abc", "exists": True, "size_bytes": 100}}
        rec_r = EvidenceRecord(
            evidence_id="r_fs_eq",
            session_id=session_id,
            input_id="inp_fs_eq",
            role="reference",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"before_state": file_state, "after_state": file_state},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_fs_eq",
            session_id=session_id,
            input_id="inp_fs_eq",
            role="target",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"before_state": file_state, "after_state": file_state},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_fs_eq",
            session_id=session_id,
            correlation_id="c_p5_fseq",
            application_id=app_id,
            input_set_id="is_p5_fseq",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_fseq", application_id=app_id, input_set_id="is_p5_fseq", input_set_hash="h_fseq", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-FS-NO-CHANGE",
            name="Filesystem Read Only",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.PASS
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS

    # 24. STATE EVIDENCE: FILESYSTEM DIFFERENT HASHES YIELDS STATE_CHANGE PASS (Section 12)
    def test_state_evidence_filesystem_different_hashes_yields_state_change_pass(self):
        """When before and after filesystem state hashes differ, STATE_CHANGE evaluates to PASS."""
        session_id = "sess_p5_fs_diff"
        app_id = "app_p5_fs_diff"

        fs_before = {"/data/app.log": {"path": "/data/app.log", "sha256_hash": "hash_111", "exists": True, "size_bytes": 100}}
        fs_after = {"/data/app.log": {"path": "/data/app.log", "sha256_hash": "hash_222", "exists": True, "size_bytes": 200}}

        rec_r = EvidenceRecord(
            evidence_id="r_fs_df",
            session_id=session_id,
            input_id="inp_fs_df",
            role="reference",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"before_state": fs_before, "after_state": fs_after},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_fs_df",
            session_id=session_id,
            input_id="inp_fs_df",
            role="target",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"before_state": fs_before, "after_state": fs_after},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_fs_df",
            session_id=session_id,
            correlation_id="c_p5_fsdf",
            application_id=app_id,
            input_set_id="is_p5_fsdf",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_fsdf", application_id=app_id, input_set_id="is_p5_fsdf", input_set_hash="h_fsdf", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-FS-CHANGE",
            name="Filesystem Mutation Required",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.PASS
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS

    # 25. FALSE PASS 2: CAPTURED FILE WITHOUT SNAPSHOTS (Section 12, 23) (MANDATORY)
    def test_false_pass_2_captured_file_without_snapshots_yields_inconclusive(self):
        """FileEvidence with CAPTURED status but empty before_state / after_state yields INCONCLUSIVE (not PASS)."""
        session_id = "sess_p5_fp2"
        app_id = "app_p5_fp2"

        rec_r = EvidenceRecord(
            evidence_id="r_fs_fp2",
            session_id=session_id,
            input_id="inp_fs_fp2",
            role="reference",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={},  # No before_state, after_state or file lists
        )
        rec_t = EvidenceRecord(
            evidence_id="t_fs_fp2",
            session_id=session_id,
            input_id="inp_fs_fp2",
            role="target",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={},  # No before_state, after_state or file lists
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_fp2",
            session_id=session_id,
            correlation_id="c_p5_fp2",
            application_id=app_id,
            input_set_id="is_p5_fp2",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_fp2", application_id=app_id, input_set_id="is_p5_fp2", input_set_hash="h_fp2", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-FP2-NO-CHANGE",
            name="No FS Change Rule",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE
        assm = res.rule_assessments[0]
        assert assm.overall_rule_status == RuleComplianceVerdict.INCONCLUSIVE

    # 26. STATE EVIDENCE: FILESYSTEM PARTIAL STATUS YIELDS INCONCLUSIVE (Section 12)
    def test_state_evidence_filesystem_partial_status_yields_inconclusive(self):
        """When FileEvidence has capture_status=PARTIAL, evaluation yields INCONCLUSIVE."""
        session_id = "sess_p5_fs_part"
        app_id = "app_p5_fs_part"

        rec_r = EvidenceRecord(
            evidence_id="r_fs_pt",
            session_id=session_id,
            input_id="inp_fs_pt",
            role="reference",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.PARTIAL,
            payload={"before_state": {"/a": {"sha256_hash": "h1"}}, "after_state": {"/a": {"sha256_hash": "h1"}}},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_fs_pt",
            session_id=session_id,
            input_id="inp_fs_pt",
            role="target",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.PARTIAL,
            payload={"before_state": {"/a": {"sha256_hash": "h1"}}, "after_state": {"/a": {"sha256_hash": "h1"}}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_fs_pt",
            session_id=session_id,
            correlation_id="c_p5_fspt",
            application_id=app_id,
            input_set_id="is_p5_fspt",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_fspt", application_id=app_id, input_set_id="is_p5_fspt", input_set_hash="h_fspt", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-FS-PARTIAL",
            name="No FS Change Rule",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 27. STATE EVIDENCE: FILESYSTEM NOT_SUPPORTED YIELDS INCONCLUSIVE (Section 12)
    def test_state_evidence_filesystem_not_supported_yields_inconclusive(self):
        """When FileEvidence has capture_status=NOT_SUPPORTED, evaluation yields INCONCLUSIVE."""
        session_id = "sess_p5_fs_ns"
        app_id = "app_p5_fs_ns"

        rec_r = EvidenceRecord(
            evidence_id="r_fs_ns",
            session_id=session_id,
            input_id="inp_fs_ns",
            role="reference",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.NOT_SUPPORTED,
            payload={},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_fs_ns",
            session_id=session_id,
            input_id="inp_fs_ns",
            role="target",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.NOT_SUPPORTED,
            payload={},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_fs_ns",
            session_id=session_id,
            correlation_id="c_p5_fsns",
            application_id=app_id,
            input_set_id="is_p5_fsns",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_fsns", application_id=app_id, input_set_id="is_p5_fsns", input_set_hash="h_fsns", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-FS-NOT-SUPP",
            name="No FS Change Rule",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 28. ROLE CONTAMINATION TEST A: OUTPUT SECRET ISOLATION (Section 13, 23, 26) (MANDATORY)
    def test_role_contamination_test_a_output_secret_isolation(self):
        """Ref output is {'status': 'OK'}, Target output is {'status': 'OK', 'secret': 99}.
        Rule condition: field_source='output', secret == 99.
        Ref must evaluate to UNKNOWN -> INCONCLUSIVE.
        Target evaluates to TRUE -> PASS.
        Ref MUST NEVER become applicable because Target has secret.
        """
        session_id = "sess_p5_rc_a"
        app_id = "app_p5_rc_a"

        # Reference has NO secret
        rec_r = EvidenceRecord(
            evidence_id="r_rc_a",
            session_id=session_id,
            input_id="inp_rc_a",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK", "http_status": 200}},
        )
        # Target HAS secret = 99
        rec_t = EvidenceRecord(
            evidence_id="t_rc_a",
            session_id=session_id,
            input_id="inp_rc_a",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK", "secret": 99, "http_status": 200}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_rc_a",
            session_id=session_id,
            correlation_id="c_p5_rca",
            application_id=app_id,
            input_set_id="is_p5_rca",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_rca", application_id=app_id, input_set_id="is_p5_rca", input_set_hash="h_rca", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-SECRET-99",
            name="Secret Must Be 99",
            condition=RulePredicate(field="secret", field_source="output", operator=RuleOperator.EQ, value=99),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assm = res.rule_assessments[0]

        # Target matched condition (TRUE -> PASS)
        assert assm.target_compliance == RuleComplianceVerdict.PASS
        assert assm.details["target_applicability"] == "TRUE"

        # Reference did NOT match condition (missing field -> UNKNOWN -> INCONCLUSIVE)
        assert assm.reference_compliance == RuleComplianceVerdict.INCONCLUSIVE
        assert assm.details["reference_applicability"] == "UNKNOWN"

        # Overall verdict must be INCONCLUSIVE because Reference is inconclusive
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 29. ROLE CONTAMINATION TEST B: STATE ISOLATION (Section 13)
    def test_role_contamination_test_b_state_isolation(self):
        """Ref has state field balance = 100, Target does not. Rule reads field_source='state', balance == 100.
        Ref evaluates to TRUE, Target evaluates to UNKNOWN.
        """
        session_id = "sess_p5_rc_b"
        app_id = "app_p5_rc_b"

        rec_r_out = EvidenceRecord(
            evidence_id="r_out_b",
            session_id=session_id,
            input_id="inp_rc_b",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK"}},
        )
        rec_r_db = EvidenceRecord(
            evidence_id="r_db_b",
            session_id=session_id,
            input_id="inp_rc_b",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"balance": 100, "snapshot_before": {"balance": 100}, "snapshot_after": {"balance": 100}},
        )
        rec_t_out = EvidenceRecord(
            evidence_id="t_out_b",
            session_id=session_id,
            input_id="inp_rc_b",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK"}},
        )
        rec_t_db = EvidenceRecord(
            evidence_id="t_db_b",
            session_id=session_id,
            input_id="inp_rc_b",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": {"score": 50}, "snapshot_after": {"score": 50}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_rc_b",
            session_id=session_id,
            correlation_id="c_p5_rcb",
            application_id=app_id,
            input_set_id="is_p5_rcb",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_rcb", application_id=app_id, input_set_id="is_p5_rcb", input_set_hash="h_rcb", records=[rec_r_out, rec_r_db, rec_t_out, rec_t_db]),
            records=[rec_r_out, rec_r_db, rec_t_out, rec_t_db],
        )

        rule = BusinessRule(
            rule_id="RULE-STATE-BAL-100",
            name="State Balance 100",
            condition=RulePredicate(field="balance", field_source="state", operator=RuleOperator.EQ, value=100),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assm = res.rule_assessments[0]

        # Ref matched state condition
        assert assm.details["reference_applicability"] == "TRUE"
        assert assm.reference_compliance == RuleComplianceVerdict.PASS

        # Target lacks balance in state -> UNKNOWN -> INCONCLUSIVE
        assert assm.details["target_applicability"] == "UNKNOWN"
        assert assm.target_compliance == RuleComplianceVerdict.INCONCLUSIVE

    # 30. ROLE CONTAMINATION TEST C: ERROR ISOLATION (Section 13)
    def test_role_contamination_test_c_error_isolation(self):
        """Target has error, Reference does not. Rule reads field_source='error'.
        Ref does not see Target error -> Ref evaluates to UNKNOWN.
        """
        session_id = "sess_p5_rc_c"
        app_id = "app_p5_rc_c"

        rec_r = EvidenceRecord(
            evidence_id="r_rc_c",
            session_id=session_id,
            input_id="inp_rc_c",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK"}},
        )
        rec_t_err = EvidenceRecord(
            evidence_id="t_err_c",
            session_id=session_id,
            input_id="inp_rc_c",
            role="target",
            evidence_type=EvidenceType.ERROR,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"error_code": "ERR_NETWORK_TIMEOUT", "message": "timed out"},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_rc_c",
            session_id=session_id,
            correlation_id="c_p5_rcc",
            application_id=app_id,
            input_set_id="is_p5_rcc",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_rcc", application_id=app_id, input_set_id="is_p5_rcc", input_set_hash="h_rcc", records=[rec_r, rec_t_err]),
            records=[rec_r, rec_t_err],
        )

        rule = BusinessRule(
            rule_id="RULE-TIMEOUT-ERR",
            name="Network Timeout Error",
            condition=RulePredicate(field="error_code", field_source="error", operator=RuleOperator.EQ, value="ERR_NETWORK_TIMEOUT"),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.REJECT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assm = res.rule_assessments[0]

        # Target saw error and is APPLICABLE
        assert assm.details["target_applicability"] == "TRUE"
        assert assm.target_compliance == RuleComplianceVerdict.PASS

        # Reference has no error -> UNKNOWN -> INCONCLUSIVE
        assert assm.details["reference_applicability"] == "UNKNOWN"
        assert assm.reference_compliance == RuleComplianceVerdict.INCONCLUSIVE

    # 31. ROLE CONTAMINATION TEST D: METADATA ISOLATION (Section 13)
    def test_role_contamination_test_d_metadata_isolation(self):
        """Target metadata contains a field, Reference does not.
        Rule reads field_source='metadata'. Ref does not see Target metadata.
        """
        session_id = "sess_p5_rc_d"
        app_id = "app_p5_rc_d"

        rec_r = EvidenceRecord(
            evidence_id="r_rc_d",
            session_id=session_id,
            input_id="inp_rc_d",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK"}},
            metadata={"environment": "staging"},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_rc_d",
            session_id=session_id,
            input_id="inp_rc_d",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK"}},
            metadata={"environment": "production", "feature_flag": "ENABLED"},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_rc_d",
            session_id=session_id,
            correlation_id="c_p5_rcd",
            application_id=app_id,
            input_set_id="is_p5_rcd",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_rcd", application_id=app_id, input_set_id="is_p5_rcd", input_set_hash="h_rcd", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-FF-METADATA",
            name="Feature Flag Enabled",
            condition=RulePredicate(field="feature_flag", field_source="metadata", operator=RuleOperator.EQ, value="ENABLED"),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assm = res.rule_assessments[0]

        assert assm.details["target_applicability"] == "TRUE"
        assert assm.target_compliance == RuleComplianceVerdict.PASS

        assert assm.details["reference_applicability"] == "UNKNOWN"
        assert assm.reference_compliance == RuleComplianceVerdict.INCONCLUSIVE

    # 32. ROLE CONTAMINATION TEST E: AUTO SOURCE RESOLUTION IS ROLE-LOCAL (Section 13, 14)
    def test_role_contamination_test_e_auto_source_isolation(self):
        """AUTO source resolves only within each role's local context."""
        session_id = "sess_p5_rc_e"
        app_id = "app_p5_rc_e"

        # Ref has flag='ALPHA', Target has flag='BETA'
        rec_r = EvidenceRecord(
            evidence_id="r_rc_e",
            session_id=session_id,
            input_id="inp_rc_e",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"flag": "ALPHA", "status": "OK"}},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_rc_e",
            session_id=session_id,
            input_id="inp_rc_e",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"flag": "BETA", "status": "OK"}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_rc_e",
            session_id=session_id,
            correlation_id="c_p5_rce",
            application_id=app_id,
            input_set_id="is_p5_rce",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_rce", application_id=app_id, input_set_id="is_p5_rce", input_set_hash="h_rce", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-AUTO-ALPHA",
            name="Alpha Mode",
            condition=RulePredicate(field="flag", field_source="auto", operator=RuleOperator.EQ, value="ALPHA"),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assm = res.rule_assessments[0]

        # Reference matched 'ALPHA' -> TRUE -> PASS
        assert assm.details["reference_applicability"] == "TRUE"
        assert assm.reference_compliance == RuleComplianceVerdict.PASS

        # Target saw 'BETA' != 'ALPHA' -> FALSE -> NOT_APPLICABLE
        assert assm.details["target_applicability"] == "FALSE"
        assert assm.target_compliance == RuleComplianceVerdict.NOT_APPLICABLE

        # Overall: Reference applicable & passed, Target not applicable -> overall PASS
        assert res.overall_verdict == RuleComplianceVerdict.PASS

    # 33. FALSE DIFFERENCE: CAPTURED EMPTY OUTPUT IS VALID OBSERVATION (Section 24)
    def test_false_difference_captured_empty_output_equals(self):
        """Both sides genuinely captured equal empty output payload ({}) -> ACCEPT evaluates to PASS."""
        session_id = "sess_p5_fd_out"
        app_id = "app_p5_fd_out"

        rec_r = EvidenceRecord(
            evidence_id="r_fd_o",
            session_id=session_id,
            input_id="inp_fd_o",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {}, "http_status": 204},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_fd_o",
            session_id=session_id,
            input_id="inp_fd_o",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {}, "http_status": 204},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_fd_o",
            session_id=session_id,
            correlation_id="c_p5_fdo",
            application_id=app_id,
            input_set_id="is_p5_fdo",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_fdo", application_id=app_id, input_set_id="is_p5_fdo", input_set_hash="h_fdo", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-NO-CONTENT",
            name="204 No Content Acceptance",
            condition=RulePredicate(field="http_status", field_source="output", operator=RuleOperator.EQ, value=204),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.PASS
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS

    # 34. FALSE DIFFERENCE: NO ERROR WITH CAPTURED ERROR STATUS (Section 24)
    def test_false_difference_no_error_with_captured_error_status(self):
        """Both sides explicitly have captured success output and no error records -> ACCEPT evaluates to PASS."""
        session_id = "sess_p5_fd_noerr"
        app_id = "app_p5_fd_noerr"

        rec_r = EvidenceRecord(
            evidence_id="r_fd_ne",
            session_id=session_id,
            input_id="inp_fd_ne",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"success": True}, "http_status": 200},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_fd_ne",
            session_id=session_id,
            input_id="inp_fd_ne",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"success": True}, "http_status": 200},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_fd_ne",
            session_id=session_id,
            correlation_id="c_p5_fdne",
            application_id=app_id,
            input_set_id="is_p5_fdne",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_fdne", application_id=app_id, input_set_id="is_p5_fdne", input_set_hash="h_fdne", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-SUCCESS-ACCEPT",
            name="Success Flag True",
            condition=RulePredicate(field="success", field_source="output", operator=RuleOperator.EQ, value=True),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.PASS
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS

