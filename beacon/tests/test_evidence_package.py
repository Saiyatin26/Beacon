"""Unit and integration tests for Phase 5 Unified Evidence Model and Package."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

import legacy_loan_approval
from common.models import SourceLocation, StaticAnalysisResult, TraceEvent
from evidence.builder import EvidencePackageBuilder, build_evidence_package
from evidence.models import (
    CorrelatedConditionEvidence,
    DynamicEvidenceItem,
    StaticEvidenceItem,
    UnifiedEvidencePackage,
)
from ingestion.legacy_parser import extract_ast_structure
from ingestion.runtime_tracer import PythonRuntimeTracer
from ingestion.static_analyzer import PythonAnalyzer
from ingestion.trace_providers import RuntimeTraceProvider, SyntheticTraceProvider


def test_static_evidence_representation():
    item = StaticEvidenceItem(
        evidence_id="EV-S-001",
        type="STATIC_CONDITION",
        file="legacy_loan_approval.py",
        line=15,
        condition="credit_score < 600",
        strength=0.7,
        source_location_id="legacy_loan_approval.py:15",
    )
    assert item.evidence_id == "EV-S-001"
    assert item.strength == 0.7
    assert item.source_location_id == "legacy_loan_approval.py:15"


def test_dynamic_evidence_representation():
    item = DynamicEvidenceItem(
        evidence_id="EV-D-001",
        type="RUNTIME_OBSERVATION",
        execution_id="EX-001",
        timestamp="2026-08-17T12:00:00Z",
        function="evaluate_loan",
        inputs={"credit_score": 580, "debt_ratio": 0.47},
        output={"decision": "REJECT"},
        branch_results={"credit_score < 600": True, "debt_ratio > 0.4": True},
    )
    assert item.evidence_id == "EV-D-001"
    assert item.execution_id == "EX-001"
    assert item.branch_results["credit_score < 600"] is True


def test_combine_static_and_dynamic_evidence():
    code = """
def check(credit_score):
    if credit_score < 600:
        return "REJECT"
"""
    analyzer = PythonAnalyzer()
    static_res = analyzer.analyze(code, "sample.py")

    tracer = PythonRuntimeTracer()
    traces = tracer.trace_batch(
        lambda credit_score: {"decision": "REJECT" if credit_score < 600 else "APPROVE"},
        [{"credit_score": 580}, {"credit_score": 700}],
    )

    package = build_evidence_package(static_analysis=static_res, runtime_traces=traces)

    assert isinstance(package, UnifiedEvidencePackage)
    assert len(package.static_evidence_items) > 0
    assert len(package.dynamic_evidence_items) == 2
    assert len(package.correlated_conditions) > 0


def test_source_locations_and_execution_ids_preserved():
    code = """
def evaluate(credit_score):
    if credit_score < 500:
        return "REJECT"
"""
    analyzer = PythonAnalyzer()
    static_res = analyzer.analyze(code, "test_file.py")

    tracer = PythonRuntimeTracer()
    trace_event = tracer.trace_execution(
        lambda credit_score: {"decision": "REJECT" if credit_score < 500 else "APPROVE"},
        {"credit_score": 450},
        execution_id="EX-100",
    )

    package = build_evidence_package(static_analysis=static_res, runtime_traces=[trace_event])

    # Verify source locations preserved
    s_item = package.static_evidence_items[0]
    assert s_item.file == "test_file.py"
    assert s_item.line == 3

    # Verify execution IDs preserved
    d_item = package.dynamic_evidence_items[0]
    assert d_item.execution_id == "EX-100"


def test_multiple_traces_support_one_candidate_condition():
    code = """
def eval_rule(credit_score, debt_ratio):
    if credit_score < 600 and debt_ratio > 0.4:
        return "REJECT"
"""
    analyzer = PythonAnalyzer()
    static_res = analyzer.analyze(code, "rule.py")

    tracer = PythonRuntimeTracer()
    traces = tracer.trace_batch(
        lambda credit_score, debt_ratio: {"decision": "REJECT" if credit_score < 600 and debt_ratio > 0.4 else "APPROVE"},
        [
            {"credit_score": 580, "debt_ratio": 0.47},
            {"credit_score": 550, "debt_ratio": 0.50},
            {"credit_score": 599, "debt_ratio": 0.41},
        ],
    )

    package = build_evidence_package(static_analysis=static_res, runtime_traces=traces)
    correlated = next(c for c in package.correlated_conditions if "credit_score < 600" in c.condition_expr)

    assert correlated.runtime_observations >= 3
    assert len(correlated.execution_ids) >= 3
    assert correlated.observed_outcomes.get("REJECT") == 3


def test_evidence_package_json_serializability():
    code = "def f(x):\n    if x < 10:\n        return x"
    static_res = PythonAnalyzer().analyze(code, "dummy.py")
    traces = PythonRuntimeTracer().trace_batch(lambda x: {"result": x}, [{"x": 5}])

    package = build_evidence_package(static_res, traces)

    json_str = package.model_dump_json()
    assert isinstance(json_str, str)

    deserialized = UnifiedEvidencePackage.model_validate_json(json_str)
    assert deserialized.package_id == package.package_id
    assert deserialized.source_file == package.source_file


def test_evidence_package_consumed_by_mining_layer():
    """Verify that Stage 2 mining layer can consume UnifiedEvidencePackage payload."""
    sample_file = ROOT / "legacy_sample" / "legacy_loan_approval.py"
    ast_dict = extract_ast_structure(sample_file)
    static_res = StaticAnalysisResult.model_validate(ast_dict)

    runtime_provider = RuntimeTraceProvider(target_func=legacy_loan_approval.evaluate_loan)
    traces = runtime_provider.get_traces()

    package = build_evidence_package(static_res, traces, project_id="loan-approval-project")
    assert package.project_id == "loan-approval-project"

    # Confirm mining layer can extract traces from package
    package_traces = package.runtime_traces
    assert len(package_traces) > 0


def test_phase5_final_acceptance_pipeline():
    """PHASE 5 FINAL ACCEPTANCE TEST:
    End-to-end Phase 1-5 pipeline connecting Static Analysis + Dynamic Tracing into Unified Evidence Package.
    """
    sample_file = ROOT / "legacy_sample" / "legacy_loan_approval.py"

    # 1. Phase 3 Static Analyzer
    ast_dict = extract_ast_structure(sample_file)
    static_res = StaticAnalysisResult.model_validate(ast_dict)
    assert len(static_res.comparisons) >= 5

    # 2. Phase 4 Runtime Tracer
    runtime_provider = RuntimeTraceProvider(target_func=legacy_loan_approval.evaluate_loan)
    traces = runtime_provider.get_traces()
    assert len(traces) > 0

    # 3. Phase 5 Unified Evidence Package Assembly
    package = build_evidence_package(
        static_analysis=static_res,
        runtime_traces=traces,
        project_id="beacon-loan-pipeline",
    )

    assert isinstance(package, UnifiedEvidencePackage)
    assert package.source_file == "legacy_loan_approval.py"
    assert len(package.static_evidence_items) > 0
    assert len(package.dynamic_evidence_items) > 0

    # 4. Verify support for hidden invariant: credit_score < 600 AND debt_ratio > 0.4 -> REJECT
    hidden_rule_corr = next(
        (c for c in package.correlated_conditions if "credit_score < 600" in c.condition_expr and "debt_ratio > 0.4" in c.condition_expr),
        None,
    )
    assert hidden_rule_corr is not None, "Evidence package must contain correlated evidence for credit_score < 600 and debt_ratio > 0.4"
    assert hidden_rule_corr.runtime_observations > 0
    assert hidden_rule_corr.observed_outcomes.get("REJECT", 0) > 0
    assert len(hidden_rule_corr.execution_ids) > 0
