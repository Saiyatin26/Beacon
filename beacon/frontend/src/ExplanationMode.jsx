import { useEffect, useState } from "react";

export default function ExplanationMode({
  apiBase,
  authToken,
  activeResult,
  customActiveResult,
  historicalArtifacts = [],
}) {
  const [selectedCertId, setSelectedCertId] = useState(() => {
    return (
      activeResult?.certification_id ||
      customActiveResult?.certification_id ||
      (historicalArtifacts.length > 0 ? historicalArtifacts[0].certification_id : "")
    );
  });

  const [explanation, setExplanation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  // Configuration controls
  const [genMode, setGenMode] = useState("auto"); // auto, deterministic, assisted, llm
  const [useKnowledge, setUseKnowledge] = useState(true);
  const [preferredProvider, setPreferredProvider] = useState("auto");

  // Interactive QA state
  const [qaQuestion, setQaQuestion] = useState("");
  const [qaLoading, setQaLoading] = useState(false);
  const [qaHistory, setQaHistory] = useState([]);

  // Sync selected cert ID if active result or historical artifacts arrive
  useEffect(() => {
    if (!selectedCertId) {
      const defaultId =
        activeResult?.certification_id ||
        customActiveResult?.certification_id ||
        (historicalArtifacts.length > 0 ? historicalArtifacts[0].certification_id : "");
      if (defaultId) setSelectedCertId(defaultId);
    }
  }, [activeResult, customActiveResult, historicalArtifacts, selectedCertId]);

  // Load explanation when cert ID changes
  useEffect(() => {
    if (selectedCertId) {
      loadExplanation(selectedCertId, false);
    }
  }, [selectedCertId]);

  const authFetch = (url, options = {}) => {
    const headers = { ...(options.headers || {}) };
    if (authToken) {
      headers["Authorization"] = `Bearer ${authToken}`;
    }
    return fetch(url, { ...options, headers });
  };

  const loadExplanation = async (certId, forceRecompute = false) => {
    if (!certId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch(`${apiBase}/api/v2/certifications/${certId}/explanation`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: genMode,
          use_company_knowledge: useKnowledge,
          preferred_provider: preferredProvider,
          force_recompute: forceRecompute,
        }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to load explanation.");
      }
      const data = await res.json();
      setExplanation(data);
      if (forceRecompute) {
        setNotice("Explanation successfully synthesized and verified.");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleAskQuestion = async (customPrompt) => {
    const questionText = customPrompt || qaQuestion;
    if (!questionText.trim() || !selectedCertId) return;

    setQaLoading(true);
    setError(null);
    try {
      const res = await authFetch(`${apiBase}/api/v2/certifications/${selectedCertId}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: questionText,
          use_company_knowledge: useKnowledge,
          preferred_provider: preferredProvider,
        }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to process question.");
      }
      const ansData = await res.json();
      setQaHistory((prev) => [ansData, ...prev]);
      if (!customPrompt) setQaQuestion("");
    } catch (err) {
      setError(err.message);
    } finally {
      setQaLoading(false);
    }
  };

  const cardStyle = {
    background: "#ffffff",
    border: "1px solid #e2e8f0",
    borderRadius: "12px",
    padding: "20px",
    boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
    marginBottom: "20px",
  };

  const badgeStyle = (bg, color, border) => ({
    display: "inline-flex",
    alignItems: "center",
    gap: "5px",
    padding: "4px 10px",
    borderRadius: "9999px",
    fontSize: "12px",
    fontWeight: "600",
    background: bg,
    color: color,
    border: `1px solid ${border || bg}`,
  });

  const getVerdictBadge = (verdict) => {
    const v = String(verdict || "").toUpperCase();
    if (v.includes("CERTIFIED") && !v.includes("NOT") && !v.includes("WARNING")) {
      return badgeStyle("#ecfdf5", "#065f46", "#10b981");
    }
    if (v.includes("WARNING")) {
      return badgeStyle("#fffbeb", "#92400e", "#f59e0b");
    }
    if (v.includes("INSUFFICIENT") || v.includes("INCONCLUSIVE")) {
      return badgeStyle("#fff7ed", "#9a3412", "#f97316");
    }
    return badgeStyle("#fef2f2", "#991b1b", "#ef4444");
  };

  return (
    <div style={{ maxWidth: "1440px", margin: "0 auto" }}>
      {/* Notifications */}
      {error && (
        <div style={{ background: "#fef2f2", border: "1px solid #f87171", color: "#991b1b", padding: "14px 18px", borderRadius: "8px", marginBottom: "20px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>⚠️ <strong>Error:</strong> {error}</span>
          <button onClick={() => setError(null)} style={{ background: "transparent", border: "none", cursor: "pointer", fontWeight: "700", color: "#991b1b" }}>✕</button>
        </div>
      )}
      {notice && (
        <div style={{ background: "#ecfdf5", border: "1px solid #34d399", color: "#065f46", padding: "14px 18px", borderRadius: "8px", marginBottom: "20px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>ℹ️ {notice}</span>
          <button onClick={() => setNotice(null)} style={{ background: "transparent", border: "none", cursor: "pointer", fontWeight: "700", color: "#065f46" }}>✕</button>
        </div>
      )}

      {/* Header & Controls Panel */}
      <div style={cardStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", borderBottom: "1px solid #e2e8f0", paddingBottom: "16px", marginBottom: "16px" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <span style={{ fontSize: "24px" }}>🤖</span>
              <h2 style={{ margin: 0, fontSize: "20px", fontWeight: "800", color: "#0f172a" }}>
                Intelligent Agent & Detailed Certification Explanations
              </h2>
            </div>
            <p style={{ margin: "4px 0 0", fontSize: "13px", color: "#64748b" }}>
              Transform deterministic empirical evidence, reconciled invariants, and enterprise knowledge into audit-ready explanations.
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={badgeStyle("#f8fafc", "#475569", "#cbd5e1")}>
              🛡️ Authoritative Trust Boundary Active
            </span>
          </div>
        </div>

        {/* Configuration Bar */}
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr auto", gap: "12px", alignItems: "center" }}>
          {/* Certification Run Selector */}
          <div>
            <label style={{ display: "block", fontSize: "11px", fontWeight: "700", color: "#475569", textTransform: "uppercase", marginBottom: "4px" }}>
              Target Certification Run
            </label>
            <select
              value={selectedCertId}
              onChange={(e) => setSelectedCertId(e.target.value)}
              style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", fontFamily: "monospace" }}
            >
              <option value="">-- Select a Certification Run --</option>
              {!activeResult && !customActiveResult && historicalArtifacts.length === 0 && (
                <option value="" disabled>No certification runs available</option>
              )}
              {activeResult && <option value={activeResult.certification_id}>Active Run: {activeResult.certification_id} ({activeResult.benchmark_id || "benchmark"})</option>}
              {customActiveResult && <option value={customActiveResult.certification_id}>Custom Run: {customActiveResult.certification_id} ({customActiveResult.project_id || "custom"})</option>}
              {historicalArtifacts.map((a) => (
                <option key={a.certification_id} value={a.certification_id}>
                  {a.certification_id} • {a.benchmark_id || a.project_id} • {a.status}
                </option>
              ))}
            </select>
          </div>

          {/* Intelligence Mode Selector */}
          <div>
            <label style={{ display: "block", fontSize: "11px", fontWeight: "700", color: "#475569", textTransform: "uppercase", marginBottom: "4px" }}>
              Intelligence Mode
            </label>
            <select
              value={genMode}
              onChange={(e) => setGenMode(e.target.value)}
              style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
            >
              <option value="auto">Auto (AI + Fallback)</option>
              <option value="deterministic">Deterministic (Offline)</option>
              <option value="assisted">Assisted (Context + LLM)</option>
              <option value="llm">Strict LLM (OpenRouter)</option>
            </select>
          </div>

          {/* Preferred Provider */}
          <div>
            <label style={{ display: "block", fontSize: "11px", fontWeight: "700", color: "#475569", textTransform: "uppercase", marginBottom: "4px" }}>
              LLM Provider
            </label>
            <select
              value={preferredProvider}
              onChange={(e) => setPreferredProvider(e.target.value)}
              style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
            >
              <option value="auto">Auto Provider Chain</option>
              <option value="openrouter">OpenRouter (Cloud)</option>
              <option value="anthropic">Anthropic Claude</option>
              <option value="ollama">Ollama (Local)</option>
              <option value="offline">Offline (Rule Engine)</option>
            </select>
          </div>

          {/* Company Knowledge Toggle */}
          <div>
            <label style={{ display: "block", fontSize: "11px", fontWeight: "700", color: "#475569", textTransform: "uppercase", marginBottom: "4px" }}>
              Phase 9 Knowledge
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", color: "#334155", cursor: "pointer", marginTop: "8px" }}>
              <input
                type="checkbox"
                checked={useKnowledge}
                onChange={(e) => setUseKnowledge(e.target.checked)}
              />
              Include PDF/DOCX
            </label>
          </div>

          {/* Re-generate Button */}
          <div>
            <label style={{ display: "block", fontSize: "11px", fontWeight: "700", color: "transparent", textTransform: "uppercase", marginBottom: "4px" }}>
              Action
            </label>
            <button
              onClick={() => loadExplanation(selectedCertId, true)}
              disabled={loading || !selectedCertId}
              style={{
                background: "#2563eb",
                color: "#ffffff",
                border: "none",
                padding: "8px 16px",
                borderRadius: "6px",
                fontWeight: "600",
                fontSize: "13px",
                cursor: loading || !selectedCertId ? "not-allowed" : "pointer",
                opacity: loading || !selectedCertId ? 0.6 : 1,
              }}
            >
              {loading ? "Generating..." : "⚡ Generate"}
            </button>
          </div>
        </div>
      </div>

      {loading && (
        <div style={{ textAlign: "center", padding: "60px 20px", color: "#64748b" }}>
          <div style={{ fontSize: "28px", marginBottom: "12px" }}>⏳</div>
          <div style={{ fontSize: "16px", fontWeight: "600" }}>Synthesizing Authoritative Explanation...</div>
          <p style={{ fontSize: "13px", margin: "6px 0 0" }}>Validating evidence traces, rule impacts, and hallucination guardrails.</p>
        </div>
      )}

      {!loading && explanation && (
        <>
          {/* Hero Verdict Banner */}
          <div
            style={{
              ...cardStyle,
              borderLeft: `6px solid ${
                explanation.overall_verdict.includes("CERTIFIED") && !explanation.overall_verdict.includes("NOT")
                  ? "#10b981"
                  : explanation.overall_verdict.includes("INSUFFICIENT")
                  ? "#f97316"
                  : "#ef4444"
              }`,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  <span style={{ fontSize: "20px" }}>
                    {explanation.overall_verdict.includes("CERTIFIED") && !explanation.overall_verdict.includes("NOT") ? "✅" : "⚠️"}
                  </span>
                  <h3 style={{ margin: 0, fontSize: "18px", fontWeight: "800", color: "#0f172a" }}>
                    Authoritative Verdict: {explanation.overall_verdict}
                  </h3>
                  <span style={getVerdictBadge(explanation.overall_verdict)}>
                    {explanation.overall_verdict}
                  </span>
                </div>
                <p style={{ margin: "8px 0 0", fontSize: "14px", color: "#334155", lineHeight: "1.6" }}>
                  {explanation.executive_summary}
                </p>
              </div>

              <div style={{ textAlign: "right" }}>
                <span style={badgeStyle("#f1f5f9", "#475569")}>
                  Mode: {explanation.generation_metadata?.generation_mode || "DETERMINISTIC"}
                </span>
                <div style={{ fontSize: "11px", color: "#64748b", fontFamily: "monospace", marginTop: "6px" }}>
                  Fingerprint: {explanation.context_fingerprint?.slice(0, 16)}...
                </div>
              </div>
            </div>

            {/* KPI Metrics */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "12px", marginTop: "18px" }}>
              <div style={{ background: "#f8fafc", padding: "10px 14px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "11px", color: "#64748b", textTransform: "uppercase" }}>Equivalence Score</div>
                <div style={{ fontSize: "20px", fontWeight: "800", color: (explanation.scope_summary?.equivalence_score || 0) >= 0.8 ? "#059669" : "#dc2626" }}>
                  {((explanation.scope_summary?.equivalence_score || 0) * 100).toFixed(1)}%
                </div>
              </div>
              <div style={{ background: "#f8fafc", padding: "10px 14px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "11px", color: "#64748b", textTransform: "uppercase" }}>Evaluated Inputs</div>
                <div style={{ fontSize: "20px", fontWeight: "800", color: "#0f172a" }}>
                  {explanation.scope_summary?.evaluated_inputs || 0}
                </div>
              </div>
              <div style={{ background: "#f8fafc", padding: "10px 14px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "11px", color: "#64748b", textTransform: "uppercase" }}>Matching Cases</div>
                <div style={{ fontSize: "20px", fontWeight: "800", color: "#059669" }}>
                  {explanation.scope_summary?.matching_cases || 0}
                </div>
              </div>
              <div style={{ background: "#f8fafc", padding: "10px 14px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "11px", color: "#64748b", textTransform: "uppercase" }}>Regressions</div>
                <div style={{ fontSize: "20px", fontWeight: "800", color: (explanation.scope_summary?.regression_cases || 0) > 0 ? "#dc2626" : "#059669" }}>
                  {explanation.scope_summary?.regression_cases || 0}
                </div>
              </div>
              <div style={{ background: "#f8fafc", padding: "10px 14px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "11px", color: "#64748b", textTransform: "uppercase" }}>Rules Evaluated</div>
                <div style={{ fontSize: "20px", fontWeight: "800", color: "#2563eb" }}>
                  {explanation.rule_impacts?.length || 0}
                </div>
              </div>
            </div>

            {/* Authoritative Provenance Strip (Requirement 22) */}
            <div
              style={{
                marginTop: "16px",
                padding: "12px 16px",
                borderRadius: "8px",
                background: "#f1f5f9",
                border: "1px solid #cbd5e1",
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                gap: "12px",
                fontSize: "12px",
              }}
            >
              <div>
                <span style={{ color: "#64748b", fontWeight: "600" }}>Certification Run: </span>
                <span style={{ fontFamily: "monospace", color: "#0f172a", fontWeight: "700" }}>{explanation.certification_id}</span>
              </div>
              <div>
                <span style={{ color: "#64748b", fontWeight: "600" }}>Deterministic Verdict: </span>
                <span style={{ fontWeight: "700", color: explanation.overall_verdict.includes("CERTIFIED") && !explanation.overall_verdict.includes("NOT") ? "#059669" : "#dc2626" }}>
                  {explanation.overall_verdict}
                </span>
              </div>
              <div>
                <span style={{ color: "#64748b", fontWeight: "600" }}>AI Provider: </span>
                <span style={{ fontWeight: "700", color: "#1e293b" }}>{explanation.generation_metadata?.provider || "offline"}</span>
              </div>
              <div>
                <span style={{ color: "#64748b", fontWeight: "600" }}>Model: </span>
                <span style={{ fontWeight: "700", fontFamily: "monospace", color: "#1e293b" }}>{explanation.generation_metadata?.model || "deterministic"}</span>
              </div>
              <div>
                <span style={{ color: "#64748b", fontWeight: "600" }}>RAG Knowledge: </span>
                <span style={{ fontWeight: "700", color: explanation.company_knowledge_context?.citations?.length > 0 ? "#2563eb" : "#64748b" }}>
                  {explanation.company_knowledge_context?.citations?.length > 0
                    ? `${explanation.company_knowledge_context.citations.length} sources retrieved`
                    : "Not Used / No Citations"}
                </span>
              </div>
              <div>
                <span style={{ color: "#64748b", fontWeight: "600" }}>Grounding: </span>
                <span style={{ fontWeight: "700", color: "#059669" }}>
                  {explanation.audit_status === "PERSISTED" ? "VERIFIED (Empirical Grounding)" : explanation.audit_status}
                </span>
              </div>
              <div>
                <span style={{ color: "#64748b", fontWeight: "600" }}>Fallback Status: </span>
                <span style={{ fontWeight: "700", color: explanation.generation_metadata?.fallback_occurred ? "#d97706" : "#059669" }}>
                  {explanation.generation_metadata?.fallback_occurred ? `Fallback Used: ${explanation.generation_metadata.fallback_reason || "Deterministic"}` : "Direct Provider Output"}
                </span>
              </div>
              <div>
                <span style={{ color: "#64748b", fontWeight: "600" }}>Evidence Context: </span>
                <span style={{ fontWeight: "700", color: "#1e293b" }}>
                  {explanation.evidence_traces?.length || 0} traces / {explanation.scope_summary?.evaluated_inputs || 0} inputs
                </span>
              </div>
            </div>
          </div>

          {/* Behavioral Dimensions & Rule Impact Section */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px" }}>
            {/* Dimension Breakdown */}
            <div style={cardStyle}>
              <h4 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                📊 Behavioral Dimension Explanations
              </h4>
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {explanation.dimension_explanations?.map((dim, idx) => (
                  <div key={idx} style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                      <span style={{ fontWeight: "700", fontSize: "13px", color: "#1e293b" }}>{dim.dimension}</span>
                      <span style={badgeStyle(dim.status === "PASS" ? "#ecfdf5" : "#fef2f2", dim.status === "PASS" ? "#065f46" : "#991b1b")}>
                        {dim.status}
                      </span>
                    </div>
                    <p style={{ margin: "4px 0", fontSize: "12px", color: "#475569" }}>{dim.difference_summary}</p>
                    {dim.findings?.map((f, fIdx) => (
                      <div key={fIdx} style={{ fontSize: "11px", color: "#64748b", background: "#ffffff", padding: "6px 8px", borderRadius: "4px", marginTop: "4px", border: "1px solid #cbd5e1" }}>
                        <strong>{f.support}:</strong> {f.statement}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>

            {/* Affected Behavioral Rules */}
            <div style={cardStyle}>
              <h4 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                ⚖️ Reconciled Invariant & Rule Impacts
              </h4>
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {explanation.rule_impacts?.map((r, idx) => (
                  <div key={idx} style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                      <span style={{ fontWeight: "700", fontSize: "13px", color: "#2563eb", fontFamily: "monospace" }}>{r.rule_id}</span>
                      <span style={badgeStyle(r.status === "COMPLIANT" ? "#ecfdf5" : "#fee2e2", r.status === "COMPLIANT" ? "#065f46" : "#991b1b")}>
                        {r.status}
                      </span>
                    </div>
                    <div style={{ fontSize: "12px", color: "#334155", fontWeight: "500" }}>{r.rule_description}</div>
                    <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px" }}><em>{r.observed_behavior}</em></div>
                  </div>
                ))}
                {explanation.rule_impacts?.length === 0 && (
                  <p style={{ fontSize: "13px", color: "#64748b" }}>No rule contradictions detected.</p>
                )}
              </div>
            </div>
          </div>

          {/* Missing Evidence & Uncertainty Disclosures */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px" }}>
            {/* Missing Evidence */}
            <div style={cardStyle}>
              <h4 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: "700", color: "#9a3412" }}>
                ❓ Missing Evidence Disclosures
              </h4>
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {explanation.missing_evidence?.map((m, idx) => (
                  <div key={idx} style={{ background: "#fff7ed", border: "1px solid #fed7aa", borderRadius: "8px", padding: "12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                      <span style={{ fontWeight: "700", fontSize: "12px", color: "#9a3412" }}>{m.dimension} Evidence</span>
                      <span style={badgeStyle("#ffedd5", "#9a3412")}>{m.status}</span>
                    </div>
                    <p style={{ margin: "2px 0", fontSize: "12px", color: "#7c2d12" }}>{m.description}</p>
                    <div style={{ fontSize: "11px", color: "#9a3412", marginTop: "4px" }}><strong>Implication:</strong> {m.implication}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Uncertainty Notes */}
            <div style={cardStyle}>
              <h4 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: "700", color: "#475569" }}>
                🔍 Uncertainty & Epistemic Boundaries
              </h4>
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {explanation.uncertainty_notes?.map((u, idx) => (
                  <div key={idx} style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                      <span style={{ fontWeight: "700", fontSize: "12px", color: "#334155" }}>{u.topic}</span>
                      <span style={badgeStyle("#f1f5f9", "#475569")}>{u.support_level}</span>
                    </div>
                    <p style={{ margin: "2px 0", fontSize: "12px", color: "#475569" }}>{u.claim}</p>
                    <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px" }}><strong>Reason:</strong> {u.reason}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Phase 9 Company Knowledge Citations */}
          {explanation.company_knowledge_context?.citations?.length > 0 && (
            <div style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <h4 style={{ margin: 0, fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                  📚 Retrieved Enterprise Knowledge Citations (Phase 9)
                </h4>
                <span style={badgeStyle("#eff6ff", "#1d4ed8")}>
                  {explanation.company_knowledge_context.citations.length} Citations Retrieved
                </span>
              </div>
              <p style={{ fontSize: "12px", color: "#64748b", margin: "0 0 12px 0" }}>
                {explanation.company_knowledge_context.citation_note}
              </p>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "12px" }}>
                {explanation.company_knowledge_context.citations.map((c, idx) => (
                  <div key={idx} style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                      <span style={{ fontWeight: "700", fontSize: "12px", color: "#2563eb" }}>📄 {c.filename}</span>
                      <span style={{ fontSize: "11px", color: "#64748b" }}>Relevance: {(c.relevance_score * 100).toFixed(0)}%</span>
                    </div>
                    <p style={{ margin: 0, fontSize: "12px", color: "#334155", fontStyle: "italic", background: "#ffffff", padding: "8px", borderRadius: "4px", border: "1px solid #cbd5e1" }}>
                      "{c.content_snippet}"
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Actionable Recommendations */}
          <div style={cardStyle}>
            <h4 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
              🛠️ Prioritized Actionable Investigation Recommendations
            </h4>
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              {explanation.investigation_recommendations?.map((rec, idx) => (
                <div key={idx} style={{ display: "flex", alignItems: "flex-start", gap: "12px", background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "12px" }}>
                  <div style={{ background: "#2563eb", color: "#ffffff", borderRadius: "50%", width: "24px", height: "24px", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "12px", fontWeight: "700", flexShrink: 0 }}>
                    {rec.priority}
                  </div>
                  <div>
                    <h5 style={{ margin: "0 0 4px 0", fontSize: "13px", fontWeight: "700", color: "#0f172a" }}>{rec.title}</h5>
                    <p style={{ margin: "0 0 4px 0", fontSize: "12px", color: "#475569" }}>{rec.description}</p>
                    <div style={{ fontSize: "11px", color: "#64748b" }}><strong>Rationale:</strong> {rec.rationale}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Interactive "Ask the Certification" Chat Module */}
          <div style={cardStyle}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "12px" }}>
              <span style={{ fontSize: "20px" }}>💬</span>
              <h4 style={{ margin: 0, fontSize: "16px", fontWeight: "700", color: "#0f172a" }}>
                Ask the Certification Assistant
              </h4>
            </div>
            <p style={{ margin: "0 0 14px 0", fontSize: "13px", color: "#64748b" }}>
              Ask targeted questions about the behavioral evaluation, counterexamples, rules, or evidence.
            </p>

            {/* Quick Prompt Pills */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginBottom: "14px" }}>
              {[
                "Why did the reference and target differ?",
                "Which specific inputs exposed the behavioral difference?",
                "Which OracleSet rules were potentially violated?",
                "What evidence is missing for a complete proof?",
                "What is the recommended next investigation step?",
              ].map((prompt, pIdx) => (
                <button
                  key={pIdx}
                  onClick={() => handleAskQuestion(prompt)}
                  disabled={qaLoading}
                  style={{
                    background: "#f1f5f9",
                    border: "1px solid #cbd5e1",
                    borderRadius: "16px",
                    padding: "6px 12px",
                    fontSize: "12px",
                    color: "#334155",
                    cursor: "pointer",
                    textAlign: "left",
                  }}
                >
                  💡 {prompt}
                </button>
              ))}
            </div>

            {/* Question Input Box */}
            <div style={{ display: "flex", gap: "10px", marginBottom: "18px" }}>
              <input
                type="text"
                value={qaQuestion}
                onChange={(e) => setQaQuestion(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleAskQuestion()}
                placeholder="Type your question about this certification run..."
                style={{ flex: 1, padding: "10px 14px", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "13px" }}
              />
              <button
                onClick={() => handleAskQuestion()}
                disabled={qaLoading || !qaQuestion.trim()}
                style={{
                  background: "#2563eb",
                  color: "#ffffff",
                  border: "none",
                  padding: "10px 20px",
                  borderRadius: "8px",
                  fontWeight: "600",
                  fontSize: "13px",
                  cursor: qaLoading || !qaQuestion.trim() ? "not-allowed" : "pointer",
                }}
              >
                {qaLoading ? "Thinking..." : "Ask"}
              </button>
            </div>

            {/* QA Conversation Stream */}
            {qaHistory.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {qaHistory.map((item, qIdx) => (
                  <div key={qIdx} style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "14px" }}>
                    <div style={{ fontWeight: "700", fontSize: "13px", color: "#0f172a", marginBottom: "6px" }}>
                      Q: {item.question}
                    </div>
                    <p style={{ margin: "0 0 8px 0", fontSize: "13px", color: "#334155", lineHeight: "1.5" }}>
                      {item.answer}
                    </p>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", fontSize: "11px", color: "#64748b" }}>
                      <span style={badgeStyle("#e2e8f0", "#334155")}>Support: {item.support_level}</span>
                      {item.referenced_evidence_ids?.map((eid) => (
                        <span key={eid} style={badgeStyle("#eff6ff", "#1e40af")}>Proof: {eid}</span>
                      ))}
                      {item.referenced_rule_ids?.map((rid) => (
                        <span key={rid} style={badgeStyle("#fdf4ff", "#7e22ce")}>Rule: {rid}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
