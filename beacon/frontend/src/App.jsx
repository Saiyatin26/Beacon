import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

const API_BASE = "http://localhost:8000";

// Reusable Design Tokens & Styles
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
  padding: "3px 10px",
  borderRadius: "9999px",
  fontSize: "12px",
  fontWeight: "600",
  background: bg,
  color: color,
  border: `1px solid ${border || bg}`,
});

const statusBadgeStyles = {
  CERTIFIED: { bg: "#ecfdf5", border: "#10b981", color: "#065f46", text: "CERTIFIED" },
  CERTIFIED_WITH_WARNINGS: { bg: "#fffbeb", border: "#f59e0b", color: "#92400e", text: "CERTIFIED WITH WARNINGS" },
  NOT_CERTIFIED: { bg: "#fef2f2", border: "#ef4444", color: "#991b1b", text: "NOT CERTIFIED" },
  REFERENCE_INCONSISTENT: { bg: "#f5f3ff", border: "#8b5cf6", color: "#5b21b6", text: "REFERENCE INCONSISTENT" },
  INSUFFICIENT_COVERAGE: { bg: "#fff7ed", border: "#f97316", color: "#9a3412", text: "INSUFFICIENT COVERAGE" },
  ORACLE_SET_INVALID: { bg: "#fef2f2", border: "#dc2626", color: "#7f1d1d", text: "ORACLE SET INVALID" },
};

export default function App() {
  // Navigation Tabs
  const [activeTab, setActiveTab] = useState("benchmark"); // benchmark, history, audit, drift, loan_demo

  // Benchmark Selection & Step Workflow State
  const [benchmarks, setBenchmarks] = useState([]);
  const [selectedBenchmarkId, setSelectedBenchmarkId] = useState("retail_discount_pricing");
  const [selectedVariant, setSelectedVariant] = useState("clean_v2");
  const [discoveryMode, setDiscoveryMode] = useState("CONTROLLED");
  const [preferredProvider, setPreferredProvider] = useState("auto");
  const [benchmarkValidation, setBenchmarkValidation] = useState(null);

  // Authoritative Active Certification Result
  const [activeResult, setActiveResult] = useState(null);
  const [activeCases, setActiveCases] = useState([]);
  const [caseFilter, setCaseFilter] = useState("ALL");
  const [expandedOracleId, setExpandedOracleId] = useState(null);
  const [cryptographicProof, setCryptographicProof] = useState(null);

  // Historical Viewing State
  const [historicalArtifacts, setHistoricalArtifacts] = useState([]);
  const [viewingHistoricalArtifact, setViewingHistoricalArtifact] = useState(null);

  // Continuous Drift State
  const [driftSamples, setDriftSamples] = useState([]);

  // Legacy Loan Demo Sandbox State (strictly isolated)
  const [loanRuns, setLoanRuns] = useState([]);
  const [selectedLoanRun, setSelectedLoanRun] = useState(null);
  const [loanInvariants, setLoanInvariants] = useState([]);
  const [loanDriftSamples, setLoanDriftSamples] = useState([]);

  // UI Feedback
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  // Load Benchmarks Metadata
  const loadBenchmarks = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/benchmarks`);
      if (res.ok) {
        const data = await res.json();
        setBenchmarks(data.benchmarks || []);
      }
    } catch {
      // Non-fatal
    }
  };

  // Load Historical Artifacts Filtered by Benchmark
  const loadHistoricalArtifacts = async (benchmarkId) => {
    try {
      const url = benchmarkId
        ? `${API_BASE}/api/v1/certification/artifacts?benchmark_id=${benchmarkId}`
        : `${API_BASE}/api/v1/certification/artifacts`;
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setHistoricalArtifacts(data.artifacts || []);
      }
    } catch {
      // Non-fatal
    }
  };

  // Load Drift Samples Filtered by Benchmark
  const loadDrift = async (benchmarkId) => {
    try {
      const url = benchmarkId ? `${API_BASE}/drift?benchmark_id=${benchmarkId}` : `${API_BASE}/drift`;
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setDriftSamples(data.samples || []);
      }
    } catch {
      // Non-fatal
    }
  };

  // Load Legacy Loan Demo State
  const loadLoanDemoData = async () => {
    try {
      const [runsRes, invRes, driftRes] = await Promise.all([
        fetch(`${API_BASE}/runs`),
        fetch(`${API_BASE}/demo/invariants`),
        fetch(`${API_BASE}/drift?benchmark_id=loan`),
      ]);
      if (runsRes.ok) {
        const d = await runsRes.json();
        setLoanRuns(d.runs || []);
        if (d.runs?.length > 0) setSelectedLoanRun(d.runs[0]);
      }
      if (invRes.ok) {
        const d = await invRes.json();
        setLoanInvariants(d.invariants || []);
      }
      if (driftRes.ok) {
        const d = await driftRes.json();
        setLoanDriftSamples(d.samples || []);
      }
    } catch {
      // Non-fatal
    }
  };

  // Initial Load
  useEffect(() => {
    Promise.all([loadBenchmarks(), loadHistoricalArtifacts(selectedBenchmarkId), loadDrift(selectedBenchmarkId)]).catch(() =>
      setError("Could not reach BEACON API backend. Start with: python -m uvicorn backend.api.main:app --reload")
    );
  }, []);

  // Invalidate Active Result and Reload Benchmark Data when Configuration Changes
  const handleBenchmarkChange = (newBenchmarkId) => {
    setSelectedBenchmarkId(newBenchmarkId);
    setActiveResult(null);
    setBenchmarkValidation(null);
    setCryptographicProof(null);
    setViewingHistoricalArtifact(null);
    setNotice(null);
    setError(null);

    const spec = benchmarks.find((b) => b.benchmark_id === newBenchmarkId);
    if (spec && spec.modernized_adapters) {
      setSelectedVariant(Object.keys(spec.modernized_adapters)[0] || "clean_v2");
    } else {
      setSelectedVariant("clean_v2");
    }

    loadHistoricalArtifacts(newBenchmarkId);
    loadDrift(newBenchmarkId);
  };

  const handleModeChange = (newMode) => {
    setDiscoveryMode(newMode);
    setActiveResult(null);
    setCryptographicProof(null);
    setViewingHistoricalArtifact(null);
    setNotice(null);
  };

  const handleVariantChange = (newVariant) => {
    setSelectedVariant(newVariant);
    setActiveResult(null);
    setCryptographicProof(null);
    setViewingHistoricalArtifact(null);
    setNotice(null);
  };

  // Load Cases when Active Result or Historical Artifact Changes
  const targetArtifact = viewingHistoricalArtifact || activeResult;
  useEffect(() => {
    if (targetArtifact?.certification_id) {
      fetch(`${API_BASE}/api/v1/certification/${targetArtifact.certification_id}/cases?classification=${caseFilter}`)
        .then((res) => res.json())
        .then((data) => setActiveCases(data.cases || []))
        .catch(console.error);
    } else {
      setActiveCases([]);
    }
  }, [targetArtifact, caseFilter]);

  // Step 6: Pre-Flight Validation Action
  const validateBenchmark = async () => {
    if (!selectedBenchmarkId) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/benchmarks/${selectedBenchmarkId}/validate`, {
        method: "POST",
      });
      const data = await res.json();
      setBenchmarkValidation(data);
      if (data.is_valid) {
        const cs = data.dataset_checksum ? ` (SHA-256: ${data.dataset_checksum.slice(0, 16)}...)` : "";
        setNotice(`Pre-flight validation passed: ${data.dataset_record_count} dataset inputs verified${cs}. Ready to certify.`);
      } else {
        setError(`Pre-flight validation failed: ${data.errors?.join("; ") || "Adapter or dataset mismatch."}`);
      }
    } catch (e) {
      setError(`Pre-flight validation request failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  // Step 7: Run Benchmark Equivalence Certification
  const runBenchmarkCertification = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    setCryptographicProof(null);
    setViewingHistoricalArtifact(null);

    try {
      const res = await fetch(`${API_BASE}/api/v1/certification/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          benchmark_id: selectedBenchmarkId,
          benchmark_variant: selectedVariant,
          discovery_mode: discoveryMode,
          preferred_provider: preferredProvider,
          use_llm: discoveryMode === "FULL_BEACON" && preferredProvider !== "offline",
          dataset_name: "default",
        }),
      });

      const artifact = await res.json();
      if (!res.ok) throw new Error(artifact.detail || "Certification run failed.");

      setActiveResult(artifact);
      await loadHistoricalArtifacts(selectedBenchmarkId);

      const isPass = artifact.status === "CERTIFIED" || artifact.status === "CERTIFIED_WITH_WARNINGS";
      if (isPass) {
        setNotice(`CERTIFIED: Equivalence established for ${selectedBenchmarkId} [${discoveryMode} • ${selectedVariant}].`);
      } else {
        setNotice(`NOT CERTIFIED: Behavioral regressions detected for ${selectedBenchmarkId} [${discoveryMode} • ${selectedVariant}].`);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // Cryptographic Verification Action (8-Point Integrity Check)
  const verifyArtifactIntegrity = async (certId) => {
    if (!certId) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/certification/${certId}/verify`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setCryptographicProof(data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Export Certification Dossier (JSON / Markdown / CSV)
  const exportDossier = (certId, format) => {
    if (!certId) return;
    window.open(`${API_BASE}/api/v1/certification/${certId}/export?format=${format}`, "_blank");
  };

  // Run Legacy Loan Demo (isolated)
  const runLoanDemo = async (implementation) => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/demo/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ implementation }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Demo run failed.");
      setSelectedLoanRun(data.run);
      await loadLoanDemoData();
      setNotice(
        implementation === "buggy"
          ? "Legacy Loan Demo: Buggy implementation evaluated — regression detected."
          : "Legacy Loan Demo: Equivalent implementation certified."
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // Active benchmark specification
  const currentSpec = benchmarks.find((b) => b.benchmark_id === selectedBenchmarkId) || benchmarks[0];

  return (
    <div style={{ minHeight: "100vh", background: "#f8fafc", color: "#1e293b", fontFamily: "'Inter', sans-serif" }}>
      {/* Top Header */}
      <header style={{ background: "#0f172a", color: "#f8fafc", padding: "16px 28px", borderBottom: "1px solid #1e293b" }}>
        <div style={{ maxWidth: "1440px", margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <span style={{ fontSize: "24px" }}>🛡️</span>
            <div>
              <h1 style={{ margin: 0, fontSize: "20px", fontWeight: "700", letterSpacing: "-0.5px" }}>BEACON</h1>
              <p style={{ margin: 0, fontSize: "12px", color: "#94a3b8" }}>
                Behavioral Equivalence Assurance & Cryptographic Oracle Notarization
              </p>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span style={badgeStyle("#1e293b", "#38bdf8", "#334155")}>Phase 13 Production-Grade</span>
            <span style={badgeStyle("#1e293b", "#a7f3d0", "#334155")}>Deterministic Reproducibility</span>
          </div>
        </div>
      </header>

      {/* Main Navigation Bar */}
      <nav style={{ background: "#ffffff", borderBottom: "1px solid #e2e8f0", padding: "0 28px" }}>
        <div style={{ maxWidth: "1440px", margin: "0 auto", display: "flex", gap: "24px" }}>
          {[
            { id: "benchmark", label: "🎯 Benchmark Certification", desc: "Select & Certify Applications" },
            { id: "history", label: "📜 Certification History", desc: "Benchmark Runs & Fingerprints" },
            { id: "audit", label: "🔒 Audit Trail & Proofs", desc: "Cryptographic Verification" },
            { id: "drift", label: "📈 Drift Monitoring", desc: "Post-Migration Live Drift" },
            { id: "loan_demo", label: "🧪 Legacy Loan Demo Sandbox", desc: "Isolated Demonstration" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => {
                setActiveTab(tab.id);
                if (tab.id === "loan_demo" && loanRuns.length === 0) loadLoanDemoData();
              }}
              style={{
                background: "transparent",
                border: "none",
                borderBottom: activeTab === tab.id ? "3px solid #2563eb" : "3px solid transparent",
                padding: "14px 4px",
                cursor: "pointer",
                fontWeight: activeTab === tab.id ? "700" : "500",
                color: activeTab === tab.id ? "#1e40af" : "#64748b",
                fontSize: "14px",
                display: "flex",
                alignItems: "center",
                gap: "6px",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </nav>

      {/* Main Container */}
      <main style={{ maxWidth: "1440px", margin: "24px auto", padding: "0 28px" }}>
        {/* Global Notifications */}
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

        {/* ========================================================================= */}
        {/* TAB 1: PRODUCTION-GRADE 9-STEP CERTIFICATION WORKFLOW                     */}
        {/* ========================================================================= */}
        {activeTab === "benchmark" && (
          <div>
            {/* Top Persistent Active Configuration Summary Bar */}
            <div style={{ background: "#ffffff", border: "1px solid #cbd5e1", borderRadius: "10px", padding: "12px 18px", marginBottom: "20px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "16px", fontSize: "13px" }}>
                <span><strong>Target:</strong> <span style={{ color: "#2563eb", fontWeight: "600" }}>{currentSpec?.name || selectedBenchmarkId}</span></span>
                <span>•</span>
                <span><strong>Mode:</strong> <span style={badgeStyle("#eff6ff", "#1e40af")}>{discoveryMode}</span></span>
                <span>•</span>
                <span><strong>Variant:</strong> <span style={{ fontWeight: "600" }}>{selectedVariant}</span></span>
                <span>•</span>
                <span><strong>Provider:</strong> <span style={{ color: "#475569" }}>{preferredProvider}</span></span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                {benchmarkValidation?.is_valid ? (
                  <span style={badgeStyle("#dcfce7", "#15803d", "#86efac")}>✅ Pre-Flight: Ready ({benchmarkValidation.dataset_record_count} cases)</span>
                ) : (
                  <span style={badgeStyle("#fef3c7", "#92400e", "#fde68a")}>⚠️ Pre-Flight: Validation Required</span>
                )}
              </div>
            </div>

            {/* Workflow Configuration Panel (Steps 1 - 7) */}
            <section style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #e2e8f0", paddingBottom: "14px", marginBottom: "18px" }}>
                <div>
                  <h2 style={{ margin: 0, fontSize: "18px", fontWeight: "700", color: "#0f172a" }}>
                    Production-Grade Certification Workflow
                  </h2>
                  <p style={{ margin: "2px 0 0", fontSize: "13px", color: "#64748b" }}>
                    Follow Steps 1 through 7 to configure target application, inspect dataset provenance, validate adapters, and execute certification.
                  </p>
                </div>
                <div style={{ display: "flex", gap: "10px" }}>
                  <button
                    onClick={validateBenchmark}
                    disabled={busy}
                    style={{
                      background: "#f1f5f9",
                      color: "#334155",
                      border: "1px solid #cbd5e1",
                      padding: "8px 16px",
                      borderRadius: "6px",
                      fontWeight: "600",
                      fontSize: "13px",
                      cursor: busy ? "not-allowed" : "pointer",
                    }}
                  >
                    {busy ? "Validating..." : "Step 6: 🔍 Pre-Flight Validate"}
                  </button>
                  <button
                    onClick={runBenchmarkCertification}
                    disabled={busy || !benchmarkValidation?.is_valid}
                    style={{
                      background: benchmarkValidation?.is_valid ? "#2563eb" : "#94a3b8",
                      color: "#ffffff",
                      border: "none",
                      padding: "8px 20px",
                      borderRadius: "6px",
                      fontWeight: "600",
                      fontSize: "13px",
                      cursor: busy || !benchmarkValidation?.is_valid ? "not-allowed" : "pointer",
                      boxShadow: benchmarkValidation?.is_valid ? "0 1px 2px rgba(37,99,235,0.2)" : "none",
                    }}
                  >
                    {busy ? "Executing Certification..." : "Step 7: ⚡ Run Equivalence Certification"}
                  </button>
                </div>
              </div>

              {/* Grid of Steps 1 to 5 Controls */}
              <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 1.2fr 1fr", gap: "14px" }}>
                {/* Step 1: Benchmark Selector */}
                <div>
                  <label style={{ display: "block", fontSize: "13px", fontWeight: "600", color: "#334155", marginBottom: "6px" }}>
                    Step 1 — Select Benchmark
                  </label>
                  <select
                    value={selectedBenchmarkId}
                    onChange={(e) => handleBenchmarkChange(e.target.value)}
                    style={{
                      width: "100%",
                      padding: "9px 12px",
                      borderRadius: "6px",
                      border: "1px solid #cbd5e1",
                      background: "#ffffff",
                      fontSize: "13px",
                      fontWeight: "500",
                    }}
                  >
                    {benchmarks.map((b) => (
                      <option key={b.benchmark_id} value={b.benchmark_id}>
                        {b.name} ({b.domain.toUpperCase()})
                      </option>
                    ))}
                  </select>
                </div>

                {/* Step 3: Evaluation Mode */}
                <div>
                  <label style={{ display: "block", fontSize: "13px", fontWeight: "600", color: "#334155", marginBottom: "6px" }}>
                    Step 3 — Evaluation Mode
                  </label>
                  <div style={{ display: "flex", gap: "6px" }}>
                    <button
                      onClick={() => handleModeChange("CONTROLLED")}
                      style={{
                        flex: 1,
                        padding: "8px 4px",
                        borderRadius: "6px",
                        fontSize: "11px",
                        fontWeight: "600",
                        cursor: "pointer",
                        border: discoveryMode === "CONTROLLED" ? "2px solid #2563eb" : "1px solid #cbd5e1",
                        background: discoveryMode === "CONTROLLED" ? "#eff6ff" : "#ffffff",
                        color: discoveryMode === "CONTROLLED" ? "#1e40af" : "#475569",
                      }}
                    >
                      CONTROLLED<br />
                      <span style={{ fontSize: "9px", fontWeight: "400", color: "#64748b" }}>Baseline Oracles</span>
                    </button>
                    <button
                      onClick={() => handleModeChange("FULL_BEACON")}
                      style={{
                        flex: 1,
                        padding: "8px 4px",
                        borderRadius: "6px",
                        fontSize: "11px",
                        fontWeight: "600",
                        cursor: "pointer",
                        border: discoveryMode === "FULL_BEACON" ? "2px solid #2563eb" : "1px solid #cbd5e1",
                        background: discoveryMode === "FULL_BEACON" ? "#eff6ff" : "#ffffff",
                        color: discoveryMode === "FULL_BEACON" ? "#1e40af" : "#475569",
                      }}
                    >
                      FULL_BEACON<br />
                      <span style={{ fontSize: "9px", fontWeight: "400", color: "#64748b" }}>Discovered Oracles</span>
                    </button>
                  </div>
                </div>

                {/* Step 4: Provider Hierarchy */}
                <div>
                  <label style={{ display: "block", fontSize: "13px", fontWeight: "600", color: "#334155", marginBottom: "6px" }}>
                    Step 4 — Provider Hierarchy
                  </label>
                  <select
                    value={preferredProvider}
                    onChange={(e) => setPreferredProvider(e.target.value)}
                    style={{
                      width: "100%",
                      padding: "9px 12px",
                      borderRadius: "6px",
                      border: "1px solid #cbd5e1",
                      background: "#ffffff",
                      fontSize: "13px",
                      fontWeight: "500",
                    }}
                  >
                    <option value="auto">Auto Fallback (OpenRouter &rarr; Anthropic &rarr; Ollama &rarr; Offline)</option>
                    <option value="openrouter">OpenRouter (Primary Cloud)</option>
                    <option value="anthropic">Anthropic (Claude Fallback)</option>
                    <option value="ollama">Ollama (Local Mistral/Qwen)</option>
                    <option value="offline">Deterministic Offline (No LLM)</option>
                  </select>
                </div>

                {/* Step 5: Modernization Variant */}
                <div>
                  <label style={{ display: "block", fontSize: "13px", fontWeight: "600", color: "#334155", marginBottom: "6px" }}>
                    Step 5 — Target Variant
                  </label>
                  <select
                    value={selectedVariant}
                    onChange={(e) => handleVariantChange(e.target.value)}
                    style={{
                      width: "100%",
                      padding: "9px 12px",
                      borderRadius: "6px",
                      border: "1px solid #cbd5e1",
                      background: "#ffffff",
                      fontSize: "13px",
                      fontWeight: "500",
                    }}
                  >
                    {currentSpec?.modernized_adapters ? (
                      Object.keys(currentSpec.modernized_adapters).map((varKey) => (
                        <option key={varKey} value={varKey}>
                          {varKey.includes("clean") ? "🟢 " : "🔴 "}
                          {varKey.replace("_v2", "").replace("_", " ").toUpperCase()} ({currentSpec.modernized_adapters[varKey]})
                        </option>
                      ))
                    ) : (
                      <option value="clean_v2">Clean Modernization</option>
                    )}
                  </select>
                </div>
              </div>

              {/* Step 2: Detailed Dataset & Provenance Inspection Card */}
              {currentSpec && (
                <div style={{ marginTop: "16px", background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "14px 18px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                      <span style={{ fontWeight: "700", fontSize: "13px", color: "#0f172a" }}>
                        Step 2 — Dataset Specifications & Provenance
                      </span>
                      <span style={badgeStyle("#dbeafe", "#1e40af", "#93c5fd")}>
                        {currentSpec.provenance_category || "REALISTIC_SYNTHETIC"}
                      </span>
                      <span style={badgeStyle("#f1f5f9", "#334155", "#cbd5e1")}>
                        License: {currentSpec.license || "Apache-2.0"}
                      </span>
                    </div>
                    {currentSpec.dataset_checksum && (
                      <div style={{ fontSize: "12px", color: "#475569", fontFamily: "monospace" }}>
                        Dataset SHA-256: <strong>{currentSpec.dataset_checksum.slice(0, 24)}...</strong>
                      </div>
                    )}
                  </div>
                  <p style={{ margin: "4px 0", fontSize: "12px", color: "#475569" }}>
                    <strong>Dataset Source:</strong> {currentSpec.dataset_source}
                  </p>
                  <div style={{ display: "flex", gap: "20px", fontSize: "12px", color: "#64748b", marginTop: "6px" }}>
                    <span>Language: <strong>{currentSpec.language}</strong></span>
                    <span>Domain: <strong>{currentSpec.domain}</strong></span>
                    <span>Dataset Version: <strong>{currentSpec.dataset_version}</strong></span>
                    {currentSpec.source_repository && (
                      <span>
                        Source Repo: <a href={currentSpec.source_repository} target="_blank" rel="noreferrer" style={{ color: "#2563eb" }}>{currentSpec.source_repository}</a>
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* Step 6 Pre-Flight Validation Banner */}
              {benchmarkValidation && (
                <div style={{ marginTop: "14px", padding: "12px 16px", borderRadius: "8px", background: benchmarkValidation.is_valid ? "#f0fdf4" : "#fef2f2", border: `1px solid ${benchmarkValidation.is_valid ? "#86efac" : "#fca5a5"}` }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: "13px", fontWeight: "600", color: benchmarkValidation.is_valid ? "#166534" : "#991b1b" }}>
                      {benchmarkValidation.is_valid ? "✅ Step 6: Pre-Flight Validation Passed" : "❌ Step 6: Pre-Flight Validation Failed"}
                    </span>
                    <span style={{ fontSize: "12px", color: "#475569" }}>
                      Verified Dataset Inputs: <strong>{benchmarkValidation.dataset_record_count}</strong> | Legacy Adapter: <strong>{benchmarkValidation.legacy_adapter_status || "OK"}</strong>
                    </span>
                  </div>
                  {benchmarkValidation.dataset_checksum && (
                    <div style={{ fontSize: "11px", color: "#166534", marginTop: "4px", fontFamily: "monospace" }}>
                      Propagated Checksum: {benchmarkValidation.dataset_checksum}
                    </div>
                  )}
                  {benchmarkValidation.errors?.length > 0 && (
                    <div style={{ fontSize: "12px", color: "#991b1b", marginTop: "4px" }}>
                      Errors: {benchmarkValidation.errors.join("; ")}
                    </div>
                  )}
                </div>
              )}
            </section>

            {/* Historical Viewing Notification */}
            {viewingHistoricalArtifact && (
              <div style={{ background: "#eff6ff", border: "1px solid #3b82f6", borderRadius: "8px", padding: "12px 18px", marginBottom: "20px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <span style={{ fontWeight: "700", color: "#1e40af", fontSize: "13px" }}>
                    📜 VIEWING HISTORICAL ARTIFACT: {viewingHistoricalArtifact.certification_id}
                  </span>
                  <p style={{ margin: "2px 0 0", fontSize: "12px", color: "#3b82f6" }}>
                    Benchmark: <strong>{viewingHistoricalArtifact.benchmark_id || viewingHistoricalArtifact.project_id}</strong> • Mode: <strong>{viewingHistoricalArtifact.evaluation_mode}</strong> • Variant: <strong>{viewingHistoricalArtifact.modernization_variant}</strong>
                  </p>
                </div>
                <button
                  onClick={() => setViewingHistoricalArtifact(null)}
                  style={{ background: "#2563eb", color: "#ffffff", border: "none", padding: "6px 12px", borderRadius: "4px", fontSize: "12px", cursor: "pointer" }}
                >
                  Return to Active Configuration
                </button>
              </div>
            )}

            {/* ========================================================================= */}
            {/* STEP 8: AUTHORITATIVE CERTIFICATION RESULT PRESENTATION                   */}
            {/* ========================================================================= */}
            {targetArtifact ? (
              <div>
                {/* 1. Authoritative Top Status Banner */}
                <div
                  style={{
                    background: statusBadgeStyles[targetArtifact.status]?.bg || "#f8fafc",
                    border: `1px solid ${statusBadgeStyles[targetArtifact.status]?.border || "#cbd5e1"}`,
                    color: statusBadgeStyles[targetArtifact.status]?.color || "#0f172a",
                    borderRadius: "12px",
                    padding: "20px 24px",
                    marginBottom: "20px",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "6px" }}>
                      <span style={{ fontSize: "20px", fontWeight: "800", letterSpacing: "-0.5px" }}>
                        Step 8 — Outcome: {targetArtifact.status === "CERTIFIED"
                          ? "CERTIFIED: Quantified Behavioral Equivalence Established"
                          : targetArtifact.status === "CERTIFIED_WITH_WARNINGS"
                          ? "CERTIFIED WITH WARNINGS: Non-Critical Discrepancies Permitted"
                          : targetArtifact.status === "INSUFFICIENT_COVERAGE"
                          ? "CERTIFICATION BLOCKED: Inadequate Oracle Coverage across Tested Input Domain"
                          : targetArtifact.status === "REFERENCE_INCONSISTENT"
                          ? "CERTIFICATION BLOCKED: Reference Inconsistency Detected in Legacy Implementation"
                          : "NOT CERTIFIED: Behavioral Regressions Detected Across Target Implementation"}
                      </span>
                      <span
                        style={badgeStyle(
                          statusBadgeStyles[targetArtifact.status]?.bg,
                          statusBadgeStyles[targetArtifact.status]?.color,
                          statusBadgeStyles[targetArtifact.status]?.border
                        )}
                      >
                        {targetArtifact.status}
                      </span>
                    </div>
                    <div style={{ fontSize: "13px", opacity: 0.9, display: "flex", gap: "16px" }}>
                      <span>Run ID: <strong>{targetArtifact.certification_id}</strong></span>
                      <span>Target: <strong>{targetArtifact.benchmark_id || targetArtifact.project_id}</strong></span>
                      <span>Mode: <strong>{targetArtifact.evaluation_mode || "CONTROLLED"}</strong></span>
                      <span>Variant: <strong>{targetArtifact.modernization_variant || "clean_v2"}</strong></span>
                    </div>
                  </div>

                  <div style={{ display: "flex", gap: "8px" }}>
                    <button
                      onClick={() => exportDossier(targetArtifact.certification_id, "json")}
                      style={{ background: "#ffffff", border: "1px solid #cbd5e1", color: "#0f172a", padding: "6px 12px", borderRadius: "6px", fontWeight: "600", fontSize: "12px", cursor: "pointer" }}
                    >
                      ⬇️ JSON Dossier
                    </button>
                    <button
                      onClick={() => exportDossier(targetArtifact.certification_id, "markdown")}
                      style={{ background: "#ffffff", border: "1px solid #cbd5e1", color: "#0f172a", padding: "6px 12px", borderRadius: "6px", fontWeight: "600", fontSize: "12px", cursor: "pointer" }}
                    >
                      ⬇️ Markdown Report
                    </button>
                    <button
                      onClick={() => exportDossier(targetArtifact.certification_id, "csv")}
                      style={{ background: "#ffffff", border: "1px solid #cbd5e1", color: "#0f172a", padding: "6px 12px", borderRadius: "6px", fontWeight: "600", fontSize: "12px", cursor: "pointer" }}
                    >
                      ⬇️ CSV Cases
                    </button>
                    <button
                      onClick={() => verifyArtifactIntegrity(targetArtifact.certification_id)}
                      style={{
                        background: "#2563eb",
                        border: "none",
                        color: "#ffffff",
                        padding: "6px 14px",
                        borderRadius: "6px",
                        fontWeight: "600",
                        fontSize: "12px",
                        cursor: "pointer",
                        boxShadow: "0 1px 2px rgba(37,99,235,0.2)",
                      }}
                    >
                      🔒 Verify Integrity
                    </button>
                  </div>
                </div>

                {/* Plain-Language Outcome Explanation */}
                <div style={{ ...cardStyle, background: targetArtifact.status === "CERTIFIED" ? "#f0fdf4" : (targetArtifact.status === "NOT_CERTIFIED" ? "#fef2f2" : "#f8fafc"), border: `1px solid ${targetArtifact.status === "CERTIFIED" ? "#86efac" : (targetArtifact.status === "NOT_CERTIFIED" ? "#fca5a5" : "#cbd5e1")}` }}>
                  <h4 style={{ margin: "0 0 6px 0", fontSize: "14px", fontWeight: "700", color: targetArtifact.status === "CERTIFIED" ? "#166534" : (targetArtifact.status === "NOT_CERTIFIED" ? "#991b1b" : "#334155") }}>
                    Plain-Language Certification Summary
                  </h4>
                  <p style={{ margin: 0, fontSize: "13px", color: targetArtifact.status === "CERTIFIED" ? "#14532d" : (targetArtifact.status === "NOT_CERTIFIED" ? "#7f1d1d" : "#475569"), lineHeight: "1.5" }}>
                    {targetArtifact.status === "CERTIFIED" && (
                      <>All <strong>{targetArtifact.metrics?.oracle_count || targetArtifact.oracle_summaries?.length || 0}</strong> evaluated behavioral invariants matched legacy behavior perfectly across all <strong>{targetArtifact.metrics?.unique_input_count || 0}</strong> canonical test inputs with zero regressions. Behavioral equivalence is certified under policy <code>{targetArtifact.certification_policy_id}</code>.</>
                    )}
                    {targetArtifact.status === "NOT_CERTIFIED" && (
                      <>Modernized implementation produced <strong>{targetArtifact.metrics?.regression_case_count || targetArtifact.regressions?.length || 0} behavioral regressions</strong> violating <strong>{targetArtifact.regressions?.length > 0 ? targetArtifact.regressions.map(r => r.oracle_id).filter((v, i, a) => a.indexOf(v) === i).join(", ") : "invariant rules"}</strong>. Exact counterexamples are pinpointed below.</>
                    )}
                    {targetArtifact.status === "INSUFFICIENT_COVERAGE" && (
                      <>Oracle coverage ({((targetArtifact.metrics?.oracle_coverage_pct || 0) * 100).toFixed(0)}%) or tested probe density did not satisfy the minimum policy threshold (80%). Certification cannot be established.</>
                    )}
                    {targetArtifact.status === "REFERENCE_INCONSISTENT" && (
                      <>Legacy reference implementation itself contradicted one or more validated invariant oracles. Equivalence certification is blocked.</>
                    )}
                  </p>
                </div>

                {/* 8-Point Cryptographic Proof Verification Result */}
                {cryptographicProof && (
                  <div style={{ background: cryptographicProof.status === "PASS" ? "#f0fdf4" : "#fef2f2", border: `1px solid ${cryptographicProof.status === "PASS" ? "#86efac" : "#fca5a5"}`, borderRadius: "8px", padding: "16px 20px", marginBottom: "20px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                      <span style={{ fontWeight: "700", color: cryptographicProof.status === "PASS" ? "#166534" : "#991b1b", fontSize: "14px" }}>
                        🛡️ 8-POINT CRYPTOGRAPHIC INTEGRITY REPORT: {cryptographicProof.status === "PASS" ? "ALL CHECKS PASSED (TAMPER-PROOF)" : "INTEGRITY VIOLATION DETECTED"}
                      </span>
                      <span style={badgeStyle(cryptographicProof.status === "PASS" ? "#dcfce7" : "#fee2e2", cryptographicProof.status === "PASS" ? "#15803d" : "#991b1b", cryptographicProof.status === "PASS" ? "#86efac" : "#fca5a5")}>
                        {cryptographicProof.status}
                      </span>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", fontSize: "12px" }}>
                      {cryptographicProof.checks && Object.entries(cryptographicProof.checks).map(([chkKey, chkVal]) => (
                        <div key={chkKey} style={{ display: "flex", alignItems: "center", gap: "6px", color: chkVal ? "#166534" : "#991b1b" }}>
                          <span>{chkVal ? "✅" : "❌"}</span>
                          <span style={{ fontWeight: "600" }}>{chkKey.replace(/_/g, " ").toUpperCase()}:</span>
                          <span>{chkVal ? "VALID" : "FAILED"}</span>
                        </div>
                      ))}
                    </div>

                    {cryptographicProof.errors?.length > 0 && (
                      <div style={{ marginTop: "10px", padding: "8px 12px", borderRadius: "6px", background: "#fee2e2", color: "#991b1b", fontSize: "12px" }}>
                        <strong>Integrity Errors:</strong> {cryptographicProof.errors.join("; ")}
                      </div>
                    )}
                  </div>
                )}

                {/* 2. Disambiguated Metric KPI Cards */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(8, 1fr)", gap: "10px", marginBottom: "20px" }}>
                  {[
                    { label: "Score", val: `${((targetArtifact.score || 0) * 100).toFixed(1)}%`, color: targetArtifact.score >= 0.8 ? "#059669" : "#dc2626" },
                    { label: "Coverage", val: `${((targetArtifact.metrics?.oracle_coverage_pct || 0) * 100).toFixed(0)}%`, color: "#0284c7" },
                    { label: "Unique Inputs", val: targetArtifact.metrics?.unique_input_count || targetArtifact.metrics?.total_inputs || 0, color: "#334155" },
                    { label: "Persisted Cases", val: targetArtifact.metrics?.certification_case_count || targetArtifact.metrics?.total_inputs || 0, color: "#334155" },
                    { label: "Oracles", val: targetArtifact.metrics?.oracle_count || targetArtifact.oracle_summaries?.length || 0, color: "#2563eb" },
                    { label: "Evaluations", val: targetArtifact.metrics?.oracle_evaluation_count || 0, color: "#475569" },
                    { label: "Matching Cases", val: targetArtifact.metrics?.matching_case_count || 0, color: "#059669" },
                    { label: "Regressions", val: targetArtifact.metrics?.regression_case_count || targetArtifact.metrics?.modern_regressions || 0, color: (targetArtifact.metrics?.regression_case_count || targetArtifact.metrics?.modern_regressions || 0) > 0 ? "#dc2626" : "#059669" },
                  ].map((m, i) => (
                    <div key={i} style={{ ...cardStyle, marginBottom: 0, padding: "12px 8px", textAlign: "center" }}>
                      <div style={{ fontSize: "10px", fontWeight: "600", color: "#64748b", textTransform: "uppercase", marginBottom: "2px" }}>
                        {m.label}
                      </div>
                      <div style={{ fontSize: "18px", fontWeight: "800", color: m.color }}>{m.val}</div>
                    </div>
                  ))}
                </div>

                {/* ========================================================================= */}
                {/* STEP 9: EVIDENCE INSPECTION AND DETAILED AUDIT DRILL-DOWN                 */}
                {/* ========================================================================= */}

                {/* Oracle Provenance & Discovery Pipeline Card */}
                <div style={cardStyle}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <span style={{ fontSize: "12px", fontWeight: "600", color: "#64748b", textTransform: "uppercase" }}>
                        Step 9 — Oracle Set Provenance & Discovery Pipeline
                      </span>
                      <div style={{ display: "flex", alignItems: "center", gap: "10px", marginTop: "4px" }}>
                        <span style={badgeStyle("#eff6ff", "#1e40af", "#bfdbfe")}>
                          Provenance: {targetArtifact.oracle_source_type || (targetArtifact.context?.oracle_source_type || "CONTROLLED_ORACLE_SET")}
                        </span>
                        <span style={{ fontSize: "12px", color: "#475569" }}>
                          Provider: <strong>{targetArtifact.context?.provider || targetArtifact.provider || "offline"}</strong>
                        </span>
                        <span style={{ fontSize: "12px", color: "#475569" }}>
                          Oracle Set ID: <strong>{targetArtifact.oracle_set_id}</strong>
                        </span>
                        <span style={{ fontSize: "12px", color: "#475569" }}>
                          Policy ID: <strong>{targetArtifact.certification_policy_id}</strong>
                        </span>
                      </div>
                    </div>
                    <div style={{ textAlign: "right", fontSize: "12px", color: "#64748b", fontFamily: "monospace" }}>
                      OracleSet Hash: {targetArtifact.oracle_set_hash?.slice(0, 16)}...
                    </div>
                  </div>
                </div>

                {/* Per-Oracle Verification Breakdown Table */}
                <div style={cardStyle}>
                  <h3 style={{ margin: "0 0 14px 0", fontSize: "16px", fontWeight: "700", color: "#0f172a" }}>
                    Per-Oracle Verification Breakdown ({targetArtifact.oracle_summaries?.length || 0} Evaluated Oracles)
                  </h3>
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                      <thead>
                        <tr style={{ background: "#f8fafc", borderBottom: "2px solid #e2e8f0", textAlign: "left" }}>
                          <th style={{ padding: "10px 12px" }}>Oracle ID</th>
                          <th style={{ padding: "10px 12px" }}>Behavioral Rule</th>
                          <th style={{ padding: "10px 12px" }}>Severity</th>
                          <th style={{ padding: "10px 12px" }}>Probes</th>
                          <th style={{ padding: "10px 12px" }}>Matching</th>
                          <th style={{ padding: "10px 12px" }}>Regressions</th>
                          <th style={{ padding: "10px 12px" }}>Match Rate</th>
                          <th style={{ padding: "10px 12px" }}>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {targetArtifact.oracle_summaries?.map((orc) => (
                          <tr
                            key={orc.oracle_id}
                            style={{ borderBottom: "1px solid #f1f5f9", cursor: "pointer", background: expandedOracleId === orc.oracle_id ? "#f8fafc" : "transparent" }}
                            onClick={() => setExpandedOracleId(expandedOracleId === orc.oracle_id ? null : orc.oracle_id)}
                          >
                            <td style={{ padding: "10px 12px", fontWeight: "600", color: "#2563eb", fontFamily: "monospace" }}>
                              {orc.oracle_id}
                            </td>
                            <td style={{ padding: "10px 12px", color: "#334155" }}>
                              <code>{orc.condition_str}</code> &rarr; <code>{orc.consequence_str}</code>
                            </td>
                            <td style={{ padding: "10px 12px" }}>
                              <span style={badgeStyle(orc.severity === "critical" ? "#fee2e2" : "#f1f5f9", orc.severity === "critical" ? "#991b1b" : "#475569")}>
                                {orc.severity}
                              </span>
                            </td>
                            <td style={{ padding: "10px 12px" }}>{orc.applicable_probes}</td>
                            <td style={{ padding: "10px 12px", color: "#059669", fontWeight: "600" }}>{orc.matching_probes}</td>
                            <td style={{ padding: "10px 12px", color: orc.modern_regressions > 0 ? "#dc2626" : "#475569", fontWeight: orc.modern_regressions > 0 ? "700" : "400" }}>
                              {orc.modern_regressions}
                            </td>
                            <td style={{ padding: "10px 12px", fontWeight: "600" }}>
                              {((orc.oracle_equivalence_rate || 0) * 100).toFixed(1)}%
                            </td>
                            <td style={{ padding: "10px 12px" }}>
                              <span style={badgeStyle(orc.oracle_status === "PASS" ? "#dcfce7" : "#fee2e2", orc.oracle_status === "PASS" ? "#166534" : "#991b1b")}>
                                {orc.oracle_status}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Concrete Counterexamples / Behavioral Regressions Explorer */}
                {targetArtifact.regressions?.length > 0 && (
                  <div style={cardStyle}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
                      <h3 style={{ margin: 0, fontSize: "16px", fontWeight: "700", color: "#991b1b" }}>
                        🚨 Concrete Behavioral Regressions & Counterexamples ({targetArtifact.regressions.length})
                      </h3>
                      <span style={{ fontSize: "12px", color: "#64748b" }}>First-Class Reproducible Evidence</span>
                    </div>
                    <div style={{ overflowX: "auto" }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                        <thead>
                          <tr style={{ background: "#fef2f2", borderBottom: "2px solid #fecaca", textAlign: "left" }}>
                            <th style={{ padding: "8px 10px" }}>Input ID</th>
                            <th style={{ padding: "8px 10px" }}>Input Hash</th>
                            <th style={{ padding: "8px 10px" }}>Input Values</th>
                            <th style={{ padding: "8px 10px" }}>Legacy Output</th>
                            <th style={{ padding: "8px 10px" }}>Modern Output</th>
                            <th style={{ padding: "8px 10px" }}>Violated Oracle</th>
                            <th style={{ padding: "8px 10px" }}>Severity</th>
                          </tr>
                        </thead>
                        <tbody>
                          {targetArtifact.regressions.map((reg, idx) => (
                            <tr key={idx} style={{ borderBottom: "1px solid #fee2e2" }}>
                              <td style={{ padding: "8px 10px", fontWeight: "600", fontFamily: "monospace" }}>{reg.input_id}</td>
                              <td style={{ padding: "8px 10px", color: "#64748b", fontFamily: "monospace" }}>{reg.input_hash ? reg.input_hash.slice(0, 16) + "..." : "—"}</td>
                              <td style={{ padding: "8px 10px", fontFamily: "monospace" }}>
                                {JSON.stringify(reg.input_values)}
                              </td>
                              <td style={{ padding: "8px 10px", color: "#059669", fontWeight: "600", fontFamily: "monospace" }}>
                                {JSON.stringify(reg.legacy_output)}
                              </td>
                              <td style={{ padding: "8px 10px", color: "#dc2626", fontWeight: "600", fontFamily: "monospace" }}>
                                {JSON.stringify(reg.modern_output)}
                              </td>
                              <td style={{ padding: "8px 10px", fontFamily: "monospace", color: "#2563eb" }}>{reg.oracle_id}</td>
                              <td style={{ padding: "8px 10px" }}>
                                <span style={badgeStyle("#fee2e2", "#991b1b")}>{reg.severity}</span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* Execution Case Explorer */}
                <div style={cardStyle}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
                    <h3 style={{ margin: 0, fontSize: "16px", fontWeight: "700", color: "#0f172a" }}>
                      Execution Case Explorer ({activeCases.length} Cases Loaded)
                    </h3>
                    <div style={{ display: "flex", gap: "6px" }}>
                      {["ALL", "MATCH", "MODERN_REGRESSION", "REFERENCE_INCONSISTENT"].map((cls) => (
                        <button
                          key={cls}
                          onClick={() => setCaseFilter(cls)}
                          style={{
                            padding: "4px 10px",
                            borderRadius: "4px",
                            fontSize: "11px",
                            fontWeight: "600",
                            cursor: "pointer",
                            border: caseFilter === cls ? "1px solid #2563eb" : "1px solid #cbd5e1",
                            background: caseFilter === cls ? "#eff6ff" : "#ffffff",
                            color: caseFilter === cls ? "#1e40af" : "#475569",
                          }}
                        >
                          {cls}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div style={{ maxHeight: "300px", overflowY: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                      <thead>
                        <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0", textAlign: "left" }}>
                          <th style={{ padding: "6px 8px" }}>Index</th>
                          <th style={{ padding: "6px 8px" }}>Input Values</th>
                          <th style={{ padding: "6px 8px" }}>Legacy Output</th>
                          <th style={{ padding: "6px 8px" }}>Modern Output</th>
                          <th style={{ padding: "6px 8px" }}>Classification</th>
                        </tr>
                      </thead>
                      <tbody>
                        {activeCases.map((c) => (
                          <tr key={c.case_id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                            <td style={{ padding: "6px 8px", color: "#64748b" }}>#{c.case_index}</td>
                            <td style={{ padding: "6px 8px", fontFamily: "monospace" }}>{c.input_json}</td>
                            <td style={{ padding: "6px 8px", fontFamily: "monospace", color: "#059669" }}>{c.legacy_output_json}</td>
                            <td style={{ padding: "6px 8px", fontFamily: "monospace", color: c.classification === "MATCH" ? "#059669" : "#dc2626" }}>
                              {c.modern_output_json}
                            </td>
                            <td style={{ padding: "6px 8px" }}>
                              <span style={badgeStyle(c.classification === "MATCH" ? "#dcfce7" : "#fee2e2", c.classification === "MATCH" ? "#166534" : "#991b1b")}>
                                {c.classification}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Cryptographic Audit Fingerprints & Hashes */}
                <div style={cardStyle}>
                  <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                    Cryptographic Audit Fingerprints & Hashes
                  </h3>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", fontSize: "12px", fontFamily: "monospace" }}>
                    <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <span style={{ color: "#64748b" }}>Legacy Implementation SHA-256:</span>
                      <div style={{ color: "#0f172a", marginTop: "2px", wordBreak: "break-all" }}>{targetArtifact.legacy_implementation_hash || targetArtifact.context?.legacy_implementation_hash || "—"}</div>
                    </div>
                    <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <span style={{ color: "#64748b" }}>Modern Implementation SHA-256:</span>
                      <div style={{ color: "#0f172a", marginTop: "2px", wordBreak: "break-all" }}>{targetArtifact.modernized_implementation_hash || targetArtifact.context?.modernized_implementation_hash || "—"}</div>
                    </div>
                    <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <span style={{ color: "#64748b" }}>Dataset Checksum (SHA-256):</span>
                      <div style={{ color: "#0f172a", marginTop: "2px", wordBreak: "break-all" }}>{targetArtifact.dataset_checksum || targetArtifact.context?.dataset_checksum || "—"}</div>
                    </div>
                    <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <span style={{ color: "#64748b" }}>Input-Set Hash (SHA-256):</span>
                      <div style={{ color: "#0f172a", marginTop: "2px", wordBreak: "break-all" }}>{targetArtifact.input_set_hash || "—"}</div>
                    </div>
                    <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <span style={{ color: "#64748b" }}>Oracle-Set Hash (SHA-256):</span>
                      <div style={{ color: "#0f172a", marginTop: "2px", wordBreak: "break-all" }}>{targetArtifact.oracle_set_hash || "—"}</div>
                    </div>
                    <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <span style={{ color: "#64748b" }}>Policy Hash (SHA-256):</span>
                      <div style={{ color: "#0f172a", marginTop: "2px", wordBreak: "break-all" }}>{targetArtifact.certification_policy_hash || "—"}</div>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              /* Ready / Empty State Prompt to Validate & Execute */
              <div style={{ ...cardStyle, textAlign: "center", padding: "48px 24px" }}>
                <span style={{ fontSize: "40px" }}>🎯</span>
                <h3 style={{ margin: "12px 0 6px", fontSize: "18px", fontWeight: "700", color: "#0f172a" }}>
                  Ready to Certify: {currentSpec?.name || selectedBenchmarkId}
                </h3>
                <p style={{ margin: "0 auto 20px", maxWidth: "600px", fontSize: "14px", color: "#64748b" }}>
                  Selected Configuration: <strong>{discoveryMode}</strong> mode with <strong>{selectedVariant}</strong>.
                  Run Step 6 Pre-Flight Validation to verify dataset inputs and adapter bindings before executing certification.
                </p>
                <div style={{ display: "flex", justifyContent: "center", gap: "12px" }}>
                  <button
                    onClick={validateBenchmark}
                    disabled={busy}
                    style={{
                      background: "#f1f5f9",
                      color: "#334155",
                      border: "1px solid #cbd5e1",
                      padding: "10px 20px",
                      borderRadius: "6px",
                      fontWeight: "600",
                      fontSize: "14px",
                      cursor: "pointer",
                    }}
                  >
                    Step 6: 🔍 Pre-Flight Validate
                  </button>
                  <button
                    onClick={runBenchmarkCertification}
                    disabled={busy || !benchmarkValidation?.is_valid}
                    style={{
                      background: benchmarkValidation?.is_valid ? "#2563eb" : "#94a3b8",
                      color: "#ffffff",
                      border: "none",
                      padding: "10px 24px",
                      borderRadius: "6px",
                      fontWeight: "600",
                      fontSize: "14px",
                      cursor: busy || !benchmarkValidation?.is_valid ? "not-allowed" : "pointer",
                    }}
                  >
                    {busy ? "Executing Certification..." : "Step 7: ⚡ Run Equivalence Certification"}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 2: CERTIFICATION HISTORY (BENCHMARK FILTERED)                          */}
        {/* ========================================================================= */}
        {activeTab === "history" && (
          <div>
            <div style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                <div>
                  <h2 style={{ margin: 0, fontSize: "18px", fontWeight: "700", color: "#0f172a" }}>
                    Certification Run History
                  </h2>
                  <p style={{ margin: "2px 0 0", fontSize: "13px", color: "#64748b" }}>
                    Filtered for Benchmark: <strong>{selectedBenchmarkId}</strong>
                  </p>
                </div>
                <button
                  onClick={() => loadHistoricalArtifacts(selectedBenchmarkId)}
                  style={{ background: "#f1f5f9", border: "1px solid #cbd5e1", padding: "6px 12px", borderRadius: "6px", fontSize: "12px", cursor: "pointer" }}
                >
                  🔄 Refresh History
                </button>
              </div>

              {historicalArtifacts.length === 0 ? (
                <div style={{ textAlign: "center", padding: "32px", color: "#64748b" }}>
                  No historical runs recorded for <strong>{selectedBenchmarkId}</strong> yet.
                </div>
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                    <thead>
                      <tr style={{ background: "#f8fafc", borderBottom: "2px solid #e2e8f0", textAlign: "left" }}>
                        <th style={{ padding: "10px 12px" }}>Run / Artifact ID</th>
                        <th style={{ padding: "10px 12px" }}>Timestamp</th>
                        <th style={{ padding: "10px 12px" }}>Mode</th>
                        <th style={{ padding: "10px 12px" }}>Variant</th>
                        <th style={{ padding: "10px 12px" }}>Equivalence Score</th>
                        <th style={{ padding: "10px 12px" }}>Status</th>
                        <th style={{ padding: "10px 12px" }}>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {historicalArtifacts.map((art) => (
                        <tr key={art.certification_id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "10px 12px", fontFamily: "monospace", fontWeight: "600", color: "#2563eb" }}>
                            {art.certification_id}
                          </td>
                          <td style={{ padding: "10px 12px", color: "#64748b" }}>{art.timestamp ? new Date(art.timestamp).toLocaleString() : "—"}</td>
                          <td style={{ padding: "10px 12px" }}>
                            <span style={badgeStyle("#eff6ff", "#1e40af")}>{art.evaluation_mode || "CONTROLLED"}</span>
                          </td>
                          <td style={{ padding: "10px 12px", color: "#334155" }}>{art.modernization_variant || "clean_v2"}</td>
                          <td style={{ padding: "10px 12px", fontWeight: "700", color: (art.score || 0) >= 0.8 ? "#059669" : "#dc2626" }}>
                            {((art.score || 0) * 100).toFixed(1)}%
                          </td>
                          <td style={{ padding: "10px 12px" }}>
                            <span style={badgeStyle(statusBadgeStyles[art.status]?.bg, statusBadgeStyles[art.status]?.color, statusBadgeStyles[art.status]?.border)}>
                              {art.status}
                            </span>
                          </td>
                          <td style={{ padding: "10px 12px" }}>
                            <button
                              onClick={() => {
                                setViewingHistoricalArtifact(art);
                                setActiveTab("benchmark");
                              }}
                              style={{ background: "#f1f5f9", border: "1px solid #cbd5e1", padding: "4px 10px", borderRadius: "4px", fontSize: "12px", cursor: "pointer", fontWeight: "600" }}
                            >
                              Inspect Run
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 3: AUDIT TRAIL & VERIFICATION                                         */}
        {/* ========================================================================= */}
        {activeTab === "audit" && (
          <div>
            <div style={cardStyle}>
              <h2 style={{ margin: "0 0 8px 0", fontSize: "18px", fontWeight: "700", color: "#0f172a" }}>
                Immutable Audit Trail & Cryptographic Verification
              </h2>
              <p style={{ margin: "0 0 20px 0", fontSize: "13px", color: "#64748b" }}>
                Verify content-addressable SHA-256 hashes for any historical certification artifact and its complete evaluated input suite.
              </p>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px" }}>
                <div>
                  <h3 style={{ fontSize: "14px", fontWeight: "600", color: "#334155", marginBottom: "10px" }}>
                    Select Artifact to Verify
                  </h3>
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px", maxHeight: "400px", overflowY: "auto" }}>
                    {historicalArtifacts.map((art) => (
                      <div
                        key={art.certification_id}
                        onClick={() => verifyArtifactIntegrity(art.certification_id)}
                        style={{
                          padding: "12px 14px",
                          borderRadius: "8px",
                          border: "1px solid #e2e8f0",
                          background: "#ffffff",
                          cursor: "pointer",
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                        }}
                      >
                        <div>
                          <div style={{ fontFamily: "monospace", fontWeight: "600", color: "#2563eb", fontSize: "13px" }}>
                            {art.certification_id}
                          </div>
                          <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                            {art.benchmark_id || art.project_id} • {art.evaluation_mode} • {art.modernization_variant}
                          </div>
                        </div>
                        <span style={badgeStyle(statusBadgeStyles[art.status]?.bg, statusBadgeStyles[art.status]?.color)}>
                          {art.status}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <h3 style={{ fontSize: "14px", fontWeight: "600", color: "#334155", marginBottom: "10px" }}>
                    Cryptographic Proof & Content Digest
                  </h3>
                  {cryptographicProof ? (
                    <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
                        <span style={{ fontSize: "18px" }}>🛡️</span>
                        <span style={{ fontWeight: "700", fontSize: "14px", color: cryptographicProof.status === "PASS" ? "#166534" : "#991b1b" }}>
                          Verification Result: {cryptographicProof.status}
                        </span>
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: "10px", fontSize: "12px", fontFamily: "monospace" }}>
                        <div>
                          <span style={{ color: "#64748b" }}>Artifact ID:</span>
                          <div style={{ color: "#0f172a" }}>{cryptographicProof.certification_id}</div>
                        </div>
                        <div>
                          <span style={{ color: "#64748b" }}>Artifact Integrity:</span>
                          <div style={{ color: cryptographicProof.artifact_integrity_valid ? "#166534" : "#991b1b", fontWeight: "600" }}>
                            {cryptographicProof.artifact_integrity_valid ? "VALID (SHA-256 Confirmed)" : "FAIL"}
                          </div>
                        </div>
                        <div>
                          <span style={{ color: "#64748b" }}>Input Set Integrity:</span>
                          <div style={{ color: cryptographicProof.input_set_integrity_valid ? "#166534" : "#991b1b", fontWeight: "600" }}>
                            {cryptographicProof.input_set_integrity_valid ? "VALID (Canonical Inputs Match)" : "FAIL"}
                          </div>
                        </div>
                        <div>
                          <span style={{ color: "#64748b" }}>Content Hash:</span>
                          <div style={{ color: "#0f172a", wordBreak: "break-all" }}>{cryptographicProof.content_hash}</div>
                        </div>
                        <div>
                          <span style={{ color: "#64748b" }}>Input Set Hash:</span>
                          <div style={{ color: "#0f172a", wordBreak: "break-all" }}>{cryptographicProof.input_set_hash}</div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div style={{ padding: "32px", textAlign: "center", background: "#f8fafc", borderRadius: "8px", border: "1px dashed #cbd5e1", color: "#64748b", fontSize: "13px" }}>
                      Select an artifact from the list to inspect cryptographic hashes.
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 4: CONTINUOUS DRIFT MONITORING (BENCHMARK SPECIFIC)                   */}
        {/* ========================================================================= */}
        {activeTab === "drift" && (
          <div>
            <div style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                <div>
                  <h2 style={{ margin: 0, fontSize: "18px", fontWeight: "700", color: "#0f172a" }}>
                    Continuous Behavioral Drift Monitoring
                  </h2>
                  <p style={{ margin: "2px 0 0", fontSize: "13px", color: "#64748b" }}>
                    Runtime evaluation of post-migration production observations against frozen validated oracles.
                  </p>
                </div>
                <button
                  onClick={() => loadDrift(selectedBenchmarkId)}
                  style={{ background: "#f1f5f9", border: "1px solid #cbd5e1", padding: "6px 12px", borderRadius: "6px", fontSize: "12px", cursor: "pointer" }}
                >
                  🔄 Refresh Drift
                </button>
              </div>

              {driftSamples.length === 0 ? (
                <div style={{ padding: "40px 20px", textAlign: "center", background: "#f8fafc", borderRadius: "8px", border: "1px dashed #cbd5e1" }}>
                  <span style={{ fontSize: "32px" }}>📊</span>
                  <h3 style={{ margin: "10px 0 4px", fontSize: "15px", fontWeight: "600", color: "#334155" }}>
                    No Drift Observations Recorded for {selectedBenchmarkId}
                  </h3>
                  <p style={{ margin: 0, fontSize: "13px", color: "#64748b" }}>
                    Post-migration runtime observations for this benchmark will be logged here and tracked for regressions.
                  </p>
                </div>
              ) : (
                <div>
                  <div style={{ height: "240px", marginBottom: "20px" }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={driftSamples.slice().reverse()}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                        <XAxis dataKey="run_timestamp" tick={{ fontSize: 10 }} />
                        <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} />
                        <Tooltip />
                        <Line type="monotone" dataKey="equivalence_score" stroke="#2563eb" strokeWidth={2} name="Equivalence Score" />
                        <Line type="monotone" dataKey="baseline_score" stroke="#10b981" strokeDasharray="4 4" name="Baseline Score" />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>

                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                    <thead>
                      <tr style={{ background: "#f8fafc", borderBottom: "2px solid #e2e8f0", textAlign: "left" }}>
                        <th style={{ padding: "8px 10px" }}>Timestamp</th>
                        <th style={{ padding: "8px 10px" }}>Score</th>
                        <th style={{ padding: "8px 10px" }}>Baseline</th>
                        <th style={{ padding: "8px 10px" }}>Delta</th>
                        <th style={{ padding: "8px 10px" }}>Alert</th>
                      </tr>
                    </thead>
                    <tbody>
                      {driftSamples.map((s, idx) => (
                        <tr key={idx} style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "8px 10px", color: "#64748b" }}>{s.run_timestamp}</td>
                          <td style={{ padding: "8px 10px", fontWeight: "600" }}>{((s.equivalence_score || 0) * 100).toFixed(1)}%</td>
                          <td style={{ padding: "8px 10px" }}>{((s.baseline_score || 0) * 100).toFixed(1)}%</td>
                          <td style={{ padding: "8px 10px", color: s.delta_pct > 0 ? "#dc2626" : "#059669" }}>
                            {s.delta_pct > 0 ? `+${s.delta_pct}%` : `${s.delta_pct}%`}
                          </td>
                          <td style={{ padding: "8px 10px" }}>
                            <span style={badgeStyle(s.alert ? "#fee2e2" : "#dcfce7", s.alert ? "#991b1b" : "#166534")}>
                              {s.alert ? "DRIFT ALERT" : "STABLE"}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 5: LEGACY LOAN DEMO SANDBOX (ISOLATED)                                */}
        {/* ========================================================================= */}
        {activeTab === "loan_demo" && (
          <div>
            <div style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #e2e8f0", paddingBottom: "14px", marginBottom: "16px" }}>
                <div>
                  <h2 style={{ margin: 0, fontSize: "18px", fontWeight: "700", color: "#0f172a" }}>
                    🧪 Legacy Loan Approval Demo Sandbox
                  </h2>
                  <p style={{ margin: "2px 0 0", fontSize: "13px", color: "#64748b" }}>
                    Phase 1–9 baseline loan approval demonstration. Kept isolated from multi-benchmark certification.
                  </p>
                </div>
                <div style={{ display: "flex", gap: "10px" }}>
                  <button
                    onClick={() => runLoanDemo("equivalent")}
                    disabled={busy}
                    style={{ background: "#059669", color: "#ffffff", border: "none", padding: "8px 14px", borderRadius: "6px", fontWeight: "600", fontSize: "13px", cursor: "pointer" }}
                  >
                    Run Equivalent Demo
                  </button>
                  <button
                    onClick={() => runLoanDemo("buggy")}
                    disabled={busy}
                    style={{ background: "#dc2626", color: "#ffffff", border: "none", padding: "8px 14px", borderRadius: "6px", fontWeight: "600", fontSize: "13px", cursor: "pointer" }}
                  >
                    Run Buggy Demo
                  </button>
                </div>
              </div>

              {/* Invariants and Results */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "18px" }}>
                <div>
                  <h3 style={{ fontSize: "14px", fontWeight: "600", color: "#334155", marginBottom: "8px" }}>
                    Loan Demo Invariants ({loanInvariants.length})
                  </h3>
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    {loanInvariants.map((inv) => (
                      <div key={inv.invariant_id} style={{ padding: "10px 12px", background: "#f8fafc", borderRadius: "6px", border: "1px solid #e2e8f0", fontSize: "12px" }}>
                        <div style={{ fontWeight: "600", color: "#2563eb", fontFamily: "monospace" }}>{inv.invariant_id}</div>
                        <div style={{ color: "#334155", marginTop: "2px" }}>
                          <code>{inv.canonical_condition || inv.condition}</code> &rarr; <code>{JSON.stringify(inv.consequence)}</code>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <h3 style={{ fontSize: "14px", fontWeight: "600", color: "#334155", marginBottom: "8px" }}>
                    Latest Loan Run Outcome
                  </h3>
                  {selectedLoanRun ? (
                    <div style={{ background: "#f8fafc", borderRadius: "8px", border: "1px solid #e2e8f0", padding: "16px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                        <span style={{ fontWeight: "700", fontSize: "14px", color: "#0f172a" }}>
                          Run #{selectedLoanRun.id}
                        </span>
                        <span style={badgeStyle((selectedLoanRun.equivalence_score || 0) >= 0.8 ? "#dcfce7" : "#fee2e2", (selectedLoanRun.equivalence_score || 0) >= 0.8 ? "#166534" : "#991b1b")}>
                          Score: {((selectedLoanRun.equivalence_score || 0) * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div style={{ fontSize: "12px", color: "#475569", display: "flex", flexDirection: "column", gap: "4px" }}>
                        <div>Total Checked: <strong>{selectedLoanRun.total_checked}</strong></div>
                        <div>Total Violated: <strong>{selectedLoanRun.total_violated}</strong></div>
                        <div>Implementation: <strong>{selectedLoanRun.implementation}</strong></div>
                        <div>Timestamp: <strong>{selectedLoanRun.timestamp}</strong></div>
                      </div>
                    </div>
                  ) : (
                    <div style={{ padding: "24px", textAlign: "center", color: "#64748b", fontSize: "13px" }}>
                      Click one of the buttons above to run the demo.
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
