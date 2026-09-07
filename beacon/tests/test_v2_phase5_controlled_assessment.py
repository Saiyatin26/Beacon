"""BEACON V2 — Phase 5 Controlled Mode Assessment Integration Tests.

Validates end-to-end evaluation of user-defined business rules over Phase 3 evidence
bundles and Phase 4 behavioral results, proving conservative aggregation, false-pass
elimination, traceability, and deterministic reproducibility.
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
    OutputEvidence,
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
        assert assm.reference_compliance == RuleComplianceVerdict.PASS
        assert assm.target_compliance == RuleComplianceVerdict.PASS
        assert assm.overall_rule_status == RuleComplianceVerdict.PASS
        assert assm.behavioral_equivalence == EvaluationVerdict.EQUIVALENT
        assert "r_out_1" in assm.reference_evidence_ids
        assert "t_out_1" in assm.target_evidence_ids

    # 2. TARGET VIOLATES RULE WHILE REFERENCE COMPLIES (FAIL)
    def test_e2e_target_violates_rule_yields_fail_and_distinguishes_p4_different(self):
        """Reference passes rule (ACCEPT), Target fails rule (REJECT / 400).
        Expected: Reference=PASS, Target=FAIL, Phase4=DIFFERENT, Overall Rule Status=FAIL.
        """
        session_id = "sess_p5_2"
        app_id = "app_p5_2"

        # Ref produces 200, Target produces 500 error
        rec_r = EvidenceRecord(
            evidence_id="r_out_2",
            session_id=session_id,
            input_id="inp_02",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"decision": "APPROVED", "http_status": 200}, "normalized_output": {"decision": "APPROVED", "http_status": 200}, "score": 750},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_out_2",
            session_id=session_id,
            input_id="inp_02",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"decision": "REJECTED", "http_status": 500}, "normalized_output": {"decision": "REJECTED", "http_status": 500}, "score": 750},
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
            rule_id="RULE-SCORE-01",
            name="Score Threshold",
            condition=RulePredicate(field="score", operator=RuleOperator.GTE, value=700),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        # Phase 4 evaluates difference
        p4_res = behavioral_evaluation_engine.evaluate_bundle(bundle, policy=DEFAULT_COMPARISON_POLICY)
        assert p4_res.verdict == EvaluationVerdict.DIFFERENT

        # Phase 5 evaluates rule compliance
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
        assert assm.overall_rule_status == RuleComplianceVerdict.FAIL
        assert assm.behavioral_equivalence == EvaluationVerdict.DIFFERENT

    # 3. RULE NOT TRIGGERED (NOT_APPLICABLE)
    def test_e2e_condition_not_triggered_yields_not_applicable(self):
        """When rule condition evaluates to False, status is NOT_APPLICABLE (never false PASS)."""
        session_id = "sess_p5_3"
        app_id = "app_p5_3"

        rec_r = EvidenceRecord(
            evidence_id="r_out_3",
            session_id=session_id,
            input_id="inp_minor",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"res": 1}, "normalized_output": {"res": 1}, "age": 15},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_out_3",
            session_id=session_id,
            input_id="inp_minor",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"res": 1}, "normalized_output": {"res": 1}, "age": 15},
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

        # Rule: age >= 18 -> ACCEPT (Input has age=15 -> False)
        rule = BusinessRule(
            rule_id="RULE-AGE-02",
            name="Adult Check",
            condition=RulePredicate(field="age", operator=RuleOperator.GTE, value=18),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(
            rules=[rule],
            bundle=bundle,
        )

        assert res.overall_verdict == RuleComplianceVerdict.NOT_APPLICABLE
        assm = res.rule_assessments[0]
        assert assm.applicability == "NOT_APPLICABLE"
        assert assm.reference_compliance == RuleComplianceVerdict.NOT_APPLICABLE
        assert assm.target_compliance == RuleComplianceVerdict.NOT_APPLICABLE
        assert assm.overall_rule_status == RuleComplianceVerdict.NOT_APPLICABLE

    # 4. PARTIAL / INSUFFICIENT EVIDENCE (INCONCLUSIVE)
    def test_e2e_partial_evidence_yields_inconclusive(self):
        """When evidence capture status is PARTIAL, rule assessment yields INCONCLUSIVE."""
        session_id = "sess_p5_4"
        app_id = "app_p5_4"

        rec_r = EvidenceRecord(
            evidence_id="r_out_4",
            session_id=session_id,
            input_id="inp_04",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"x": 1}, "normalized_output": {"x": 1}, "trigger": True},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_out_4",
            session_id=session_id,
            input_id="inp_04",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.PARTIAL,  # Incomplete capture!
            payload={"raw_output": {"x": 1}, "normalized_output": {"x": 1}, "trigger": True},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_4",
            session_id=session_id,
            correlation_id="c_p5_4",
            application_id=app_id,
            input_set_id="is_p5_4",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_4", application_id=app_id, input_set_id="is_p5_4", input_set_hash="h_4", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        rule = BusinessRule(
            rule_id="RULE-PART-01",
            name="Trigger Rule",
            condition=RulePredicate(field="trigger", operator=RuleOperator.EQ, value=True),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res = controlled_assessment_engine.evaluate_controlled_mode(
            rules=[rule],
            bundle=bundle,
        )

        assert res.overall_verdict == RuleComplianceVerdict.INCONCLUSIVE
        assm = res.rule_assessments[0]
        assert assm.applicability == "APPLICABLE"
        assert assm.target_compliance == RuleComplianceVerdict.INCONCLUSIVE
        assert assm.overall_rule_status == RuleComplianceVerdict.INCONCLUSIVE

    # 5. MULTIPLE RULES CONSERVATIVE AGGREGATION
    def test_e2e_multiple_rules_aggregation_priority(self):
        """Verify conservative aggregation priority: ERROR > FAIL > INCONCLUSIVE > PASS > NOT_APPLICABLE."""
        session_id = "sess_p5_5"
        app_id = "app_p5_5"

        rec_r = EvidenceRecord(
            evidence_id="r_5",
            session_id=session_id,
            input_id="inp_05",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"val": 100, "http_status": 200}, "normalized_output": {"val": 100, "http_status": 200}, "num": 50},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_5",
            session_id=session_id,
            input_id="inp_05",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            capture_status=EvidenceCaptureStatus.CAPTURED,
            payload={"raw_output": {"val": 100, "http_status": 200}, "normalized_output": {"val": 100, "http_status": 200}, "num": 50},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_5",
            session_id=session_id,
            correlation_id="c_p5_5",
            application_id=app_id,
            input_set_id="is_p5_5",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_5", application_id=app_id, input_set_id="is_p5_5", input_set_hash="h_5", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )

        # Rule 1: num >= 10 -> ACCEPT (Passes)
        rule_pass = BusinessRule(
            rule_id="R-PASS",
            name="Passing Rule",
            condition=RulePredicate(field="num", operator=RuleOperator.GTE, value=10),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )
        # Rule 2: num >= 10 -> RETURN_VALUE == 999 (Fails, because val=100)
        rule_fail = BusinessRule(
            rule_id="R-FAIL",
            name="Failing Rule",
            condition=RulePredicate(field="num", operator=RuleOperator.GTE, value=10),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.RETURN_VALUE, target_field="val", expected_value=999),
        )

        # Evaluating [rule_pass, rule_fail] must yield FAIL
        res = controlled_assessment_engine.evaluate_controlled_mode(
            rules=[rule_pass, rule_fail],
            bundle=bundle,
        )
        assert res.overall_verdict == RuleComplianceVerdict.FAIL
        assert res.summary.passed_rule_count == 1
        assert res.summary.failed_rule_count == 1

    # 6. DETERMINISTIC REPRODUCIBILITY
    def test_e2e_deterministic_evaluation_fingerprint(self):
        """Repeated controlled evaluations over identical rules and bundle produce identical evaluation_fingerprint."""
        session_id = "sess_p5_6"
        app_id = "app_p5_6"
        rec_r = EvidenceRecord(
            evidence_id="r_6",
            session_id=session_id,
            input_id="inp_06",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            payload={"raw_output": {"data": 1}, "normalized_output": {"data": 1}, "flag": True},
        )
        rec_t = EvidenceRecord(
            evidence_id="t_6",
            session_id=session_id,
            input_id="inp_06",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            payload={"raw_output": {"data": 1}, "normalized_output": {"data": 1}, "flag": True},
        )
        bundle = EvidenceBundle(
            bundle_id="bnd_p5_6",
            session_id=session_id,
            correlation_id="c_p5_6",
            application_id=app_id,
            input_set_id="is_p5_6",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p5_6", application_id=app_id, input_set_id="is_p5_6", input_set_hash="h_6", records=[rec_r, rec_t]),
            records=[rec_r, rec_t],
        )
        rule = BusinessRule(
            rule_id="R-DET",
            name="Deterministic Rule",
            condition=RulePredicate(field="flag", operator=RuleOperator.EQ, value=True),
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.ACCEPT),
        )

        res1 = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)
        res2 = controlled_assessment_engine.evaluate_controlled_mode(rules=[rule], bundle=bundle)

        assert res1.overall_verdict == RuleComplianceVerdict.PASS
        assert res2.overall_verdict == RuleComplianceVerdict.PASS
        assert res1.evaluation_fingerprint == res2.evaluation_fingerprint
        assert len(res1.evaluation_fingerprint) == 64

    # 7. REST API INTEGRATION
    def test_api_rules_crud_and_validation(self, client):
        """Verify REST API endpoints: /api/v2/rules, /api/v2/rules/validate."""
        # 1. Validate rule candidate
        valid_payload = {
            "rule": {
                "rule_id": "API-RULE-01",
                "name": "API Validated Rule",
                "condition": {"field": "amount", "operator": "GT", "value": 0},
                "expected_behavior": {"behavior_type": "ACCEPT"},
            }
        }
        res_val = client.post("/api/v2/rules/validate", json=valid_payload)
        assert res_val.status_code == 200
        assert res_val.json()["is_valid"] is True

        # 2. Create rule
        rule_payload = {
            "rule_id": "API-RULE-01",
            "name": "API Validated Rule",
            "condition": {"type": "predicate", "field": "amount", "operator": "GT", "value": 0},
            "expected_behavior": {"behavior_type": "ACCEPT"},
        }
        res_create = client.post("/api/v2/rules", json=rule_payload)
        assert res_create.status_code == 201
        created_data = res_create.json()
        assert created_data["rule_id"] == "API-RULE-01"
        assert created_data["version"] == 1
        assert len(created_data["fingerprint"]) == 64

        # 3. Get rule
        res_get = client.get("/api/v2/rules/API-RULE-01")
        assert res_get.status_code == 200
        assert res_get.json()["name"] == "API Validated Rule"

        # 4. List rules
        res_list = client.get("/api/v2/rules")
        assert res_list.status_code == 200
        assert len(res_list.json()) >= 1
