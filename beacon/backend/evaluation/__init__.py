"""BEACON V2 — Phase 4 Behavioral Equivalence Evaluation Engine.

Provides domain-agnostic, deterministic, policy-driven behavioral equivalence evaluation
across six dimensions (Output, Error, Boundary, State, Workflow, Nonfunctional).
"""

from .engine import BehavioralEvaluationEngine, behavioral_evaluation_engine
from .evaluators import (
    BoundaryEvaluator,
    ErrorEvaluator,
    NonfunctionalEvaluator,
    OutputEvaluator,
    StateEvaluator,
    WorkflowEvaluator,
    boundary_evaluator,
    error_evaluator,
    nonfunctional_evaluator,
    output_evaluator,
    state_evaluator,
    workflow_evaluator,
)
from .input_adapter import CorrelatedInputItem, EvaluationInputAdapter, evaluation_input_adapter
from .models import (
    BehaviorDifference,
    BehaviorDimension,
    DifferenceType,
    DimensionEvaluationSummary,
    DimensionResult,
    EvaluationResult,
    EvaluationSummary,
    EvaluationVerdict,
    InputEvaluationResult,
)
from .policies import (
    DEFAULT_COMPARISON_POLICY,
    RELAXED_COMPARISON_POLICY,
    STRICT_COMPARISON_POLICY,
    BoundaryComparisonPolicy,
    ComparisonPolicy,
    ErrorComparisonPolicy,
    FloatComparisonMode,
    NonfunctionalComparisonPolicy,
    OutputComparisonPolicy,
    StateComparisonPolicy,
    WorkflowComparisonPolicy,
    get_builtin_policy,
    list_builtin_policies,
    resolve_comparison_policy,
)
from .reporting import generate_json_report, generate_markdown_report

__all__ = [
    # Core Engine
    "BehavioralEvaluationEngine",
    "behavioral_evaluation_engine",
    # Models
    "BehaviorDimension",
    "DifferenceType",
    "EvaluationVerdict",
    "BehaviorDifference",
    "DimensionResult",
    "DimensionEvaluationSummary",
    "InputEvaluationResult",
    "EvaluationSummary",
    "EvaluationResult",
    # Policies
    "ComparisonPolicy",
    "OutputComparisonPolicy",
    "ErrorComparisonPolicy",
    "StateComparisonPolicy",
    "WorkflowComparisonPolicy",
    "BoundaryComparisonPolicy",
    "NonfunctionalComparisonPolicy",
    "DEFAULT_COMPARISON_POLICY",
    "STRICT_COMPARISON_POLICY",
    "RELAXED_COMPARISON_POLICY",
    "FloatComparisonMode",
    "get_builtin_policy",
    "list_builtin_policies",
    "resolve_comparison_policy",
    # Input Adapter
    "CorrelatedInputItem",
    "EvaluationInputAdapter",
    "evaluation_input_adapter",
    # Reporting
    "generate_markdown_report",
    "generate_json_report",
    # Evaluators
    "OutputEvaluator",
    "ErrorEvaluator",
    "BoundaryEvaluator",
    "StateEvaluator",
    "WorkflowEvaluator",
    "NonfunctionalEvaluator",
    "NonFunctionalEvaluator",
    "output_evaluator",
    "error_evaluator",
    "boundary_evaluator",
    "state_evaluator",
    "workflow_evaluator",
    "nonfunctional_evaluator",
]
