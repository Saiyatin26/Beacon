"""BEACON V2 — Phase 5 Business Rule & Controlled Mode Domain Models.

Defines generic, domain-independent representations for business rules, AST conditions,
expected behaviors, assessment results, and controlled evaluation summaries.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field

from evaluation.models import BehaviorDimension, EvaluationVerdict


class RuleOperator(str, Enum):
    """Generic relational, collection, and existence comparison operators."""
    EQ = "EQ"              # ==
    NE = "NE"              # !=
    GT = "GT"              # >
    GTE = "GTE"            # >=
    LT = "LT"              # <
    LTE = "LTE"            # <=
    IN = "IN"              # in list/set
    NOT_IN = "NOT_IN"      # not in list/set
    CONTAINS = "CONTAINS"  # substring or element in collection
    NOT_CONTAINS = "NOT_CONTAINS"
    IS_NULL = "IS_NULL"
    IS_NOT_NULL = "IS_NOT_NULL"
    EXISTS = "EXISTS"      # field exists in payload
    NOT_EXISTS = "NOT_EXISTS"


class RuleStatus(str, Enum):
    """Lifecycle status of a business rule."""
    DRAFT = "DRAFT"
    VALID = "VALID"
    INVALID = "INVALID"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class RuleSource(str, Enum):
    """Explicit origin of the business rule."""
    USER_DEFINED = "USER_DEFINED"
    CONFIGURATION = "CONFIGURATION"
    IMPORTED = "IMPORTED"
    SYSTEM_METADATA = "SYSTEM_METADATA"


class RuleSeverity(str, Enum):
    """Severity or criticality level of a rule."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class ExpectedBehaviorType(str, Enum):
    """Generic behavioral expectation categories."""
    ACCEPT = "ACCEPT"                    # Execution succeeds without error (e.g., exit_code=0, http_status < 400)
    REJECT = "REJECT"                    # Execution explicitly rejected/fails with error
    ERROR = "ERROR"                      # Specific error code/category/status is produced
    RETURN_VALUE = "RETURN_VALUE"        # Specific output field matches expected value
    RETURN_STATUS = "RETURN_STATUS"      # Specific HTTP status code or exit code returned
    STATE_CHANGE = "STATE_CHANGE"        # Observable state mutation occurred
    NO_STATE_CHANGE = "NO_STATE_CHANGE"  # No observable state mutation occurred
    WORKFLOW_STEP = "WORKFLOW_STEP"      # Specific event or stage present in workflow trace


class RuleComplianceVerdict(str, Enum):
    """Assessment verdict of an observed behavior against a business rule."""
    PASS = "PASS"                        # Observed behavior strictly satisfies the expected behavior
    FAIL = "FAIL"                        # Observed behavior violates the expected behavior
    INCONCLUSIVE = "INCONCLUSIVE"        # Insufficient or partial evidence to assess compliance
    NOT_APPLICABLE = "NOT_APPLICABLE"    # Rule condition was not triggered for this input
    ERROR = "ERROR"                      # Rule evaluation failed due to invalid rule, bad types, or schema error


# ==============================================================================
# Condition AST Nodes
# ==============================================================================

class RulePredicate(BaseModel):
    """Leaf node representing a single atomic condition on an observation field."""
    field: str
    operator: RuleOperator
    value: Optional[Any] = None
    field_source: Literal["input", "output", "state", "error", "metadata", "auto"] = "auto"
    value_type: Optional[str] = None


class CompoundRuleCondition(BaseModel):
    """Branch node representing logical composition (AND / OR)."""
    logical_op: Literal["AND", "OR"]
    operands: list[Union[RulePredicate, "CompoundRuleCondition", "UnaryRuleCondition"]]


class UnaryRuleCondition(BaseModel):
    """Branch node representing logical inversion (NOT)."""
    logical_op: Literal["NOT"] = "NOT"
    operand: Union[RulePredicate, CompoundRuleCondition, "UnaryRuleCondition"]


# Rebuild recursive Pydantic models
CompoundRuleCondition.model_rebuild()
UnaryRuleCondition.model_rebuild()

RuleConditionNode = Union[RulePredicate, CompoundRuleCondition, UnaryRuleCondition]


# ==============================================================================
# Expected Behavior Model
# ==============================================================================

class ExpectedBehavior(BaseModel):
    """Defines what behavioral outcome is expected when the rule condition holds."""
    behavior_type: ExpectedBehaviorType = ExpectedBehaviorType.ACCEPT
    target_field: Optional[str] = None
    expected_value: Optional[Any] = None
    expected_status_code: Optional[int] = None
    expected_error_code: Optional[str] = None
    expected_state_mutation: Optional[bool] = None
    expected_workflow_event: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)


# ==============================================================================
# Canonical Business Rule Model
# ==============================================================================

class BusinessRule(BaseModel):
    """Generic, domain-independent representation of a user-defined business rule."""
    rule_id: str
    name: str
    description: Optional[str] = None
    version: int = 1
    source: RuleSource = RuleSource.USER_DEFINED
    condition: RuleConditionNode
    expected_behavior: ExpectedBehavior = Field(default_factory=ExpectedBehavior)
    scope: Optional[str] = "global"
    referenced_fields: list[str] = Field(default_factory=list)
    referenced_dimensions: list[BehaviorDimension] = Field(default_factory=list)
    severity: RuleSeverity = RuleSeverity.MEDIUM
    status: RuleStatus = RuleStatus.ACTIVE
    fingerprint: str = ""
    natural_language_text: Optional[str] = None
    interpretation_metadata: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def compute_fingerprint(self) -> str:
        """Computes deterministic SHA-256 fingerprint over canonical rule representation."""
        from .normalizer import rule_normalizer
        return rule_normalizer.compute_rule_fingerprint(self)


# ==============================================================================
# Assessment Models
# ==============================================================================

class RuleAssessment(BaseModel):
    """Detailed result of assessing a single business rule against an input execution."""
    assessment_id: str
    rule_id: str
    rule_name: str
    rule_version: int
    rule_fingerprint: str
    input_id: str
    applicability: Literal["APPLICABLE", "NOT_APPLICABLE", "UNKNOWN"]
    condition_satisfied: bool
    reference_compliance: RuleComplianceVerdict
    target_compliance: RuleComplianceVerdict
    overall_rule_status: RuleComplianceVerdict
    behavioral_equivalence: Optional[EvaluationVerdict] = None
    reference_evidence_ids: list[str] = Field(default_factory=list)
    target_evidence_ids: list[str] = Field(default_factory=list)
    phase4_evaluation_id: Optional[str] = None
    explanation: str = ""
    observed_values: dict[str, Any] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)


class ControlledEvaluationSummary(BaseModel):
    """Aggregated summary metrics across all rule assessments in a controlled evaluation."""
    total_rules_evaluated: int
    applicable_rule_count: int
    not_applicable_rule_count: int
    passed_rule_count: int
    failed_rule_count: int
    inconclusive_rule_count: int
    error_rule_count: int
    overall_compliance_verdict: RuleComplianceVerdict
    rules_summary_by_id: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ControlledEvaluationResult(BaseModel):
    """Complete, audit-ready result of a Controlled Mode evaluation session."""
    evaluation_id: str
    bundle_id: Optional[str] = None
    application_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    overall_verdict: RuleComplianceVerdict
    summary: ControlledEvaluationSummary
    rule_assessments: list[RuleAssessment] = Field(default_factory=list)
    evaluation_fingerprint: str = ""
    rules_evaluated: list[BusinessRule] = Field(default_factory=list)
    phase4_evaluation_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
