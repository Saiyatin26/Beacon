"""BEACON V2 — Phase 5: Business-Rule Understanding + Controlled Mode.

Provides domain-agnostic business rule representation, AST condition evaluation,
deterministic rule assessment, versioned persistence, and Controlled Mode coordination.
"""

from .engine import ControlledAssessmentEngine, controlled_assessment_engine
from .evaluator import RuleConditionEvaluator, rule_condition_evaluator
from .models import (
    BusinessRule,
    CompoundRuleCondition,
    ControlledEvaluationResult,
    ControlledEvaluationSummary,
    ExpectedBehavior,
    ExpectedBehaviorType,
    RuleAssessment,
    RuleComplianceVerdict,
    RuleConditionNode,
    RuleOperator,
    RulePredicate,
    RuleSeverity,
    RuleSource,
    RuleStatus,
    UnaryRuleCondition,
)
from .normalizer import RuleNormalizer, rule_normalizer
from .registry import RuleRegistry, rule_registry
from .validator import RuleValidationError, RuleValidator, rule_validator

__all__ = [
    "BusinessRule",
    "RuleOperator",
    "RuleConditionNode",
    "RulePredicate",
    "CompoundRuleCondition",
    "UnaryRuleCondition",
    "ExpectedBehavior",
    "ExpectedBehaviorType",
    "RuleComplianceVerdict",
    "RuleStatus",
    "RuleSource",
    "RuleSeverity",
    "RuleAssessment",
    "ControlledEvaluationResult",
    "ControlledEvaluationSummary",
    "RuleValidator",
    "RuleValidationError",
    "rule_validator",
    "RuleNormalizer",
    "rule_normalizer",
    "RuleConditionEvaluator",
    "rule_condition_evaluator",
    "ControlledAssessmentEngine",
    "controlled_assessment_engine",
    "RuleRegistry",
    "rule_registry",
]
