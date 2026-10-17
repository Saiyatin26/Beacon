"""Phase 10 — Human-Readable HTML and Markdown Certification Report Generator.

Generates professional, responsive audit reports containing executive summaries,
cryptographic verification hashes, per-oracle breakdown tables, exact regression
counterexamples, and audit provenance without exposing secrets.
"""

import html
import io
import json
from typing import Any, Optional
from .models import CertificationArtifact, CertificationStatus
from .scorer import EVIDENCE_SCORE_WEIGHTS


def generate_html_report(artifact: CertificationArtifact) -> str:
    """Generates a standalone, styled HTML audit certificate report."""
    context = artifact.context
    coverage = artifact.metrics.oracle_coverage_pct
    coverage_text = f"{coverage * 100:.0f}%" if coverage is not None else "N/A"
    evidence_quality_text = (
        f"{artifact.metrics.evidence_quality_score * 100:.1f}%"
        if artifact.metrics.evidence_quality_score is not None
        else "N/A"
    )
    total_factor_weight = sum(
        EVIDENCE_SCORE_WEIGHTS[name]
        for name in artifact.metrics.evidence_score_factors
    )
    evidence_factor_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{value * 100:.1f}%</td>"
        f"<td>{EVIDENCE_SCORE_WEIGHTS[name] / total_factor_weight * 100:.1f}%</td></tr>"
        for name, value in artifact.metrics.evidence_score_factors.items()
    ) if total_factor_weight else ""
    evidence_gate_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{'PASS' if passed else 'BLOCK'}</td></tr>"
        for name, passed in artifact.metrics.evidence_gate_results.items()
    )
    status_colors = {
        CertificationStatus.CERTIFIED: ("#10b981", "#ecfdf5", "CERTIFIED"),
        CertificationStatus.CERTIFIED_WITH_WARNINGS: ("#f59e0b", "#fffbeb", "CERTIFIED WITH WARNINGS"),
        CertificationStatus.NOT_CERTIFIED: ("#ef4444", "#fef2f2", "NOT CERTIFIED"),
        CertificationStatus.REFERENCE_INCONSISTENT: ("#8b5cf6", "#f5f3ff", "REFERENCE INCONSISTENT"),
        CertificationStatus.INSUFFICIENT_COVERAGE: ("#f97316", "#fff7ed", "INSUFFICIENT COVERAGE"),
        CertificationStatus.ORACLE_SET_INVALID: ("#dc2626", "#fef2f2", "ORACLE SET INVALID"),
        CertificationStatus.INCONCLUSIVE: ("#6b7280", "#f3f4f6", "INCONCLUSIVE"),
    }

    badge_color, badge_bg, badge_text = status_colors.get(
        artifact.status, ("#6b7280", "#f3f4f6", artifact.status.value)
    )

    # Build oracle rows
    oracle_rows = []
    for s in artifact.oracle_summaries:
        status_badge = (
            f'<span style="padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 11px; '
            f'background: {"#d1fae5; color: #065f46" if s.oracle_status == "PASS" else "#fee2e2; color: #991b1b"};">'
            f'{html.escape(s.oracle_status)}</span>'
        )
        oracle_rows.append(f"""
            <tr>
                <td style="font-family: monospace; font-size: 12px; font-weight: bold;">{html.escape(s.oracle_id)}</td>
                <td style="font-family: monospace; font-size: 12px;">{html.escape(s.condition_str)} &rarr; {html.escape(s.consequence_str)}</td>
                <td><span style="text-transform: uppercase; font-size: 11px; font-weight: bold;">{html.escape(s.severity)}</span></td>
                <td>{s.applicable_probes}</td>
                <td>{s.matching_probes}</td>
                <td>{s.modern_regressions}</td>
                <td style="font-weight: bold;">{s.oracle_equivalence_rate * 100:.1f}%</td>
                <td>{status_badge}</td>
            </tr>
        """)

    # Build regression rows
    regression_cards = []
    for reg in artifact.regressions:
        regression_cards.append(f"""
            <div style="background: #fff; border: 1px solid #fecaca; border-left: 4px solid #ef4444; border-radius: 6px; padding: 14px; margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                    <span style="font-weight: bold; color: #991b1b;">Oracle #{html.escape(reg.oracle_id)} &bull; Regression #{html.escape(reg.regression_id)}</span>
                    <span style="font-family: monospace; font-size: 12px; color: #6b7280;">Input ID: {html.escape(reg.input_id)}</span>
                </div>
                <div style="margin-bottom: 8px; font-size: 13px;">
                    <strong>Failed Assertion:</strong> <code>{html.escape(reg.failed_assertion)}</code>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; background: #f9fafb; padding: 10px; border-radius: 4px; font-size: 12px;">
                    <div><strong>Input Values:</strong><br><pre style="margin: 4px 0; font-size: 11px;">{html.escape(json.dumps(reg.input_values, indent=1))}</pre></div>
                    <div><strong>Legacy Output:</strong><br><span style="color: #059669; font-weight: bold;">{html.escape(str(reg.legacy_output))}</span></div>
                    <div><strong>Modernized Output:</strong><br><span style="color: #dc2626; font-weight: bold;">{html.escape(str(reg.modern_output))}</span></div>
                </div>
            </div>
        """)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BEACON Behavioral Equivalence Certificate — {html.escape(artifact.certification_id)}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #f8fafc; color: #1e293b; line-height: 1.5; margin: 0; padding: 30px; }}
        .container {{ max-width: 1000px; margin: 0 auto; background: #ffffff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.06); padding: 36px; }}
        .header {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #e2e8f0; padding-bottom: 20px; margin-bottom: 24px; }}
        .badge {{ padding: 6px 16px; border-radius: 20px; font-size: 14px; font-weight: bold; display: inline-block; }}
        .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
        .card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; text-align: center; }}
        .card-val {{ font-size: 24px; font-weight: bold; color: #0f172a; margin-top: 4px; }}
        .card-lbl {{ font-size: 12px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; }}
        th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #e2e8f0; font-size: 13px; }}
        th {{ background: #f1f5f9; color: #475569; font-weight: 600; text-transform: uppercase; font-size: 11px; }}
        .provenance-box {{ background: #f1f5f9; border-radius: 6px; padding: 14px; font-family: monospace; font-size: 11px; word-break: break-all; margin-bottom: 24px; }}
        .statement {{ font-size: 12px; color: #64748b; font-style: italic; border-top: 1px solid #e2e8f0; padding-top: 16px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1 style="margin: 0; font-size: 24px; color: #0f172a;">BEACON Behavioral Equivalence Certificate</h1>
                <div style="font-size: 13px; color: #64748b; margin-top: 4px;">
                    Certificate ID: <strong>{html.escape(artifact.certification_id)}</strong> &bull; Project: <strong>{html.escape(artifact.project_id)}</strong>
                </div>
            </div>
            <div>
                <div class="badge" style="background: {badge_bg}; color: {badge_color}; border: 1px solid {badge_color};">
                    {badge_text}
                </div>
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <div class="card-lbl">Evidence-Adjusted Score</div>
                <div class="card-val" style="color: {badge_color};">{artifact.score * 100:.1f}%</div>
            </div>
            <div class="card">
                <div class="card-lbl">Oracle Coverage</div>
                <div class="card-val">{coverage_text}</div>
            </div>
            <div class="card">
                <div class="card-lbl">Matching Probes</div>
                <div class="card-val" style="color: #10b981;">{artifact.metrics.matching_probes} / {artifact.metrics.applicable_inputs}</div>
            </div>
            <div class="card">
                <div class="card-lbl">Regressions</div>
                <div class="card-val" style="color: {'#ef4444' if artifact.metrics.modern_regressions > 0 else '#10b981'};">{artifact.metrics.modern_regressions}</div>
            </div>
        </div>

        <h3 style="font-size: 16px; margin-bottom: 12px;">Per-Oracle Verification Breakdown</h3>
        <table>
            <thead>
                <tr>
                    <th>Oracle ID</th>
                    <th>Behavioral Rule</th>
                    <th>Severity</th>
                    <th>Applied</th>
                    <th>Matches</th>
                    <th>Regressions</th>
                    <th>Equivalence</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {''.join(oracle_rows)}
            </tbody>
        </table>

        <h3 style="font-size: 16px; margin-bottom: 8px;">Evidence &amp; Execution Context</h3>
        <div class="provenance-box">
            <strong>Certification Run ID:</strong> {html.escape(context.certification_run_id if context else artifact.certification_id)}<br>
            <strong>Observed Behavioral Equivalence:</strong> {artifact.metrics.overall_equivalence_score * 100:.1f}%<br>
            <strong>Evidence Quality:</strong> {evidence_quality_text}<br>
            <strong>Policy Threshold:</strong> {f"{context.policy_min_equivalence_score * 100:.1f}%" if context else "not recorded"}<br>
            <strong>Legacy Source SHA-256:</strong> {html.escape(context.legacy_implementation_hash if context else artifact.legacy_implementation_hash or "")}<br>
            <strong>Modern Source SHA-256:</strong> {html.escape(context.modernized_implementation_hash if context else artifact.modernized_implementation_hash or "")}<br>
            <strong>Execution Metadata:</strong> {html.escape(json.dumps(context.execution_metadata, sort_keys=True, default=str) if context else "{}")}
        </div>
        <p style="font-size: 12px; color: #64748b;">The evidence-adjusted score combines observed behavioral equivalence with run-derived evidence quality factors. This project heuristic is not a statistical confidence interval or proof of arbitrary program equivalence.</p>
        <table>
            <thead><tr><th>Evidence Factor</th><th>Observed Value</th><th>Normalized Weight</th></tr></thead>
            <tbody>{evidence_factor_rows or '<tr><td colspan="2">No factor data recorded</td></tr>'}</tbody>
        </table>
        <h3 style="font-size: 16px; margin-bottom: 8px;">Inventive-Step Evidence Gates</h3>
        <p style="font-size: 12px; color: #64748b;">A failed gate blocks certification; it cannot be offset by the composite score.</p>
        <table><thead><tr><th>Gate</th><th>Result</th></tr></thead>
            <tbody>{evidence_gate_rows or '<tr><td colspan="2">Gate data was not recorded for this legacy artifact.</td></tr>'}</tbody></table>

        {f'<h3 style="font-size: 16px; margin-bottom: 12px; color: #991b1b;">Behavioral Regressions &amp; Counterexamples ({len(artifact.regressions)})</h3>{"".join(regression_cards)}' if artifact.regressions else ''}

        <h3 style="font-size: 16px; margin-bottom: 8px;">Cryptographic Audit Provenance</h3>
        <div class="provenance-box">
            <strong>Certificate SHA-256 Hash:</strong> {html.escape(artifact.content_hash)}<br>
            <strong>Oracle Set ID:</strong> {html.escape(artifact.oracle_set_id)} (v{artifact.oracle_set_version}) &bull; Hash: {html.escape(artifact.oracle_set_hash)}<br>
            <strong>Input Set ID:</strong> {html.escape(artifact.input_set_id)} &bull; Hash: {html.escape(artifact.input_set_hash)}<br>
            <strong>Policy ID:</strong> {html.escape(artifact.certification_policy_id)} (v{artifact.certification_policy_version}) &bull; Hash: {html.escape(artifact.certification_policy_hash)}<br>
            <strong>Implementations:</strong> Legacy v{html.escape(artifact.legacy_version)} &bull; Modernized v{html.escape(artifact.modernized_version)}<br>
            <strong>Generated At:</strong> {html.escape(artifact.timestamp)} &bull; Engine v{html.escape(artifact.certification_engine_version)}
        </div>

        <div class="statement">
            <strong>Legal &amp; Methodological Notice:</strong> {html.escape(artifact.statement)}
        </div>
    </div>
</body>
</html>
"""


def generate_markdown_report(artifact: CertificationArtifact) -> str:
    """Generates a structured markdown audit report."""
    context = artifact.context
    coverage = artifact.metrics.oracle_coverage_pct
    coverage_text = f"{coverage * 100:.0f}%" if coverage is not None else "N/A"
    evidence_quality_text = (
        f"{artifact.metrics.evidence_quality_score * 100:.1f}%"
        if artifact.metrics.evidence_quality_score is not None
        else "N/A (not recorded)"
    )
    md = []
    md.append(f"# BEACON Behavioral Equivalence Certificate — {artifact.certification_id}")
    md.append(f"**Status**: `{artifact.status.value}` | **Certified**: `{artifact.certified}` | **Evidence-adjusted score**: `{artifact.score * 100:.1f}%`\n")
    md.append(f"- **Certification Run ID**: `{context.certification_run_id if context and context.certification_run_id else artifact.certification_id}`")
    md.append(f"- **Project**: `{artifact.project_id}`")
    md.append(f"- **Legacy Version**: `{artifact.legacy_version}` &rarr; **Modernized Version**: `{artifact.modernized_version}`")
    md.append(f"- **Oracle Set**: `{artifact.oracle_set_id}` (v{artifact.oracle_set_version}, Hash: `{artifact.oracle_set_hash[:12]}...`)")
    md.append(f"- **Certificate Content Hash**: `{artifact.content_hash}`")
    md.append(f"- **Legacy Source SHA-256**: `{context.legacy_implementation_hash if context else artifact.legacy_implementation_hash or ''}`")
    md.append(f"- **Modern Source SHA-256**: `{context.modernized_implementation_hash if context else artifact.modernized_implementation_hash or ''}`")
    md.append(f"- **Timestamp**: `{artifact.timestamp}`\n")

    md.append("## Quantitative Metrics")
    md.append(f"| Metric | Value |")
    md.append(f"| :--- | :--- |")
    md.append(f"| Evidence-adjusted score | **{artifact.score * 100:.1f}%** |")
    md.append(f"| Observed behavioral equivalence score | **{artifact.metrics.overall_equivalence_score * 100:.1f}%** |")
    md.append(f"| Evidence quality score | **{evidence_quality_text}** |")
    md.append(f"| Oracle Coverage | **{coverage_text}** ({artifact.metrics.oracles_exercised}/{artifact.metrics.oracle_count}) |")
    md.append(f"| Matching Probes | {artifact.metrics.matching_probes} / {artifact.metrics.applicable_inputs} |")
    md.append(f"| Modern Regressions | {artifact.metrics.modern_regressions} |")
    md.append(f"| Reference Inconsistencies | {artifact.metrics.reference_inconsistencies} |")
    md.append(f"| Mutual Violations | {artifact.metrics.mutual_violations} |\n")

    md.append("## Evidence-adjusted score factors")
    md.append("The evidence-adjusted score combines observed behavioral equivalence with run-derived evidence quality factors. It is a project heuristic, not a statistical confidence interval or proof of arbitrary program equivalence.")
    md.append("| Factor | Value | Normalized weight |")
    md.append("| :--- | ---: | ---: |")
    if artifact.metrics.evidence_score_factors:
        total_factor_weight = sum(
            EVIDENCE_SCORE_WEIGHTS[name]
            for name in artifact.metrics.evidence_score_factors
        )
        for name, value in artifact.metrics.evidence_score_factors.items():
            normalized_weight = EVIDENCE_SCORE_WEIGHTS[name] / total_factor_weight
            md.append(f"| `{name}` | {value * 100:.1f}% | {normalized_weight * 100:.1f}% |")
    else:
        md.append("| Not recorded | N/A | N/A |")
    md.append("\n## Inventive-step evidence gates")
    md.append("These fail-closed gates prevent a high composite score from certifying a run with unreliable execution, failed integrity verification, or missing Full BEACON provenance.")
    if artifact.metrics.evidence_gate_results:
        md.append("| Gate | Result |")
        md.append("| :--- | :--- |")
        for name, passed in artifact.metrics.evidence_gate_results.items():
            md.append(f"| `{name}` | {'PASS' if passed else 'BLOCK'} |")
    else:
        md.append("- Gate data was not recorded for this legacy artifact.")
    if artifact.metrics.evidence_gate_reasons:
        md.extend(f"- **Blocked:** {reason}" for reason in artifact.metrics.evidence_gate_reasons)
    if context:
        md.append("\n## Execution and provider provenance")
        md.append(f"- **Execution metadata**: `{json.dumps(context.execution_metadata, sort_keys=True, default=str)}`")
        md.append(f"- **Provider metadata**: `{json.dumps(context.provider_metadata, sort_keys=True, default=str)}`")
        md.append(f"- **Policy threshold**: `{context.policy_min_equivalence_score * 100:.1f}%`")
    if artifact.blocking_reasons:
        md.append("\n## Blocking reasons")
        md.extend(f"- {reason}" for reason in artifact.blocking_reasons)
    if artifact.warnings:
        md.append("\n## Warnings")
        md.extend(f"- {warning}" for warning in artifact.warnings)

    md.append("## Per-Oracle Summary")
    md.append("| Oracle ID | Severity | Applied | Matching | Regressions | Equivalence | Status |")
    md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for s in artifact.oracle_summaries:
        md.append(f"| `{s.oracle_id}` | {s.severity} | {s.applicable_probes} | {s.matching_probes} | {s.modern_regressions} | {s.oracle_equivalence_rate * 100:.1f}% | `{s.oracle_status}` |")

    if artifact.regressions:
        md.append("\n## Behavioral Regressions")
        for reg in artifact.regressions:
            md.append(f"### Regression in Oracle `{reg.oracle_id}`")
            md.append(f"- **Input ID**: `{reg.input_id}` (`{json.dumps(reg.input_values)}`)")
            md.append(f"- **Failed Assertion**: `{reg.failed_assertion}`")
            md.append(f"- **Legacy Output**: `{reg.legacy_output}` vs **Modern Output**: `{reg.modern_output}`")

    md.append(f"\n> **Notice**: {artifact.statement}")
    return "\n".join(md)


def generate_pdf_report(
    artifact: CertificationArtifact,
    ai_summary: Optional[str] = None,
    cases: Optional[list[Any]] = None,
) -> bytes:
    """Generate a PDF dossier for a persisted certification and its grounded summary."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = io.BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CertificateTitle", parent=styles["Title"], alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="SmallText", parent=styles["BodyText"], fontSize=8, leading=10))
    story = [
        Paragraph("BEACON Behavioral Equivalence Certificate", styles["CertificateTitle"]),
        Spacer(1, 12),
        Paragraph(f"Certificate ID: {html.escape(artifact.certification_id)}", styles["Heading2"]),
    ]

    context = artifact.context
    run_id = context.certification_run_id if context and context.certification_run_id else artifact.certification_id
    score_text = f"{artifact.score * 100:.1f}%"
    metrics = [
        ["Verdict", artifact.status.value, "Certified", "Yes" if artifact.certified else "No"],
        ["Evidence-adjusted score", score_text, "Policy threshold", (
            f"{context.policy_min_equivalence_score * 100:.1f}%" if context else "Not recorded"
        )],
        ["Run ID", run_id, "Generated", artifact.timestamp or "Not recorded"],
        ["Oracle coverage", (
            f"{artifact.metrics.oracle_coverage_pct * 100:.1f}%"
            if artifact.metrics.oracle_coverage_pct is not None else "N/A"
        ), "Matching probes", str(artifact.metrics.matching_probes)],
    ]
    story.extend([
        Table(
            metrics,
            colWidths=[1.45 * inch, 2.0 * inch, 1.35 * inch, 2.0 * inch],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8eef5")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#e8eef5")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]),
        ),
        Spacer(1, 12),
        Paragraph("Evidence-grounded AI summary", styles["Heading2"]),
        Paragraph(
            html.escape(ai_summary.strip()) if ai_summary and ai_summary.strip()
            else "No AI summary was persisted for this certification run.",
            styles["BodyText"],
        ),
        Spacer(1, 10),
        Paragraph("Source and certificate identity", styles["Heading2"]),
        Paragraph(
            f"Legacy source SHA-256: {html.escape(context.legacy_implementation_hash if context else artifact.legacy_implementation_hash or 'Not recorded')}<br/>"
            f"Modern source SHA-256: {html.escape(context.modernized_implementation_hash if context else artifact.modernized_implementation_hash or 'Not recorded')}<br/>"
            f"Certificate SHA-256: {html.escape(artifact.content_hash or 'Not recorded')}<br/>"
            f"Input-set SHA-256: {html.escape(artifact.input_set_hash or 'Not recorded')}<br/>"
            f"Oracle-set SHA-256: {html.escape(artifact.oracle_set_hash or 'Not recorded')}",
            styles["SmallText"],
        ),
        Spacer(1, 10),
        Paragraph("Execution and limitations", styles["Heading2"]),
        Paragraph(
            html.escape(json.dumps(context.execution_metadata, sort_keys=True, default=str) if context else "{}"),
            styles["SmallText"],
        ),
        Paragraph(
            f"AI provider: {html.escape(context.provider if context else 'Not recorded')} | "
            f"Model: {html.escape(context.model if context else 'Not recorded')} | "
            f"Generation method: {html.escape(context.generation_method if context else 'Not recorded')}",
            styles["SmallText"],
        ),
        Paragraph(
            "The evidence-adjusted score is a project heuristic over the tested input domain. "
            "It is not a statistical confidence interval or proof of arbitrary program equivalence.",
            styles["SmallText"],
        ),
    ])
    if artifact.blocking_reasons:
        story.extend([Spacer(1, 8), Paragraph("Blocking reasons", styles["Heading2"])])
        story.extend(Paragraph(f"- {html.escape(reason)}", styles["SmallText"]) for reason in artifact.blocking_reasons)
    if artifact.warnings:
        story.extend([Spacer(1, 8), Paragraph("Warnings", styles["Heading2"])])
        story.extend(Paragraph(f"- {html.escape(warning)}", styles["SmallText"]) for warning in artifact.warnings)
    if artifact.regressions:
        story.extend([Spacer(1, 8), Paragraph("Behavioral regressions", styles["Heading2"])])
        for regression in artifact.regressions:
            story.append(Paragraph(
                f"Oracle {html.escape(regression.oracle_id)}; input {html.escape(regression.input_id)}: "
                f"{html.escape(regression.failed_assertion)}",
                styles["SmallText"],
            ))
            story.append(Paragraph(
                f"Legacy output: {html.escape(str(regression.legacy_output))}<br/>"
                f"Modern output: {html.escape(str(regression.modern_output))}",
                styles["SmallText"],
            ))
            story.append(Spacer(1, 5))
    if cases:
        story.extend([Spacer(1, 8), Paragraph("Persisted execution evidence", styles["Heading2"])])
        evidence_rows = [[
            Paragraph("<b>Case</b>", styles["SmallText"]),
            Paragraph("<b>Classification / status</b>", styles["SmallText"]),
            Paragraph("<b>Input</b>", styles["SmallText"]),
            Paragraph("<b>Observed outputs</b>", styles["SmallText"]),
        ]]
        for case in cases[:100]:
            input_value = getattr(case, "input_json", "")
            legacy_value = getattr(case, "legacy_output_json", "")
            modern_value = getattr(case, "modern_output_json", "")
            if isinstance(input_value, str):
                input_value = input_value[:1200]
            if isinstance(legacy_value, str):
                legacy_value = legacy_value[:1200]
            if isinstance(modern_value, str):
                modern_value = modern_value[:1200]
            case_label = f"{getattr(case, 'case_id', '')} / {getattr(case, 'input_id', '')}"
            execution_status = (
                f"{getattr(case, 'classification', 'UNKNOWN')}<br/>"
                f"Legacy: {getattr(case, 'legacy_execution_status', 'UNKNOWN')}<br/>"
                f"Modern: {getattr(case, 'modern_execution_status', 'UNKNOWN')}"
            )
            outputs = f"Legacy: {legacy_value}<br/>Modern: {modern_value}"
            evidence_rows.append([
                Paragraph(html.escape(str(case_label)), styles["SmallText"]),
                Paragraph(html.escape(str(execution_status)), styles["SmallText"]),
                Paragraph(html.escape(str(input_value)), styles["SmallText"]),
                Paragraph(html.escape(str(outputs)), styles["SmallText"]),
            ])
        story.append(Table(
            evidence_rows,
            colWidths=[1.05 * inch, 1.25 * inch, 2.2 * inch, 2.25 * inch],
            repeatRows=1,
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]),
        ))
    story.extend([
        Spacer(1, 12),
        Paragraph(html.escape(artifact.statement), styles["SmallText"]),
    ])
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.6 * inch,
        leftMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=f"BEACON Certificate {artifact.certification_id}",
        author="BEACON",
        pageCompression=0,
    )
    document.build(story)
    return buffer.getvalue()


def generate_workflow_run_pdf_report(
    run: dict[str, Any],
    ai_summary: Optional[str] = None,
) -> bytes:
    """Generate a PDF run report that never misrepresents a blocked run as a certificate."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="RunReportTitle", parent=styles["Title"], alignment=1))
    styles.add(ParagraphStyle(name="RunReportSmall", parent=styles["BodyText"], fontSize=8, leading=10))
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    source_hashes = metadata.get("source_hashes") or {}
    if not source_hashes:
        source_hashes = {
            "legacy": (metadata.get("legacy_provenance") or {}).get("content_hash"),
            "modern": (metadata.get("modern_provenance") or {}).get("content_hash"),
        }
    score = run.get("certification_score", run.get("equivalence_score"))
    score_text = f"{float(score) * 100:.1f}%" if isinstance(score, (int, float)) else "Not calculated"
    status_text = str(run.get("certification_status") or run.get("status") or run.get("state") or "UNKNOWN")
    story = [
        Paragraph("BEACON Workflow Run Report", styles["RunReportTitle"]),
        Spacer(1, 8),
        Paragraph("<b>NOT A CERTIFICATE</b> — this run did not produce a certification artifact.", styles["Heading2"]),
        Table(
            [
                ["Workflow Run ID", str(run.get("workflow_run_id", "Not recorded"))],
                ["Status", status_text],
                ["Certified", "Yes" if run.get("certified") else "No"],
                ["Evidence-adjusted score", score_text],
                ["Error code", str(run.get("error_code") or "None recorded")],
                ["Error / diagnostic", str(run.get("error_message") or metadata.get("diagnostic_message") or "None recorded")],
            ],
            colWidths=[1.6 * inch, 5.0 * inch],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8eef5")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]),
        ),
        Spacer(1, 10),
        Paragraph("Source identity", styles["Heading2"]),
        Paragraph(
            f"Legacy source SHA-256: {html.escape(str(source_hashes.get('legacy') or 'Not recorded'))}<br/>"
            f"Modern source SHA-256: {html.escape(str(source_hashes.get('modern') or 'Not recorded'))}",
            styles["RunReportSmall"],
        ),
        Spacer(1, 8),
        Paragraph("AI summary", styles["Heading2"]),
        Paragraph(
            html.escape(ai_summary.strip()) if ai_summary and ai_summary.strip()
            else "No grounded AI summary is available for this run.",
            styles["BodyText"],
        ),
        Spacer(1, 8),
        Paragraph("Run evidence", styles["Heading2"]),
    ]
    evidence = metadata.get("representative_cases") or metadata.get("evidence") or []
    if isinstance(evidence, list) and evidence:
        for item in evidence[:50]:
            story.append(Paragraph(
                html.escape(json.dumps(item, sort_keys=True, default=str)[:1800]),
                styles["RunReportSmall"],
            ))
            story.append(Spacer(1, 4))
    else:
        story.append(Paragraph("No paired execution evidence was recorded.", styles["RunReportSmall"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "A successful certificate is generated only when execution and evidence satisfy the declared policy. "
        "This report records the run state and must not be used as a certification claim.",
        styles["RunReportSmall"],
    ))
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.6 * inch,
        leftMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=f"BEACON Run Report {run.get('workflow_run_id', '')}",
        author="BEACON",
        pageCompression=0,
    )
    document.build(story)
    return buffer.getvalue()
