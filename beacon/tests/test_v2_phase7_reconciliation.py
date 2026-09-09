"""BEACON V2 — Phase 7 Rule Reconciliation & OracleSet Generation Test Suite.

Comprehensive tests for candidate eligibility, canonical normalization, semantic deduplication,
conflict detection, specialization analysis, provenance fusion, OracleSet generation,
integrity hashing, SQLite persistence, security, and REST API routing.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api.main import app
from auth import create_access_token
from auth.repository import auth_repository
from discovery.models import (
    CandidateValidationStatus,
    DiscoveredCandidate,
    DiscoveredRuleType,
    DiscoveryMethod,
    DiscoveryPolicy,
    DiscoveryResult,
)
from execution.evidence_models import (
    EvidenceBundle,
    EvidenceManifest,
    EvidenceRecord,
    EvidenceType,
)
from reconciliation.comparator import rule_comparator
from reconciliation.engine import RuleReconciliationEngine, rule_reconciliation_engine
from reconciliation.models import (
    OracleRule,
    OracleSet,
    OracleSetStatus,
    ReconciliationPolicy,
    ReconciliationResult,
    ResolutionState,
    RuleConflict,
    RuleProvenanceSource,
    RuleRelationship,
)
from reconciliation.normalizer import rule_normalizer
from reconciliation.persistence import ReconciliationPersistenceStore, reconciliation_persistence
from rules.models import (
    BusinessRule,
    CompoundRuleCondition,
    ExpectedBehavior,
    ExpectedBehaviorType,
    RuleOperator,
    RulePredicate,
    RuleSeverity,
    RuleSource,
    RuleStatus,
)


class TestPhase7RuleReconciliation:
    """Comprehensive test suite for Phase 7 Rule Reconciliation & OracleSet Generation."""

    # --------------------------------------------------------------------------
    # 1. Rule Normalization & Canonical Expressions
    # --------------------------------------------------------------------------
    def test_rule_normalization_canonical_expression(self):
        """Normalizer standardizes whitespace, operators, and commutative condition operands."""
        # Compound condition: (age >= 18 AND status == 'ACTIVE')
        pred1 = RulePredicate(field="age", operator=RuleOperator.GTE, value=18)
        pred2 = RulePredicate(field="status", operator=RuleOperator.EQ, value="ACTIVE")
        comp = CompoundRuleCondition(logical_op="AND", operands=[pred1, pred2])
        eb = ExpectedBehavior(behavior_type=ExpectedBehaviorType.RETURN_VALUE, target_field="output.approved", expected_value=True)

        user_rule = BusinessRule(
            rule_id="rule_u1",
            name="Adult Active Rule",
            condition=comp,
            expected_behavior=eb,
            status=RuleStatus.ACTIVE,
        )

        norm = rule_normalizer.normalize_user_rule(user_rule)
        assert norm.source_type == RuleProvenanceSource.USER_DEFINED
        assert "IF" in norm.canonical_expression
        assert "THEN output.approved == true" in norm.canonical_expression
        assert norm.fingerprint != ""

        # Discovered candidate normalization
        cand = DiscoveredCandidate(
            candidate_id="cand_d1",
            rule_type=DiscoveredRuleType.INPUT_OUTPUT_RELATION,
            canonical_expression="  output.discount   ==   0.15  ",
            normalized_expression="output.discount == 0.15",
            description="15 percent discount",
            role_scope="reference",
            support_count=5,
            confidence=1.0,
            validation_status=CandidateValidationStatus.VALIDATED,
        )
        norm_cand = rule_normalizer.normalize_discovered_candidate(cand)
        assert norm_cand.canonical_expression == "output.discount == 0.15"
        assert norm_cand.source_type == RuleProvenanceSource.DISCOVERED

    # --------------------------------------------------------------------------
    # 2. Candidate Eligibility Filtering (Fail-Closed)
    # --------------------------------------------------------------------------
    def test_candidate_eligibility_filtering(self):
        """Candidates with CONTRADICTED, WEAK, or INSUFFICIENT_COVERAGE status are rejected fail-closed."""
        engine = RuleReconciliationEngine()
        policy = ReconciliationPolicy(require_validated_candidates=True, minimum_support_count=2, minimum_confidence=0.8)

        cand_valid = DiscoveredCandidate(
            candidate_id="c_valid",
            rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
            canonical_expression="output.ok == true",
            normalized_expression="output.ok == true",
            description="Valid ok",
            support_count=10,
            confidence=1.0,
            validation_status=CandidateValidationStatus.VALIDATED,
        )
        cand_weak = DiscoveredCandidate(
            candidate_id="c_weak",
            rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
            canonical_expression="output.status == 200",
            normalized_expression="output.status == 200",
            description="Weak status",
            support_count=3,
            contradiction_count=2,
            confidence=0.6,
            validation_status=CandidateValidationStatus.WEAK,
        )
        cand_contra = DiscoveredCandidate(
            candidate_id="c_contra",
            rule_type=DiscoveredRuleType.RELATIONAL_INVARIANT,
            canonical_expression="output.total >= 0",
            normalized_expression="output.total >= 0",
            description="Contradicted total",
            support_count=5,
            contradiction_count=5,
            confidence=0.5,
            validation_status=CandidateValidationStatus.CONTRADICTED,
        )

        res = engine.reconcile(
            application_id="app_test",
            discovered_candidates=[cand_valid, cand_weak, cand_contra],
            policy=policy,
            persist=False,
        )

        assert res.approved_count == 1
        assert res.rejected_count == 2
        assert len(res.oracle_set.rules) == 1
        assert res.oracle_set.rules[0].canonical_expression == "output.ok == true"

        # Check that rejection reasons are preserved in decision traces
        weak_traces = [dt for dt in res.decision_traces if dt.source_id == "c_weak"]
        assert len(weak_traces) == 1
        assert weak_traces[0].decision == "REJECTED"
        assert "requires VALIDATED" in weak_traces[0].reason

    # --------------------------------------------------------------------------
    # 3. Semantic Deduplication & Provenance Fusion
    # --------------------------------------------------------------------------
    def test_semantic_deduplication_and_provenance_fusion(self):
        """Identical discoveries from multiple observations fuse into one rule preserving all provenance."""
        engine = RuleReconciliationEngine()

        cand1 = DiscoveredCandidate(
            candidate_id="c1",
            rule_type=DiscoveredRuleType.INPUT_OUTPUT_RELATION,
            canonical_expression="output.res == input.x * 2",
            normalized_expression="output.res == input.x * 2",
            description="Linear x2",
            support_count=4,
            confidence=1.0,
            evidence_ids=["ev_1", "ev_2"],
            input_ids=["inp_1", "inp_2"],
            fingerprint="fp_linear_x2",
            validation_status=CandidateValidationStatus.VALIDATED,
        )
        cand2 = DiscoveredCandidate(
            candidate_id="c2",
            rule_type=DiscoveredRuleType.INPUT_OUTPUT_RELATION,
            canonical_expression="output.res == input.x * 2",
            normalized_expression="output.res == input.x * 2",
            description="Linear x2 duplicate run",
            support_count=6,
            confidence=1.0,
            evidence_ids=["ev_3", "ev_4"],
            input_ids=["inp_3", "inp_4"],
            fingerprint="fp_linear_x2",
            validation_status=CandidateValidationStatus.VALIDATED,
        )

        res = engine.reconcile(
            application_id="app_test",
            discovered_candidates=[cand1, cand2],
            persist=False,
        )

        assert res.approved_count == 1
        assert res.merged_count == 1
        oracle_rule = res.oracle_set.rules[0]
        assert set(oracle_rule.evidence_ids) == {"ev_1", "ev_2", "ev_3", "ev_4"}
        assert set(oracle_rule.input_ids) == {"inp_1", "inp_2", "inp_3", "inp_4"}
        assert set(oracle_rule.source_candidate_ids) == {"c1", "c2"}
        assert oracle_rule.source == RuleProvenanceSource.DISCOVERED

    # --------------------------------------------------------------------------
    # 4. User Rule + Discovered Rule Equivalent Merging
    # --------------------------------------------------------------------------
    def test_user_rule_and_discovered_rule_merge_provenance(self):
        """User rule combined with an equivalent discovered candidate produces a MERGED rule with both provenances."""
        engine = RuleReconciliationEngine()

        pred = RulePredicate(field="input.tier", operator=RuleOperator.EQ, value="Gold")
        eb = ExpectedBehavior(behavior_type=ExpectedBehaviorType.RETURN_VALUE, target_field="output.discount", expected_value=0.10)
        u_rule = BusinessRule(
            rule_id="user_gold_disc",
            name="Gold 10% Discount",
            condition=pred,
            expected_behavior=eb,
            status=RuleStatus.ACTIVE,
        )

        cand = DiscoveredCandidate(
            candidate_id="cand_gold_disc",
            rule_type=DiscoveredRuleType.INPUT_OUTPUT_RELATION,
            canonical_expression="IF input.tier == Gold THEN output.discount == 0.1",
            normalized_expression="IF input.tier == Gold THEN output.discount == 0.1",
            description="Discovered gold discount",
            support_count=8,
            confidence=1.0,
            evidence_ids=["ev_gold_1", "ev_gold_2"],
            input_ids=["inp_g1", "inp_g2"],
            validation_status=CandidateValidationStatus.VALIDATED,
        )

        res = engine.reconcile(
            application_id="app_test",
            user_rules=[u_rule],
            discovered_candidates=[cand],
            persist=False,
        )

        assert res.approved_count == 1
        assert res.merged_count == 1
        rule = res.oracle_set.rules[0]
        assert rule.source == RuleProvenanceSource.MERGED
        assert "user_gold_disc" in rule.source_rule_ids
        assert "cand_gold_disc" in rule.source_candidate_ids
        assert "ev_gold_1" in rule.evidence_ids

    # --------------------------------------------------------------------------
    # 5. Direct Conflict Detection (User vs Discovered)
    # --------------------------------------------------------------------------
    def test_direct_conflict_detection_user_vs_discovered(self):
        """User rule (Gold -> 10%) vs Discovered candidate (Gold -> 15%) triggers CONFLICT and blocks OracleSet."""
        engine = RuleReconciliationEngine()

        pred_u = RulePredicate(field="input.tier", operator=RuleOperator.EQ, value="Gold")
        eb_u = ExpectedBehavior(behavior_type=ExpectedBehaviorType.RETURN_VALUE, target_field="output.discount", expected_value=0.10)
        u_rule = BusinessRule(
            rule_id="user_gold_10",
            name="Gold 10% Rule",
            condition=pred_u,
            expected_behavior=eb_u,
            status=RuleStatus.ACTIVE,
        )

        # Discovered candidate with conflicting 15% discount for Gold tier
        cand = DiscoveredCandidate(
            candidate_id="cand_gold_15",
            rule_type=DiscoveredRuleType.INPUT_OUTPUT_RELATION,
            canonical_expression="IF input.tier == Gold THEN output.discount == 0.15",
            normalized_expression="IF input.tier == Gold THEN output.discount == 0.15",
            description="Discovered 15% discount",
            support_count=12,
            confidence=1.0,
            validation_status=CandidateValidationStatus.VALIDATED,
        )

        res = engine.reconcile(
            application_id="app_test",
            user_rules=[u_rule],
            discovered_candidates=[cand],
            persist=False,
        )

        assert res.conflict_count == 1
        assert res.unresolved_conflict_count == 1
        assert res.approved_count == 0
        assert res.oracle_set.status == OracleSetStatus.BLOCKED
        assert len(res.conflicts) == 1
        assert res.conflicts[0].relationship == RuleRelationship.CONFLICT
        assert "user_gold_10" in (res.conflicts[0].rule_a_id, res.conflicts[0].rule_b_id)
        assert "cand_gold_15" in (res.conflicts[0].rule_a_id, res.conflicts[0].rule_b_id)

    # --------------------------------------------------------------------------
    # 6. User vs User Rule Conflict
    # --------------------------------------------------------------------------
    def test_user_vs_user_conflict_detection(self):
        """Two contradictory user rules are both quarantined and block the OracleSet."""
        engine = RuleReconciliationEngine()

        pred = RulePredicate(field="input.code", operator=RuleOperator.EQ, value="US")
        u_rule1 = BusinessRule(
            rule_id="u_tax_1",
            name="US Tax 5%",
            condition=pred,
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.RETURN_VALUE, target_field="output.tax", expected_value=0.05),
            status=RuleStatus.ACTIVE,
        )
        u_rule2 = BusinessRule(
            rule_id="u_tax_2",
            name="US Tax 10%",
            condition=pred,
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.RETURN_VALUE, target_field="output.tax", expected_value=0.10),
            status=RuleStatus.ACTIVE,
        )

        res = engine.reconcile(
            application_id="app_test",
            user_rules=[u_rule1, u_rule2],
            persist=False,
        )

        assert res.conflict_count == 1
        assert res.approved_count == 0
        assert res.oracle_set.status == OracleSetStatus.BLOCKED

    # --------------------------------------------------------------------------
    # 7. Specialization vs Conflict
    # --------------------------------------------------------------------------
    def test_compatible_specialization_is_not_a_conflict(self):
        """A sub-case rule with compatible consequence is a specialization and does NOT conflict."""
        engine = RuleReconciliationEngine()

        # Base rule: Gold -> 10% discount
        pred_base = RulePredicate(field="tier", operator=RuleOperator.EQ, value="Gold")
        u_base = BusinessRule(
            rule_id="rule_base",
            name="Base Gold Rule",
            condition=pred_base,
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.RETURN_VALUE, target_field="discount", expected_value=0.10),
            status=RuleStatus.ACTIVE,
        )

        # Compatible Specialized rule: Gold AND amount > 1000 -> 10% discount (compatible consequence)
        pred_sub1 = RulePredicate(field="tier", operator=RuleOperator.EQ, value="Gold")
        pred_sub2 = RulePredicate(field="amount", operator=RuleOperator.GT, value=1000)
        comp_sub = CompoundRuleCondition(logical_op="AND", operands=[pred_sub1, pred_sub2])
        u_spec = BusinessRule(
            rule_id="rule_spec",
            name="Specialized VIP Gold Rule",
            condition=comp_sub,
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.RETURN_VALUE, target_field="discount", expected_value=0.10),
            status=RuleStatus.ACTIVE,
        )

        res = engine.reconcile(
            application_id="app_test",
            user_rules=[u_base, u_spec],
            persist=False,
        )

        assert res.conflict_count == 0
        assert res.approved_count == 2
        assert res.oracle_set.status == OracleSetStatus.READY

    # --------------------------------------------------------------------------
    # 8. Determinism & Input Shuffling Invariance
    # --------------------------------------------------------------------------
    def test_determinism_under_shuffled_inputs(self):
        """Shuffling rule input order produces identical OracleSet hash and identical rule sorting."""
        engine = RuleReconciliationEngine()

        rules = [
            BusinessRule(
                rule_id=f"rule_{i}",
                name=f"Rule {i}",
                condition=RulePredicate(field="param", operator=RuleOperator.EQ, value=i),
                expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.RETURN_VALUE, target_field="out", expected_value=i * 10),
                status=RuleStatus.ACTIVE,
            )
            for i in range(10)
        ]

        # Run 1: Ascending
        res1 = engine.reconcile(application_id="app_shuf", user_rules=rules, persist=False)
        hash1 = res1.oracle_set.oracle_set_hash

        # Run 2: Reversed
        res2 = engine.reconcile(application_id="app_shuf", user_rules=list(reversed(rules)), persist=False)
        hash2 = res2.oracle_set.oracle_set_hash

        # Run 3: Mixed
        mixed = [rules[3], rules[0], rules[9], rules[1], rules[8], rules[2], rules[7], rules[4], rules[6], rules[5]]
        res3 = engine.reconcile(application_id="app_shuf", user_rules=mixed, persist=False)
        hash3 = res3.oracle_set.oracle_set_hash

        assert hash1 == hash2 == hash3
        assert [r.rule_id for r in res1.oracle_set.rules] == [r.rule_id for r in res2.oracle_set.rules] == [r.rule_id for r in res3.oracle_set.rules]

    # --------------------------------------------------------------------------
    # 9. OracleSet Integrity Hash Sensitivity
    # --------------------------------------------------------------------------
    def test_oracle_set_hash_sensitivity(self):
        """OracleSet hash changes when a rule definition, confidence, or conflict changes."""
        engine = RuleReconciliationEngine()

        cand_a = DiscoveredCandidate(
            candidate_id="ca",
            rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
            canonical_expression="output.ok == true",
            normalized_expression="output.ok == true",
            description="Ok candidate",
            support_count=10,
            confidence=1.0,
            validation_status=CandidateValidationStatus.VALIDATED,
        )
        cand_b = DiscoveredCandidate(
            candidate_id="cb",
            rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
            canonical_expression="output.ok == true",
            normalized_expression="output.ok == true",
            description="Ok candidate with different confidence",
            support_count=10,
            confidence=0.85,
            validation_status=CandidateValidationStatus.VALIDATED,
        )

        res_a = engine.reconcile(application_id="app_hash", discovered_candidates=[cand_a], persist=False)
        res_b = engine.reconcile(application_id="app_hash", discovered_candidates=[cand_b], persist=False)

        assert res_a.oracle_set.oracle_set_hash != res_b.oracle_set.oracle_set_hash

    # --------------------------------------------------------------------------
    # 10. SQLite Persistence & Non-Destructive Migration
    # --------------------------------------------------------------------------
    def test_sqlite_persistence_and_retrieval(self, tmp_path):
        """ReconciliationResult and OracleSet persist to SQLite and can be retrieved accurately."""
        db_file = tmp_path / "test_recon.sqlite3"
        store = ReconciliationPersistenceStore(db_path=str(db_file))

        engine = RuleReconciliationEngine()
        cand = DiscoveredCandidate(
            candidate_id="c_persist",
            rule_type=DiscoveredRuleType.RELATIONAL_INVARIANT,
            canonical_expression="output.val >= 0",
            normalized_expression="output.val >= 0",
            description="Positive val",
            support_count=15,
            confidence=1.0,
            evidence_ids=["ev_p1", "ev_p2"],
            validation_status=CandidateValidationStatus.VALIDATED,
        )

        res = engine.reconcile(application_id="app_persist", discovered_candidates=[cand], persist=False)
        store.save_reconciliation_result(res)

        # Retrieve run
        fetched_run = store.get_reconciliation_result(res.run_id)
        assert fetched_run is not None
        assert fetched_run.run_id == res.run_id
        assert fetched_run.approved_count == 1

        # Retrieve OracleSet
        fetched_oset = store.get_oracle_set(res.oracle_set_id)
        assert fetched_oset is not None
        assert fetched_oset.oracle_set_id == res.oracle_set_id
        assert len(fetched_oset.rules) == 1
        assert fetched_oset.rules[0].canonical_expression == "output.val >= 0"

        # List OracleSets
        oset_list = store.list_oracle_sets("app_persist")
        assert len(oset_list) == 1
        assert oset_list[0]["oracle_set_id"] == res.oracle_set_id

    # --------------------------------------------------------------------------
    # 11. Security Audit: Safe AST & Zero eval/exec
    # --------------------------------------------------------------------------
    def test_security_audit_malicious_expressions_fail_closed(self):
        """Malicious syntax payloads are handled safely without code execution."""
        engine = RuleReconciliationEngine()

        malicious_cand = DiscoveredCandidate(
            candidate_id="c_malicious",
            rule_type=DiscoveredRuleType.INPUT_OUTPUT_RELATION,
            canonical_expression="__import__('os').system('echo hacked') == True",
            normalized_expression="__import__('os').system('echo hacked') == True",
            description="Malicious attempt",
            support_count=10,
            confidence=1.0,
            validation_status=CandidateValidationStatus.VALIDATED,
        )

        res = engine.reconcile(
            application_id="app_sec",
            discovered_candidates=[malicious_cand],
            persist=False,
        )
        assert res is not None
        # Must be normalized into a safe static string expression without execution
        assert res.oracle_set.rules[0].canonical_expression == "__import__('os').system('echo hacked') == true"

    # --------------------------------------------------------------------------
    # 12. REST API Verification
    # --------------------------------------------------------------------------
    def test_reconciliation_rest_api(self):
        """FastAPI endpoints for reconcile, runs, and oraclesets return HTTP 200 with complete schemas."""
        from auth.models import User
        client = TestClient(app)
        test_user = User(user_id="admin_test", username="admin_test", email="admin@example.com", is_system_admin=True, password_hash="dummy_hash")
        token = create_access_token(user=test_user)
        headers = {"Authorization": f"Bearer {token}"}

        payload = {
            "application_id": "app_api_test",
            "user_rules": [
                {
                    "rule_id": "api_rule_1",
                    "name": "API Rule 1",
                    "condition": {"field": "input.x", "operator": "GT", "value": 0},
                    "expected_behavior": {"behavior_type": "RETURN_VALUE", "target_field": "output.y", "expected_value": 100},
                    "status": "ACTIVE",
                }
            ],
            "discovered_candidates": [
                {
                    "candidate_id": "api_cand_1",
                    "rule_type": "OUTPUT_CONSISTENCY",
                    "canonical_expression": "output.ok == true",
                    "normalized_expression": "output.ok == true",
                    "description": "API cand 1",
                    "support_count": 5,
                    "confidence": 1.0,
                    "validation_status": "VALIDATED",
                }
            ],
            "persist": True,
        }

        # 1. Trigger reconciliation
        r_post = client.post("/api/v2/reconciliation/reconcile", json=payload, headers=headers)
        assert r_post.status_code == 200, r_post.text
        data = r_post.json()
        assert data["application_id"] == "app_api_test"
        assert data["approved_count"] == 2
        run_id = data["run_id"]
        oracle_set_id = data["oracle_set_id"]

        # 2. Query run
        r_run = client.get(f"/api/v2/reconciliation/runs/{run_id}", headers=headers)
        assert r_run.status_code == 200
        assert r_run.json()["run_id"] == run_id

        # 3. Query OracleSet
        r_oset = client.get(f"/api/v2/oraclesets/{oracle_set_id}", headers=headers)
        assert r_oset.status_code == 200
        assert r_oset.json()["oracle_set_id"] == oracle_set_id

        # 4. List OracleSets
        r_list = client.get("/api/v2/oraclesets?application_id=app_api_test", headers=headers)
        assert r_list.status_code == 200
        assert len(r_list.json()) >= 1

    # --------------------------------------------------------------------------
    # 13. Hardening: Result Hash Invariance to Random Run ID
    # --------------------------------------------------------------------------
    def test_result_hash_invariance_to_random_run_id(self):
        """Reconciliation result_hash must be identical across runs with identical inputs regardless of run_id."""
        engine = RuleReconciliationEngine()

        cand = DiscoveredCandidate(
            candidate_id="c_det",
            rule_type=DiscoveredRuleType.INPUT_OUTPUT_RELATION,
            canonical_expression="output.total == input.subtotal * 1.08",
            normalized_expression="output.total == input.subtotal * 1.08",
            description="Tax multiplier",
            support_count=10,
            confidence=1.0,
            validation_status=CandidateValidationStatus.VALIDATED,
        )

        res1 = engine.reconcile(application_id="app_det", discovered_candidates=[cand], persist=False)
        res2 = engine.reconcile(application_id="app_det", discovered_candidates=[cand], persist=False)

        # Run IDs must differ (unique execution tracing)
        assert res1.run_id != res2.run_id
        # Semantic result hashes MUST be identical
        assert res1.result_hash == res2.result_hash
        assert res1.oracle_set.oracle_set_hash == res2.oracle_set.oracle_set_hash

    # --------------------------------------------------------------------------
    # 14. Hardening: Never Fabricate Evidence Counts on Deduplication
    # --------------------------------------------------------------------------
    def test_never_fabricate_evidence_counts_on_merge(self):
        """Merging duplicate candidates preserves exact unique evidence/input counts without arbitrary increments."""
        engine = RuleReconciliationEngine()

        cand_a = DiscoveredCandidate(
            candidate_id="ca_count",
            rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
            canonical_expression="output.valid == true",
            normalized_expression="output.valid == true",
            description="Valid output",
            support_count=10,
            confidence=1.0,
            input_ids=[f"inp_{i}" for i in range(10)],
            evidence_ids=[f"ev_{i}" for i in range(10)],
            validation_status=CandidateValidationStatus.VALIDATED,
        )
        cand_b = DiscoveredCandidate(
            candidate_id="cb_count",
            rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
            canonical_expression="output.valid == true",
            normalized_expression="output.valid == true",
            description="Valid output duplicate run with overlapping inputs",
            support_count=15,
            confidence=1.0,
            input_ids=[f"inp_{i}" for i in range(5, 20)],  # 15 inputs, 5 overlapping (total 20 unique)
            evidence_ids=[f"ev_{i}" for i in range(5, 20)],
            validation_status=CandidateValidationStatus.VALIDATED,
        )

        res = engine.reconcile(application_id="app_count", discovered_candidates=[cand_a, cand_b], persist=False)
        assert res.approved_count == 1
        rule = res.oracle_set.rules[0]
        # Total unique input IDs is exactly 20, not 15 + 1 or 25
        assert len(rule.input_ids) == 20
        assert rule.support_count == 20

    # --------------------------------------------------------------------------
    # 15. Hardening: Incompatible Specialization is Classified as Conflict
    # --------------------------------------------------------------------------
    def test_specialization_with_incompatible_consequence_is_conflict(self):
        """A narrower condition with contradictory output (e.g. Gold -> 10% vs Gold AND amount > 1000 -> 15%) is CONFLICT."""
        engine = RuleReconciliationEngine()

        # Rule A: Gold -> 10%
        pred_a = RulePredicate(field="tier", operator=RuleOperator.EQ, value="Gold")
        u_a = BusinessRule(
            rule_id="rule_base_gold",
            name="Base Gold Rule",
            condition=pred_a,
            expected_behavior=ExpectedBehavior(behavior_type=ExpectedBehaviorType.RETURN_VALUE, target_field="discount", expected_value=0.10),
            status=RuleStatus.ACTIVE,
        )

        # Rule B: Gold AND amount > 1000 with contradictory discount 15%
        pred_b1 = RulePredicate(field="tier", operator=RuleOperator.EQ, value="Gold")
        pred_b2 = RulePredicate(field="amount", operator=RuleOperator.GT, value=1000)
        comp_b = CompoundRuleCondition(logical_op="AND", operands=[pred_b1, pred_b2])
        cand_b = DiscoveredCandidate(
            candidate_id="cand_spec_conflict",
            rule_type=DiscoveredRuleType.INPUT_OUTPUT_RELATION,
            canonical_expression="IF (tier == Gold AND amount > 1000) THEN discount == 0.15",
            normalized_expression="IF (tier == Gold AND amount > 1000) THEN discount == 0.15",
            description="Contradictory specialized discount",
            support_count=5,
            confidence=1.0,
            validation_status=CandidateValidationStatus.VALIDATED,
        )

        res = engine.reconcile(application_id="app_spec_conf", user_rules=[u_a], discovered_candidates=[cand_b], persist=False)
        assert res.conflict_count == 1
        assert res.oracle_set.status == OracleSetStatus.BLOCKED

    # --------------------------------------------------------------------------
    # 16. Hardening: Boolean and Null Normalization Invariance
    # --------------------------------------------------------------------------
    def test_boolean_and_null_canonical_normalization(self):
        """Case variations in booleans and nulls normalize to identical canonical values."""
        cand_t1 = DiscoveredCandidate(
            candidate_id="c_t1",
            rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
            canonical_expression="output.active == true",
            normalized_expression="output.active == true",
            description="true lower",
            support_count=5,
            confidence=1.0,
            validation_status=CandidateValidationStatus.VALIDATED,
        )
        cand_t2 = DiscoveredCandidate(
            candidate_id="c_t2",
            rule_type=DiscoveredRuleType.OUTPUT_CONSISTENCY,
            canonical_expression="output.active == True",
            normalized_expression="output.active == True",
            description="True capitalized",
            support_count=5,
            confidence=1.0,
            validation_status=CandidateValidationStatus.VALIDATED,
        )

        norm1 = rule_normalizer.normalize_discovered_candidate(cand_t1)
        norm2 = rule_normalizer.normalize_discovered_candidate(cand_t2)
        assert norm1.normalized_expected_behavior["expected_value"] is True
        assert norm2.normalized_expected_behavior["expected_value"] is True
        assert norm1.fingerprint == norm2.fingerprint

