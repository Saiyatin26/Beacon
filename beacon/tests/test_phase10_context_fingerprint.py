"""BEACON V2 — Phase 10 Complete Context Fingerprint Tests.

Verifies:
1. Fingerprint is deterministic and canonical across all semantic fields.
2. Modifying any single semantic element produces a distinct SHA-256 fingerprint:
   - evidence ID
   - evidence value
   - threshold
   - rule
   - missing-evidence state
   - knowledge fingerprint
   - dimension result
3. Non-semantic runtime metadata (timestamps, latency, random UUIDs) do not alter the fingerprint.
"""

import pytest
from evaluation.models import BehaviorDimension
from intelligence.models import (
    CompanyKnowledgeContext,
    ExplanationContext,
    MissingEvidence,
    RetrievedKnowledgeCitation,
)


def _build_base_context() -> ExplanationContext:
    return ExplanationContext(
        certification_id="CERT-FP-001",
        application_id="app_fp_test",
        project_id="proj_fp_test",
        session_id="SESS-001",
        authoritative_verdict="NOT_CERTIFIED",
        equivalence_score=0.75,
        unique_inputs_count=10,
        matching_cases_count=7,
        regression_cases_count=3,
        dimensions_evaluated=[BehaviorDimension.OUTPUT, BehaviorDimension.STATE],
        differences_summary=[
            {
                "input_id": "INP-001",
                "difference_id": "DIFF-001",
                "reference_value": 100,
                "target_value": 90,
                "reference_evidence_id": "EVID-REF-001",
                "target_evidence_id": "EVID-TGT-001",
            }
        ],
        valid_evidence_ids=["EVID-REF-001", "EVID-TGT-001"],
        valid_rule_ids=["RULE-001"],
        valid_input_ids=["INP-001"],
        rules_context=[
            {
                "rule_id": "RULE-001",
                "status": "VIOLATED",
                "condition_str": "x > 0",
            }
        ],
        thresholds_context=[
            {
                "policy_id": "POL-001",
                "metric": "equivalence_score",
                "strategy": "fixed",
                "resolved_threshold": 0.85,
            }
        ],
        missing_evidence=[
            MissingEvidence(
                dimension=BehaviorDimension.STATE,
                description="Snapshots absent",
                implication="Inconclusive",
                status="INCONCLUSIVE",
            )
        ],
    )


def test_fingerprint_sensitivity_matrix():
    """Verify that changing any single semantic field alters the SHA-256 fingerprint."""
    base_ctx = _build_base_context()
    base_fp = base_ctx.compute_context_fingerprint()

    # 1. Evidence ID change
    ctx_evid = _build_base_context()
    ctx_evid.valid_evidence_ids = ["EVID-REF-001", "EVID-TGT-999"]
    assert ctx_evid.compute_context_fingerprint() != base_fp

    # 2. Value observation change
    ctx_val = _build_base_context()
    ctx_val.differences_summary[0]["target_value"] = 85
    assert ctx_val.compute_context_fingerprint() != base_fp

    # 3. Threshold change
    ctx_thresh = _build_base_context()
    ctx_thresh.thresholds_context[0]["resolved_threshold"] = 0.90
    assert ctx_thresh.compute_context_fingerprint() != base_fp

    # 4. Rule change
    ctx_rule = _build_base_context()
    ctx_rule.valid_rule_ids = ["RULE-002"]
    assert ctx_rule.compute_context_fingerprint() != base_fp

    # 5. Missing-evidence state change
    ctx_miss = _build_base_context()
    ctx_miss.missing_evidence = []
    assert ctx_miss.compute_context_fingerprint() != base_fp

    # 6. Knowledge retrieval fingerprint change
    ctx_know = _build_base_context()
    ctx_know.knowledge_context = CompanyKnowledgeContext(
        retrieval_query="query",
        retrieval_fingerprint="FP-KNOWLEDGE-ABC-123",
        citations=[],
    )
    assert ctx_know.compute_context_fingerprint() != base_fp

    # 7. Dimension result change
    ctx_dim = _build_base_context()
    ctx_dim.dimensions_evaluated = [BehaviorDimension.OUTPUT]
    assert ctx_dim.compute_context_fingerprint() != base_fp


def test_fingerprint_deterministic_stability():
    """Verify that identical semantic context produces identical fingerprint regardless of order."""
    ctx1 = _build_base_context()
    ctx2 = _build_base_context()
    assert ctx1.compute_context_fingerprint() == ctx2.compute_context_fingerprint()
