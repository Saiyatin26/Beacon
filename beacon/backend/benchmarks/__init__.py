"""Phase 12 — Real-World / Public Benchmark Subsystem.

Exports:
- Models: BenchmarkSpec, DatasetSpec, ProvenanceCategory, BenchmarkValidationResult, ReproducibilityManifest
- Loader: load_dataset_file, compute_file_checksum
- Registry: BenchmarkRegistry, benchmark_registry
"""

from .models import (
    BenchmarkSpec,
    BenchmarkValidationResult,
    DatasetSpec,
    ProvenanceCategory,
    ReproducibilityManifest,
)
from .dataset_loader import compute_file_checksum, load_dataset_file
from .registry import BenchmarkRegistry, benchmark_registry

__all__ = [
    "BenchmarkSpec",
    "DatasetSpec",
    "ProvenanceCategory",
    "BenchmarkValidationResult",
    "ReproducibilityManifest",
    "load_dataset_file",
    "compute_file_checksum",
    "BenchmarkRegistry",
    "benchmark_registry",
]
