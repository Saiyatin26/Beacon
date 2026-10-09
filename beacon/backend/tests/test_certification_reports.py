from certification.models import (
    CertificationArtifact,
    CertificationContext,
    CertificationMetrics,
    CertificationStatus,
)
from certification.report_generator import generate_html_report, generate_markdown_report


def make_artifact():
    return CertificationArtifact(
        certification_id="CERT-TEST",
        project_id="sample",
        status=CertificationStatus.CERTIFIED,
        certified=True,
        score=0.9,
        content_hash="artifact-sha256",
        context=CertificationContext(
            certification_run_id="RUN-TEST",
            legacy_implementation_hash="legacy-sha256",
            modernized_implementation_hash="modern-sha256",
            policy_min_equivalence_score=0.8,
            execution_metadata={"legacy": {"runtime": "python"}},
        ),
        metrics=CertificationMetrics(
            overall_equivalence_score=1.0,
            evidence_quality_score=0.9,
            evidence_adjusted_score=0.9,
            evidence_score_factors={"input_coverage": 0.8},
        ),
    )


def test_markdown_certificate_report_includes_run_hashes_and_evidence_score():
    report = generate_markdown_report(make_artifact())

    assert "RUN-TEST" in report
    assert "legacy-sha256" in report
    assert "modern-sha256" in report
    assert "Evidence-adjusted score" in report
    assert "`input_coverage`" in report
    assert "90.0%" in report


def test_html_certificate_report_handles_missing_coverage_and_shows_execution_mode():
    report = generate_html_report(make_artifact())

    assert "N/A" in report
    assert "RUN-TEST" in report
    assert "legacy-sha256" in report
    assert "Evidence Factor" in report
