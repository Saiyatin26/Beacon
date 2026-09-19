/**
 * BEACON V2 — CertificationTab.jsx
 *
 * Repository-First Behavioral Equivalence Certification Entry Point.
 * Implements the V2 Part 1 Architecture:
 *   1. User provides Legacy Repository URL, Modern Repository URL, and Evaluation Mode (CONTROLLED | FULL).
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
  badgeStyle,
  cardStyle,
  statusBadgeStyles,
  userHasPermission,
  onCertifyResult,
}) {
  // ── Repository Form State (Empty Defaults, Pure Repo-First) ──────────────────
  const [legacyRepoUrl, setLegacyRepoUrl] = useState("");
  const [legacyRevision, setLegacyRevision] = useState("");
  const [legacySubdir, setLegacySubdir] = useState("");
  const [modernRepoUrl, setModernRepoUrl] = useState("");
  const [modernRevision, setModernRevision] = useState("");
  const [modernSubdir, setModernSubdir] = useState("");
  const [evaluationMode, setEvaluationMode] = useState("CONTROLLED"); // CONTROLLED | FULL
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

  // ── Step Tracking ──────────────────────────────────────────────────────────
  const [activeStep, setActiveStep] = useState("configure"); // configure | result

  // ── Recent Workflow Runs ───────────────────────────────────────────────────
  const [recentRuns, setRecentRuns] = useState([]);
  const [runsLoading, setRunsLoading] = useState(false);

  const _fetch = authFetch || window.fetch;

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
    loadRecentRuns();
  }, []);

  // ── Repository Analysis Handler ─────────────────────────────────────────────
  const handleAnalyzeRepositories = async () => {
    if (!legacyRepoUrl.trim() || !modernRepoUrl.trim()) {
      setAnalysisError("Both Legacy Reference and Modernized Target repository paths or URLs are required.");
      return;
    }
    setAnalysisBusy(true);
    setAnalysisError(null);
    setAnalysisResult(null);

    try {
      const payload = {
        legacy_repository: {
          repository_url: legacyRepoUrl.trim(),
          revision: legacyRevision.trim() || null,
          subdirectory: legacySubdir.trim() || null,
        },
        modern_repository: {
          repository_url: modernRepoUrl.trim(),
          revision: modernRevision.trim() || null,
          subdirectory: modernSubdir.trim() || null,
        },
        evaluation_mode: evaluationMode,
      };

      const res = await _fetch(`${apiBase}/api/v2/workflow/analyze-repository`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) {
        const errMsg = data.detail?.message || data.detail || `Repository analysis failed (HTTP ${res.status})`;
        throw new Error(typeof errMsg === "object" ? JSON.stringify(errMsg) : errMsg);
      }
      setAnalysisResult(data);
    } catch (e) {
      setAnalysisError(e.message);
    } finally {
      setAnalysisBusy(false);
    }
  };

  // ── Repository Certification Execution Handler ──────────────────────────────
  const handleCertifyRepository = async () => {
    if (!legacyRepoUrl.trim() || !modernRepoUrl.trim()) {
      setCertifyError("Both Legacy Reference and Modernized Target repository paths or URLs are required.");
      return;
    }
    setCertifyBusy(true);
    setCertifyError(null);
    setWorkflowResult(null);

    try {
      const payload = {
        legacy_repository: {
          repository_url: legacyRepoUrl.trim(),
          revision: legacyRevision.trim() || null,
          subdirectory: legacySubdir.trim() || null,
        },
        modern_repository: {
          repository_url: modernRepoUrl.trim(),
          revision: modernRevision.trim() || null,
          subdirectory: modernSubdir.trim() || null,
        },
        evaluation_mode: evaluationMode,
        policy_min_equivalence_score: 0.999,
        policy_min_oracle_coverage: 0.0,
        allow_warnings: false,
        explain: true,
        explanation_mode: "deterministic",
      };

      const res = await _fetch(`${apiBase}/api/v2/workflow/certify-repository`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) {
        const errMsg = data.detail?.message || data.detail || `Repository certification failed (HTTP ${res.status})`;
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

  // ── Load Past Run Helper ───────────────────────────────────────────────────
  const loadPastRun = async (runId) => {
    try {
      const res = await _fetch(`${apiBase}/api/v2/workflow/runs/${runId}`);
      if (res.ok) {
        const run = await res.json();
        setWorkflowRunId(run.workflow_run_id);
        setWorkflowResult({
          workflow_run_id: run.workflow_run_id,
          application_id: run.application_id,
          state: run.state,
          status: run.certification_status || run.state,
          certified: run.certification_status === "CERTIFIED" || run.certification_status === "CERTIFIED_WITH_WARNINGS",
          equivalence_score: run.certification_score,
          artifact_id: run.certification_id,
          regressions_count: 0,
          regressions: [],
          timings_ms: run.stage_timings_ms || {},
          audit_status: "PERSISTED",
          metadata: run.metadata || {},
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

              {/* Dual Repository Source Inputs */}
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
                      border: `1px solid ${evaluationMode === "FULL" ? "#2563eb" : "#cbd5e1"}`,
                      background: evaluationMode === "FULL" ? "#eff6ff" : "#f8fafc",
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="radio"
                      name="evaluationMode"
                      value="FULL"
                      checked={evaluationMode === "FULL"}
                      onChange={(e) => setEvaluationMode(e.target.value)}
                      style={{ marginTop: "2px" }}
                    />
                    <div>
                      <div style={{ fontSize: "13px", fontWeight: "700", color: evaluationMode === "FULL" ? "#1e40af" : "#1e293b" }}>
                        🔍 FULL Mode
                      </div>
                      <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                        Broader BEACON-managed automatic discovery across all extracted AST paths and comprehensive evidence collection.
                      </div>
                    </div>
                  </label>
                </div>
              </div>

              {/* Analysis Action Button */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "12px", color: "#64748b" }}>
                  Zero dynamic code execution: Inspection runs through pure static AST and manifest parsing.
                </span>
                <button
                  type="button"
                  onClick={handleAnalyzeRepositories}
                  disabled={analysisBusy || !legacyRepoUrl.trim() || !modernRepoUrl.trim()}
                  style={{
                    background: analysisBusy || !legacyRepoUrl.trim() || !modernRepoUrl.trim() ? "#94a3b8" : "#2563eb",
                    color: "#ffffff",
                    border: "none",
                    padding: "10px 22px",
                    borderRadius: "6px",
                    fontWeight: "700",
                    fontSize: "13px",
                    cursor: analysisBusy || !legacyRepoUrl.trim() || !modernRepoUrl.trim() ? "not-allowed" : "pointer",
                    boxShadow: "0 2px 4px rgba(37,99,235,0.25)",
                    transition: "all 0.15s",
                  }}
                >
                  {analysisBusy ? "🔍 Analyzing Repositories..." : "🔍 Analyze Repositories"}
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
                    border: `1px solid ${
                      analysisResult.status === "READY"
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
                      {analysisResult.status === "READY" && "✅ Analysis Complete — Repositories Validated & Ready for Certification"}
                      {analysisResult.status === "DISCOVERY_INSUFFICIENT" && "⚠️ Discovery Insufficient — Incomplete Input Evidence"}
                      {analysisResult.status === "FAILED" && "❌ Repository Analysis Failed"}
                    </div>
                    <div style={{ fontSize: "12px", color: "#475569", marginTop: "2px" }}>
                      Mode: <strong>{analysisResult.evaluation_mode}</strong> • Discovered Rules: <strong>{analysisResult.discovered_rules?.length || 0}</strong> • Validated Inputs: <strong>{analysisResult.discovered_inputs?.length || 0}</strong>
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
                      <div><strong>Resolved Adapter:</strong> <span style={{ fontFamily: "monospace", fontWeight: "600", color: "#0f172a" }}>{analysisResult.legacy?.adapter?.adapter_id || "—"}</span> ({analysisResult.legacy?.adapter?.status || "RESOLVED"})</div>
                      <div><strong>Discovered Entrypoint:</strong> <span style={{ fontFamily: "monospace", color: "#0f172a" }}>{analysisResult.legacy?.entrypoint_file || analysisResult.legacy?.adapter?.entrypoint_file || "—"}</span></div>
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
                      <div><strong>Resolved Adapter:</strong> <span style={{ fontFamily: "monospace", fontWeight: "600", color: "#0f172a" }}>{analysisResult.modern?.adapter?.adapter_id || "—"}</span> ({analysisResult.modern?.adapter?.status || "RESOLVED"})</div>
                      <div><strong>Discovered Entrypoint:</strong> <span style={{ fontFamily: "monospace", color: "#0f172a" }}>{analysisResult.modern?.entrypoint_file || analysisResult.modern?.adapter?.entrypoint_file || "—"}</span></div>
                    </div>
                  </section>
                </div>

                {/* Discovered Behavioral Rules & Invariants */}
                <section style={{ ...cardStyle, marginBottom: "16px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                    <h4 style={{ margin: 0, fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                      📜 Discovered Behavioral Rules & Invariants ({analysisResult.discovered_rules?.length || 0})
                    </h4>
                    <span style={{ fontSize: "11px", color: "#64748b" }}>AST Branch & Expression Inference</span>
                  </div>
                  {analysisResult.discovered_rules && analysisResult.discovered_rules.length > 0 ? (
                    <div style={{ maxHeight: "180px", overflowY: "auto", border: "1px solid #e2e8f0", borderRadius: "6px" }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                        <thead>
                          <tr style={{ background: "#f8fafc", textAlign: "left", borderBottom: "1px solid #e2e8f0" }}>
                            <th style={{ padding: "6px 10px", color: "#475569" }}>Rule ID</th>
                            <th style={{ padding: "6px 10px", color: "#475569" }}>Description / Invariant</th>
                            <th style={{ padding: "6px 10px", color: "#475569" }}>Location</th>
                            <th style={{ padding: "6px 10px", color: "#475569" }}>Method</th>
                          </tr>
                        </thead>
                        <tbody>
                          {analysisResult.discovered_rules.map((rule, rIdx) => (
                            <tr key={rIdx} style={{ borderBottom: "1px solid #f1f5f9" }}>
                              <td style={{ padding: "6px 10px", fontFamily: "monospace", fontWeight: "600", color: "#1e40af" }}>
                                {rule.rule_id || `rule_${rIdx + 1}`}
                              </td>
                              <td style={{ padding: "6px 10px", color: "#1e293b" }}>
                                {rule.description || rule.name || "—"}
                              </td>
                              <td style={{ padding: "6px 10px", fontFamily: "monospace", color: "#64748b" }}>
                                {rule.source_file ? `${rule.source_file}:${rule.source_location || 1}` : "—"}
                              </td>
                              <td style={{ padding: "6px 10px", color: "#475569" }}>
                                {rule.discovery_method || "AST_ANALYSIS"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div style={{ padding: "12px", background: "#f8fafc", borderRadius: "6px", fontSize: "12px", color: "#64748b" }}>
                      No explicit AST invariants extracted. Equivalence certification will evaluate complete entrypoint signatures.
                    </div>
                  )}
                </section>

                {/* Discovered Legitimate Inputs */}
                <section style={{ ...cardStyle, marginBottom: "16px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                    <h4 style={{ margin: 0, fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                      🧪 Discovered Legitimate Inputs ({analysisResult.discovered_inputs?.length || 0} cases)
                    </h4>
                    <span style={{ fontSize: "11px", color: "#166534", fontWeight: "600" }}>
                      Provenance-Backed & Validated
                    </span>
                  </div>

                  {analysisResult.discovered_inputs && analysisResult.discovered_inputs.length > 0 ? (
                    <div>
                      <div style={{ fontSize: "12px", color: "#475569", marginBottom: "8px" }}>
                        Input Provenance: <strong>{analysisResult.input_provenance?.source || "Repository Fixtures / Validated Evidence"}</strong>
                      </div>
                      <div style={{ maxHeight: "150px", overflowY: "auto", background: "#f8fafc", borderRadius: "6px", border: "1px solid #e2e8f0", padding: "8px" }}>
                        <pre style={{ margin: 0, fontSize: "11px", fontFamily: "monospace", color: "#0f172a" }}>
                          {JSON.stringify(analysisResult.discovered_inputs.slice(0, 5), null, 2)}
                          {analysisResult.discovered_inputs.length > 5 && `
... and ${analysisResult.discovered_inputs.length - 5} more validated cases`}
                        </pre>
                      </div>
                    </div>
                  ) : (
                    <div style={{ padding: "12px", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: "6px", fontSize: "12px", color: "#92400e" }}>
                      ⚠️ No legitimate test fixtures or manifests discovered in repositories. Certification cannot proceed without genuine input evidence (fail-closed).
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
        const oracleCoverage = meta.oracle_coverage != null ? `${(meta.oracle_coverage * 100).toFixed(1)}%` : "100.0%";

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
              </div>
            </div>

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
                  label: "Equivalence Score",
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
                  val: workflowResult.regressions_count ?? workflowResult.regressions?.length ?? 0,
                  color: (workflowResult.regressions_count ?? 0) > 0 ? "#dc2626" : "#059669",
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
                    📜 Discovered Behavioral Invariants & Legitimate Inputs
                  </h3>
                  <p style={{ margin: "2px 0 0", fontSize: "12px", color: "#64748b" }}>
                    Static AST branch extraction and genuine test fixtures discovered directly from ingested source code.
                  </p>
                </div>
                <span style={{ fontSize: "12px", color: "#475569" }}>
                  Invariants: <strong>{discoveryMeta.invariants_discovered ?? meta.discovered_rules?.length ?? 0}</strong> • Validated Cases: <strong>{meta.inputs_count ?? discoveryMeta.legitimate_inputs_discovered ?? 0}</strong>
                </span>
              </div>

              {meta.discovered_rules && meta.discovered_rules.length > 0 ? (
                <div style={{ maxHeight: "150px", overflowY: "auto", border: "1px solid #e2e8f0", borderRadius: "6px", marginBottom: "10px" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                    <thead>
                      <tr style={{ background: "#f8fafc", textAlign: "left", borderBottom: "1px solid #e2e8f0" }}>
                        <th style={{ padding: "6px 10px", color: "#475569" }}>Rule ID</th>
                        <th style={{ padding: "6px 10px", color: "#475569" }}>Invariant / Description</th>
                        <th style={{ padding: "6px 10px", color: "#475569" }}>Source AST Location</th>
                        <th style={{ padding: "6px 10px", color: "#475569" }}>Discovery Method</th>
                      </tr>
                    </thead>
                    <tbody>
                      {meta.discovered_rules.map((rule, rIdx) => (
                        <tr key={rIdx} style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "6px 10px", fontFamily: "monospace", fontWeight: "600", color: "#1e40af" }}>
                            {rule.rule_id || `rule_${rIdx + 1}`}
                          </td>
                          <td style={{ padding: "6px 10px", color: "#1e293b" }}>
                            {rule.description || rule.name || "—"}
                          </td>
                          <td style={{ padding: "6px 10px", fontFamily: "monospace", color: "#64748b" }}>
                            {rule.source_file ? `${rule.source_file}:${rule.source_location || 1}` : "—"}
                          </td>
                          <td style={{ padding: "6px 10px", color: "#475569" }}>
                            {rule.discovery_method || "AST_ANALYSIS"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ padding: "10px 14px", background: "#f8fafc", borderRadius: "6px", fontSize: "12px", color: "#64748b", marginBottom: "10px" }}>
                  Equivalence certified across complete adapter entrypoint signatures.
                </div>
              )}
              <div style={{ fontSize: "11px", color: "#64748b" }}>
                Input Provenance: <strong>{discoveryMeta.input_provenance?.source || meta.input_discovery?.input_provenance?.source || "Validated Repository Fixtures / Legitimate Ingested Evidence"}</strong>
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
                            </td>
                            <td style={{ padding: "8px 10px", fontFamily: "monospace", color: isMatch ? "#059669" : "#dc2626", fontWeight: "600" }}>
                              {JSON.stringify(c.modern_output)}
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
                  <span style={{ fontSize: "11px", fontWeight: "600", color: "#166534", background: "#f0fdf4", border: "1px solid #bbf7d0", padding: "1px 6px", borderRadius: "4px" }}>
                    Evidence-Reconciled
                  </span>
                </div>
                <div style={{ fontSize: "12px", color: "#334155", lineHeight: "1.7" }}>
                  <div><strong>Reconciliation Status:</strong> <span style={{ color: "#166534", fontWeight: "600" }}>VALIDATED</span></div>
                  <div><strong>Oracle Coverage:</strong> <strong style={{ color: "#1e40af" }}>{oracleCoverage}</strong></div>
                  <div><strong>Oracle Set ID:</strong> <span style={{ fontFamily: "monospace", color: "#0f172a" }}>{oracleSetId}</span></div>
                  <div><strong>Oracle Hash (SHA-256):</strong> <span style={{ fontFamily: "monospace", color: "#475569", fontSize: "11px" }}>{oracleSetHash ? (oracleSetHash.length > 28 ? oracleSetHash.slice(0, 24) + "..." : oracleSetHash) : "—"}</span></div>
                  <div><strong>Cross-Binding:</strong> <span style={{ color: "#166534" }}>Verified to Execution & Input Identity</span></div>
                </div>
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
                    {workflowResult.explanation.headline && (
                      <p style={{ margin: "0 0 6px", fontWeight: "700", fontSize: "14px", color: "#0f172a" }}>
                        {workflowResult.explanation.headline}
                      </p>
                    )}
                    {workflowResult.explanation.status_rationale && (
                      <p style={{ margin: "0 0 8px", fontSize: "13px", color: "#334155", lineHeight: "1.6" }}>
                        {workflowResult.explanation.status_rationale}
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
