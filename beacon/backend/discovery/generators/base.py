"""BEACON V2 — Phase 6 Base Candidate Generator.

Defines the protocol and helper methods for domain-agnostic candidate rule generators.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional
from ..models import (
    CandidateValidationStatus,
    DiscoveredCandidate,
    DiscoveryMethod,
    DiscoveryPolicy,
    ObservationFact,
)


class BaseCandidateGenerator(ABC):
    """Abstract base class for all candidate rule and invariant generators."""

    generator_name: str = "base_generator"
    discovery_method: DiscoveryMethod = DiscoveryMethod.DIRECT_RELATION

    @abstractmethod
    def generate_candidates(
        self,
        facts: list[ObservationFact],
        policy: DiscoveryPolicy,
        role_scope: str = "reference",
    ) -> list[DiscoveredCandidate]:
        """Proposes candidate hypotheses based on observed facts for the given role scope."""
        pass
