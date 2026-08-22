"""Phase 14 — User-Supplied Dataset Ingestion Validator & Sanitizer.

Provides strict parsing, schema inference, size limits, row limits, secret scanning,
redacted preview generation, and canonical SHA-256 fingerprinting for user-supplied datasets.
"""

import csv
import io
import json
import logging
import re
from typing import Any, Optional
from datetime import datetime, timezone
import hashlib

from certification.models import (
    CertificationTestInput,
    compute_input_set_canonical_hash,
)
from .dataset_models import (
    DataFormat,
    DatasetIngestionManifest,
    DatasetIngestionRequest,
    DatasetLifecycleStatus,
    DatasetPreview,
    compute_canonical_dataset_checksum,
    compute_schema_fingerprint,
)

logger = logging.getLogger(__name__)

# Configurable Limits
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_DATASET_ROWS = 5000
MIN_DATASET_ROWS = 1

# Security Patterns for Credentials and Secrets
SECRET_PATTERNS = [
    re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}", re.IGNORECASE),
    re.compile(r"sk-or-[a-zA-Z0-9_\-]{20,}", re.IGNORECASE),
    re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"github_pat_[a-zA-Z0-9_]{40,}"),
    re.compile(r"mongodb\+srv://[^\s]+"),
]


def scan_for_secrets(text: str) -> bool:
    """Scans content for known credential patterns and secret tokens."""
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return True
    return False


def infer_scalar_type(val: Any) -> str:
    """Infers canonical scalar type name for schema fingerprinting."""
    if isinstance(val, bool):
        return "bool"
    if isinstance(val, int):
        return "int"
    if isinstance(val, float):
        return "float"
    if isinstance(val, dict):
        return "dict"
    if isinstance(val, list):
        return "list"
    if isinstance(val, str):
        # Check if numeric string in CSV context
        if val.lower() in ("true", "false"):
            return "bool"
        try:
            int(val)
            return "int"
        except ValueError:
            pass
        try:
            float(val)
            return "float"
        except ValueError:
            pass
        return "str"
    if val is None:
        return "null"
    return "str"


def cast_csv_value(val: str) -> Any:
    """Casts string values from CSV into appropriate numeric/boolean/string types."""
    if val is None:
        return ""
    val_stripped = val.strip()
    if val_stripped.lower() == "true":
        return True
    if val_stripped.lower() == "false":
        return False
    if val_stripped.lower() in ("null", "none", ""):
        return None
    try:
        return int(val_stripped)
    except ValueError:
        pass
    try:
        return float(val_stripped)
    except ValueError:
        pass
    return val_stripped


class DatasetValidator:
    """Validates, sanitizes, and canonicalizes user-supplied dataset payloads."""

    def __init__(
        self,
        max_size_bytes: int = MAX_UPLOAD_SIZE_BYTES,
        max_rows: int = MAX_DATASET_ROWS,
        min_rows: int = MIN_DATASET_ROWS,
    ):
        self.max_size_bytes = max_size_bytes
        self.max_rows = max_rows
        self.min_rows = min_rows

    def parse_raw_content(
        self,
        raw_text: str,
        data_format: DataFormat,
    ) -> tuple[list[dict[str, Any]], list[str], list[str]]:
        """Parses raw text payload according to declared format, performing validation checks."""
        warnings: list[str] = []
        errors: list[str] = []
        records: list[dict[str, Any]] = []

        if not raw_text or not raw_text.strip():
            errors.append("Dataset content is empty.")
            return records, warnings, errors

        content_bytes = len(raw_text.encode("utf-8"))
        if content_bytes > self.max_size_bytes:
            errors.append(
                f"Dataset size ({content_bytes} bytes) exceeds maximum allowable limit of {self.max_size_bytes} bytes (10MB)."
            )
            return records, warnings, errors

        # Secret scanning
        if scan_for_secrets(raw_text):
            errors.append(
                "Security violation: Uploaded dataset contains prohibited secret tokens, private keys, or API credentials. Ingestion rejected."
            )
            return records, warnings, errors

        try:
            if data_format == DataFormat.JSON:
                parsed = json.loads(raw_text)
                if isinstance(parsed, list):
                    records = [r for r in parsed if isinstance(r, dict)]
                elif isinstance(parsed, dict):
                    # Check common wrapper keys
                    for k in ("data", "records", "items", "rows", "inputs"):
                        if k in parsed and isinstance(parsed[k], list):
                            records = [r for r in parsed[k] if isinstance(r, dict)]
                            break
                    if not records:
                        records = [parsed]
                else:
                    errors.append("JSON payload must contain an array of objects or an object containing a records array.")

            elif data_format == DataFormat.JSONL:
                for idx, line in enumerate(raw_text.strip().splitlines()):
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        row_obj = json.loads(line_str)
                        if isinstance(row_obj, dict):
                            records.append(row_obj)
                        else:
                            warnings.append(f"Row #{idx + 1} is not a valid JSON object; skipped.")
                    except json.JSONDecodeError as jde:
                        errors.append(f"JSONL parse error on line #{idx + 1}: {str(jde)}")

            elif data_format == DataFormat.CSV:
                reader = csv.DictReader(io.StringIO(raw_text))
                if not reader.fieldnames:
                    errors.append("CSV payload contains no valid header columns.")
                else:
                    for idx, row in enumerate(reader):
                        casted_row = {k: cast_csv_value(v) for k, v in row.items() if k is not None}
                        records.append(casted_row)

        except Exception as exc:
            errors.append(f"Failed to parse {data_format.value} content: {str(exc)}")

        if not errors:
            if len(records) < self.min_rows:
                errors.append(f"Dataset contains {len(records)} records, but at least {self.min_rows} record is required.")
            elif len(records) > self.max_rows:
                errors.append(f"Dataset contains {len(records)} records, exceeding the maximum limit of {self.max_rows} rows.")

        return records, warnings, errors

    def extract_schema(self, records: list[dict[str, Any]]) -> dict[str, str]:
        """Extracts consistent field schemas across records."""
        if not records:
            return {}
        schema: dict[str, str] = {}
        for r in records:
            for k, v in r.items():
                inferred = infer_scalar_type(v)
                if k not in schema:
                    schema[k] = inferred
                elif schema[k] != inferred and inferred != "null":
                    # Upgrade int to float if numeric divergence
                    if {schema[k], inferred} == {"int", "float"}:
                        schema[k] = "float"
                    else:
                        schema[k] = "str"
        return dict(sorted(schema.items()))

    def create_preview(self, request: DatasetIngestionRequest) -> DatasetPreview:
        """Generates dry-run preview with schema, checksum, and redacted samples without persisting."""
        records, warnings, errors = self.parse_raw_content(
            raw_text=request.raw_content or "",
            data_format=request.data_format,
        )

        inferred_schema = self.extract_schema(records)
        schema_fingerprint = compute_schema_fingerprint(inferred_schema) if inferred_schema else ""
        dataset_checksum = compute_canonical_dataset_checksum(records) if records else ""

        # Compute sample inputs and input-set hash
        sample_inputs = []
        for i, r in enumerate(records[:5]):
            # Redact long strings or PII-like patterns if needed
            redacted_row = {}
            for k, v in r.items():
                if isinstance(v, str) and len(v) > 100:
                    redacted_row[k] = v[:40] + "..." + v[-10:]
                else:
                    redacted_row[k] = v
            sample_inputs.append(redacted_row)

        test_inputs = [
            CertificationTestInput(
                input_id=f"PREV-{i:04d}",
                values=r,
                input_hash=hashlib.sha256(json.dumps(r, sort_keys=True).encode("utf-8")).hexdigest(),
                origin="explicit_case",
            )
            for i, r in enumerate(records)
        ]
        input_set_hash = compute_input_set_canonical_hash(test_inputs) if test_inputs else ""

        return DatasetPreview(
            dataset_name=request.dataset_name,
            data_format=request.data_format.value,
            row_count=len(records),
            inferred_schema=inferred_schema,
            schema_fingerprint=schema_fingerprint,
            dataset_checksum=dataset_checksum,
            input_set_hash=input_set_hash,
            sample_records=sample_inputs,
            validation_passed=len(errors) == 0,
            warnings=warnings,
            errors=errors,
        )

    def validate_for_ingestion(
        self,
        request: DatasetIngestionRequest,
    ) -> tuple[DatasetIngestionManifest, list[dict[str, Any]], list[CertificationTestInput]]:
        """Performs authoritative validation and prepares dataset manifest, canonical records, and test inputs."""
        records, warnings, errors = self.parse_raw_content(
            raw_text=request.raw_content or "",
            data_format=request.data_format,
        )

        if errors:
            raise ValueError(f"Dataset validation failed: {'; '.join(errors)}")

        inferred_schema = self.extract_schema(records)
        schema_fingerprint = compute_schema_fingerprint(inferred_schema)
        dataset_checksum = compute_canonical_dataset_checksum(records)

        now_str = datetime.now(timezone.utc).isoformat()
        dataset_id = f"UDS-{hashlib.sha256(f'{request.project_id}:{request.dataset_name}:{dataset_checksum}'.encode('utf-8')).hexdigest()[:12]}"
        manifest_id = f"MAN-{hashlib.sha256(f'{dataset_id}:{now_str}'.encode('utf-8')).hexdigest()[:12]}"

        test_inputs = [
            CertificationTestInput(
                input_id=f"INP-{i:04d}",
                values=r,
                input_hash=hashlib.sha256(json.dumps(r, sort_keys=True).encode("utf-8")).hexdigest(),
                origin="explicit_case",
            )
            for i, r in enumerate(records)
        ]
        input_set_hash = compute_input_set_canonical_hash(test_inputs)

        manifest = DatasetIngestionManifest(
            manifest_id=manifest_id,
            dataset_id=dataset_id,
            project_id=request.project_id,
            dataset_name=request.dataset_name,
            version=request.dataset_version,
            data_format=request.data_format.value,
            declared_provenance=request.declared_provenance,
            source_reference=request.source_reference,
            target_domain=request.target_domain,
            checksum=dataset_checksum,
            schema_fingerprint=schema_fingerprint,
            input_set_hash=input_set_hash,
            row_count=len(records),
            accepted_records=len(records),
            rejected_records=0,
            inferred_schema=inferred_schema,
            validation_rules_version="1.0.0",
            status=DatasetLifecycleStatus.READY,
            created_at=now_str,
            content_hash=dataset_checksum,
        )

        return manifest, records, test_inputs


# Singleton default validator instance
dataset_validator = DatasetValidator()
