import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

const API_BASE = "http://localhost:8000";

const card = {
  background: "white",
  border: "1px solid #e5e7eb",
  borderRadius: 12,
  padding: 20,
  boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
};

const statusStyles = {
  CERTIFIED: { bg: "#ecfdf5", border: "#10b981", color: "#065f46", text: "CERTIFIED" },
  CERTIFIED_WITH_WARNINGS: { bg: "#fffbeb", border: "#f59e0b", color: "#92400e", text: "CERTIFIED WITH WARNINGS" },
  NOT_CERTIFIED: { bg: "#fef2f2", border: "#ef4444", color: "#991b1b", text: "NOT CERTIFIED" },
  REFERENCE_INCONSISTENT: { bg: "#f5f3ff", border: "#8b5cf6", color: "#5b21b6", text: "REFERENCE INCONSISTENT" },
  INSUFFICIENT_COVERAGE: { bg: "#fff7ed", border: "#f97316", color: "#9a3412", text: "INSUFFICIENT COVERAGE" },
  ORACLE_SET_INVALID: { bg: "#fef2f2", border: "#dc2626", color: "#7f1d1d", text: "ORACLE SET INVALID" },
};

export default function App() {
  const [runs, setRuns] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [invariants, setInvariants] = useState([]);
  const [driftSamples, setDriftSamples] = useState([]);
  const [artifacts, setArtifacts] = useState([]);
  const [selectedArtifact, setSelectedArtifact] = useState(null);
  const [expandedOracleId, setExpandedOracleId] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const [artifactCases, setArtifactCases] = useState([]);
  const [caseFilter, setCaseFilter] = useState("ALL");

  useEffect(() => {
    if (selectedArtifact) {
      fetch(`${API_BASE}/api/v1/certification/${selectedArtifact.certification_id}/cases?classification=${caseFilter}`)
        .then(res => res.json())
        .then(data => setArtifactCases(data.cases || []))
        .catch(console.error);
    } else {
      setArtifactCases([]);
    }
  }, [selectedArtifact, caseFilter]);

  const loadRuns = async () => {
    const response = await fetch(`${API_BASE}/runs`);
    if (!response.ok) throw new Error("Could not load certification history.");
    const data = await response.json();
    setRuns(data.runs || []);
    setSelectedRun((current) => current || data.runs?.[0] || null);
  };

  const loadInvariants = async () => {
    const response = await fetch(`${API_BASE}/demo/invariants`);
    if (!response.ok) throw new Error("Could not load the sample invariants.");
    const data = await response.json();
    setInvariants(data.invariants || []);
  };

  const loadDrift = async () => {
    const response = await fetch(`${API_BASE}/drift`);
    if (!response.ok) throw new Error("Could not load drift history.");
    const data = await response.json();
    setDriftSamples(data.samples || []);
  };

  const loadArtifacts = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/certification/artifacts`);
      if (response.ok) {
        const data = await response.json();
        setArtifacts(data.artifacts || []);
        if (data.artifacts?.length > 0) {
          setSelectedArtifact(data.artifacts[0]);
        }
      }
    } catch {
      // Non-fatal
    }
  };

  const [benchmarks, setBenchmarks] = useState([]);
  const [selectedBenchmarkId, setSelectedBenchmarkId] = useState("retail_discount_pricing");
  const [selectedVariant, setSelectedVariant] = useState("clean_v2");
  const [discoveryMode, setDiscoveryMode] = useState("CONTROLLED");
  const [benchmarkValidation, setBenchmarkValidation] = useState(null);

  const loadBenchmarks = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/benchmarks`);
      if (response.ok) {
        const data = await response.json();
        setBenchmarks(data.benchmarks || []);
      }
    } catch {
      // Non-fatal
    }
  };

  useEffect(() => {
    Promise.all([loadRuns(), loadInvariants(), loadDrift(), loadArtifacts(), loadBenchmarks()]).catch(() =>
      setError("Could not reach the BEACON API. Start it with: python -m uvicorn backend.api.main:app --reload --port 8000")
    );
  }, []);

  const runCertification = async (implementation) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch(`${API_BASE}/demo/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ implementation }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Certification failed.");
      setInvariants(data.invariants || []);
      setSelectedRun(data.run);
      await loadRuns();
      await loadArtifacts();
      setNotice(
        implementation === "buggy"
          ? "Buggy modernization certified: BEACON detected the behavioral regression."
          : "Equivalent implementation certified: all validated oracles passed."
      );
    } catch (runError) {
      setError(runError.message);
    } finally {
      setBusy(false);
    }
  };

  const validateCurrentBenchmark = async () => {
    if (!selectedBenchmarkId) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch(`${API_BASE}/api/v1/benchmarks/${selectedBenchmarkId}/validate`, {
        method: "POST",
      });
      const data = await response.json();
      setBenchmarkValidation(data);
      if (data.is_valid) {
        const cs = data.dataset_checksum ? ` (SHA-256: ${data.dataset_checksum.slice(0, 12)}...)` : "";
        setNotice(`Benchmark '${selectedBenchmarkId}' validation passed: ${data.dataset_record_count} dataset inputs verified${cs}.`);
      } else {
        setError(`Benchmark validation issues: ${data.errors.join(", ")}`);
      }
    } catch (valError) {
      setError(valError.message);
    } finally {
      setBusy(false);
    }
  };

  const runBenchmarkCertification = async () => {
    if (!selectedBenchmarkId) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch(`${API_BASE}/api/v1/certification/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          benchmark_id: selectedBenchmarkId,
          benchmark_variant: selectedVariant,
          discovery_mode: discoveryMode,
          n_samples: 60,
        }),
      });
      const artifact = await response.json();
      if (!response.ok) throw new Error(artifact.detail || "Benchmark certification failed.");
      setSelectedArtifact(artifact);
      await loadArtifacts();
      setNotice(
        artifact.certified
          ? `Benchmark [${discoveryMode}] certified: ${artifact.metrics.matching_probes}/${artifact.metrics.total_inputs} inputs matched with 100% equivalence.`
          : `Benchmark [${discoveryMode}] certification failed as expected: ${artifact.metrics.modern_regressions} regression(s) detected.`
      );
    } catch (benchError) {
      setError(benchError.message);
    } finally {
      setBusy(false);
    }
  };

  const runDriftCheck = async () => {
    if (!selectedRun) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/drift/demo`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ baseline_run_id: selectedRun.run_id, implementation: "buggy" }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Drift check failed.");
      await loadDrift();
      setNotice(
        data.alert
          ? `Drift alert: score fell ${data.delta_pct.toFixed(1)} points below the selected baseline.`
          : "No material drift detected against the selected baseline."
      );
    } catch (driftError) {
      setError(driftError.message);
    } finally {
      setBusy(false);
    }
  };

  const currentBenchmark = benchmarks.find((b) => b.benchmark_id === selectedBenchmarkId) || benchmarks[0];
  const chartData = [...runs].reverse().map((run) => ({
    run: run.run_id,
    score: Math.round(run.equivalence_score * 100),
  }));

  const currentStatusStyle = selectedArtifact
    ? statusStyles[selectedArtifact.status] || statusStyles.NOT_CERTIFIED
    : selectedRun?.equivalence_score >= 0.8 && selectedRun?.total_violated === 0
    ? statusStyles.CERTIFIED
    : statusStyles.NOT_CERTIFIED;

  const provenanceBadgeColor = {
    PUBLIC: { bg: "#e0e7ff", color: "#3730a3", text: "PUBLIC DOMAIN" },
    REALISTIC: { bg: "#ecfdf5", color: "#065f46", text: "REALISTIC ENTERPRISE" },
    REAL_EXTERNAL: { bg: "#fef3c7", color: "#92400e", text: "EXTERNAL OPEN SOURCE" },
    CONTROLLED: { bg: "#f1f5f9", color: "#475569", text: "CONTROLLED DEMO" },
  };

  return (
    <main style={{ fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", color: "#1e293b", background: "#f8fafc", minHeight: "100vh", padding: "32px 16px" }}>
      <div style={{ maxWidth: 1080, margin: "0 auto" }}>
        {/* Header */}
        <header style={{ marginBottom: 24, display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
          <div>
            <p style={{ color: "#0f766e", fontWeight: 700, margin: 0, letterSpacing: 1.2, fontSize: 13 }}>
              BEACON &bull; BEHAVIORAL EQUIVALENCE &amp; CERTIFICATION
            </p>
            <h1 style={{ margin: "6px 0 0", fontSize: 28, color: "#0f172a" }}>Behavioral Equivalence Governance</h1>
            <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: 14 }}>
              Deterministic Oracle Verification, Quantified Certification &amp; Post-Migration Drift Monitoring
            </p>
          </div>
          {selectedArtifact && (
            <div style={{ padding: "8px 18px", borderRadius: 20, background: currentStatusStyle.bg, border: `2px solid ${currentStatusStyle.border}`, color: currentStatusStyle.color, fontWeight: 700, fontSize: 14 }}>
              {currentStatusStyle.text}
            </div>
          )}
        </header>

        {error && <p style={{ ...card, color: "#b42318", borderColor: "#fecdca" }}>{error}</p>}
        {notice && <p style={{ ...card, color: "#067647", borderColor: "#a6f4c5" }}>{notice}</p>}

        {/* Phase 12 Benchmark Catalog & Selection */}
        <section style={{ ...card, marginBottom: 18, borderLeft: "4px solid #0f766e" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12 }}>
            <div>
              <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1, color: "#0f766e", textTransform: "uppercase" }}>Phase 12 Real-World Benchmark Integration</span>
              <h2 style={{ margin: "4px 0 6px", fontSize: 18 }}>Select Evaluation Benchmark &amp; Inspect Provenance</h2>
            </div>
            {currentBenchmark && (
              <span
                style={{
                  padding: "4px 10px",
                  borderRadius: 12,
                  fontSize: 11,
                  fontWeight: 700,
                  background: provenanceBadgeColor[currentBenchmark.provenance_category]?.bg || "#f1f5f9",
                  color: provenanceBadgeColor[currentBenchmark.provenance_category]?.color || "#334155",
                  border: "1px solid rgba(0,0,0,0.05)"
                }}
              >
                {provenanceBadgeColor[currentBenchmark.provenance_category]?.text || currentBenchmark.provenance_category} &bull; {currentBenchmark.license}
              </span>
            )}
          </div>

          {/* Benchmark Tabs */}
          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            {benchmarks.map((b) => (
              <button
                key={b.benchmark_id}
                onClick={() => {
                  setSelectedBenchmarkId(b.benchmark_id);
                  const firstVar = Object.keys(b.modernized_adapters || {})[0] || "clean_v2";
                  setSelectedVariant(firstVar);
                  setBenchmarkValidation(null);
                }}
                style={{
                  padding: "8px 14px",
                  borderRadius: 8,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                  border: selectedBenchmarkId === b.benchmark_id ? "2px solid #0f766e" : "1px solid #cbd5e1",
                  background: selectedBenchmarkId === b.benchmark_id ? "#f0fdfa" : "white",
                  color: selectedBenchmarkId === b.benchmark_id ? "#0f766e" : "#475569",
                }}
              >
                {b.name}
              </button>
            ))}
          </div>

          {/* Benchmark Details Card */}
          {currentBenchmark && (
            <div style={{ marginTop: 14, padding: 14, borderRadius: 8, background: "#f8fafc", border: "1px solid #e2e8f0", fontSize: 13 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10, marginBottom: 10 }}>
                <div><strong>Domain:</strong> {currentBenchmark.domain}</div>
                <div><strong>Language:</strong> {currentBenchmark.language}</div>
                <div><strong>Dataset Source:</strong> {currentBenchmark.dataset_source}</div>
                <div><strong>Source / Provenance:</strong> {currentBenchmark.source}</div>
                {benchmarkValidation?.dataset_checksum && (
                  <div><strong>Dataset SHA-256:</strong> <code style={{ fontSize: 11, background: "#e2e8f0", padding: "2px 4px", borderRadius: 4 }}>{benchmarkValidation.dataset_checksum.slice(0, 16)}...</code></div>
                )}
              </div>
              <p style={{ margin: "4px 0 12px", color: "#475569", fontSize: 12 }}>{currentBenchmark.description}</p>

              {/* Evaluation Mode Toggle (CONTROLLED vs FULL_BEACON) */}
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 12, paddingBottom: 10, borderBottom: "1px dashed #cbd5e1" }}>
                <span style={{ fontWeight: 600, fontSize: 12, color: "#334155" }}>Evaluation Mode:</span>
                <button
                  onClick={() => setDiscoveryMode("CONTROLLED")}
                  style={{
                    padding: "5px 10px",
                    borderRadius: 6,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: "pointer",
                    border: discoveryMode === "CONTROLLED" ? "2px solid #0f766e" : "1px solid #cbd5e1",
                    background: discoveryMode === "CONTROLLED" ? "#ccfbf1" : "white",
                    color: discoveryMode === "CONTROLLED" ? "#0f766e" : "#475569",
                  }}
                >
                  CONTROLLED (Baseline OracleSet)
                </button>
                <button
                  onClick={() => setDiscoveryMode("FULL_BEACON")}
                  style={{
                    padding: "5px 10px",
                    borderRadius: 6,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: "pointer",
                    border: discoveryMode === "FULL_BEACON" ? "2px solid #6366f1" : "1px solid #cbd5e1",
                    background: discoveryMode === "FULL_BEACON" ? "#e0e7ff" : "white",
                    color: discoveryMode === "FULL_BEACON" ? "#4338ca" : "#475569",
                  }}
                >
                  FULL_BEACON (Evidence Mining & Discovery)
                </button>
              </div>

              {/* Modernized Target Variant Selector */}
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", borderTop: "1px solid #e2e8f0", paddingTop: 10 }}>
                <span style={{ fontWeight: 600, fontSize: 12, color: "#334155" }}>Target Variant:</span>
                {Object.keys(currentBenchmark.modernized_adapters || {}).map((varKey) => {
                  const isClean = varKey.includes("clean") || varKey.includes("equiv");
                  return (
                    <button
                      key={varKey}
                      onClick={() => setSelectedVariant(varKey)}
                      style={{
                        padding: "6px 12px",
                        borderRadius: 6,
                        fontSize: 12,
                        fontWeight: 600,
                        cursor: "pointer",
                        border: selectedVariant === varKey ? `2px solid ${isClean ? "#0f766e" : "#ef4444"}` : "1px solid #cbd5e1",
                        background: selectedVariant === varKey ? (isClean ? "#ccfbf1" : "#fee2e2") : "white",
                        color: selectedVariant === varKey ? (isClean ? "#0f766e" : "#991b1b") : "#475569",
                      }}
                    >
                      {isClean ? "✓ Clean Modernization" : `⚠ Buggy: ${varKey.replace("_v2", "").replace("buggy_", "")}`}
                    </button>
                  );
                })}

                <button
                  disabled={busy}
                  onClick={validateCurrentBenchmark}
                  style={{
                    padding: "6px 12px",
                    borderRadius: 6,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: "pointer",
                    border: "1px solid #0f766e",
                    background: "white",
                    color: "#0f766e",
                    marginLeft: "auto",
                  }}
                >
                  {busy ? "Validating..." : "Pre-Flight Validate"}
                </button>

                <button
                  disabled={busy}
                  onClick={runBenchmarkCertification}
                  style={{
                    padding: "6px 16px",
                    borderRadius: 6,
                    fontSize: 12,
                    fontWeight: 700,
                    cursor: "pointer",
                    border: "none",
                    background: selectedVariant.includes("buggy") ? "#ef4444" : "#0f766e",
                    color: "white",
                  }}
                >
                  {busy ? "Certifying..." : `Certify [${discoveryMode}]`}
                </button>
              </div>
            </div>
          )}
        </section>

        {/* Action Panel */}
        <section style={{ ...card, marginBottom: 18 }}>
          <h2 style={{ marginTop: 0, fontSize: 18 }}>Quick Loan Demo Certification</h2>
          <p style={{ color: "#64748b", fontSize: 14, margin: "4px 0 16px" }}>
            Executes frozen language-independent oracles against legacy reference and modernized candidate versions under strict certification policy.
          </p>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <button
              disabled={busy}
              onClick={() => runCertification("buggy")}
              style={{ padding: "10px 16px", border: 0, borderRadius: 8, background: "#ef4444", color: "white", fontWeight: 600, cursor: "pointer", fontSize: 13 }}
            >
              {busy ? "Executing..." : "Certify Candidate with Migration Bug"}
            </button>
            <button
              disabled={busy}
              onClick={() => runCertification("equivalent")}
              style={{ padding: "10px 16px", border: "1px solid #0f766e", borderRadius: 8, background: "white", color: "#0f766e", fontWeight: 600, cursor: "pointer", fontSize: 13 }}
            >
              Certify Equivalent Candidate
            </button>
            {selectedArtifact && (
              <a
                href={`${API_BASE}/api/v1/certification/${selectedArtifact.certification_id}/report`}
                target="_blank"
                rel="noreferrer"
                style={{ padding: "10px 16px", border: "1px solid #cbd5e1", borderRadius: 8, background: "#f8fafc", color: "#334155", textDecoration: "none", fontWeight: 600, fontSize: 13, display: "inline-flex", alignItems: "center" }}
              >
                View HTML Certificate &rarr;
              </a>
            )}
          </div>
        </section>

        {/* Selected Certificate Summary Cards */}
        {selectedArtifact && (
          <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 14, marginBottom: 18 }}>
            <div style={{ ...card, borderLeft: `4px solid ${currentStatusStyle.border}` }}>
              <div style={{ fontSize: 12, color: "#64748b", textTransform: "uppercase", fontWeight: 600 }}>Equivalence Score</div>
              <div style={{ fontSize: 26, fontWeight: 700, color: currentStatusStyle.color, marginTop: 4 }}>
                {(selectedArtifact.score * 100).toFixed(1)}%
              </div>
              <div style={{ fontSize: 11, color: currentStatusStyle.color, marginTop: 4, fontWeight: 600 }}>
                {selectedArtifact.certified ? "✓ Certified under Policy" : `⚠ Non-Certified: ${currentStatusStyle.text}`}
              </div>
            </div>
            <div style={card}>
              <div style={{ fontSize: 12, color: "#64748b", textTransform: "uppercase", fontWeight: 600 }}>Oracle Coverage</div>
              <div style={{ fontSize: 26, fontWeight: 700, color: "#0f172a", marginTop: 4 }}>
                {(selectedArtifact.metrics.oracle_coverage_pct * 100).toFixed(0)}%
              </div>
            </div>
            <div style={card}>
              <div style={{ fontSize: 12, color: "#64748b", textTransform: "uppercase", fontWeight: 600 }}>Matching Probes</div>
              <div style={{ fontSize: 26, fontWeight: 700, color: "#10b981", marginTop: 4 }}>
                {selectedArtifact.metrics.matching_probes} / {selectedArtifact.metrics.applicable_inputs}
              </div>
            </div>
            <div style={card}>
              <div style={{ fontSize: 12, color: "#64748b", textTransform: "uppercase", fontWeight: 600 }}>Regressions</div>
              <div style={{ fontSize: 26, fontWeight: 700, color: selectedArtifact.metrics.modern_regressions > 0 ? "#ef4444" : "#10b981", marginTop: 4 }}>
                {selectedArtifact.metrics.modern_regressions}
              </div>
            </div>
          </section>
        )}

        {/* Oracle Verification Drill-Down */}
        {selectedArtifact && selectedArtifact.oracle_summaries?.length > 0 && (
          <section style={{ ...card, marginBottom: 18 }}>
            <h2 style={{ marginTop: 0, fontSize: 18 }}>Per-Oracle Verification Breakdown</h2>
            <p style={{ color: "#64748b", fontSize: 13, margin: "2px 0 14px" }}>
              Click any oracle row to inspect exact behavioral condition, inputs, outputs, and counterexamples.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {selectedArtifact.oracle_summaries.map((summary) => {
                const isExpanded = expandedOracleId === summary.oracle_id;
                const isPassing = summary.oracle_status === "PASS";
                return (
                  <div
                    key={summary.oracle_id}
                    style={{ border: `1px solid ${isPassing ? "#e2e8f0" : "#fca5a5"}`, borderRadius: 8, overflow: "hidden", background: isPassing ? "#ffffff" : "#fffbfa" }}
                  >
                    <div
                      onClick={() => setExpandedOracleId(isExpanded ? null : summary.oracle_id)}
                      style={{ padding: "12px 16px", display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer", userSelect: "none" }}
                    >
                      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                        <span style={{ fontFamily: "monospace", fontWeight: 700, fontSize: 13 }}>#{summary.oracle_id}</span>
                        <code style={{ fontSize: 12, background: "#f1f5f9", padding: "2px 6px", borderRadius: 4 }}>{summary.condition_str} &rarr; {summary.consequence_str}</code>
                      </div>
                      <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
                        <span style={{ fontSize: 12, color: "#64748b" }}>{summary.matching_probes}/{summary.applicable_probes} matches</span>
                        <span style={{ fontWeight: 700, fontSize: 13, color: isPassing ? "#10b981" : "#ef4444" }}>
                          {(summary.oracle_equivalence_rate * 100).toFixed(1)}%
                        </span>
                        <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 700, background: isPassing ? "#d1fae5" : "#fee2e2", color: isPassing ? "#065f46" : "#991b1b" }}>
                          {summary.oracle_status}
                        </span>
                      </div>
                    </div>
                    {isExpanded && (
                      <div style={{ padding: "14px 16px", borderTop: "1px solid #e2e8f0", background: "#f8fafc", fontSize: 13 }}>
                        <div style={{ marginBottom: 8 }}>
                          <strong>Severity:</strong> <span style={{ textTransform: "uppercase", fontWeight: 600 }}>{summary.severity}</span> &bull; <strong>Confidence:</strong> {Math.round(summary.confidence * 100)}%
                        </div>
                        {summary.counterexamples?.length > 0 ? (
                          <div>
                            <strong style={{ color: "#991b1b" }}>Counterexample Regressions ({summary.counterexamples.length}):</strong>
                            {summary.counterexamples.slice(0, 3).map((ce, idx) => (
                              <div key={idx} style={{ marginTop: 6, background: "white", padding: 10, borderRadius: 6, border: "1px solid #fca5a5" }}>
                                <div><strong>Failed Assertion:</strong> <code>{ce.failed_assertion}</code></div>
                                <div style={{ display: "flex", gap: 16, marginTop: 4, fontSize: 12 }}>
                                  <span>Legacy Output: <b style={{ color: "#10b981" }}>{String(ce.legacy_output)}</b></span>
                                  <span>Modern Output: <b style={{ color: "#ef4444" }}>{String(ce.modern_output)}</b></span>
                                </div>
                                <pre style={{ margin: "6px 0 0", fontSize: 11, background: "#f1f5f9", padding: 6, borderRadius: 4 }}>{JSON.stringify(ce.input_values, null, 2)}</pre>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div style={{ color: "#065f46" }}>&check; All tested inputs satisfied the oracle. No counterexamples detected.</div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Test Cases / Audit Trail */}
        {selectedArtifact && (
          <section style={{ ...card, marginBottom: 18 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h2 style={{ marginTop: 0, fontSize: 18 }}>Test Cases / Audit Trail</h2>
              <a
                href={`${API_BASE}/api/v1/certification/${selectedArtifact.certification_id}/export`}
                target="_blank"
                rel="noreferrer"
                style={{ padding: "8px 12px", border: "1px solid #cbd5e1", borderRadius: 8, background: "#f8fafc", color: "#334155", textDecoration: "none", fontWeight: 600, fontSize: 12 }}
              >
                Export Dataset
              </a>
            </div>
            
            <div style={{ margin: "14px 0", display: "flex", gap: 8 }}>
              {["ALL", "MATCH", "MODERN_REGRESSION", "REFERENCE_INCONSISTENT"].map(filter => (
                <button
                  key={filter}
                  onClick={() => setCaseFilter(filter)}
                  style={{
                    padding: "4px 8px",
                    borderRadius: 4,
                    fontSize: 12,
                    border: caseFilter === filter ? "1px solid #0f766e" : "1px solid #cbd5e1",
                    background: caseFilter === filter ? "#ccfbf1" : "#f8fafc",
                    color: caseFilter === filter ? "#0f766e" : "#475569",
                    cursor: "pointer"
                  }}
                >
                  {filter}
                </button>
              ))}
            </div>

            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, textAlign: "left" }}>
                <thead>
                  <tr style={{ borderBottom: "2px solid #e2e8f0", color: "#64748b" }}>
                    <th style={{ padding: "8px" }}>Index</th>
                    <th style={{ padding: "8px" }}>Input</th>
                    <th style={{ padding: "8px" }}>Result</th>
                    <th style={{ padding: "8px" }}>Classification</th>
                  </tr>
                </thead>
                <tbody>
                  {artifactCases.slice(0, 50).map(c => (
                    <tr key={c.case_id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                      <td style={{ padding: "8px", color: "#64748b" }}>#{c.case_index}</td>
                      <td style={{ padding: "8px", fontFamily: "monospace", fontSize: 11 }}>{c.input_json}</td>
                      <td style={{ padding: "8px", fontWeight: "bold", color: c.oracle_result === "PASS" ? "#10b981" : "#ef4444" }}>{c.oracle_result}</td>
                      <td style={{ padding: "8px" }}>{c.classification}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {artifactCases.length > 50 && <p style={{ fontSize: 12, color: "#64748b", textAlign: "center" }}>Showing first 50 cases for this filter.</p>}
            </div>
          </section>
        )}

        {/* Drift Simulation */}
        <section style={{ ...card, marginBottom: 18 }}>
          <h2 style={{ marginTop: 0, fontSize: 18 }}>Continuous Drift Monitoring</h2>
          <p style={{ color: "#64748b", fontSize: 14, margin: "2px 0 14px" }}>
            Replays runtime post-migration observations against the frozen oracle set to detect behavioral drift.
          </p>
          <button
            disabled={busy || !selectedRun}
            onClick={runDriftCheck}
            style={{ padding: "8px 16px", border: "1px solid #d97706", borderRadius: 8, background: "#fffbeb", color: "#92400e", fontWeight: 600, cursor: "pointer", fontSize: 13 }}
          >
            Evaluate Post-Migration Observations
          </button>
          {driftSamples[0] && (
            <p style={{ marginTop: 10, marginBottom: 0, color: driftSamples[0].alert ? "#b42318" : "#067647", fontWeight: 600, fontSize: 13 }}>
              Latest observation: {(driftSamples[0].equivalence_score * 100).toFixed(1)}% &bull; Baseline: {(driftSamples[0].baseline_score * 100).toFixed(1)}% &bull; Status: {driftSamples[0].alert ? "DRIFT ALERT" : "STABLE"}
            </p>
          )}
        </section>

        {/* Charts & Invariants */}
        <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 18, marginBottom: 18 }}>
          <div style={card}>
            <h2 style={{ marginTop: 0, fontSize: 18 }}>Validated Behavioral Invariants</h2>
            {invariants.length === 0 ? (
              <p style={{ color: "#64748b" }}>No invariants loaded yet.</p>
            ) : (
              invariants.map((inv) => (
                <div key={inv.invariant_id} style={{ borderTop: "1px solid #e2e8f0", padding: "10px 0" }}>
                  <code>{inv.condition}</code>
                  <div style={{ color: "#64748b", marginTop: 4, fontSize: 12 }}>
                    &rarr; {inv.consequence} &bull; {Math.round(inv.confidence * 100)}% confidence
                  </div>
                </div>
              ))
            )}
          </div>
          <div style={card}>
            <h2 style={{ marginTop: 0, fontSize: 18 }}>Equivalence History</h2>
            <ResponsiveContainer width="100%" height={230}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="run" />
                <YAxis domain={[0, 100]} unit="%" />
                <Tooltip />
                <Line type="monotone" dataKey="score" stroke="#0f766e" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
      </div>
    </main>
  );
}
