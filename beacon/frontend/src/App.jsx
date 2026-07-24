import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

const API_BASE = "http://localhost:8000";

export default function App() {
  const [runs, setRuns] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/runs`)
      .then((r) => r.json())
      .then((data) => {
        setRuns(data.runs || []);
        if (data.runs?.length) setSelectedRun(data.runs[0]);
      })
      .catch(() => setError(
        "Could not reach the BEACON API. Is uvicorn running on :8000 " +
        "(cd backend && uvicorn api.main:app --reload --port 8000)?"
      ));
  }, []);

  const chartData = [...runs].reverse().map((r) => ({
    run: r.run_id,
    score: Math.round(r.equivalence_score * 100),
  }));

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", maxWidth: 900, margin: "40px auto", padding: "0 16px" }}>
      <h1>BEACON — Behavioral Equivalence Dashboard</h1>

      {error && <p style={{ color: "#993C1D" }}>{error}</p>}

      <h2>Equivalence score over time</h2>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="run" />
          <YAxis domain={[0, 100]} unit="%" />
          <Tooltip />
          <Line type="monotone" dataKey="score" stroke="#993C1D" strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>

      <h2>Certification runs</h2>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid #ccc" }}>
            <th>Run ID</th><th>Timestamp</th><th>Score</th><th>Violations</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.run_id} onClick={() => setSelectedRun(r)}
                style={{ cursor: "pointer", borderBottom: "1px solid #eee" }}>
              <td>{r.run_id}</td>
              <td>{r.timestamp}</td>
              <td>{(r.equivalence_score * 100).toFixed(1)}%</td>
              <td>{r.total_violated}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {selectedRun && (
        <>
          <h2>Violation detail — run {selectedRun.run_id}</h2>
          {selectedRun.violations.length === 0 && <p>No violations in this run.</p>}
          {selectedRun.violations.map((v) => (
            <div key={v.invariant_id} style={{ border: "1px solid #ddd", borderRadius: 8, padding: 12, marginBottom: 10 }}>
              <b>Invariant #{v.invariant_id}</b> — severity: {v.severity}, confidence: {v.confidence.toFixed(2)}
              <p>Expected: {v.expected}</p>
              <p>Legacy output: {v.legacy_output} &nbsp;|&nbsp; Modern output: {v.modern_output}</p>
              <p>Counterexample: {JSON.stringify(v.counterexample)}</p>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
