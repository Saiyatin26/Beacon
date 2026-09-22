import { useState, useEffect } from "react";

export default function ThresholdMode({ apiBase = "", authFetch, badgeStyle, cardStyle }) {
  // Strategy & Policy Configuration State
  const [strategy, setStrategy] = useState("EVIDENCE_DERIVED");
  const [metric, setMetric] = useState("ABSOLUTE_DIFF");
  const [kParam, setKParam] = useState("2.0");
  const [fixedValue, setFixedValue] = useState("0.05");
  const [minSamples, setMinSamples] = useState("5");
  const [minBound, setMinBound] = useState("0.01");
  const [maxBound, setMaxBound] = useState("0.25");
  const [estimator, setEstimator] = useState("MEAN_STDDEV");
  const [outlierPolicy, setOutlierPolicy] = useState("NONE");
  const [fallbackStrategy, setFallbackStrategy] = useState("FIXED");
  const [fallbackValue, setFallbackValue] = useState("0.10");

  // Authoritative Observations Input
  const [sampleInput, setSampleInput] = useState("");
  
  // Resolution State
  const [isResolving, setIsResolving] = useState(false);
  const [resolvedThreshold, setResolvedThreshold] = useState(null);
  const [resolveError, setResolveError] = useState(null);

  // Evaluation Sandbox State (Simulation / Preview)
  const [refVal, setRefVal] = useState("");
  const [tarVal, setTarVal] = useState("");
  const [evalVerdict, setEvalVerdict] = useState(null);
  // Authoritative Evaluation Context State
  const [appId, setAppId] = useState("");
  const [refSessionId, setRefSessionId] = useState("");
  const [tarSessionId, setTarSessionId] = useState("");
  const [oracleSetId, setOracleSetId] = useState("");
  const [authEvalError, setAuthEvalError] = useState(null);
  const [backendEvalResult, setBackendEvalResult] = useState(null);
  const [isEvaluating, setIsEvaluating] = useState(false);

  const handleResolveThreshold = async () => {
    setIsResolving(true);
    setResolveError(null);
    try {
      const numbers = sampleInput
        .split(",")
        .map((s) => parseFloat(s.trim()))
        .filter((n) => !isNaN(n));

      if (strategy !== "FIXED" && numbers.length === 0) {
        setResolveError("Awaiting authoritative threshold observations");
        setIsResolving(false);
        return;
      }

      const policyPayload = {
        policy_id: `policy_${strategy.toLowerCase()}_v1`,
        version: "1.0.0",
        description: "Interactive threshold policy from UI",
        metric: metric,
        strategy: strategy,
        parameters: strategy === "FIXED" ? { value: parseFloat(fixedValue) || 0.0 } : { k: parseFloat(kParam) || 2.0 },
        minimum_samples: parseInt(minSamples, 10) || 5,
        minimum_bound: minBound ? parseFloat(minBound) : null,
        maximum_bound: maxBound ? parseFloat(maxBound) : null,
        estimator: estimator,
        outlier_policy: outlierPolicy,
        fallback_strategy: fallbackStrategy,
        fallback_value: fallbackValue ? parseFloat(fallbackValue) : null,
        enabled: true,
      };

      const resolveReq = {
        metric: metric,
        policy: policyPayload,
        reference_observations: strategy === "FIXED" ? [] : numbers,
        evidence_ids: numbers.map((_, idx) => `ev_ref_${idx + 1}`),
      };

      const resp = await (authFetch || fetch)(`${apiBase}/api/v2/threshold/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(resolveReq),
      });

      if (!resp.ok) {
        const errJson = await resp.json().catch(() => ({}));
        throw new Error(errJson.detail || `Resolution failed with HTTP ${resp.status}`);
      }

      const res = await resp.json();
      setResolvedThreshold(res);
      evaluateSimulationPreview(res);
    } catch (err) {
      setResolveError(err.message || String(err));
    } finally {
      setIsResolving(false);
    }
  };

  const evaluateSimulationPreview = (resObj) => {
    const res = resObj || resolvedThreshold;
    if (!res || (res.status !== "RESOLVED" && res.status !== "FIXED")) {
      setEvalVerdict({
        status: "INCONCLUSIVE",
        reason: "Threshold is not resolved (insufficient evidence or error).",
      });
      return;
    }

    const r = parseFloat(refVal);
    const t = parseFloat(tarVal);
    if (isNaN(r) || isNaN(t)) {
      setEvalVerdict({
        status: "ERROR",
        reason: "Reference or target value is not a valid number.",
      });
      return;
    }

    const absDiff = Math.abs(t - r);
    let diff = absDiff;
    if (metric === "RELATIVE_DIFF") {
      diff = Math.abs(r) > 1e-12 ? absDiff / Math.abs(r) : absDiff;
    } else if (metric === "PERCENTAGE_DIFF") {
      diff = Math.abs(r) > 1e-12 ? (absDiff / Math.abs(r)) * 100 : absDiff * 100;
    }

    const tol = res.final_value !== null ? res.final_value : 0.0;
    const isWithin = diff <= tol;

    setEvalVerdict({
      status: isWithin ? "EQUIVALENT" : "DIFFERENT",
      diff: diff.toFixed(6),
      tol: tol.toFixed(6),
      isWithin,
      isSimulation: true,
      reason: isWithin
        ? `[SIMULATION PREVIEW] Difference (${diff.toFixed(6)}) within resolved tolerance (${tol.toFixed(6)}). Authoritative certification runs on backend.`
        : `[SIMULATION PREVIEW] Difference (${diff.toFixed(6)}) exceeded resolved tolerance (${tol.toFixed(6)}). Authoritative certification runs on backend.`,
    });
  };

  const handleRunAuthoritativeEvaluation = async () => {
    if (!refSessionId.trim() || !tarSessionId.trim() || !oracleSetId.trim()) {
      setAuthEvalError("Reference Session ID, Target Session ID, and OracleSet ID are all strictly required for authoritative evaluation.");
      return;
    }

    setIsEvaluating(true);
    setAuthEvalError(null);
    setBackendEvalResult(null);

    try {
      const policyPayload = {
        policy_id: `policy_${strategy.toLowerCase()}_v1`,
        version: "1.0.0",
        description: "Interactive threshold policy from UI",
        metric: metric,
        strategy: strategy,
        parameters: strategy === "FIXED" ? { value: parseFloat(fixedValue) || 0.0 } : { k: parseFloat(kParam) || 2.0 },
        minimum_samples: parseInt(minSamples, 10) || 5,
        minimum_bound: minBound ? parseFloat(minBound) : null,
        maximum_bound: maxBound ? parseFloat(maxBound) : null,
        estimator: estimator,
        outlier_policy: outlierPolicy,
        fallback_strategy: fallbackStrategy,
        fallback_value: fallbackValue ? parseFloat(fallbackValue) : null,
        enabled: true,
      };

      const evalReq = {
        application_id: appId.trim(),
        reference_session_id: refSessionId.trim(),
        target_session_id: tarSessionId.trim(),
        oracle_set_id: oracleSetId.trim(),
        custom_policy: policyPayload,
        persist: true,
      };

      const resp = await (authFetch || fetch)(`${apiBase}/api/v2/evaluation/advanced`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(evalReq),
      });

      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `Evaluation failed with HTTP ${resp.status}`);
      }

      const data = await resp.json();
      setBackendEvalResult(data);
    } catch (err) {
      setAuthEvalError(err.message || String(err));
    } finally {
      setIsEvaluating(false);
    }
  };

  useEffect(() => {
    // Await authoritative threshold resolution
  }, []);

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto", padding: "10px" }}>
      {/* Header Banner */}
      <div
        style={{
          ...cardStyle,
          background: "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)",
          color: "#f8fafc",
          border: "1px solid #334155",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <h2 style={{ fontSize: "22px", fontWeight: "700", margin: "0 0 6px 0", color: "#60a5fa" }}>
              ⚡ BEACON V2 — Dynamic & Evidence-Driven Thresholds
            </h2>
            <p style={{ margin: 0, fontSize: "14px", color: "#94a3b8" }}>
              Evidence-based, deterministic, bounded, and auditable behavioral evaluation with strict anti-target-contamination guarantees.
            </p>
          </div>
          <span style={badgeStyle("#1e3a8a", "#93c5fd", "#3b82f6")}>
            Phase 8 Active
          </span>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px" }}>
        {/* Policy Configuration Panel */}
        <div style={cardStyle}>
          <h3 style={{ fontSize: "16px", fontWeight: "600", marginBottom: "16px", color: "#1e293b" }}>
            1. Threshold Policy Configuration
          </h3>

          <div style={{ marginBottom: "14px" }}>
            <label style={{ display: "block", fontSize: "13px", fontWeight: "600", marginBottom: "4px", color: "#475569" }}>
              Threshold Strategy
            </label>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              style={{ width: "100%", padding: "8px 12px", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "14px" }}
            >
              <option value="EVIDENCE_DERIVED">EVIDENCE_DERIVED (Historical Reference Spread)</option>
              <option value="STATISTICAL">STATISTICAL (Variance / StdDev Estimator)</option>
              <option value="FIXED">FIXED (Static Tolerance Parameter)</option>
              <option value="ABSOLUTE">ABSOLUTE (|target - ref| &le; tol)</option>
              <option value="RELATIVE">RELATIVE (|target - ref| / |ref| &le; tol)</option>
              <option value="PERCENTAGE">PERCENTAGE ((|target - ref| / |ref|) &times; 100 &le; tol)</option>
            </select>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "14px" }}>
            <div>
              <label style={{ display: "block", fontSize: "13px", fontWeight: "600", marginBottom: "4px", color: "#475569" }}>
                Difference Metric
              </label>
              <select
                value={metric}
                onChange={(e) => setMetric(e.target.value)}
                style={{ width: "100%", padding: "8px 12px", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "14px" }}
              >
                <option value="ABSOLUTE_DIFF">ABSOLUTE_DIFF</option>
                <option value="RELATIVE_DIFF">RELATIVE_DIFF</option>
                <option value="PERCENTAGE_DIFF">PERCENTAGE_DIFF</option>
                <option value="COUNT_DIFF">COUNT_DIFF</option>
                <option value="LATENCY_DIFF">LATENCY_DIFF</option>
              </select>
            </div>
            <div>
              <label style={{ display: "block", fontSize: "13px", fontWeight: "600", marginBottom: "4px", color: "#475569" }}>
                {strategy === "FIXED" ? "Fixed Value" : "Multiplier (k)"}
              </label>
              <input
                type="number"
                step="0.01"
                value={strategy === "FIXED" ? fixedValue : kParam}
                onChange={(e) => strategy === "FIXED" ? setFixedValue(e.target.value) : setKParam(e.target.value)}
                style={{ width: "100%", padding: "8px 12px", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "14px" }}
              />
            </div>
          </div>

          {strategy !== "FIXED" && (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "14px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "13px", fontWeight: "600", marginBottom: "4px", color: "#475569" }}>
                    Statistical Estimator
                  </label>
                  <select
                    value={estimator}
                    onChange={(e) => setEstimator(e.target.value)}
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "14px" }}
                  >
                    <option value="MEAN_STDDEV">MEAN_STDDEV (k &times; &sigma;)</option>
                    <option value="IQR_ROBUST">IQR_ROBUST (k &times; (Q3 - Q1))</option>
                    <option value="MAX_OBSERVED_DELTA">MAX_OBSERVED_DELTA</option>
                    <option value="PERCENTILE_95">PERCENTILE_95</option>
                    <option value="RANGE_FRACTION">RANGE_FRACTION</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "13px", fontWeight: "600", marginBottom: "4px", color: "#475569" }}>
                    Outlier Handling
                  </label>
                  <select
                    value={outlierPolicy}
                    onChange={(e) => setOutlierPolicy(e.target.value)}
                    style={{ width: "100%", padding: "8px 12px", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "14px" }}
                  >
                    <option value="NONE">NONE (Use All Samples)</option>
                    <option value="CLIPPED">CLIPPED (Clamp to Fences)</option>
                    <option value="ROBUST">ROBUST (Exclude Outliers)</option>
                  </select>
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "10px", marginBottom: "14px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", marginBottom: "4px", color: "#475569" }}>
                    Min Samples
                  </label>
                  <input
                    type="number"
                    value={minSamples}
                    onChange={(e) => setMinSamples(e.target.value)}
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", marginBottom: "4px", color: "#475569" }}>
                    Min Bound
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    value={minBound}
                    onChange={(e) => setMinBound(e.target.value)}
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", marginBottom: "4px", color: "#475569" }}>
                    Max Bound
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    value={maxBound}
                    onChange={(e) => setMaxBound(e.target.value)}
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                  />
                </div>
              </div>

              <div style={{ marginBottom: "14px" }}>
                <label style={{ display: "block", fontSize: "13px", fontWeight: "600", marginBottom: "4px", color: "#475569" }}>
                  Reference Observations (Comma-separated)
                </label>
                <textarea
                  rows={2}
                  value={sampleInput}
                  onChange={(e) => setSampleInput(e.target.value)}
                  placeholder="Awaiting authoritative threshold observations or enter comma-separated numbers..."
                  style={{ width: "100%", padding: "8px 12px", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "13px", fontFamily: "monospace" }}
                />
              </div>
            </>
          )}

          <button
            onClick={handleResolveThreshold}
            disabled={isResolving}
            style={{
              width: "100%",
              padding: "10px",
              background: "#2563eb",
              color: "#ffffff",
              border: "none",
              borderRadius: "8px",
              fontWeight: "600",
              cursor: isResolving ? "wait" : "pointer",
            }}
          >
            {isResolving ? "Resolving..." : "⚡ Resolve & Freeze Threshold"}
          </button>
        </div>

        {/* Resolved Threshold & Evaluation Sandbox */}
        <div>
          {/* Resolved Threshold Card */}
          <div style={cardStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
              <h3 style={{ fontSize: "16px", fontWeight: "600", margin: 0, color: "#1e293b" }}>
                2. Resolved & Frozen Threshold
              </h3>
              {resolvedThreshold && (
                <span
                  style={
                    resolvedThreshold.status === "RESOLVED"
                      ? badgeStyle("#ecfdf5", "#047857", "#10b981")
                      : resolvedThreshold.status === "FIXED"
                      ? badgeStyle("#eff6ff", "#1d4ed8", "#3b82f6")
                      : badgeStyle("#fff7ed", "#c2410c", "#f97316")
                  }
                >
                  {resolvedThreshold.status}
                </span>
              )}
            </div>

            {resolveError && (
              <div style={{ padding: "10px", background: "#fef2f2", color: "#b91c1c", borderRadius: "8px", fontSize: "13px", marginBottom: "12px" }}>
                Error: {resolveError}
              </div>
            )}

            {resolvedThreshold ? (
              <div style={{ background: "#f8fafc", padding: "14px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", fontSize: "13px", marginBottom: "10px" }}>
                  <div>Strategy: <strong>{resolvedThreshold.strategy}</strong></div>
                  <div>Final Tolerance: <strong style={{ color: "#2563eb", fontSize: "15px" }}>{resolvedThreshold.final_value !== null ? resolvedThreshold.final_value : "N/A"}</strong></div>
                  <div>Raw Calculated: <span>{resolvedThreshold.raw_value !== null ? resolvedThreshold.raw_value : "N/A"}</span></div>
                  <div>Sample Count: <span>{resolvedThreshold.sample_count}</span></div>
                  <div>Min / Max Bounds: <span>[{resolvedThreshold.minimum_bound ?? "None"}, {resolvedThreshold.maximum_bound ?? "None"}]</span></div>
                  <div>Fallback Used: <span>{resolvedThreshold.fallback_used ? "Yes" : "No"}</span></div>
                </div>
                <div style={{ fontSize: "11px", color: "#64748b", wordBreak: "break-all" }}>
                  Resolution ID: {resolvedThreshold.resolution_id}
                </div>
              </div>
            ) : (
              <div style={{ color: "#94a3b8", fontSize: "13px" }}>Awaiting authoritative threshold resolution</div>
            )}
          </div>

          {/* Evaluation Sandbox Card (Preview / Simulation) */}
          <div style={cardStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
              <h3 style={{ fontSize: "16px", fontWeight: "600", margin: 0, color: "#1e293b" }}>
                3. Simulation Preview (Non-Authoritative)
              </h3>
              <span style={badgeStyle("#f1f5f9", "#475569", "#cbd5e1")}>
                Preview Only
              </span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "14px" }}>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", marginBottom: "4px", color: "#475569" }}>
                  Reference Value
                </label>
                <input
                  type="text"
                  value={refVal}
                  placeholder="Reference value (optional preview)..."
                  onChange={(e) => {
                    setRefVal(e.target.value);
                    evaluateSimulationPreview();
                  }}
                  style={{ width: "100%", padding: "8px 10px", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", marginBottom: "4px", color: "#475569" }}>
                  Target Value
                </label>
                <input
                  type="text"
                  value={tarVal}
                  placeholder="Target value (optional preview)..."
                  onChange={(e) => {
                    setTarVal(e.target.value);
                    evaluateSimulationPreview();
                  }}
                  style={{ width: "100%", padding: "8px 10px", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>
            </div>

            {evalVerdict && (
              <div
                style={{
                  padding: "14px",
                  borderRadius: "8px",
                  border: `1px solid ${
                    evalVerdict.status === "EQUIVALENT" ? "#86efac" : evalVerdict.status === "DIFFERENT" ? "#fca5a5" : "#fed7aa"
                  }`,
                  background:
                    evalVerdict.status === "EQUIVALENT" ? "#f0fdf4" : evalVerdict.status === "DIFFERENT" ? "#fef2f2" : "#fff7ed",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                  <span style={{ fontWeight: "700", fontSize: "15px", color: evalVerdict.status === "EQUIVALENT" ? "#15803d" : "#b91c1c" }}>
                    {evalVerdict.status === "EQUIVALENT" ? "✓ EQUIVALENT (PREVIEW)" : evalVerdict.status === "DIFFERENT" ? "✗ DIFFERENT (PREVIEW)" : "⚠ INCONCLUSIVE"}
                  </span>
                  {evalVerdict.diff !== undefined && (
                    <span style={{ fontSize: "13px", color: "#475569" }}>
                      &Delta; = {evalVerdict.diff} (Tol = {evalVerdict.tol})
                    </span>
                  )}
                </div>
                <div style={{ fontSize: "13px", color: "#334155" }}>{evalVerdict.reason}</div>
              </div>
            )}
          </div>

          {/* Authoritative Certification Card (Context-Aware) */}
          <div style={cardStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
              <h3 style={{ fontSize: "16px", fontWeight: "600", margin: 0, color: "#1e293b" }}>
                4. Authoritative Certification Evaluation
              </h3>
              <span style={badgeStyle("#0f172a", "#f8fafc", "#334155")}>
                Authoritative
              </span>
            </div>

            <p style={{ fontSize: "13px", color: "#64748b", margin: "0 0 14px 0" }}>
              Executes backend certification binding real Phase 3 Evidence Sessions with Phase 7 OracleSet rules under the resolved threshold policy.
            </p>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginBottom: "10px" }}>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", marginBottom: "4px", color: "#475569" }}>
                  Application ID *
                </label>
                <input
                  type="text"
                  value={appId}
                  onChange={(e) => setAppId(e.target.value)}
                  placeholder="e.g. repository_application_id"
                  style={{ width: "100%", padding: "7px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", marginBottom: "4px", color: "#475569" }}>
                  OracleSet ID *
                </label>
                <input
                  type="text"
                  value={oracleSetId}
                  onChange={(e) => setOracleSetId(e.target.value)}
                  placeholder="e.g. oset_id"
                  style={{ width: "100%", padding: "7px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginBottom: "14px" }}>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", marginBottom: "4px", color: "#475569" }}>
                  Reference Session ID *
                </label>
                <input
                  type="text"
                  value={refSessionId}
                  onChange={(e) => setRefSessionId(e.target.value)}
                  placeholder="e.g. SESS-REF-001"
                  style={{ width: "100%", padding: "7px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", marginBottom: "4px", color: "#475569" }}>
                  Target Session ID *
                </label>
                <input
                  type="text"
                  value={tarSessionId}
                  onChange={(e) => setTarSessionId(e.target.value)}
                  placeholder="e.g. SESS-TAR-001"
                  style={{ width: "100%", padding: "7px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>
            </div>

            {(!refSessionId.trim() || !tarSessionId.trim() || !oracleSetId.trim()) && (
              <div style={{ padding: "10px", background: "#fff7ed", border: "1px solid #fed7aa", borderRadius: "6px", color: "#c2410c", fontSize: "12px", marginBottom: "12px" }}>
                ⚠️ Authoritative certification requires selecting/providing Reference Session ID, Target Session ID, and OracleSet ID.
              </div>
            )}

            {authEvalError && (
              <div style={{ padding: "10px", background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "6px", color: "#b91c1c", fontSize: "12px", marginBottom: "12px" }}>
                Error: {authEvalError}
              </div>
            )}

            <button
              onClick={handleRunAuthoritativeEvaluation}
              disabled={isEvaluating || !refSessionId.trim() || !tarSessionId.trim() || !oracleSetId.trim()}
              style={{
                width: "100%",
                padding: "10px",
                background: (!refSessionId.trim() || !tarSessionId.trim() || !oracleSetId.trim()) ? "#94a3b8" : "#0f172a",
                color: "#ffffff",
                border: "none",
                borderRadius: "8px",
                fontWeight: "600",
                cursor: (isEvaluating || !refSessionId.trim() || !tarSessionId.trim() || !oracleSetId.trim()) ? "not-allowed" : "pointer",
              }}
            >
              {isEvaluating ? "Executing Certification..." : "🛡️ Run Backend Authoritative Evaluation"}
            </button>

            {backendEvalResult && (
              <div style={{ marginTop: "14px", background: "#f8fafc", padding: "14px", borderRadius: "8px", border: "1px solid #cbd5e1" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                  <strong style={{ fontSize: "14px", color: "#0f172a" }}>Authoritative Backend Verdict</strong>
                  <span
                    style={
                      backendEvalResult.overall_verdict === "EQUIVALENT"
                        ? badgeStyle("#ecfdf5", "#047857", "#10b981")
                        : backendEvalResult.overall_verdict === "DIFFERENT"
                        ? badgeStyle("#fef2f2", "#b91c1c", "#ef4444")
                        : badgeStyle("#fff7ed", "#c2410c", "#f97316")
                    }
                  >
                    {backendEvalResult.overall_verdict}
                  </span>
                </div>
                <div style={{ fontSize: "12px", color: "#475569", lineHeight: "1.6" }}>
                  <div>Evaluation ID: <code>{backendEvalResult.evaluation_id}</code></div>
                  <div>OracleSet Hash: <code>{backendEvalResult.oracle_set_hash?.slice(0, 16) || "N/A"}...</code></div>
                  <div>Policy Hash: <code>{backendEvalResult.policy_hash?.slice(0, 16)}...</code></div>
                  <div>Evaluations: <strong>{backendEvalResult.total_evaluations}</strong> (Passed: {backendEvalResult.passed_count}, Failed: {backendEvalResult.failed_count}, Inconclusive: {backendEvalResult.inconclusive_count})</div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
