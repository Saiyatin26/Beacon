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

        db_snap = {"accounts": {"row_count": 1, "rows": [{"id": 1, "balance": 1000}], "table_hash": "hash_accounts_1000"}}
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

        db_before = {"accounts": {"row_count": 1, "rows": [{"id": 1, "balance": 1000}], "table_hash": "hash_accounts_1000"}}
        db_after = {"accounts": {"row_count": 1, "rows": [{"id": 1, "balance": 900}], "table_hash": "hash_accounts_900"}}

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

        db_snap = {"users": {"row_count": 1, "rows": [{"id": 1}], "table_hash": "hash_users_1"}}
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

    # 22. STATE EVIDENCE: UNANCHORED EMPTY DATABASE SNAPSHOTS ({}) YIELD INCONCLUSIVE (Issue A, Section 21)
    def test_state_evidence_explicitly_captured_empty_database_is_valid(self):
        """Unanchored empty database snapshots ({}) without table structure represent missing/placeholder state and yield INCONCLUSIVE."""
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
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.INCONCLUSIVE
        assert assm.target_compliance == RuleComplianceVerdict.INCONCLUSIVE

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

    # 35. FALSE PASS: ROW_COUNT=0 WITHOUT SNAPSHOTS YIELDS INCONCLUSIVE (Section 9, 28, 44)
    def test_false_pass_row_count_zero_without_snapshots_yields_inconclusive(self):
        """Database evidence with row_count=0 but missing before/after snapshots yields INCONCLUSIVE for NO_STATE_CHANGE."""
        session_id = "sess_p5_rc0"
        app_id = "app_p5_rc0"

        rec_r = EvidenceRecord(
            evidence_id="r_rc0",
            session_id=session_id,
            input_id="inp_rc0",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"row_count": 0},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_rc0",
            session_id=session_id,
            input_id="inp_rc0",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"row_count": 0},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_rc0",
            session_id=session_id,
            correlation_id="c_p5_rc0",
            application_id=app_id,
            input_set_id="is_p5_rc0",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_rc0", application_id=app_id, input_set_id="is_p5_rc0", input_set_hash="h_rc0", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-RC0-NO-CHANGE",
            name="No State Change Rule",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE
        assm = res.rule_assessments[0]
        assert assm.overall_rule_status == RuleComplianceVerdict.INCONCLUSIVE

    # 36. FALSE PASS: ROW_COUNT=10 WITHOUT SNAPSHOTS YIELDS INCONCLUSIVE (Section 9, 28)
    def test_false_pass_row_count_ten_without_snapshots_yields_inconclusive(self):
        """Database evidence with row_count=10 but missing before/after snapshots yields INCONCLUSIVE for NO_STATE_CHANGE."""
        session_id = "sess_p5_rc10"
        app_id = "app_p5_rc10"

        rec_r = EvidenceRecord(
            evidence_id="r_rc10",
            session_id=session_id,
            input_id="inp_rc10",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"row_count": 10},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_rc10",
            session_id=session_id,
            input_id="inp_rc10",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"row_count": 10},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_rc10",
            session_id=session_id,
            correlation_id="c_p5_rc10",
            application_id=app_id,
            input_set_id="is_p5_rc10",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_rc10", application_id=app_id, input_set_id="is_p5_rc10", input_set_hash="h_rc10", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-RC10-NO-CHANGE",
            name="No State Change Rule",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 37. FALSE PASS: SELECT QUERY ONLY YIELDS INCONCLUSIVE FOR NO_STATE_CHANGE (Section 11, 28, 45)
    def test_false_pass_select_query_only_yields_inconclusive_for_no_state_change(self):
        """Read-only SELECT query without before/after snapshots yields INCONCLUSIVE for NO_STATE_CHANGE."""
        session_id = "sess_p5_sel_nc"
        app_id = "app_p5_sel_nc"

        rec_r = EvidenceRecord(
            evidence_id="r_sel_nc",
            session_id=session_id,
            input_id="inp_sel_nc",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"queries": ["SELECT * FROM accounts WHERE user_id = 123"]},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_sel_nc",
            session_id=session_id,
            input_id="inp_sel_nc",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"queries": ["SELECT * FROM accounts WHERE user_id = 123"]},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_sel_nc",
            session_id=session_id,
            correlation_id="c_p5_selnc",
            application_id=app_id,
            input_set_id="is_p5_selnc",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_selnc", application_id=app_id, input_set_id="is_p5_selnc", input_set_hash="h_selnc", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-SEL-NO-CHANGE",
            name="No State Change Rule",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 38. FALSE PASS: SELECT QUERY ONLY YIELDS INCONCLUSIVE FOR STATE_CHANGE (Section 11, 28)
    def test_false_pass_select_query_only_yields_inconclusive_for_state_change(self):
        """Read-only SELECT query without before/after snapshots yields INCONCLUSIVE for STATE_CHANGE."""
        session_id = "sess_p5_sel_sc"
        app_id = "app_p5_sel_sc"

        rec_r = EvidenceRecord(
            evidence_id="r_sel_sc",
            session_id=session_id,
            input_id="inp_sel_sc",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"queries": ["SELECT * FROM accounts WHERE user_id = 123"]},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_sel_sc",
            session_id=session_id,
            input_id="inp_sel_sc",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"queries": ["SELECT * FROM accounts WHERE user_id = 123"]},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_sel_sc",
            session_id=session_id,
            correlation_id="c_p5_selsc",
            application_id=app_id,
            input_set_id="is_p5_selsc",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_selsc", application_id=app_id, input_set_id="is_p5_selsc", input_set_hash="h_selsc", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-SEL-CHANGE",
            name="State Change Required",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 39. MANDATORY QUERY PRECEDENCE TEST 1: UPDATE QUERY WITH EQUAL SNAPSHOTS YIELDS NO_STATE_CHANGE PASS (Section 16, 40)
    def test_query_precedence_test_1_update_query_with_equal_snapshots_yields_no_state_change_pass(self):
        """When an UPDATE query was executed but before/after snapshots are equal (e.g. 0 rows affected or no-op), NO_STATE_CHANGE evaluates to PASS."""
        session_id = "sess_p5_qp1"
        app_id = "app_p5_qp1"

        snap_a = {"accounts": {"row_count": 1, "rows": [{"id": 42, "balance": 100}], "table_hash": "hash_accounts_100"}}
        rec_r = EvidenceRecord(
            evidence_id="r_qp1",
            session_id=session_id,
            input_id="inp_qp1",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={
                "queries": ["UPDATE accounts SET balance = balance - 0 WHERE id = 42"],
                "snapshot_before": snap_a,
                "snapshot_after": snap_a,
            },
        )
        rec_t = EvidenceRecord(
            evidence_id="t_qp1",
            session_id=session_id,
            input_id="inp_qp1",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={
                "queries": ["UPDATE accounts SET balance = balance - 0 WHERE id = 42"],
                "snapshot_before": snap_a,
                "snapshot_after": snap_a,
            },
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_qp1",
            session_id=session_id,
            correlation_id="c_p5_qp1",
            application_id=app_id,
            input_set_id="is_p5_qp1",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_qp1", application_id=app_id, input_set_id="is_p5_qp1", input_set_hash="h_qp1", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-QP1-NO-CHANGE",
            name="No State Change Precedence",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.PASS
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS

    # 39B. MANDATORY QUERY PRECEDENCE TEST 2: UPDATE QUERY WITH DIFFERENT SNAPSHOTS YIELDS STATE_CHANGE PASS (Section 16, 40)
    def test_query_precedence_test_2_update_query_with_different_snapshots_yields_state_change_pass(self):
        """When an UPDATE query was executed and before/after snapshots differ, STATE_CHANGE evaluates to PASS."""
        session_id = "sess_p5_qp2"
        app_id = "app_p5_qp2"

        snap_a = {"accounts": {"row_count": 1, "rows": [{"id": 42, "balance": 100}], "table_hash": "hash_accounts_100"}}
        snap_b = {"accounts": {"row_count": 1, "rows": [{"id": 42, "balance": 50}], "table_hash": "hash_accounts_50"}}
        rec_r = EvidenceRecord(
            evidence_id="r_qp2",
            session_id=session_id,
            input_id="inp_qp2",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={
                "queries": ["UPDATE accounts SET balance = balance - 50 WHERE id = 42"],
                "snapshot_before": snap_a,
                "snapshot_after": snap_b,
            },
        )
        rec_t = EvidenceRecord(
            evidence_id="t_qp2",
            session_id=session_id,
            input_id="inp_qp2",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={
                "queries": ["UPDATE accounts SET balance = balance - 50 WHERE id = 42"],
                "snapshot_before": snap_a,
                "snapshot_after": snap_b,
            },
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_qp2",
            session_id=session_id,
            correlation_id="c_p5_qp2",
            application_id=app_id,
            input_set_id="is_p5_qp2",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_qp2", application_id=app_id, input_set_id="is_p5_qp2", input_set_hash="h_qp2", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-QP2-CHANGE",
            name="State Change Confirmed",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.PASS
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS

    # 39C. MANDATORY QUERY PRECEDENCE TEST 3: SELECT QUERY ALONE CANNOT PROVE STATE_CHANGE (Section 16, 40)
    def test_query_precedence_test_3_select_query_alone_yields_inconclusive_for_state_change(self):
        """When only a SELECT query is present without before/after snapshots, STATE_CHANGE evaluates to INCONCLUSIVE."""
        session_id = "sess_p5_qp3"
        app_id = "app_p5_qp3"

        rec_r = EvidenceRecord(
            evidence_id="r_qp3",
            session_id=session_id,
            input_id="inp_qp3",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"queries": ["SELECT * FROM accounts WHERE id = 42"]},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_qp3",
            session_id=session_id,
            input_id="inp_qp3",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"queries": ["SELECT * FROM accounts WHERE id = 42"]},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_qp3",
            session_id=session_id,
            correlation_id="c_p5_qp3",
            application_id=app_id,
            input_set_id="is_p5_qp3",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_qp3", application_id=app_id, input_set_id="is_p5_qp3", input_set_hash="h_qp3", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-QP3-CHANGE",
            name="State Change Required",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 39D. UPDATE WITH ZERO AFFECTED ROWS YIELDS INCONCLUSIVE FOR STATE_CHANGE (Section 13)
    def test_update_query_with_zero_affected_rows_yields_inconclusive_for_state_change(self):
        """UPDATE query with affected_rows=0 (e.g. condition matched 0 rows) yields INCONCLUSIVE for STATE_CHANGE."""
        session_id = "sess_p5_aff0"
        app_id = "app_p5_aff0"

        rec_r = EvidenceRecord(
            evidence_id="r_aff0",
            session_id=session_id,
            input_id="inp_aff0",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"queries": ["UPDATE accounts SET balance = 0 WHERE id = 99999"], "affected_rows": 0},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_aff0",
            session_id=session_id,
            input_id="inp_aff0",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"queries": ["UPDATE accounts SET balance = 0 WHERE id = 99999"], "affected_rows": 0},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_aff0",
            session_id=session_id,
            correlation_id="c_p5_aff0",
            application_id=app_id,
            input_set_id="is_p5_aff0",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_aff0", application_id=app_id, input_set_id="is_p5_aff0", input_set_hash="h_aff0", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-AFF0-CHANGE",
            name="State Change Required",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 39E. RAW QUERY WITH AFFECTED_ROWS WITHOUT BEFORE/AFTER SNAPSHOTS YIELDS INCONCLUSIVE (Section 12, 13)
    def test_raw_query_with_affected_rows_without_snapshots_yields_inconclusive(self):
        """Under Phase 3 contract, raw queries with arbitrary affected_rows without Phase 3 before/after snapshots yield INCONCLUSIVE."""
        session_id = "sess_p5_aff1"
        app_id = "app_p5_aff1"

        rec_r = EvidenceRecord(
            evidence_id="r_aff1",
            session_id=session_id,
            input_id="inp_aff1",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"queries": ["UPDATE accounts SET balance = 50 WHERE id = 42"], "affected_rows": 1, "records": [{"id": 42, "balance": 50}]},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_aff1",
            session_id=session_id,
            input_id="inp_aff1",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"queries": ["UPDATE accounts SET balance = 50 WHERE id = 42"], "affected_rows": 1, "records": [{"id": 42, "balance": 50}]},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_aff1",
            session_id=session_id,
            correlation_id="c_p5_aff1",
            application_id=app_id,
            input_set_id="is_p5_aff1",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_aff1", application_id=app_id, input_set_id="is_p5_aff1", input_set_hash="h_aff1", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-AFF1-CHANGE",
            name="State Change Required",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.INCONCLUSIVE
        assert assm.target_compliance == RuleComplianceVerdict.INCONCLUSIVE

    # 40. ROW_COUNT AS FIELD EVALUATION IN CONDITION REMAINS VALID (Section 10, 29)
    def test_row_count_as_field_condition_evaluation_remains_valid(self):
        """row_count is not rejected when explicitly evaluated by predicate conditions on state.row_count."""
        session_id = "sess_p5_rc_cond"
        app_id = "app_p5_rc_cond"

        rec_r = EvidenceRecord(
            evidence_id="r_rc_cd",
            session_id=session_id,
            input_id="inp_rc_cd",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"row_count": 0},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_rc_cd",
            session_id=session_id,
            input_id="inp_rc_cd",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"row_count": 0},
        )
        rec_r_out = EvidenceRecord(
            evidence_id="r_rc_out",
            session_id=session_id,
            input_id="inp_rc_cd",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "SUCCESS"}, "http_status": 200},
        )
        rec_t_out = EvidenceRecord(
            evidence_id="t_rc_out",
            session_id=session_id,
            input_id="inp_rc_cd",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "SUCCESS"}, "http_status": 200},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_rc_cd",
            session_id=session_id,
            correlation_id="c_p5_rccd",
            application_id=app_id,
            input_set_id="is_p5_rccd",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_rccd", application_id=app_id, input_set_id="is_p5_rccd", input_set_hash="h_rccd", records=[rec_r, rec_t, rec_r_out, rec_t_out]),
            records=[rec_r, rec_t, rec_r_out, rec_t_out],
        )

        rule = BusinessRule(
            rule_id="RULE-STATE-ROWCOUNT-0",
            name="Zero Row Count Check",
            condition=RulePredicate(field="row_count", field_source="state", operator=RuleOperator.EQ, value=0),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assm = res.rule_assessments[0]
        # Condition row_count == 0 evaluated to TRUE on state_dict
        assert assm.details["reference_applicability"] == "TRUE"
        assert assm.details["target_applicability"] == "TRUE"
        assert res.overall_verdict == RuleComplianceVerdict.PASS

    # 41. FILESYSTEM EXPLICIT FILE ABSENCE YIELDS NO_STATE_CHANGE PASS (Section 15, 29)
    def test_filesystem_explicit_file_absence_yields_no_state_change_pass(self):
        """Explicitly captured absence (exists=False before and after) proves NO_STATE_CHANGE as PASS."""
        session_id = "sess_p5_fs_abs"
        app_id = "app_p5_fs_abs"

        file_absent = {"/var/run/app.lock": {"path": "/var/run/app.lock", "exists": False, "size_bytes": 0}}
        rec_r = EvidenceRecord(
            evidence_id="r_fs_abs",
            session_id=session_id,
            input_id="inp_fs_abs",
            role="reference",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"before_state": file_absent, "after_state": file_absent},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_fs_abs",
            session_id=session_id,
            input_id="inp_fs_abs",
            role="target",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"before_state": file_absent, "after_state": file_absent},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_fs_abs",
            session_id=session_id,
            correlation_id="c_p5_fsabs",
            application_id=app_id,
            input_set_id="is_p5_fsabs",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_fsabs", application_id=app_id, input_set_id="is_p5_fsabs", input_set_hash="h_fsabs", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-FS-ABSENCE-NO-CHANGE",
            name="No Lock File Mutation",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.PASS
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS

    # 42. FILESYSTEM FILE CREATION (ABSENT -> PRESENT) YIELDS STATE_CHANGE PASS (Section 15, 29)
    def test_filesystem_file_creation_yields_state_change_pass(self):
        """Explicitly captured file creation (exists: False -> True) proves STATE_CHANGE as PASS."""
        session_id = "sess_p5_fs_create"
        app_id = "app_p5_fs_create"

        b_fs = {"/var/run/app.lock": {"path": "/var/run/app.lock", "exists": False, "size_bytes": 0}}
        a_fs = {"/var/run/app.lock": {"path": "/var/run/app.lock", "exists": True, "size_bytes": 12, "sha256_hash": "h_created"}}
        rec_r = EvidenceRecord(
            evidence_id="r_fs_crt",
            session_id=session_id,
            input_id="inp_fs_crt",
            role="reference",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"before_state": b_fs, "after_state": a_fs},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_fs_crt",
            session_id=session_id,
            input_id="inp_fs_crt",
            role="target",
            evidence_type=EvidenceType.FILESYSTEM,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"before_state": b_fs, "after_state": a_fs},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_fs_crt",
            session_id=session_id,
            correlation_id="c_p5_fscrt",
            application_id=app_id,
            input_set_id="is_p5_fscrt",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_fscrt", application_id=app_id, input_set_id="is_p5_fscrt", input_set_hash="h_fscrt", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-FS-CREATE-CHANGE",
            name="Lock File Created",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.PASS
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS

    # =========================================================================
    # FINAL PHASE 5 CLOSURE PERMANENT REGRESSION TESTS
    # =========================================================================

    # 43. CLOSURE ISSUE A: PLACEHOLDER EMPTY SNAPSHOTS ({}) YIELD INCONCLUSIVE (Mandatory Test #4, Section 21 Test 1)
    def test_closure_issue_a_placeholder_empty_snapshots_yield_inconclusive(self):
        """Unanchored empty database snapshots ({}) without table structure yield INCONCLUSIVE for NO_STATE_CHANGE."""
        session_id = "sess_p5_cls_ia_ph"
        app_id = "app_p5_cls_ia_ph"

        rec_r = EvidenceRecord(
            evidence_id="r_cls_ia_ph",
            session_id=session_id,
            input_id="inp_cls_ia_ph",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": {}, "snapshot_after": {}},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_cls_ia_ph",
            session_id=session_id,
            input_id="inp_cls_ia_ph",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": {}, "snapshot_after": {}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_cls_ia_ph",
            session_id=session_id,
            correlation_id="c_p5_cls_ia_ph",
            application_id=app_id,
            input_set_id="is_p5_cls_ia_ph",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_cls_ia_ph", application_id=app_id, input_set_id="is_p5_cls_ia_ph", input_set_hash="h_ia_ph", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-CLS-NO-STATE-CHANGE",
            name="No State Mutation",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.INCONCLUSIVE
        assert assm.target_compliance == RuleComplianceVerdict.INCONCLUSIVE

    # 44. CLOSURE ISSUE A: EXPLICITLY CAPTURED EMPTY DATABASE STATE YIELDS PASS (Mandatory Test #8, Section 22 Test 1)
    def test_closure_issue_a_explicitly_captured_empty_database_yields_pass(self):
        """Explicitly captured empty table state (e.g. table_hash of empty rows) proves NO_STATE_CHANGE as PASS."""
        session_id = "sess_p5_cls_ia_exp"
        app_id = "app_p5_cls_ia_exp"

        empty_tbl_snap = {"users": {"row_count": 0, "rows": [], "table_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}}
        rec_r = EvidenceRecord(
            evidence_id="r_cls_ia_exp",
            session_id=session_id,
            input_id="inp_cls_ia_exp",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": empty_tbl_snap, "snapshot_after": empty_tbl_snap},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_cls_ia_exp",
            session_id=session_id,
            input_id="inp_cls_ia_exp",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": empty_tbl_snap, "snapshot_after": empty_tbl_snap},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_cls_ia_exp",
            session_id=session_id,
            correlation_id="c_p5_cls_ia_exp",
            application_id=app_id,
            input_set_id="is_p5_cls_ia_exp",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_cls_ia_exp", application_id=app_id, input_set_id="is_p5_cls_ia_exp", input_set_hash="h_ia_exp", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-CLS-EMPTY-NO-CHANGE",
            name="Empty Table No Change",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.PASS
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS

    # 45. CLOSURE ISSUE B: GENERIC RECORDS DO NOT PROVE STATE MUTATION (Mandatory Test #5, Section 21 Test 2)
    def test_closure_issue_b_generic_records_do_not_prove_state_mutation(self):
        """Generic records (e.g. row dictionaries) without before/after state or confirmed mutation yield INCONCLUSIVE for STATE_CHANGE."""
        session_id = "sess_p5_cls_ib_gen"
        app_id = "app_p5_cls_ib_gen"

        rec_r = EvidenceRecord(
            evidence_id="r_cls_ib_gen",
            session_id=session_id,
            input_id="inp_cls_ib_gen",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"records": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_cls_ib_gen",
            session_id=session_id,
            input_id="inp_cls_ib_gen",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"records": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_cls_ib_gen",
            session_id=session_id,
            correlation_id="c_p5_cls_ib_gen",
            application_id=app_id,
            input_set_id="is_p5_cls_ib_gen",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_cls_ib_gen", application_id=app_id, input_set_id="is_p5_cls_ib_gen", input_set_hash="h_ib_gen", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-CLS-MUTATION-REQ",
            name="State Mutation Required",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.INCONCLUSIVE
        assert assm.target_compliance == RuleComplianceVerdict.INCONCLUSIVE

    # 46. CLOSURE ISSUE B: SELECT QUERY RESULTS IN RECORDS YIELD INCONCLUSIVE FOR STATE_CHANGE (Section 21 Test 3 & Mandatory Test #6)
    def test_closure_issue_b_select_query_results_in_records_yield_inconclusive(self):
        """Query result records from SELECT queries yield INCONCLUSIVE for STATE_CHANGE."""
        session_id = "sess_p5_cls_ib_sel"
        app_id = "app_p5_cls_ib_sel"

        rec_r = EvidenceRecord(
            evidence_id="r_cls_ib_sel",
            session_id=session_id,
            input_id="inp_cls_ib_sel",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"queries": ["SELECT * FROM accounts WHERE id = 1"], "records": [{"id": 1, "balance": 100}]},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_cls_ib_sel",
            session_id=session_id,
            input_id="inp_cls_ib_sel",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"queries": ["SELECT * FROM accounts WHERE id = 1"], "records": [{"id": 1, "balance": 100}]},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_cls_ib_sel",
            session_id=session_id,
            correlation_id="c_p5_cls_ib_sel",
            application_id=app_id,
            input_set_id="is_p5_cls_ib_sel",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_cls_ib_sel", application_id=app_id, input_set_id="is_p5_cls_ib_sel", input_set_hash="h_ib_sel", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-CLS-SELECT-NO-MUT",
            name="Select Query No Mutation Proof",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 47. CLOSURE ISSUE B: UPDATE QUERY WITH AFFECTED_ROWS=0 YIELDS INCONCLUSIVE (Mandatory Test #7, Section 51)
    def test_closure_issue_b_update_query_zero_affected_rows_yields_inconclusive(self):
        """An UPDATE query with affected_rows=0 does not prove persistent state mutation and yields INCONCLUSIVE."""
        session_id = "sess_p5_cls_ib_upd0"
        app_id = "app_p5_cls_ib_upd0"

        rec_r = EvidenceRecord(
            evidence_id="r_cls_ib_upd0",
            session_id=session_id,
            input_id="inp_cls_ib_upd0",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"queries": ["UPDATE accounts SET balance = balance WHERE id = 999"], "affected_rows": 0},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_cls_ib_upd0",
            session_id=session_id,
            input_id="inp_cls_ib_upd0",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"queries": ["UPDATE accounts SET balance = balance WHERE id = 999"], "affected_rows": 0},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_cls_ib_upd0",
            session_id=session_id,
            correlation_id="c_p5_cls_ib_upd0",
            application_id=app_id,
            input_set_id="is_p5_cls_ib_upd0",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_cls_ib_upd0", application_id=app_id, input_set_id="is_p5_cls_ib_upd0", input_set_hash="h_ib_upd0", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-CLS-UPD-ZERO",
            name="Zero Affected Rows Mutation Req",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 48. CLOSURE STATE DIFF: BEFORE=A / AFTER=B YIELDS STATE_CHANGE PASS (Mandatory Test #9, Section 22 Test 3)
    def test_closure_snapshot_diff_before_a_after_b_yields_state_change_pass(self):
        """When explicitly captured snapshot before (A) differs from after (B), STATE_CHANGE yields PASS."""
        session_id = "sess_p5_cls_diff"
        app_id = "app_p5_cls_diff"

        snap_a = {"users": {"row_count": 1, "rows": [{"id": 1}], "table_hash": "hash_a"}}
        snap_b = {"users": {"row_count": 2, "rows": [{"id": 1}, {"id": 2}], "table_hash": "hash_b"}}
        rec_r = EvidenceRecord(
            evidence_id="r_cls_diff",
            session_id=session_id,
            input_id="inp_cls_diff",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": snap_a, "snapshot_after": snap_b},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_cls_diff",
            session_id=session_id,
            input_id="inp_cls_diff",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": snap_a, "snapshot_after": snap_b},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_cls_diff",
            session_id=session_id,
            correlation_id="c_p5_cls_diff",
            application_id=app_id,
            input_set_id="is_p5_cls_diff",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_cls_diff", application_id=app_id, input_set_id="is_p5_cls_diff", input_set_hash="h_diff", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-CLS-DIFF-CHANGE",
            name="State Diff Requires Change",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.PASS
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS

    # 49. CLOSURE MANDATORY E2E #1: VALID OUTPUT + MALFORMED STATE OVERALL INCONCLUSIVE (Section 45)
    def test_closure_mandatory_e2e_1_valid_output_and_malformed_state(self):
        """Mandatory End-to-End Test #1: Output passes, state is malformed/partial -> Overall INCONCLUSIVE."""
        session_id = "sess_p5_cls_m1"
        app_id = "app_p5_cls_m1"

        rec_r_out = EvidenceRecord(
            evidence_id="r_m1_out",
            session_id=session_id,
            input_id="inp_m1",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "SUCCESS", "http_status": 200}, "normalized_output": {"status": "SUCCESS", "http_status": 200}, "amount": 100},
        )
        rec_t_out = EvidenceRecord(
            evidence_id="t_m1_out",
            session_id=session_id,
            input_id="inp_m1",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "SUCCESS", "http_status": 200}, "normalized_output": {"status": "SUCCESS", "http_status": 200}, "amount": 100},
        )
        rec_r_db = EvidenceRecord(
            evidence_id="r_m1_db",
            session_id=session_id,
            input_id="inp_m1",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.PARTIAL,
            payload={"queries": ["UPDATE accounts SET balance = balance - 100"]},
        )
        rec_t_db = EvidenceRecord(
            evidence_id="t_m1_db",
            session_id=session_id,
            input_id="inp_m1",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.PARTIAL,
            payload={"queries": ["UPDATE accounts SET balance = balance - 100"]},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_cls_m1",
            session_id=session_id,
            correlation_id="c_p5_cls_m1",
            application_id=app_id,
            input_set_id="is_p5_cls_m1",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_cls_m1", application_id=app_id, input_set_id="is_p5_cls_m1", input_set_hash="h_m1", records=[rec_r_out, rec_t_out, rec_r_db, rec_t_db]),
            records=[rec_r_out, rec_t_out, rec_r_db, rec_t_db],
        )

        rule_out = BusinessRule(
            rule_id="RULE-M1-OUTPUT",
            name="Output Must Succeed",
            condition=RulePredicate(field="amount", operator=RuleOperator.GT, value=0),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        rule_state = BusinessRule(
            rule_id="RULE-M1-STATE",
            name="State Mutation Required",
            condition=RulePredicate(field="amount", operator=RuleOperator.GT, value=0),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule_out, rule_state], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE
        assm_out = next(a for a in res.rule_assessments if a.rule_id == "RULE-M1-OUTPUT")
        assm_state = next(a for a in res.rule_assessments if a.rule_id == "RULE-M1-STATE")
        assert assm_out.overall_rule_status == RuleComplianceVerdict.PASS
        assert assm_state.overall_rule_status == RuleComplianceVerdict.INCONCLUSIVE

    # 50. CLOSURE MANDATORY E2E #2: ROLE CONTAMINATION SECRET ISOLATION (Section 46, Mandatory Test #2)
    def test_closure_mandatory_e2e_2_role_contamination_secret_isolation(self):
        """Mandatory End-to-End Test #2: Reference cannot see Target secret field, evaluating independently."""
        session_id = "sess_p5_cls_m2"
        app_id = "app_p5_cls_m2"

        rec_r = EvidenceRecord(
            evidence_id="r_m2",
            session_id=session_id,
            input_id="inp_m2",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK"}, "normalized_output": {"status": "OK"}},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_m2",
            session_id=session_id,
            input_id="inp_m2",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"status": "OK", "secret": 99}, "normalized_output": {"status": "OK", "secret": 99}},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_cls_m2",
            session_id=session_id,
            correlation_id="c_p5_cls_m2",
            application_id=app_id,
            input_set_id="is_p5_cls_m2",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_cls_m2", application_id=app_id, input_set_id="is_p5_cls_m2", input_set_hash="h_m2", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-M2-SECRET-99",
            name="Secret Must Equal 99",
            condition=RulePredicate(field="secret", operator=RuleOperator.EQ, value=99, field_source="output"),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assm = res.rule_assessments[0]
        # Reference is missing 'secret' field in output -> UNKNOWN condition -> NOT_APPLICABLE / INCONCLUSIVE
        assert assm.reference_compliance in (RuleComplianceVerdict.NOT_APPLICABLE, RuleComplianceVerdict.INCONCLUSIVE)
        # Target has secret == 99 -> TRUE condition -> APPLICABLE -> ACCEPT passes -> PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS

    # 51. MALFORMED SNAPSHOT CASE C: CAPTURE FAILED ERROR OBJECT YIELDS INCONCLUSIVE (Section 6 Case C)
    def test_malformed_snapshot_case_c_error_object_yields_inconclusive(self):
        """Database snapshot containing error object (e.g. {'error': 'capture failed'}) is malformed and yields INCONCLUSIVE."""
        session_id = "sess_p5_mal_c"
        app_id = "app_p5_mal_c"

        mal_snap = {"error": "capture failed"}
        rec_r = EvidenceRecord(
            evidence_id="r_mal_c",
            session_id=session_id,
            input_id="inp_mal_c",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": mal_snap, "snapshot_after": mal_snap},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_mal_c",
            session_id=session_id,
            input_id="inp_mal_c",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": mal_snap, "snapshot_after": mal_snap},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_mal_c",
            session_id=session_id,
            correlation_id="c_p5_mal_c",
            application_id=app_id,
            input_set_id="is_p5_mal_c",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_mal_c", application_id=app_id, input_set_id="is_p5_mal_c", input_set_hash="h_mal_c", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-MAL-C",
            name="Malformed Snapshot No Change",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 52. MALFORMED SNAPSHOT CASE D: EMPTY TABLE DICT YIELDS INCONCLUSIVE (Section 6 Case D)
    def test_malformed_snapshot_case_d_empty_table_dict_yields_inconclusive(self):
        """Database snapshot containing empty table dict (e.g. {'users': {}}) lacks contract fields and yields INCONCLUSIVE."""
        session_id = "sess_p5_mal_d"
        app_id = "app_p5_mal_d"

        mal_snap = {"users": {}}
        rec_r = EvidenceRecord(
            evidence_id="r_mal_d",
            session_id=session_id,
            input_id="inp_mal_d",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": mal_snap, "snapshot_after": mal_snap},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_mal_d",
            session_id=session_id,
            input_id="inp_mal_d",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": mal_snap, "snapshot_after": mal_snap},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_mal_d",
            session_id=session_id,
            correlation_id="c_p5_mal_d",
            application_id=app_id,
            input_set_id="is_p5_mal_d",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_mal_d", application_id=app_id, input_set_id="is_p5_mal_d", input_set_hash="h_mal_d", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-MAL-D",
            name="Empty Table Dict No Change",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 53. MALFORMED SNAPSHOT CASE E: ARBITRARY NON-CONTRACT DICT YIELDS INCONCLUSIVE (Section 6 Case E)
    def test_malformed_snapshot_case_e_arbitrary_non_contract_dict_yields_inconclusive(self):
        """Database snapshot containing arbitrary non-contract dict (e.g. {'users': {'bad': 'x'}}) yields INCONCLUSIVE."""
        session_id = "sess_p5_mal_e"
        app_id = "app_p5_mal_e"

        mal_snap = {"users": {"bad": "x"}}
        rec_r = EvidenceRecord(
            evidence_id="r_mal_e",
            session_id=session_id,
            input_id="inp_mal_e",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": mal_snap, "snapshot_after": mal_snap},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_mal_e",
            session_id=session_id,
            input_id="inp_mal_e",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": mal_snap, "snapshot_after": mal_snap},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_mal_e",
            session_id=session_id,
            correlation_id="c_p5_mal_e",
            application_id=app_id,
            input_set_id="is_p5_mal_e",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_mal_e", application_id=app_id, input_set_id="is_p5_mal_e", input_set_hash="h_mal_e", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-MAL-E",
            name="Non Contract Schema No Change",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 54. ASYMMETRIC STATE CHANGE CASE 3: REFERENCE CHANGES, TARGET DOES NOT (Section 8 Case 3)
    def test_asymmetric_state_change_reference_changes_target_does_not(self):
        """When Reference mutates state (PASS) but Target does not mutate (FAIL), overall rule status is FAIL."""
        session_id = "sess_p5_asym_r"
        app_id = "app_p5_asym_r"

        snap_a = {"users": {"row_count": 1, "rows": [{"id": 1}], "table_hash": "hash_a"}}
        snap_b = {"users": {"row_count": 2, "rows": [{"id": 1}, {"id": 2}], "table_hash": "hash_b"}}

        rec_r = EvidenceRecord(
            evidence_id="r_asym_r",
            session_id=session_id,
            input_id="inp_asym_r",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": snap_a, "snapshot_after": snap_b},  # State mutated
        )
        rec_t = EvidenceRecord(
            evidence_id="t_asym_r",
            session_id=session_id,
            input_id="inp_asym_r",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": snap_a, "snapshot_after": snap_a},  # State NOT mutated
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_asym_r",
            session_id=session_id,
            correlation_id="c_p5_asym_r",
            application_id=app_id,
            input_set_id="is_p5_asym_r",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_asym_r", application_id=app_id, input_set_id="is_p5_asym_r", input_set_hash="h_asym_r", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-ASYM-STATE-CHANGE",
            name="State Mutation Required",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.FAIL
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.FAIL

    # 55. ASYMMETRIC STATE CHANGE CASE 4: TARGET CHANGES, REFERENCE DOES NOT (Section 8 Case 4)
    def test_asymmetric_state_change_target_changes_reference_does_not(self):
        """When Target mutates state (PASS) but Reference does not mutate (FAIL), overall rule status is FAIL."""
        session_id = "sess_p5_asym_t"
        app_id = "app_p5_asym_t"

        snap_a = {"users": {"row_count": 1, "rows": [{"id": 1}], "table_hash": "hash_a"}}
        snap_b = {"users": {"row_count": 2, "rows": [{"id": 1}, {"id": 2}], "table_hash": "hash_b"}}

        rec_r = EvidenceRecord(
            evidence_id="r_asym_t",
            session_id=session_id,
            input_id="inp_asym_t",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": snap_a, "snapshot_after": snap_a},  # State NOT mutated
        )
        rec_t = EvidenceRecord(
            evidence_id="t_asym_t",
            session_id=session_id,
            input_id="inp_asym_t",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": snap_a, "snapshot_after": snap_b},  # State mutated
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_asym_t",
            session_id=session_id,
            correlation_id="c_p5_asym_t",
            application_id=app_id,
            input_set_id="is_p5_asym_t",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_asym_t", application_id=app_id, input_set_id="is_p5_asym_t", input_set_hash="h_asym_t", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-ASYM-STATE-CHANGE-2",
            name="State Mutation Required",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.FAIL
        assm = res.rule_assessments[0]
        assert assm.reference_compliance == RuleComplianceVerdict.FAIL
        assert assm.target_compliance == RuleComplianceVerdict.PASS

    # 56. CONTRACT-LOCK: ARBITRARY ROW LIST SNAPSHOT YIELDS INCONCLUSIVE (Section 1, 4, 8)
    def test_contract_lock_arbitrary_row_list_snapshot_yields_inconclusive(self):
        """Database snapshot formatted as an arbitrary list of rows (e.g. {'users': [{'id': 1}]}) is rejected under Phase 3 contract."""
        session_id = "sess_p5_lock_rowlist"
        app_id = "app_p5_lock_rowlist"

        mal_snap = {"users": [{"id": 1}]}
        rec_r = EvidenceRecord(
            evidence_id="r_lock_rl",
            session_id=session_id,
            input_id="inp_lock_rl",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": mal_snap, "snapshot_after": mal_snap},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_lock_rl",
            session_id=session_id,
            input_id="inp_lock_rl",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": mal_snap, "snapshot_after": mal_snap},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_lock_rl",
            session_id=session_id,
            correlation_id="c_p5_lock_rl",
            application_id=app_id,
            input_set_id="is_p5_lock_rl",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_lock_rl", application_id=app_id, input_set_id="is_p5_lock_rl", input_set_hash="h_rl", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-LOCK-ROWLIST",
            name="Row List Rejected",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 57. CONTRACT-LOCK: ARBITRARY PRIMARY-KEY ROW MAP YIELDS INCONCLUSIVE (Section 1, 4, 8)
    def test_contract_lock_primary_key_row_map_yields_inconclusive(self):
        """Database snapshot formatted as a primary-key row mapping (e.g. {'users': {'42': {'balance': 100}}}) is rejected."""
        session_id = "sess_p5_lock_pk"
        app_id = "app_p5_lock_pk"

        mal_snap = {"users": {"42": {"balance": 100}}}
        rec_r = EvidenceRecord(
            evidence_id="r_lock_pk",
            session_id=session_id,
            input_id="inp_lock_pk",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": mal_snap, "snapshot_after": mal_snap},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_lock_pk",
            session_id=session_id,
            input_id="inp_lock_pk",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": mal_snap, "snapshot_after": mal_snap},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_lock_pk",
            session_id=session_id,
            correlation_id="c_p5_lock_pk",
            application_id=app_id,
            input_set_id="is_p5_lock_pk",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_lock_pk", application_id=app_id, input_set_id="is_p5_lock_pk", input_set_hash="h_pk", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-LOCK-PK",
            name="PK Map Rejected",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 58. CONTRACT-LOCK: ARBITRARY NON-DICT VALUE YIELDS INCONCLUSIVE (Section 1, 4, 8)
    def test_contract_lock_non_dict_table_value_yields_inconclusive(self):
        """Database snapshot containing non-dict table value (e.g. {'fake_table': 123}) is rejected."""
        session_id = "sess_p5_lock_nondict"
        app_id = "app_p5_lock_nondict"

        mal_snap = {"fake_table": 123}
        rec_r = EvidenceRecord(
            evidence_id="r_lock_nd",
            session_id=session_id,
            input_id="inp_lock_nd",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": mal_snap, "snapshot_after": mal_snap},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_lock_nd",
            session_id=session_id,
            input_id="inp_lock_nd",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"snapshot_before": mal_snap, "snapshot_after": mal_snap},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_lock_nd",
            session_id=session_id,
            correlation_id="c_p5_lock_nd",
            application_id=app_id,
            input_set_id="is_p5_lock_nd",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_lock_nd", application_id=app_id, input_set_id="is_p5_lock_nd", input_set_hash="h_nd", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-LOCK-NONDICT",
            name="Non Dict Value Rejected",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE

    # 59. CONTRACT-LOCK: ACTUAL PHASE 3 DATABASE EVIDENCE PROVIDER INTEGRATION TEST (Section 31)
    def test_actual_phase3_provider_sqlite_integration(self, tmp_path):
        """End-to-end integration test using actual Phase 3 DatabaseEvidenceProvider against a real SQLite database."""
        import sqlite3
        from execution.evidence_providers import DatabaseEvidenceProvider

        db_file = tmp_path / "app_test.db"
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, balance REAL)")
            conn.execute("INSERT INTO users (id, name, balance) VALUES (1, 'Alice', 100.0)")
            conn.commit()

        provider = DatabaseEvidenceProvider(config={"database_path": str(db_file), "tables": ["users"]})

        # Capture before
        snap_before = provider.capture_before()
        assert "users" in snap_before
        assert snap_before["users"]["row_count"] == 1
        assert len(snap_before["users"]["rows"]) == 1
        assert "table_hash" in snap_before["users"]

        # Capture after without modifying (equal state)
        ev_after_eq = provider.capture_after()
        assert ev_after_eq["status"] == EvidenceCaptureStatus.CAPTURED
        assert ev_after_eq["delta_detected"] is False

        session_id = "sess_p5_real_p3"
        app_id = "app_p5_real_p3"

        rec_r_eq = EvidenceRecord(
            evidence_id="r_real_eq",
            session_id=session_id,
            input_id="inp_real_eq",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload=ev_after_eq,
        )
        rec_t_eq = EvidenceRecord(
            evidence_id="t_real_eq",
            session_id=session_id,
            input_id="inp_real_eq",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload=ev_after_eq,
        )
        bundle_eq = EvidenceBundle(
            bundle_id="bnd_p5_real_eq",
            session_id=session_id,
            correlation_id="c_p5_real_eq",
            application_id=app_id,
            input_set_id="is_p5_real_eq",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_real_eq", application_id=app_id, input_set_id="is_p5_real_eq", input_set_hash="h_req", records=[rec_r_eq, rec_t_eq]),
            records=[rec_r_eq, rec_t_eq],
        )

        rule_no_change = BusinessRule(
            rule_id="RULE-P3-NO-CHANGE",
            name="Real P3 Provider No Change",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.NO_STATE_CHANGE),
        )

        res_eq = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule_no_change], bundle=bundle_eq)
        assert res_eq.overall_verdict == RuleComplianceVerdict.PASS

        # Now mutate the database and capture after with diff
        provider._before_snapshot = snap_before
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute("UPDATE users SET balance = 150.0 WHERE id = 1")
            conn.commit()

        ev_after_diff = provider.capture_after()
        assert ev_after_diff["delta_detected"] is True

        rec_r_diff = EvidenceRecord(
            evidence_id="r_real_diff",
            session_id=session_id,
            input_id="inp_real_diff",
            role="reference",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload=ev_after_diff,
        )
        rec_t_diff = EvidenceRecord(
            evidence_id="t_real_diff",
            session_id=session_id,
            input_id="inp_real_diff",
            role="target",
            evidence_type=EvidenceType.DATABASE,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload=ev_after_diff,
        )
        bundle_diff = EvidenceBundle(
            bundle_id="bnd_p5_real_diff",
            session_id=session_id,
            correlation_id="c_p5_real_diff",
            application_id=app_id,
            input_set_id="is_p5_real_diff",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_real_diff", application_id=app_id, input_set_id="is_p5_real_diff", input_set_hash="h_rdiff", records=[rec_r_diff, rec_t_diff]),
            records=[rec_r_diff, rec_t_diff],
        )

        rule_change = BusinessRule(
            rule_id="RULE-P3-CHANGE",
            name="Real P3 Provider State Change",
            condition=RulePredicate(field="input_id", operator=RuleOperator.EXISTS),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.STATE_CHANGE),
        )

        res_diff = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule_change], bundle=bundle_diff)
        assert res_diff.overall_verdict == RuleComplianceVerdict.PASS


