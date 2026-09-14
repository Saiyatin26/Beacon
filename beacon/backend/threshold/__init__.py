"""BEACON V2 — Phase 8 Dynamic / Evidence-Driven Thresholds & Behavioral Evaluation Package.

Provides models, engines, evaluators, and persistence for evidence-driven,
deterministic, bounded, and auditable threshold resolution and advanced
behavioral evaluation.
"""

from threshold.models import (
    DifferenceMetric,
    EstimatorType,
    OutlierPolicy,
    ThresholdPolicy,
    ThresholdResolution,
    ThresholdStatus,
    ThresholdStrategy,
    AdvancedEvaluationRequest,
    AdvancedEvaluationResult,
)
from threshold.engine import (
    ThresholdEngine,
    ThresholdResolver,
    threshold_engine,
    threshold_resolver,
)
from threshold.evaluator import (
    AdvancedBehavioralEvaluator,
    advanced_evaluator,
)
from threshold.persistence import (
    ThresholdPersistenceStore,
    threshold_persistence,
)

__all__ = [
    "DifferenceMetric",
    "EstimatorType",
    "OutlierPolicy",
    "ThresholdPolicy",
    "ThresholdResolution",
    "ThresholdStatus",
    "ThresholdStrategy",
    "AdvancedEvaluationRequest",
    "AdvancedEvaluationResult",
    "ThresholdEngine",
    "ThresholdResolver",
    "threshold_engine",
    "threshold_resolver",
    "AdvancedBehavioralEvaluator",
    "advanced_evaluator",
    "ThresholdPersistenceStore",
    "threshold_persistence",
]
