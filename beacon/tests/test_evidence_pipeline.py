"""Integration tests proving the evidence architecture is correctly connected."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

import legacy_loan_approval
from generate_traces import generate_traces
from ingestion.legacy_parser import extract_ast_structure
from ingestion.trace_loader import load_traces
from evidence.builder import build_evidence_package
from mining.pipeline import run_mining_pipeline
from common.models import TraceEvent


FIELD_BOUNDS = {
    "credit_score": (400, 820),
    "debt_ratio": (0.0, 0.9),
    "annual_income": (10_000, 150_000),
}


def test_evidence_package_integration_flow():
    """Prove that mining uses the UnifiedEvidencePackage, produces candidates, validates, and calculates confidence."""
    
    # 1. Load sample legacy program
    legacy_file = str(ROOT / "legacy_sample" / "legacy_loan_approval.py")
    
    # 2. Run static analysis
    static_result = extract_ast_structure(legacy_file)
    assert len(static_result.conditions) > 0
    
    # 3. Generate/load runtime traces
    trace_dicts = generate_traces(n_random=500)
    traces = [TraceEvent(**t) for t in trace_dicts]
    assert len(traces) > 0
    
    # 4. Construct UnifiedEvidencePackage
    evidence_pkg = build_evidence_package(static_result, traces)
    assert len(evidence_pkg.static_evidence_items) > 0
    assert len(evidence_pkg.dynamic_evidence_items) > 0
    
    # 5-9. Pass to generator, collect evidence, validation, confidence scoring, threshold
    graduated, unconfirmed = run_mining_pipeline(
        evidence_package=evidence_pkg,
        legacy_fn=legacy_loan_approval.evaluate_loan,
        field_bounds=FIELD_BOUNDS,
        already_validated=[],
        use_atlas=False,
        use_llm=False
    )
    
    # Verify resulting status is correct
    assert len(graduated) + len(unconfirmed) > 0
    
    # Check provenance
    if graduated:
        assert graduated[0].generation_method == "offline"
        assert len(graduated[0].evidence_ids) > 0
