"""BEACON V2 -- Phase 4 Comparison Policies and Tolerance Specifications.

Defines declarative, deterministic policies governing structural output comparison,
numeric tolerances, array order semantics, string matching, error categories,
state deltas, workflow traces, and nonfunctional limits.
"""

import hashlib
import json
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field


class OutputComparisonPolicy(BaseModel):
    """Configuration for evaluating output equivalence."""
    objects: Literal["structural"] = "structural"
    arrays: Literal["ordered", "unordered"] = "ordered"
    strings: Literal["exact", "normalized_whitespace", "case_insensitive"] = "exact"
    numbers: Literal["exact", "absolute_tolerance", "relative_tolerance"] = "exact"
    abs_tolerance: float = 0.0
    rel_tolerance: float = 0.0
    ignore_extra_fields: bool = False
    ignored_fields: list[str] = Field(default_factory=list)


class ErrorComparisonPolicy(BaseModel):
    """Configuration for evaluating error behavior equivalence."""
    compare_status: bool = True
    compare_code: bool = True
    compare_message: bool = True
    message_matching: Literal["exact", "normalized"] = "exact"
    ignored_fields: list[str] = Field(default_factory=list)


class BoundaryComparisonPolicy(BaseModel):
    """Configuration for evaluating behavior on boundary / edge inputs."""
    enabled: bool = True
    require_exact_status: bool = True


class StateComparisonPolicy(BaseModel):
    """Configuration for evaluating state and side-effect deltas."""
    compare_database: bool = True
    compare_filesystem: bool = True
    compare_http: bool = True
    ignore_row_order: bool = False
    ignored_tables: list[str] = Field(default_factory=list)


class WorkflowComparisonPolicy(BaseModel):
    """Configuration for evaluating observable execution sequences."""
    compare_sequence: bool = True
    sequence_matching: Literal["exact", "subsequence"] = "exact"
    filter_internal_events: bool = True


class NonfunctionalComparisonPolicy(BaseModel):
    """Configuration for nonfunctional metrics (duration, resource usage)."""
    enabled: bool = False
    max_duration_ratio: float = 2.0
    max_absolute_diff_ms: float = 5000.0


class FloatComparisonMode(str):
    """Explicit float comparison mode constants used in comparison policies."""
    EXACT = "exact"
    ABSOLUTE = "absolute_tolerance"
    RELATIVE = "relative_tolerance"


class ComparisonPolicy(BaseModel):
    """Declarative policy defining equivalence thresholds and rules across dimensions.

    Provides both:
    - Nested sub-policies (output_policy, error_policy, ...) for full control.
    - Flat convenience fields (float_tolerance, ignore_array_order, ignore_keys,
      max_latency_ratio) for concise single-field customization.
    """
    policy_id: str = "default_v2"
    version: str = "1.0.0"
    description: str = "Standard conservative V2 behavioral comparison policy"
    output_policy: OutputComparisonPolicy = Field(default_factory=OutputComparisonPolicy)
    error_policy: ErrorComparisonPolicy = Field(default_factory=ErrorComparisonPolicy)
    boundary_policy: BoundaryComparisonPolicy = Field(default_factory=BoundaryComparisonPolicy)
    state_policy: StateComparisonPolicy = Field(default_factory=StateComparisonPolicy)
    workflow_policy: WorkflowComparisonPolicy = Field(default_factory=WorkflowComparisonPolicy)
    nonfunctional_policy: NonfunctionalComparisonPolicy = Field(default_factory=NonfunctionalComparisonPolicy)

    # Flat convenience fields for concise policy construction.
    # float_tolerance: Absolute float comparison threshold (0.0 = exact).
    float_tolerance: float = 0.0
    # float_mode: FloatComparisonMode constant governing float comparison strategy.
    float_mode: str = FloatComparisonMode.ABSOLUTE
    # ignore_array_order: When True, arrays are compared without regard to ordering.
    ignore_array_order: bool = False
    # ignore_keys: List of field/key names to exclude from output comparison.
    ignore_keys: list[str] = Field(default_factory=list)
    # max_latency_ratio: Maximum acceptable target/reference latency ratio.
    #   If > 0, enables nonfunctional latency comparison regardless of nonfunctional_policy.enabled.
    max_latency_ratio: float = 0.0

    def compute_policy_hash(self) -> str:
        """Computes deterministic SHA-256 fingerprint of the policy configuration."""
        raw = self.model_dump()
        # Ensure lists are sorted for determinism (key order should not change hash)
        if "ignore_keys" in raw and isinstance(raw["ignore_keys"], list):
            raw["ignore_keys"] = sorted(raw["ignore_keys"])
        canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# Pre-defined deterministic policies
DEFAULT_COMPARISON_POLICY = ComparisonPolicy(
    policy_id="default_v2",
    version="1.0.0",
    description="Default conservative evaluation: ordered arrays, exact strings/numbers, strict errors (status+category), state verification",
    float_tolerance=1e-5,
    float_mode=FloatComparisonMode.ABSOLUTE,
    ignore_array_order=False,
    # Default error policy compares status and category, but NOT exact error message text
    error_policy=ErrorComparisonPolicy(
        compare_status=True,
        compare_code=True,
        compare_message=False,
        message_matching="normalized",
    ),
)

STRICT_COMPARISON_POLICY = ComparisonPolicy(
    policy_id="strict_v2",
    version="1.0.0",
    description="Strict evaluation: zero tolerance, no extra fields permitted, exact error matching",
    float_tolerance=0.0,
    float_mode=FloatComparisonMode.EXACT,
    ignore_array_order=False,
    output_policy=OutputComparisonPolicy(
        objects="structural",
        arrays="ordered",
        strings="exact",
        numbers="exact",
        abs_tolerance=0.0,
        rel_tolerance=0.0,
        ignore_extra_fields=False,
    ),
    error_policy=ErrorComparisonPolicy(
        compare_status=True,
        compare_code=True,
        compare_message=True,
        message_matching="exact",
    ),
    state_policy=StateComparisonPolicy(
        compare_database=True,
        compare_filesystem=True,
        compare_http=True,
        ignore_row_order=False,
    ),
)

RELAXED_COMPARISON_POLICY = ComparisonPolicy(
    policy_id="relaxed_v2",
    version="1.0.0",
    description="Relaxed evaluation: unordered arrays permitted, small numeric tolerance, normalized error strings",
    float_tolerance=1e-2,
    float_mode=FloatComparisonMode.ABSOLUTE,
    ignore_array_order=True,
    output_policy=OutputComparisonPolicy(
        objects="structural",
        arrays="unordered",
        strings="normalized_whitespace",
        numbers="absolute_tolerance",
        abs_tolerance=0.001,
        ignore_extra_fields=True,
    ),
    error_policy=ErrorComparisonPolicy(
        compare_status=True,
        compare_code=True,
        compare_message=True,
        message_matching="normalized",
    ),
    state_policy=StateComparisonPolicy(
        compare_database=True,
        compare_filesystem=True,
        compare_http=True,
        ignore_row_order=True,
    ),
)

POLICY_REGISTRY: dict[str, ComparisonPolicy] = {
    "default_v2": DEFAULT_COMPARISON_POLICY,
    "strict_v2": STRICT_COMPARISON_POLICY,
    "relaxed_v2": RELAXED_COMPARISON_POLICY,
}


def resolve_comparison_policy(
    policy_spec: Optional[Union[ComparisonPolicy, dict[str, Any], str]] = None
) -> ComparisonPolicy:
    """Resolves policy from policy instance, dict, or named identifier, falling back to default."""
    if policy_spec is None:
        return DEFAULT_COMPARISON_POLICY

    if isinstance(policy_spec, ComparisonPolicy):
        return policy_spec

    if isinstance(policy_spec, str):
        if policy_spec in POLICY_REGISTRY:
            return POLICY_REGISTRY[policy_spec]
        # Return default if unknown name
        return DEFAULT_COMPARISON_POLICY

    if isinstance(policy_spec, dict):
        try:
            return ComparisonPolicy(**policy_spec)
        except Exception:
            return DEFAULT_COMPARISON_POLICY

    return DEFAULT_COMPARISON_POLICY


def get_builtin_policy(policy_id: str) -> Optional[ComparisonPolicy]:
    """Returns a named built-in policy by ID, or None if not found."""
    return POLICY_REGISTRY.get(policy_id)


def list_builtin_policies() -> list[ComparisonPolicy]:
    """Returns all registered built-in comparison policies."""
    return list(POLICY_REGISTRY.values())
