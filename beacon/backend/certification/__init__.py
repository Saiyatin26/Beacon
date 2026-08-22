"""Phase 10 — Quantified Behavioral Equivalence Certification Subsystem.

Exports:
- Models: Observation, CertificationTestInput, BehavioralRegression, ComparisonRecord,
  OracleEquivalenceMetrics, CrossVersionCertificationReport, CertificationStatus,
  CertificationPolicy, PerOracleCertificationSummary, CertificationMetrics, CertificationArtifact
- Adapters: ImplementationAdapter, FunctionAdapter, LegacyAdapter, ModernizedAdapter,
  default_input_normalizer, default_output_normalizer
- Input Generation & Replay: generate_certification_test_suite
- Cross-Version Comparison Engine: CrossVersionCertificationEngine
- Certification Engine: CertificationEngine, certification_engine
- Repository: CertificationRepository, certification_repository
- Reporting: generate_html_report, generate_markdown_report
- Runner & Scoring: certify, equivalence_score, domain_scores
"""

from .models import (
    BehavioralRegression,
    CertificationArtifact,
    CertificationCase,
    CertificationContext,
    CertificationInputSet,
    CertificationMetrics,
    CertificationPolicy,
    CertificationStatus,
    CertificationTestInput,
    ComparisonRecord,
    CrossVersionCertificationReport,
    ImmutabilityError,
    Observation,
    OracleEquivalenceMetrics,
    PerOracleCertificationSummary,
    compute_artifact_content_hash,
    compute_certification_request_identity,
    compute_input_set_canonical_hash,
    verify_artifact_integrity,
    verify_input_set_integrity,
)
from .adapters import (
    FunctionAdapter,
    ImplementationAdapter,
    LegacyAdapter,
    ModernizedAdapter,
    default_input_normalizer,
    default_output_normalizer,
)
from .adapter_registry import AdapterRegistry, adapter_registry
from .input_generator import generate_certification_test_suite
from .engine import CrossVersionCertificationEngine
from .certification_engine import CertificationEngine, certification_engine
from .repository import CertificationRepository, certification_repository
from .report_generator import generate_html_report, generate_markdown_report
from .runner import certify
from .scorer import domain_scores, equivalence_score

__all__ = [
    "Observation",
    "CertificationTestInput",
    "BehavioralRegression",
    "ComparisonRecord",
    "OracleEquivalenceMetrics",
    "CrossVersionCertificationReport",
    "CertificationStatus",
    "CertificationPolicy",
    "PerOracleCertificationSummary",
    "CertificationMetrics",
    "CertificationArtifact",
    "CertificationInputSet",
    "CertificationCase",
    "ImmutabilityError",
    "compute_artifact_content_hash",
    "compute_input_set_canonical_hash",
    "verify_artifact_integrity",
    "verify_input_set_integrity",
    "ImplementationAdapter",
    "FunctionAdapter",
    "LegacyAdapter",
    "ModernizedAdapter",
    "AdapterRegistry",
    "adapter_registry",
    "default_input_normalizer",
    "default_output_normalizer",
    "generate_certification_test_suite",
    "CrossVersionCertificationEngine",
    "CertificationEngine",
    "certification_engine",
    "CertificationRepository",
    "certification_repository",
    "generate_html_report",
    "generate_markdown_report",
    "certify",
    "equivalence_score",
    "domain_scores",
]
