"""Phase 12 — Deterministic Benchmark Dataset Loader and Schema Validator.

Loads, validates, and hashes input datasets for benchmarks, ensuring that all
external inputs feed directly into the Phase 11 CertificationInputSet pipeline.
"""

import csv
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional

from certification.models import CertificationTestInput

logger = logging.getLogger(__name__)


def compute_file_checksum(file_path: Path) -> str:
    """Computes the SHA-256 checksum of a dataset file."""
    if not file_path.exists():
        return ""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _cast_value(val: Any, expected_type: str) -> Any:
    """Casts a scalar value to the expected schema type with strict validation."""
    if val is None or val == "":
        return None
    expected = expected_type.lower()
    if expected in ("float", "number", "real"):
        return float(val)
    elif expected in ("int", "integer"):
        return int(float(val))
    elif expected in ("bool", "boolean"):
        if isinstance(val, bool):
            return val
        s = str(val).strip().lower()
        if s in ("true", "1", "yes", "t"):
            return True
        elif s in ("false", "0", "no", "f"):
            return False
        raise ValueError(f"Cannot cast '{val}' to boolean")
    elif expected in ("str", "string"):
        return str(val).strip()
    return val


def validate_and_normalize_record(
    record: dict[str, Any],
    schema: dict[str, str],
    index: int,
) -> dict[str, Any]:
    """Validates and normalizes a single record against the expected input schema."""
    normalized: dict[str, Any] = {}
    for field_name, expected_type in schema.items():
        if field_name not in record:
            raise ValueError(f"Record #{index} missing required field '{field_name}'")
        raw_val = record[field_name]
        try:
            casted = _cast_value(raw_val, expected_type)
            if casted is None:
                raise ValueError(f"Record #{index} has null/empty value for required field '{field_name}'")
            normalized[field_name] = casted
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Record #{index} field '{field_name}' invalid type: {exc}")
    return normalized


def load_dataset_file(
    file_path: Path,
    input_schema: dict[str, str],
    benchmark_id: str = "benchmark",
) -> tuple[list[CertificationTestInput], str]:
    """Loads a JSON or CSV dataset file, validates records against input_schema,
    and returns a deterministic list of CertificationTestInput objects and file checksum.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {file_path}")

    checksum = compute_file_checksum(file_path)
    raw_records: list[dict[str, Any]] = []

    suffix = file_path.suffix.lower()
    if suffix == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                raw_records = data
            elif isinstance(data, dict) and "records" in data:
                raw_records = data["records"]
            else:
                raise ValueError("JSON dataset must be a list of records or an object containing a 'records' list.")
    elif suffix == ".csv":
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            raw_records = [dict(row) for row in reader]
    else:
        raise ValueError(f"Unsupported dataset file format: '{suffix}'. Use .json or .csv.")

    test_inputs: list[CertificationTestInput] = []
    for idx, raw in enumerate(raw_records):
        norm_values = validate_and_normalize_record(raw, input_schema, idx)
        
        # Compute deterministic stable input ID from canonical JSON
        val_json = json.dumps(norm_values, sort_keys=True, separators=(",", ":"))
        val_hash = hashlib.sha256(val_json.encode("utf-8")).hexdigest()[:8]
        input_id = f"INP-{benchmark_id[:6].upper()}-{idx:03d}-{val_hash}"

        test_inputs.append(
            CertificationTestInput(
                input_id=input_id,
                values=norm_values,
                origin="explicit_case",
                provenance={"benchmark_id": benchmark_id, "record_index": idx},
                tags=["benchmark_dataset", benchmark_id],
            )
        )

    return test_inputs, checksum
