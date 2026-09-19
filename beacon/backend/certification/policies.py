"""BEACON V2 — Certification Threshold Policy Abstractions.

Defines the threshold evaluation policy interface supporting both deterministic
StaticThresholdPolicy (current standard) and DynamicThresholdPolicy extension points.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional
from pydantic import BaseModel, Field

from .models import CertificationPolicy, CertificationStatus


class ThresholdPolicy(ABC):
    """Abstract base class for equivalence certification decision policies."""

    @abstractmethod
    def evaluate_status(
        self,
        equivalence_score: float,
        regression_count: int,
        oracle_coverage: float,
        reference_inconsistent_count: int = 0,
        has_critical_regression: bool = False,
    ) -> CertificationStatus:
        """Determines certification status outcome based on evaluation metrics."""
        pass

    @abstractmethod
    def get_policy_summary(self) -> dict[str, Any]:
        """Returns structured metadata of threshold rules."""
        pass


class StaticThresholdPolicy(ThresholdPolicy, BaseModel):
    """Deterministic static threshold policy (BEACON V1/V2 baseline standard)."""
    policy_id: str = "POL-STATIC-DEFAULT"
    name: str = "Strict Equivalence Static Policy"
    version: int = 1
    min_equivalence_score: float = 0.999
    min_oracle_coverage: float = 0.80
    allow_warnings: bool = False
    block_on_critical_regression: bool = True
    block_on_reference_inconsistent: bool = True

    def evaluate_status(
        self,
        equivalence_score: float,
        regression_count: int,
        oracle_coverage: float,
        reference_inconsistent_count: int = 0,
        has_critical_regression: bool = False,
    ) -> CertificationStatus:
        if self.block_on_reference_inconsistent and reference_inconsistent_count > 0:
            return CertificationStatus.REFERENCE_INCONSISTENT

        if self.block_on_critical_regression and has_critical_regression:
            return CertificationStatus.NOT_CERTIFIED

        if oracle_coverage < self.min_oracle_coverage:
            return CertificationStatus.INSUFFICIENT_COVERAGE

        if regression_count > 0 or equivalence_score < self.min_equivalence_score:
            if self.allow_warnings and regression_count == 0 and equivalence_score >= (self.min_equivalence_score - 0.05):
                return CertificationStatus.CERTIFIED_WITH_WARNINGS
            return CertificationStatus.NOT_CERTIFIED

        return CertificationStatus.CERTIFIED

    def get_policy_summary(self) -> dict[str, Any]:
        return {
            "policy_type": "StaticThresholdPolicy",
            "policy_id": self.policy_id,
            "min_equivalence_score": self.min_equivalence_score,
            "min_oracle_coverage": self.min_oracle_coverage,
            "allow_warnings": self.allow_warnings,
            "block_on_critical_regression": self.block_on_critical_regression,
            "block_on_reference_inconsistent": self.block_on_reference_inconsistent,
        }


class DynamicThresholdPolicy(ThresholdPolicy, BaseModel):
    """Extension point for future evidence-driven dynamic threshold adaptation.
    
    In Phase 1, provides a structured contract with customizable confidence margins.
    Full dynamic deriving algorithm is deferred to later phases.
    """
    policy_id: str = "POL-DYNAMIC-EXTENSION"
    name: str = "Dynamic Evidence-Adaptive Policy (Extension Point)"
    version: int = 1
    base_equivalence_score: float = 0.95
    confidence_margin: float = 0.03
    min_oracle_coverage: float = 0.75
    allow_warnings: bool = True

    def evaluate_status(
        self,
        equivalence_score: float,
        regression_count: int,
        oracle_coverage: float,
        reference_inconsistent_count: int = 0,
        has_critical_regression: bool = False,
    ) -> CertificationStatus:
        if reference_inconsistent_count > 0:
            return CertificationStatus.REFERENCE_INCONSISTENT
        if has_critical_regression:
            return CertificationStatus.NOT_CERTIFIED
        if oracle_coverage < self.min_oracle_coverage:
            return CertificationStatus.INSUFFICIENT_COVERAGE

        effective_threshold = max(0.80, self.base_equivalence_score - self.confidence_margin)
        if equivalence_score >= self.base_equivalence_score and regression_count == 0:
            return CertificationStatus.CERTIFIED
        elif equivalence_score >= effective_threshold and self.allow_warnings:
            return CertificationStatus.CERTIFIED_WITH_WARNINGS
        return CertificationStatus.NOT_CERTIFIED

    def get_policy_summary(self) -> dict[str, Any]:
        return {
            "policy_type": "DynamicThresholdPolicy",
            "policy_id": self.policy_id,
            "base_equivalence_score": self.base_equivalence_score,
            "confidence_margin": self.confidence_margin,
            "min_oracle_coverage": self.min_oracle_coverage,
            "allow_warnings": self.allow_warnings,
        }


class CertificationPolicyResolver:
    """Backend-authoritative resolver for deterministic certification policies.
    
    Ensures certification authority is strictly governed by verified backend configuration,
    preventing callers from manipulating certification boundaries.
    """

    def resolve_effective_policy(
        self,
        application_id: str,
        evaluation_mode: str = "CONTROLLED",
        configured_policy: Optional[dict[str, Any]] = None,
    ) -> CertificationPolicy:
        """Deterministically derives the effective certification policy."""
        # 1. Base policy configuration derived from evaluation mode
        if evaluation_mode in ("FULL", "FULL_BEACON"):
            base_min_score = 0.99
            base_min_coverage = 0.70
            allow_warn = False
        else:  # CONTROLLED default
            base_min_score = 0.999
            base_min_coverage = 0.0  # Controlled mode exercises discovered/reconciled rules directly
            allow_warn = False

        # 2. Allow server-side configured overrides if valid
        if configured_policy and isinstance(configured_policy, dict):
            min_score = float(configured_policy.get("min_equivalence_score", base_min_score))
            min_cov = float(configured_policy.get("min_oracle_coverage", base_min_coverage))
            allow_warn = bool(configured_policy.get("allow_warnings", allow_warn))
            comp_pol = str(configured_policy.get("comparison_policy", "default_v2"))
            metric = str(configured_policy.get("threshold_metric", "ABSOLUTE_DIFF"))
        else:
            min_score = base_min_score
            min_cov = base_min_coverage
            comp_pol = "default_v2"
            metric = "ABSOLUTE_DIFF"

        pol = CertificationPolicy(
            policy_id=f"POL-{application_id}",
            version=1,
            name=f"Authoritative Policy for {application_id} ({evaluation_mode})",
            min_equivalence_score=min_score,
            min_oracle_coverage=min_cov,
            min_applicable_probes_per_oracle=0,
            allow_warnings=allow_warn,
            block_on_critical_regression=True,
            block_on_reference_inconsistent=True,
            block_on_mutual_violation=True,
            comparison_policy=comp_pol,
            threshold_metric=metric,
            evaluation_mode=evaluation_mode,
        )
        pol.policy_hash = pol.compute_hash()
        pol.policy_fingerprint = pol.policy_hash
        return pol


certification_policy_resolver = CertificationPolicyResolver()

