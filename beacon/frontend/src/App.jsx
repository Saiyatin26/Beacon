import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

const API_BASE = "http://localhost:8000";

const card = { background: "white", border: "1px solid #e5e7eb", borderRadius: 12, padding: 18, boxShadow: "0 1px 2px #00000008" };

export default function App() {
  const [runs, setRuns] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [invariants, setInvariants] = useState([]);
  const [driftSamples, setDriftSamples] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);

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

  useEffect(() => {
    Promise.all([loadRuns(), loadInvariants(), loadDrift()]).catch(() => setError(
      "Could not reach the BEACON API. Start it with: cd backend; python -m uvicorn api.main:app --reload --port 8000"
    ));
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
      setNotice(implementation === "buggy"
        ? "Buggy modernization certified: BEACON found the missing rule."
        : "Equivalent implementation certified: all mined rules passed.");
    } catch (runError) {
      setError(runError.message);
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
      setNotice(data.alert
        ? `Drift alert: score fell ${data.delta_pct.toFixed(1)} points below the selected baseline.`
        : "No material drift detected against the selected baseline.");
    } catch (driftError) {
      setError(driftError.message);
    } finally {
      setBusy(false);
    }
  };

  const chartData = [...runs].reverse().map((run) => ({
    run: run.run_id,
    score: Math.round(run.equivalence_score * 100),
  }));

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", color: "#172033", background: "#f8fafc", minHeight: "100vh", padding: "32px 16px" }}>
      <div style={{ maxWidth: 1000, margin: "0 auto" }}>
        <header style={{ marginBottom: 24 }}>
          <p style={{ color: "#0f766e", fontWeight: 700, margin: 0, letterSpacing: 1 }}>BEACON · LOCAL PROTOTYPE</p>
          <h1 style={{ margin: "6px 0" }}>Behavioral Equivalence Certification</h1>
          <p style={{ margin: 0, color: "#475569" }}>Mine legacy decision rules, test a modernization, and retain an auditable certification history.</p>
        </header>

        {error && <p style={{ ...card, color: "#b42318", borderColor: "#fecdca" }}>{error}</p>}
        {notice && <p style={{ ...card, color: "#067647", borderColor: "#a6f4c5" }}>{notice}</p>}

        <section style={{ ...card, marginBottom: 18 }}>
          <h2 style={{ marginTop: 0 }}>Run the loan-approval certification</h2>
          <p style={{ color: "#475569" }}>The local miner extracts and validates rules from the sample legacy Python application. No API keys are required.</p>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <button disabled={busy} onClick={() => runCertification("buggy")} style={{ padding: "10px 14px", border: 0, borderRadius: 8, background: "#b42318", color: "white", cursor: "pointer" }}>
              {busy ? "Running…" : "Certify buggy modernization"}
            </button>
            <button disabled={busy} onClick={() => runCertification("equivalent")} style={{ padding: "10px 14px", border: "1px solid #0f766e", borderRadius: 8, background: "white", color: "#0f766e", cursor: "pointer" }}>
              Certify equivalent implementation
            </button>
          </div>
        </section>

        <section style={{ ...card, marginBottom: 18 }}>
          <h2 style={{ marginTop: 0 }}>Production drift simulation</h2>
          <p style={{ color: "#475569" }}>Use the selected certification run as a baseline, then replay the buggy deployment against the same executable oracles.</p>
          <button disabled={busy || !selectedRun} onClick={runDriftCheck} style={{ padding: "10px 14px", border: "1px solid #a16207", borderRadius: 8, background: "#fffbeb", color: "#854d0e", cursor: "pointer" }}>
            Check drift against selected run
          </button>
          {driftSamples[0] && <p style={{ marginBottom: 0, color: driftSamples[0].alert ? "#b42318" : "#067647" }}>
            Latest sample: {(driftSamples[0].equivalence_score * 100).toFixed(1)}% · baseline {(driftSamples[0].baseline_score * 100).toFixed(1)}% · {driftSamples[0].alert ? "alert" : "stable"}
          </p>}
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 18, marginBottom: 18 }}>
          <div style={card}>
            <h2 style={{ marginTop: 0 }}>Mined invariants</h2>
            {invariants.length === 0 ? <p>No invariants loaded yet.</p> : invariants.map((invariant) => (
              <div key={invariant.invariant_id} style={{ borderTop: "1px solid #e5e7eb", padding: "10px 0" }}>
                <code>{invariant.condition}</code>
                <div style={{ color: "#475569", marginTop: 4 }}>→ {invariant.consequence} · {Math.round(invariant.confidence * 100)}% confidence</div>
              </div>
            ))}
          </div>
          <div style={card}>
            <h2 style={{ marginTop: 0 }}>Equivalence score history</h2>
            <ResponsiveContainer width="100%" height={230}>
              <LineChart data={chartData}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="run" /><YAxis domain={[0, 100]} unit="%" /><Tooltip /><Line type="monotone" dataKey="score" stroke="#0f766e" strokeWidth={2} /></LineChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section style={card}>
          <h2 style={{ marginTop: 0 }}>Certification history</h2>
          {runs.length === 0 ? <p style={{ color: "#475569" }}>No runs yet. Use one of the certification buttons above.</p> : (
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ textAlign: "left", borderBottom: "1px solid #cbd5e1" }}><th>Run</th><th>Score</th><th>Violations</th><th>Timestamp</th></tr></thead>
              <tbody>{runs.map((run) => <tr key={run.run_id} onClick={() => setSelectedRun(run)} style={{ cursor: "pointer", borderBottom: "1px solid #e5e7eb" }}><td>{run.run_id}</td><td>{(run.equivalence_score * 100).toFixed(1)}%</td><td>{run.total_violated}</td><td>{new Date(run.timestamp).toLocaleString()}</td></tr>)}</tbody>
            </table>
          )}
        </section>

        {selectedRun && <section style={{ ...card, marginTop: 18 }}>
          <h2 style={{ marginTop: 0 }}>Violation detail · {selectedRun.run_id}</h2>
          {selectedRun.violations.length === 0 ? <p style={{ color: "#067647" }}>No rule violations found.</p> : selectedRun.violations.map((violation) => (
            <article key={violation.invariant_id} style={{ borderLeft: "4px solid #b42318", background: "#fffbfa", padding: 14, marginBottom: 10 }}>
              <b>Invariant {violation.invariant_id}</b> · {violation.severity} · {Math.round(violation.confidence * 100)}% confidence
              <div>Expected: {violation.expected}</div><div>Legacy: {violation.legacy_output} | Modern: {violation.modern_output}</div>
              <code style={{ display: "block", marginTop: 8 }}>{JSON.stringify(violation.counterexample)}</code>
            </article>
          ))}
        </section>}
      </div>
    </main>
  );
}
