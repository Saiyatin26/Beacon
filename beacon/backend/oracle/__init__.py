"""Phase 8 — Language-Independent Behavioral Oracle Subsystem.

Exports:
- Domain Models: OracleDefinition, OracleSet, OraclePredicate, CompoundCondition,
  UnaryCondition, OracleConsequence, OracleInputSchema, OracleOutputSchema,
  OracleProvenance, OracleStatus, OracleEvaluationReport, Oracle (alias)
- Compiler: compile_candidate_to_oracle, parse_condition_to_ast, parse_consequence_to_ast,
  OracleCompilationError, synthesize_oracle
- Evaluator: evaluate_oracle, evaluate_condition, run_oracle
- Serializer: serialize_canonical_oracle, compute_content_hash, compute_oracle_set_hash
- Registry: OracleRegistry, registry
"""

from .models import (
    CompoundCondition,
    Oracle,
    OracleConditionNode,
    OracleConsequence,
    OracleDefinition,
    OracleEvaluationReport,
    OracleInputSchema,
    OracleOutputSchema,
    OraclePredicate,
    OracleProvenance,
    OracleSet,
    OracleStatus,
    OracleVariable,
    UnaryCondition,
)
from .compiler import (
    OracleCompilationError,
    compile_candidate_to_oracle,
    parse_condition_to_ast,
    parse_consequence_to_ast,
)
from .serializer import (
    canonicalize_ast_dict,
    compute_content_hash,
    compute_oracle_set_hash,
    serialize_canonical_oracle,
)
from .evaluator import evaluate_condition, evaluate_oracle
from .registry import OracleRegistry, registry
from .synthesizer import synthesize_oracle
from .interpreter import run_oracle

__all__ = [
    "Oracle",
    "OracleDefinition",
    "OracleSet",
    "OracleStatus",
    "OraclePredicate",
    "CompoundCondition",
    "UnaryCondition",
    "OracleConditionNode",
    "OracleConsequence",
    "OracleVariable",
    "OracleInputSchema",
    "OracleOutputSchema",
    "OracleProvenance",
    "OracleEvaluationReport",
    "OracleCompilationError",
    "compile_candidate_to_oracle",
    "parse_condition_to_ast",
    "parse_consequence_to_ast",
    "serialize_canonical_oracle",
    "canonicalize_ast_dict",
    "compute_content_hash",
    "compute_oracle_set_hash",
    "evaluate_oracle",
    "evaluate_condition",
    "OracleRegistry",
    "registry",
    "synthesize_oracle",
    "run_oracle",
]
