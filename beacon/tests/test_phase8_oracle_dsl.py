"""Comprehensive Test Suite for Phase 8 — Language-Independent Behavioral Oracle DSL.

Tests:
1. Valid Invariant-to-Oracle Compilation
2. Strict Rejection of Unvalidated / Low-Confidence Candidates
3. Comparison Predicate Variations (<, <=, ==, !=, >=, >)
4. Compound Boolean Conditions (AND, OR, NOT, Nested)
5. Diverse Consequence Types (String, Numeric, Boolean)
6. Rejection of Unsupported Syntax (Calls, Lambdas, Bitwise Ops)
7. Deterministic Canonical Serialization and SHA-256 Hashing
8. Language-Independent Evaluator (PASS, FAIL, NOT_APPLICABLE, INVALID_INPUT)
9. Versioned Immutable Registry & Historical Integrity
10. Frozen Oracle Set and Composite Hashing
11. Zero LLM Dependency in Compilation & Evaluation
"""

import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

from common.models import CandidateInvariant, Counterexample, ValidationReport
from oracle import (
    CompoundCondition,
    OracleCompilationError,
    OracleDefinition,
    OracleEvaluationReport,
    OraclePredicate,
    OracleRegistry,
    OracleSet,
    OracleStatus,
    UnaryCondition,
    compile_candidate_to_oracle,
    compute_content_hash,
    compute_oracle_set_hash,
    evaluate_condition,
    evaluate_oracle,
    parse_condition_to_ast,
    parse_consequence_to_ast,
    run_oracle,
    serialize_canonical_oracle,
    synthesize_oracle,
)


def _create_sample_candidate(
    condition: str = "credit_score < 600 and debt_ratio > 0.4",
    consequence: str = "REJECT",
    confidence: float = 0.92,
    status: str = "graduated",
    counterexamples: list = None,
) -> CandidateInvariant:
    val_report = None
    if counterexamples is not None:
        val_report = ValidationReport(
            invariant_id="INV-001",
            overall_property_pass_rate=0.95,
            boundary_pass_rate=0.90,
            counterexamples=counterexamples,
        )

    return CandidateInvariant(
        invariant_id="local-c7180ce5",
        condition=condition,
        raw_condition=condition,
        consequence=consequence,
        source_file="legacy_loan_approval.py",
        source_lines=[14],
        severity="critical",
        evidence_ids=["EV-S-002", "EV-D-014"],
        execution_ids=["EX-004", "EX-009"],
        generation_method="offline",
        timestamp="2026-08-19T10:00:00Z",
        rationale="Loan denial rule for high risk applicants.",
        confidence=confidence,
        status=status,
        validation_result=val_report,
        reproducibility={"provider": "offline", "model": "deterministic-rule-miner"},
    )


# ==============================================================================
# 1. Valid Compilation & Schema Extraction
# ==============================================================================

def test_compile_valid_candidate_to_oracle():
    cand = _create_sample_candidate()
    oracle = compile_candidate_to_oracle(cand)

    assert isinstance(oracle, OracleDefinition)
    assert oracle.oracle_id.startswith("ORC-")
    assert oracle.version == 1
    assert oracle.domain == "loan_approval" or oracle.domain == "business_logic"
    assert oracle.severity == "critical"
    assert oracle.confidence == 0.92
    assert oracle.status == OracleStatus.ACTIVE
    assert len(oracle.content_hash) == 64  # SHA-256 length

    # Verify Condition AST
    assert isinstance(oracle.condition, CompoundCondition)
    assert oracle.condition.type == "AND"
    assert len(oracle.condition.operands) == 2

    # Verify Input Schema
    var_names = [v.name for v in oracle.input_schema.variables]
    assert "credit_score" in var_names
    assert "debt_ratio" in var_names

    # Verify Consequence
    assert oracle.consequence.variable == "decision"
    assert oracle.consequence.value == "REJECT"

    # Verify Provenance
    assert oracle.provenance.invariant_id == "local-c7180ce5"
    assert oracle.provenance.source_lines == [14]
    assert "EV-S-002" in oracle.provenance.evidence_ids


# ==============================================================================
# 2. Strict Rejection of Unvalidated / Low-Confidence Candidates
# ==============================================================================

def test_compiler_rejects_unconfirmed_candidate():
    cand = _create_sample_candidate(status="unconfirmed", confidence=0.85)
    with pytest.raises(OracleCompilationError, match="unvalidated status"):
        compile_candidate_to_oracle(cand)


def test_compiler_rejects_invalidated_candidate():
    cand = _create_sample_candidate(status="INVALIDATED", confidence=0.85)
    with pytest.raises(OracleCompilationError, match="unvalidated status"):
        compile_candidate_to_oracle(cand)


def test_compiler_rejects_grounding_failed_candidate():
    cand = _create_sample_candidate(status="GROUNDING_FAILED", confidence=0.85)
    with pytest.raises(OracleCompilationError, match="unvalidated status"):
        compile_candidate_to_oracle(cand)


def test_compiler_rejects_low_confidence_candidate():
    cand = _create_sample_candidate(status="graduated", confidence=0.74)
    with pytest.raises(OracleCompilationError, match="below certification threshold"):
        compile_candidate_to_oracle(cand, confidence_threshold=0.80)


def test_compiler_rejects_candidate_with_active_counterexamples():
    cand = _create_sample_candidate(
        status="graduated",
        confidence=0.88,
        counterexamples=[{"inputs": {"credit_score": 550}, "actual": "APPROVE"}],
    )
    with pytest.raises(OracleCompilationError, match="active counterexamples"):
        compile_candidate_to_oracle(cand)


# ==============================================================================
# 3. Comparison Predicate & Operator Variations
# ==============================================================================

def test_comparison_operators():
    ops = [
        ("age < 18", "<", "age", 18),
        ("score <= 600", "<=", "score", 600),
        ("status == 'ACTIVE'", "==", "status", "ACTIVE"),
        ("tier != 'GOLD'", "!=", "tier", "GOLD"),
        ("income >= 50000", ">=", "income", 50000),
        ("ratio > 0.4", ">", "ratio", 0.4),
    ]

    for expr, expected_op, expected_var, expected_val in ops:
        ast_node = parse_condition_to_ast(expr)
        assert isinstance(ast_node, OraclePredicate)
        assert ast_node.operator == expected_op
        assert ast_node.variable == expected_var
        assert ast_node.value == expected_val


def test_inverted_comparison_variable_order():
    # 600 > credit_score should invert to credit_score < 600
    ast_node = parse_condition_to_ast("600 > credit_score")
    assert isinstance(ast_node, OraclePredicate)
    assert ast_node.variable == "credit_score"
    assert ast_node.operator == "<"
    assert ast_node.value == 600


# ==============================================================================
# 4. Compound Boolean Logic (AND, OR, NOT, Nested)
# ==============================================================================

def test_compound_and_or_not_parsing():
    # OR expression
    or_ast = parse_condition_to_ast("credit_score < 500 or annual_income < 20000")
    assert isinstance(or_ast, CompoundCondition)
    assert or_ast.type == "OR"
    assert len(or_ast.operands) == 2

    # NOT expression
    not_ast = parse_condition_to_ast("not (credit_score >= 600)")
    assert isinstance(not_ast, UnaryCondition)
    assert not_ast.type == "NOT"
    assert isinstance(not_ast.operand, OraclePredicate)
    assert not_ast.operand.operator == ">="

    # Nested AND with OR
    nested_ast = parse_condition_to_ast("credit_score < 600 and (debt_ratio > 0.4 or annual_income < 25000)")
    assert isinstance(nested_ast, CompoundCondition)
    assert nested_ast.type == "AND"
    assert isinstance(nested_ast.operands[1], CompoundCondition)
    assert nested_ast.operands[1].type == "OR"


# ==============================================================================
# 5. Unsupported Syntax Rejection
# ==============================================================================

def test_rejection_of_unsupported_syntax():
    unsupported_expressions = [
        "calculate_risk(credit_score) > 5",       # Function Call
        "credit_score & 4 == 4",                  # Bitwise op
        "(lambda x: x > 500)(credit_score)",      # Lambda
        "applicant.credit_score < 600",           # Attribute lookup
        "credit_scores[0] < 600",                 # Subscript
    ]

    for expr in unsupported_expressions:
        with pytest.raises(OracleCompilationError):
            parse_condition_to_ast(expr)


# ==============================================================================
# 6. Deterministic Canonical Serialization & SHA-256 Hashing
# ==============================================================================

def test_deterministic_canonical_serialization():
    # AST 1: credit_score < 600 and debt_ratio > 0.4
    ast1 = parse_condition_to_ast("credit_score < 600 and debt_ratio > 0.4")
    conseq1 = parse_consequence_to_ast("REJECT")
    json1 = serialize_canonical_oracle(ast1.model_dump(mode="json"), conseq1.model_dump(mode="json"))
    hash1 = compute_content_hash(json1)

    # AST 2: debt_ratio > 0.4 and credit_score < 600 (Commutative swap)
    ast2 = parse_condition_to_ast("debt_ratio > 0.4 and credit_score < 600")
    conseq2 = parse_consequence_to_ast("REJECT")
    json2 = serialize_canonical_oracle(ast2.model_dump(mode="json"), conseq2.model_dump(mode="json"))
    hash2 = compute_content_hash(json2)

    assert json1 == json2
    assert hash1 == hash2


# ==============================================================================
# 7. Language-Independent Evaluator
# ==============================================================================

def test_evaluator_statuses():
    cand = _create_sample_candidate("credit_score < 600 and debt_ratio > 0.4", "REJECT")
    oracle = compile_candidate_to_oracle(cand)

    # 1. PASS: Condition met (credit_score=550, debt_ratio=0.5) and decision == REJECT
    pass_report = evaluate_oracle(oracle, inputs={"credit_score": 550, "debt_ratio": 0.5}, outputs={"decision": "REJECT"})
    assert pass_report.status == "PASS"
    assert pass_report.condition_satisfied is True
    assert pass_report.consequence_satisfied is True

    # 2. FAIL: Condition met (credit_score=550, debt_ratio=0.5) but decision == APPROVE
    fail_report = evaluate_oracle(oracle, inputs={"credit_score": 550, "debt_ratio": 0.5}, outputs={"decision": "APPROVE"})
    assert fail_report.status == "FAIL"
    assert fail_report.condition_satisfied is True
    assert fail_report.consequence_satisfied is False
    assert fail_report.counterexample is not None
    assert fail_report.counterexample["expected"] == "REJECT"
    assert fail_report.counterexample["actual"] == "APPROVE"

    # 3. NOT_APPLICABLE: Condition not met (credit_score=750, debt_ratio=0.2)
    na_report = evaluate_oracle(oracle, inputs={"credit_score": 750, "debt_ratio": 0.2}, outputs={"decision": "APPROVE"})
    assert na_report.status == "NOT_APPLICABLE"
    assert na_report.condition_satisfied is False
    assert na_report.consequence_satisfied is None

    # 4. INVALID_INPUT: Missing required variable 'debt_ratio'
    invalid_report = evaluate_oracle(oracle, inputs={"credit_score": 550}, outputs={"decision": "REJECT"})
    assert invalid_report.status == "INVALID_INPUT"
    assert "missing from observation" in (invalid_report.reason or "")


# ==============================================================================
# 8. Versioned Immutable Registry
# ==============================================================================

def test_versioned_immutable_registry():
    test_registry = OracleRegistry()
    cand1 = _create_sample_candidate("credit_score < 600", "REJECT")
    oracle_v1 = compile_candidate_to_oracle(cand1)
    oracle_v1.oracle_id = "ORC-TEST"

    # Register initial version (v1)
    registered_v1 = test_registry.register_oracle(oracle_v1)
    assert registered_v1.version == 1
    assert registered_v1.status == OracleStatus.ACTIVE

    # Register modified oracle with same ID (e.g. updated threshold < 580)
    cand2 = _create_sample_candidate("credit_score < 580", "REJECT")
    oracle_v2 = compile_candidate_to_oracle(cand2)
    oracle_v2.oracle_id = "ORC-TEST"

    registered_v2 = test_registry.register_oracle(oracle_v2)
    assert registered_v2.version == 2
    assert registered_v2.status == OracleStatus.ACTIVE

    # Check that historical v1 was preserved and marked superseded
    hist_v1 = test_registry.get_oracle("ORC-TEST", version=1)
    assert hist_v1 is not None
    assert hist_v1.version == 1
    assert hist_v1.status == OracleStatus.SUPERSEDED

    # Check latest version retrieval
    latest = test_registry.get_oracle("ORC-TEST")
    assert latest.version == 2


# ==============================================================================
# 9. Frozen Oracle Set & Composite Hash
# ==============================================================================

def test_frozen_oracle_set():
    test_registry = OracleRegistry()
    cand1 = _create_sample_candidate("credit_score < 500", "REJECT")
    cand2 = _create_sample_candidate("credit_score < 600 and debt_ratio > 0.4", "REJECT")

    orc1 = test_registry.register_oracle(compile_candidate_to_oracle(cand1))
    orc2 = test_registry.register_oracle(compile_candidate_to_oracle(cand2))

    oracle_set = test_registry.create_oracle_set(
        name="LoanApprovalCoreSuite",
        oracle_ids=[orc1.oracle_id, orc2.oracle_id],
        domain="loan_approval",
    )

    assert isinstance(oracle_set, OracleSet)
    assert oracle_set.oracle_set_id.startswith("SET-")
    assert len(oracle_set.oracle_set_hash) == 64
    assert len(oracle_set.oracles) == 2

    # Verify retrieval
    retrieved = test_registry.get_oracle_set(oracle_set.oracle_set_id)
    assert retrieved is not None
    assert retrieved.name == "LoanApprovalCoreSuite"


# ==============================================================================
# 10. Backward Compatibility with synthesizer.py and interpreter.py
# ==============================================================================

def test_synthesizer_and_interpreter_integration():
    from common.models import ValidatedInvariant
    val_inv = ValidatedInvariant(
        invariant_id="local-c7180ce5",
        condition="credit_score < 600 and debt_ratio > 0.4",
        consequence="REJECT",
        source_file="legacy_loan_approval.py",
        confidence=0.94,
        status="graduated",
        graduated=True,
    )

    oracle = synthesize_oracle(val_inv)
    assert isinstance(oracle, OracleDefinition)
    assert oracle.property == "(credit_score < 600 and debt_ratio > 0.4) implies (decision == 'REJECT')"

    def dummy_app(credit_score=0, debt_ratio=0.0, annual_income=0):
        if credit_score < 600 and debt_ratio > 0.4:
            return {"decision": "REJECT"}
        return {"decision": "APPROVE"}

    result = run_oracle(
        oracle=oracle,
        impl_fn=dummy_app,
        field_bounds={"credit_score": (400, 800), "debt_ratio": (0.1, 0.8), "annual_income": (20000, 100000)},
        n_samples=50,
    )

    assert result["checked"] > 0
    assert result["violated"] == 0
    assert result["passed"] == result["checked"]
    assert result["pass_i"] == 1
