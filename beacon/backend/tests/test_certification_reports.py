from certification.models import (
    CertificationArtifact,
    CertificationContext,
    CertificationMetrics,
    CertificationStatus,
)
from certification.report_generator import (
    generate_html_report,
    generate_markdown_report,
    generate_pdf_report,
    generate_workflow_run_pdf_report,
)


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
            evidence_gate_results={"input_set_integrity": True},
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
    assert "Inventive-step evidence gates" in report
    assert "input_set_integrity" in report


def test_html_certificate_report_handles_missing_coverage_and_shows_execution_mode():
    report = generate_html_report(make_artifact())

    assert "N/A" in report
    assert "RUN-TEST" in report
    assert "legacy-sha256" in report
    assert "Evidence Factor" in report
    assert "Inventive-Step Evidence Gates" in report


def test_pdf_certificate_includes_summary_and_certificate_identity():
    report = generate_pdf_report(make_artifact(), ai_summary="Evidence summary from this run.")

    assert report.startswith(b"%PDF-")
    assert b"Evidence summary from this run." in report
    assert b"CERT-TEST" in report


def test_blocked_run_pdf_is_marked_not_a_certificate_and_has_no_fabricated_score():
    report = generate_workflow_run_pdf_report({
        "workflow_run_id": "RUN-BLOCKED",
        "status": "FAILED",
        "certified": False,
        "error_message": "No runtime output captured.",
        "metadata": {"source_hashes": {"legacy": "legacy-hash", "modern": "modern-hash"}},
    })

    assert report.startswith(b"%PDF-")
    assert b"NOT A CERTIFICATE" in report
    assert b"Not calculated" in report
    assert b"legacy-hash" in report
