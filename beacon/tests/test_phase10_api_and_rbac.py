"""BEACON V2 — Phase 10 REST API & RBAC Authorization Tests.

Verifies explanation generation, retrieval, interactive Q&A, and multi-tenant RBAC enforcement.
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from auth import (
    User,
    UserRole,
    auth_repository,
    create_access_token,
)
from certification.models import (
    BehavioralRegression,
    CertificationArtifact,
    CertificationMetrics,
    CertificationPolicy,
    CertificationStatus,
    compute_artifact_content_hash,
)
from certification.repository import certification_repository


class TestPhase10ApiAndRbac:
    """Test suite for Phase 10 REST API endpoints and RBAC authorization."""

    @pytest.fixture(autouse=True)
    def setup_test_data(self):
        """Set up test users, projects, and certification artifact."""
        self.client = TestClient(app)

        # 1. Create Admin & Tenant Users
        self.admin_user = auth_repository.get_user_by_username("admin_phase10")
        if not self.admin_user:
            self.admin_user = auth_repository.create_user(
                user_id="USR-ADMIN-10",
                username="admin_phase10",
                password="AdminPhase10Pass2026!",
                full_name="Admin Phase10",
                email="admin10@beacon.local",
                is_system_admin=True,
            )

        self.alice_user = auth_repository.get_user_by_username("alice_phase10")
        if not self.alice_user:
            self.alice_user = auth_repository.create_user(
                user_id="USR-ALICE-10",
                username="alice_phase10",
                password="AlicePhase10Pass2026!",
                full_name="Alice Phase10",
                email="alice10@beacon.local",
                is_system_admin=False,
            )

        self.eve_user = auth_repository.get_user_by_username("eve_phase10")
        if not self.eve_user:
            self.eve_user = auth_repository.create_user(
                user_id="USR-EVE-10",
                username="eve_phase10",
                password="EvePhase10Pass2026!",
                full_name="Eve Phase10",
                email="eve10@beacon.local",
                is_system_admin=False,
            )

        # Alice has access to 'proj_alice'
        auth_repository.assign_user_to_project(
            user_id=self.alice_user.user_id,
            project_id="proj_alice",
            role=UserRole.CERTIFIER,
        )


        # 2. Create Certification Artifact for proj_alice
        self.cert_id = "CERT-PHASE10-ALICE-01"
        artifact_raw = CertificationArtifact(
            certification_id=self.cert_id,
            project_id="proj_alice",
            benchmark_id="retail_discount_pricing",
            status=CertificationStatus.NOT_CERTIFIED,
            certified=False,
            score=0.75,
            metrics=CertificationMetrics(
                unique_input_count=10,
                matching_case_count=7,
                regression_case_count=3,
                total_inputs=10,
            ),
            regressions=[
                BehavioralRegression(
                    regression_id="REG-101",
                    oracle_id="ORC-101",
                    input_id="INP-101",
                    input_values={"order_amount": 100},
                    expected_behavior=90,
                    legacy_output=90,
                    modern_output=95,
                    failed_assertion="output == 90",
                    evidence_ids=["EVID-101"],
                )
            ],
            content_hash="",
        )
        artifact = artifact_raw.model_copy(update={"content_hash": compute_artifact_content_hash(artifact_raw)})
        certification_repository.save_artifact(artifact)


        self.admin_token = create_access_token(self.admin_user)
        self.alice_token = create_access_token(self.alice_user)
        self.eve_token = create_access_token(self.eve_user)

    def test_authorized_user_can_generate_and_retrieve_explanation(self):
        """Verify authorized user Alice can generate and retrieve explanation for proj_alice."""
        headers = {"Authorization": f"Bearer {self.alice_token}"}

        # 1. POST generate explanation
        res = self.client.post(
            f"/api/v2/certifications/{self.cert_id}/explanation",
            json={"mode": "deterministic", "use_company_knowledge": False},
            headers=headers,
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["certification_id"] == self.cert_id
        assert data["overall_verdict"] == "NOT_CERTIFIED"
        assert len(data["dimension_explanations"]) >= 1
        assert len(data["rule_impacts"]) >= 0

        # 2. GET retrieve persisted explanation
        res_get = self.client.get(
            f"/api/v2/certifications/{self.cert_id}/explanation",
            headers=headers,
        )
        assert res_get.status_code == 200
        get_data = res_get.json()
        assert get_data["explanation_id"] == data["explanation_id"]

    def test_unauthorized_user_is_denied_with_403(self):
        """Verify unauthorized user Eve is denied with HTTP 403 when requesting Alice's certification."""
        headers = {"Authorization": f"Bearer {self.eve_token}"}

        res = self.client.post(
            f"/api/v2/certifications/{self.cert_id}/explanation",
            json={"mode": "deterministic"},
            headers=headers,
        )
        assert res.status_code == 403, "Unauthorized user without project membership must receive HTTP 403."

        res_ask = self.client.post(
            f"/api/v2/certifications/{self.cert_id}/ask",
            json={"question": "Why did this run fail?"},
            headers=headers,
        )
        assert res_ask.status_code == 403, "Unauthorized user must not be able to query another project's certification."

    def test_interactive_qa_endpoint(self):
        """Verify asking a targeted question returns structured, evidence-backed answers."""
        headers = {"Authorization": f"Bearer {self.alice_token}"}

        res = self.client.post(
            f"/api/v2/certifications/{self.cert_id}/ask",
            json={
                "question": "Which inputs caused the behavioral regressions?",
                "use_company_knowledge": False,
                "preferred_provider": "offline",
            },
            headers=headers,
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["question"] == "Which inputs caused the behavioral regressions?"
        assert data["authoritative_verdict"] == "NOT_CERTIFIED"
        assert len(data["answer"]) > 10
        assert data["support_level"] in ("DETERMINISTIC_EVIDENCE", "INFERRED", "UNCERTAIN", "UNKNOWN")
