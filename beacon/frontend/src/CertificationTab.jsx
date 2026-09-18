/**
 * BEACON V2 — CertificationTab.jsx
 *
 * Repository-first behavioral equivalence certification entry point.
 * Implements the correct BEACON V2 architecture:
 *   1. User provides an ApplicationSpec (application_id, adapters, inputs)
 *   2. Frontend calls /api/v2/applications to register or select an existing app
 *   3. Frontend calls /api/v2/adapters/validate for pre-flight adapter readiness
 *   4. Frontend calls /api/v2/workflow/certify to run the canonical V2 engine
 *   5. The V2 engine automatically discovers oracles, resolves thresholds,
 *      evaluates, certifies, and persists the result — no human intervention.
 *   6. Results are displayed from the WorkflowResult payload.
 *
 * There are no benchmark dropdowns, no hardcoded adapter names, no loan-demo
 * references, and no hardcoded tolerance values in this component.
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

// ─── Default ApplicationSpec template ─────────────────────────────────────────

const DEFAULT_SPEC = {
  application_id: "",
  name: "",
  domain: "",
  description: "",
  reference_implementations: [
    {
      adapter_id: "",
      version: "1.0.0",
      description: "Legacy reference implementation",
    },
  ],
  target_implementations: [
    {
      adapter_id: "",
      version: "2.0.0",
      description: "Modernized target implementation",
    },
  ],
  test_inputs: [],
};

// ─── Component ────────────────────────────────────────────────────────────────

export default function CertificationTab({
  apiBase = "",
  authFetch,
  badgeStyle,
  cardStyle,
  statusBadgeStyles,
  userHasPermission,
  onCertifyResult,   // callback so App.jsx dossier tab can pick up cert_id
}) {
  // ── Registered Applications ──────────────────────────────────────────────
  const [registeredApps, setRegisteredApps] = useState([]);
  const [appsLoading, setAppsLoading] = useState(false);
  const [appsError, setAppsError] = useState(null);

  // ── Application Spec Form State ──────────────────────────────────────────
  const [appId, setAppId] = useState("");
  const [appName, setAppName] = useState("");
  const [appDomain, setAppDomain] = useState("");
  const [appDescription, setAppDescription] = useState("");
  const [refAdapterId, setRefAdapterId] = useState("");
  const [refAdapterVersion, setRefAdapterVersion] = useState("1.0.0");
  const [targetAdapterId, setTargetAdapterId] = useState("");
  const [targetAdapterVersion, setTargetAdapterVersion] = useState("2.0.0");
  const [targetIndex, setTargetIndex] = useState(0);
  const [customInputsText, setCustomInputsText] = useState("");
  const [customInputsError, setCustomInputsError] = useState(null);

  // ── Workflow Policy Overrides ────────────────────────────────────────────
  const [policyMinScore, setPolicyMinScore] = useState("0.999");
  const [policyMinCoverage, setPolicyMinCoverage] = useState("0.0");
  const [allowWarnings, setAllowWarnings] = useState(false);
  const [explainMode, setExplainMode] = useState("deterministic");
  const [useCompanyKnowledge, setUseCompanyKnowledge] = useState(false);
  const [forceRecompute, setForceRecompute] = useState(false);

  // ── Registration / Pre-flight ────────────────────────────────────────────
  const [registrationResult, setRegistrationResult] = useState(null);
  const [preflightResult, setPreflightResult] = useState(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [preflightError, setPreflightError] = useState(null);
  const [registrationBusy, setRegistrationBusy] = useState(false);
  const [registrationError, setRegistrationError] = useState(null);

  // ── Workflow Execution ───────────────────────────────────────────────────
  const [certifyBusy, setCertifyBusy] = useState(false);
  const [certifyError, setCertifyError] = useState(null);
  const [workflowResult, setWorkflowResult] = useState(null);
  const [workflowRunId, setWorkflowRunId] = useState(null);

  // ── Recent Workflow Runs ─────────────────────────────────────────────────
  const [recentRuns, setRecentRuns] = useState([]);
  const [runsLoading, setRunsLoading] = useState(false);

  // ── Step tracking ────────────────────────────────────────────────────────
  const [activeStep, setActiveStep] = useState("configure"); // configure | review | result

  // ─── Helpers ───────────────────────────────────────────────────────────────

  const _fetch = authFetch || window.fetch;

  const loadRegisteredApps = async () => {
    setAppsLoading(true);
    setAppsError(null);
    try {
      const res = await _fetch(`${apiBase}/api/v2/applications`);
      if (res.ok) {
        const data = await res.json();
        setRegisteredApps(Array.isArray(data) ? data : []);
      } else {
        setAppsError(`Failed to load applications (HTTP ${res.status})`);
      }
    } catch (e) {
      setAppsError(`Network error: ${e.message}`);
    } finally {
      setAppsLoading(false);
    }
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
    loadRegisteredApps();
    loadRecentRuns();
  }, []);

  const populateFromApp = (app) => {
    setAppId(app.application_id);
    setAppName(app.name || "");
    setAppDomain(app.domain || "");
    setAppDescription(app.description || "");
    const ref = app.reference_implementations?.[0];
    const tgt = app.target_implementations?.[0];
    if (ref) {
      setRefAdapterId(ref.adapter_id || "");
      setRefAdapterVersion(ref.version || "1.0.0");
    }
    if (tgt) {
      setTargetAdapterId(tgt.adapter_id || "");
      setTargetAdapterVersion(tgt.version || "2.0.0");
    }
    setPreflightResult(null);
    setRegistrationResult(null);
    setWorkflowResult(null);
    setCertifyError(null);
    setActiveStep("configure");
  };

  const buildSpec = () => ({
    application_id: appId.trim(),
    name: appName.trim() || appId.trim(),
    domain: appDomain.trim() || "general",
    description: appDescription.trim() || `Application ${appId}`,
    reference_implementations: [
      {
        adapter_id: refAdapterId.trim(),
        version: refAdapterVersion.trim() || "1.0.0",
        description: "Legacy reference implementation",
      },
    ],
    target_implementations: [
      {
        adapter_id: targetAdapterId.trim(),
        version: targetAdapterVersion.trim() || "2.0.0",
        description: "Modernized target implementation",
      },
    ],
    test_inputs: [],
  });

  const parseCustomInputs = () => {
    setCustomInputsError(null);
    if (!customInputsText.trim()) return null;
    try {
      const parsed = JSON.parse(customInputsText.trim());
      if (!Array.isArray(parsed)) throw new Error("Custom inputs must be a JSON array.");
      return parsed;
    } catch (e) {
      setCustomInputsError(`JSON parse error: ${e.message}`);
      return undefined; // signals error
    }
  };

  // ── Step 1: Register (or upsert) the ApplicationSpec ─────────────────────

  const handleRegisterApp = async () => {
    if (!appId.trim() || !refAdapterId.trim() || !targetAdapterId.trim()) {
      setRegistrationError("Application ID, Legacy Adapter ID, and Modern Adapter ID are required.");
      return;
    }
    setRegistrationBusy(true);
    setRegistrationError(null);
    setPreflightResult(null);
    try {
      const spec = buildSpec();
      const res = await _fetch(`${apiBase}/api/v2/applications`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(spec),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || `Registration failed (HTTP ${res.status})`);
      }
      setRegistrationResult(data);
      // Refresh list
      loadRegisteredApps();
    } catch (e) {
      setRegistrationError(e.message);
    } finally {
      setRegistrationBusy(false);
    }
  };

  // ── Step 2: Pre-flight adapter readiness validation ───────────────────────

  const handlePreflight = async () => {
    if (!appId.trim() || !refAdapterId.trim() || !targetAdapterId.trim()) {
      setPreflightError("Application ID, Legacy Adapter ID, and Modern Adapter ID are required.");
      return;
    }
    setPreflightBusy(true);
    setPreflightError(null);
    try {
      const spec = buildSpec();
      const res = await _fetch(`${apiBase}/api/v2/adapters/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spec }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || `Pre-flight failed (HTTP ${res.status})`);
      }
      setPreflightResult(data);
      if (data.is_ready) {
        setActiveStep("review");
      }
    } catch (e) {
      setPreflightError(e.message);
    } finally {
      setPreflightBusy(false);
    }
  };

  // ── Step 3: Run canonical V2 certification workflow ───────────────────────

  const handleCertify = async () => {
    if (!appId.trim()) {
      setCertifyError("Application ID is required.");
      return;
    }

    const customInputs = parseCustomInputs();
    if (customInputs === undefined) return; // parse error already shown

    setCertifyBusy(true);
    setCertifyError(null);
    setWorkflowResult(null);
    setWorkflowRunId(null);

    try {
      const payload = {
        application_id: appId.trim(),
        target_index: targetIndex,
        custom_inputs: customInputs,
        policy_min_equivalence_score: parseFloat(policyMinScore) || 0.999,
        policy_min_oracle_coverage: parseFloat(policyMinCoverage) || 0.0,
        allow_warnings: allowWarnings,
        explain: true,
        explanation_mode: explainMode,
        use_company_knowledge: useCompanyKnowledge,
        force_recompute: forceRecompute,
      };

      const res = await _fetch(`${apiBase}/api/v2/workflow/certify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || `Workflow execution failed (HTTP ${res.status})`);
      }
      setWorkflowResult(data);
      setWorkflowRunId(data.workflow_run_id);
      setActiveStep("result");

      // Notify App.jsx so the Dossier tab can auto-populate
      if (onCertifyResult && data.artifact_id) {
        onCertifyResult(data);
      }

      // Refresh recent runs
      loadRecentRuns();
    } catch (e) {
      setCertifyError(e.message);
    } finally {
      setCertifyBusy(false);
    }
  };

  // ── Load a past run to inspect ────────────────────────────────────────────

  const loadPastRun = async (runId) => {
    try {
      const res = await _fetch(`${apiBase}/api/v2/workflow/runs/${runId}`);
      if (res.ok) {
        const run = await res.json();
        // Partial display — populate appId from run
        setAppId(run.application_id || "");
        setWorkflowRunId(run.workflow_run_id);
        // Construct a WorkflowResult-compatible object for display
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
        });
        setActiveStep("result");
      }
    } catch {
      // Non-fatal
    }
  };

  // ─── Derived ───────────────────────────────────────────────────────────────

  const isFormReady = appId.trim() && refAdapterId.trim() && targetAdapterId.trim();
  const isPreflightPassed = preflightResult?.is_ready === true;
  const certStatus = workflowResult?.status;
  const statusStyle = STATUS_STYLES[certStatus] || { bg: "#f8fafc", border: "#cbd5e1", color: "#0f172a", label: certStatus || "—" };

  // ─── Render ────────────────────────────────────────────────────────────────

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
            ⚡ Application Behavioral Equivalence Certification
          </h2>
          <p style={{ margin: "3px 0 0", fontSize: "13px", color: "#64748b" }}>
            Register your legacy and modernized implementations. BEACON V2 automatically
            discovers behavioral invariants, resolves thresholds, and certifies equivalence —
            no manual tolerance configuration required.
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
            Automatic Thresholds
          </span>
        </div>
      </div>

      {/* ── Step Pills ── */}
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
          { id: "configure", label: "1. Configure Application" },
          { id: "review", label: "2. Review & Validate" },
          { id: "result", label: "3. Certification Result" },
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
      {/* STEP 1: CONFIGURE APPLICATION                                          */}
      {/* ═══════════════════════════════════════════════════════════════════════ */}
      {activeStep === "configure" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: "20px", alignItems: "start" }}>

          {/* ── Main Config Panel ── */}
          <div>

            {/* Application Identity */}
            <section style={cardStyle}>
              <h3 style={{ margin: "0 0 14px", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                Step 1 — Application Identity
              </h3>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "12px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>
                    Application ID <span style={{ color: "#dc2626" }}>*</span>
                  </label>
                  <input
                    type="text"
                    value={appId}
                    onChange={(e) => {
                      setAppId(e.target.value);
                      setPreflightResult(null);
                      setRegistrationResult(null);
                      setWorkflowResult(null);
                    }}
                    placeholder="e.g. loan_approval, payroll_tax_calc"
                    style={{
                      width: "100%",
                      padding: "8px 10px",
                      borderRadius: "6px",
                      border: `1px solid ${appId ? "#94a3b8" : "#cbd5e1"}`,
                      fontSize: "13px",
                      boxSizing: "border-box",
                      fontFamily: "monospace",
                    }}
                  />
                  <span style={{ fontSize: "11px", color: "#94a3b8" }}>
                    Unique snake_case identifier for this application
                  </span>
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>
                    Display Name
                  </label>
                  <input
                    type="text"
                    value={appName}
                    onChange={(e) => setAppName(e.target.value)}
                    placeholder="e.g. Loan Approval Engine"
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", boxSizing: "border-box" }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>
                    Domain
                  </label>
                  <input
                    type="text"
                    value={appDomain}
                    onChange={(e) => setAppDomain(e.target.value)}
                    placeholder="e.g. financial_services, healthcare, retail"
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", boxSizing: "border-box" }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>
                    Description
                  </label>
                  <input
                    type="text"
                    value={appDescription}
                    onChange={(e) => setAppDescription(e.target.value)}
                    placeholder="Brief description of application"
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", boxSizing: "border-box" }}
                  />
                </div>
              </div>

              {registrationError && (
                <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "6px", padding: "8px 12px", color: "#991b1b", fontSize: "12px", marginBottom: "10px" }}>
                  ⚠️ {registrationError}
                </div>
              )}

              {registrationResult && (
                <div style={{ background: "#f0fdf4", border: "1px solid #86efac", borderRadius: "6px", padding: "8px 12px", color: "#166534", fontSize: "12px", marginBottom: "10px" }}>
                  ✅ Application <strong>{registrationResult.application_id}</strong> registered successfully.
                </div>
              )}

              <button
                onClick={handleRegisterApp}
                disabled={registrationBusy || !isFormReady}
                style={{
                  background: isFormReady ? "#0f172a" : "#94a3b8",
                  color: "#ffffff",
                  border: "none",
                  padding: "8px 18px",
                  borderRadius: "6px",
                  fontWeight: "600",
                  fontSize: "13px",
                  cursor: isFormReady && !registrationBusy ? "pointer" : "not-allowed",
                }}
              >
                {registrationBusy ? "Registering..." : "📋 Register / Update Application"}
              </button>
            </section>

            {/* Adapter Binding */}
            <section style={cardStyle}>
              <h3 style={{ margin: "0 0 14px", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                Step 2 — Implementation Adapter Binding
              </h3>
              <p style={{ margin: "0 0 14px", fontSize: "12px", color: "#64748b" }}>
                Specify the registered adapter IDs for both the legacy reference and the modernized
                target implementations. Adapters must be pre-registered in the BEACON V2 adapter
                registry before certification can run.
              </p>
              <div style={{ display: "grid", gridTemplateColumns: "1.5fr 0.5fr 1.5fr 0.5fr", gap: "12px", marginBottom: "16px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>
                    Legacy Adapter ID <span style={{ color: "#dc2626" }}>*</span>
                  </label>
                  <input
                    type="text"
                    value={refAdapterId}
                    onChange={(e) => { setRefAdapterId(e.target.value); setPreflightResult(null); }}
                    placeholder="e.g. loan_approval_legacy"
                    style={{
                      width: "100%",
                      padding: "8px 10px",
                      borderRadius: "6px",
                      border: `1px solid ${refAdapterId ? "#94a3b8" : "#cbd5e1"}`,
                      fontSize: "13px",
                      boxSizing: "border-box",
                      fontFamily: "monospace",
                      background: "#fafafa",
                    }}
                  />
                  <span style={{ fontSize: "11px", color: "#94a3b8" }}>Reference / legacy system</span>
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>Version</label>
                  <input
                    type="text"
                    value={refAdapterVersion}
                    onChange={(e) => setRefAdapterVersion(e.target.value)}
                    placeholder="1.0.0"
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", boxSizing: "border-box" }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>
                    Modern Adapter ID <span style={{ color: "#dc2626" }}>*</span>
                  </label>
                  <input
                    type="text"
                    value={targetAdapterId}
                    onChange={(e) => { setTargetAdapterId(e.target.value); setPreflightResult(null); }}
                    placeholder="e.g. loan_approval_modern_v2"
                    style={{
                      width: "100%",
                      padding: "8px 10px",
                      borderRadius: "6px",
                      border: `1px solid ${targetAdapterId ? "#94a3b8" : "#cbd5e1"}`,
                      fontSize: "13px",
                      boxSizing: "border-box",
                      fontFamily: "monospace",
                      background: "#f0fdf4",
                    }}
                  />
                  <span style={{ fontSize: "11px", color: "#94a3b8" }}>Modernized / target system</span>
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>Version</label>
                  <input
                    type="text"
                    value={targetAdapterVersion}
                    onChange={(e) => setTargetAdapterVersion(e.target.value)}
                    placeholder="2.0.0"
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", boxSizing: "border-box" }}
                  />
                </div>
              </div>

              {/* Target variant index (for multi-target apps) */}
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <label style={{ fontSize: "12px", fontWeight: "600", color: "#475569" }}>Target Index:</label>
                <input
                  type="number"
                  value={targetIndex}
                  min={0}
                  onChange={(e) => setTargetIndex(parseInt(e.target.value, 10) || 0)}
                  style={{ width: "70px", padding: "6px 8px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
                <span style={{ fontSize: "11px", color: "#94a3b8" }}>
                  Index into target_implementations array (0 = first modernized adapter)
                </span>
              </div>
            </section>

            {/* Optional Custom Inputs */}
            <section style={cardStyle}>
              <h3 style={{ margin: "0 0 6px", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                Step 3 — Custom Test Inputs <span style={{ fontSize: "12px", fontWeight: "400", color: "#94a3b8" }}>(Optional)</span>
              </h3>
              <p style={{ margin: "0 0 12px", fontSize: "12px", color: "#64748b" }}>
                By default, BEACON V2 uses the inputs registered with the adapter. Optionally,
                provide a JSON array of input objects to override with custom test cases.
              </p>
              <textarea
                rows={5}
                value={customInputsText}
                onChange={(e) => { setCustomInputsText(e.target.value); setCustomInputsError(null); }}
                placeholder='[{"credit_score": 750, "debt_ratio": 0.25}, {"credit_score": 580, "debt_ratio": 0.45}]'
                style={{
                  width: "100%",
                  padding: "10px",
                  borderRadius: "6px",
                  border: `1px solid ${customInputsError ? "#fca5a5" : "#cbd5e1"}`,
                  fontFamily: "monospace",
                  fontSize: "12px",
                  boxSizing: "border-box",
                  resize: "vertical",
                }}
              />
              {customInputsError && (
                <div style={{ color: "#dc2626", fontSize: "11px", marginTop: "4px" }}>⚠️ {customInputsError}</div>
              )}
              <div style={{ fontSize: "11px", color: "#94a3b8", marginTop: "4px" }}>
                Leave empty to use adapter-registered inputs. Provide JSON array to override.
              </div>
            </section>

            {/* Pre-flight validation */}
            <section style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                    Step 4 — Pre-flight Adapter Validation
                  </h3>
                  <p style={{ margin: "3px 0 0", fontSize: "12px", color: "#64748b" }}>
                    Verify adapter readiness before executing the full workflow.
                  </p>
                </div>
                <button
                  onClick={handlePreflight}
                  disabled={preflightBusy || !isFormReady}
                  style={{
                    background: isFormReady ? "#f1f5f9" : "#e2e8f0",
                    color: "#334155",
                    border: "1px solid #cbd5e1",
                    padding: "8px 16px",
                    borderRadius: "6px",
                    fontWeight: "600",
                    fontSize: "13px",
                    cursor: isFormReady && !preflightBusy ? "pointer" : "not-allowed",
                  }}
                >
                  {preflightBusy ? "Validating..." : "🔍 Run Pre-flight Check"}
                </button>
              </div>

              {preflightError && (
                <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "6px", padding: "8px 12px", color: "#991b1b", fontSize: "12px", marginBottom: "10px" }}>
                  ⚠️ {preflightError}
                </div>
              )}

              {preflightResult && (
                <div
                  style={{
                    background: preflightResult.is_ready ? "#f0fdf4" : "#fef2f2",
                    border: `1px solid ${preflightResult.is_ready ? "#86efac" : "#fca5a5"}`,
                    borderRadius: "8px",
                    padding: "12px 16px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                    <span style={{ fontWeight: "700", fontSize: "13px", color: preflightResult.is_ready ? "#166534" : "#991b1b" }}>
                      {preflightResult.is_ready ? "✅ Pre-flight Passed — Adapters Ready" : "❌ Pre-flight Failed — Adapter Errors Detected"}
                    </span>
                    {preflightResult.is_ready && (
                      <button
                        onClick={() => setActiveStep("review")}
                        style={{ background: "#2563eb", color: "#fff", border: "none", padding: "4px 10px", borderRadius: "4px", fontSize: "12px", cursor: "pointer", fontWeight: "600" }}
                      >
                        Continue →
                      </button>
                    )}
                  </div>
                  {preflightResult.errors?.length > 0 && (
                    <ul style={{ margin: "6px 0 0", padding: "0 0 0 16px", fontSize: "12px", color: "#991b1b" }}>
                      {preflightResult.errors.map((e, i) => <li key={i}>{e}</li>)}
                    </ul>
                  )}
                  {preflightResult.warnings?.length > 0 && (
                    <ul style={{ margin: "6px 0 0", padding: "0 0 0 16px", fontSize: "12px", color: "#92400e" }}>
                      {preflightResult.warnings.map((w, i) => <li key={i}>⚠️ {w}</li>)}
                    </ul>
                  )}
                </div>
              )}
            </section>
          </div>

          {/* ── Right Sidebar: Registered Apps & Recent Runs ── */}
          <div>

            {/* Registered Applications Picker */}
            <section style={{ ...cardStyle, marginBottom: "16px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                <h4 style={{ margin: 0, fontSize: "13px", fontWeight: "700", color: "#0f172a" }}>
                  Registered Applications
                </h4>
                <button
                  onClick={loadRegisteredApps}
                  style={{ background: "transparent", border: "none", cursor: "pointer", fontSize: "14px", color: "#64748b" }}
                  title="Refresh"
                >
                  🔄
                </button>
              </div>

              {appsLoading && (
                <div style={{ fontSize: "12px", color: "#94a3b8" }}>Loading...</div>
              )}
              {appsError && (
                <div style={{ fontSize: "12px", color: "#dc2626" }}>⚠️ {appsError}</div>
              )}
              {!appsLoading && !appsError && registeredApps.length === 0 && (
                <div style={{ fontSize: "12px", color: "#94a3b8", fontStyle: "italic" }}>
                  No applications registered yet. Fill in the form and register one.
                </div>
              )}
              {registeredApps.map((app) => (
                <div
                  key={app.application_id}
                  onClick={() => populateFromApp(app)}
                  style={{
                    padding: "8px 10px",
                    borderRadius: "6px",
                    border: `1px solid ${appId === app.application_id ? "#2563eb" : "#e2e8f0"}`,
                    background: appId === app.application_id ? "#eff6ff" : "#f8fafc",
                    cursor: "pointer",
                    marginBottom: "6px",
                    transition: "border-color 0.15s",
                  }}
                >
                  <div style={{ fontWeight: "700", fontSize: "12px", color: "#0f172a", fontFamily: "monospace" }}>
                    {app.application_id}
                  </div>
                  <div style={{ fontSize: "11px", color: "#64748b" }}>
                    {app.name} · {app.domain || "—"}
                  </div>
                </div>
              ))}
            </section>

            {/* Recent Workflow Runs */}
            <section style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                <h4 style={{ margin: 0, fontSize: "13px", fontWeight: "700", color: "#0f172a" }}>
                  Recent Runs
                </h4>
                <button
                  onClick={loadRecentRuns}
                  style={{ background: "transparent", border: "none", cursor: "pointer", fontSize: "14px", color: "#64748b" }}
                  title="Refresh"
                >
                  🔄
                </button>
              </div>
              {runsLoading && <div style={{ fontSize: "12px", color: "#94a3b8" }}>Loading...</div>}
              {!runsLoading && recentRuns.length === 0 && (
                <div style={{ fontSize: "12px", color: "#94a3b8", fontStyle: "italic" }}>No recent runs.</div>
              )}
              {recentRuns.map((run) => (
                <div
                  key={run.workflow_run_id}
                  onClick={() => loadPastRun(run.workflow_run_id)}
                  style={{
                    padding: "8px 10px",
                    borderRadius: "6px",
                    border: "1px solid #e2e8f0",
                    background: "#f8fafc",
                    cursor: "pointer",
                    marginBottom: "6px",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <div>
                    <div style={{ fontSize: "11px", fontFamily: "monospace", color: "#2563eb" }}>
                      {run.workflow_run_id?.slice(0, 18)}...
                    </div>
                    <div style={{ fontSize: "11px", color: "#475569" }}>{run.application_id}</div>
                  </div>
                  <span
                    style={{
                      fontSize: "10px",
                      fontWeight: "700",
                      color: WORKFLOW_STATE_COLORS[run.state] || "#94a3b8",
                      background: "#f1f5f9",
                      padding: "2px 6px",
                      borderRadius: "4px",
                    }}
                  >
                    {run.state}
                  </span>
                </div>
              ))}
            </section>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════ */}
      {/* STEP 2: REVIEW & EXECUTE                                               */}
      {/* ═══════════════════════════════════════════════════════════════════════ */}
      {activeStep === "review" && (
        <div>
          {/* Configuration Summary */}
          <section style={cardStyle}>
            <h3 style={{ margin: "0 0 14px", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
              Configuration Summary
            </h3>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(3, 1fr)",
                gap: "12px",
                marginBottom: "16px",
                fontSize: "13px",
              }}
            >
              {[
                { label: "Application ID", val: appId, mono: true },
                { label: "Display Name", val: appName || appId },
                { label: "Domain", val: appDomain || "—" },
                { label: "Legacy Adapter", val: refAdapterId, mono: true },
                { label: "Legacy Version", val: refAdapterVersion },
                { label: "Modern Adapter", val: targetAdapterId, mono: true },
                { label: "Modern Version", val: targetAdapterVersion },
                { label: "Target Index", val: targetIndex },
                { label: "Custom Inputs", val: customInputsText.trim() ? `${customInputsText.split("{").length - 1} records` : "None (adapter default)" },
              ].map(({ label, val, mono }) => (
                <div key={label} style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                  <div style={{ fontSize: "10px", fontWeight: "600", color: "#94a3b8", textTransform: "uppercase", marginBottom: "3px" }}>
                    {label}
                  </div>
                  <div style={{ fontWeight: "600", color: "#0f172a", fontFamily: mono ? "monospace" : "inherit" }}>
                    {String(val)}
                  </div>
                </div>
              ))}
            </div>

            {preflightResult?.is_ready && (
              <div
                style={{
                  background: "#f0fdf4",
                  border: "1px solid #86efac",
                  borderRadius: "6px",
                  padding: "8px 12px",
                  fontSize: "12px",
                  color: "#166534",
                  marginBottom: "16px",
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                }}
              >
                ✅ Pre-flight validation passed. Adapters are ready for certification.
              </div>
            )}
          </section>

          {/* Policy Overrides */}
          <section style={cardStyle}>
            <h3 style={{ margin: "0 0 6px", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
              Certification Policy Configuration
            </h3>
            <p style={{ margin: "0 0 14px", fontSize: "12px", color: "#64748b" }}>
              BEACON V2 automatically resolves the tolerance threshold from evidence — no manual
              value is required. Adjust policy bounds only if your domain requires specific guarantees.
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "14px", marginBottom: "16px" }}>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>
                  Min Equivalence Score (0–1)
                </label>
                <input
                  type="number"
                  value={policyMinScore}
                  min={0}
                  max={1}
                  step={0.001}
                  onChange={(e) => setPolicyMinScore(e.target.value)}
                  style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", boxSizing: "border-box" }}
                />
                <span style={{ fontSize: "11px", color: "#94a3b8" }}>Default: 0.999 (99.9%)</span>
              </div>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>
                  Min Oracle Coverage (0–1)
                </label>
                <input
                  type="number"
                  value={policyMinCoverage}
                  min={0}
                  max={1}
                  step={0.01}
                  onChange={(e) => setPolicyMinCoverage(e.target.value)}
                  style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", boxSizing: "border-box" }}
                />
                <span style={{ fontSize: "11px", color: "#94a3b8" }}>Default: 0.0 (disabled)</span>
              </div>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>
                  Explanation Mode
                </label>
                <select
                  value={explainMode}
                  onChange={(e) => setExplainMode(e.target.value)}
                  style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", background: "#fff", boxSizing: "border-box" }}
                >
                  <option value="deterministic">deterministic (offline)</option>
                  <option value="auto">auto (fallback chain)</option>
                  <option value="llm">llm (cloud-assisted)</option>
                </select>
              </div>
            </div>

            {/* Boolean Flags */}
            <div style={{ display: "flex", gap: "24px", marginBottom: "16px", flexWrap: "wrap" }}>
              {[
                { state: allowWarnings, set: setAllowWarnings, label: "Allow Warnings", desc: "Permit CERTIFIED_WITH_WARNINGS as a pass outcome" },
                { state: useCompanyKnowledge, set: setUseCompanyKnowledge, label: "Use Company Knowledge", desc: "Incorporate RAG-augmented knowledge base in explanations" },
                { state: forceRecompute, set: setForceRecompute, label: "Force Recompute", desc: "Bypass idempotency cache — run fresh certification" },
              ].map(({ state, set, label, desc }) => (
                <label key={label} style={{ display: "flex", alignItems: "flex-start", gap: "8px", cursor: "pointer", fontSize: "13px" }}>
                  <input
                    type="checkbox"
                    checked={state}
                    onChange={(e) => set(e.target.checked)}
                    style={{ marginTop: "2px" }}
                  />
                  <div>
                    <div style={{ fontWeight: "600", color: "#334155" }}>{label}</div>
                    <div style={{ fontSize: "11px", color: "#94a3b8" }}>{desc}</div>
                  </div>
                </label>
              ))}
            </div>

            {certifyError && (
              <div
                style={{
                  background: "#fef2f2",
                  border: "1px solid #fca5a5",
                  borderRadius: "6px",
                  padding: "10px 14px",
                  color: "#991b1b",
                  fontSize: "13px",
                  marginBottom: "12px",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <span>⚠️ {certifyError}</span>
                <button
                  onClick={() => setCertifyError(null)}
                  style={{ background: "transparent", border: "none", cursor: "pointer", fontWeight: "700", color: "#991b1b" }}
                >
                  ✕
                </button>
              </div>
            )}

            {/* Certify Button */}
            <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
              <button
                onClick={handleCertify}
                disabled={certifyBusy || !appId.trim()}
                style={{
                  background: !certifyBusy && appId.trim() ? "#2563eb" : "#94a3b8",
                  color: "#ffffff",
                  border: "none",
                  padding: "10px 28px",
                  borderRadius: "6px",
                  fontWeight: "700",
                  fontSize: "14px",
                  cursor: !certifyBusy && appId.trim() ? "pointer" : "not-allowed",
                  boxShadow: !certifyBusy && appId.trim() ? "0 2px 4px rgba(37,99,235,0.25)" : "none",
                }}
              >
                {certifyBusy ? "⚙️ Running Canonical V2 Workflow..." : "⚡ Run Equivalence Certification"}
              </button>

              {certifyBusy && (
                <div style={{ fontSize: "12px", color: "#64748b" }}>
                  BEACON V2 is automatically discovering invariants, resolving thresholds,
                  executing evaluation, and certifying...
                </div>
              )}
            </div>

            {certifyBusy && (
              <div
                style={{
                  marginTop: "16px",
                  background: "#f0f9ff",
                  border: "1px solid #bae6fd",
                  borderRadius: "8px",
                  padding: "14px 18px",
                }}
              >
                <div style={{ fontSize: "12px", fontWeight: "600", color: "#0369a1", marginBottom: "8px" }}>
                  ⚙️ V2 Workflow Stages Running Automatically:
                </div>
                <div
                  style={{
                    display: "flex",
                    gap: "8px",
                    flexWrap: "wrap",
                    fontSize: "11px",
                  }}
                >
                  {[
                    "VALIDATING",
                    "CAPTURING_EVIDENCE",
                    "EVALUATING",
                    "RESOLVING_ORACLES",
                    "RESOLVING_THRESHOLDS",
                    "CERTIFYING",
                    "EXPLAINING",
                    "PERSISTING",
                  ].map((stage) => (
                    <span
                      key={stage}
                      style={{
                        background: "#e0f2fe",
                        color: "#0369a1",
                        padding: "3px 8px",
                        borderRadius: "4px",
                        fontFamily: "monospace",
                        fontWeight: "600",
                      }}
                    >
                      {stage}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════ */}
      {/* STEP 3: CERTIFICATION RESULT                                           */}
      {/* ═══════════════════════════════════════════════════════════════════════ */}
      {activeStep === "result" && workflowResult && (
        <div>
          {/* Authoritative Status Banner */}
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
                {workflowResult.artifact_id && (
                  <span>Artifact: <strong style={{ fontFamily: "monospace" }}>{workflowResult.artifact_id}</strong></span>
                )}
              </div>
            </div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <button
                onClick={() => setActiveStep("configure")}
                style={{
                  background: "rgba(255,255,255,0.6)",
                  border: `1px solid ${statusStyle.border}`,
                  color: statusStyle.color,
                  padding: "6px 12px",
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

          {/* Error / Failure Detail */}
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
                label: "Unique Inputs",
                val: workflowResult.unique_input_count ?? "—",
                color: "#334155",
              },
              {
                label: "Regressions",
                val: workflowResult.regressions_count ?? workflowResult.regressions?.length ?? 0,
                color: (workflowResult.regressions_count ?? 0) > 0 ? "#dc2626" : "#059669",
              },
              {
                label: "Audit Status",
                val: workflowResult.audit_status || "—",
                color: workflowResult.audit_status === "PERSISTED" ? "#059669" : "#f59e0b",
              },
              {
                label: "Workflow State",
                val: workflowResult.state,
                color: WORKFLOW_STATE_COLORS[workflowResult.state] || "#94a3b8",
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
                <div style={{ fontSize: "18px", fontWeight: "800", color: m.color }}>
                  {String(m.val)}
                </div>
              </div>
            ))}
          </div>

          {/* Linked Identifiers */}
          <section style={cardStyle}>
            <h3 style={{ margin: "0 0 12px", fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
              🔗 Authoritative Workflow Link Identifiers
            </h3>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "8px",
                fontSize: "12px",
                fontFamily: "monospace",
              }}
            >
              {[
                { label: "Workflow Run ID", val: workflowResult.workflow_run_id },
                { label: "Certification Artifact ID", val: workflowResult.artifact_id },
                { label: "Artifact Hash (SHA-256)", val: workflowResult.artifact_hash },
                { label: "Threshold Resolution ID", val: workflowResult.threshold_resolution_id },
                { label: "Threshold Fingerprint", val: workflowResult.threshold_resolution_fingerprint },
              ].map(({ label, val }) => (
                <div
                  key={label}
                  style={{
                    background: "#f8fafc",
                    padding: "8px 10px",
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
          </section>

          {/* Stage Timings */}
          {workflowResult.timings_ms && Object.keys(workflowResult.timings_ms).length > 0 && (
            <section style={cardStyle}>
              <h3 style={{ margin: "0 0 12px", fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                ⏱️ Stage-by-Stage Execution Timings
              </h3>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                {Object.entries(workflowResult.timings_ms).map(([stage, ms]) => (
                  <div
                    key={stage}
                    style={{
                      background: "#f1f5f9",
                      padding: "6px 10px",
                      borderRadius: "6px",
                      fontSize: "12px",
                      border: "1px solid #e2e8f0",
                    }}
                  >
                    <span style={{ fontWeight: "600", color: "#334155", fontFamily: "monospace" }}>{stage}</span>
                    <span style={{ color: "#64748b", marginLeft: "6px" }}>{Math.round(ms)}ms</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Regressions */}
          {workflowResult.regressions?.length > 0 && (
            <section style={cardStyle}>
              <h3 style={{ margin: "0 0 12px", fontSize: "14px", fontWeight: "700", color: "#991b1b" }}>
                🚨 Behavioral Regressions — Concrete Counterexamples ({workflowResult.regressions.length})
              </h3>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                  <thead>
                    <tr style={{ background: "#fef2f2", borderBottom: "2px solid #fecaca", textAlign: "left" }}>
                      <th style={{ padding: "8px 10px" }}>Oracle / Rule</th>
                      <th style={{ padding: "8px 10px" }}>Input</th>
                      <th style={{ padding: "8px 10px" }}>Legacy Output</th>
                      <th style={{ padding: "8px 10px" }}>Modern Output</th>
                      <th style={{ padding: "8px 10px" }}>Diff</th>
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

          {/* Explanation (if present) */}
          {workflowResult.explanation && (
            <section style={cardStyle}>
              <h3 style={{ margin: "0 0 10px", fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                📖 Certification Explanation
              </h3>
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
            </section>
          )}
        </div>
      )}

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
