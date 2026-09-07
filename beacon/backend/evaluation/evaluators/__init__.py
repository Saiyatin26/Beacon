"""BEACON V2 -- Phase 4 Modular Dimension Evaluators Package."""

from .output_evaluator import OutputEvaluator, output_evaluator
from .error_evaluator import ErrorEvaluator, error_evaluator
from .boundary_evaluator import BoundaryEvaluator, boundary_evaluator
from .state_evaluator import StateEvaluator, state_evaluator
from .workflow_evaluator import WorkflowEvaluator, workflow_evaluator
from .nonfunctional_evaluator import NonfunctionalEvaluator, nonfunctional_evaluator

# Alias: tests import as NonFunctionalEvaluator (capital F)
NonFunctionalEvaluator = NonfunctionalEvaluator

__all__ = [
    "OutputEvaluator",
    "output_evaluator",
    "ErrorEvaluator",
    "error_evaluator",
    "BoundaryEvaluator",
    "boundary_evaluator",
    "StateEvaluator",
    "state_evaluator",
    "WorkflowEvaluator",
    "workflow_evaluator",
    "NonfunctionalEvaluator",
    "nonfunctional_evaluator",
    "NonFunctionalEvaluator",
]
