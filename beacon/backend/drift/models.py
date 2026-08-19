"""Phase 10 — Post-Migration Drift Monitoring Foundation Domain Models.

Defines drift observation models, evaluation statuses, drift events, and drift policies.
"""

from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class DriftStatus(str, Enum):
    """Evaluation status for a post-migration runtime observation."""
    NORMAL = "NORMAL"
    ORACLE_VIOLATION = "ORACLE_VIOLATION"
    UNCOVERED_INPUT = "UNCOVERED_INPUT"
    INVALID_INPUT = "INVALID_INPUT"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class DriftObservation(BaseModel):
    """Post-migration production or staging runtime observation."""
    observation_id: str
    timestamp: str = ""
    environment: str = "production"
    application_version: str = "2.0.0"
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    provenance: dict[str, Any] = Field(default_factory=dict)


class DriftPolicy(BaseModel):
    """Policy configuring drift alerting thresholds and oracle evaluation rules."""
    policy_id: str = "DRIFT-POL-DEFAULT"
    name: str = "Standard Drift Policy"
    alert_on_critical_violation: bool = True
    alert_on_any_violation: bool = False
    max_allowed_violation_rate: float = 0.01  # 1%
    min_observations_for_alert: int = 10


class DriftEvent(BaseModel):
    """Evaluated outcome of a single post-migration observation against a frozen OracleSet."""
    event_id: str
    observation_id: str
    timestamp: str
    oracle_set_id: str
    oracle_set_hash: str
    certification_id: Optional[str] = None
    status: DriftStatus
    violated_oracle_ids: list[str] = Field(default_factory=list)
    applicable_oracle_ids: list[str] = Field(default_factory=list)
    evaluation_details: list[dict[str, Any]] = Field(default_factory=list)
    alert_triggered: bool = False
    reason: Optional[str] = None
