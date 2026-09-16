"""BEACON V2 — Phase 10 Persistence Failure Semantics Tests.

Verifies:
1. When persistence encounters a database error, the error is NOT silently swallowed.
2. The explanation object returns with persistence_status = "FAILED" and is not falsely declared as succeeded.
"""

from pathlib import Path
import pytest
from evaluation.models import BehaviorDimension
from intelligence.models import (
    CertificationExplanation,
    DimensionExplanation,
    GenerationMetadata,
)
from intelligence.persistence import IntelligencePersistenceStore


def test_persistence_failure_sets_failed_status(tmp_path: Path):
    """Verify that a storage error does not crash generation and sets persistence_status = 'FAILED'."""
    # Point persistence store to a directory path instead of a file so sqlite3 fails on insert
    invalid_db_path = tmp_path  # directory instead of file
    store = IntelligencePersistenceStore(db_path=invalid_db_path)

    explanation = CertificationExplanation(
        explanation_id="EXP-FAIL-001",
        certification_id="CERT-FAIL-001",
        overall_verdict="NOT_CERTIFIED",
        executive_summary="Executive summary test",
        behavioral_summary="Behavioral summary test",
        dimension_explanations=[],
    )

    result = store.save_explanation(explanation)
    assert result.persistence_status == "FAILED"
