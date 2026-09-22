"""Phase 12 — Benchmark Specifications, Provenance, and Dataset Models.

Defines the contract for external/public legacy benchmarks, dataset specifications,
provenance categories, execution manifests, and validation results.
"""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class ProvenanceCategory(str, Enum):
    """Categorizes the origin and realism of a benchmark."""
    CONTROLLED = "CONTROLLED"                                    # Controlled synthetic reference benchmark
    REALISTIC_SYNTHETIC = "REALISTIC_SYNTHETIC"                  # Realistic synthetic domain engine
    REALISTIC = "REALISTIC"                                      # Backward compatible alias for REALISTIC_SYNTHETIC
    PUBLIC_STATUTORY = "PUBLIC_STATUTORY"                        # Public-style statutory/regulatory logic bundled in benchmark
    PUBLIC = "PUBLIC"                                            # Backward compatible alias for PUBLIC_STATUTORY
    AUTHENTIC_PUBLIC_MIGRATION = "AUTHENTIC_PUBLIC_MIGRATION"   # Genuine external public migration codebase


class ModernizationProvenance(str, Enum):
    """Categorizes how the modernized implementation was created."""
    CONTROLLED_MUTATION = "CONTROLLED_MUTATION"                  # Intentionally introduced behavioral mutation for sensitivity testing
    INDEPENDENT_REIMPLEMENTATION = "INDEPENDENT_REIMPLEMENTATION" # Clean, structured equivalent modernization
    AUTHENTIC_PUBLIC_MIGRATION = "AUTHENTIC_PUBLIC_MIGRATION"   # Authentic external public migration


class DiscoveryMode(str, Enum):
    """Categorizes the oracle specification origin for an experiment."""
    CONTROLLED = "CONTROLLED"      # Evaluation against predefined/frozen baseline OracleSet
    FULL_BEACON = "FULL_BEACON"    # End-to-end evidence mining -> grounding -> adversarial validation -> Oracle compilation


class DatasetSpec(BaseModel):
    """Specification of an evaluation input dataset."""
    dataset_id: str
    name: str
    version: str = "1.0.0"
    record_count: int = 0
    checksum: str = ""                # SHA-256 hex digest of the raw dataset file
    source: str = ""
    license: str = "Apache-2.0"
    acquisition_method: str = "bundled" # "bundled", "download_script", "derived_anonymized"
    file_path: str = ""
    input_schema: dict[str, str] = Field(default_factory=dict)
    description: str = ""


class ReproducibilityManifest(BaseModel):
    """Benchmark-level reproducibility manifest."""
    benchmark_id: str = ""
    benchmark_version: str = "1.0.0"
    adapter_version: str = "1.0.0"
    dataset_checksum: str = ""
    input_set_hash: str = ""
    oracle_set_hash: str = ""
    policy_hash: str = ""
    certification_engine_version: str = "1.0.0"
    environment_requirements: dict[str, str] = Field(default_factory=lambda: {"python": ">=3.10"})


class BenchmarkSpec(BaseModel):
    """Comprehensive specification for an external or public benchmark."""
    benchmark_id: str
    name: str
    domain: str
    description: str
    source: str
    source_repository: Optional[str] = None
    source_url: Optional[str] = None
    source_commit: Optional[str] = None
    source_version: str = "1.0.0"
    source_license: str = "Apache-2.0"
    license: str = "Apache-2.0"
    language: str = "Python"
    legacy_version: str = "1.0.0"
    modernized_version: str = "2.0.0"
    provenance_category: ProvenanceCategory = ProvenanceCategory.REALISTIC_SYNTHETIC
    modernization_provenance: dict[str, ModernizationProvenance] = Field(default_factory=dict)
    input_schema: dict[str, str] = Field(default_factory=dict)
    output_schema: dict[str, str] = Field(default_factory=dict)
    expected_behavior_source: str = "oracle_derived" # "oracle_derived" or "external_ground_truth"
    dataset_source: str = ""
    dataset_license: str = "Apache-2.0"
    dataset_version: str = "1.0.0"
    dataset_checksum: str = ""
    adapter_version: str = "1.0.0"
    legacy_adapter_id: str = ""
    legacy_implementation_hash: str = ""
    modernized_adapters: dict[str, str] = Field(default_factory=dict) # variant_name -> adapter_id
    field_bounds: dict[str, tuple[float, float]] = Field(default_factory=dict)
    reproducibility_manifest: Optional[ReproducibilityManifest] = None
    tags: list[str] = Field(default_factory=list)


class BenchmarkValidationRequest(BaseModel):
    """Request payload for comprehensive benchmark pre-flight validation."""
    benchmark_id: Optional[str] = None
    dataset_name: str = "default"
    evaluation_mode: str = "CONTROLLED"
    target_variant: str = "clean_v2"
    preferred_provider: str = "auto"
    policy_id: str = "POL-DEFAULT"


class BenchmarkValidationResult(BaseModel):
    """Pre-flight validation result for a benchmark's adapters, schema, dataset, and configuration."""
    benchmark_id: str
    evaluation_mode: str = "CONTROLLED"
    target_variant: str = "clean_v2"
    preferred_provider: str = "auto"
    config_fingerprint: str = ""
    is_valid: bool
    checks_passed: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    legacy_adapter_status: str = "UNKNOWN"
    modernized_adapters_status: dict[str, str] = Field(default_factory=dict)
    target_variant_adapter_status: str = "UNKNOWN"
    dataset_record_count: int = 0
    dataset_checksum: str = ""
    legacy_implementation_hash: str = ""
    modernized_implementation_hash: str = ""
    metadata_provenance_valid: bool = True
    oracle_set_id: str = ""
    oracle_set_hash: str = ""


class BenchmarkExecutionManifest(BaseModel):
    """Audit record capturing complete provenance, implementation hashes, and disambiguated metrics."""
    model_config = {"protected_namespaces": ()}

    benchmark_id: str
    benchmark_version: str = "1.0.0"
    provenance_category: ProvenanceCategory
    modernization_provenance: str
    source_version: str = "1.0.0"
    adapter_version: str = "1.0.0"
    legacy_implementation_hash: str = ""
    modernized_implementation_hash: str = ""
    dataset_id: str
    dataset_version: str = "1.0.0"
    dataset_checksum: str
    input_set_id: str
    input_set_hash: str
    evidence_collection_version: str = "1.0.0"
    invariant_mining_config: dict[str, Any] = Field(default_factory=dict)
    model_provider_identifier: str = "offline/deterministic"
    provider: str = "offline"
    model: str = "deterministic"
    generation_method: str = "offline"
    oracle_set_id: str
    oracle_set_hash: str
    oracle_set_provenance: str = "CONTROLLED_ORACLE_SET"
    oracle_source_type: str = "CONTROLLED_ORACLE_SET"
    evidence_package_hash: str = ""
    prompt_version: str = "v1.0"
    policy_id: str
    policy_hash: str
    beacon_version: str = "1.0.0"
    execution_timestamp: str = ""
    discovery_mode: DiscoveryMode = DiscoveryMode.CONTROLLED
    environment_info: dict[str, str] = Field(default_factory=dict)
    # Disambiguated metrics
    unique_input_count: int = 0
    certification_case_count: int = 0
    oracle_count: int = 0
    oracle_evaluation_count: int = 0
    matching_case_count: int = 0
    regression_case_count: int = 0
    execution_error_count: int = 0
    counterexample_count: int = 0
    total_inputs: int = 0
    total_oracles: int = 0
    total_cases: int = 0
    violations: int = 0
    errors: int = 0
    oracle_coverage_pct: Optional[float] = None
    equivalence_score: float = 0.0
    certification_status: str = "NOT_CERTIFIED"
    artifact_hash: str = ""
