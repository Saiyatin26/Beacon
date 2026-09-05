"""BEACON V2 — Phase 1 Architectural & Domain-Agnostic Validation Suite.

Validates:
1. Generic ApplicationSpec creation with domain absent / optional metadata only.
2. Complete domain-agnosticism: hypothetical Agriculture application certified
   without any domain-specific business logic in BEACON's core engine.
3. Reference and Target generic adapter roles, identity, and full lifecycle execution.
4. Safe, configurable output normalizers preserving exact raw outputs and casing.
5. CanonicalInput model with structured, nested payloads and stable cryptographic hashing.
6. Enhanced CanonicalObservation with raw outputs, side-effects, and exception tracking.
7. OracleSet source mode compatibility (CONTROLLED, USER_PROVIDED, FULL_BEACON_DISCOVERED).
8. ThresholdPolicy abstractions (StaticThresholdPolicy and DynamicThresholdPolicy).
9. Knowledge & RAG extension boundary interfaces.
10. Deterministic authority & Intelligence explanation boundary.
11. Full backward compatibility with existing V1 benchmarks (loan_demo, retail, payroll, medical).
"""

import hashlib
import json
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

from application import (
    ApplicationRegistry,
    ApplicationResolutionError,
    ApplicationResolver,
    ApplicationRole,
    ApplicationSpec,
    DatasetConfig,
    EvidenceConfig,
    ExecutionConfig,
    ImplementationTarget,
    InputContract,
    OutputContract,
    RuleConfig,
    RuntimeConfig,
    application_registry,
    application_repository,
)
from certification.adapters import (
    AdapterRole,
    ConfiguredOutputNormalizer,
    DefaultOutputNormalizer,
    FunctionAdapter,
    ImplementationAdapter,
    LegacyAdapter,
    ModernizedAdapter,
    PreserveCaseNormalizer,
    ReferenceAdapter,
    StripWhitespaceNormalizer,
    TargetAdapter,
    compute_implementation_hash,
)
from certification.adapter_registry import AdapterRegistration, AdapterRegistry, adapter_registry
from certification.models import (
    CanonicalInput,
    CertificationArtifact,
    CertificationContext,
    CertificationPolicy,
    CertificationStatus,
    CertificationTestInput,
    Observation,
    compute_canonical_input_hash,
)
from certification.policies import DynamicThresholdPolicy, StaticThresholdPolicy, ThresholdPolicy
from certification.certification_engine import CertificationEngine, certification_engine
from evidence.contracts import EvidenceCategory, GenericEvidenceItem
from knowledge.contracts import (
    KnowledgeChunk,
    KnowledgeContext,
    KnowledgeDocument,
    KnowledgeSource,
    StubKnowledgeRetriever,
)
from llm.explanation import CertificationExplainer
from oracle.models import (
    OracleConsequence,
    OracleDefinition,
    OracleInputSchema,
    OracleOutputSchema,
    OraclePredicate,
    OracleProvenance,
    OracleRule,
    OracleSet,
    OracleSourceMode,
    RuleSeverity,
)
from oracle.registry import registry as oracle_registry
from benchmarks import benchmark_registry


# ==============================================================================
# 1. Application Spec & Domain Independence Tests
# ==============================================================================

def test_application_spec_creation_with_no_domain():
    """ApplicationSpec can be instantiated with domain=None."""
    spec = ApplicationSpec(
        application_id="app_generic_calc",
        name="Generic Calculator Service",
        reference_implementation="calc_ref",
        target_implementations=["calc_target"],
    )

    assert spec.application_id == "app_generic_calc"
    assert spec.domain is None
    assert spec.version == "1.0.0"
    assert spec.compute_spec_hash() is not None
    assert len(spec.compute_spec_hash()) == 64


def test_application_spec_domain_is_metadata_only():
    """Domain field is purely descriptive metadata and does not affect hashing or spec validity."""
    spec_agri = ApplicationSpec(
        application_id="app_crop_opt",
        name="Crop Yield Optimizer",
        domain="agriculture",
        reference_implementation="agri_ref",
    )
    spec_health = ApplicationSpec(
        application_id="app_health_triage",
        name="Clinical Assessment",
        domain="healthcare",
        reference_implementation="health_ref",
    )

    assert spec_agri.domain == "agriculture"
    assert spec_health.domain == "healthcare"
    # Both resolve identically in the domain-neutral application registry
    reg = ApplicationRegistry(repository=application_repository)
    reg.register_application(spec_agri)
    reg.register_application(spec_health)

    retrieved = reg.get_application("app_crop_opt")
    assert retrieved is not None
    assert retrieved.name == "Crop Yield Optimizer"
    assert retrieved.domain == "agriculture"

    # Filter by domain metadata
    agri_apps = reg.list_applications(domain="agriculture")
    assert any(a.application_id == "app_crop_opt" for a in agri_apps)


# ==============================================================================
# 2. End-to-End Architectural Test: Hypothetical Agriculture Application
# ==============================================================================

def reference_crop_irrigation(soil_moisture: float, temperature_c: float) -> dict:
    """Hypothetical reference Agriculture system."""
    if soil_moisture < 25.0 and temperature_c > 30.0:
        return {"irrigation_valve": "OPEN_FULL", "flow_rate": 100.0}
    elif soil_moisture < 40.0:
        return {"irrigation_valve": "OPEN_HALF", "flow_rate": 50.0}
    return {"irrigation_valve": "CLOSED", "flow_rate": 0.0}


def candidate_crop_irrigation_clean(soil_moisture: float, temperature_c: float) -> dict:
    """Modernized equivalent Agriculture system."""
    if soil_moisture < 25.0 and temperature_c > 30.0:
        return {"irrigation_valve": "OPEN_FULL", "flow_rate": 100.0}
    elif soil_moisture < 40.0:
        return {"irrigation_valve": "OPEN_HALF", "flow_rate": 50.0}
    return {"irrigation_valve": "CLOSED", "flow_rate": 0.0}


def candidate_crop_irrigation_buggy(soil_moisture: float, temperature_c: float) -> dict:
    """Buggy candidate with subtle threshold error."""
    if soil_moisture < 20.0 and temperature_c > 30.0:  # BUG: 20.0 instead of 25.0
        return {"irrigation_valve": "OPEN_FULL", "flow_rate": 100.0}
    elif soil_moisture < 40.0:
        return {"irrigation_valve": "OPEN_HALF", "flow_rate": 50.0}
    return {"irrigation_valve": "CLOSED", "flow_rate": 0.0}


def test_hypothetical_agriculture_application_certification_clean():
    """Proves an unknown domain application (Agriculture) certifies 100% cleanly
    through generic ApplicationSpec, Adapter roles, and CanonicalInputs without
    adding agriculture-specific logic to the engine.
    """
    resolver = ApplicationResolver()

    # Define ApplicationSpec for Agriculture system
    spec = ApplicationSpec(
        application_id="smart_farm_irrigation",
        name="Precision Irrigation & Soil Hydration Controller",
        domain="agriculture",
        reference_implementation=ImplementationTarget(
            target_id="farm_ref_v1",
            name="legacy_irrigation_firmware",
            role=ApplicationRole.REFERENCE,
            entrypoint=reference_crop_irrigation,
        ),
        target_implementations=[
            ImplementationTarget(
                target_id="farm_modern_v2",
                name="modern_cloud_irrigation",
                role=ApplicationRole.TARGET,
                entrypoint=candidate_crop_irrigation_clean,
            )
        ],
        input_contract=InputContract(
            fields={"soil_moisture": (10.0, 60.0), "temperature_c": (15.0, 45.0)}
        ),
        output_contract=OutputContract(normalizer="preserve_case"),
        dataset_config=DatasetConfig(sample_count=40, seed=123),
        rule_config=RuleConfig(
            mode="CONTROLLED",
            rules=[
                {
                    "rule_id": "agri_rule_01",
                    "name": "Extreme drought emergency irrigation",
                    "condition": "soil_moisture < 25.0 and temperature_c > 30.0",
                    "consequence": "irrigation_valve == 'OPEN_FULL'",
                    "severity": "CRITICAL",
                },
                {
                    "rule_id": "agri_rule_02",
                    "name": "Standard dry soil irrigation",
                    "condition": "soil_moisture >= 25.0 and soil_moisture < 40.0",
                    "consequence": "irrigation_valve == 'OPEN_HALF'",
                    "severity": "HIGH",
                },
                {
                    "rule_id": "agri_rule_03",
                    "name": "Adequate soil moisture",
                    "condition": "soil_moisture >= 40.0",
                    "consequence": "irrigation_valve == 'CLOSED'",
                    "severity": "MEDIUM",
                },
            ],
        ),
    )

    # Resolve components generically
    ref_adapter, target_adapter = resolver.resolve_adapters(spec)
    inputs = resolver.resolve_inputs(spec)
    oracle_set = resolver.resolve_oracle_set(spec)

    assert len(inputs) == 40
    assert isinstance(ref_adapter, ImplementationAdapter)
    assert isinstance(target_adapter, ImplementationAdapter)

    # Execute deterministic certification
    engine = CertificationEngine()
    policy = CertificationPolicy(min_equivalence_score=0.999, allow_warnings=False)
    context = CertificationContext(
        benchmark_id=spec.application_id,
        benchmark_name=spec.name,
        evaluation_mode="CONTROLLED",
    )

    artifact = engine.certify(
        project_id=spec.application_id,
        legacy_adapter=ref_adapter,
        modern_adapter=target_adapter,
        test_inputs=inputs,
        oracle_set=oracle_set,
        context=context,
        policy=policy,
    )

    assert artifact.certification_status == CertificationStatus.CERTIFIED
    assert artifact.equivalence_score == 1.0
    assert len(artifact.regressions) == 0


def test_hypothetical_agriculture_application_certification_buggy():
    """Detects behavioral regression in buggy Agriculture candidate implementation."""
    resolver = ApplicationResolver()

    spec = ApplicationSpec(
        application_id="smart_farm_irrigation_buggy",
        name="Precision Irrigation Controller",
        domain="agriculture",
        reference_implementation=reference_crop_irrigation,
        target_implementations=[candidate_crop_irrigation_buggy],
        input_contract=InputContract(
            fields={"soil_moisture": (10.0, 60.0), "temperature_c": (15.0, 45.0)}
        ),
        output_contract=OutputContract(normalizer="preserve_case"),
        dataset_config=DatasetConfig(sample_count=50, seed=99),
        rule_config=RuleConfig(
            mode="CONTROLLED",
            rules=[
                {
                    "rule_id": "agri_rule_01",
                    "name": "Extreme drought emergency irrigation",
                    "condition": "soil_moisture < 25.0 and temperature_c > 30.0",
                    "consequence": "irrigation_valve == 'OPEN_FULL'",
                    "severity": "CRITICAL",
                },
            ],
        ),
    )

    ref_adapter, target_adapter = resolver.resolve_adapters(spec)
    # Include an explicit probe in the boundary region (soil_moisture=22.0, temp=35.0)
    boundary_input = CertificationTestInput(
        input_id="agri_probe_boundary",
        values={"soil_moisture": 22.0, "temperature_c": 35.0},
        origin="boundary_probe",
    )
    inputs = [boundary_input] + resolver.resolve_inputs(spec)
    oracle_set = resolver.resolve_oracle_set(spec)

    engine = CertificationEngine()
    policy = CertificationPolicy(min_equivalence_score=0.999)
    context = CertificationContext(benchmark_id=spec.application_id)

    artifact = engine.certify(
        project_id=spec.application_id,
        legacy_adapter=ref_adapter,
        modern_adapter=target_adapter,
        test_inputs=inputs,
        oracle_set=oracle_set,
        context=context,
        policy=policy,
    )

    assert artifact.certification_status == CertificationStatus.NOT_CERTIFIED
    assert len(artifact.regressions) > 0

    # Test that LLM explainer produces structured triage without modifying decision
    explainer = CertificationExplainer()
    explanation = explainer.generate_explanation(artifact)
    assert explanation["deterministic_authority"] is True
    assert explanation["status"] == "CertificationStatus.NOT_CERTIFIED" or "NOT_CERTIFIED" in explanation["status"]
    assert len(explanation["remediation_suggestions"]) > 0


# ==============================================================================
# 3. Adapter Contract, Roles & Full Lifecycle Tests
# ==============================================================================

def test_adapter_roles_and_lifecycle():
    """Verifies prepare, validate, execute, normalize_output, capture_evidence, and cleanup hooks."""
    class MockTargetService:
        def __init__(self):
            self.prepared = False
            self.cleaned = False

        def process(self, value: int) -> dict:
            return {"status": "ok", "value": value * 2}

    service = MockTargetService()

    class LifecycleAdapter(ImplementationAdapter):
        def __init__(self, svc):
            self.svc = svc
            self.name = "lifecycle_test_adapter"
            self.version = "1.0.0"
            self.role = AdapterRole.TARGET
            self.implementation_hash = hashlib.sha256(b"lifecycle_test").hexdigest()

        def prepare(self, context=None):
            self.svc.prepared = True

        def validate(self) -> bool:
            return self.svc is not None

        def execute(self, inputs, input_id=""):
            raw_data = inputs.get_data() if isinstance(inputs, CanonicalInput) else inputs
            out = self.svc.process(**raw_data)
            return Observation(
                input_id=input_id,
                raw_inputs=raw_data,
                raw_outputs=out,
                normalized_outputs=out,
                execution_status="SUCCESS",
                implementation_name=self.name,
                implementation_version=self.version,
            )

        def cleanup(self):
            self.svc.cleaned = True

    adapter = LifecycleAdapter(service)
    assert adapter.role == AdapterRole.TARGET
    assert adapter.validate() is True

    adapter.prepare({"env": "test"})
    assert service.prepared is True

    obs = adapter.execute(CanonicalInput(input_id="in_1", payload={"value": 5}))
    assert obs.execution_status == "SUCCESS"
    assert obs.raw_outputs == {"status": "ok", "value": 10}

    adapter.cleanup()
    assert service.cleaned is True


# ==============================================================================
# 4. Safe Semantics-Preserving Output Normalization Tests
# ==============================================================================

def test_preserve_case_normalizer_preserves_casing_and_raw_output():
    """PreserveCaseNormalizer preserves lowercase, camelCase, and preserves exact raw outputs."""
    normalizer = PreserveCaseNormalizer()

    # Dictionary output
    raw_dict = {"status": "pendingApproval", "token": "secretToken123", "code": 404}
    norm_dict = normalizer.normalize(raw_dict)
    assert norm_dict["status"] == "pendingApproval"  # Not forced uppercase!
    assert norm_dict["token"] == "secretToken123"

    # Scalar output
    raw_scalar = "in_progress"
    norm_scalar = normalizer.normalize(raw_scalar)
    assert norm_scalar == {"decision": "in_progress"}


def test_strip_whitespace_normalizer():
    """StripWhitespaceNormalizer trims whitespace while preserving letter case."""
    normalizer = StripWhitespaceNormalizer()
    raw = {"name": "  Alice Johnson  ", "category": "\tpremium_tier\n"}
    norm = normalizer.normalize(raw)
    assert norm["name"] == "Alice Johnson"
    assert norm["category"] == "premium_tier"


def test_configured_output_normalizer():
    """ConfiguredOutputNormalizer applies field-specific transformations."""
    normalizer = ConfiguredOutputNormalizer(
        uppercase_fields=["country_code"],
        strip_fields=["username"],
        numeric_fields=["amount_str"],
    )
    raw = {"country_code": "us", "username": "  bob  ", "amount_str": "125.50"}
    norm = normalizer.normalize(raw)
    assert norm["country_code"] == "US"
    assert norm["username"] == "bob"
    assert norm["amount_str"] == 125.50


def test_function_adapter_always_preserves_raw_outputs():
    """FunctionAdapter preserves exact raw outputs even when normalizer transforms them."""
    def sample_fn(x: str) -> str:
        return f"result_for_{x}"

    adapter = FunctionAdapter(
        target_fn=sample_fn,
        output_normalizer=DefaultOutputNormalizer(),  # uppercase normalizer
    )

    obs = adapter.execute({"x": "item_1"}, input_id="inp_01")
    assert obs.raw_outputs == {"decision": "result_for_item_1"}  # Exact raw output preserved!
    assert obs.normalized_outputs == {"decision": "RESULT_FOR_ITEM_1"}  # Normalized uppercase


# ==============================================================================
# 5. Canonical Input & Observation Models Tests
# ==============================================================================

def test_canonical_input_with_nested_payload_and_stable_hash():
    """CanonicalInput handles nested structures and computes deterministic SHA-256 hash."""
    payload1 = {"user": {"id": 101, "role": "admin"}, "tags": ["prod", "us-east"]}
    payload2 = {"tags": ["prod", "us-east"], "user": {"role": "admin", "id": 101}}

    c_in1 = CanonicalInput(input_id="in_101", payload=payload1)
    c_in2 = CanonicalInput(input_id="in_102", payload=payload2)

    assert c_in1.input_hash != ""
    assert len(c_in1.input_hash) == 64
    # Key order independent hashing
    assert c_in1.input_hash == c_in2.input_hash


def test_observation_state_changes_and_side_effects():
    """Observation supports side-effects, state-changes, and trace references."""
    obs = Observation(
        input_id="in_obs_1",
        raw_inputs={"id": 1},
        normalized_inputs={"id": 1},
        raw_outputs={"status": "updated"},
        normalized_outputs={"status": "updated"},
        state_changes={"table_rows_added": 1},
        side_effects=[{"action": "audit_log", "target": "events_queue"}],
        trace_reference="trace_ref_99812",
        implementation_name="service_v2",
    )

    assert obs.state_changes == {"table_rows_added": 1}
    assert len(obs.side_effects) == 1
    assert obs.trace_reference == "trace_ref_99812"


# ==============================================================================
# 6. OracleSet Source Modes & Threshold Policies Tests
# ==============================================================================

def test_oracle_set_source_modes():
    """OracleSet supports CONTROLLED, USER_PROVIDED, FULL_BEACON_DISCOVERED, RECONCILED."""
    for mode in [
        OracleSourceMode.CONTROLLED,
        OracleSourceMode.USER_PROVIDED,
        OracleSourceMode.FULL_BEACON_DISCOVERED,
        OracleSourceMode.RECONCILED,
    ]:
        oset = OracleSet(
            oracle_set_id=f"oset_mode_{mode.value}",
            name=f"Oracle Set {mode.value}",
            source_mode=mode,
        )
        assert oset.source_mode == mode


def test_static_and_dynamic_threshold_policies():
    """StaticThresholdPolicy and DynamicThresholdPolicy evaluate outcomes deterministically."""
    static_policy = StaticThresholdPolicy(min_equivalence_score=0.999, allow_warnings=False)
    assert static_policy.evaluate_status(
        equivalence_score=1.0, regression_count=0, oracle_coverage=0.90
    ) == CertificationStatus.CERTIFIED
    assert static_policy.evaluate_status(
        equivalence_score=0.98, regression_count=1, oracle_coverage=0.90
    ) == CertificationStatus.NOT_CERTIFIED

    dynamic_policy = DynamicThresholdPolicy(
        base_equivalence_score=0.95, confidence_margin=0.03, allow_warnings=True
    )
    # Score in warning band (0.93 >= 0.92)
    assert dynamic_policy.evaluate_status(
        equivalence_score=0.93, regression_count=0, oracle_coverage=0.85
    ) == CertificationStatus.CERTIFIED_WITH_WARNINGS


# ==============================================================================
# 7. Knowledge & RAG Extension Boundary Tests
# ==============================================================================

def test_knowledge_contracts_and_stub_retriever():
    """Verifies Knowledge contracts without external vector DB or embeddings."""
    source = KnowledgeSource(source_id="src_spec", name="System Specification")
    doc = KnowledgeDocument(
        doc_id="doc_1",
        source_id=source.source_id,
        title="Architecture Requirements",
        content="System must guarantee 100% deterministic decision logic.",
    )
    chunk = KnowledgeChunk(
        chunk_id="chunk_1_1",
        doc_id=doc.doc_id,
        text="System must guarantee 100% deterministic decision logic.",
    )

    assert doc.doc_hash != ""
    assert len(doc.doc_hash) == 64

    retriever = StubKnowledgeRetriever()
    ctx = retriever.retrieve("deterministic requirements")
    assert isinstance(ctx, KnowledgeContext)
    assert ctx.confidence == 1.0


# ==============================================================================
# 8. Backward Compatibility: All V1 Benchmarks Still Function
# ==============================================================================

def test_v1_benchmarks_compatibility():
    """Verifies that existing V1 benchmarks (retail, payroll, medical, loan) resolve cleanly."""
    benchmarks = benchmark_registry.list_benchmarks()
    assert len(benchmarks) >= 4

    bench_ids = [b.benchmark_id for b in benchmarks]
    assert "retail_discount_pricing" in bench_ids
    assert "payroll_tax_calculator" in bench_ids
    assert "medical_triage" in bench_ids
    assert "loan_demo" in bench_ids

    # Verify adapter resolution for legacy benchmarks
    for b_id in ["retail_discount_pricing", "payroll_tax_calculator", "medical_triage", "loan_demo"]:
        legacy_ad = benchmark_registry.get_legacy_adapter(b_id)
        assert legacy_ad is not None
        assert isinstance(legacy_ad, ImplementationAdapter)


# ==============================================================================
# 9. Application API Router Integration Tests
# ==============================================================================

def test_application_api_endpoints():
    """Verifies /api/v2/applications REST endpoints with authentication."""
    from fastapi.testclient import TestClient
    from api.main import app
    from auth.security import create_access_token
    from auth.repository import auth_repository

    client = TestClient(app)
    admin_user = auth_repository.get_user_by_username("admin")
    assert admin_user is not None
    token = create_access_token(user=admin_user)
    headers = {"Authorization": f"Bearer {token}"}

    # Register application
    spec_payload = {
        "application_id": "app_rest_demo",
        "name": "REST Demo Application",
        "domain": "telecommunications",
        "reference_implementation": {
            "name": "loan_approval_legacy",
            "entrypoint": "loan_approval_legacy",
            "role": "reference",
        },
        "target_implementations": [
            {
                "name": "loan_approval_modern_equiv",
                "entrypoint": "loan_approval_modern_equiv",
                "role": "target",
            }
        ],
        "input_contract": {
            "fields": {"credit_score": (400, 800), "debt_ratio": (0.1, 0.8), "annual_income": (20000, 100000)}
        },
        "dataset_config": {"sample_count": 20, "seed": 42},
        "rule_config": {
            "mode": "CONTROLLED",
            "rules": [
                {
                    "rule_id": "loan_rule_1",
                    "condition": "credit_score >= 700",
                    "consequence": "decision == 'APPROVE'",
                    "severity": "CRITICAL",
                },
                {
                    "rule_id": "loan_rule_2",
                    "condition": "credit_score < 600",
                    "consequence": "decision == 'REJECT'",
                    "severity": "CRITICAL",
                },
            ],
        },
    }

    # 1. Register
    resp = client.post("/api/v2/applications", json=spec_payload, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["application_id"] == "app_rest_demo"

    # 2. Get
    resp = client.get("/api/v2/applications/app_rest_demo", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "REST Demo Application"

    # 3. List
    resp = client.get("/api/v2/applications?domain=telecommunications", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # 4. Certify
    resp = client.post("/api/v2/applications/app_rest_demo/certify", json={"explain": True}, headers=headers)
    assert resp.status_code == 200
    cert_data = resp.json()
    assert cert_data["status"] == "CERTIFIED"
    assert "explanation" in cert_data

    # 5. Delete
    resp = client.delete("/api/v2/applications/app_rest_demo", headers=headers)
    assert resp.status_code == 204


# ==============================================================================
# 10. Generic Resolver Domain Independence & No Inventions Tests
# ==============================================================================

def reference_quantum_fisheries(biomass_density: float, sonar_frequency_khz: float, water_salinity_ppt: float) -> dict:
    """Hypothetical reference implementation for fictional Quantum Fisheries domain."""
    if biomass_density > 75.0 and sonar_frequency_khz < 45.0:
        return {"harvest_clearance": "AUTHORIZED", "sonar_gain_db": 12.5, "zone_code": "QF_ALPHA"}
    elif water_salinity_ppt < 20.0:
        return {"harvest_clearance": "RESTRICTED", "sonar_gain_db": 6.0, "zone_code": "QF_ESTUARY"}
    return {"harvest_clearance": "STANDBY", "sonar_gain_db": 0.0, "zone_code": "QF_OPEN"}


def candidate_quantum_fisheries_clean(biomass_density: float, sonar_frequency_khz: float, water_salinity_ppt: float) -> dict:
    """Modernized equivalent implementation for fictional Quantum Fisheries domain."""
    if biomass_density > 75.0 and sonar_frequency_khz < 45.0:
        return {"harvest_clearance": "AUTHORIZED", "sonar_gain_db": 12.5, "zone_code": "QF_ALPHA"}
    elif water_salinity_ppt < 20.0:
        return {"harvest_clearance": "RESTRICTED", "sonar_gain_db": 6.0, "zone_code": "QF_ESTUARY"}
    return {"harvest_clearance": "STANDBY", "sonar_gain_db": 0.0, "zone_code": "QF_OPEN"}


def test_generic_resolver_contains_no_domain_specific_defaults():
    """Proves that an arbitrary fictional domain (Quantum Fisheries) works seamlessly with
    explicit contracts and that removing explicit rules does NOT invent any domain-specific rules.
    """
    resolver = ApplicationResolver()

    # 1. Spec with explicit rules for novel domain
    spec = ApplicationSpec(
        application_id="app_quantum_fisheries_001",
        name="Quantum Marine Harvest Control",
        domain="quantum_fisheries",
        reference_implementation=ImplementationTarget(
            target_id="qf_ref_v1",
            name="qf_firmware_legacy",
            role=ApplicationRole.REFERENCE,
            entrypoint=reference_quantum_fisheries,
        ),
        target_implementations=[
            ImplementationTarget(
                target_id="qf_target_v2",
                name="qf_service_modern",
                role=ApplicationRole.TARGET,
                entrypoint=candidate_quantum_fisheries_clean,
            )
        ],
        input_contract=InputContract(
            fields={
                "biomass_density": (10.0, 100.0),
                "sonar_frequency_khz": (20.0, 80.0),
                "water_salinity_ppt": (5.0, 40.0),
            }
        ),
        output_contract=OutputContract(normalizer="preserve_case"),
        dataset_config=DatasetConfig(sample_count=25, seed=777),
        rule_config=RuleConfig(
            mode="USER_PROVIDED",
            rules=[
                {
                    "rule_id": "qf_rule_01",
                    "condition": "biomass_density > 75.0 and sonar_frequency_khz < 45.0",
                    "consequence": "harvest_clearance == 'AUTHORIZED'",
                    "severity": "CRITICAL",
                },
                {
                    "rule_id": "qf_rule_02",
                    "condition": "water_salinity_ppt < 20.0",
                    "consequence": "harvest_clearance == 'RESTRICTED'",
                    "severity": "HIGH",
                },
            ],
        ),
    )

    ref_adapter, target_adapter = resolver.resolve_adapters(spec)
    inputs = resolver.resolve_inputs(spec)
    oracle_set = resolver.resolve_oracle_set(spec)

    assert len(inputs) == 25
    assert len(oracle_set.oracles) == 2
    assert oracle_set.metadata["rule_discovery_status"] == "explicit_rules_loaded"

    # Verify certification succeeds deterministically
    engine = CertificationEngine()
    policy = CertificationPolicy(min_equivalence_score=0.999)
    artifact = engine.certify(
        reference_adapter=ref_adapter,
        modernized_adapter=target_adapter,
        oracle_set=oracle_set,
        test_inputs=inputs,
        policy=policy,
        application_id="app_quantum_fisheries_001",
    )
    assert artifact.status == CertificationStatus.CERTIFIED
    assert artifact.score == 1.0
    assert artifact.metrics.overall_equivalence_score == 1.0

    # 2. Spec with NO explicit rules and NO OracleSet:
    # Verify BEACON does NOT invent soil_moisture, credit_score, tax, medical, retail, loan, or any heuristic rules.
    spec_no_rules = ApplicationSpec(
        application_id="app_quantum_fisheries_norules",
        name="Quantum Marine Harvest Control No Rules",
        domain="quantum_fisheries",
        reference_implementation=ImplementationTarget(
            target_id="qf_ref_v1",
            name="qf_firmware_legacy",
            role=ApplicationRole.REFERENCE,
            entrypoint=reference_quantum_fisheries,
        ),
        target_implementations=[
            ImplementationTarget(
                target_id="qf_target_v2",
                name="qf_service_modern",
                role=ApplicationRole.TARGET,
                entrypoint=candidate_quantum_fisheries_clean,
            )
        ],
        input_contract=InputContract(
            fields={
                "biomass_density": (10.0, 100.0),
                "sonar_frequency_khz": (20.0, 80.0),
                "water_salinity_ppt": (5.0, 40.0),
            }
        ),
    )

    oset_deferred = resolver.resolve_oracle_set(spec_no_rules)
    assert len(oset_deferred.oracles) == 0
    assert oset_deferred.metadata["rule_discovery_status"] == "deferred_to_full_beacon"
    assert oset_deferred.metadata["rules_count"] == 0

    # Confirm none of the forbidden domain words exist in the resolved oracle definitions
    all_conditions = [o.condition for o in oset_deferred.oracles]
    forbidden_terms = ["soil_moisture", "credit_score", "annual_income", "tax", "medical", "retail", "loan"]
    for cond in all_conditions:
        for term in forbidden_terms:
            assert term not in cond


def test_generic_adapter_registry_registration_and_resolution():
    """Proves that generic AdapterRegistry can register and resolve arbitrary custom adapters
    without benchmark or domain knowledge.
    """
    custom_registry = AdapterRegistry()

    def dummy_fn(x: float) -> dict:
        return {"result": x * 2.0}

    custom_adapter = ReferenceAdapter(
        target_fn=dummy_fn,
        name="custom_reference_adapter_001",
        version="3.1.4",
    )

    custom_reg_record = AdapterRegistration(
        adapter_id="custom_reference_adapter_001:3.1.4",
        name="custom_reference_adapter_001",
        role="reference",
        version="3.1.4",
        implementation_type="custom",
        capabilities=["execution", "evidence_capture"],
        metadata={"custom_flag": True},
    )

    custom_registry.register_adapter(custom_adapter, registration=custom_reg_record)

    resolved = custom_registry.get_adapter("custom_reference_adapter_001", version="3.1.4")
    assert resolved is not None
    assert resolved.name == "custom_reference_adapter_001"
    assert resolved.version == "3.1.4"

    reg_meta = custom_registry.get_registration("custom_reference_adapter_001", version="3.1.4")
    assert reg_meta is not None
    assert reg_meta.adapter_id == "custom_reference_adapter_001:3.1.4"
    assert reg_meta.role == "reference"
    assert reg_meta.implementation_type == "custom"
    assert reg_meta.capabilities == ["execution", "evidence_capture"]
    assert reg_meta.metadata == {"custom_flag": True}


def test_resolver_inputs_fallback_marks_test_source():
    """Verifies that development fallback inputs are explicitly tagged with source metadata."""
    resolver = ApplicationResolver()
    spec_empty = ApplicationSpec(
        application_id="app_empty_contract",
        name="Empty Contract Application",
        reference_implementation="calc_ref",
    )

    inputs = resolver.resolve_inputs(spec_empty)
    assert len(inputs) == 10
    for inp in inputs:
        assert inp.provenance.get("source") == "phase1_test_fallback"


