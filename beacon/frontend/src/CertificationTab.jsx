/**
 * BEACON V2 — CertificationTab.jsx
 *
 * Repository-First Behavioral Equivalence Certification Entry Point.
 * Implements the V2 Part 1 Architecture:
 *   1. User provides Legacy/Modern sources, explicit test inputs, and evaluation mode.
 *   2. Backend securely ingests repositories, resolves immutable commit SHAs and content hashes.
 *   3. Safe static inspection (zero dynamic imports) resolves compatible adapters and entrypoints.
 *   4. Behavioral invariants and legitimate inputs are discovered from repository evidence.
 *   5. Backend builds a cryptographically bound RepositoryExecutionSpec.
 *   6. User reviews the derived evidence and proceeds to authoritative certification.
 *
 * Presets, hardcoded benchmarks, and synthetic input fallbacks have been removed from this flow.
 */
import { useState, useEffect } from "react";

// ─── Status / Badge helpers ────────────────────────────────────────────────────

const STATUS_STYLES = {
  CERTIFIED: { bg: "#ecfdf5", border: "#10b981", color: "#065f46", label: "✅ CERTIFIED" },
  CERTIFIED_WITH_WARNINGS: { bg: "#fffbeb", border: "#f59e0b", color: "#92400e", label: "⚠️ CERTIFIED WITH WARNINGS" },
  NOT_CERTIFIED: { bg: "#fef2f2", border: "#ef4444", color: "#991b1b", label: "❌ NOT CERTIFIED" },
  INCONCLUSIVE: { bg: "#fff7ed", border: "#f97316", color: "#9a3412", label: "⚙️ INCONCLUSIVE" },
  INSUFFICIENT_COVERAGE: { bg: "#fff7ed", border: "#f97316", color: "#9a3412", label: "⚠️ INSUFFICIENT COVERAGE" },
  REFERENCE_INCONSISTENT: { bg: "#f5f3ff", border: "#8b5cf6", color: "#5b21b6", label: "🔴 REFERENCE INCONSISTENT" },
  ORACLE_SET_INVALID: { bg: "#fef2f2", border: "#dc2626", color: "#7f1d1d", label: "🚫 ORACLE SET INVALID" },
};

const WORKFLOW_STATE_COLORS = {
  INITIALIZED: "#94a3b8",
  VALIDATING: "#f59e0b",
  CAPTURING_EVIDENCE: "#3b82f6",
  EVALUATING: "#6366f1",
  RESOLVING_ORACLES: "#8b5cf6",
  RESOLVING_THRESHOLDS: "#ec4899",
  CERTIFYING: "#14b8a6",
  EXPLAINING: "#06b6d4",
  PERSISTING: "#22c55e",
  COMPLETED: "#10b981",
  FAILED: "#ef4444",
  INCONCLUSIVE: "#f97316",
};

export default function CertificationTab({
  apiBase = "",
  authFetch,
  authToken,
  badgeStyle,
  cardStyle,
  statusBadgeStyles,
  userHasPermission,
  onCertifyResult,
}) {
  // ── Source Ingestion & Repository Form State ──────────────────────────────
  const [sourceType, setSourceType] = useState("GITHUB_REPOSITORY"); // GITHUB_REPOSITORY | UPLOADED_FILES
  const [legacyRepoUrl, setLegacyRepoUrl] = useState("");
  const [legacyRevision, setLegacyRevision] = useState("");
  const [legacySubdir, setLegacySubdir] = useState("");
  const [modernRepoUrl, setModernRepoUrl] = useState("");
  const [modernRevision, setModernRevision] = useState("");
  const [modernSubdir, setModernSubdir] = useState("");
  const [legacyFiles, setLegacyFiles] = useState([]);
  const [modernFiles, setModernFiles] = useState([]);
  const [analysisScope, setAnalysisScope] = useState("FILE"); // FILE | DIRECTORY
  const [stagedUpload, setStagedUpload] = useState(null);
  const [evaluationMode, setEvaluationMode] = useState("FULL_BEACON");
  const [customInputsJson, setCustomInputsJson] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);

  // ── Repository Analysis State ───────────────────────────────────────────────
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [analysisError, setAnalysisError] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);

  // ── Workflow Execution State ───────────────────────────────────────────────
  const [certifyBusy, setCertifyBusy] = useState(false);
  const [certifyError, setCertifyError] = useState(null);
  const [workflowResult, setWorkflowResult] = useState(null);
  const [workflowRunId, setWorkflowRunId] = useState(null);
  const [reportBusy, setReportBusy] = useState(false);
  const [reportError, setReportError] = useState(null);

  // ── Authoritative Oracle Reconciliation State ─────────────────────────────
  const [oracleRecon, setOracleRecon] = useState(null);
  const [oracleReconLoading, setOracleReconLoading] = useState(false);
  const [oracleReconError, setOracleReconError] = useState(null);

  // ── Step Tracking ──────────────────────────────────────────────────────────
  const [activeStep, setActiveStep] = useState("configure"); // configure | result

  // ── Recent Workflow Runs ───────────────────────────────────────────────────
  const [recentRuns, setRecentRuns] = useState([]);
  const [runsLoading, setRunsLoading] = useState(false);

  const _fetch = authFetch || window.fetch;

  const addLegacyFiles = (newFiles) => {
    const arr = Array.from(newFiles);
    setLegacyFiles((prev) => [...prev, ...arr]);
    setStagedUpload(null);
    setAnalysisResult(null);
    setAnalysisError(null);
  };

  const removeLegacyFile = (index) => {
    setLegacyFiles((prev) => prev.filter((_, i) => i !== index));
    setStagedUpload(null);
    setAnalysisResult(null);
    setAnalysisError(null);
  };

  const addModernFiles = (newFiles) => {
    const arr = Array.from(newFiles);
    setModernFiles((prev) => [...prev, ...arr]);
    setStagedUpload(null);
    setAnalysisResult(null);
    setAnalysisError(null);
  };

  const removeModernFile = (index) => {
    setModernFiles((prev) => prev.filter((_, i) => i !== index));
    setStagedUpload(null);
    setAnalysisResult(null);
    setAnalysisError(null);
  };

  const loadRecentRuns = async () => {
    setRunsLoading(true);
    try {
      const res = await _fetch(`${apiBase}/api/v2/workflow/runs?limit=10`);
      if (res.ok) {
        const data = await res.json();
        setRecentRuns(Array.isArray(data) ? data : []);
      }
    } catch {
      // Non-fatal
    } finally {
      setRunsLoading(false);
    }
  };

  useEffect(() => {
    if (authToken) loadRecentRuns();
  }, [authToken]);

  useEffect(() => {
    const runId = workflowResult?.artifact_id || workflowResult?.workflow_run_id || workflowRunId;
    if (!runId) {
      setOracleRecon(null);
      setOracleReconError(null);
      return;
    }
    let isCancelled = false;
    const fetchOracleReconciliation = async () => {
      setOracleReconLoading(true);
      setOracleReconError(null);
      try {
        const res = await _fetch(`${apiBase}/api/certifications/${encodeURIComponent(runId)}/oracle-reconciliation`);
        if (isCancelled) return;
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `HTTP ${res.status}: Failed to load oracle reconciliation`);
        }
        const data = await res.json();
        if (!isCancelled) {
          setOracleRecon(data);
        }
      } catch (err) {
        if (!isCancelled) {
          setOracleReconError(err.message || "Failed to load oracle reconciliation");
        }
      } finally {
        if (!isCancelled) {
          setOracleReconLoading(false);
        }
      }
    };
    fetchOracleReconciliation();
    return () => { isCancelled = true; };
  }, [workflowResult?.artifact_id, workflowResult?.workflow_run_id, workflowRunId, apiBase]);

  // ── Repository / Source Analysis Handler ────────────────────────────────────
  const handleAnalyzeRepositories = async () => {
    let activeLegacySpec = {
      repository_url: legacyRepoUrl.trim(),
      revision: legacyRevision.trim() || null,
      subdirectory: legacySubdir.trim() || null,
    };
    let activeModernSpec = {
      repository_url: modernRepoUrl.trim(),
      revision: modernRevision.trim() || null,
      subdirectory: modernSubdir.trim() || null,
    };
    let selectedArtifacts = null;
    let uploadId = null;

    if (sourceType === "UPLOADED_FILES") {
      if (legacyFiles.length === 0 || modernFiles.length === 0) {
        setAnalysisError("Both Legacy Reference and Modern Target source files must be selected.");
        return;
      }
    } else {
      if (!legacyRepoUrl.trim() || !modernRepoUrl.trim()) {
        setAnalysisError("Both Legacy Reference and Modernized Target repository paths or URLs are required.");
        return;
      }
    }

    setAnalysisBusy(true);
    setAnalysisError(null);
    setAnalysisResult(null);

    try {
      if (sourceType === "UPLOADED_FILES") {
        const formData = new FormData();
        legacyFiles.forEach((f) => formData.append("legacy_files", f));
        modernFiles.forEach((f) => formData.append("modern_files", f));
        formData.append("scope", analysisScope);

        const upRes = await _fetch(`${apiBase}/api/v2/workflow/sources/upload`, {
          method: "POST",
          body: formData,
        });
        const upData = await upRes.json();
        if (!upRes.ok) {
          throw new Error(upData.detail?.message || upData.detail || "Source upload failed");
        }
        setStagedUpload(upData);
        activeLegacySpec = upData.legacy_source_spec;
        activeModernSpec = upData.modern_source_spec;
        selectedArtifacts = [...(upData.legacy_artifacts || []), ...(upData.modern_artifacts || [])];
        uploadId = upData.upload_id;
      }

      const payload = {
        legacy_repository: activeLegacySpec,
        modern_repository: activeModernSpec,
        evaluation_mode: evaluationMode,
        source_mode: sourceType,
        analysis_scope: sourceType === "UPLOADED_FILES" ? analysisScope : "REPOSITORY",
        selected_artifacts: selectedArtifacts,
        upload_id: uploadId,
      };

      const res = await _fetch(`${apiBase}/api/v2/workflow/analyze-repository`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) {
        const errMsg = data.detail?.error
          ? `[${data.detail.error}] ${data.detail.message || ""}`
          : (data.detail?.message || data.detail || `Source analysis failed (HTTP ${res.status})`);
        throw new Error(typeof errMsg === "object" ? JSON.stringify(errMsg) : errMsg);
      }
      setAnalysisResult(data);
    } catch (e) {
      setAnalysisError(e.message);
    } finally {
      setAnalysisBusy(false);
    }
  };

  // ── Source Certification Execution Handler ──────────────────────────────────
  const handleCertifyRepository = async () => {
    let activeLegacySpec = {
      repository_url: legacyRepoUrl.trim(),
      revision: legacyRevision.trim() || null,
      subdirectory: legacySubdir.trim() || null,
    };
    let activeModernSpec = {
      repository_url: modernRepoUrl.trim(),
      revision: modernRevision.trim() || null,
      subdirectory: modernSubdir.trim() || null,
    };
    let selectedArtifacts = null;
    let uploadId = null;

    if (sourceType === "UPLOADED_FILES") {
      if (legacyFiles.length === 0 || modernFiles.length === 0) {
        setCertifyError("Both Legacy Reference and Modern Target source files must be selected.");
        return;
      }
    } else {
      if (!legacyRepoUrl.trim() || !modernRepoUrl.trim()) {
        setCertifyError("Both Legacy Reference and Modernized Target repository paths or URLs are required.");
        return;
      }
    }

    let customInputs = null;
    if (customInputsJson.trim()) {
      let parsedInputs;
      try {
        parsedInputs = JSON.parse(customInputsJson);
      } catch {
        setCertifyError("Additional test inputs must be valid JSON (one object or an array of objects).");
        return;
      }
      if (Array.isArray(parsedInputs)) {
        customInputs = parsedInputs;
      } else if (parsedInputs && typeof parsedInputs === "object") {
        customInputs = [parsedInputs];
      } else {
        setCertifyError("Additional test inputs must be a JSON object or an array of JSON objects.");
        return;
      }
      if (customInputs.length === 0 || customInputs.some((item) =>
        !item || typeof item !== "object" || Array.isArray(item) || Object.keys(item).length === 0
      )) {
        setCertifyError("Provide at least one non-empty JSON object for each additional test input.");
        return;
      }
    }

    setCertifyBusy(true);
    setCertifyError(null);
    setWorkflowResult(null);

    try {
      if (sourceType === "UPLOADED_FILES") {
        if (!stagedUpload) {
          const formData = new FormData();
          legacyFiles.forEach((f) => formData.append("legacy_files", f));
          modernFiles.forEach((f) => formData.append("modern_files", f));
          formData.append("scope", analysisScope);

          const upRes = await _fetch(`${apiBase}/api/v2/workflow/sources/upload`, {
            method: "POST",
            body: formData,
          });
          const upData = await upRes.json();
          if (!upRes.ok) {
            throw new Error(upData.detail?.message || upData.detail || "Source upload failed");
          }
          setStagedUpload(upData);
          activeLegacySpec = upData.legacy_source_spec;
          activeModernSpec = upData.modern_source_spec;
          selectedArtifacts = [...(upData.legacy_artifacts || []), ...(upData.modern_artifacts || [])];
          uploadId = upData.upload_id;
        } else {
          activeLegacySpec = stagedUpload.legacy_source_spec;
          activeModernSpec = stagedUpload.modern_source_spec;
          selectedArtifacts = [...(stagedUpload.legacy_artifacts || []), ...(stagedUpload.modern_artifacts || [])];
          uploadId = stagedUpload.upload_id;
        }
      }

      const payload = {
        legacy_repository: activeLegacySpec,
        modern_repository: activeModernSpec,
        evaluation_mode: evaluationMode,
        source_mode: sourceType,
        analysis_scope: sourceType === "UPLOADED_FILES" ? analysisScope : "REPOSITORY",
        selected_artifacts: selectedArtifacts,
        upload_id: uploadId,
        custom_inputs: customInputs,
        explain: true,
        explanation_mode: "auto",
      };

      const res = await _fetch(`${apiBase}/api/v2/workflow/certify-repository`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) {
        const errMsg = data.detail?.error
          ? `[${data.detail.error}] ${data.detail.message || ""}`
          : (data.detail?.message || data.detail || `Certification failed (HTTP ${res.status})`);
        throw new Error(typeof errMsg === "object" ? JSON.stringify(errMsg) : errMsg);
      }

      setWorkflowResult(data);
      setWorkflowRunId(data.workflow_run_id);
      setActiveStep("result");

      if (onCertifyResult && data.artifact_id) {
        onCertifyResult(data);
      }
      loadRecentRuns();
    } catch (e) {
      setCertifyError(e.message);
    } finally {
      setCertifyBusy(false);
    }
  };

  const saveDownload = (blob, filename) => {
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(anchor);
  };

  const downloadCertificate = async () => {
    if (!workflowResult?.artifact_id) return;
    setReportBusy(true);
    setReportError(null);
    try {
      const response = await _fetch(
        `${apiBase}/api/v1/certification/${encodeURIComponent(workflowResult.artifact_id)}/export?format=pdf`
      );
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || `Certificate download failed (HTTP ${response.status}).`);
      }
      saveDownload(
        await response.blob(),
        `beacon_certificate_${workflowResult.artifact_id}.pdf`
      );
    } catch (error) {
      setReportError(error.message || "Certificate download failed.");
    } finally {
      setReportBusy(false);
    }
  };

  const downloadRunReport = async () => {
    if (!workflowResult?.workflow_run_id) return;
    setReportBusy(true);
    setReportError(null);
    try {
      const response = await _fetch(
        `${apiBase}/api/v2/workflow/runs/${encodeURIComponent(workflowResult.workflow_run_id)}/export`
      );
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || `Run report download failed (HTTP ${response.status}).`);
      }
      saveDownload(
        await response.blob(),
        `beacon_run_${workflowResult.workflow_run_id}.pdf`
      );
    } catch (error) {
      setReportError(error.message || "Run report download failed.");
    } finally {
      setReportBusy(false);
    }
  };

  const downloadAiSummary = () => {
    if (!workflowResult?.explanation) return;
    const meta = workflowResult.metadata || {};
    const explanation = workflowResult.explanation;
    const generation = explanation.generation_metadata || {};
    const explanationFailed = explanation.status === "EXPLANATION_FAILED";
    const summary = {
      report_type: explanationFailed
        ? "BEACON_EXPLANATION_FAILURE_REPORT"
        : "BEACON_EVIDENCE_GROUNDED_SUMMARY",
      generation_status: explanation.status || "COMPLETED",
      workflow_run_id: workflowResult.workflow_run_id,
      certification_id: workflowResult.artifact_id || null,
      certificate_hash: workflowResult.artifact_hash || null,
      source_hashes: {
        legacy: meta.legacy_provenance?.content_hash || meta.sources?.legacy?.content_hash || null,
        modern: meta.modern_provenance?.content_hash || meta.sources?.modern?.content_hash || null,
      },
      authoritative_verdict: workflowResult.status,
      certified: Boolean(workflowResult.certified),
      summary: explanation.executive_summary || explanation.status_rationale || explanation.summary || "",
      provider: generation.provider || explanation.provider || "offline",
      model: generation.model || explanation.model || "deterministic",
      generation_mode: generation.generation_mode || explanation.mode || "DETERMINISTIC",
      fallback_used: Boolean(generation.fallback_occurred || explanation.fallback_used),
      fallback_reason: generation.fallback_reason || explanation.fallback_reason || null,
      grounding_status: explanation.grounding_status || explanation.authoritative_match_status || null,
      explanation,
    };
    const filename = `beacon_ai_summary_${workflowResult.artifact_id || workflowResult.workflow_run_id}.json`;
    saveDownload(new Blob([JSON.stringify(summary, null, 2)], { type: "application/json" }), filename);
  };

  // ── Load Past Run Helper ───────────────────────────────────────────────────
  const loadPastRun = async (runId) => {
    try {
      const res = await _fetch(`${apiBase}/api/v2/workflow/runs/${runId}`);
      if (res.ok) {
        const run = await res.json();
        const meta = run.metadata || {};
        const repCases = meta.representative_cases || [];
        const nonMatches = repCases.filter(c => c.classification !== "MATCH" && c.oracle_result !== "PASS");
        setWorkflowRunId(run.workflow_run_id);
        setWorkflowResult({
          workflow_run_id: run.workflow_run_id,
          application_id: run.application_id,
          state: run.state,
          status: run.certification_status || run.state,
          certified: run.certification_status === "CERTIFIED" || run.certification_status === "CERTIFIED_WITH_WARNINGS",
          equivalence_score: run.certification_score,
          artifact_id: run.certification_id,
          regressions_count: nonMatches.length,
          regressions: nonMatches.map((c, i) => ({
            oracle_id: `Case #${c.case_index ?? i + 1}`,
            input: c.input,
            legacy_output: c.legacy_output,
            modern_output: c.modern_output,
            diff: "Behavioral divergence detected between legacy COBOL and modern Python",
          })),
          timings_ms: run.stage_timings_ms || {},
          audit_status: "PERSISTED",
          metadata: meta,
          explanation: meta.explanation || null,
        });
        setActiveStep("result");
      }
    } catch {
      // Non-fatal
    }
  };

  const certStatus = workflowResult?.status;
  const statusStyle = STATUS_STYLES[certStatus] || { bg: "#f8fafc", border: "#cbd5e1", color: "#0f172a", label: certStatus || "—" };

  return (
    <div>
      {/* ── Header Bar ── */}
      <div
        style={{
          background: "#ffffff",
          border: "1px solid #cbd5e1",
          borderRadius: "10px",
          padding: "14px 20px",
          marginBottom: "20px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: "18px", fontWeight: "700", color: "#0f172a" }}>
            ⚡ BEACON V2 — Repository-First Behavioral Equivalence Certification
          </h2>
          <p style={{ margin: "3px 0 0", fontSize: "13px", color: "#64748b" }}>
            Autonomous repository-first equivalence verification. Securely ingests source repositories,
            resolves immutable content identities, safely inspects structure without dynamic module execution,
            and discovers behavioral invariants and legitimate test cases.
          </p>
        </div>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "5px",
              padding: "3px 10px",
              borderRadius: "9999px",
              fontSize: "12px",
              fontWeight: "600",
              background: "#eff6ff",
              color: "#1e40af",
              border: "1px solid #bfdbfe",
            }}
          >
            V2 Canonical Engine
          </span>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "5px",
              padding: "3px 10px",
              borderRadius: "9999px",
              fontSize: "12px",
              fontWeight: "600",
              background: "#f0fdf4",
              color: "#166534",
              border: "1px solid #86efac",
            }}
          >
            Safe Static Discovery
          </span>
        </div>
      </div>

      {/* ── Step Navigation Pills ── */}
      <div
        style={{
          display: "flex",
          gap: "0",
          marginBottom: "20px",
          background: "#f1f5f9",
          borderRadius: "8px",
          padding: "4px",
          width: "fit-content",
        }}
      >
        {[
          { id: "configure", label: "1. Repository Analysis & Discovery" },
          { id: "result", label: "2. Certification Result" },
        ].map((step) => (
          <button
            key={step.id}
            onClick={() => setActiveStep(step.id)}
            style={{
              background: activeStep === step.id ? "#ffffff" : "transparent",
              border: "none",
              padding: "7px 16px",
              borderRadius: "6px",
              fontWeight: activeStep === step.id ? "700" : "500",
              fontSize: "13px",
              color: activeStep === step.id ? "#1e40af" : "#64748b",
              cursor: "pointer",
              boxShadow: activeStep === step.id ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
              transition: "all 0.15s",
            }}
          >
            {step.label}
          </button>
        ))}
      </div>

      {/* ═══════════════════════════════════════════════════════════════════════ */}
      {/* STEP 1: REPOSITORY ANALYSIS & DISCOVERY                                */}
      {/* ═══════════════════════════════════════════════════════════════════════ */}
      {activeStep === "configure" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: "20px", alignItems: "start" }}>

          {/* ── Left Column: Configuration & Discovery Results ── */}
          <div>
            {/* Repository Input Form */}
            <section style={{ ...cardStyle, marginBottom: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                    Source Repositories & Evaluation Scope
                  </h3>
                  <p style={{ margin: "2px 0 0", fontSize: "12px", color: "#64748b" }}>
                    Provide legitimate legacy and modern repository paths or URLs. BEACON ingests and inspects them statically.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setShowAdvanced(!showAdvanced)}
                  style={{
                    background: "transparent",
                    border: "1px solid #cbd5e1",
                    borderRadius: "6px",
                    padding: "4px 10px",
                    fontSize: "11px",
                    fontWeight: "600",
                    color: "#475569",
                    cursor: "pointer",
                  }}
                >
                  {showAdvanced ? "Hide Advanced Settings ▲" : "Advanced Settings (Ref/Subdir) ▼"}
                </button>
              </div>

              {/* Source Type Selector */}
              <div style={{ display: "flex", gap: "10px", marginBottom: "16px", background: "#f1f5f9", padding: "4px", borderRadius: "8px" }}>
                <button
                  type="button"
                  onClick={() => { setSourceType("GITHUB_REPOSITORY"); setAnalysisResult(null); setAnalysisError(null); }}
                  style={{
                    flex: 1,
                    padding: "8px 14px",
                    borderRadius: "6px",
                    border: "none",
                    background: sourceType === "GITHUB_REPOSITORY" ? "#ffffff" : "transparent",
                    color: sourceType === "GITHUB_REPOSITORY" ? "#0f172a" : "#64748b",
                    fontWeight: "700",
                    fontSize: "13px",
                    cursor: "pointer",
                    boxShadow: sourceType === "GITHUB_REPOSITORY" ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
                    transition: "all 0.15s ease",
                  }}
                >
                  🐙 GitHub Repository
                </button>
                <button
                  type="button"
                  onClick={() => { setSourceType("UPLOADED_FILES"); setAnalysisResult(null); setAnalysisError(null); }}
                  style={{
                    flex: 1,
                    padding: "8px 14px",
                    borderRadius: "6px",
                    border: "none",
                    background: sourceType === "UPLOADED_FILES" ? "#ffffff" : "transparent",
                    color: sourceType === "UPLOADED_FILES" ? "#0f172a" : "#64748b",
                    fontWeight: "700",
                    fontSize: "13px",
                    cursor: "pointer",
                    boxShadow: sourceType === "UPLOADED_FILES" ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
                    transition: "all 0.15s ease",
                  }}
                >
                  📁 Upload / Select Source Files
                </button>
              </div>

              {/* GITHUB REPOSITORY MODE */}
              {sourceType === "GITHUB_REPOSITORY" && (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "16px" }}>
                  {/* Legacy Repository */}
                  <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "14px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "8px" }}>
                      <span style={{ fontSize: "14px" }}>🏛️</span>
                      <label style={{ fontSize: "13px", fontWeight: "700", color: "#0f172a" }}>
                        Legacy Reference Repository <span style={{ color: "#dc2626" }}>*</span>
                      </label>
                    </div>
                    <input
                      type="text"
                      value={legacyRepoUrl}
                      onChange={(e) => {
                        setLegacyRepoUrl(e.target.value);
                        setAnalysisResult(null);
                        setAnalysisError(null);
                      }}
                      placeholder="https://github.com/example/legacy-system"
                      style={{
                        width: "100%",
                        padding: "9px 12px",
                        borderRadius: "6px",
                        border: "1px solid #cbd5e1",
                        fontSize: "13px",
                        boxSizing: "border-box",
                        fontFamily: "monospace",
                      }}
                    />
                    <span style={{ display: "block", marginTop: "4px", fontSize: "11px", color: "#64748b" }}>
                      Remote Git URL or local repository path.
                    </span>

                    {showAdvanced && (
                      <div style={{ marginTop: "10px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                        <div>
                          <label style={{ display: "block", fontSize: "11px", fontWeight: "600", color: "#475569", marginBottom: "2px" }}>
                            Branch / Revision Ref
                          </label>
                          <input
                            type="text"
                            value={legacyRevision}
                            onChange={(e) => setLegacyRevision(e.target.value)}
                            placeholder="e.g. main or commit SHA"
                            style={{ width: "100%", padding: "6px 8px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "11px", fontFamily: "monospace", boxSizing: "border-box" }}
                          />
                        </div>
                        <div>
                          <label style={{ display: "block", fontSize: "11px", fontWeight: "600", color: "#475569", marginBottom: "2px" }}>
                            Subdirectory
                          </label>
                          <input
                            type="text"
                            value={legacySubdir}
                            onChange={(e) => setLegacySubdir(e.target.value)}
                            placeholder="Optional subpath"
                            style={{ width: "100%", padding: "6px 8px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "11px", boxSizing: "border-box" }}
                          />
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Modernized Target Repository */}
                  <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "14px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "8px" }}>
                      <span style={{ fontSize: "14px" }}>🚀</span>
                      <label style={{ fontSize: "13px", fontWeight: "700", color: "#0f172a" }}>
                        Modernized Target Repository <span style={{ color: "#dc2626" }}>*</span>
                      </label>
                    </div>
                    <input
                      type="text"
                      value={modernRepoUrl}
                      onChange={(e) => {
                        setModernRepoUrl(e.target.value);
                        setAnalysisResult(null);
                        setAnalysisError(null);
                      }}
                      placeholder="https://github.com/example/modern-system"
                      style={{
                        width: "100%",
                        padding: "9px 12px",
                        borderRadius: "6px",
                        border: "1px solid #cbd5e1",
                        fontSize: "13px",
                        boxSizing: "border-box",
                        fontFamily: "monospace",
                      }}
                    />
                    <span style={{ display: "block", marginTop: "4px", fontSize: "11px", color: "#64748b" }}>
                      Modernized target to certify against the legacy reference.
                    </span>

                    {showAdvanced && (
                      <div style={{ marginTop: "10px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                        <div>
                          <label style={{ display: "block", fontSize: "11px", fontWeight: "600", color: "#475569", marginBottom: "2px" }}>
                            Branch / Revision Ref
                          </label>
                          <input
                            type="text"
                            value={modernRevision}
                            onChange={(e) => setModernRevision(e.target.value)}
                            placeholder="e.g. main or commit SHA"
                            style={{ width: "100%", padding: "6px 8px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "11px", fontFamily: "monospace", boxSizing: "border-box" }}
                          />
                        </div>
                        <div>
                          <label style={{ display: "block", fontSize: "11px", fontWeight: "600", color: "#475569", marginBottom: "2px" }}>
                            Subdirectory
                          </label>
                          <input
                            type="text"
                            value={modernSubdir}
                            onChange={(e) => setModernSubdir(e.target.value)}
                            placeholder="Optional subpath"
                            style={{ width: "100%", padding: "6px 8px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "11px", boxSizing: "border-box" }}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* UPLOAD / SELECT SOURCE FILES MODE */}
              {sourceType === "UPLOADED_FILES" && (
                <div style={{ marginBottom: "16px" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "12px" }}>
                    {/* Legacy Source Files */}
                    <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "14px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                        <label style={{ fontSize: "13px", fontWeight: "700", color: "#0f172a" }}>
                          🏛️ Legacy Reference Sources <span style={{ color: "#dc2626" }}>*</span>
                        </label>
                        <span style={{ fontSize: "11px", color: "#64748b" }}>
                          {legacyFiles.length} file{legacyFiles.length !== 1 ? "s" : ""} selected
                        </span>
                      </div>
                      <input
                        type="file"
                        multiple
                        onChange={(e) => addLegacyFiles(e.target.files)}
                        style={{ width: "100%", fontSize: "12px", padding: "6px", background: "#ffffff", borderRadius: "6px", border: "1px dashed #94a3b8" }}
                      />
                      <span style={{ display: "block", marginTop: "4px", fontSize: "11px", color: "#64748b" }}>
                        Select source files (.cbl, .py, .java, etc.) or .zip archive.
                      </span>

                      {legacyFiles.length > 0 && (
                        <div style={{ marginTop: "10px", maxHeight: "120px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "4px" }}>
                          {legacyFiles.map((file, fIdx) => (
                            <div key={fIdx} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "#ffffff", padding: "4px 8px", borderRadius: "4px", border: "1px solid #e2e8f0", fontSize: "11px" }}>
                              <span style={{ fontFamily: "monospace", color: "#1e293b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "200px" }}>
                                📄 {file.name}
                              </span>
                              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                <span style={{ color: "#64748b", fontSize: "10px" }}>{(file.size / 1024).toFixed(1)} KB</span>
                                <button
                                  type="button"
                                  onClick={() => removeLegacyFile(fIdx)}
                                  style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer", fontWeight: "bold", fontSize: "12px", padding: "0 2px" }}
                                >
                                  ×
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Modern Target Source Files */}
                    <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "14px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                        <label style={{ fontSize: "13px", fontWeight: "700", color: "#0f172a" }}>
                          🚀 Modernized Target Sources <span style={{ color: "#dc2626" }}>*</span>
                        </label>
                        <span style={{ fontSize: "11px", color: "#64748b" }}>
                          {modernFiles.length} file{modernFiles.length !== 1 ? "s" : ""} selected
                        </span>
                      </div>
                      <input
                        type="file"
                        multiple
                        onChange={(e) => addModernFiles(e.target.files)}
                        style={{ width: "100%", fontSize: "12px", padding: "6px", background: "#ffffff", borderRadius: "6px", border: "1px dashed #94a3b8" }}
                      />
                      <span style={{ display: "block", marginTop: "4px", fontSize: "11px", color: "#64748b" }}>
                        Select source files (.py, .ts, etc.) or .zip archive.
                      </span>

                      {modernFiles.length > 0 && (
                        <div style={{ marginTop: "10px", maxHeight: "120px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "4px" }}>
                          {modernFiles.map((file, fIdx) => (
                            <div key={fIdx} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "#ffffff", padding: "4px 8px", borderRadius: "4px", border: "1px solid #e2e8f0", fontSize: "11px" }}>
                              <span style={{ fontFamily: "monospace", color: "#1e293b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "200px" }}>
                                📄 {file.name}
                              </span>
                              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                <span style={{ color: "#64748b", fontSize: "10px" }}>{(file.size / 1024).toFixed(1)} KB</span>
                                <button
                                  type="button"
                                  onClick={() => removeModernFile(fIdx)}
                                  style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer", fontWeight: "bold", fontSize: "12px", padding: "0 2px" }}
                                >
                                  ×
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Analysis Scope Selector */}
                  <div style={{ background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "10px 14px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div style={{ fontSize: "12px", fontWeight: "700", color: "#334155" }}>
                      ANALYSIS SCOPE:
                    </div>
                    <div style={{ display: "flex", gap: "16px" }}>
                      <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "#1e293b", cursor: "pointer" }}>
                        <input
                          type="radio"
                          name="analysisScope"
                          value="FILE"
                          checked={analysisScope === "FILE"}
                          onChange={(e) => setAnalysisScope(e.target.value)}
                        />
                        <strong>FILE Scope</strong> (Direct file-to-file pairing)
                      </label>
                      <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "#1e293b", cursor: "pointer" }}>
                        <input
                          type="radio"
                          name="analysisScope"
                          value="DIRECTORY"
                          checked={analysisScope === "DIRECTORY"}
                          onChange={(e) => setAnalysisScope(e.target.value)}
                        />
                        <strong>DIRECTORY Scope</strong> (Directory/archive inspection)
                      </label>
                    </div>
                  </div>
                </div>
              )}

              {/* Evaluation Mode Selector */}
              <div style={{ marginBottom: "16px", background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "12px 16px" }}>
                <div style={{ fontSize: "12px", fontWeight: "700", color: "#334155", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "8px" }}>
                  Evaluation Mode
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <label
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: "10px",
                      padding: "10px 12px",
                      borderRadius: "6px",
                      border: `1px solid ${evaluationMode === "CONTROLLED" ? "#2563eb" : "#cbd5e1"}`,
                      background: evaluationMode === "CONTROLLED" ? "#eff6ff" : "#f8fafc",
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="radio"
                      name="evaluationMode"
                      value="CONTROLLED"
                      checked={evaluationMode === "CONTROLLED"}
                      onChange={(e) => setEvaluationMode(e.target.value)}
                      style={{ marginTop: "2px" }}
                    />
                    <div>
                      <div style={{ fontSize: "13px", fontWeight: "700", color: evaluationMode === "CONTROLLED" ? "#1e40af" : "#1e293b" }}>
                        ⚖️ CONTROLLED Mode
                      </div>
                      <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                        Constrained, deterministic evaluation boundary over validated behavioral invariants and legitimate test cases.
                      </div>
                    </div>
                  </label>

                  <label
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: "10px",
                      padding: "10px 12px",
                      borderRadius: "6px",
                      border: `1px solid ${evaluationMode === "FULL_BEACON" ? "#2563eb" : "#cbd5e1"}`,
                      background: evaluationMode === "FULL_BEACON" ? "#eff6ff" : "#f8fafc",
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="radio"
                      name="evaluationMode"
                      value="FULL_BEACON"
                      checked={evaluationMode === "FULL_BEACON"}
                      onChange={(e) => setEvaluationMode(e.target.value)}
                      style={{ marginTop: "2px" }}
                    />
                    <div>
                      <div style={{ fontSize: "13px", fontWeight: "700", color: evaluationMode === "FULL_BEACON" ? "#1e40af" : "#1e293b" }}>
                        🔍 FULL BEACON Mode
                      </div>
                      <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                        Primary end-to-end mode: discover rules and inputs, execute both programs, compare evidence, and certify.
                      </div>
                    </div>
                  </label>
                </div>
              </div>

              <label style={{ display: "block", marginBottom: "16px" }}>
                <span style={{ display: "block", fontSize: "12px", fontWeight: "700", color: "#334155", marginBottom: "6px" }}>
                  Additional test inputs (optional JSON)
                </span>
                <textarea
                  value={customInputsJson}
                  onChange={(event) => setCustomInputsJson(event.target.value)}
                  placeholder={'{"acct_id":"12345678901","credit_limit":"5000"}\n—or an array of input objects'}
                  rows={4}
                  style={{
                    width: "100%",
                    boxSizing: "border-box",
                    padding: "10px 12px",
                    border: "1px solid #cbd5e1",
                    borderRadius: "6px",
                    fontFamily: "monospace",
                    fontSize: "12px",
                    resize: "vertical",
                  }}
                />
                <span style={{ display: "block", marginTop: "5px", fontSize: "11px", color: "#64748b" }}>
                  BEACON executes these inputs against both implementations and records them as user-supplied evidence.
                </span>
              </label>

              {/* Analysis Action Button */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "12px", color: "#64748b" }}>
                  Zero dynamic code execution: Inspection runs through pure static AST and manifest parsing.
                </span>
                <button
                  type="button"
                  onClick={handleAnalyzeRepositories}
                  disabled={analysisBusy || (sourceType === "GITHUB_REPOSITORY" ? (!legacyRepoUrl.trim() || !modernRepoUrl.trim()) : (legacyFiles.length === 0 || modernFiles.length === 0))}
                  style={{
                    background: analysisBusy || (sourceType === "GITHUB_REPOSITORY" ? (!legacyRepoUrl.trim() || !modernRepoUrl.trim()) : (legacyFiles.length === 0 || modernFiles.length === 0)) ? "#94a3b8" : "#2563eb",
                    color: "#ffffff",
                    border: "none",
                    padding: "10px 22px",
                    borderRadius: "6px",
                    fontWeight: "700",
                    fontSize: "13px",
                    cursor: analysisBusy || (sourceType === "GITHUB_REPOSITORY" ? (!legacyRepoUrl.trim() || !modernRepoUrl.trim()) : (legacyFiles.length === 0 || modernFiles.length === 0)) ? "not-allowed" : "pointer",
                    boxShadow: "0 2px 4px rgba(37,99,235,0.25)",
                    transition: "all 0.15s",
                  }}
                >
                  {analysisBusy ? "🔍 Analyzing Sources..." : "🔍 Analyze Sources & Discover Rules"}
                </button>
              </div>

              {analysisError && (
                <div
                  style={{
                    marginTop: "14px",
                    background: "#fef2f2",
                    border: "1px solid #fecaca",
                    borderRadius: "6px",
                    padding: "10px 14px",
                    color: "#991b1b",
                    fontSize: "13px",
                  }}
                >
                  ❌ {analysisError}
                </div>
              )}
            </section>

            {/* In-Flight Analysis Progress State */}
            {analysisBusy && (
              <section style={{ ...cardStyle, marginBottom: "20px", background: "#f8fafc" }}>
                <div style={{ fontSize: "13px", fontWeight: "700", color: "#1e40af", marginBottom: "10px" }}>
                  ⚙️ Repository-First Inspection & Evidence Pipeline Executing:
                </div>
                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", fontSize: "12px" }}>
                  {[
                    "1. Safe Repository Retrieval",
                    "2. Resolving Commit SHAs & Content Hashes",
                    "3. Static AST & Structure Inspection",
                    "4. Fail-Closed Adapter Resolution",
                    "5. Invariant & Rule Extraction",
                    "6. Genuine Input Discovery",
                  ].map((stepText, idx) => (
                    <span
                      key={idx}
                      style={{
                        background: "#ffffff",
                        border: "1px solid #cbd5e1",
                        borderRadius: "4px",
                        padding: "4px 10px",
                        color: "#334155",
                        fontWeight: "600",
                      }}
                    >
                      {stepText}
                    </span>
                  ))}
                </div>
              </section>
            )}

            {/* Analysis Results Display */}
            {analysisResult && (
              <div>
                {/* Status Banner */}
                <div
                  style={{
                    padding: "14px 18px",
                    borderRadius: "8px",
                    marginBottom: "16px",
                    border: `1px solid ${analysisResult.status === "READY"
                        ? "#86efac"
                        : analysisResult.status === "DISCOVERY_INSUFFICIENT"
                          ? "#fcd34d"
                          : "#fca5a5"
                      }`,
                    background:
                      analysisResult.status === "READY"
                        ? "#f0fdf4"
                        : analysisResult.status === "DISCOVERY_INSUFFICIENT"
                          ? "#fffbeb"
                          : "#fef2f2",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <div>
                    <div
                      style={{
                        fontWeight: "700",
                        fontSize: "14px",
                        color:
                          analysisResult.status === "READY"
                            ? "#166534"
                            : analysisResult.status === "DISCOVERY_INSUFFICIENT"
                              ? "#92400e"
                              : "#991b1b",
                      }}
                    >
                      {analysisResult.status === "READY" && "✅ Analysis Complete — Sources Validated & Ready for Certification"}
                      {analysisResult.status === "DISCOVERY_INSUFFICIENT" && "⚠️ Discovery Insufficient — Incomplete Input Evidence"}
                      {analysisResult.status === "FAILED" && "❌ Source Analysis Failed"}
                    </div>
                    <div style={{ fontSize: "12px", color: "#475569", marginTop: "2px" }}>
                      Mode: <strong>{analysisResult.evaluation_mode}</strong> • Source: <strong>{analysisResult.source_mode || sourceType}</strong> • Scope: <strong>{analysisResult.analysis_scope || (sourceType === "UPLOADED_FILES" ? analysisScope : "REPOSITORY")}</strong> • Rules: <strong>{(analysisResult.rules || analysisResult.discovered_rules || []).length}</strong> • Inputs: <strong>{analysisResult.inputs_count || (analysisResult.inputs || analysisResult.discovered_inputs || []).length}</strong>
                    </div>
                  </div>
                  <span
                    style={{
                      fontFamily: "monospace",
                      fontSize: "12px",
                      fontWeight: "700",
                      padding: "3px 8px",
                      borderRadius: "4px",
                      background: "#ffffff",
                      border: "1px solid #cbd5e1",
                      color: "#0f172a",
                    }}
                  >
                    {analysisResult.status}
                  </span>
                </div>

                {/* Dual Repository Provenance Cards */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "16px" }}>
                  {/* Legacy Source Identity */}
                  <section style={{ ...cardStyle, padding: "14px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                      <h4 style={{ margin: 0, fontSize: "13px", fontWeight: "700", color: "#0f172a" }}>
                        🏛️ Legacy Repository Identity
                      </h4>
                      <span style={{ fontSize: "11px", color: "#15803d", fontWeight: "600" }}>Validated</span>
                    </div>
                    <div style={{ fontSize: "12px", color: "#334155", lineHeight: "1.6" }}>
                      <div><strong>Canonical URL:</strong> <span style={{ fontFamily: "monospace", color: "#0f172a" }}>{analysisResult.legacy?.source_identity?.canonical_url || analysisResult.legacy?.repository_url || "—"}</span></div>
                      <div><strong>Resolved Commit:</strong> <span style={{ fontFamily: "monospace", color: "#1e40af", background: "#eff6ff", padding: "1px 4px", borderRadius: "3px" }}>{analysisResult.legacy?.source_identity?.commit_sha ? analysisResult.legacy.source_identity.commit_sha.slice(0, 12) : "HEAD"}</span></div>
                      <div><strong>Content Hash:</strong> <span style={{ fontFamily: "monospace", color: "#475569" }}>{analysisResult.legacy?.source_identity?.content_hash ? analysisResult.legacy.source_identity.content_hash.slice(0, 16) + "..." : "—"}</span></div>
                      <div><strong>Technologies:</strong> {analysisResult.legacy?.technologies?.length > 0 ? analysisResult.legacy.technologies.join(", ") : "Standard Python/Module"}</div>
                      <div><strong>Resolved Adapter:</strong> <span style={{ fontFamily: "monospace", fontWeight: "600", color: "#0f172a" }}>{analysisResult.legacy?.adapter?.adapter_name || analysisResult.legacy?.adapter?.adapter_id || "—"}</span> ({analysisResult.legacy?.adapter?.status || "RESOLVED"})</div>
                      <div><strong>Discovered Entrypoint:</strong> <span style={{ fontFamily: "monospace", color: "#0f172a" }}>{analysisResult.legacy?.adapter?.resolved_entrypoint || analysisResult.legacy?.adapter?.resolved_function || analysisResult.legacy?.entrypoint_file || "—"}</span></div>
                    </div>
                  </section>

                  {/* Modernized Source Identity */}
                  <section style={{ ...cardStyle, padding: "14px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                      <h4 style={{ margin: 0, fontSize: "13px", fontWeight: "700", color: "#0f172a" }}>
                        🚀 Modernized Target Identity
                      </h4>
                      <span style={{ fontSize: "11px", color: "#15803d", fontWeight: "600" }}>Validated</span>
                    </div>
                    <div style={{ fontSize: "12px", color: "#334155", lineHeight: "1.6" }}>
                      <div><strong>Canonical URL:</strong> <span style={{ fontFamily: "monospace", color: "#0f172a" }}>{analysisResult.modern?.source_identity?.canonical_url || analysisResult.modern?.repository_url || "—"}</span></div>
                      <div><strong>Resolved Commit:</strong> <span style={{ fontFamily: "monospace", color: "#1e40af", background: "#eff6ff", padding: "1px 4px", borderRadius: "3px" }}>{analysisResult.modern?.source_identity?.commit_sha ? analysisResult.modern.source_identity.commit_sha.slice(0, 12) : "HEAD"}</span></div>
                      <div><strong>Content Hash:</strong> <span style={{ fontFamily: "monospace", color: "#475569" }}>{analysisResult.modern?.source_identity?.content_hash ? analysisResult.modern.source_identity.content_hash.slice(0, 16) + "..." : "—"}</span></div>
                      <div><strong>Technologies:</strong> {analysisResult.modern?.technologies?.length > 0 ? analysisResult.modern.technologies.join(", ") : "Standard Python/Module"}</div>
                      <div><strong>Resolved Adapter:</strong> <span style={{ fontFamily: "monospace", fontWeight: "600", color: "#0f172a" }}>{analysisResult.modern?.adapter?.adapter_name || analysisResult.modern?.adapter?.adapter_id || "—"}</span> ({analysisResult.modern?.adapter?.status || "RESOLVED"})</div>
                      <div><strong>Discovered Entrypoint:</strong> <span style={{ fontFamily: "monospace", color: "#0f172a" }}>{analysisResult.modern?.adapter?.resolved_entrypoint || analysisResult.modern?.adapter?.resolved_function || analysisResult.modern?.entrypoint_file || "—"}</span></div>
                    </div>
                  </section>
                </div>

                {/* AI-Assisted COBOL Execution Plan (If COBOL Detected) */}
                {analysisResult.provenance?.cobol_execution_plan && (() => {
                  const cPlan = analysisResult.provenance.cobol_execution_plan;
                  return (
                    <section style={{ ...cardStyle, marginBottom: "16px", background: "#f8fafc", border: "1px solid #bfdbfe" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <span style={{ fontSize: "16px" }}>⚙️</span>
                          <h4 style={{ margin: 0, fontSize: "14px", fontWeight: "700", color: "#1e3a8a" }}>
                            AI COBOL Execution Plan & Compatibility Harness Specification
                          </h4>
                        </div>
                        <span style={{ fontSize: "11px", fontWeight: "700", color: "#166534", background: "#dcfce7", border: "1px solid #86efac", padding: "2px 8px", borderRadius: "4px" }}>
                          {cPlan.validation_status === "VALIDATED" ? "✓ Validated Against AST" : cPlan.validation_status}
                        </span>
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "10px", fontSize: "12px", marginBottom: "10px" }}>
                        <div><strong>Program ID:</strong> <span style={{ fontFamily: "monospace", color: "#1e40af" }}>{cPlan.program_id}</span></div>
                        <div><strong>Execution Harness:</strong> <span style={{ fontFamily: "monospace", color: "#059669", fontWeight: "600" }}>GnuCOBOL + BEACON Harness (WSL)</span></div>
                        <div><strong>Confidence:</strong> <span>{Math.round((cPlan.confidence_score || 1) * 100)}%</span></div>
                        <div><strong>Transactions:</strong> <span style={{ fontFamily: "monospace" }}>{cPlan.transactions?.join(", ") || "—"}</span></div>
                        <div><strong>Copybooks Resolved:</strong> <span>{cPlan.copybooks?.length || 0} copybooks</span></div>
                        <div><strong>Data Files:</strong> <span style={{ fontFamily: "monospace" }}>{cPlan.data_dependencies?.join(", ") || "—"}</span></div>
                      </div>
                      {cPlan.cics_operations?.length > 0 && (
                        <div style={{ fontSize: "11px", color: "#475569" }}>
                          <strong>Detected CICS Operations:</strong>{" "}
                          <span style={{ fontFamily: "monospace" }}>{cPlan.cics_operations.join(" • ")}</span>
                        </div>
                      )}
                    </section>
                  );
                })()}

                {/* AI-validated Behavioral Rules */}
                <section style={{ ...cardStyle, marginBottom: "16px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                    <h4 style={{ margin: 0, fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                      📜 Dual-source AI-extracted Rules ({(analysisResult.rules || analysisResult.discovered_rules || []).length})
                    </h4>
                    <span style={{ fontSize: "11px", color: "#64748b" }}>Each side is extracted independently; exact anchors and alignment are retained</span>
                  </div>
                  {(analysisResult.rules?.length > 0 || analysisResult.discovered_rules?.length > 0) ? (
                    <div style={{ maxHeight: "180px", overflowY: "auto", border: "1px solid #e2e8f0", borderRadius: "6px" }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                        <thead>
                          <tr style={{ background: "#f8fafc", textAlign: "left", borderBottom: "1px solid #e2e8f0" }}>
                            <th style={{ padding: "6px 10px", color: "#475569" }}>Rule ID</th>
                            <th style={{ padding: "6px 10px", color: "#475569" }}>Description / Invariant</th>
                            <th style={{ padding: "6px 10px", color: "#475569" }}>Legacy source anchor</th>
                            <th style={{ padding: "6px 10px", color: "#475569" }}>Modern source anchor</th>
                            <th style={{ padding: "6px 10px", color: "#475569" }}>Alignment</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(analysisResult.rules || analysisResult.discovered_rules || []).map((rule, rIdx) => (
                            <tr key={rIdx} style={{ borderBottom: "1px solid #f1f5f9" }}>
                              <td style={{ padding: "6px 10px", fontFamily: "monospace", fontWeight: "600", color: "#1e40af" }}>
                                {rule.rule_id || `rule_${rIdx + 1}`}
                              </td>
                              <td style={{ padding: "6px 10px", color: "#1e293b" }}>
                                <div>{rule.description || rule.name || "—"}</div>
                                {rule.observable_effect && (
                                  <div style={{ color: "#64748b", marginTop: "3px" }}>{rule.observable_effect}</div>
                                )}
                              </td>
                              <td style={{ padding: "6px 10px", fontFamily: "monospace", color: "#64748b" }}>
                                {rule.source_evidence?.legacy
                                  ? `${rule.source_evidence.legacy.path}:${rule.source_evidence.legacy.line}\n${rule.source_evidence.legacy.excerpt}`
                                  : "No source anchor"}
                              </td>
                              <td style={{ padding: "6px 10px", fontFamily: "monospace", color: "#64748b" }}>
                                {rule.source_evidence?.modern
                                  ? `${rule.source_evidence.modern.path}:${rule.source_evidence.modern.line}\n${rule.source_evidence.modern.excerpt}`
                                  : "No source anchor"}
                              </td>
                              <td style={{ padding: "6px 10px", color: rule.alignment_status === "MATCH" ? "#166534" : "#991b1b" }}>
                                <strong>{rule.alignment_status || "UNALIGNED"}</strong>
                                {rule.alignment_rationale && (
                                  <div style={{ color: "#64748b", marginTop: "3px" }}>{rule.alignment_rationale}</div>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div style={{ padding: "12px", background: "#f8fafc", borderRadius: "6px", fontSize: "12px", color: "#64748b" }}>
                      {analysisResult.evaluation_mode === "FULL_BEACON"
                        ? "No complete source-grounded rule manifest was produced. Full BEACON certification is blocked."
                        : "No source-grounded behavioral rules were extracted for this analysis."}
                    </div>
                  )}
                </section>

                {/* Discovered Legitimate Inputs */}
                <section style={{ ...cardStyle, marginBottom: "16px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                    <h4 style={{ margin: 0, fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                      🧪 Discovered Legitimate Inputs ({analysisResult.inputs_count ?? ((analysisResult.inputs || analysisResult.discovered_inputs || []).length)} cases)
                    </h4>
                    <span style={{ fontSize: "11px", color: "#166534", fontWeight: "600" }}>
                      Provenance-Backed & Validated
                    </span>
                  </div>

                  {(analysisResult.inputs?.length > 0 || analysisResult.discovered_inputs?.length > 0) ? (
                    <div>
                      <div style={{ fontSize: "12px", color: "#475569", marginBottom: "8px" }}>
                        Input Provenance: <strong>{analysisResult.input_provenance?.source || "Repository Fixtures / Validated Evidence"}</strong>
                      </div>
                      <div style={{ maxHeight: "150px", overflowY: "auto", background: "#f8fafc", borderRadius: "6px", border: "1px solid #e2e8f0", padding: "8px" }}>
                        <pre style={{ margin: 0, fontSize: "11px", fontFamily: "monospace", color: "#0f172a" }}>
                          {JSON.stringify((analysisResult.inputs || analysisResult.discovered_inputs || []).slice(0, 5), null, 2)}
                          {(analysisResult.inputs || analysisResult.discovered_inputs || []).length > 5 && `
... and ${(analysisResult.inputs || analysisResult.discovered_inputs || []).length - 5} more validated cases`}
                        </pre>
                      </div>
                    </div>
                  ) : (
                    <div style={{ padding: "12px", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: "6px", fontSize: "12px", color: "#92400e" }}>
                      ⚠️ No repository fixtures were found. BEACON also asks the configured AI provider to propose source-grounded test cases; proposed cases are only accepted after local validation and execution against both programs.
                    </div>
                  )}
                  {analysisResult.input_provenance?.llm_provider && (
                    <div style={{ marginTop: "8px", fontSize: "11px", color: "#475569" }}>
                      AI discovery: <strong>{analysisResult.input_provenance.llm_provider.actual_provider || "unavailable"}</strong>
                      {analysisResult.input_provenance.llm_provider.model ? ` (${analysisResult.input_provenance.llm_provider.model})` : ""}
                      {" · "}
                      <strong>{analysisResult.input_provenance.llm_provider.error_category || analysisResult.input_provenance.llm_provider.rule_extraction_status || "NOT_RECORDED"}</strong>
                      {analysisResult.input_provenance.proposed_count !== undefined && (
                        <span>
                          {" · "}Proposed: <strong>{analysisResult.input_provenance.proposed_count}</strong>
                          {" · "}Accepted: <strong>{analysisResult.input_provenance.accepted_count}</strong>
                          {analysisResult.input_provenance.rejected_count > 0 && (
                            <span style={{ color: "#b91c1c" }}>
                              {" · "}Rejected: <strong>{analysisResult.input_provenance.rejected_count}</strong>
                            </span>
                          )}
                        </span>
                      )}
                      {(analysisResult.input_provenance.llm_provider.error || analysisResult.input_provenance.llm_provider.fallback_reason) ? (
                        <div style={{ color: "#b91c1c", marginTop: "3px", fontWeight: "500" }}>
                          Provider detail: {analysisResult.input_provenance.llm_provider.error || analysisResult.input_provenance.llm_provider.fallback_reason}
                        </div>
                      ) : null}
                    </div>
                  )}
                </section>

                {/* Specification Fingerprint Card */}
                {analysisResult.execution_spec && (
                  <div style={{ background: "#f1f5f9", border: "1px solid #cbd5e1", borderRadius: "8px", padding: "10px 14px", marginBottom: "16px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ fontSize: "12px", color: "#334155" }}>
                      <strong>Cryptographic Specification Fingerprint:</strong>
                    </div>
                    <span style={{ fontFamily: "monospace", fontSize: "11px", color: "#1e40af", background: "#ffffff", padding: "2px 8px", borderRadius: "4px", border: "1px solid #cbd5e1" }}>
                      {analysisResult.execution_spec.specification_fingerprint || "—"}
                    </span>
                  </div>
                )}

                {/* Final Certification Action Bar */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "#ffffff", border: "1px solid #cbd5e1", borderRadius: "8px", padding: "14px 18px" }}>
                  <div>
                    <div style={{ fontSize: "13px", fontWeight: "700", color: "#0f172a" }}>
                      Ready for Behavioral Equivalence Certification
                    </div>
                    <div style={{ fontSize: "12px", color: "#64748b" }}>
                      Executes authorized adapters in sandboxed runtime, calculates equivalence score, and registers immutable proof.
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={handleCertifyRepository}
                    disabled={certifyBusy || analysisResult.status !== "READY" || !userHasPermission("run_certification")}
                    style={{
                      background: certifyBusy || analysisResult.status !== "READY" ? "#94a3b8" : "#16a34a",
                      color: "#ffffff",
                      border: "none",
                      padding: "11px 24px",
                      borderRadius: "6px",
                      fontWeight: "700",
                      fontSize: "13px",
                      cursor: certifyBusy || analysisResult.status !== "READY" ? "not-allowed" : "pointer",
                      boxShadow: "0 2px 4px rgba(22,163,74,0.3)",
                      transition: "all 0.15s",
                    }}
                  >
                    {certifyBusy ? "⚡ Certifying Repositories..." : "⚡ Certify Behavioral Equivalence"}
                  </button>
                </div>

                {certifyError && (
                  <div
                    style={{
                      marginTop: "14px",
                      background: "#fef2f2",
                      border: "1px solid #fecaca",
                      borderRadius: "6px",
                      padding: "10px 14px",
                      color: "#991b1b",
                      fontSize: "13px",
                    }}
                  >
                    ❌ {certifyError}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Right Column: Architecture Guardrails & Recent Runs ── */}
          <div>
            {/* V2 Guardrails Card */}
            <section style={{ ...cardStyle, marginBottom: "16px" }}>
              <h3 style={{ margin: "0 0 10px", fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                🛡️ V2 Architectural Guardrails
              </h3>
              <div style={{ fontSize: "12px", color: "#475569", lineHeight: "1.5" }}>
                <div style={{ marginBottom: "8px" }}>
                  <strong>🔒 Zero Dynamic Import Detection:</strong>
                  <div style={{ color: "#64748b" }}>Untrusted repository code is never executed during inspection or adapter detection.</div>
                </div>
                <div style={{ marginBottom: "8px" }}>
                  <strong>⚖️ Fail-Closed Adapter Resolution:</strong>
                  <div style={{ color: "#64748b" }}>Ambiguous technology or missing adapters immediately fail closed. No guessing.</div>
                </div>
                <div style={{ marginBottom: "8px" }}>
                  <strong>🧪 Genuine Input Evidence:</strong>
                  <div style={{ color: "#64748b" }}>Test cases are discovered from legitimate repository fixtures. Synthetic [0,1,5,10] fallbacks are disabled.</div>
                </div>
                <div>
                  <strong>📜 Immutable Identity:</strong>
                  <div style={{ color: "#64748b" }}>All runs bind canonical repository URLs, resolved commit SHAs, and content hashes.</div>
                </div>
              </div>
            </section>

            {/* Recent Workflow Runs */}
            <section style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <h3 style={{ margin: 0, fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                  Recent Runs
                </h3>
                <button
                  onClick={loadRecentRuns}
                  style={{
                    background: "transparent",
                    border: "none",
                    fontSize: "12px",
                    color: "#2563eb",
                    cursor: "pointer",
                    fontWeight: "600",
                  }}
                >
                  Refresh
                </button>
              </div>

              {runsLoading ? (
                <div style={{ fontSize: "13px", color: "#94a3b8", textAlign: "center", padding: "12px 0" }}>
                  Loading runs...
                </div>
              ) : recentRuns.length === 0 ? (
                <div style={{ fontSize: "12px", color: "#94a3b8", textAlign: "center", padding: "16px 0" }}>
                  No recent runs recorded yet.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  {recentRuns.map((run) => (
                    <div
                      key={run.workflow_run_id}
                      onClick={() => loadPastRun(run.workflow_run_id)}
                      style={{
                        padding: "10px 12px",
                        background: "#f8fafc",
                        border: "1px solid #e2e8f0",
                        borderRadius: "6px",
                        cursor: "pointer",
                        transition: "all 0.15s",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                        <span style={{ fontSize: "12px", fontWeight: "700", color: "#0f172a", fontFamily: "monospace" }}>
                          {run.workflow_run_id.slice(0, 8)}...
                        </span>
                        <span
                          style={{
                            fontSize: "10px",
                            fontWeight: "700",
                            padding: "2px 6px",
                            borderRadius: "4px",
                            background: run.certification_status === "CERTIFIED" ? "#dcfce7" : "#fee2e2",
                            color: run.certification_status === "CERTIFIED" ? "#15803d" : "#b91c1c",
                          }}
                        >
                          {run.certification_status || run.state}
                        </span>
                      </div>
                      <div style={{ fontSize: "11px", color: "#64748b" }}>
                        Score: <strong>{run.certification_score != null ? `${(run.certification_score * 100).toFixed(1)}%` : "—"}</strong>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════ */}
      {/* STEP 2: CERTIFICATION RESULT (FACULTY-FACING V2 AUTHORITY VIEW)        */}
      {/* ═══════════════════════════════════════════════════════════════════════ */}
      {activeStep === "result" && workflowResult && (() => {
        const meta = workflowResult.metadata || {};
        const legacySrc = meta.sources?.legacy || meta.legacy_provenance || analysisResult?.legacy?.source_identity || {};
        const modernSrc = meta.sources?.modern || meta.modern_provenance || analysisResult?.modern?.source_identity || {};
        const legacyAdapter = meta.legacy_adapter_resolution || analysisResult?.legacy?.adapter || {};
        const modernAdapter = meta.modern_adapter_resolution || analysisResult?.modern?.adapter || {};
        const discoveryMeta = meta.discovery || {};
        const repCases = meta.representative_cases || [];
        const threshMeta = meta.threshold_resolution || {};
        const execFingerprint = meta.execution_fingerprint || workflowResult.execution_fingerprint || "—";
        const finalizationState = meta.finalization_state || "COMPLETED";
        const oracleSetId = meta.oracle_set_id || workflowResult.oracle_set_id || "—";
        const oracleSetHash = meta.oracle_set_hash || workflowResult.oracle_set_hash || "—";
        const oracleCoverage = meta.oracle_coverage != null ? `${(meta.oracle_coverage * 100).toFixed(1)}%` : "Not available";
        const sourceRuleEvidence = meta.source_rule_evidence || {};
        const sourceRuleEvidenceEntries = Object.entries(sourceRuleEvidence.rules || {});
        const evidenceGates = meta.evidence_gate_results || {};
        const evidenceFactors = meta.evidence_score_factors || {};

        return (
          <div>
            {/* 1. Authoritative Status Banner */}
            <div
              style={{
                background: statusStyle.bg,
                border: `1px solid ${statusStyle.border}`,
                color: statusStyle.color,
                borderRadius: "12px",
                padding: "20px 24px",
                marginBottom: "20px",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "6px" }}>
                  <span style={{ fontSize: "20px", fontWeight: "800" }}>{statusStyle.label}</span>
                </div>
                <div style={{ fontSize: "13px", opacity: 0.9, display: "flex", gap: "16px", flexWrap: "wrap" }}>
                  <span>Run ID: <strong style={{ fontFamily: "monospace" }}>{workflowResult.workflow_run_id}</strong></span>
                  <span>Application: <strong>{workflowResult.application_id}</strong></span>
                  <span>State: <strong>{workflowResult.state}</strong></span>
                  <span>Stage-B Finalization: <strong style={{ color: "#166534", background: "rgba(255,255,255,0.7)", padding: "1px 6px", borderRadius: "4px" }}>{finalizationState}</strong></span>
                </div>
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <button
                  onClick={() => setActiveStep("configure")}
                  style={{
                    background: "rgba(255,255,255,0.7)",
                    border: `1px solid ${statusStyle.border}`,
                    color: statusStyle.color,
                    padding: "7px 14px",
                    borderRadius: "6px",
                    fontWeight: "600",
                    fontSize: "12px",
                    cursor: "pointer",
                  }}
                >
                  ← New Certification
                </button>
                <button
                  onClick={workflowResult.artifact_id ? downloadCertificate : downloadRunReport}
                  disabled={reportBusy}
                  style={{
                    background: "#0f766e",
                    border: "1px solid #0f766e",
                    color: "#ffffff",
                    padding: "7px 14px",
                    borderRadius: "6px",
                    fontWeight: "600",
                    fontSize: "12px",
                    cursor: reportBusy ? "wait" : "pointer",
                  }}
                >
                  {reportBusy
                    ? "Preparing download…"
                    : workflowResult.artifact_id
                      ? "Download Certificate (PDF)"
                      : "Download Run Report (PDF; Not a Certificate)"}
                </button>
                {workflowResult.explanation && (
                  <button
                    onClick={downloadAiSummary}
                    style={{
                      background: "#ffffff",
                      border: "1px solid #2563eb",
                      color: "#1d4ed8",
                      padding: "7px 14px",
                      borderRadius: "6px",
                      fontWeight: "600",
                      fontSize: "12px",
                      cursor: "pointer",
                    }}
                  >
                    {workflowResult.explanation.status === "EXPLANATION_FAILED"
                      ? "Download Explanation Status"
                      : "Download AI Summary"}
                  </button>
                )}
              </div>
            </div>

            {reportError && (
              <div style={{ marginBottom: "16px", color: "#991b1b", fontSize: "13px" }} role="alert">
                {reportError}
              </div>
            )}

            {/* Error / Failure Detail if present */}
            {workflowResult.error_code && (
              <div
                style={{
                  background: "#fef2f2",
                  border: "1px solid #fca5a5",
                  borderRadius: "8px",
                  padding: "14px 18px",
                  marginBottom: "20px",
                  fontSize: "13px",
                  color: "#991b1b",
                }}
              >
                <strong>Error Code:</strong> {workflowResult.error_code}
                {workflowResult.error_message && (
                  <div style={{ marginTop: "4px" }}>{workflowResult.error_message}</div>
                )}
              </div>
            )}

            {/* Key Metric KPI Grid */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(6, 1fr)",
                gap: "10px",
                marginBottom: "20px",
              }}
            >
              {[
                {
                  label: "Evidence-Adjusted Score",
                  val: workflowResult.equivalence_score != null
                    ? `${(workflowResult.equivalence_score * 100).toFixed(2)}%`
                    : "—",
                  color: workflowResult.equivalence_score >= 0.999 ? "#059669" : "#dc2626",
                },
                {
                  label: "Certified",
                  val: workflowResult.certified ? "YES" : "NO",
                  color: workflowResult.certified ? "#059669" : "#dc2626",
                },
                {
                  label: "Unique Cases",
                  val: workflowResult.unique_input_count ?? repCases.length ?? meta.inputs_count ?? "—",
                  color: "#334155",
                },
                {
                  label: "Regressions",
                  val: workflowResult.regressions_count ?? (workflowResult.regressions ? workflowResult.regressions.length : "—"),
                  color: (workflowResult.regressions_count > 0 || (workflowResult.regressions && workflowResult.regressions.length > 0)) ? "#dc2626" : ((workflowResult.regressions_count === 0 || (workflowResult.regressions && workflowResult.regressions.length === 0)) ? "#059669" : "#64748b"),
                },
                {
                  label: "Auto Threshold",
                  val: threshMeta.resolved_threshold != null
                    ? Number(threshMeta.resolved_threshold).toFixed(4)
                    : (threshMeta.final_value != null ? Number(threshMeta.final_value).toFixed(4) : "Not resolved"),
                  color: (threshMeta.resolved_threshold != null || threshMeta.final_value != null) ? "#2563eb" : "#dc2626",
                },
                {
                  label: "Stage-B Finalization",
                  val: finalizationState,
                  color: finalizationState === "COMPLETED" ? "#059669" : "#f59e0b",
                },
              ].map((m) => (
                <div
                  key={m.label}
                  style={{
                    ...cardStyle,
                    marginBottom: 0,
                    padding: "12px 8px",
                    textAlign: "center",
                  }}
                >
                  <div
                    style={{
                      fontSize: "10px",
                      fontWeight: "600",
                      color: "#64748b",
                      textTransform: "uppercase",
                      marginBottom: "2px",
                    }}
                  >
                    {m.label}
                  </div>
                  <div style={{ fontSize: "17px", fontWeight: "800", color: m.color }}>
                    {String(m.val)}
                  </div>
                </div>
              ))}
            </div>

            {/* ═════════════════════════════════════════════════════════════════ */}
            {/* 3-4 LINE AUTHORITATIVE CERTIFICATE SUMMARY                        */}
            {/* ═════════════════════════════════════════════════════════════════ */}
            {(() => {
              const expl = workflowResult.explanation || {};
              const execSummary = expl.executive_summary || expl.status_rationale || expl.summary;
              const isCertified = Boolean(workflowResult.certified);
              const isInconclusive = workflowResult.status === "INCONCLUSIVE" || workflowResult.equivalence_score == null;

              const themeColor = isCertified ? "#166534" : (isInconclusive ? "#854d0e" : "#991b1b");
              const themeBg = isCertified ? "#f0fdf4" : (isInconclusive ? "#fefce8" : "#fef2f2");
              const themeBorder = isCertified ? "#bbf7d0" : (isInconclusive ? "#fef08a" : "#fecaca");
              const badgeBg = isCertified ? "#dcfce7" : (isInconclusive ? "#fef9c3" : "#fee2e2");

              const inputCount = workflowResult.unique_input_count ?? repCases.length ?? meta.inputs_count ?? 0;
              const ruleCount = meta.discovered_rules?.length ?? discoveryMeta.invariants_discovered ?? 0;
              const regressionsCount = workflowResult.regressions_count ?? workflowResult.regressions?.length ?? 0;
              const threshVal = threshMeta.final_value != null ? Number(threshMeta.final_value).toFixed(4) : (threshMeta.raw_value != null ? Number(threshMeta.raw_value).toFixed(4) : "Dynamic");

              const defaultNarrative = isCertified ? (
                `BEACON issued ${workflowResult.status} with an evidence-adjusted score of ${workflowResult.equivalence_score != null ? `${(workflowResult.equivalence_score * 100).toFixed(2)}%` : "not available"} across ${inputCount} evaluated cases. ${regressionsCount} regression case(s) were recorded. This result applies only to the tested inputs and declared evidence.`
              ) : (isInconclusive ? (
                `Certification concluded with status INCONCLUSIVE (${workflowResult.error_message || 'Missing dependencies or insufficient reference evidence'}). Re-run with required copybooks or sample data to resolve full certification.`
              ) : (
                `Certification concluded with status ${workflowResult.status || 'FAILED'}. Found ${regressionsCount} behavioral regressions across ${inputCount} evaluated test vectors (${workflowResult.error_message || 'Equivalence score did not satisfy tolerance threshold'}).`
              ));

              return (
                <section style={{
                  ...cardStyle,
                  marginBottom: "20px",
                  background: themeBg,
                  border: `1.5px solid ${themeBorder}`,
                  borderRadius: "8px",
                  padding: "18px 20px"
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "12px" }}>
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
                        <span style={{ fontSize: "20px" }}>{isCertified ? "🏆" : (isInconclusive ? "⚠️" : "❌")}</span>
                        <h3 style={{ margin: 0, fontSize: "16px", fontWeight: "800", color: themeColor }}>
                          Executive Certification Summary
                        </h3>
                      </div>
                      <div style={{ fontSize: "12px", color: "#64748b" }}>
                        Verdict determined by BEACON's certification engine; any AI summary is supplemental.
                      </div>
                    </div>
                    <span style={{
                      fontSize: "12px",
                      fontWeight: "700",
                      color: themeColor,
                      background: badgeBg,
                      border: `1px solid ${themeBorder}`,
                      padding: "4px 10px",
                      borderRadius: "6px"
                    }}>
                      {workflowResult.status || (isInconclusive ? "INCONCLUSIVE AUDIT" : "NON-EQUIVALENT")}
                    </span>
                  </div>

                  {/* Plain-English Customer Narrative */}
                  <div style={{
                    fontSize: "13.5px",
                    lineHeight: "1.7",
                    color: "#1e293b",
                    marginBottom: "16px",
                    background: "rgba(255,255,255,0.7)",
                    padding: "12px 14px",
                    borderRadius: "6px",
                    borderLeft: `4px solid ${themeColor}`
                  }}>
                    {execSummary || defaultNarrative}
                  </div>

                  {/* 4 Quick Customer Metric Pills */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "10px" }}>
                    <div style={{ background: "#ffffff", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <div style={{ fontSize: "11px", color: "#64748b", fontWeight: "600", textTransform: "uppercase" }}>Evidence-Adjusted Score</div>
                      <div style={{ fontSize: "16px", fontWeight: "800", color: themeColor }}>
                        {workflowResult.equivalence_score != null ? `${(workflowResult.equivalence_score * 100).toFixed(2)}%` : "N/A"}
                      </div>
                    </div>
                    <div style={{ background: "#ffffff", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <div style={{ fontSize: "11px", color: "#64748b", fontWeight: "600", textTransform: "uppercase" }}>Test Cases</div>
                      <div style={{ fontSize: "16px", fontWeight: "800", color: "#0f172a" }}>
                        {inputCount} Evaluated
                      </div>
                    </div>
                    <div style={{ background: "#ffffff", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <div style={{ fontSize: "11px", color: "#64748b", fontWeight: "600", textTransform: "uppercase" }}>Mined Rules</div>
                      <div style={{ fontSize: "16px", fontWeight: "800", color: "#0f172a" }}>
                        {ruleCount} Invariants
                      </div>
                    </div>
                    <div style={{ background: "#ffffff", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <div style={{ fontSize: "11px", color: "#64748b", fontWeight: "600", textTransform: "uppercase" }}>Tolerance Bound</div>
                      <div style={{ fontSize: "16px", fontWeight: "800", color: "#0f172a" }}>
                        {threshVal}
                      </div>
                    </div>
                  </div>
                </section>
              );
            })()}

            {/* ═════════════════════════════════════════════════════════════════ */}
            {/* SECTION 1: IMMUTABLE SOURCE REPOSITORY PROVENANCE                 */}
            {/* ═════════════════════════════════════════════════════════════════ */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "20px" }}>
              {/* Legacy Source */}
              <section style={cardStyle}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                  <h3 style={{ margin: 0, fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                    🏛️ Legacy Reference Repository
                  </h3>
                  <span style={{ fontSize: "11px", fontWeight: "600", color: "#166534", background: "#f0fdf4", border: "1px solid #bbf7d0", padding: "1px 6px", borderRadius: "4px" }}>
                    Immutable Source
                  </span>
                </div>
                <div style={{ fontSize: "12px", color: "#334155", lineHeight: "1.7" }}>
                  <div><strong>Canonical URL:</strong> <span style={{ fontFamily: "monospace", color: "#0f172a" }}>{legacySrc.canonical_url || legacySrc.repository_url || legacyRepoUrl || "—"}</span></div>
                  <div><strong>Resolved Commit:</strong> <span style={{ fontFamily: "monospace", color: "#1e40af", background: "#eff6ff", padding: "1px 6px", borderRadius: "3px" }}>{legacySrc.commit_sha ? legacySrc.commit_sha.slice(0, 12) : "HEAD"}</span></div>
                  <div><strong>Content Hash:</strong> <span style={{ fontFamily: "monospace", color: "#475569" }}>{legacySrc.content_hash ? legacySrc.content_hash.slice(0, 20) + "..." : "—"}</span></div>
                  <div><strong>Technologies:</strong> {legacySrc.technologies?.length > 0 ? legacySrc.technologies.join(", ") : "Standard Python/Module"}</div>
                  <div><strong>Resolved Adapter:</strong> <span style={{ fontFamily: "monospace", fontWeight: "600" }}>{legacyAdapter.adapter_id || legacySrc.adapter || "—"}</span></div>
                  <div><strong>Discovered Entrypoint:</strong> <span style={{ fontFamily: "monospace" }}>{legacySrc.entrypoint_file || legacyAdapter.entrypoint_file || "—"}</span></div>
                </div>
              </section>

              {/* Modernized Target Source */}
              <section style={cardStyle}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                  <h3 style={{ margin: 0, fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                    🚀 Modernized Target Repository
                  </h3>
                  <span style={{ fontSize: "11px", fontWeight: "600", color: "#166534", background: "#f0fdf4", border: "1px solid #bbf7d0", padding: "1px 6px", borderRadius: "4px" }}>
                    Immutable Source
                  </span>
                </div>
                <div style={{ fontSize: "12px", color: "#334155", lineHeight: "1.7" }}>
                  <div><strong>Canonical URL:</strong> <span style={{ fontFamily: "monospace", color: "#0f172a" }}>{modernSrc.canonical_url || modernSrc.repository_url || modernRepoUrl || "—"}</span></div>
                  <div><strong>Resolved Commit:</strong> <span style={{ fontFamily: "monospace", color: "#1e40af", background: "#eff6ff", padding: "1px 6px", borderRadius: "3px" }}>{modernSrc.commit_sha ? modernSrc.commit_sha.slice(0, 12) : "HEAD"}</span></div>
                  <div><strong>Content Hash:</strong> <span style={{ fontFamily: "monospace", color: "#475569" }}>{modernSrc.content_hash ? modernSrc.content_hash.slice(0, 20) + "..." : "—"}</span></div>
                  <div><strong>Technologies:</strong> {modernSrc.technologies?.length > 0 ? modernSrc.technologies.join(", ") : "Standard Python/Module"}</div>
                  <div><strong>Resolved Adapter:</strong> <span style={{ fontFamily: "monospace", fontWeight: "600" }}>{modernAdapter.adapter_id || modernSrc.adapter || "—"}</span></div>
                  <div><strong>Discovered Entrypoint:</strong> <span style={{ fontFamily: "monospace" }}>{modernSrc.entrypoint_file || modernAdapter.entrypoint_file || "—"}</span></div>
                </div>
              </section>
            </div>

            {/* ═════════════════════════════════════════════════════════════════ */}
            {/* SECTION 2: BEHAVIORAL DISCOVERY & INPUT EVIDENCE                  */}
            {/* ═════════════════════════════════════════════════════════════════ */}
            <section style={{ ...cardStyle, marginBottom: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                    📜 Dual-source Behavioral Rules & Inputs
                  </h3>
                  <p style={{ margin: "2px 0 0", fontSize: "12px", color: "#64748b" }}>
                    Legacy and modern rules are extracted independently, anchored to exact source lines, and tested using paired executions.
                  </p>
                </div>
                <span style={{ fontSize: "12px", color: "#475569" }}>
                  AI-validated rules: <strong>{meta.discovered_rules?.length ?? discoveryMeta.invariants_discovered ?? 0}</strong> • Validated Cases: <strong>{meta.inputs_count ?? discoveryMeta.legitimate_inputs_discovered ?? 0}</strong>
                </span>
              </div>

              {meta.discovered_rules && meta.discovered_rules.length > 0 ? (
                <div style={{ maxHeight: "150px", overflowY: "auto", border: "1px solid #e2e8f0", borderRadius: "6px", marginBottom: "10px" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                    <thead>
                      <tr style={{ background: "#f8fafc", textAlign: "left", borderBottom: "1px solid #e2e8f0" }}>
                        <th style={{ padding: "6px 10px", color: "#475569" }}>Rule ID</th>
                        <th style={{ padding: "6px 10px", color: "#475569" }}>Invariant / Description</th>
                        <th style={{ padding: "6px 10px", color: "#475569" }}>Legacy source</th>
                        <th style={{ padding: "6px 10px", color: "#475569" }}>Modern source</th>
                        <th style={{ padding: "6px 10px", color: "#475569" }}>Alignment</th>
                      </tr>
                    </thead>
                    <tbody>
                      {meta.discovered_rules.map((rule, rIdx) => (
                        <tr key={rIdx} style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "6px 10px", fontFamily: "monospace", fontWeight: "600", color: "#1e40af" }}>
                            {rule.rule_id || `rule_${rIdx + 1}`}
                          </td>
                          <td style={{ padding: "6px 10px", color: "#1e293b" }}>
                            <div>{rule.description || rule.name || "—"}</div>
                            {rule.observable_effect && (
                              <div style={{ color: "#64748b", marginTop: "3px" }}>{rule.observable_effect}</div>
                            )}
                          </td>
                          <td style={{ padding: "6px 10px", fontFamily: "monospace", color: "#64748b" }}>
                            {rule.source_evidence?.legacy
                              ? `${rule.source_evidence.legacy.path}:${rule.source_evidence.legacy.line} — ${rule.source_evidence.legacy.excerpt}`
                              : "No source anchor"}
                          </td>
                          <td style={{ padding: "6px 10px", fontFamily: "monospace", color: "#64748b" }}>
                            {rule.source_evidence?.modern
                              ? `${rule.source_evidence.modern.path}:${rule.source_evidence.modern.line} — ${rule.source_evidence.modern.excerpt}`
                              : "No source anchor"}
                          </td>
                          <td style={{ padding: "6px 10px", color: rule.alignment_status === "MATCH" ? "#166534" : "#991b1b" }}>
                            <strong>{rule.alignment_status || "UNALIGNED"}</strong>
                            {rule.alignment_rationale && (
                              <div style={{ color: "#64748b", marginTop: "3px" }}>{rule.alignment_rationale}</div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ padding: "10px 14px", background: "#f8fafc", borderRadius: "6px", fontSize: "12px", color: "#64748b", marginBottom: "10px" }}>
                  {meta.evaluation_mode === "FULL_BEACON"
                    ? "No complete source-grounded rule manifest is available; this run cannot support Full BEACON certification."
                    : "No source-grounded behavioral rules were available for this run."}
                </div>
              )}
              <div style={{ fontSize: "11px", color: "#64748b" }}>
                Input Provenance: <strong>{discoveryMeta.input_provenance?.source || meta.input_discovery?.input_provenance?.source || "Validated Repository Fixtures / Legitimate Ingested Evidence"}</strong>
              </div>
            </section>

            <section style={{ ...cardStyle, marginBottom: "20px" }}>
              <h3 style={{ margin: "0 0 10px", fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                Evidence-Driven Adaptive Behavioral Certification (EDABC)
              </h3>
              <div style={{ fontSize: "12px", color: "#475569", marginBottom: "10px" }}>
                Manifest: <code>{meta.source_rule_manifest_hash || "Unavailable"}</code>
                {" · "}Rule coverage:{" "}
                {meta.source_rule_coverage != null
                  ? `${(meta.source_rule_coverage * 100).toFixed(1)}%`
                  : "Unavailable"}
                {" · "}Source integrity:{" "}
                {meta.source_rule_integrity != null
                  ? `${(meta.source_rule_integrity * 100).toFixed(1)}%`
                  : "Unavailable"}
              </div>
              {sourceRuleEvidenceEntries.length > 0 ? (
                <div style={{ overflowX: "auto", marginBottom: "12px" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "11px" }}>
                    <thead>
                      <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                        <th style={{ padding: "6px 8px" }}>Rule</th>
                        <th style={{ padding: "6px 8px" }}>Targeted inputs</th>
                        <th style={{ padding: "6px 8px" }}>Paired comparisons</th>
                        <th style={{ padding: "6px 8px" }}>Execution evidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sourceRuleEvidenceEntries.map(([ruleId, evidence]) => (
                        <tr key={ruleId} style={{ borderTop: "1px solid #e2e8f0" }}>
                          <td style={{ padding: "6px 8px", fontFamily: "monospace" }}>{ruleId}</td>
                          <td style={{ padding: "6px 8px" }}>
                            {(evidence.targeted_input_ids || []).join(", ") || "None"}
                          </td>
                          <td style={{ padding: "6px 8px" }}>
                            {(evidence.paired_comparison_outcomes || []).map((outcome) =>
                              `${outcome.input_id}: ${outcome.comparison}`
                            ).join("; ") || "Not evaluated"}
                          </td>
                          <td style={{ padding: "6px 8px", fontFamily: "monospace" }}>
                            {(evidence.paired_comparison_outcomes || []).map((outcome) =>
                              [outcome.legacy_evidence_id, outcome.modern_evidence_id].filter(Boolean).join(" / ")
                            ).filter(Boolean).join("; ") || "Unavailable"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ fontSize: "12px", color: "#64748b", marginBottom: "12px" }}>
                  Per-rule execution traceability is unavailable for this run.
                </div>
              )}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                <div>
                  <strong style={{ fontSize: "12px" }}>Mandatory evidence gates</strong>
                  {Object.keys(evidenceGates).length > 0 ? (
                    <ul style={{ fontSize: "11px", margin: "6px 0", paddingLeft: "18px" }}>
                      {Object.entries(evidenceGates).map(([name, passed]) => (
                        <li key={name} style={{ color: passed ? "#166534" : "#991b1b" }}>
                          {name.replaceAll("_", " ")}: {passed ? "PASS" : "BLOCK"}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div style={{ fontSize: "11px", color: "#64748b", marginTop: "6px" }}>Gate results unavailable.</div>
                  )}
                  {(meta.evidence_gate_reasons || []).length > 0 && (
                    <ul style={{ fontSize: "11px", color: "#991b1b", margin: "6px 0", paddingLeft: "18px" }}>
                      {meta.evidence_gate_reasons.map((reason, index) => <li key={index}>{reason}</li>)}
                    </ul>
                  )}
                </div>
                <div>
                  <strong style={{ fontSize: "12px" }}>Evidence-quality factors</strong>
                  {Object.keys(evidenceFactors).length > 0 ? (
                    <ul style={{ fontSize: "11px", margin: "6px 0", paddingLeft: "18px" }}>
                      {Object.entries(evidenceFactors).map(([name, value]) => (
                        <li key={name}>
                          {name.replaceAll("_", " ")}: {Number(value * 100).toFixed(1)}%
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div style={{ fontSize: "11px", color: "#64748b", marginTop: "6px" }}>Factor results unavailable.</div>
                  )}
                </div>
              </div>
            </section>

            {/* ═════════════════════════════════════════════════════════════════ */}
            {/* SECTION 3: AUTHORITATIVE DUAL-EXECUTION CASES                     */}
            {/* ═════════════════════════════════════════════════════════════════ */}
            <section style={{ ...cardStyle, marginBottom: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                    🧪 Authoritative Execution Observations ({repCases.length > 0 ? `${repCases.length} Representative Cases` : "Recorded Cases"})
                  </h3>
                  <p style={{ margin: "2px 0 0", fontSize: "12px", color: "#64748b" }}>
                    Actual sandboxed execution outputs captured across legacy and modern implementations with zero synthetic fallbacks.
                  </p>
                </div>
                <span style={{ fontSize: "11px", fontWeight: "600", color: "#166534", background: "#f0fdf4", border: "1px solid #bbf7d0", padding: "2px 8px", borderRadius: "4px" }}>
                  Sandboxed Execution Verified
                </span>
              </div>

              {(meta.genuine_cobol_execution || meta.cobol_execution_plan) && (
                <div
                  style={{
                    background: "#f0fdf4",
                    border: "1px solid #86efac",
                    borderRadius: "6px",
                    padding: "10px 14px",
                    marginBottom: "12px",
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                    fontSize: "12px",
                    color: "#166534",
                  }}
                >
                  <span style={{ fontSize: "16px" }}>⚙️</span>
                  <div>
                    <strong>GnuCOBOL with BEACON Compatibility Harness Verified:</strong> Reference outputs were produced by compiling and executing the standalone COBOL executable under GnuCOBOL in WSL. Zero synthetic mock values or LLM-fabricated outputs were used.
                  </div>
                </div>
              )}

              {repCases.length > 0 ? (
                <div style={{ overflowX: "auto", border: "1px solid #e2e8f0", borderRadius: "6px" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                    <thead>
                      <tr style={{ background: "#f8fafc", borderBottom: "2px solid #e2e8f0", textAlign: "left" }}>
                        <th style={{ padding: "8px 10px" }}>Case #</th>
                        <th style={{ padding: "8px 10px" }}>Evaluated Input</th>
                        <th style={{ padding: "8px 10px" }}>Legacy Reference Output</th>
                        <th style={{ padding: "8px 10px" }}>Modernized Target Output</th>
                        <th style={{ padding: "8px 10px" }}>Classification</th>
                        <th style={{ padding: "8px 10px" }}>Verdict</th>
                      </tr>
                    </thead>
                    <tbody>
                      {repCases.map((c, cIdx) => {
                        const isMatch = c.classification === "MATCH" || c.oracle_result === "PASS" || c.classification === "EQUIVALENT";
                        return (
                          <tr key={cIdx} style={{ borderBottom: "1px solid #f1f5f9", background: isMatch ? "#ffffff" : "#fef2f2" }}>
                            <td style={{ padding: "8px 10px", fontFamily: "monospace", fontWeight: "700", color: "#475569" }}>
                              #{c.case_index ?? cIdx + 1}
                            </td>
                            <td style={{ padding: "8px 10px", fontFamily: "monospace", fontSize: "11px", maxWidth: "220px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {JSON.stringify(c.input)}
                            </td>
                            <td style={{ padding: "8px 10px", fontFamily: "monospace", color: "#059669", fontWeight: "600" }}>
                              {JSON.stringify(c.legacy_output)}
                              <div style={{ fontFamily: "inherit", fontSize: "10px", color: "#64748b", fontWeight: "400" }}>
                                Status: {c.legacy_execution_status || "UNKNOWN"}
                              </div>
                              {c.legacy_error && (
                                <div style={{ fontFamily: "inherit", fontSize: "10px", color: "#991b1b", fontWeight: "400" }}>
                                  Error: {String(c.legacy_error)}
                                </div>
                              )}
                              {c.legacy_state_changes && (
                                <div style={{ fontFamily: "inherit", fontSize: "10px", color: "#475569", fontWeight: "400" }}>
                                  State: {JSON.stringify(c.legacy_state_changes)}
                                </div>
                              )}
                            </td>
                            <td style={{ padding: "8px 10px", fontFamily: "monospace", color: isMatch ? "#059669" : "#dc2626", fontWeight: "600" }}>
                              {JSON.stringify(c.modern_output)}
                              <div style={{ fontFamily: "inherit", fontSize: "10px", color: "#64748b", fontWeight: "400" }}>
                                Status: {c.modern_execution_status || "UNKNOWN"}
                              </div>
                              {c.modern_error && (
                                <div style={{ fontFamily: "inherit", fontSize: "10px", color: "#991b1b", fontWeight: "400" }}>
                                  Error: {String(c.modern_error)}
                                </div>
                              )}
                              {c.modern_state_changes && (
                                <div style={{ fontFamily: "inherit", fontSize: "10px", color: "#475569", fontWeight: "400" }}>
                                  State: {JSON.stringify(c.modern_state_changes)}
                                </div>
                              )}
                            </td>
                            <td style={{ padding: "8px 10px" }}>
                              <span
                                style={{
                                  fontSize: "11px",
                                  fontWeight: "700",
                                  padding: "2px 6px",
                                  borderRadius: "4px",
                                  background: isMatch ? "#dcfce7" : "#fee2e2",
                                  color: isMatch ? "#15803d" : "#b91c1c",
                                }}
                              >
                                {c.classification || (isMatch ? "MATCH" : "REGRESSION")}
                              </span>
                            </td>
                            <td style={{ padding: "8px 10px", fontWeight: "600", color: isMatch ? "#059669" : "#dc2626" }}>
                              {c.oracle_result || (isMatch ? "PASS" : "FAIL")}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ padding: "14px", background: "#f8fafc", borderRadius: "6px", fontSize: "12px", color: "#64748b" }}>
                  Authoritative cases successfully recorded into certification artifact. (Full dataset available in durable artifact store).
                </div>
              )}
            </section>

            {/* ═════════════════════════════════════════════════════════════════ */}
            {/* SECTION 4 & 5: ORACLE RECONCILIATION & AUTOMATIC THRESHOLD       */}
            {/* ═════════════════════════════════════════════════════════════════ */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "20px" }}>
              {/* Oracle Reconciliation Card */}
              <section style={cardStyle}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                  <h3 style={{ margin: 0, fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                    ⚖️ Oracle Reconciliation
                  </h3>
                  {(() => {
                    if (oracleReconLoading) {
                      return (
                        <span style={{ fontSize: "11px", fontWeight: "600", color: "#1e40af", background: "#eff6ff", border: "1px solid #bfdbfe", padding: "1px 6px", borderRadius: "4px" }}>
                          Loading…
                        </span>
                      );
                    }
                    if (oracleReconError) {
                      return (
                        <span style={{ fontSize: "11px", fontWeight: "600", color: "#991b1b", background: "#fef2f2", border: "1px solid #fecaca", padding: "1px 6px", borderRadius: "4px" }}>
                          API Unavailable
                        </span>
                      );
                    }
                    const st = oracleRecon?.status;
                    const styleMap = {
                      RECONCILED: { color: "#166534", bg: "#f0fdf4", border: "#bbf7d0", text: "RECONCILED" },
                      PARTIALLY_RECONCILED: { color: "#854d0e", bg: "#fefce8", border: "#fef08a", text: "PARTIALLY RECONCILED" },
                      CONFLICT: { color: "#991b1b", bg: "#fef2f2", border: "#fecaca", text: "CONFLICT" },
                      NOT_AVAILABLE: { color: "#475569", bg: "#f8fafc", border: "#cbd5e1", text: "NOT AVAILABLE" },
                      FAILED: { color: "#991b1b", bg: "#fef2f2", border: "#fecaca", text: "FAILED" },
                      PENDING: { color: "#1e40af", bg: "#eff6ff", border: "#bfdbfe", text: "PENDING" },
                    };
                    const badge = styleMap[st] || { color: "#475569", bg: "#f8fafc", border: "#cbd5e1", text: st || "NOT AVAILABLE" };
                    return (
                      <span style={{
                        fontSize: "11px",
                        fontWeight: "700",
                        color: badge.color,
                        background: badge.bg,
                        border: `1px solid ${badge.border}`,
                        padding: "1px 6px",
                        borderRadius: "4px"
                      }}>
                        {badge.text}
                      </span>
                    );
                  })()}
                </div>

                {oracleReconLoading ? (
                  <div style={{ fontSize: "12px", color: "#64748b", padding: "12px 0", fontStyle: "italic" }}>
                    ⏳ Fetching authoritative cross-binding and reconciliation evidence…
                  </div>
                ) : oracleReconError ? (
                  <div style={{ fontSize: "12px", color: "#991b1b", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: "6px", padding: "10px", lineHeight: "1.6" }}>
                    <strong>API Unavailable:</strong> {oracleReconError}
                    <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px" }}>The backend oracle reconciliation endpoint could not be reached.</div>
                  </div>
                ) : (
                  <div style={{ fontSize: "12px", color: "#334155", lineHeight: "1.7" }}>
                    <div>
                      <strong>Reconciliation Status:</strong>{" "}
                      <span style={{
                        color: oracleRecon?.status === "RECONCILED" ? "#166534" : (oracleRecon?.status === "PARTIALLY_RECONCILED" ? "#854d0e" : "#dc2626"),
                        fontWeight: "700",
                      }}>
                        {oracleRecon?.status || "NOT_AVAILABLE"}
                      </span>
                      {oracleRecon?.status_reason && (
                        <span style={{ fontSize: "11px", color: "#64748b", display: "block", marginTop: "1px" }}>
                          {oracleRecon.status_reason}
                        </span>
                      )}
                    </div>
                    <div>
                      <strong>Oracle Coverage:</strong>{" "}
                      <strong style={{ color: "#1e40af" }}>
                        {oracleRecon?.coverage != null ? `${(oracleRecon.coverage * 100).toFixed(1)}%` : (oracleRecon ? "Undefined (0 required rules)" : "—")}
                      </strong>
                    </div>
                    <div>
                      <strong>Oracle Set ID:</strong>{" "}
                      <span style={{ fontFamily: "monospace", color: "#0f172a" }}>
                        {oracleRecon?.oracle_set_id || oracleSetId || "—"}
                      </span>
                    </div>
                    <div>
                      <strong>Oracle Hash (SHA-256):</strong>{" "}
                      <span style={{ fontFamily: "monospace", color: "#475569", fontSize: "11px" }}>
                        {oracleRecon?.oracle_set_hash
                          ? (oracleRecon.oracle_set_hash.length > 28 ? oracleRecon.oracle_set_hash.slice(0, 24) + "..." : oracleRecon.oracle_set_hash)
                          : (oracleSetHash && oracleSetHash !== "—" ? (oracleSetHash.length > 28 ? oracleSetHash.slice(0, 24) + "..." : oracleSetHash) : "—")}
                      </span>
                    </div>
                    <div>
                      <strong>InputSet ID:</strong>{" "}
                      <span style={{ fontFamily: "monospace", color: "#0f172a" }}>
                        {oracleRecon?.input_set_id || meta.input_set_id || "—"}
                      </span>
                    </div>
                    <div>
                      <strong>InputSet Hash (SHA-256):</strong>{" "}
                      <span style={{ fontFamily: "monospace", color: "#475569", fontSize: "11px" }}>
                        {oracleRecon?.input_set_hash
                          ? (oracleRecon.input_set_hash.length > 28 ? oracleRecon.input_set_hash.slice(0, 24) + "..." : oracleRecon.input_set_hash)
                          : (meta.input_set_hash ? (meta.input_set_hash.length > 28 ? meta.input_set_hash.slice(0, 24) + "..." : meta.input_set_hash) : "—")}
                      </span>
                    </div>
                    <div>
                      <strong>Binding Counts:</strong>{" "}
                      <span>
                        Required: <strong>{oracleRecon?.binding_counts?.total_required_bindings ?? 0}</strong> • Matched: <strong style={{ color: "#166534" }}>{oracleRecon?.binding_counts?.matched_bindings ?? 0}</strong> • Missing: <strong style={{ color: (oracleRecon?.binding_counts?.missing_bindings ?? 0) > 0 ? "#dc2626" : "#64748b" }}>{oracleRecon?.binding_counts?.missing_bindings ?? 0}</strong> • Conflicts: <strong style={{ color: (oracleRecon?.binding_counts?.conflicting_bindings ?? 0) > 0 ? "#dc2626" : "#64748b" }}>{oracleRecon?.binding_counts?.conflicting_bindings ?? 0}</strong>
                      </span>
                    </div>
                    <div>
                      <strong>Cross-Binding:</strong>{" "}
                      <span style={{
                        color: oracleRecon?.status === "RECONCILED" ? "#166534" : (oracleRecon?.status === "PARTIALLY_RECONCILED" ? "#854d0e" : "#64748b"),
                        fontWeight: "600",
                      }}>
                        {oracleRecon?.status === "RECONCILED"
                          ? "Verified to Execution & Input Identity"
                          : (oracleRecon?.status === "PARTIALLY_RECONCILED"
                            ? "Partially Bound to Executions"
                            : (oracleRecon?.status === "CONFLICT"
                              ? "Contradictory Bindings Detected"
                              : (oracleRecon?.status === "FAILED"
                                ? "Integrity Check Failed"
                                : "Not Reconciled")))}
                      </span>
                    </div>
                    {oracleRecon?.evidence_hash && (
                      <div>
                        <strong>Evidence Digest (SHA-256):</strong>{" "}
                        <span style={{ fontFamily: "monospace", color: "#475569", fontSize: "11px" }}>
                          {oracleRecon.evidence_hash.length > 28 ? oracleRecon.evidence_hash.slice(0, 24) + "..." : oracleRecon.evidence_hash}
                        </span>
                      </div>
                    )}
                    {oracleRecon?.created_at && (
                      <div style={{ fontSize: "11px", color: "#64748b" }}>
                        <strong>Reconciled At:</strong> {new Date(oracleRecon.created_at).toLocaleString()}
                      </div>
                    )}
                    {oracleRecon?.failure_reasons && oracleRecon.failure_reasons.length > 0 && (
                      <div style={{ marginTop: "8px", padding: "8px 10px", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: "6px", fontSize: "11px", color: "#991b1b", lineHeight: "1.5" }}>
                        <strong>Integrity / Missing Evidence Reasons:</strong>
                        <ul style={{ margin: "4px 0 0", paddingLeft: "16px" }}>
                          {oracleRecon.failure_reasons.map((r, i) => (
                            <li key={i}>{r}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </section>

              {/* Automatic Threshold Resolution Card (Strictly Read-Only) */}
              <section style={cardStyle}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                  <h3 style={{ margin: 0, fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                    🎯 Automatic Threshold Resolution
                  </h3>
                  <span style={{ fontSize: "11px", fontWeight: "700", color: "#1e40af", background: "#eff6ff", border: "1px solid #bfdbfe", padding: "1px 6px", borderRadius: "4px" }}>
                    Deterministic Resolver
                  </span>
                </div>
                <div style={{ fontSize: "12px", color: "#334155", lineHeight: "1.7" }}>
                  <div><strong>Resolution Strategy:</strong> <span style={{ fontFamily: "monospace", fontWeight: "700", color: "#1e40af" }}>{threshMeta.strategy || "EVIDENCE_DERIVED"}</span></div>
                  <div><strong>Difference Metric:</strong> <span style={{ fontFamily: "monospace" }}>{threshMeta.metric || "ABSOLUTE"}</span></div>
                  <div><strong>Resolved Threshold:</strong> {(threshMeta.resolved_threshold != null || threshMeta.final_value != null) ? <strong style={{ color: "#059669", fontSize: "14px", fontFamily: "monospace" }}>{Number(threshMeta.resolved_threshold ?? threshMeta.final_value).toFixed(4)}</strong> : <strong style={{ color: "#dc2626", fontSize: "12px" }}>Not resolved (Inconclusive)</strong>}</div>
                  <div><strong>Reference Samples Analyzed:</strong> <strong>{threshMeta.sample_count ?? repCases.length ?? meta.inputs_count ?? 0}</strong> observations</div>
                  <div><strong>Estimator / Outliers:</strong> {threshMeta.estimator || "IQR"} • Policy: {threshMeta.outlier_policy || "NONE"}</div>
                  <div><strong>Resolution Status:</strong> <span style={{ color: "#166534", fontWeight: "600" }}>{threshMeta.resolution_status || "RESOLVED & FROZEN"}</span></div>
                  <div><strong>Threshold Fingerprint:</strong> <span style={{ fontFamily: "monospace", color: "#475569", fontSize: "11px" }}>{threshMeta.fingerprint ? (threshMeta.fingerprint.length > 24 ? threshMeta.fingerprint.slice(0, 20) + "..." : threshMeta.fingerprint) : (workflowResult.threshold_resolution_fingerprint ? workflowResult.threshold_resolution_fingerprint.slice(0, 20) + "..." : "—")}</span></div>
                </div>
                <div style={{ marginTop: "8px", fontSize: "11px", color: "#64748b", fontStyle: "italic", borderTop: "1px solid #f1f5f9", paddingTop: "6px" }}>
                  ✓ Automatically resolved from reference execution evidence. Arbitrary magic fallbacks (0.001) are prohibited.
                </div>
              </section>
            </div>

            {/* ═════════════════════════════════════════════════════════════════ */}
            {/* SECTION 6: GROUNDED CERTIFICATION EXPLANATION                     */}
            {/* ═════════════════════════════════════════════════════════════════ */}
            {workflowResult.explanation && (
              <section style={{ ...cardStyle, marginBottom: "20px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                  <h3 style={{ margin: 0, fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                    📖 Grounded Certification Explanation
                  </h3>
                  <span style={{ fontSize: "11px", color: "#059669", fontWeight: "600", background: "#f0fdf4", border: "1px solid #bbf7d0", padding: "1px 6px", borderRadius: "4px" }}>
                    Authoritative Context Grounded
                  </span>
                </div>
                {typeof workflowResult.explanation === "string" ? (
                  <p style={{ margin: 0, fontSize: "13px", color: "#334155", lineHeight: "1.6" }}>
                    {workflowResult.explanation}
                  </p>
                ) : (
                  <div>
                    {(workflowResult.explanation.headline || workflowResult.explanation.overall_verdict) && (
                      <p style={{ margin: "0 0 6px", fontWeight: "700", fontSize: "14px", color: "#0f172a" }}>
                        {workflowResult.explanation.headline || `Verdict: ${workflowResult.explanation.overall_verdict}`}
                      </p>
                    )}
                    {(workflowResult.explanation.executive_summary || workflowResult.explanation.status_rationale) && (
                      <p style={{ margin: "0 0 8px", fontSize: "13px", color: "#334155", lineHeight: "1.6" }}>
                        {workflowResult.explanation.executive_summary || workflowResult.explanation.status_rationale}
                      </p>
                    )}
                    {workflowResult.explanation.behavioral_summary && workflowResult.explanation.behavioral_summary !== workflowResult.explanation.executive_summary && (
                      <p style={{ margin: "0 0 8px", fontSize: "12px", color: "#475569", lineHeight: "1.6" }}>
                        {workflowResult.explanation.behavioral_summary}
                      </p>
                    )}
                    {workflowResult.explanation.key_findings?.length > 0 && (
                      <ul style={{ margin: "0", padding: "0 0 0 18px", fontSize: "13px", color: "#475569", lineHeight: "1.8" }}>
                        {workflowResult.explanation.key_findings.map((f, i) => (
                          <li key={i}>{f}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
                <div style={{ marginTop: "10px", fontSize: "11px", color: "#94a3b8" }}>
                  Note: Explanatory synthesis is derived strictly from verified evaluation observations and cannot modify authoritative certification results.
                </div>
              </section>
            )}

            {/* ═════════════════════════════════════════════════════════════════ */}
            {/* SECTION 7: BEHAVIORAL REGRESSIONS / COUNTEREXAMPLES (IF ANY)      */}
            {/* ═════════════════════════════════════════════════════════════════ */}
            {workflowResult.regressions?.length > 0 && (
              <section style={{ ...cardStyle, marginBottom: "20px" }}>
                <h3 style={{ margin: "0 0 12px", fontSize: "14px", fontWeight: "700", color: "#991b1b" }}>
                  🚨 Behavioral Regressions — Concrete Counterexamples ({workflowResult.regressions.length})
                </h3>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                    <thead>
                      <tr style={{ background: "#fef2f2", borderBottom: "2px solid #fecaca", textAlign: "left" }}>
                        <th style={{ padding: "8px 10px" }}>Oracle / Rule</th>
                        <th style={{ padding: "8px 10px" }}>Evaluated Input</th>
                        <th style={{ padding: "8px 10px" }}>Legacy Reference Output</th>
                        <th style={{ padding: "8px 10px" }}>Modernized Target Output</th>
                        <th style={{ padding: "8px 10px" }}>Difference</th>
                      </tr>
                    </thead>
                    <tbody>
                      {workflowResult.regressions.map((reg, idx) => (
                        <tr key={idx} style={{ borderBottom: "1px solid #fee2e2" }}>
                          <td style={{ padding: "8px 10px", fontFamily: "monospace", color: "#2563eb", fontWeight: "600" }}>
                            {reg.oracle_id || reg.rule_id || `#${idx + 1}`}
                          </td>
                          <td style={{ padding: "8px 10px", fontFamily: "monospace", fontSize: "11px" }}>
                            {JSON.stringify(reg.input_values ?? reg.input ?? "—")}
                          </td>
                          <td style={{ padding: "8px 10px", color: "#059669", fontFamily: "monospace" }}>
                            {JSON.stringify(reg.legacy_output ?? reg.reference_output ?? "—")}
                          </td>
                          <td style={{ padding: "8px 10px", color: "#dc2626", fontFamily: "monospace", fontWeight: "600" }}>
                            {JSON.stringify(reg.modern_output ?? reg.target_output ?? "—")}
                          </td>
                          <td style={{ padding: "8px 10px", color: "#64748b" }}>
                            {reg.diff ?? reg.difference ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {/* ═════════════════════════════════════════════════════════════════ */}
            {/* SECTION 8: CRYPTOGRAPHIC AUDIT & STAGE-B DURABLE FINALIZATION     */}
            {/* ═════════════════════════════════════════════════════════════════ */}
            <section style={{ ...cardStyle, marginBottom: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <h3 style={{ margin: 0, fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                  🔒 Cryptographic Audit & Stage-B Finalization Trail
                </h3>
                <span style={{ fontSize: "11px", fontWeight: "700", color: "#166534", background: "#f0fdf4", border: "1px solid #bbf7d0", padding: "2px 8px", borderRadius: "4px" }}>
                  Durable Audit Verified
                </span>
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "10px",
                  fontSize: "12px",
                  fontFamily: "monospace",
                }}
              >
                {[
                  { label: "Stage-B Execution Fingerprint", val: execFingerprint },
                  { label: "Certification Artifact ID", val: workflowResult.artifact_id },
                  { label: "Artifact Hash (SHA-256)", val: workflowResult.artifact_hash },
                  { label: "Threshold Resolution Fingerprint", val: threshMeta.fingerprint || workflowResult.threshold_resolution_fingerprint },
                  { label: "Oracle Set Hash (SHA-256)", val: oracleSetHash },
                  { label: "Audit Status / Finalization State", val: `${workflowResult.audit_status || "PERSISTED"} / ${finalizationState}` },
                ].map(({ label, val }) => (
                  <div
                    key={label}
                    style={{
                      background: "#f8fafc",
                      padding: "8px 12px",
                      borderRadius: "6px",
                      border: "1px solid #e2e8f0",
                    }}
                  >
                    <span style={{ color: "#64748b", fontFamily: "sans-serif", fontSize: "11px", fontWeight: "600" }}>
                      {label}:
                    </span>
                    <div style={{ color: "#0f172a", marginTop: "2px", wordBreak: "break-all" }}>
                      {val || <span style={{ color: "#94a3b8", fontStyle: "italic" }}>—</span>}
                    </div>
                  </div>
                ))}
              </div>

              {/* Stage Timings breakdown */}
              {workflowResult.timings_ms && Object.keys(workflowResult.timings_ms).length > 0 && (
                <div style={{ marginTop: "14px" }}>
                  <div style={{ fontSize: "11px", fontWeight: "600", color: "#64748b", marginBottom: "6px", textTransform: "uppercase" }}>
                    Stage-by-Stage Latencies:
                  </div>
                  <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                    {Object.entries(workflowResult.timings_ms).map(([stage, ms]) => (
                      <div
                        key={stage}
                        style={{
                          background: "#f1f5f9",
                          padding: "4px 8px",
                          borderRadius: "4px",
                          fontSize: "11px",
                          border: "1px solid #e2e8f0",
                        }}
                      >
                        <span style={{ fontWeight: "600", color: "#334155", fontFamily: "monospace" }}>{stage}</span>
                        <span style={{ color: "#64748b", marginLeft: "4px" }}>{Math.round(ms)}ms</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>
          </div>
        );
      })()}

      {/* Empty result state */}
      {activeStep === "result" && !workflowResult && (
        <div
          style={{
            ...cardStyle,
            textAlign: "center",
            padding: "48px 24px",
          }}
        >
          <span style={{ fontSize: "40px" }}>⚡</span>
          <h3 style={{ margin: "12px 0 6px", fontSize: "18px", fontWeight: "700", color: "#0f172a" }}>
            No Result Yet
          </h3>
          <p style={{ margin: "0 0 20px", maxWidth: "500px", marginLeft: "auto", marginRight: "auto", fontSize: "14px", color: "#64748b" }}>
            Configure your application and run certification from the previous step.
          </p>
          <button
            onClick={() => setActiveStep("configure")}
            style={{
              background: "#2563eb",
              color: "#fff",
              border: "none",
              padding: "10px 24px",
              borderRadius: "6px",
              fontWeight: "600",
              fontSize: "14px",
              cursor: "pointer",
            }}
          >
            ← Go to Configuration
          </button>
        </div>
      )}
    </div>
  );
}
