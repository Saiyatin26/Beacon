"""BEACON V2 — Phase 5 Controlled Mode Assessment Integration Tests.

Validates end-to-end evaluation of user-defined business rules over Phase 3 evidence
bundles and Phase 4 behavioral results, proving conservative aggregation, false-pass
elimination, three-valued applicability, evidence sufficiency preconditions, traceability,
and deterministic reproducibility.
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app
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
from rules.registry import rule_registry


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
        assert "State evidence is missing" in assm.details["reference_explanation"]

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
