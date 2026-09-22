import React, { useState, useEffect } from "react";

export default function ControlledMode({ apiBase = "", authFetch, badgeStyle, cardStyle }) {
  // Rules List & Selected Rule
  const [rules, setRules] = useState([]);
  const [loadingRules, setLoadingRules] = useState(false);
  const [selectedRuleId, setSelectedRuleId] = useState(null);

  // Rule Form State
  const [ruleId, setRuleId] = useState("R-001");
  const [ruleName, setRuleName] = useState("Eligibility Minimum Age Requirement");
  const [ruleDescription, setRuleDescription] = useState("Requests with age >= 18 should be accepted");
  const [ruleSeverity, setRuleSeverity] = useState("CRITICAL");
  const [conditionField, setConditionField] = useState("age");
  const [conditionOperator, setConditionOperator] = useState("GTE");
  const [conditionValue, setConditionValue] = useState("18");
  const [conditionType, setConditionType] = useState("number"); // number, string, boolean, json
  const [expectedType, setExpectedType] = useState("ACCEPT");
  const [expectedStatus, setExpectedStatus] = useState("");
  const [expectedPayload, setExpectedPayload] = useState("");

  // Validation / Evaluation feedback
  const [validationResult, setValidationResult] = useState(null);
  const [evaluating, setEvaluating] = useState(false);
  const [evaluationResult, setEvaluationResult] = useState(null);
  const [evaluationId, setEvaluationId] = useState("");
  const [naturalLanguageInput, setNaturalLanguageInput] = useState("");
  const [nlNotice, setNlNotice] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const fetchClient = authFetch || window.fetch;

  // Load registered rules on mount
  const loadRules = async () => {
    setLoadingRules(true);
    setError(null);
    try {
      const res = await fetchClient(`${apiBase}/api/v2/rules`);
      if (res.ok) {
        const data = await res.json();
        setRules(data.rules || []);
      } else {
        const err = await res.json().catch(() => ({}));
        setError(err.detail || "Failed to load rules");
      }
    } catch (e) {
      setError("Error connecting to rules API: " + e.message);
    } finally {
      setLoadingRules(false);
    }
  };

  useEffect(() => {
    loadRules();
  }, []);

  // Parse condition value based on selected type
  const parseTypedValue = (valStr, type) => {
    if (type === "number") {
      const num = Number(valStr);
      return isNaN(num) ? valStr : num;
    }
    if (type === "boolean") {
      return valStr.toLowerCase() === "true" || valStr === "1";
    }
    if (type === "json") {
      try {
        return JSON.parse(valStr);
      } catch {
        return valStr;
      }
    }
    return valStr;
  };

  const buildCurrentRulePayload = () => {
    const parsedVal = parseTypedValue(conditionValue, conditionType);
    let expectedBehavior = { type: expectedType };
    if (expectedStatus) {
      const stNum = Number(expectedStatus);
      expectedBehavior.status_code = isNaN(stNum) ? expectedStatus : stNum;
    }
    if (expectedPayload.trim()) {
      try {
        expectedBehavior.payload = JSON.parse(expectedPayload);
      } catch {
        expectedBehavior.payload = expectedPayload;
      }
    }

    return {
      rule_id: ruleId.trim(),
      name: ruleName.trim(),
      description: ruleDescription.trim(),
      version: 1,
      source: "USER_DEFINED",
      severity: ruleSeverity,
      status: "ACTIVE",
      condition: {
        field: conditionField.trim(),
        operator: conditionOperator,
        value: parsedVal,
        value_type: conditionType,
      },
      expected_behavior: expectedBehavior,
      referenced_fields: [conditionField.trim()],
      metadata: {
        created_via: "controlled_mode_ui",
      },
    };
  };

  const handleValidateRule = async () => {
    setError(null);
    setNotice(null);
    setValidationResult(null);
    try {
      const payload = buildCurrentRulePayload();
      const res = await fetchClient(`${apiBase}/api/v2/rules/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      setValidationResult(data);
      if (data.is_valid) {
        setNotice(`Rule syntax and semantics valid. Fingerprint: ${data.fingerprint?.slice(0, 16)}...`);
      } else {
        setError(`Rule validation failed: ${data.errors?.join("; ")}`);
      }
    } catch (e) {
      setError("Validation failed: " + e.message);
    }
  };

  const handleSaveRule = async () => {
    setError(null);
    setNotice(null);
    try {
      const payload = buildCurrentRulePayload();
      const res = await fetchClient(`${apiBase}/api/v2/rules`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (res.ok) {
        setNotice(`Rule [${data.rule_id}] v${data.version} registered successfully.`);
        await loadRules();
      } else {
        setError(data.detail || "Failed to register rule.");
      }
    } catch (e) {
      setError("Registration error: " + e.message);
    }
  };

  const handleSimulateNaturalLanguage = () => {
    if (!naturalLanguageInput.trim()) return;
    setInterpretingNl(true);
    setNlNotice(null);
    setTimeout(() => {
      // Deterministic parser / interpreter mapping for Controlled Mode
      const text = naturalLanguageInput.toLowerCase();
      if (text.includes("age") && (text.includes("below 18") || text.includes("< 18") || text.includes("under 18"))) {
        setRuleId("R-NL-001");
        setRuleName("Reject Minors Under 18");
        setRuleDescription(naturalLanguageInput);
        setConditionField("age");
        setConditionOperator("LT");
        setConditionValue("18");
        setConditionType("number");
        setExpectedType("REJECT");
        setNlNotice("Interpreted natural-language constraint into structured AST (Audit Status: Reviewable, Non-authoritative).");
      } else if (text.includes("amount") && (text.includes(">") || text.includes("greater") || text.includes("over"))) {
        setRuleId("R-NL-002");
        setRuleName("High Value Request Restriction");
        setRuleDescription(naturalLanguageInput);
        setConditionField("amount");
        setConditionOperator("GT");
        setConditionValue("10000");
        setConditionType("number");
        setExpectedType("RETURN_STATUS");
        setExpectedStatus("400");
        setNlNotice("Interpreted natural-language rule into structured rule. Review and validate before certifying.");
      } else {
        setRuleId("R-NL-CUSTOM");
        setRuleName("Custom NL Rule");
        setRuleDescription(naturalLanguageInput);
        setConditionField("status");
        setConditionOperator("EQ");
        setConditionValue("ACTIVE");
        setConditionType("string");
        setExpectedType("ACCEPT");
        setNlNotice("Interpreted natural-language rule into structured rule representation.");
      }
      setInterpretingNl(false);
    }, 400);
  };

  const handleRunControlledEvaluation = async () => {
    setEvaluating(true);
    setError(null);
    setNotice(null);
    setEvaluationResult(null);
    try {
      const activeRule = buildCurrentRulePayload();
      const res = await fetchClient(`${apiBase}/api/v2/controlled/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rules: [activeRule],
          evaluation_id: evaluationId,
          strict_evidence_policy: true,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setEvaluationResult(data);
        setNotice(`Controlled evaluation completed: Overall Status = ${data.overall_status}`);
      } else {
        setError(data.detail || "Controlled evaluation failed.");
      }
    } catch (e) {
      setError("Evaluation execution failed: " + e.message);
    } finally {
      setEvaluating(false);
    }
  };

  const statusBadge = (status) => {
    switch (status) {
      case "PASS":
        return <span style={badgeStyle("#ecfdf5", "#065f46", "#10b981")}>✓ PASS</span>;
      case "FAIL":
        return <span style={badgeStyle("#fef2f2", "#991b1b", "#ef4444")}>✗ FAIL</span>;
      case "INCONCLUSIVE":
        return <span style={badgeStyle("#fff7ed", "#9a3412", "#f97316")}>? INCONCLUSIVE</span>;
      case "NOT_APPLICABLE":
        return <span style={badgeStyle("#f8fafc", "#475569", "#94a3b8")}>○ NOT APPLICABLE</span>;
      case "ERROR":
        return <span style={badgeStyle("#fdf2f8", "#9d174d", "#f43f5e")}>⚠ ERROR</span>;
      default:
        return <span style={badgeStyle("#f1f5f9", "#334155", "#cbd5e1")}>{status || "UNKNOWN"}</span>;
    }
  };

  return (
    <div style={{ maxWidth: "1440px", margin: "0 auto", padding: "24px 0" }}>
      {/* Title & Introduction */}
      <div style={{ ...cardStyle, borderLeft: "4px solid #2563eb", background: "#f8fafc" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "12px" }}>
          <div>
            <h2 style={{ margin: "0 0 6px 0", fontSize: "18px", fontWeight: "700", color: "#0f172a" }}>
              ⚖️ Controlled Mode — Business Rule Understanding & Behavioral Compliance
            </h2>
            <p style={{ margin: 0, fontSize: "13px", color: "#64748b", maxWidth: "900px", lineHeight: "1.5" }}>
              Evaluate explicit, user-defined business rules against Phase 3 observable evidence and Phase 4 behavioral evaluations.
              Phase 4 certifies <strong>Behavioral Equivalence</strong> (<em>Reference ≡ Target</em>), while Phase 5 evaluates <strong>Rule Compliance</strong> (<em>Observed Behavior satisfies Rule</em>).
            </p>
          </div>
          <div style={{ display: "flex", gap: "8px" }}>
            <span style={badgeStyle("#eff6ff", "#1d4ed8", "#60a5fa")}>Phase 5 Active</span>
            <span style={badgeStyle("#f0fdf4", "#166534", "#4ade80")}>Domain Agnostic</span>
            <span style={badgeStyle("#fdf4ff", "#7e22ce", "#c084fc")}>Deterministic AST</span>
          </div>
        </div>
      </div>

      {/* Notifications */}
      {error && (
        <div style={{ ...cardStyle, background: "#fef2f2", border: "1px solid #fecaca", color: "#991b1b", padding: "12px 16px" }}>
          <strong>Error: </strong> {error}
        </div>
      )}
      {notice && (
        <div style={{ ...cardStyle, background: "#f0fdf4", border: "1px solid #bbf7d0", color: "#166534", padding: "12px 16px" }}>
          <strong>Notice: </strong> {notice}
        </div>
      )}

      {/* Grid: Left Column (Rule Builder), Right Column (Evaluation & Results) */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px" }}>
        
        {/* Left Column: Rule Specification & Registry */}
        <div>
          {/* Natural Language Interpreter Extension Point (Optional & Auditable) */}
          <div style={cardStyle}>
            <h3 style={{ margin: "0 0 10px 0", fontSize: "14px", fontWeight: "600", color: "#334155" }}>
              💬 Natural Language Rule Input (Optional Interpreter)
            </h3>
            <p style={{ fontSize: "12px", color: "#64748b", margin: "0 0 8px 0" }}>
              Translates natural language text into a structured, reviewable AST. The LLM/interpreter output is always normalized and never acts as certification authority.
            </p>
            <div style={{ display: "flex", gap: "8px" }}>
              <input
                type="text"
                value={naturalLanguageInput}
                onChange={(e) => setNaturalLanguageInput(e.target.value)}
                placeholder="e.g., If age is below 18, reject the request."
                style={{ flex: 1, padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
              />
              <button
                onClick={handleSimulateNaturalLanguage}
                disabled={interpretingNl || !naturalLanguageInput.trim()}
                style={{
                  background: "#475569",
                  color: "#ffffff",
                  border: "none",
                  padding: "8px 14px",
                  borderRadius: "6px",
                  fontSize: "12px",
                  fontWeight: "600",
                  cursor: "pointer",
                }}
              >
                {interpretingNl ? "Interpreting..." : "Translate to AST"}
              </button>
            </div>
            {nlNotice && (
              <div style={{ marginTop: "8px", fontSize: "12px", color: "#2563eb", background: "#eff6ff", padding: "6px 10px", borderRadius: "4px" }}>
                ℹ️ {nlNotice}
              </div>
            )}
          </div>

          {/* Structured Rule Builder Form */}
          <div style={cardStyle}>
            <h3 style={{ margin: "0 0 16px 0", fontSize: "15px", fontWeight: "600", color: "#0f172a" }}>
              🛠️ Structured Business Rule Builder
            </h3>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: "12px", marginBottom: "12px" }}>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>Rule ID</label>
                <input
                  type="text"
                  value={ruleId}
                  onChange={(e) => setRuleId(e.target.value)}
                  style={{ width: "100%", padding: "6px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>Rule Title / Name</label>
                <input
                  type="text"
                  value={ruleName}
                  onChange={(e) => setRuleName(e.target.value)}
                  style={{ width: "100%", padding: "6px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>
            </div>

            <div style={{ marginBottom: "12px" }}>
              <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>Description</label>
              <textarea
                rows={2}
                value={ruleDescription}
                onChange={(e) => setRuleDescription(e.target.value)}
                style={{ width: "100%", padding: "6px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
              />
            </div>

            {/* Condition AST Section */}
            <div style={{ background: "#f8fafc", padding: "12px", borderRadius: "8px", border: "1px solid #e2e8f0", marginBottom: "12px" }}>
              <span style={{ fontSize: "12px", fontWeight: "700", color: "#334155", display: "block", marginBottom: "8px" }}>
                CONDITION PREDICATE (IF)
              </span>
              <div style={{ display: "grid", gridTemplateColumns: "2fr 2fr 2fr 1.5fr", gap: "8px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "11px", color: "#64748b", marginBottom: "2px" }}>Field</label>
                  <input
                    type="text"
                    value={conditionField}
                    onChange={(e) => setConditionField(e.target.value)}
                    placeholder="e.g. age, status"
                    style={{ width: "100%", padding: "5px 8px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "12px" }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "11px", color: "#64748b", marginBottom: "2px" }}>Operator</label>
                  <select
                    value={conditionOperator}
                    onChange={(e) => setConditionOperator(e.target.value)}
                    style={{ width: "100%", padding: "5px 8px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "12px", background: "#fff" }}
                  >
                    <option value="EQ">EQ (==)</option>
                    <option value="NE">NE (!=)</option>
                    <option value="GT">GT (&gt;)</option>
                    <option value="GTE">GTE (&gt;=)</option>
                    <option value="LT">LT (&lt;)</option>
                    <option value="LTE">LTE (&lt;=)</option>
                    <option value="IN">IN (contained in)</option>
                    <option value="NOT_IN">NOT_IN (not in)</option>
                    <option value="CONTAINS">CONTAINS (has item)</option>
                    <option value="IS_NULL">IS_NULL</option>
                    <option value="IS_NOT_NULL">IS_NOT_NULL</option>
                    <option value="EXISTS">EXISTS</option>
                    <option value="NOT_EXISTS">NOT_EXISTS</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "11px", color: "#64748b", marginBottom: "2px" }}>Value</label>
                  <input
                    type="text"
                    value={conditionValue}
                    onChange={(e) => setConditionValue(e.target.value)}
                    placeholder="e.g. 18, ACTIVE"
                    style={{ width: "100%", padding: "5px 8px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "12px" }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "11px", color: "#64748b", marginBottom: "2px" }}>Type</label>
                  <select
                    value={conditionType}
                    onChange={(e) => setConditionType(e.target.value)}
                    style={{ width: "100%", padding: "5px 8px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "12px", background: "#fff" }}
                  >
                    <option value="number">Number</option>
                    <option value="string">String</option>
                    <option value="boolean">Boolean</option>
                    <option value="json">JSON Array/Obj</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Expected Behavior Section */}
            <div style={{ background: "#f8fafc", padding: "12px", borderRadius: "8px", border: "1px solid #e2e8f0", marginBottom: "16px" }}>
              <span style={{ fontSize: "12px", fontWeight: "700", color: "#334155", display: "block", marginBottom: "8px" }}>
                EXPECTED BEHAVIOR (THEN)
              </span>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "11px", color: "#64748b", marginBottom: "2px" }}>Behavior Type</label>
                  <select
                    value={expectedType}
                    onChange={(e) => setExpectedType(e.target.value)}
                    style={{ width: "100%", padding: "5px 8px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "12px", background: "#fff" }}
                  >
                    <option value="ACCEPT">ACCEPT (HTTP 2xx / success)</option>
                    <option value="REJECT">REJECT (HTTP 4xx / rejection)</option>
                    <option value="RETURN_STATUS">RETURN_STATUS</option>
                    <option value="RETURN_VALUE">RETURN_VALUE</option>
                    <option value="ERROR">ERROR (HTTP 5xx / exception)</option>
                    <option value="STATE_CHANGE">STATE_CHANGE</option>
                    <option value="NO_STATE_CHANGE">NO_STATE_CHANGE</option>
                    <option value="WORKFLOW_STEP">WORKFLOW_STEP</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "11px", color: "#64748b", marginBottom: "2px" }}>Expected Status Code (Optional)</label>
                  <input
                    type="text"
                    value={expectedStatus}
                    onChange={(e) => setExpectedStatus(e.target.value)}
                    placeholder="e.g. 200, 400"
                    style={{ width: "100%", padding: "5px 8px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "12px" }}
                  />
                </div>
              </div>
            </div>

            {/* Action Buttons */}
            <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
              <button
                onClick={handleValidateRule}
                style={{
                  background: "#0284c7",
                  color: "#ffffff",
                  border: "none",
                  padding: "8px 16px",
                  borderRadius: "6px",
                  fontSize: "13px",
                  fontWeight: "600",
                  cursor: "pointer",
                }}
              >
                ✓ Validate Rule
              </button>
              <button
                onClick={handleSaveRule}
                style={{
                  background: "#16a34a",
                  color: "#ffffff",
                  border: "none",
                  padding: "8px 16px",
                  borderRadius: "6px",
                  fontSize: "13px",
                  fontWeight: "600",
                  cursor: "pointer",
                }}
              >
                💾 Save to Registry
              </button>
            </div>
          </div>

          {/* Registered Rules Catalog */}
          <div style={cardStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
              <h3 style={{ margin: 0, fontSize: "14px", fontWeight: "600", color: "#0f172a" }}>
                📚 Rule Registry ({rules.length} Registered)
              </h3>
              <button
                onClick={loadRules}
                style={{ background: "transparent", border: "1px solid #cbd5e1", padding: "4px 8px", borderRadius: "4px", fontSize: "11px", cursor: "pointer" }}
              >
                🔄 Refresh
              </button>
            </div>
            {loadingRules ? (
              <p style={{ fontSize: "12px", color: "#64748b" }}>Loading registry rules...</p>
            ) : rules.length === 0 ? (
              <p style={{ fontSize: "12px", color: "#94a3b8" }}>No rules registered yet in registry.</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "6px", maxHeight: "220px", overflowY: "auto" }}>
                {rules.map((r) => (
                  <div
                    key={r.rule_id}
                    onClick={() => {
                      setSelectedRuleId(r.rule_id);
                      setRuleId(r.rule_id);
                      setRuleName(r.name);
                      setRuleDescription(r.description || "");
                      if (r.condition) {
                        setConditionField(r.condition.field || "");
                        setConditionOperator(r.condition.operator || "EQ");
                        setConditionValue(String(r.condition.value || ""));
                      }
                      if (r.expected_behavior) {
                        setExpectedType(r.expected_behavior.type || "ACCEPT");
                      }
                    }}
                    style={{
                      padding: "8px 12px",
                      background: selectedRuleId === r.rule_id ? "#eff6ff" : "#f8fafc",
                      border: `1px solid ${selectedRuleId === r.rule_id ? "#3b82f6" : "#e2e8f0"}`,
                      borderRadius: "6px",
                      cursor: "pointer",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                    }}
                  >
                    <div>
                      <span style={{ fontWeight: "600", fontSize: "12px", color: "#1e293b" }}>{r.rule_id}: {r.name}</span>
                      <div style={{ fontSize: "11px", color: "#64748b" }}>
                        v{r.version} • {r.condition?.field} {r.condition?.operator} {String(r.condition?.value)} → {r.expected_behavior?.type}
                      </div>
                    </div>
                    <span style={badgeStyle("#f1f5f9", "#475569", "#cbd5e1")}>
                      {r.fingerprint ? r.fingerprint.slice(0, 8) : "valid"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Controlled Evaluation & Results */}
        <div>
          {/* Evaluation Trigger Card */}
          <div style={cardStyle}>
            <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: "600", color: "#0f172a" }}>
              ⚡ Execute Controlled Evaluation
            </h3>
            <p style={{ fontSize: "12px", color: "#64748b", margin: "0 0 12px 0" }}>
              Evaluates the configured rule set against recorded Phase 3 evidence and Phase 4 behavioral equivalence outcomes.
            </p>
            <div style={{ display: "flex", gap: "10px", alignItems: "center", marginBottom: "14px" }}>
              <div style={{ flex: 1 }}>
                <label style={{ display: "block", fontSize: "11px", color: "#64748b", marginBottom: "2px" }}>Evaluation / Run Scope ID</label>
                <input
                  type="text"
                  value={evaluationId}
                  onChange={(e) => setEvaluationId(e.target.value)}
                  placeholder="Awaiting authoritative execution ID..."
                  style={{ width: "100%", padding: "6px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>
              <button
                onClick={handleRunControlledEvaluation}
                disabled={evaluating}
                style={{
                  marginTop: "16px",
                  background: "#2563eb",
                  color: "#ffffff",
                  border: "none",
                  padding: "8px 20px",
                  borderRadius: "6px",
                  fontSize: "13px",
                  fontWeight: "600",
                  cursor: evaluating ? "not-allowed" : "pointer",
                }}
              >
                {evaluating ? "Evaluating..." : "Run Controlled Assessment"}
              </button>
            </div>
          </div>

          {/* Evaluation Results Card */}
          {evaluationResult && (
            <div style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
                <h3 style={{ margin: 0, fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                  📊 Controlled Assessment Report
                </h3>
                <div>{statusBadge(evaluationResult.overall_status)}</div>
              </div>

              {/* Summary Stats Grid */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "8px", marginBottom: "16px" }}>
                <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0", textAlign: "center" }}>
                  <div style={{ fontSize: "11px", color: "#64748b" }}>Total Rules</div>
                  <div style={{ fontSize: "18px", fontWeight: "700", color: "#0f172a" }}>{evaluationResult.summary?.total_rules || 0}</div>
                </div>
                <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0", textAlign: "center" }}>
                  <div style={{ fontSize: "11px", color: "#64748b" }}>Applicable</div>
                  <div style={{ fontSize: "18px", fontWeight: "700", color: "#0f172a" }}>{evaluationResult.summary?.applicable_rules || 0}</div>
                </div>
                <div style={{ background: "#f0fdf4", padding: "10px", borderRadius: "6px", border: "1px solid #bbf7d0", textAlign: "center" }}>
                  <div style={{ fontSize: "11px", color: "#166534" }}>Passed</div>
                  <div style={{ fontSize: "18px", fontWeight: "700", color: "#166534" }}>{evaluationResult.summary?.passed || 0}</div>
                </div>
                <div style={{ background: "#fef2f2", padding: "10px", borderRadius: "6px", border: "1px solid #fecaca", textAlign: "center" }}>
                  <div style={{ fontSize: "11px", color: "#991b1b" }}>Failed</div>
                  <div style={{ fontSize: "18px", fontWeight: "700", color: "#991b1b" }}>{evaluationResult.summary?.failed || 0}</div>
                </div>
              </div>

              {/* Metadata / Audit Hash */}
              <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0", marginBottom: "16px", fontSize: "11px" }}>
                <div style={{ color: "#64748b", marginBottom: "2px" }}>
                  <strong>Evaluation Fingerprint: </strong>
                  <code style={{ color: "#0f172a" }}>{evaluationResult.evaluation_fingerprint || "N/A"}</code>
                </div>
                <div style={{ color: "#64748b" }}>
                  <strong>Policy Hash: </strong>
                  <code style={{ color: "#0f172a" }}>{evaluationResult.policy_hash || "N/A"}</code>
                </div>
              </div>

              {/* Detailed Rule Assessments */}
              <h4 style={{ margin: "0 0 10px 0", fontSize: "13px", fontWeight: "600", color: "#334155" }}>
                Detailed Rule Assessments
              </h4>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                {(evaluationResult.assessments || []).map((ass, idx) => (
                  <div
                    key={ass.assessment_id || idx}
                    style={{
                      background: "#ffffff",
                      border: "1px solid #e2e8f0",
                      borderRadius: "6px",
                      padding: "12px",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                      <div>
                        <span style={{ fontWeight: "700", fontSize: "13px", color: "#0f172a" }}>Rule {ass.rule_id}</span>
                        <span style={{ fontSize: "11px", color: "#64748b", marginLeft: "8px" }}>v{ass.rule_version}</span>
                      </div>
                      <div style={{ display: "flex", gap: "6px" }}>
                        <span style={badgeStyle(ass.applicability === "APPLICABLE" ? "#eff6ff" : "#f8fafc", ass.applicability === "APPLICABLE" ? "#1d4ed8" : "#64748b", "#cbd5e1")}>
                          {ass.applicability}
                        </span>
                        {statusBadge(ass.rule_compliance)}
                      </div>
                    </div>

                    {/* Reference vs Target comparison */}
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "6px", fontSize: "12px", marginBottom: "8px" }}>
                      <div style={{ background: "#f8fafc", padding: "6px", borderRadius: "4px" }}>
                        <div style={{ fontSize: "10px", color: "#64748b" }}>Reference Result</div>
                        <div style={{ fontWeight: "600" }}>{ass.reference_result}</div>
                      </div>
                      <div style={{ background: "#f8fafc", padding: "6px", borderRadius: "4px" }}>
                        <div style={{ fontSize: "10px", color: "#64748b" }}>Target Result</div>
                        <div style={{ fontWeight: "600" }}>{ass.target_result}</div>
                      </div>
                      <div style={{ background: "#f8fafc", padding: "6px", borderRadius: "4px" }}>
                        <div style={{ fontSize: "10px", color: "#64748b" }}>Phase 4 Equivalence</div>
                        <div style={{ fontWeight: "600" }}>{ass.equivalence_result}</div>
                      </div>
                    </div>

                    {/* Explanation */}
                    <div style={{ fontSize: "12px", color: "#334155", background: "#f1f5f9", padding: "6px 10px", borderRadius: "4px" }}>
                      <strong>Audit Explanation: </strong> {ass.explanation}
                    </div>

                    {/* Evidence IDs */}
                    {ass.evidence_ids && ass.evidence_ids.length > 0 && (
                      <div style={{ marginTop: "6px", fontSize: "11px", color: "#64748b" }}>
                        Traceable Evidence: {ass.evidence_ids.join(", ")}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
