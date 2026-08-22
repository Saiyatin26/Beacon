"""Phase 14 — User-Supplied Dataset Ingestion Models.

Defines schemas, provenance classifications, ingestion manifests, and lifecycle
states for real and user-supplied dataset ingestion without altering certification semantics.
"""

from enum import Enum
import hashlib
import json
from typing import Any, Optional
from pydantic import BaseModel, Field


class DataFormat(str, Enum):
    JSON = "JSON"
    JSONL = "JSONL"
    CSV = "CSV"


class DatasetProvenanceCategory(str, Enum):
    USER_SUPPLIED = "USER_SUPPLIED"
    PUBLIC_EXTERNAL = "PUBLIC_EXTERNAL"
    PRIVATE_ENTERPRISE = "PRIVATE_ENTERPRISE"
    REALISTIC_SYNTHETIC = "REALISTIC_SYNTHETIC"
    BENCHMARK_DERIVED = "BENCHMARK_DERIVED"


class DatasetLifecycleStatus(str, Enum):
    UPLOADED = "UPLOADED"
    VALIDATED = "VALIDATED"
    READY = "READY"
    REJECTED = "REJECTED"
    CERTIFYING = "CERTIFYING"
    CERTIFIED = "CERTIFIED"
    NOT_CERTIFIED = "NOT_CERTIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"


class DatasetIngestionRequest(BaseModel):
    """Request payload for ingesting user-supplied datasets."""
    project_id: str = Field(..., description="Unique project namespace identifier")
    dataset_name: str = Field(..., description="Human-readable dataset name")
    description: Optional[str] = Field(default="", description="Dataset description")
    data_format: DataFormat = Field(default=DataFormat.JSON, description="File data format (JSON, JSONL, CSV)")
    raw_content: Optional[str] = Field(default=None, description="Raw text content of the dataset")
    declared_provenance: DatasetProvenanceCategory = Field(
        default=DatasetProvenanceCategory.USER_SUPPLIED,
        description="Declared truthful dataset provenance class",
    )
    dataset_version: str = Field(default="1.0.0", description="Semantic version of the dataset")
    source_reference: Optional[str] = Field(default=None, description="Optional external source URI or reference")
    target_domain: Optional[str] = Field(default=None, description="Target application domain")


class DatasetPreview(BaseModel):
    """Dry-run preview structure showing metadata, schema, and redacted samples without persistence."""
    dataset_name: str
    data_format: str
    row_count: int
    inferred_schema: dict[str, str]
    schema_fingerprint: str
    dataset_checksum: str
    input_set_hash: str
    sample_records: list[dict[str, Any]]
    validation_passed: bool
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class DatasetIngestionManifest(BaseModel):
    """Cryptographic manifest documenting accepted ingestion parameters and schema verification."""
    manifest_id: str
    dataset_id: str
    project_id: str
    dataset_name: str
    version: str = "1.0.0"
    data_format: str
    declared_provenance: DatasetProvenanceCategory = DatasetProvenanceCategory.USER_SUPPLIED
    source_reference: Optional[str] = None
    target_domain: Optional[str] = None
    checksum: str
    schema_fingerprint: str
    input_set_hash: str
    row_count: int
    accepted_records: int
    rejected_records: int = 0
    inferred_schema: dict[str, str] = Field(default_factory=dict)
    validation_rules_version: str = "1.0.0"
    status: DatasetLifecycleStatus = DatasetLifecycleStatus.READY
    created_at: str
    content_hash: str = ""


class UserDatasetRecord(BaseModel):
    """Internal representation of a persisted custom dataset and its canonical records."""
    dataset_id: str
    project_id: str
    dataset_name: str
    version: str
    manifest: DatasetIngestionManifest
    canonical_records: list[dict[str, Any]]
    created_at: str


def compute_schema_fingerprint(schema: dict[str, str]) -> str:
    """Computes deterministic SHA-256 fingerprint over canonical JSON schema dictionary."""
    canonical_json = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compute_canonical_dataset_checksum(records: list[dict[str, Any]]) -> str:
    """Computes deterministic SHA-256 checksum over canonical list of records.
    Normalizes numeric precision, sorts dictionary keys, and formats strictly as canonical JSON.
    """
    normalized_records = []
    for r in records:
        if not isinstance(r, dict):
            continue
        norm_row = {}
        for k in sorted(r.keys()):
            val = r[k]
            if isinstance(val, float):
                # Format float with up to 10 significant decimals, removing trailing zeroes
                norm_row[k] = round(val, 10)
            elif isinstance(val, (int, bool, str, list, dict)) or val is None:
                norm_row[k] = val
            else:
                norm_row[k] = str(val)
        normalized_records.append(norm_row)

    canonical_json = json.dumps(normalized_records, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
