"""BEACON V2 — Phase 6 Behavioral Rule / Invariant Discovery Test Suite.

Comprehensive tests for candidate generation, empirical validation, 3-valued observation matrix extraction,
deterministic deduplication & ranking, SQLite persistence, role separation, and real Phase 3 integration.
"""

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
from discovery.engine import RuleDiscoveryEngine, rule_discovery_engine
from discovery.generators.boundary import BoundaryCandidateGenerator
from discovery.generators.error_behavior import ErrorBehaviorCandidateGenerator
from discovery.generators.input_output import InputOutputCandidateGenerator
from discovery.generators.nullability import NullabilityCandidateGenerator
from discovery.generators.relational import RelationalCandidateGenerator
from discovery.generators.state import StateCandidateGenerator
from discovery.generators.type_shape import TypeShapeCandidateGenerator
from discovery.generators.workflow import WorkflowCandidateGenerator
from discovery.matrix import observation_matrix_builder
from discovery.models import (
    CandidateValidationStatus,
    DiscoveredCandidate,
    DiscoveredRuleType,
    DiscoveryMethod,
    DiscoveryPolicy,
    DiscoveryResult,
    ObservationFact,
)
from discovery.normalizer import candidate_normalizer
from discovery.persistence import DiscoveryPersistenceStore, discovery_persistence
from discovery.ranking import candidate_ranker
from discovery.validator import candidate_validator
from execution.evidence_models import (
    EvidenceBundle,
    EvidenceCaptureStatus,
    EvidenceManifest,
    EvidenceRecord,
    EvidenceType,
)
from execution.evidence_providers import DatabaseEvidenceProvider


class TestPhase6RuleDiscovery:
    """Comprehensive test suite for Phase 6 Rule / Invariant Discovery Engine."""

    # --------------------------------------------------------------------------
    # 1. Models, Fingerprints & Normalization
    # --------------------------------------------------------------------------
    def test_models_canonicalization_and_fingerprints(self):
        """Candidate fingerprint is deterministic and unaffected by extraneous runtime attributes."""
        cand1 = DiscoveredCandidate(
            discovery_id="disc_1",
            candidate_id="c1",
            rule_type=DiscoveredRuleType.INPUT_OUTPUT_RELATION,
            canonical_expression="output.y == input.x",
            normalized_expression="output.y == input.x",
            description="y equals x",
            variables=["output.y", "input.x"],
            source_fields=["output.y", "input.x"],
            role_scope="reference",
        )
        cand2 = DiscoveredCandidate(
            discovery_id="disc_2",
            candidate_id="c2",
            rule_type=DiscoveredRuleType.INPUT_OUTPUT_RELATION,
            canonical_expression="output.y == input.x",
            normalized_expression="output.y == input.x",
            description="y equals x",
            variables=["output.y", "input.x"],
            source_fields=["output.y", "input.x"],
            role_scope="reference",
        )
        assert cand1.fingerprint == cand2.fingerprint
        assert len(cand1.fingerprint) == 64

    def test_commutative_expression_normalization(self):
        """Commutative binary expressions normalize symmetrically."""
        norm1 = candidate_normalizer.normalize_expression("output.b == output.a")
        norm2 = candidate_normalizer.normalize_expression("output.a == output.b")
        assert norm1 == "output.a == output.b"
        assert norm2 == "output.a == output.b"

    def test_discovery_policy_validation_and_hash(self):
        """DiscoveryPolicy produces deterministic policy hashes."""
        p1 = DiscoveryPolicy(minimum_support_count=3, minimum_confidence=0.9)
        p2 = DiscoveryPolicy(minimum_support_count=3, minimum_confidence=0.9)
        p3 = DiscoveryPolicy(minimum_support_count=5, minimum_confidence=0.9)

        assert p1.compute_policy_hash() == p2.compute_policy_hash()
        assert p1.compute_policy_hash() != p3.compute_policy_hash()

    # --------------------------------------------------------------------------
    # 2. Input -> Output Relation & Formula Discovery
    # --------------------------------------------------------------------------
    def test_input_output_linear_formula_discovery(self):
        """Observations x=1->y=2, x=2->y=4, x=3->y=6 discover y == 2 * x."""
        facts = [
            ObservationFact(input_id="inp_1", role="reference", input_data={"x": 1}, output_data={"y": 2}),
            ObservationFact(input_id="inp_2", role="reference", input_data={"x": 2}, output_data={"y": 4}),
            ObservationFact(input_id="inp_3", role="reference", input_data={"x": 3}, output_data={"y": 6}),
        ]
        policy = DiscoveryPolicy(minimum_support_count=2, minimum_confidence=0.8)
        gen = InputOutputCandidateGenerator()
        candidates = gen.generate_candidates(facts, policy, role_scope="reference")

        formula_cands = [c for c in candidates if "2" in c.canonical_expression and "input.x" in c.canonical_expression]
        assert len(formula_cands) >= 1
        cand = formula_cands[0]
        assert "output.y == 2 * input.x" in cand.canonical_expression

        # Validate candidate
        val = candidate_validator.validate_candidate(cand, facts, policy)
        assert val.support_count == 3
        assert val.contradiction_count == 0
        assert val.confidence == 1.0
        assert val.validation_status == CandidateValidationStatus.VALIDATED

    def test_input_output_contradiction_handling(self):
        """When an observation contradicts a formula candidate, contradiction count is incremented."""
        facts = [
            ObservationFact(input_id="inp_1", role="reference", input_data={"x": 1}, output_data={"y": 2}),
            ObservationFact(input_id="inp_2", role="reference", input_data={"x": 2}, output_data={"y": 4}),
            ObservationFact(input_id="inp_3", role="reference", input_data={"x": 3}, output_data={"y": 6}),
            ObservationFact(input_id="inp_4", role="reference", input_data={"x": 4}, output_data={"y": 9}),  # Contradiction
        ]
        policy = DiscoveryPolicy(minimum_support_count=2, minimum_confidence=0.8)
        cand = DiscoveredCandidate(
            discovery_id="disc_1",
            candidate_id="c_formula",
            rule_type=DiscoveredRuleType.INPUT_OUTPUT_RELATION,
            canonical_expression="output.y == 2 * input.x",
            normalized_expression="output.y == 2 * input.x",
            description="y = 2*x",
            variables=["output.y", "input.x"],
            source_fields=["output.y", "input.x"],
        )
        val = candidate_validator.validate_candidate(cand, facts, policy)
        assert val.support_count == 3
        assert val.contradiction_count == 1
        assert val.confidence == 0.75
        assert val.validation_status in (CandidateValidationStatus.WEAK, CandidateValidationStatus.CONTRADICTED)

    def test_input_output_direct_copy_and_constant_discovery(self):
        """Direct field copy and constant output value discovery."""
        facts = [
            ObservationFact(input_id="inp_1", role="reference", input_data={"name": "Alice"}, output_data={"user": "Alice", "status": "OK"}),
            ObservationFact(input_id="inp_2", role="reference", input_data={"name": "Bob"}, output_data={"user": "Bob", "status": "OK"}),
            ObservationFact(input_id="inp_3", role="reference", input_data={"name": "Charlie"}, output_data={"user": "Charlie", "status": "OK"}),
        ]
        policy = DiscoveryPolicy(minimum_support_count=2)
        gen = InputOutputCandidateGenerator()
        candidates = gen.generate_candidates(facts, policy, role_scope="reference")

        copy_cand = [c for c in candidates if c.canonical_expression == "output.user == input.name"]
        const_cand = [c for c in candidates if c.canonical_expression == "output.status == 'OK'"]

        assert len(copy_cand) == 1
        assert len(const_cand) == 1

    # --------------------------------------------------------------------------
    # 3. Type & Shape Invariants
    # --------------------------------------------------------------------------
    def test_type_and_shape_invariants(self):
        """Type stability discovers typeof(output.x) == 'integer'."""
        facts = [
            ObservationFact(input_id="inp_1", role="reference", output_data={"count": 10, "label": "A"}),
            ObservationFact(input_id="inp_2", role="reference", output_data={"count": 20, "label": "B"}),
            ObservationFact(input_id="inp_3", role="reference", output_data={"count": 30, "label": "C"}),
        ]
        policy = DiscoveryPolicy(minimum_support_count=2)
        gen = TypeShapeCandidateGenerator()
        candidates = gen.generate_candidates(facts, policy, role_scope="reference")

        count_type = [c for c in candidates if c.canonical_expression == "typeof(output.count) == 'integer'"]
        label_type = [c for c in candidates if c.canonical_expression == "typeof(output.label) == 'string'"]

        assert len(count_type) == 1
        assert len(label_type) == 1

    def test_mixed_types_do_not_generate_false_type_invariant(self):
        """Mixed types (int and str) do NOT generate a false universal integer invariant."""
        facts = [
            ObservationFact(input_id="inp_1", role="reference", output_data={"val": 10}),
            ObservationFact(input_id="inp_2", role="reference", output_data={"val": "twenty"}),
        ]
        policy = DiscoveryPolicy(minimum_support_count=2)
        gen = TypeShapeCandidateGenerator()
        candidates = gen.generate_candidates(facts, policy, role_scope="reference")
        type_candidates = [c for c in candidates if c.canonical_expression.startswith("typeof")]
        assert len(type_candidates) == 0

    # --------------------------------------------------------------------------
    # 4. Nullability & Value Distinction
    # --------------------------------------------------------------------------
    def test_nullability_and_presence_patterns(self):
        """Presence and non-null invariants are cleanly discovered."""
        facts = [
            ObservationFact(input_id="inp_1", role="reference", output_data={"score": 100}),
            ObservationFact(input_id="inp_2", role="reference", output_data={"score": 0}),  # Zero is valid non-null!
            ObservationFact(input_id="inp_3", role="reference", output_data={"score": -5}),
        ]
        policy = DiscoveryPolicy(minimum_support_count=2)
        gen = NullabilityCandidateGenerator()
        candidates = gen.generate_candidates(facts, policy, role_scope="reference")

        exists_cand = [c for c in candidates if c.canonical_expression == "exists(output.score)"]
        notnull_cand = [c for c in candidates if c.canonical_expression == "output.score != null"]

        assert len(exists_cand) == 1
        assert len(notnull_cand) == 1

    # --------------------------------------------------------------------------
    # 5. Relational Ordering Invariants
    # --------------------------------------------------------------------------
    def test_relational_ordering_invariants(self):
        """Inequality relationships like input.low <= output.high are discovered."""
        facts = [
            ObservationFact(input_id="inp_1", role="reference", input_data={"low": 10}, output_data={"high": 20}),
            ObservationFact(input_id="inp_2", role="reference", input_data={"low": 50}, output_data={"high": 50}),
            ObservationFact(input_id="inp_3", role="reference", input_data={"low": 0}, output_data={"high": 5}),
        ]
        policy = DiscoveryPolicy(minimum_support_count=2)
        gen = RelationalCandidateGenerator()
        candidates = gen.generate_candidates(facts, policy, role_scope="reference")

        le_cands = [c for c in candidates if c.canonical_expression == "input.low <= output.high"]
        assert len(le_cands) == 1

        val = candidate_validator.validate_candidate(le_cands[0], facts, policy)
        assert val.support_count == 3
        assert val.contradiction_count == 0
        assert val.validation_status == CandidateValidationStatus.VALIDATED

    # --------------------------------------------------------------------------
    # 6. Error Behavior Patterns
    # --------------------------------------------------------------------------
    def test_error_behavior_patterns(self):
        """Universal error-free execution produces has_error == false."""
        facts = [
            ObservationFact(input_id="inp_1", role="reference", has_error=False),
            ObservationFact(input_id="inp_2", role="reference", has_error=False),
            ObservationFact(input_id="inp_3", role="reference", has_error=False),
        ]
        policy = DiscoveryPolicy(minimum_support_count=2)
        gen = ErrorBehaviorCandidateGenerator()
        candidates = gen.generate_candidates(facts, policy, role_scope="reference")

        no_err = [c for c in candidates if c.canonical_expression == "has_error == false"]
        assert len(no_err) == 1

    # --------------------------------------------------------------------------
    # 7. State Invariants & Transitions (Phase 3 Contract)
    # --------------------------------------------------------------------------
    def test_state_invariant_and_transition_discovery(self):
        """Valid Phase 3 snapshots discover state invariance and mutation."""
        snap_a = {"users": {"row_count": 1, "rows": [{"id": 1}], "table_hash": "hash_a"}}
        snap_b = {"users": {"row_count": 2, "rows": [{"id": 1}, {"id": 2}], "table_hash": "hash_b"}}

        # Equal snapshots -> NO mutation invariant
        facts_eq = [
            ObservationFact(input_id="inp_1", role="reference", state_before=snap_a, state_after=snap_a, state_valid=True, state_mutated=False),
            ObservationFact(input_id="inp_2", role="reference", state_before=snap_a, state_after=snap_a, state_valid=True, state_mutated=False),
        ]
        policy = DiscoveryPolicy(minimum_support_count=2)
        gen = StateCandidateGenerator()
        cands_eq = gen.generate_candidates(facts_eq, policy, role_scope="reference")
        assert any(c.canonical_expression == "state.mutated == false" for c in cands_eq)

        # Mutated snapshots -> State Transition
        facts_diff = [
            ObservationFact(input_id="inp_1", role="reference", state_before=snap_a, state_after=snap_b, state_valid=True, state_mutated=True),
            ObservationFact(input_id="inp_2", role="reference", state_before=snap_a, state_after=snap_b, state_valid=True, state_mutated=True),
        ]
        cands_diff = gen.generate_candidates(facts_diff, policy, role_scope="reference")
        assert any(c.canonical_expression == "state.mutated == true" for c in cands_diff)

    def test_invalid_state_evidence_does_not_generate_false_state_invariant(self):
        """Uncontracted or invalid state evidence does NOT produce state invariants."""
        facts_invalid = [
            ObservationFact(input_id="inp_1", role="reference", state_valid=False),
            ObservationFact(input_id="inp_2", role="reference", state_valid=False),
        ]
        policy = DiscoveryPolicy(minimum_support_count=2)
        gen = StateCandidateGenerator()
        candidates = gen.generate_candidates(facts_invalid, policy, role_scope="reference")
        assert len(candidates) == 0

    # --------------------------------------------------------------------------
    # 8. Workflow Sequence Mining
    # --------------------------------------------------------------------------
    def test_workflow_sequence_mining(self):
        """Lifecycle trace events discover predecessor/successor invariants."""
        facts = [
            ObservationFact(input_id="inp_1", role="reference", workflow_events=["START", "VALIDATE", "EXECUTE", "STOP"]),
            ObservationFact(input_id="inp_2", role="reference", workflow_events=["START", "VALIDATE", "EXECUTE", "STOP"]),
        ]
        policy = DiscoveryPolicy(minimum_support_count=2)
        gen = WorkflowCandidateGenerator()
        candidates = gen.generate_candidates(facts, policy, role_scope="reference")

        prec_cands = [c for c in candidates if "workflow.event('START') precedes workflow.event('EXECUTE')" in c.canonical_expression]
        assert len(prec_cands) == 1

    # --------------------------------------------------------------------------
    # 9. Boundary Behavior Discovery
    # --------------------------------------------------------------------------
    def test_boundary_behavior_discovery(self):
        """Numeric input distribution shift near 10 generates OBSERVED_BOUNDARY."""
        facts = [
            ObservationFact(input_id="inp_1", role="reference", input_data={"age": 8}, has_error=True),
            ObservationFact(input_id="inp_2", role="reference", input_data={"age": 9}, has_error=True),
            ObservationFact(input_id="inp_3", role="reference", input_data={"age": 10}, has_error=False),
            ObservationFact(input_id="inp_4", role="reference", input_data={"age": 11}, has_error=False),
        ]
        policy = DiscoveryPolicy(minimum_support_count=2)
        gen = BoundaryCandidateGenerator()
        candidates = gen.generate_candidates(facts, policy, role_scope="reference")

        bound_cands = [c for c in candidates if "transition(input.age >= 10)" in c.canonical_expression]
        assert len(bound_cands) == 1
        cand = bound_cands[0]
        assert cand.rule_type == DiscoveredRuleType.BOUNDARY_BEHAVIOR

    # --------------------------------------------------------------------------
    # 10. Role Isolation & Shared Invariant Discovery
    # --------------------------------------------------------------------------
    def test_role_separation_reference_target_shared(self):
        """Reference and Target evidence generate distinct candidates, shared candidates are identified without reconciliation."""
        session_id = "sess_disc_roles"
        app_id = "app_disc_roles"

        rec_r1 = EvidenceRecord(
            evidence_id="r1", session_id=session_id, input_id="inp_1", role="reference",
            evidence_type=EvidenceType.OUTPUT, payload={"raw_output": {"y": 10}}
        )
        rec_r2 = EvidenceRecord(
            evidence_id="r2", session_id=session_id, input_id="inp_2", role="reference",
            evidence_type=EvidenceType.OUTPUT, payload={"raw_output": {"y": 10}}
        )
        rec_t1 = EvidenceRecord(
            evidence_id="t1", session_id=session_id, input_id="inp_1", role="target",
            evidence_type=EvidenceType.OUTPUT, payload={"raw_output": {"y": 10}}
        )
        rec_t2 = EvidenceRecord(
            evidence_id="t2", session_id=session_id, input_id="inp_2", role="target",
            evidence_type=EvidenceType.OUTPUT, payload={"raw_output": {"y": 10}}
        )

        bundle = EvidenceBundle(
            bundle_id="bnd_disc_roles",
            session_id=session_id,
            correlation_id="c_roles",
            application_id=app_id,
            input_set_id="is_roles",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_roles", application_id=app_id, input_set_id="is_roles", input_set_hash="h_roles", records=[rec_r1, rec_r2, rec_t1, rec_t2]),
            records=[rec_r1, rec_r2, rec_t1, rec_t2],
        )

        result = rule_discovery_engine.discover_rules(bundle=bundle, persist=False)
        assert result.observation_count == 4
        assert len(result.candidates) > 0

        # Check for role scopes
        ref_cands = [c for c in result.candidates if c.role_scope == "reference"]
        tgt_cands = [c for c in result.candidates if c.role_scope == "target"]
        shared_cands = [c for c in result.candidates if c.role_scope == "both"]

        assert len(ref_cands) >= 1
        assert len(tgt_cands) >= 1
        assert len(shared_cands) >= 1

    # --------------------------------------------------------------------------
    # 11. Determinism
    # --------------------------------------------------------------------------
    def test_determinism_identical_runs(self):
        """Repeated discovery on identical EvidenceBundle produces identical candidates, hashes, and ordering."""
        session_id = "sess_disc_det"
        app_id = "app_disc_det"

        records = []
        for i in range(5):
            records.append(
                EvidenceRecord(
                    evidence_id=f"r_{i}", session_id=session_id, input_id=f"inp_{i}", role="reference",
                    evidence_type=EvidenceType.OUTPUT, payload={"raw_output": {"score": i * 10, "status": "SUCCESS"}}
                )
            )

        bundle = EvidenceBundle(
            bundle_id="bnd_disc_det",
            session_id=session_id,
            correlation_id="c_det",
            application_id=app_id,
            input_set_id="is_det",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_det", application_id=app_id, input_set_id="is_det", input_set_hash="h_det", records=records),
            records=records,
        )

        res1 = rule_discovery_engine.discover_rules(bundle=bundle, persist=False)
        res2 = rule_discovery_engine.discover_rules(bundle=bundle, persist=False)

        assert res1.result_hash == res2.result_hash
        assert len(res1.candidates) == len(res2.candidates)
        for c1, c2 in zip(res1.candidates, res2.candidates):
            assert c1.fingerprint == c2.fingerprint
            assert c1.canonical_expression == c2.canonical_expression
            assert c1.support_count == c2.support_count
            assert c1.confidence == c2.confidence

    # --------------------------------------------------------------------------
    # 12. Real Phase 3 SQLite Integration
    # --------------------------------------------------------------------------
    def test_real_phase3_provider_sqlite_integration(self, tmp_path):
        """End-to-end integration using actual Phase 3 DatabaseEvidenceProvider."""
        db_file = tmp_path / "disc_test.db"
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL)")
            conn.execute("INSERT INTO products (id, name, price) VALUES (1, 'Widget', 19.99)")
            conn.commit()

        provider = DatabaseEvidenceProvider(config={"database_path": str(db_file), "tables": ["products"]})
        provider.capture_before()
        ev_after = provider.capture_after()

        session_id = "sess_p3_disc_real"
        app_id = "app_p3_disc_real"

        rec1 = EvidenceRecord(
            evidence_id="r_p3_1", session_id=session_id, input_id="inp_p3_1", role="reference",
            evidence_type=EvidenceType.DATABASE, payload=ev_after
        )
        rec2 = EvidenceRecord(
            evidence_id="r_p3_2", session_id=session_id, input_id="inp_p3_2", role="reference",
            evidence_type=EvidenceType.DATABASE, payload=ev_after
        )

        bundle = EvidenceBundle(
            bundle_id="bnd_p3_disc_real",
            session_id=session_id,
            correlation_id="c_p3_disc",
            application_id=app_id,
            input_set_id="is_p3_disc",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_p3_disc", application_id=app_id, input_set_id="is_p3_disc", input_set_hash="h_p3", records=[rec1, rec2]),
            records=[rec1, rec2],
        )

        result = rule_discovery_engine.discover_rules(bundle=bundle, persist=False)
        assert result.observation_count >= 2

        # State Invariant should be discovered from genuine Phase 3 DB capture!
        state_inv = [c for c in result.candidates if c.rule_type == DiscoveredRuleType.STATE_INVARIANT]
        assert len(state_inv) >= 1
        assert state_inv[0].canonical_expression == "state.mutated == false"

    # --------------------------------------------------------------------------
    # 13. Persistence & Audit Storage
    # --------------------------------------------------------------------------
    def test_sqlite_persistence_and_retrieval(self):
        """DiscoveryResult is saved into SQLite and cleanly retrieved."""
        session_id = "sess_p6_persist"
        app_id = "app_p6_persist"

        records = [
            EvidenceRecord(
                evidence_id="r_per_1", session_id=session_id, input_id="inp_per_1", role="reference",
                evidence_type=EvidenceType.OUTPUT, payload={"raw_output": {"val": 42}}
            ),
            EvidenceRecord(
                evidence_id="r_per_2", session_id=session_id, input_id="inp_per_2", role="reference",
                evidence_type=EvidenceType.OUTPUT, payload={"raw_output": {"val": 42}}
            ),
        ]
        bundle = EvidenceBundle(
            bundle_id="bnd_p6_persist",
            session_id=session_id,
            correlation_id="c_per",
            application_id=app_id,
            input_set_id="is_per",
            manifest=EvidenceManifest(session_id=session_id, correlation_id="c_per", application_id=app_id, input_set_id="is_per", input_set_hash="h_per", records=records),
            records=records,
        )

        result = rule_discovery_engine.discover_rules(bundle=bundle, persist=True)
        retrieved = discovery_persistence.get_discovery_result(result.discovery_id)

        assert retrieved is not None
        assert retrieved.discovery_id == result.discovery_id
        assert retrieved.result_hash == result.result_hash
        assert len(retrieved.candidates) == len(result.candidates)

        listed = discovery_persistence.list_discoveries(application_id=app_id)
        assert any(d["discovery_id"] == result.discovery_id for d in listed)

    # --------------------------------------------------------------------------
    # 14. REST API Endpoint Tests
    # --------------------------------------------------------------------------
    def test_rest_api_discovery_endpoints(self):
        """REST API POST /api/v2/discovery and GET /api/v2/discovery/{id}."""
        admin_user = auth_repository.get_user_by_username("admin")
        token = create_access_token(user=admin_user)
        headers = {"Authorization": f"Bearer {token}"}

        client = TestClient(app)
        session_id = "sess_p6_api"
        app_id = "app_p6_api"

        payload = {
            "bundle": {
                "bundle_id": "bnd_api_test",
                "session_id": session_id,
                "correlation_id": "c_api",
                "application_id": app_id,
                "input_set_id": "is_api",
                "manifest": {
                    "session_id": session_id,
                    "correlation_id": "c_api",
                    "application_id": app_id,
                    "input_set_id": "is_api",
                    "input_set_hash": "h_api",
                    "items": [],
                },
                "records": [
                    {
                        "evidence_id": "rec_api_1",
                        "session_id": session_id,
                        "input_id": "inp_api_1",
                        "role": "reference",
                        "evidence_type": "OUTPUT",
                        "payload": {"raw_output": {"status": "SUCCESS", "code": 200}},
                    },
                    {
                        "evidence_id": "rec_api_2",
                        "session_id": session_id,
                        "input_id": "inp_api_2",
                        "role": "reference",
                        "evidence_type": "OUTPUT",
                        "payload": {"raw_output": {"status": "SUCCESS", "code": 200}},
                    },
                ],
            },
            "persist": True,
        }

        # POST /api/v2/discovery
        res_post = client.post("/api/v2/discovery", json=payload, headers=headers)
        assert res_post.status_code == 200
        data = res_post.json()
        assert "discovery_id" in data
        assert "candidates" in data
        disc_id = data["discovery_id"]

        # GET /api/v2/discovery/{discovery_id}
        res_get = client.get(f"/api/v2/discovery/{disc_id}", headers=headers)
        assert res_get.status_code == 200
        get_data = res_get.json()
        assert get_data["discovery_id"] == disc_id

        # GET /api/v2/discovery (List)
        res_list = client.get("/api/v2/discovery", headers=headers)
        assert res_list.status_code == 200
        assert any(d["discovery_id"] == disc_id for d in res_list.json())
