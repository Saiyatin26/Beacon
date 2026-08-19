"""Phase 9 — Cross-Version Behavioral Equivalence Subsystem.

Exports:
- Models: Observation, CertificationTestInput, BehavioralRegression, ComparisonRecord,
  OracleEquivalenceMetrics, CrossVersionCertificationReport
- Adapters: ImplementationAdapter, FunctionAdapter, LegacyAdapter, ModernizedAdapter,
  default_input_normalizer, default_output_normalizer
- Input Generation & Replay: generate_certification_test_suite
- Certification Engine: CrossVersionCertificationEngine, certification_engine
- Runner & Scoring: certify, equivalence_score, domain_scores
"""

from .models import (
    BehavioralRegression,
    CertificationTestInput,
    ComparisonRecord,
    CrossVersionCertificationReport,
    Observation,
    OracleEquivalenceMetrics,
)
from .adapters import (
    FunctionAdapter,
    ImplementationAdapter,
    LegacyAdapter,
    ModernizedAdapter,
    default_input_normalizer,
    default_output_normalizer,
)
from .input_generator import generate_certification_test_suite
from .engine import CrossVersionCertificationEngine, certification_engine
from .runner import certify
from .scorer import domain_scores, equivalence_score

__all__ = [
    "Observation",
    "CertificationTestInput",
    "BehavioralRegression",
    "ComparisonRecord",
    "OracleEquivalenceMetrics",
    "CrossVersionCertificationReport",
    "ImplementationAdapter",
    "FunctionAdapter",
    "LegacyAdapter",
    "ModernizedAdapter",
    "default_input_normalizer",
    "default_output_normalizer",
    "generate_certification_test_suite",
    "CrossVersionCertificationEngine",
    "certification_engine",
    "certify",
    "equivalence_score",
    "domain_scores",
]
