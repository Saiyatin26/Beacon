"""BEACON V2 — Phase 6 Behavioral Rule & Invariant Discovery Module.

Exports data models, observation matrix builder, discovery policies, and master discovery engine.
"""

from .engine import RuleDiscoveryEngine, rule_discovery_engine
from .matrix import ObservationMatrixBuilder, normalize_capture_status, observation_matrix_builder
from .models import (
    CandidateValidationStatus,
    DiscoveredCandidate,
    DiscoveredRuleType,
    DiscoveryDiagnostic,
    DiscoveryMethod,
    DiscoveryPolicy,
    DiscoveryResult,
    ObservationFact,
    ObservationMatrix,
    compute_deterministic_hash,
)
from .normalizer import CandidateNormalizer, candidate_normalizer
from .persistence import DiscoveryPersistenceError, DiscoveryPersistenceStore, discovery_persistence
from .ranking import CandidateRanker, candidate_ranker
from .validator import CandidateValidator, candidate_validator

__all__ = [
    "RuleDiscoveryEngine",
    "rule_discovery_engine",
    "ObservationMatrixBuilder",
    "observation_matrix_builder",
    "normalize_capture_status",
    "DiscoveredRuleType",
    "CandidateValidationStatus",
    "DiscoveryDiagnostic",
    "DiscoveryMethod",
    "DiscoveryPolicy",
    "DiscoveredCandidate",
    "ObservationFact",
    "ObservationMatrix",
    "DiscoveryResult",
    "compute_deterministic_hash",
    "CandidateNormalizer",
    "candidate_normalizer",
    "CandidateValidator",
    "candidate_validator",
    "CandidateRanker",
    "candidate_ranker",
    "DiscoveryPersistenceStore",
    "DiscoveryPersistenceError",
    "discovery_persistence",
]
