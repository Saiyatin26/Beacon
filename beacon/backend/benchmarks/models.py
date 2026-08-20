"""Phase 12 — Benchmark Specifications, Provenance, and Dataset Models.

Defines the contract for external/public legacy benchmarks, dataset specifications,
provenance categories, and validation results.
"""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class ProvenanceCategory(str, Enum):
    """Categorizes the origin and realism of a benchmark."""
    CONTROLLED = "CONTROLLED"          # Synthetic/controlled experiment benchmark
    PUBLIC = "PUBLIC"                  # Publicly sourced legacy logic/rules (e.g. government/tax specs)
    REALISTIC = "REALISTIC"            # Realistic production-representative business engine
    REAL_EXTERNAL = "REAL_EXTERNAL"    # Authentic external open-source legacy system


class DatasetSpec(BaseModel):
    """Specification of an evaluation input dataset."""
    dataset_id: str
    name: str
    version: str = "1.0.0"
    record_count: int = 0
    checksum: str = ""                # SHA-256 hex digest of the raw dataset file
    source: str = ""
    acquisition_method: str = "bundled" # "bundled", "download_script", "derived_anonymized"
    file_path: str = ""
    input_schema: dict[str, str] = Field(default_factory=dict)
    description: str = ""


class ReproducibilityManifest(BaseModel):
    """Benchmark-level reproducibility manifest."""
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
    source_url: Optional[str] = None
    license: str = "Apache-2.0"
    language: str = "Python"
    legacy_version: str = "1.0.0"
    modernized_version: str = "2.0.0"
    provenance_category: ProvenanceCategory = ProvenanceCategory.REALISTIC
    input_schema: dict[str, str] = Field(default_factory=dict)
    output_schema: dict[str, str] = Field(default_factory=dict)
    expected_behavior_source: str = "oracle_derived" # "oracle_derived" or "external_ground_truth"
    dataset_source: str = ""
    dataset_version: str = "1.0.0"
    legacy_adapter_id: str = ""
    modernized_adapters: dict[str, str] = Field(default_factory=dict) # variant_name -> adapter_id
    field_bounds: dict[str, tuple[float, float]] = Field(default_factory=dict)
    reproducibility_manifest: Optional[ReproducibilityManifest] = None
    tags: list[str] = Field(default_factory=list)


class BenchmarkValidationResult(BaseModel):
    """Pre-flight validation result for a benchmark's adapters, schema, and dataset."""
    benchmark_id: str
    is_valid: bool
    checks_passed: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    legacy_adapter_status: str = "UNKNOWN"
    modernized_adapters_status: dict[str, str] = Field(default_factory=dict)
    dataset_record_count: int = 0
    dataset_checksum: str = ""
