"""Phase 8 — Language-Independent Behavioral Oracle Domain Models and AST.

Defines the canonical, language-independent Oracle DSL:
- Condition AST nodes (Comparisons, AND, OR, NOT)
- Consequence Assertion AST
- Input / Output Schemas
- Provenance & Versioning Metadata
- Oracle Definition & Frozen Oracle Sets
- Evaluation Result Reports
"""

from enum import Enum
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field


class OracleStatus(str, Enum):
    """Lifecycle status of a versioned oracle."""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    SUPERSEDED = "superseded"
    INACTIVE = "inactive"


# ==============================================================================
# 1. Oracle Condition AST Nodes
# ==============================================================================

class OraclePredicate(BaseModel):
    """Leaf node in condition AST representing a binary comparison."""
    model_config = {"frozen": True, "protected_namespaces": ()}
    type: Literal["comparison"] = "comparison"
    variable: str
    operator: Literal["<", "<=", "==", "!=", ">=", ">"]
    value: Union[int, float, str, bool]


class CompoundCondition(BaseModel):
    """Branch node representing logical AND / OR combinations."""
    model_config = {"frozen": True, "protected_namespaces": ()}
    type: Literal["AND", "OR"]
    operands: list[Union[OraclePredicate, "CompoundCondition", "UnaryCondition"]]


class UnaryCondition(BaseModel):
    """Branch node representing logical NOT inversion."""
    model_config = {"frozen": True, "protected_namespaces": ()}
    type: Literal["NOT"] = "NOT"
    operand: Union[OraclePredicate, "CompoundCondition", "UnaryCondition"]


# Allow recursive definitions in Pydantic
CompoundCondition.model_rebuild()
UnaryCondition.model_rebuild()

OracleConditionNode = Union[OraclePredicate, CompoundCondition, UnaryCondition]


# ==============================================================================
# 2. Consequence & Schema Models
# ==============================================================================

class OracleConsequence(BaseModel):
    """Asserts expected output variable value when condition evaluates to True."""
    model_config = {"frozen": True, "protected_namespaces": ()}
    type: Literal["comparison"] = "comparison"
    variable: str = "decision"
    operator: Literal["=="] = "=="
    value: Union[str, int, float, bool]


class OracleVariable(BaseModel):
    """Describes a single input parameter expected by the Oracle."""
    model_config = {"frozen": True, "protected_namespaces": ()}
    name: str
    var_type: Literal["int", "float", "str", "bool", "unknown"] = "unknown"
    min_value: Optional[float] = None
    max_value: Optional[float] = None


class OracleInputSchema(BaseModel):
    """Input parameters required to evaluate the oracle condition."""
    model_config = {"frozen": True, "protected_namespaces": ()}
    variables: list[OracleVariable] = Field(default_factory=list)


class OracleOutputSchema(BaseModel):
    """Output attributes produced by the target function to check against consequence."""
    model_config = {"frozen": True, "protected_namespaces": ()}
    variable: str = "decision"
    var_type: str = "str"
    allowed_values: Optional[list[Any]] = None


# ==============================================================================
# 3. Provenance & Full Oracle Definition
# ==============================================================================

class OracleProvenance(BaseModel):
    """Complete audit provenance linking oracle back to evidence and validation run."""
    model_config = {"frozen": True, "protected_namespaces": ()}
    invariant_id: str
    source_file: str
    source_lines: list[int] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    execution_ids: list[str] = Field(default_factory=list)
    validation_run_id: Optional[str] = None
    confidence: float
    severity: str
    domain: str = "business_logic"
    generation_method: str = "offline"
    generation_timestamp: str = ""
    reproducibility: dict[str, Any] = Field(default_factory=dict)


class OracleDefinition(BaseModel):
    """Canonical, Language-Independent Executable Behavioral Oracle."""
    model_config = {"frozen": True, "protected_namespaces": ()}

    oracle_id: str
    version: int = 1
    invariant_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    domain: str = "business_logic"
    severity: str = "medium"
    condition: OracleConditionNode
    consequence: OracleConsequence
    input_schema: OracleInputSchema
    output_schema: OracleOutputSchema
    provenance: OracleProvenance
    raw_condition: str
    canonical_condition: str
    canonical_json: str = ""
    content_hash: str = ""  # SHA-256 over deterministic canonical JSON
    status: OracleStatus = OracleStatus.ACTIVE
    created_at: str = ""

    # Backward compatibility attributes with Phase 1-5 legacy Oracle model
    property: str = ""
    inputs: list[str] = Field(default_factory=list)
    tolerance: float = 0.0
    confidence: float = 0.0


# Backward compatibility alias
Oracle = OracleDefinition


# ==============================================================================
# 4. Frozen Oracle Set
# ==============================================================================

class OracleSet(BaseModel):
    """Frozen, immutable collection of executable oracles for certification runs."""
    model_config = {"frozen": True, "protected_namespaces": ()}

    oracle_set_id: str
    name: str
    version: int = 1
    domain: str = "default"
    oracle_ids: list[str] = Field(default_factory=list)
    oracles: list[OracleDefinition] = Field(default_factory=list)
    oracle_set_hash: str = ""  # SHA-256 over sorted oracle content hashes
    created_at: str = ""


# ==============================================================================
# 5. Evaluation Report
# ==============================================================================

class OracleEvaluationReport(BaseModel):
    """Outcome of evaluating a single language-independent Oracle against an observation."""
    oracle_id: str
    status: Literal["PASS", "FAIL", "NOT_APPLICABLE", "INVALID_INPUT", "EVALUATION_ERROR"]
    condition_satisfied: bool
    consequence_satisfied: Optional[bool] = None
    inputs_observed: dict[str, Any] = Field(default_factory=dict)
    outputs_observed: dict[str, Any] = Field(default_factory=dict)
    reason: Optional[str] = None
    counterexample: Optional[dict[str, Any]] = None
