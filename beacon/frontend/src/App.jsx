import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

// Environment-based API Base URL with safe production & development defaults
const API_BASE = import.meta.env.VITE_API_BASE_URL || (import.meta.env.PROD ? "" : "http://localhost:8000");
const IS_DEV = import.meta.env.DEV;


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


const roleBadgeStyles = {
  SYSTEM_ADMIN: { bg: "#fdf4ff", border: "#c084fc", color: "#6b21a8", label: "👑 System Admin" },
  PROJECT_ADMIN: { bg: "#f0fdf4", border: "#4ade80", color: "#15803d", label: "🛡️ Project Admin" },
  CERTIFIER: { bg: "#eff6ff", border: "#60a5fa", color: "#1d4ed8", label: "⚡ Certifier" },
  AUDITOR: { bg: "#fff7ed", border: "#fb923c", color: "#c2410c", label: "📋 Auditor" },
  VIEWER: { bg: "#f8fafc", border: "#94a3b8", color: "#475569", label: "👁️ Viewer" },
};

const statusBadgeStyles = {
  CERTIFIED: { bg: "#ecfdf5", border: "#10b981", color: "#065f46", text: "CERTIFIED" },
  CERTIFIED_WITH_WARNINGS: { bg: "#fffbeb", border: "#f59e0b", color: "#92400e", text: "CERTIFIED WITH WARNINGS" },
  NOT_CERTIFIED: { bg: "#fef2f2", border: "#ef4444", color: "#991b1b", text: "NOT CERTIFIED" },
  REFERENCE_INCONSISTENT: { bg: "#f5f3ff", border: "#8b5cf6", color: "#5b21b6", text: "REFERENCE INCONSISTENT" },
  INSUFFICIENT_COVERAGE: { bg: "#fff7ed", border: "#f97316", color: "#9a3412", text: "INSUFFICIENT COVERAGE" },
  INCONCLUSIVE: { bg: "#fff7ed", border: "#f97316", color: "#9a3412", text: "INCONCLUSIVE" },
  ORACLE_SET_INVALID: { bg: "#fef2f2", border: "#dc2626", color: "#7f1d1d", text: "ORACLE SET INVALID" },
};

export default function App() {
  // =========================================================================
  // Phase 17: Authentication, RBAC & Multi-Tenant Security State
  // =========================================================================
  const [authToken, setAuthToken] = useState(() => sessionStorage.getItem("beacon_token") || null);
  const [currentUser, setCurrentUser] = useState(() => {
    try {
      const saved = sessionStorage.getItem("beacon_user");
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });
  const [loginModalOpen, setLoginModalOpen] = useState(false);
  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState(null);

  // Navigation Tabs
  const [activeTab, setActiveTab] = useState("benchmark"); // benchmark, history, audit, drift, loan_demo

  // Benchmark Catalog State with explicit Loading / Error / Empty States
  const [benchmarks, setBenchmarks] = useState([]);
  const [benchmarksLoadingState, setBenchmarksLoadingState] = useState("idle"); // idle, loading, success, error, empty

  // Step Workflow Configuration State
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

  // =========================================================================
  // Phase 14 Custom Dataset Certification State
  // =========================================================================
  const [customProjectId, setCustomProjectId] = useState("proj_retail_pilot");
  const [customDatasetName, setCustomDatasetName] = useState("Retail Custom Promo Dataset");
  const [customFormat, setCustomFormat] = useState("JSON");
  const [customProvenance, setCustomProvenance] = useState("USER_SUPPLIED");
  const [customVersion, setCustomVersion] = useState("1.0.0");
  const [customSourceRef, setCustomSourceRef] = useState("Enterprise Pilot Dataset v1");
  const [customDomain, setCustomDomain] = useState("Retail & Wholesale Commerce");
  const [customRawContent, setCustomRawContent] = useState(`[
  {"order_amount": 45.0, "customer_tier": "STANDARD", "items_count": 2, "coupon_code": "NONE", "is_express_shipping": false},
  {"order_amount": 120.0, "customer_tier": "STANDARD", "items_count": 4, "coupon_code": "WELCOME10", "is_express_shipping": false},
  {"order_amount": 75.0, "customer_tier": "VIP", "items_count": 3, "coupon_code": "NONE", "is_express_shipping": false},
  {"order_amount": 250.0, "customer_tier": "VIP", "items_count": 5, "coupon_code": "LOYALTY20", "is_express_shipping": true},
  {"order_amount": 15.0, "customer_tier": "WHOLESALE", "items_count": 1, "coupon_code": "NONE", "is_express_shipping": false}
]`);
  const [customPreview, setCustomPreview] = useState(null);
  const [customUploadedManifest, setCustomUploadedManifest] = useState(null);
  const [customLegacyAdapterId, setCustomLegacyAdapterId] = useState("retail_discount_legacy");
  const [customModernAdapterId, setCustomModernAdapterId] = useState("retail_discount_modern_clean");
  const [customOracleSetId, setCustomOracleSetId] = useState("SET-RETAIL-CONTROLLED-v1");
  const [customMode, setCustomMode] = useState("CONTROLLED");
  const [customProvider, setCustomProvider] = useState("auto");
  const [customAllowExternalLLM, setCustomAllowExternalLLM] = useState(false);
  const [customPreflight, setCustomPreflight] = useState(null);
  const [customActiveResult, setCustomActiveResult] = useState(null);
  const [customCryptographicProof, setCustomCryptographicProof] = useState(null);

  // =========================================================================
  // Phase 15 Evidence Dossier & Explainability State
  // =========================================================================
  const [dossierCertId, setDossierCertId] = useState("");
  const [dossierData, setDossierData] = useState(null);
  const [dossierExplanation, setDossierExplanation] = useState(null);
  const [dossierGraph, setDossierGraph] = useState([]);
  const [dossierNotes, setDossierNotes] = useState([]);
  const [newNoteAuthor, setNewNoteAuthor] = useState("Auditor");
  const [newNoteContent, setNewNoteContent] = useState("");
  const [dossierLoading, setDossierLoading] = useState(false);
  const [compareRunA, setCompareRunA] = useState("");
  const [compareRunB, setCompareRunB] = useState("");
  const [comparisonResult, setComparisonResult] = useState(null);
  const [comparingRuns, setComparingRuns] = useState(false);

  // =========================================================================
  // Phase 16: Operations, Health & Reliability State
  // =========================================================================
  const [operationsSummary, setOperationsSummary] = useState(null);
  const [operationsLoading, setOperationsLoading] = useState(false);
  const [operationsProjectFilter, setOperationsProjectFilter] = useState("");
  const [autoRefreshOperations, setAutoRefreshOperations] = useState(false);

  // Authenticated API client wrapper (uses native window.fetch)
  const authFetch = async (url, options = {}) => {
    const token = authToken || sessionStorage.getItem("beacon_token");
    const headers = { ...(options.headers || {}) };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await window.fetch(url, { ...options, headers });
    const reqId = res.headers.get("x-request-id") || res.headers.get("x-correlation-id");
    const reqSuffix = reqId ? ` (Reference ID: ${reqId})` : "";

    if (res.status === 401) {
      setAuthToken(null);
      setCurrentUser(null);
      sessionStorage.removeItem("beacon_token");
      sessionStorage.removeItem("beacon_user");
      setLoginModalOpen(true);
      setError(`Authentication required or session expired. Please sign in.${reqSuffix}`);
    } else if (res.status === 403) {
      const errData = await res.clone().json().catch(() => ({}));
      const msg = errData.detail || errData.message || "Access Denied (403): You do not have permission for this project or operation.";
      setError(`${msg}${reqSuffix}`);
    } else if (res.status >= 500) {
      const errData = await res.clone().json().catch(() => ({}));
      const msg = errData.message || errData.detail || "An unexpected server error occurred.";
      setError(`${msg}${reqSuffix}`);
    }
    return res;
  };

  const getCurrentRole = () => {
    if (!currentUser) return null;
    if (currentUser.is_system_admin) return "SYSTEM_ADMIN";
    const currentProj = activeTab === "custom" ? customProjectId : selectedBenchmarkId;
    const m = (currentUser.memberships || []).find(
      (mem) =>
        mem.project_id === currentProj ||
        mem.project_id === `benchmark_${currentProj}` ||
        (currentProj && currentProj.startsWith("benchmark_") && mem.project_id === currentProj.replace("benchmark_", ""))
    );
    return m ? m.role : "VIEWER";
  };

  const currentRole = getCurrentRole();

  const userHasPermission = (permission) => {
    if (!currentUser) return false;
    if (currentUser.is_system_admin) return true;
    const role = getCurrentRole();
    if (!role) return false;
    if (role === "SYSTEM_ADMIN" || role === "PROJECT_ADMIN") return true;
    if (role === "CERTIFIER") return permission === "VIEW" || permission === "CERTIFY";
    if (role === "AUDITOR") return permission === "VIEW" || permission === "AUDIT";
    if (role === "VIEWER") return permission === "VIEW";
    return false;
  };

  const quickLogin = async (username, password) => {
    setLoginBusy(true);
    setLoginError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Authentication failed.");
      }
      const data = await res.json();
      setAuthToken(data.access_token);
      setCurrentUser(data.user);
      sessionStorage.setItem("beacon_token", data.access_token);
      sessionStorage.setItem("beacon_user", JSON.stringify(data.user));
      setLoginModalOpen(false);
      setNotice(`Signed in as ${data.user.full_name} (${data.user.memberships?.[0]?.role || "SYSTEM_ADMIN"})`);
    } catch (err) {
      setLoginError(err.message);
    } finally {
      setLoginBusy(false);
    }
  };

  const handleLogout = async () => {
    if (authToken) {
      await fetch(`${API_BASE}/api/v1/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${authToken}` },
      }).catch(() => {});
    }
    setAuthToken(null);
    setCurrentUser(null);
    sessionStorage.removeItem("beacon_token");
    sessionStorage.removeItem("beacon_user");
    setNotice("You have signed out.");
  };

  const loadOperationsSummary = async () => {
    setOperationsLoading(true);
    try {
      const activeProj = operationsProjectFilter || (activeTab === "custom" ? customProjectId : (selectedBenchmarkId || "loan_demo"));
      const res = await authFetch(`${API_BASE}/api/v1/operations/summary?project_id=${encodeURIComponent(activeProj)}`);
      if (res.ok) {
        const data = await res.json();
        setOperationsSummary(data);
      }
    } catch (e) {
      console.error("Operations summary fetch error:", e);
    } finally {
      setOperationsLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === "operations") {
      loadOperationsSummary();
    }
  }, [activeTab, operationsProjectFilter, selectedBenchmarkId, customProjectId]);

  useEffect(() => {
    let interval = null;
    if (activeTab === "operations" && autoRefreshOperations) {
      interval = setInterval(() => {
        loadOperationsSummary();
      }, 3000);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [activeTab, autoRefreshOperations]);

  // Clear previous validation and active result whenever ANY certification-affecting config changes
  const invalidateValidationAndActiveState = () => {
    setBenchmarkValidation(null);
    setActiveResult(null);
    setCryptographicProof(null);
    setViewingHistoricalArtifact(null);
    setError(null);
    setNotice(null);
  };

  const invalidateCustomState = () => {
    setCustomPreflight(null);
    setCustomActiveResult(null);
    setCustomCryptographicProof(null);
    setError(null);
    setNotice(null);
  };

  // Phase 15: Evidence Dossier Loaders & Actions
  const loadDossier = async (certId) => {
    if (!certId) return;
    setDossierLoading(true);
    setDossierCertId(certId);
    try {
      const [dRes, eRes, gRes, nRes] = await Promise.all([
        authFetch(`${API_BASE}/api/v1/evidence/dossiers/${certId}`),
        authFetch(`${API_BASE}/api/v1/evidence/dossiers/${certId}/explain`),
        authFetch(`${API_BASE}/api/v1/evidence/dossiers/${certId}/graph`),
        authFetch(`${API_BASE}/api/v1/evidence/dossiers/${certId}/notes`),
      ]);
      if (dRes.ok) setDossierData(await dRes.json());
      if (eRes.ok) setDossierExplanation(await eRes.json());
      if (gRes.ok) {
        const gData = await gRes.json();
        setDossierGraph(gData.nodes || []);
      }
      if (nRes.ok) {
        const nData = await nRes.json();
        setDossierNotes(nData.notes || []);
      }
    } catch (e) {
      console.error("Failed to load dossier", e);
    } finally {
      setDossierLoading(false);
    }
  };

  const handleAddAuditorNote = async () => {
    if (!dossierCertId || !newNoteContent.trim()) return;
    try {
      const res = await authFetch(`${API_BASE}/api/v1/evidence/dossiers/${dossierCertId}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          author: newNoteAuthor.trim() || "Auditor",
          content: newNoteContent.trim(),
        }),
      });
      if (res.ok) {
        const note = await res.json();
        setDossierNotes((prev) => [...prev, note]);
        setNewNoteContent("");
        setNotice("Auditor note saved successfully (stored in isolated review layer).");
      }
    } catch (e) {
      setError("Failed to save auditor note: " + e.message);
    }
  };

  const handleCompareRuns = async () => {
    if (!compareRunA || !compareRunB) return;
    setComparingRuns(true);
    setError(null);
    try {
      const res = await authFetch(`${API_BASE}/api/v1/evidence/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id_a: compareRunA, run_id_b: compareRunB }),
      });
      if (res.ok) {
        setComparisonResult(await res.json());
      } else {
        const err = await res.json();
        setError(err.detail || "Comparison failed.");
      }
    } catch (e) {
      setError("Comparison request failed: " + e.message);
    } finally {
      setComparingRuns(false);
    }
  };

  const exportEvidenceDossier = async (certId, format) => {
    if (!certId) return;
    try {
      setBusy(true);
      const res = await authFetch(`${API_BASE}/api/v1/evidence/dossiers/${certId}/export?format=${format}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Evidence export failed.");
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `evidence_dossier_${certId}.${format === "markdown" ? "md" : format}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      setNotice(`Exported evidence dossier (${format.toUpperCase()}) successfully.`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // Phase 14: Dry-Run Preview
  const handlePreviewCustomDataset = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await authFetch(`${API_BASE}/api/v1/custom/datasets/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: customProjectId,
          dataset_name: customDatasetName,
          data_format: customFormat,
          raw_content: customRawContent,
          declared_provenance: customProvenance,
          dataset_version: customVersion,
          source_reference: customSourceRef,
          target_domain: customDomain,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Preview failed.");
      setCustomPreview(data);
      if (data.validation_passed) {
        setNotice(`Dataset Preview Valid: ${data.row_count} rows parsed (SHA-256: ${data.dataset_checksum.slice(0, 16)}...).`);
      } else {
        setError(`Dataset Preview Errors: ${data.errors?.join("; ")}`);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // Phase 14: Authoritative Ingestion & Manifest Registration
  const handleUploadCustomDataset = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    invalidateCustomState();
    try {
      const res = await authFetch(`${API_BASE}/api/v1/custom/datasets/upload`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: customProjectId,
          dataset_name: customDatasetName,
          data_format: customFormat,
          raw_content: customRawContent,
          declared_provenance: customProvenance,
          dataset_version: customVersion,
          source_reference: customSourceRef,
          target_domain: customDomain,
        }),
      });
      const manifest = await res.json();
      if (!res.ok) throw new Error(manifest.detail || "Upload failed.");
      setCustomUploadedManifest(manifest);
      setNotice(`Dataset Registered [${manifest.dataset_id}]: ${manifest.accepted_records} records verified.`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // Phase 14: Custom Pre-Flight Validation
  const handleValidateCustomCertification = async () => {
    if (!customUploadedManifest) {
      setError("Please register or upload a dataset first.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await authFetch(`${API_BASE}/api/v1/custom/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: customProjectId,
          dataset_id: customUploadedManifest.dataset_id,
          legacy_adapter_id: customLegacyAdapterId,
          modernized_adapter_id: customModernAdapterId,
          oracle_set_id: customOracleSetId,
          evaluation_mode: customMode,
          preferred_provider: customProvider,
          allow_external_llm: customAllowExternalLLM,
        }),
      });
      const data = await res.json();
      setCustomPreflight(data);
      if (data.is_valid) {
        setNotice(`Custom Pre-Flight Passed: Verified ${data.total_input_count} inputs and adapters.`);
      } else {
        setError(`Custom Pre-Flight Failed: ${data.errors?.join("; ") || "Validation errors."}`);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // Phase 14: Run Custom Certification
  const handleRunCustomCertification = async () => {
    if (!customPreflight || !customPreflight.is_valid) {
      setError("Cannot certify: Run and pass Custom Pre-Flight validation first.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    setCustomCryptographicProof(null);
    try {
      const res = await authFetch(`${API_BASE}/api/v1/custom/certify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: customProjectId,
          dataset_id: customUploadedManifest.dataset_id,
          legacy_adapter_id: customLegacyAdapterId,
          modernized_adapter_id: customModernAdapterId,
          oracle_set_id: customOracleSetId,
          evaluation_mode: customMode,
          preferred_provider: customProvider,
          allow_external_llm: customAllowExternalLLM,
          config_fingerprint: customPreflight.config_fingerprint,
        }),
      });
      const artifact = await res.json();
      if (!res.ok) {
        if (res.status === 409) {
          setCustomPreflight(null);
          throw new Error("Custom certification pre-flight is stale. Please re-run pre-flight validation.");
        }
        throw new Error(artifact.detail || "Custom certification failed.");
      }
      setCustomActiveResult(artifact);
      const isPass = artifact.status === "CERTIFIED" || artifact.status === "CERTIFIED_WITH_WARNINGS";
      setNotice(
        isPass
          ? `CUSTOM CERTIFIED: Equivalence established for ${customDatasetName}.`
          : `NOT CERTIFIED: Behavioral regressions detected for ${customDatasetName}.`
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // Phase 14: Custom 8-Point Cryptographic Verification
  const handleVerifyCustomIntegrity = async (certId) => {
    if (!certId) return;
    try {
      const res = await authFetch(`${API_BASE}/api/v1/certification/${certId}/verify`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setCustomCryptographicProof(data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Load Benchmarks with Explicit Success / Error / Empty Handling
  const loadBenchmarks = async () => {
    setBenchmarksLoadingState("loading");
    setError(null);
    try {
      const res = await authFetch(`${API_BASE}/api/v1/benchmarks`);
      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status}`);
      }
      const data = await res.json();
      const list = data.benchmarks || [];
      if (list.length === 0) {
        setBenchmarks([]);
        setBenchmarksLoadingState("empty");
      } else {
        setBenchmarks(list);
        setBenchmarksLoadingState("success");
        // Ensure selected benchmark is valid
        if (!list.some((b) => b.benchmark_id === selectedBenchmarkId)) {
          setSelectedBenchmarkId(list[0].benchmark_id);
          const spec = list[0];
          if (spec.modernized_adapters && Object.keys(spec.modernized_adapters).length > 0) {
            setSelectedVariant(Object.keys(spec.modernized_adapters)[0]);
          }
        }
      }
    } catch (err) {
      setBenchmarksLoadingState("error");
      setError(`BEACON backend unavailable (${err.message}). Start the API server and retry.`);
    }
  };

  // Load Historical Artifacts Filtered by Benchmark
  const loadHistoricalArtifacts = async (benchmarkId) => {
    try {
      const url = benchmarkId
        ? `${API_BASE}/api/v1/certification/artifacts?benchmark_id=${benchmarkId}`
        : `${API_BASE}/api/v1/certification/artifacts`;
      const res = await authFetch(url);
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
      const res = await authFetch(url);
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
        authFetch(`${API_BASE}/runs?project_id=loan_demo`),
        authFetch(`${API_BASE}/demo/invariants?project_id=loan_demo`),
        authFetch(`${API_BASE}/drift?benchmark_id=loan_demo&project_id=loan_demo`),
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
    loadBenchmarks();
    loadHistoricalArtifacts(selectedBenchmarkId);
    loadDrift(selectedBenchmarkId);
  }, []);

  // Handlers for Configuration Changes (Strict Invalidation Flow)
  const handleBenchmarkChange = (newBenchmarkId) => {
    setSelectedBenchmarkId(newBenchmarkId);
    invalidateValidationAndActiveState();

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
    invalidateValidationAndActiveState();
  };

  const handleProviderChange = (newProvider) => {
    setPreferredProvider(newProvider);
    invalidateValidationAndActiveState();
  };

  const handleVariantChange = (newVariant) => {
    setSelectedVariant(newVariant);
    invalidateValidationAndActiveState();
  };

  // Check if current validation corresponds to the exact active configuration
  const isValidationCurrent =
    benchmarkValidation?.is_valid === true &&
    benchmarkValidation?.benchmark_id === selectedBenchmarkId &&
    benchmarkValidation?.evaluation_mode === discoveryMode &&
    benchmarkValidation?.target_variant === selectedVariant &&
    benchmarkValidation?.preferred_provider === preferredProvider;

  // Load Cases when Active Result or Historical Artifact Changes
  const targetArtifact = viewingHistoricalArtifact || activeResult;
  useEffect(() => {
    if (targetArtifact?.certification_id) {
      authFetch(`${API_BASE}/api/v1/certification/${targetArtifact.certification_id}/cases?classification=${caseFilter}`)
        .then((res) => res.json())
        .then((data) => setActiveCases(data.cases || []))
        .catch(console.error);
    } else {
      setActiveCases([]);
    }
  }, [targetArtifact, caseFilter]);

  // Step 6: Pre-Flight Validation Action (Sends Complete Configuration)
  const validateBenchmark = async () => {
    if (!selectedBenchmarkId) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await authFetch(`${API_BASE}/api/v1/benchmarks/${selectedBenchmarkId}/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          benchmark_id: selectedBenchmarkId,
          evaluation_mode: discoveryMode,
          target_variant: selectedVariant,
          preferred_provider: preferredProvider,
          dataset_name: "default",
        }),
      });
      const data = await res.json();
      setBenchmarkValidation(data);
      if (data.is_valid) {
        const cs = data.dataset_checksum ? ` (SHA-256: ${data.dataset_checksum.slice(0, 16)}...)` : "";
        setNotice(
          `Pre-flight validation passed for [${selectedBenchmarkId} • ${discoveryMode} • ${selectedVariant}]: ${data.dataset_record_count} dataset inputs verified${cs}. Ready to certify.`
        );
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
    if (!isValidationCurrent) {
      setError("Cannot run certification: Pre-flight validation is missing or stale for the current configuration.");
      return;
    }

    setBusy(true);
    setError(null);
    setNotice(null);
    setCryptographicProof(null);
    setViewingHistoricalArtifact(null);

    try {
      const res = await authFetch(`${API_BASE}/api/v1/certification/run`, {
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
      const res = await authFetch(`${API_BASE}/api/v1/certification/${certId}/verify`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setCryptographicProof(data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Export Certification Dossier (JSON / Markdown / CSV)
  const exportDossier = async (certId, format) => {
    if (!certId) return;
    try {
      setBusy(true);
      const res = await authFetch(`${API_BASE}/api/v1/certification/${certId}/export?format=${format}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Certification export failed.");
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `certification_${certId}.${format === "markdown" ? "md" : format}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      setNotice(`Exported certification artifact (${format.toUpperCase()}) successfully.`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // Run Legacy Loan Demo (isolated)
  const runLoanDemo = async (implementation) => {
    setBusy(true);
    setError(null);
    try {
      const res = await authFetch(`${API_BASE}/demo/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ implementation, project_id: "loan_demo" }),
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
      <header style={{ background: "#0f172a", color: "#f8fafc", padding: "14px 28px", borderBottom: "1px solid #1e293b" }}>
        <div style={{ maxWidth: "1440px", margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <span style={{ fontSize: "24px" }}>🛡️</span>
            <div>
              <h1 style={{ margin: 0, fontSize: "19px", fontWeight: "700", letterSpacing: "-0.5px" }}>BEACON</h1>
              <p style={{ margin: 0, fontSize: "11px", color: "#94a3b8" }}>
                Behavioral Equivalence Assurance & Cryptographic Oracle Notarization
              </p>
            </div>
          </div>

          {/* Phase 17 Role Switcher & User Identity Bar */}
          <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
            {currentUser ? (
              <div style={{ display: "flex", alignItems: "center", gap: "10px", background: "#1e293b", padding: "6px 12px", borderRadius: "10px", border: "1px solid #334155" }}>
                <span style={{ fontSize: "13px", fontWeight: "600", color: "#f1f5f9" }}>
                  👤 {currentUser.full_name || currentUser.username}
                </span>
                <span style={badgeStyle(
                  roleBadgeStyles[currentRole]?.bg || "#f1f5f9",
                  roleBadgeStyles[currentRole]?.color || "#0f172a",
                  roleBadgeStyles[currentRole]?.border || "#cbd5e1"
                )}>
                  {roleBadgeStyles[currentRole]?.label || currentRole}
                </span>

                {/* Quick Role Switcher Buttons (Development Only) */}
                {IS_DEV && (
                  <div style={{ display: "flex", gap: "4px", marginLeft: "6px", borderLeft: "1px solid #475569", paddingLeft: "8px" }}>
                    <button
                      onClick={() => quickLogin("admin", "BeaconAdmin2026!")}
                      title="Switch to System Admin"
                      style={{
                        background: currentUser?.is_system_admin ? "#9333ea" : "#334155",
                        color: "#ffffff",
                        border: "none",
                        padding: "3px 7px",
                        borderRadius: "4px",
                        fontSize: "11px",
                        fontWeight: "600",
                        cursor: "pointer",
                      }}
                    >
                      👑 Admin
                    </button>
                    <button
                      onClick={() => quickLogin("alice_certifier", "AliceCert2026!")}
                      title="Switch to Certifier (Alice)"
                      style={{
                        background: currentRole === "CERTIFIER" && !currentUser?.is_system_admin ? "#2563eb" : "#334155",
                        color: "#ffffff",
                        border: "none",
                        padding: "3px 7px",
                        borderRadius: "4px",
                        fontSize: "11px",
                        fontWeight: "600",
                        cursor: "pointer",
                      }}
                    >
                      ⚡ Certifier
                    </button>
                    <button
                      onClick={() => quickLogin("bob_viewer", "BobView2026!")}
                      title="Switch to Viewer (Bob)"
                      style={{
                        background: currentRole === "VIEWER" && !currentUser?.is_system_admin ? "#2563eb" : "#334155",
                        color: "#ffffff",
                        border: "none",
                        padding: "3px 7px",
                        borderRadius: "4px",
                        fontSize: "11px",
                        fontWeight: "600",
                        cursor: "pointer",
                      }}
                    >
                      👁️ Viewer
                    </button>
                    <button
                      onClick={() => quickLogin("carol_auditor", "CarolAudit2026!")}
                      title="Switch to Auditor (Carol)"
                      style={{
                        background: currentRole === "AUDITOR" && !currentUser?.is_system_admin ? "#2563eb" : "#334155",
                        color: "#ffffff",
                        border: "none",
                        padding: "3px 7px",
                        borderRadius: "4px",
                        fontSize: "11px",
                        fontWeight: "600",
                        cursor: "pointer",
                      }}
                    >
                      📋 Auditor
                    </button>
                    <button
                      onClick={() => quickLogin("dave_admin", "DaveAdmin2026!")}
                      title="Switch to Project Admin (Dave)"
                      style={{
                        background: currentRole === "PROJECT_ADMIN" && !currentUser?.is_system_admin ? "#2563eb" : "#334155",
                        color: "#ffffff",
                        border: "none",
                        padding: "3px 7px",
                        borderRadius: "4px",
                        fontSize: "11px",
                        fontWeight: "600",
                        cursor: "pointer",
                      }}
                    >
                      🛡️ Dave
                    </button>
                  </div>
                )}

                <button
                  onClick={handleLogout}
                  style={{
                    background: "transparent",
                    color: "#ef4444",
                    border: "1px solid #7f1d1d",
                    padding: "3px 8px",
                    borderRadius: "6px",
                    fontSize: "11px",
                    fontWeight: "600",
                    cursor: "pointer",
                    marginLeft: "4px",
                  }}
                >
                  Sign Out
                </button>
              </div>
            ) : (
              <button
                onClick={() => setLoginModalOpen(true)}
                style={{
                  background: "#2563eb",
                  color: "#ffffff",
                  border: "none",
                  padding: "6px 14px",
                  borderRadius: "8px",
                  fontSize: "13px",
                  fontWeight: "600",
                  cursor: "pointer",
                }}
              >
                🔐 Sign In / Change Role
              </button>
            )}

            <div style={{ display: "flex", gap: "6px" }}>
              <span style={badgeStyle("#1e293b", "#38bdf8", "#334155")}>Phase 17 RBAC</span>
              <span style={badgeStyle("#1e293b", "#a7f3d0", "#334155")}>Multi-Tenant</span>
            </div>
          </div>
        </div>
      </header>

      {/* Main Navigation Bar */}
      <nav style={{ background: "#ffffff", borderBottom: "1px solid #e2e8f0", padding: "0 28px" }}>
        <div style={{ maxWidth: "1440px", margin: "0 auto", display: "flex", gap: "24px" }}>
          {[
            { id: "benchmark", label: "🎯 Benchmark Certification", desc: "Select & Certify Applications" },
            { id: "custom", label: "📥 Custom Certification", desc: "User-Supplied Datasets & Ingestion" },
            { id: "dossier", label: "📑 Evidence Dossier", desc: "Explainability & Traceability" },
            { id: "operations", label: "⚙️ Operations & Reliability", desc: "System Health, Metrics & Jobs" },
            { id: "history", label: "📜 Certification History", desc: "Benchmark Runs & Fingerprints" },
            { id: "audit", label: "🔒 Audit Trail & Proofs", desc: "Cryptographic Verification" },
            { id: "drift", label: "📈 Drift Monitoring", desc: "Post-Migration Live Drift" },
            { id: "loan_demo", label: "🧪 Legacy Loan Demo Sandbox", desc: "Isolated Demonstration" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => {
                setActiveTab(tab.id);
                if (tab.id === "operations") loadOperationsSummary();
                if (tab.id === "loan_demo" && loanRuns.length === 0) loadLoanDemoData();
                if (tab.id === "dossier" && !dossierData) {
                  const targetId = activeResult?.certification_id || customActiveResult?.certification_id || (historicalArtifacts.length > 0 ? historicalArtifacts[0].certification_id : "");
                  if (targetId) loadDossier(targetId);
                }
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
                {isValidationCurrent ? (
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
                    disabled={busy || benchmarksLoadingState !== "success"}
                    style={{
                      background: "#f1f5f9",
                      color: "#334155",
                      border: "1px solid #cbd5e1",
                      padding: "8px 16px",
                      borderRadius: "6px",
                      fontWeight: "600",
                      fontSize: "13px",
                      cursor: busy || benchmarksLoadingState !== "success" ? "not-allowed" : "pointer",
                    }}
                  >
                    {busy ? "Validating..." : "Step 6: 🔍 Pre-Flight Validate"}
                  </button>
                  <button
                    onClick={runBenchmarkCertification}
                    disabled={busy || !isValidationCurrent}
                    title={!isValidationCurrent ? "Pre-flight validation required for current configuration" : "Run equivalence certification"}
                    style={{
                      background: isValidationCurrent ? "#2563eb" : "#94a3b8",
                      color: "#ffffff",
                      border: "none",
                      padding: "8px 20px",
                      borderRadius: "6px",
                      fontWeight: "600",
                      fontSize: "13px",
                      cursor: busy || !isValidationCurrent ? "not-allowed" : "pointer",
                      boxShadow: isValidationCurrent ? "0 1px 2px rgba(37,99,235,0.2)" : "none",
                    }}
                  >
                    {busy ? "Executing Certification..." : "Step 7: ⚡ Run Equivalence Certification"}
                  </button>
                </div>
              </div>

              {/* Grid of Steps 1 to 5 Controls */}
              <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 1.2fr 1fr", gap: "14px" }}>
                {/* Step 1: Benchmark Selector with Explicit Error / Loading / Empty UI */}
                <div>
                  <label style={{ display: "block", fontSize: "13px", fontWeight: "600", color: "#334155", marginBottom: "6px" }}>
                    Step 1 — Select Benchmark
                  </label>
                  {benchmarksLoadingState === "loading" && (
                    <div style={{ padding: "9px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", background: "#f8fafc", fontSize: "13px", color: "#64748b" }}>
                      ⏳ Loading benchmark catalog...
                    </div>
                  )}
                  {benchmarksLoadingState === "error" && (
                    <div style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #fca5a5", background: "#fef2f2", fontSize: "12px", color: "#991b1b", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span>⚠️ API Unavailable</span>
                      <button onClick={loadBenchmarks} style={{ background: "#dc2626", color: "#ffffff", border: "none", padding: "3px 8px", borderRadius: "4px", fontSize: "11px", cursor: "pointer", fontWeight: "600" }}>
                        🔄 Retry
                      </button>
                    </div>
                  )}
                  {benchmarksLoadingState === "empty" && (
                    <div style={{ padding: "9px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", background: "#f8fafc", fontSize: "13px", color: "#64748b" }}>
                      No benchmarks registered in catalog.
                    </div>
                  )}
                  {benchmarksLoadingState === "success" && (
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
                  )}
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
                    onChange={(e) => handleProviderChange(e.target.value)}
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
                      Verified Dataset Inputs: <strong>{benchmarkValidation.dataset_record_count}</strong> | Legacy Adapter: <strong>{benchmarkValidation.legacy_adapter_status || "OK"}</strong> | Target Adapter: <strong>{benchmarkValidation.target_variant_adapter_status || "OK"}</strong>
                    </span>
                  </div>
                  {benchmarkValidation.config_fingerprint && (
                    <div style={{ fontSize: "11px", color: "#166534", marginTop: "4px", fontFamily: "monospace" }}>
                      Config Fingerprint: {benchmarkValidation.config_fingerprint}
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
                          : targetArtifact.status === "INCONCLUSIVE"
                          ? "INCONCLUSIVE: Inconclusive Equivalence Result Under Current Policy"
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
                      onClick={() => {
                        loadDossier(targetArtifact.certification_id);
                        setActiveTab("dossier");
                      }}
                      style={{ background: "#0f172a", color: "#ffffff", border: "none", padding: "6px 14px", borderRadius: "6px", fontWeight: "600", fontSize: "12px", cursor: "pointer" }}
                    >
                      📑 Inspect Evidence Dossier
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
                    {targetArtifact.status === "INCONCLUSIVE" && (
                      <>Certification outcome is inconclusive under the current policy and evaluated probe evidence.</>
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
                  Selected Configuration: <strong>{discoveryMode}</strong> mode with <strong>{selectedVariant}</strong> ({preferredProvider}).
                  Run Step 6 Pre-Flight Validation to verify dataset inputs and adapter bindings before executing certification.
                </p>
                <div style={{ display: "flex", justifyContent: "center", gap: "12px" }}>
                  <button
                    onClick={validateBenchmark}
                    disabled={busy || benchmarksLoadingState !== "success"}
                    style={{
                      background: "#f1f5f9",
                      color: "#334155",
                      border: "1px solid #cbd5e1",
                      padding: "10px 20px",
                      borderRadius: "6px",
                      fontWeight: "600",
                      fontSize: "14px",
                      cursor: busy || benchmarksLoadingState !== "success" ? "not-allowed" : "pointer",
                    }}
                  >
                    Step 6: 🔍 Pre-Flight Validate
                  </button>
                  <button
                    onClick={runBenchmarkCertification}
                    disabled={busy || !isValidationCurrent}
                    title={!isValidationCurrent ? "Pre-flight validation required for current configuration" : "Run equivalence certification"}
                    style={{
                      background: isValidationCurrent ? "#2563eb" : "#94a3b8",
                      color: "#ffffff",
                      border: "none",
                      padding: "10px 24px",
                      borderRadius: "6px",
                      fontWeight: "600",
                      fontSize: "14px",
                      cursor: busy || !isValidationCurrent ? "not-allowed" : "pointer",
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
        {/* TAB: CUSTOM / USER-SUPPLIED DATASET CERTIFICATION WORKFLOW (PHASE 14)      */}
        {/* ========================================================================= */}
        {activeTab === "custom" && (
          <div>
            {/* Custom Certification Status & Privacy Banner */}
            <div style={{ background: "#ffffff", border: "1px solid #cbd5e1", borderRadius: "10px", padding: "14px 20px", marginBottom: "20px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <h2 style={{ margin: 0, fontSize: "16px", fontWeight: "700", color: "#0f172a" }}>
                  📥 Custom & User-Supplied Dataset Certification
                </h2>
                <p style={{ margin: "2px 0 0", fontSize: "13px", color: "#64748b" }}>
                  Ingest custom enterprise or public datasets, validate schemas, bind allowlisted adapters, enforce privacy gates, and certify equivalence with the authoritative CertificationEngine.
                </p>
              </div>
              <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                <span style={badgeStyle("#eff6ff", "#1e40af", "#bfdbfe")}>Namespace: {customProjectId}</span>
                <span style={badgeStyle(customAllowExternalLLM ? "#fef3c7" : "#ecfdf5", customAllowExternalLLM ? "#92400e" : "#065f46", customAllowExternalLLM ? "#fde68a" : "#a7f3d0")}>
                  {customAllowExternalLLM ? "🌐 Cloud LLM Allowed" : "🔒 Local Processing Only"}
                </span>
                <span style={badgeStyle("#f8fafc", "#475569", "#cbd5e1")}>Mode: {customMode}</span>
              </div>
            </div>

            {/* Step 1: Dataset Specification & Provenance Declaration */}
            <div style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #e2e8f0", paddingBottom: "10px", marginBottom: "16px" }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                    Step 1: Dataset Ingestion & Truthful Provenance
                  </h3>
                  <p style={{ margin: "2px 0 0", fontSize: "12px", color: "#64748b" }}>
                    Provide structured records (JSON, JSONL, or CSV) with explicit provenance declaration.
                  </p>
                </div>
                {/* Sample Preset Loaders */}
                <div style={{ display: "flex", gap: "8px" }}>
                  <button
                    onClick={() => {
                      setCustomDatasetName("Retail Custom Pricing Invariants");
                      setCustomFormat("JSON");
                      setCustomDomain("Retail E-Commerce");
                      setCustomProvenance("USER_SUPPLIED");
                      setCustomLegacyAdapterId("retail_discount_legacy");
                      setCustomModernAdapterId("retail_discount_modern_clean");
                      setCustomRawContent(`[
  {"order_amount": 45.0, "customer_tier": "STANDARD", "items_count": 2, "coupon_code": "NONE", "is_express_shipping": false},
  {"order_amount": 120.0, "customer_tier": "STANDARD", "items_count": 4, "coupon_code": "WELCOME10", "is_express_shipping": false},
  {"order_amount": 75.0, "customer_tier": "VIP", "items_count": 3, "coupon_code": "NONE", "is_express_shipping": false},
  {"order_amount": 250.0, "customer_tier": "VIP", "items_count": 5, "coupon_code": "LOYALTY20", "is_express_shipping": true},
  {"order_amount": 15.0, "customer_tier": "WHOLESALE", "items_count": 1, "coupon_code": "NONE", "is_express_shipping": false}
]`);
                      invalidateCustomState();
                    }}
                    style={{ background: "#f8fafc", border: "1px solid #cbd5e1", padding: "4px 10px", borderRadius: "4px", fontSize: "12px", cursor: "pointer", fontWeight: "600" }}
                  >
                    Load Retail Preset
                  </button>
                  <button
                    onClick={() => {
                      setCustomDatasetName("Loan Underwriting Custom Test Inputs");
                      setCustomFormat("JSON");
                      setCustomDomain("Financial Services & Underwriting");
                      setCustomProvenance("PRIVATE_ENTERPRISE");
                      setCustomLegacyAdapterId("loan_approval_legacy");
                      setCustomModernAdapterId("loan_approval_modern_equiv");
                      setCustomRawContent(`[
  {"credit_score": 750, "debt_ratio": 0.25, "annual_income": 85000},
  {"credit_score": 580, "debt_ratio": 0.45, "annual_income": 42000},
  {"credit_score": 810, "debt_ratio": 0.15, "annual_income": 120000},
  {"credit_score": 640, "debt_ratio": 0.35, "annual_income": 55000}
]`);
                      invalidateCustomState();
                    }}
                    style={{ background: "#f8fafc", border: "1px solid #cbd5e1", padding: "4px 10px", borderRadius: "4px", fontSize: "12px", cursor: "pointer", fontWeight: "600" }}
                  >
                    Load Loan Preset
                  </button>
                </div>
              </div>

              {/* Metadata Inputs */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: "14px", marginBottom: "16px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>Project ID</label>
                  <input
                    type="text"
                    value={customProjectId}
                    onChange={(e) => { setCustomProjectId(e.target.value); invalidateCustomState(); }}
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>Dataset Name</label>
                  <input
                    type="text"
                    value={customDatasetName}
                    onChange={(e) => { setCustomDatasetName(e.target.value); invalidateCustomState(); }}
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>Data Format</label>
                  <select
                    value={customFormat}
                    onChange={(e) => { setCustomFormat(e.target.value); invalidateCustomState(); }}
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", background: "#ffffff" }}
                  >
                    <option value="JSON">JSON (Array of objects)</option>
                    <option value="JSONL">JSONL (Newline-delimited JSON)</option>
                    <option value="CSV">CSV (Header-delimited values)</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>Declared Provenance</label>
                  <select
                    value={customProvenance}
                    onChange={(e) => { setCustomProvenance(e.target.value); invalidateCustomState(); }}
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", background: "#ffffff" }}
                  >
                    <option value="USER_SUPPLIED">USER_SUPPLIED (Direct user input)</option>
                    <option value="PUBLIC_EXTERNAL">PUBLIC_EXTERNAL (Public dataset source)</option>
                    <option value="PRIVATE_ENTERPRISE">PRIVATE_ENTERPRISE (Proprietary data)</option>
                    <option value="REALISTIC_SYNTHETIC">REALISTIC_SYNTHETIC (Synthetic distribution)</option>
                    <option value="BENCHMARK_DERIVED">BENCHMARK_DERIVED (Derived subset)</option>
                  </select>
                </div>
              </div>

              {/* Raw Content Area */}
              <div style={{ marginBottom: "16px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                  <label style={{ fontSize: "12px", fontWeight: "600", color: "#475569" }}>Dataset Content ({customFormat})</label>
                  <span style={{ fontSize: "11px", color: "#94a3b8" }}>{customRawContent.length} chars • Max 10MB</span>
                </div>
                <textarea
                  rows={7}
                  value={customRawContent}
                  onChange={(e) => { setCustomRawContent(e.target.value); invalidateCustomState(); }}
                  placeholder="Paste JSON array, JSONL, or CSV data here..."
                  style={{ width: "100%", padding: "10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontFamily: "monospace", fontSize: "12px", boxSizing: "border-box" }}
                />
              </div>

              {/* Preview & Register Action Buttons */}
              <div style={{ display: "flex", gap: "10px" }}>
                <button
                  onClick={handlePreviewCustomDataset}
                  disabled={busy}
                  style={{ background: "#f1f5f9", color: "#1e293b", border: "1px solid #cbd5e1", padding: "8px 16px", borderRadius: "6px", fontWeight: "600", fontSize: "13px", cursor: "pointer" }}
                >
                  🔍 Step 2: Validate & Preview (Dry-Run)
                </button>
                <button
                  onClick={handleUploadCustomDataset}
                  disabled={busy}
                  style={{ background: "#059669", color: "#ffffff", border: "none", padding: "8px 18px", borderRadius: "6px", fontWeight: "600", fontSize: "13px", cursor: "pointer" }}
                >
                  💾 Step 3: Register & Manifest Dataset
                </button>
              </div>
            </div>

            {/* Step 2 Preview Card */}
            {customPreview && (
              <div style={cardStyle}>
                <h3 style={{ margin: "0 0 10px", fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
                  📊 Dataset Dry-Run Preview Summary
                </h3>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px", marginBottom: "14px" }}>
                  <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                    <div style={{ fontSize: "11px", color: "#64748b" }}>Parsed Rows</div>
                    <div style={{ fontSize: "16px", fontWeight: "700", color: "#0f172a" }}>{customPreview.row_count}</div>
                  </div>
                  <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                    <div style={{ fontSize: "11px", color: "#64748b" }}>Validation Outcome</div>
                    <div style={{ fontSize: "13px", fontWeight: "700", color: customPreview.validation_passed ? "#059669" : "#dc2626" }}>
                      {customPreview.validation_passed ? "VALID" : "INVALID"}
                    </div>
                  </div>
                  <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                    <div style={{ fontSize: "11px", color: "#64748b" }}>Dataset SHA-256</div>
                    <div style={{ fontSize: "11px", fontFamily: "monospace", color: "#0f172a" }}>{customPreview.dataset_checksum ? `${customPreview.dataset_checksum.slice(0, 16)}...` : "N/A"}</div>
                  </div>
                  <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                    <div style={{ fontSize: "11px", color: "#64748b" }}>Schema Fingerprint</div>
                    <div style={{ fontSize: "11px", fontFamily: "monospace", color: "#0f172a" }}>{customPreview.schema_fingerprint ? `${customPreview.schema_fingerprint.slice(0, 16)}...` : "N/A"}</div>
                  </div>
                </div>

                {/* Inferred Schema Fields */}
                <div style={{ marginBottom: "12px" }}>
                  <div style={{ fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "6px" }}>Inferred Schema Fields:</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                    {Object.entries(customPreview.inferred_schema || {}).map(([col, typ]) => (
                      <span key={col} style={{ background: "#f1f5f9", padding: "3px 8px", borderRadius: "4px", fontSize: "11px", fontFamily: "monospace" }}>
                        <strong>{col}</strong>: <span style={{ color: "#2563eb" }}>{typ}</span>
                      </span>
                    ))}
                  </div>
                </div>

                {/* Sample Records Table */}
                {customPreview.sample_records && customPreview.sample_records.length > 0 && (
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                      <thead>
                        <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
                          <th style={{ padding: "6px 8px", textAlign: "left" }}>#</th>
                          {Object.keys(customPreview.sample_records[0]).map((k) => (
                            <th key={k} style={{ padding: "6px 8px", textAlign: "left" }}>{k}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {customPreview.sample_records.map((row, idx) => (
                          <tr key={idx} style={{ borderBottom: "1px solid #f1f5f9" }}>
                            <td style={{ padding: "6px 8px", color: "#94a3b8" }}>{idx + 1}</td>
                            {Object.values(row).map((val, cidx) => (
                              <td key={cidx} style={{ padding: "6px 8px", fontFamily: "monospace" }}>{JSON.stringify(val)}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Step 3: Implementation Adapter Binding & Privacy Settings */}
            <div style={cardStyle}>
              <h3 style={{ margin: "0 0 10px", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                Step 4: Implementation Binding & Privacy Boundary
              </h3>
              <p style={{ margin: "0 0 14px", fontSize: "12px", color: "#64748b" }}>
                Select registered allowlisted adapters and configure the privacy boundary for cloud LLM evaluation.
              </p>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr", gap: "12px", marginBottom: "16px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>Legacy Implementation Adapter</label>
                  <select
                    value={customLegacyAdapterId}
                    onChange={(e) => { setCustomLegacyAdapterId(e.target.value); invalidateCustomState(); }}
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", background: "#ffffff" }}
                  >
                    <option value="retail_discount_legacy">retail_discount_legacy (v1.0.0)</option>
                    <option value="loan_approval_legacy">loan_approval_legacy (v1.0.0)</option>
                    <option value="payroll_tax_legacy">payroll_tax_legacy (v1.0.0)</option>
                    <option value="medical_triage_legacy">medical_triage_legacy (v1.0.0)</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>Modernized Implementation Variant</label>
                  <select
                    value={customModernAdapterId}
                    onChange={(e) => { setCustomModernAdapterId(e.target.value); invalidateCustomState(); }}
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", background: "#ffffff" }}
                  >
                    <option value="retail_discount_modern_clean">retail_discount_modern_clean (v2.0.0 Clean)</option>
                    <option value="retail_discount_modern_buggy_threshold">retail_discount_modern_buggy_threshold (v2.0.0 Buggy)</option>
                    <option value="loan_approval_modern_equiv">loan_approval_modern_equiv (v2.0.0 Clean)</option>
                    <option value="loan_approval_modern_buggy">loan_approval_modern_buggy (v2.0.0 Buggy)</option>
                    <option value="payroll_tax_modern_clean">payroll_tax_modern_clean (v2.0.0 Clean)</option>
                    <option value="payroll_tax_modern_buggy_bracket">payroll_tax_modern_buggy_bracket (v2.0.0 Buggy)</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>Explicit OracleSet Binding</label>
                  <select
                    value={customOracleSetId}
                    onChange={(e) => { setCustomOracleSetId(e.target.value); invalidateCustomState(); }}
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", background: "#ffffff" }}
                  >
                    <option value="SET-RETAIL-CONTROLLED-v1">SET-RETAIL-CONTROLLED-v1 (Retail Pricing)</option>
                    <option value="SET-LOAN-CONTROLLED-v1">SET-LOAN-CONTROLLED-v1 (Loan Approval)</option>
                    <option value="SET-PAYROLL-CONTROLLED-v1">SET-PAYROLL-CONTROLLED-v1 (Payroll Tax)</option>
                    <option value="SET-MEDICAL-CONTROLLED-v1">SET-MEDICAL-CONTROLLED-v1 (Medical Triage)</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>Evaluation Mode</label>
                  <select
                    value={customMode}
                    onChange={(e) => { setCustomMode(e.target.value); invalidateCustomState(); }}
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", background: "#ffffff" }}
                  >
                    <option value="CONTROLLED">CONTROLLED (Frozen Deterministic OracleSet)</option>
                    <option value="FULL_BEACON">FULL_BEACON (Invariant Discovery & Synthesis)</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>Preferred Provider</label>
                  <select
                    value={customProvider}
                    onChange={(e) => { setCustomProvider(e.target.value); invalidateCustomState(); }}
                    style={{ width: "100%", padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", background: "#ffffff" }}
                  >
                    <option value="auto">auto (Priority Fallback Chain)</option>
                    <option value="offline">offline (Deterministic Offline Engine)</option>
                    <option value="ollama">ollama (Local Private LLM)</option>
                    <option value="openrouter">openrouter (OpenRouter Cloud)</option>
                    <option value="anthropic">anthropic (Direct Anthropic Cloud)</option>
                  </select>
                </div>
              </div>

              {/* Privacy Consent Checkbox */}
              <div style={{ background: "#f8fafc", padding: "12px 16px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "10px", cursor: "pointer", fontSize: "13px" }}>
                  <input
                    type="checkbox"
                    checked={customAllowExternalLLM}
                    onChange={(e) => { setCustomAllowExternalLLM(e.target.checked); invalidateCustomState(); }}
                  />
                  <span>
                    <strong>Explicit Cloud LLM Consent:</strong> Allow sending dataset inputs and traces to external cloud providers (OpenRouter/Anthropic) when in FULL_BEACON mode.
                  </span>
                </label>
                <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px", marginLeft: "24px" }}>
                  When unchecked (default), user-supplied data is strictly processed locally (Ollama / Offline). Credentials and secrets are never transmitted.
                </div>
              </div>
            </div>

            {/* Step 4: Custom Pre-Flight Validation */}
            <div style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                    Step 5 & 6: Pre-Flight Integrity Check & Certification Execution
                  </h3>
                  <p style={{ margin: "2px 0 0", fontSize: "12px", color: "#64748b" }}>
                    Validates schema compatibility, adapter readiness, OracleSet coverage, and cryptographic fingerprint.
                  </p>
                </div>
                <div style={{ display: "flex", gap: "10px" }}>
                  <button
                    onClick={handleValidateCustomCertification}
                    disabled={busy || !customUploadedManifest}
                    style={{ background: "#f1f5f9", color: "#1e293b", border: "1px solid #cbd5e1", padding: "8px 16px", borderRadius: "6px", fontWeight: "600", fontSize: "13px", cursor: customUploadedManifest ? "pointer" : "not-allowed" }}
                  >
                    🔍 Step 6: Custom Pre-Flight Check
                  </button>
                  <button
                    onClick={handleRunCustomCertification}
                    disabled={busy || !customPreflight || !customPreflight.is_valid}
                    style={{
                      background: customPreflight?.is_valid ? "#2563eb" : "#94a3b8",
                      color: "#ffffff",
                      border: "none",
                      padding: "8px 20px",
                      borderRadius: "6px",
                      fontWeight: "600",
                      fontSize: "13px",
                      cursor: customPreflight?.is_valid ? "pointer" : "not-allowed",
                    }}
                  >
                    {busy ? "Certifying..." : "⚡ Step 7: Run Equivalence Certification"}
                  </button>
                </div>
              </div>

              {/* Preflight Results Panel */}
              {customPreflight && (
                <div style={{ background: customPreflight.is_valid ? "#f0fdf4" : "#fef2f2", border: `1px solid ${customPreflight.is_valid ? "#bbf7d0" : "#fecaca"}`, borderRadius: "8px", padding: "12px 16px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                    <span style={{ fontWeight: "700", fontSize: "13px", color: customPreflight.is_valid ? "#166534" : "#991b1b" }}>
                      {customPreflight.is_valid ? "✅ Custom Pre-Flight Validation PASSED" : "❌ Custom Pre-Flight Validation FAILED"}
                    </span>
                    <span style={{ fontSize: "11px", fontFamily: "monospace", color: "#64748b" }}>
                      Fingerprint: {customPreflight.config_fingerprint.slice(0, 16)}...
                    </span>
                  </div>
                  {customPreflight.errors?.length > 0 && (
                    <div style={{ color: "#991b1b", fontSize: "12px", marginTop: "4px" }}>
                      <strong>Errors:</strong> {customPreflight.errors.join("; ")}
                    </div>
                  )}
                  {customPreflight.warnings?.length > 0 && (
                    <div style={{ color: "#92400e", fontSize: "12px", marginTop: "4px" }}>
                      <strong>Warnings:</strong> {customPreflight.warnings.join("; ")}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Step 8 & 9: Authoritative Outcome, Evidence & Verification */}
            {customActiveResult && (
              <div style={cardStyle}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #e2e8f0", paddingBottom: "12px", marginBottom: "16px" }}>
                  <div>
                    <h3 style={{ margin: 0, fontSize: "16px", fontWeight: "700", color: "#0f172a" }}>
                      Step 8: Authoritative Certification Outcome
                    </h3>
                    <div style={{ fontSize: "12px", color: "#64748b", marginTop: "2px" }}>
                      Run ID: <code style={{ color: "#2563eb" }}>{customActiveResult.certification_id}</code> • Project: <strong>{customProjectId}</strong>
                    </div>
                  </div>
                  <span style={badgeStyle(
                    statusBadgeStyles[customActiveResult.status]?.bg || "#f1f5f9",
                    statusBadgeStyles[customActiveResult.status]?.color || "#334155",
                    statusBadgeStyles[customActiveResult.status]?.border || "#cbd5e1"
                  )}>
                    {statusBadgeStyles[customActiveResult.status]?.text || customActiveResult.status}
                  </span>
                </div>

                {/* Score & Metrics Grid */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "12px", marginBottom: "16px" }}>
                  <div style={{ background: "#f8fafc", padding: "12px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                    <div style={{ fontSize: "11px", color: "#64748b" }}>Equivalence Score</div>
                    <div style={{ fontSize: "20px", fontWeight: "800", color: customActiveResult.metrics?.equivalence_score === 1.0 ? "#059669" : "#dc2626" }}>
                      {((customActiveResult.metrics?.equivalence_score || 0) * 100).toFixed(1)}%
                    </div>
                  </div>
                  <div style={{ background: "#f8fafc", padding: "12px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                    <div style={{ fontSize: "11px", color: "#64748b" }}>Test Probes Evaluated</div>
                    <div style={{ fontSize: "20px", fontWeight: "800", color: "#0f172a" }}>
                      {customActiveResult.metrics?.unique_input_count || customActiveResult.metrics?.total_inputs}
                    </div>
                  </div>
                  <div style={{ background: "#f8fafc", padding: "12px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                    <div style={{ fontSize: "11px", color: "#64748b" }}>Matching Probes</div>
                    <div style={{ fontSize: "20px", fontWeight: "800", color: "#059669" }}>
                      {customActiveResult.metrics?.matching_case_count || customActiveResult.metrics?.matching_probes}
                    </div>
                  </div>
                  <div style={{ background: "#f8fafc", padding: "12px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                    <div style={{ fontSize: "11px", color: "#64748b" }}>Regressions Pinpointed</div>
                    <div style={{ fontSize: "20px", fontWeight: "800", color: (customActiveResult.regressions?.length || 0) > 0 ? "#dc2626" : "#059669" }}>
                      {customActiveResult.regressions?.length || 0}
                    </div>
                  </div>
                  <div style={{ background: "#f8fafc", padding: "12px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                    <div style={{ fontSize: "11px", color: "#64748b" }}>Oracle Coverage</div>
                    <div style={{ fontSize: "20px", fontWeight: "800", color: "#2563eb" }}>
                      {((customActiveResult.metrics?.oracle_coverage_pct || 1.0) * 100).toFixed(1)}%
                    </div>
                  </div>
                </div>

                {/* Provenance & Cryptographic Identifiers Table */}
                <div style={{ background: "#f8fafc", borderRadius: "8px", border: "1px solid #e2e8f0", padding: "14px", marginBottom: "16px" }}>
                  <div style={{ fontSize: "13px", fontWeight: "700", color: "#0f172a", marginBottom: "8px" }}>
                    🔒 Cryptographic Provenance Identifiers
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", fontSize: "12px" }}>
                    <div>Dataset Checksum: <code style={{ color: "#2563eb" }}>{customActiveResult.dataset_checksum || customActiveResult.context?.dataset_checksum || "N/A"}</code></div>
                    <div>Input-Set Hash: <code style={{ color: "#2563eb" }}>{customActiveResult.input_set_hash || "N/A"}</code></div>
                    <div>Legacy Implementation: <code style={{ color: "#475569" }}>{customActiveResult.legacy_implementation_hash ? `${customActiveResult.legacy_implementation_hash.slice(0, 16)}...` : "N/A"}</code></div>
                    <div>Modern Implementation: <code style={{ color: "#475569" }}>{customActiveResult.modernized_implementation_hash ? `${customActiveResult.modernized_implementation_hash.slice(0, 16)}...` : "N/A"}</code></div>
                    <div>OracleSet Digest: <code style={{ color: "#475569" }}>{customActiveResult.oracle_set_hash ? `${customActiveResult.oracle_set_hash.slice(0, 16)}...` : "N/A"}</code></div>
                    <div>Artifact Hash: <code style={{ color: "#059669", fontWeight: "700" }}>{customActiveResult.content_hash ? `${customActiveResult.content_hash.slice(0, 16)}...` : "N/A"}</code></div>
                  </div>
                </div>

                {/* Behavioral Regressions & Counterexamples */}
                {customActiveResult.regressions?.length > 0 && (
                  <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: "8px", padding: "14px", marginBottom: "16px" }}>
                    <div style={{ fontWeight: "700", color: "#991b1b", fontSize: "13px", marginBottom: "8px" }}>
                      ⚠️ Behavioral Regressions Detected ({customActiveResult.regressions.length})
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                      {customActiveResult.regressions.map((reg, idx) => (
                        <div key={idx} style={{ background: "#ffffff", padding: "8px 12px", borderRadius: "6px", border: "1px solid #fee2e2", fontSize: "12px" }}>
                          <span style={{ fontWeight: "600", color: "#dc2626" }}>Oracle {reg.oracle_id}:</span> {reg.details} •
                          Legacy: <code>{JSON.stringify(reg.legacy_output)}</code> vs Modern: <code>{JSON.stringify(reg.modern_output)}</code>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Step 9: 8-Point Cryptographic Verification Action */}
                <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                  <button
                    onClick={() => handleVerifyCustomIntegrity(customActiveResult.certification_id)}
                    style={{ background: "#0f172a", color: "#ffffff", border: "none", padding: "8px 16px", borderRadius: "6px", fontWeight: "600", fontSize: "13px", cursor: "pointer" }}
                  >
                    🔐 Step 9: Verify 8-Point Cryptographic Proof
                  </button>
                  <button
                    onClick={() => {
                      loadDossier(customActiveResult.certification_id);
                      setActiveTab("dossier");
                    }}
                    style={{ background: "#2563eb", color: "#ffffff", border: "none", padding: "8px 14px", borderRadius: "6px", fontWeight: "600", fontSize: "13px", cursor: "pointer" }}
                  >
                    📑 Inspect Evidence Dossier
                  </button>
                  <button
                    onClick={() => exportDossier(customActiveResult.certification_id, "markdown")}
                    style={{ background: "#f1f5f9", color: "#1e293b", border: "1px solid #cbd5e1", padding: "8px 14px", borderRadius: "6px", fontWeight: "600", fontSize: "13px", cursor: "pointer" }}
                  >
                    📄 Export Markdown Dossier
                  </button>
                  <button
                    onClick={() => exportDossier(customActiveResult.certification_id, "json")}
                    style={{ background: "#f1f5f9", color: "#1e293b", border: "1px solid #cbd5e1", padding: "8px 14px", borderRadius: "6px", fontWeight: "600", fontSize: "13px", cursor: "pointer" }}
                  >
                    📦 Export JSON Dossier
                  </button>
                </div>

                {/* Verification Results Panel */}
                {customCryptographicProof && (
                  <div style={{ marginTop: "14px", background: customCryptographicProof.status === "PASS" ? "#f0fdf4" : "#fef2f2", border: `1px solid ${customCryptographicProof.status === "PASS" ? "#bbf7d0" : "#fecaca"}`, borderRadius: "8px", padding: "12px 16px" }}>
                    <div style={{ fontWeight: "700", color: customCryptographicProof.status === "PASS" ? "#166534" : "#991b1b", fontSize: "13px", marginBottom: "4px" }}>
                      {customCryptographicProof.status === "PASS" ? "✅ 8-Point Cryptographic Integrity PASS" : "❌ Cryptographic Integrity Check FAIL"}
                    </div>
                    <div style={{ fontSize: "12px", color: "#475569" }}>
                      All artifact hashes, persisted inputs, implementation hashes, and dataset checksums successfully verified against canonical standards.
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB: EVIDENCE DOSSIER, EXPLAINABILITY & AUDITABILITY (PHASE 15)           */}
        {/* ========================================================================= */}
        {activeTab === "dossier" && (
          <div>
            {/* Dossier Header & Run Selector Bar */}
            <div style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #e2e8f0", paddingBottom: "14px", marginBottom: "16px" }}>
                <div>
                  <h2 style={{ margin: 0, fontSize: "18px", fontWeight: "700", color: "#0f172a" }}>
                    📑 Evidence Dossier & Explainability Engine
                  </h2>
                  <p style={{ margin: "2px 0 0", fontSize: "13px", color: "#64748b" }}>
                    Deterministic explainability, full chain-of-custody evidence tracing, completeness verification, and human audit review.
                  </p>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  {dossierCertId && (
                    <>
                      <button
                        onClick={() => exportEvidenceDossier(dossierCertId, "markdown")}
                        style={{ background: "#f1f5f9", color: "#1e293b", border: "1px solid #cbd5e1", padding: "8px 12px", borderRadius: "6px", fontWeight: "600", fontSize: "12px", cursor: "pointer" }}
                      >
                        📄 Markdown Report
                      </button>
                      <button
                        onClick={() => exportEvidenceDossier(dossierCertId, "json")}
                        style={{ background: "#f1f5f9", color: "#1e293b", border: "1px solid #cbd5e1", padding: "8px 12px", borderRadius: "6px", fontWeight: "600", fontSize: "12px", cursor: "pointer" }}
                      >
                        📦 JSON Dossier
                      </button>
                      <button
                        onClick={() => exportEvidenceDossier(dossierCertId, "csv")}
                        style={{ background: "#f1f5f9", color: "#1e293b", border: "1px solid #cbd5e1", padding: "8px 12px", borderRadius: "6px", fontWeight: "600", fontSize: "12px", cursor: "pointer" }}
                      >
                        📊 CSV Cases
                      </button>
                    </>
                  )}
                </div>
              </div>

              {/* Run Selection & Re-verify bar */}
              <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", flex: 1 }}>
                  <label style={{ fontSize: "13px", fontWeight: "600", color: "#334155" }}>Select Certification Run:</label>
                  <select
                    value={dossierCertId}
                    onChange={(e) => loadDossier(e.target.value)}
                    style={{ padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px", fontFamily: "monospace", flex: 1 }}
                  >
                    <option value="">-- Choose a Certification Run --</option>
                    {activeResult && <option value={activeResult.certification_id}>Active Run: {activeResult.certification_id} ({activeResult.benchmark_id || "benchmark"})</option>}
                    {customActiveResult && <option value={customActiveResult.certification_id}>Custom Run: {customActiveResult.certification_id} ({customProjectId})</option>}
                    {historicalArtifacts.map((a) => (
                      <option key={a.certification_id} value={a.certification_id}>
                        {a.certification_id} • {a.benchmark_id || a.project_id} • {a.status} ({a.timestamp?.slice(0, 16)})
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  onClick={() => loadDossier(dossierCertId)}
                  disabled={!dossierCertId || dossierLoading}
                  style={{ background: "#f1f5f9", border: "1px solid #cbd5e1", padding: "8px 14px", borderRadius: "6px", fontSize: "13px", fontWeight: "600", cursor: !dossierCertId ? "not-allowed" : "pointer" }}
                >
                  {dossierLoading ? "Loading..." : "🔄 Reload Dossier"}
                </button>
              </div>
            </div>

            {dossierData && dossierExplanation ? (
              <>
                {/* Idempotency & Reuse Banner */}
                {dossierData.is_reused_artifact && (
                  <div style={{ background: "#f0fdf4", border: "1px solid #86efac", borderRadius: "8px", padding: "10px 16px", marginBottom: "16px", display: "flex", alignItems: "center", gap: "10px", fontSize: "13px", color: "#166534" }}>
                    <span>♻️</span>
                    <span><strong>Deterministic Reuse:</strong> This run utilized the authoritative cached certification artifact matching identical request fingerprint. No duplicate compute was performed.</span>
                  </div>
                )}
                {dossierData.is_forced_recompute && (
                  <div style={{ background: "#eff6ff", border: "1px solid #bfdbfe", borderRadius: "8px", padding: "10px 16px", marginBottom: "16px", display: "flex", alignItems: "center", gap: "10px", fontSize: "13px", color: "#1e40af" }}>
                    <span>⚡</span>
                    <span><strong>Forced Recompute:</strong> This run executed a fresh, distinct certification run bypassing idempotency cache reuse.</span>
                  </div>
                )}

                {/* 1. WHY CERTIFIED / WHY NOT CERTIFIED / WHY INCONCLUSIVE HERO CARD */}
                <div style={{
                  ...cardStyle,
                  borderLeft: `6px solid ${
                    dossierExplanation.authoritative_status === "CERTIFIED" ? "#10b981" :
                    dossierExplanation.authoritative_status === "INSUFFICIENT_COVERAGE" ? "#f97316" : "#ef4444"
                  }`
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "14px" }}>
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                        <span style={{ fontSize: "20px" }}>
                          {dossierExplanation.authoritative_status === "CERTIFIED" ? "✅" :
                           dossierExplanation.authoritative_status === "INSUFFICIENT_COVERAGE" ? "⚠️" : "❌"}
                        </span>
                        <h3 style={{ margin: 0, fontSize: "17px", fontWeight: "800", color: "#0f172a" }}>
                          {dossierExplanation.headline}
                        </h3>
                      </div>
                      <p style={{ margin: "6px 0 0", fontSize: "13px", color: "#475569", lineHeight: "1.5" }}>
                        {dossierExplanation.status_rationale}
                      </p>
                    </div>
                    <span style={badgeStyle(
                      statusBadgeStyles[dossierExplanation.authoritative_status]?.bg || "#f1f5f9",
                      statusBadgeStyles[dossierExplanation.authoritative_status]?.color || "#334155",
                      statusBadgeStyles[dossierExplanation.authoritative_status]?.border || "#cbd5e1"
                    )}>
                      {dossierExplanation.authoritative_status}
                    </span>
                  </div>

                  {/* Quick Metrics Grid */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: "10px", marginTop: "16px" }}>
                    <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <div style={{ fontSize: "11px", color: "#64748b" }}>Equivalence Score</div>
                      <div style={{ fontSize: "18px", fontWeight: "800", color: dossierData.execution_evidence.equivalence_score >= 0.8 ? "#059669" : "#dc2626" }}>
                        {(dossierData.execution_evidence.equivalence_score * 100).toFixed(1)}%
                      </div>
                    </div>
                    <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <div style={{ fontSize: "11px", color: "#64748b" }}>Oracle Coverage</div>
                      <div style={{ fontSize: "18px", fontWeight: "800", color: "#0f172a" }}>
                        {(dossierData.execution_evidence.oracle_coverage_pct * 100).toFixed(1)}%
                      </div>
                    </div>
                    <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <div style={{ fontSize: "11px", color: "#64748b" }}>Unique Inputs</div>
                      <div style={{ fontSize: "18px", fontWeight: "800", color: "#0f172a" }}>
                        {dossierData.execution_evidence.total_inputs}
                      </div>
                    </div>
                    <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <div style={{ fontSize: "11px", color: "#64748b" }}>Matching Cases</div>
                      <div style={{ fontSize: "18px", fontWeight: "800", color: "#059669" }}>
                        {dossierData.execution_evidence.matching_cases}
                      </div>
                    </div>
                    <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <div style={{ fontSize: "11px", color: "#64748b" }}>Regressions</div>
                      <div style={{ fontSize: "18px", fontWeight: "800", color: dossierData.execution_evidence.regression_cases > 0 ? "#dc2626" : "#059669" }}>
                        {dossierData.execution_evidence.regression_cases}
                      </div>
                    </div>
                    <div style={{ background: "#f8fafc", padding: "10px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                      <div style={{ fontSize: "11px", color: "#64748b" }}>Active Oracles</div>
                      <div style={{ fontSize: "18px", fontWeight: "800", color: "#0f172a" }}>
                        {dossierData.oracle_evidence.oracle_count}
                      </div>
                    </div>
                  </div>

                  {/* Highest Severity Behavioral Regressions (if NOT CERTIFIED) */}
                  {dossierExplanation.highest_severity_failures?.length > 0 && (
                    <div style={{ marginTop: "18px" }}>
                      <h4 style={{ margin: "0 0 10px 0", fontSize: "14px", fontWeight: "700", color: "#991b1b" }}>
                        ⚠️ Pinpointed Behavioral Regressions ({dossierExplanation.highest_severity_failures.length})
                      </h4>
                      <div style={{ overflowX: "auto" }}>
                        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                          <thead>
                            <tr style={{ background: "#fef2f2", borderBottom: "1px solid #fecaca", textAlign: "left" }}>
                              <th style={{ padding: "8px 10px" }}>Oracle ID</th>
                              <th style={{ padding: "8px 10px" }}>Severity</th>
                              <th style={{ padding: "8px 10px" }}>Input Probe ID</th>
                              <th style={{ padding: "8px 10px" }}>Expected (Legacy)</th>
                              <th style={{ padding: "8px 10px" }}>Actual (Modern)</th>
                              <th style={{ padding: "8px 10px" }}>Invariant Violated</th>
                              <th style={{ padding: "8px 10px" }}>Sanitized Input Values</th>
                            </tr>
                          </thead>
                          <tbody>
                            {dossierExplanation.highest_severity_failures.map((f, idx) => (
                              <tr key={idx} style={{ borderBottom: "1px solid #f1f5f9" }}>
                                <td style={{ padding: "8px 10px", fontFamily: "monospace", fontWeight: "700", color: "#2563eb" }}>{f.oracle_id}</td>
                                <td style={{ padding: "8px 10px" }}><span style={badgeStyle("#fee2e2", "#991b1b")}>{f.severity}</span></td>
                                <td style={{ padding: "8px 10px", fontFamily: "monospace" }}>{f.input_id}</td>
                                <td style={{ padding: "8px 10px", color: "#059669", fontFamily: "monospace" }}>{JSON.stringify(f.legacy_output)}</td>
                                <td style={{ padding: "8px 10px", color: "#dc2626", fontFamily: "monospace", fontWeight: "700" }}>{JSON.stringify(f.modern_output)}</td>
                                <td style={{ padding: "8px 10px", color: "#475569" }}><em>{f.invariant_violated}</em></td>
                                <td style={{ padding: "8px 10px", fontFamily: "monospace", fontSize: "11px", color: "#64748b" }}>{JSON.stringify(f.sanitized_inputs)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>

                {/* 2. EVIDENCE COMPLETENESS & CRYPTOGRAPHIC PROOF CARD */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "20px" }}>
                  {/* Completeness Card */}
                  <div style={cardStyle}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <span style={{ fontSize: "18px" }}>📋</span>
                        <h3 style={{ margin: 0, fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                          Evidence Completeness Audit
                        </h3>
                      </div>
                      <span style={badgeStyle(
                        dossierData.completeness.status === "COMPLETE" ? "#dcfce7" : "#fee2e2",
                        dossierData.completeness.status === "COMPLETE" ? "#166534" : "#991b1b"
                      )}>
                        {dossierData.completeness.status} ({(dossierData.completeness.completeness_score * 100).toFixed(0)}%)
                      </span>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: "6px", fontSize: "12px" }}>
                      {Object.entries(dossierData.completeness.checks || {}).map(([chk, passed]) => (
                        <div key={chk} style={{ display: "flex", justifyContent: "space-between", padding: "4px 8px", background: passed ? "#f8fafc" : "#fef2f2", borderRadius: "4px" }}>
                          <span style={{ fontFamily: "monospace", color: "#334155" }}>{chk}</span>
                          <span style={{ fontWeight: "700", color: passed ? "#166534" : "#991b1b" }}>{passed ? "PASSED" : "MISSING"}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Cryptographic Hashes Card */}
                  <div style={cardStyle}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <span style={{ fontSize: "18px" }}>🛡️</span>
                        <h3 style={{ margin: 0, fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                          8-Point Cryptographic Integrity
                        </h3>
                      </div>
                      <span style={badgeStyle(
                        dossierData.cryptographic_evidence.integrity_status === "VERIFIED" ? "#dcfce7" : "#fee2e2",
                        dossierData.cryptographic_evidence.integrity_status === "VERIFIED" ? "#166534" : "#991b1b"
                      )}>
                        {dossierData.cryptographic_evidence.integrity_status}
                      </span>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: "6px", fontSize: "11px", fontFamily: "monospace" }}>
                      <div style={{ background: "#f8fafc", padding: "6px 8px", borderRadius: "4px" }}>
                        <span style={{ color: "#64748b" }}>Artifact Hash:</span> {dossierData.cryptographic_evidence.artifact_hash}
                      </div>
                      <div style={{ background: "#f8fafc", padding: "6px 8px", borderRadius: "4px" }}>
                        <span style={{ color: "#64748b" }}>Dataset Checksum:</span> {dossierData.cryptographic_evidence.dataset_checksum}
                      </div>
                      <div style={{ background: "#f8fafc", padding: "6px 8px", borderRadius: "4px" }}>
                        <span style={{ color: "#64748b" }}>OracleSet Hash:</span> {dossierData.cryptographic_evidence.oracle_set_hash}
                      </div>
                      <div style={{ background: "#f8fafc", padding: "6px 8px", borderRadius: "4px" }}>
                        <span style={{ color: "#64748b" }}>Input-Set Hash:</span> {dossierData.cryptographic_evidence.input_set_hash}
                      </div>
                    </div>
                  </div>
                </div>

                {/* 3. TRACEABILITY GRAPH / CHAIN OF CUSTODY (DAG) */}
                <div style={cardStyle}>
                  <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                    🔗 Evidence Traceability Graph / Chain of Custody
                  </h3>
                  <p style={{ margin: "0 0 16px 0", fontSize: "12px", color: "#64748b" }}>
                    Follow the chain of evidence from originating dataset to immutable cryptographic verification.
                  </p>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "10px" }}>
                    {dossierGraph.map((node) => (
                      <div key={node.node_id} style={{
                        background: node.status === "AVAILABLE" || node.status === "PASSED" ? "#ffffff" : (node.status === "WARNING" ? "#fffbeb" : "#fef2f2"),
                        border: `1px solid ${node.status === "AVAILABLE" || node.status === "PASSED" ? "#cbd5e1" : (node.status === "WARNING" ? "#fde68a" : "#fca5a5")}`,
                        borderRadius: "8px",
                        padding: "12px",
                        fontSize: "12px",
                      }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                          <span style={{ fontWeight: "700", color: "#0f172a", fontSize: "11px", textTransform: "uppercase" }}>{node.node_type}</span>
                          <span style={badgeStyle(
                            node.status === "PASSED" || node.status === "AVAILABLE" ? "#dcfce7" : (node.status === "WARNING" ? "#fef3c7" : "#fee2e2"),
                            node.status === "PASSED" || node.status === "AVAILABLE" ? "#166534" : (node.status === "WARNING" ? "#92400e" : "#991b1b")
                          )}>
                            {node.status}
                          </span>
                        </div>
                        <div style={{ fontWeight: "600", color: "#2563eb", marginBottom: "4px" }}>{node.label}</div>
                        {node.entity_id && <div style={{ fontSize: "10px", fontFamily: "monospace", color: "#64748b", wordBreak: "break-all" }}>ID: {node.entity_id}</div>}
                      </div>
                    ))}
                  </div>
                </div>

                {/* 4. CHRONOLOGICAL AUDIT TIMELINE & AUDITOR NOTES GRID */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "20px" }}>
                  {/* Audit Timeline */}
                  <div style={cardStyle}>
                    <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                      ⏱️ Chronological Audit Timeline
                    </h3>
                    <div style={{ display: "flex", flexDirection: "column", gap: "10px", maxHeight: "300px", overflowY: "auto" }}>
                      {dossierData.audit_timeline?.map((ev, idx) => (
                        <div key={idx} style={{ padding: "10px", background: "#f8fafc", borderRadius: "6px", border: "1px solid #e2e8f0", fontSize: "12px" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <span style={{ fontWeight: "700", color: "#2563eb", fontFamily: "monospace" }}>{ev.action}</span>
                            <span style={{ fontSize: "11px", color: "#64748b" }}>{ev.timestamp}</span>
                          </div>
                          <div style={{ fontSize: "11px", color: "#475569", marginTop: "4px" }}>
                            Status: <strong>{ev.status}</strong> • {JSON.stringify(ev.details)}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Human Review / Auditor Notes */}
                  <div style={cardStyle}>
                    <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                      📝 Human Review & Auditor Notes
                    </h3>
                    <p style={{ margin: "0 0 10px 0", fontSize: "12px", color: "#64748b" }}>
                      Notes are stored in an isolated annotation layer and do NOT alter cryptographic artifact hashes.
                    </p>
                    <div style={{ display: "flex", flexDirection: "column", gap: "8px", maxHeight: "180px", overflowY: "auto", marginBottom: "12px" }}>
                      {dossierNotes.length === 0 ? (
                        <div style={{ fontSize: "12px", color: "#94a3b8", textAlign: "center", padding: "12px" }}>No auditor notes recorded for this run.</div>
                      ) : (
                        dossierNotes.map((n) => (
                          <div key={n.note_id} style={{ padding: "8px 10px", background: "#f8fafc", borderRadius: "6px", border: "1px solid #e2e8f0", fontSize: "12px" }}>
                            <div style={{ display: "flex", justifyContent: "space-between", fontWeight: "600", color: "#334155" }}>
                              <span>{n.author}</span>
                              <span style={{ fontSize: "10px", color: "#64748b" }}>{n.timestamp?.slice(0, 19)}</span>
                            </div>
                            <div style={{ marginTop: "2px", color: "#0f172a" }}>{n.content}</div>
                          </div>
                        ))
                      )}
                    </div>
                    {/* Add note form */}
                    <div style={{ display: "flex", gap: "8px" }}>
                      <input
                        type="text"
                        placeholder="Author"
                        value={newNoteAuthor}
                        onChange={(e) => setNewNoteAuthor(e.target.value)}
                        style={{ width: "110px", padding: "6px 8px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "12px" }}
                      />
                      <input
                        type="text"
                        placeholder="Add audit sign-off or observation..."
                        value={newNoteContent}
                        onChange={(e) => setNewNoteContent(e.target.value)}
                        style={{ flex: 1, padding: "6px 8px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "12px" }}
                      />
                      <button
                        onClick={handleAddAuditorNote}
                        style={{ background: "#2563eb", color: "#ffffff", border: "none", padding: "6px 14px", borderRadius: "6px", fontWeight: "600", fontSize: "12px", cursor: "pointer" }}
                      >
                        Add Note
                      </button>
                    </div>
                  </div>
                </div>

                {/* 5. MULTI-RUN EVIDENCE COMPARATOR PANEL */}
                <div style={cardStyle}>
                  <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                    ⚖️ Side-by-Side Run Evidence Comparator
                  </h3>
                  <p style={{ margin: "0 0 14px 0", fontSize: "12px", color: "#64748b" }}>
                    Compare two historical runs to verify context equivalence, differential score deltas, and regression status.
                  </p>
                  <div style={{ display: "flex", gap: "12px", alignItems: "center", marginBottom: "16px" }}>
                    <select
                      value={compareRunA}
                      onChange={(e) => setCompareRunA(e.target.value)}
                      style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "12px", fontFamily: "monospace", flex: 1 }}
                    >
                      <option value="">-- Select Run A (Baseline) --</option>
                      {historicalArtifacts.map((a) => (
                        <option key={`a-${a.certification_id}`} value={a.certification_id}>{a.certification_id} ({a.status})</option>
                      ))}
                    </select>
                    <span style={{ fontWeight: "700", color: "#64748b" }}>vs</span>
                    <select
                      value={compareRunB}
                      onChange={(e) => setCompareRunB(e.target.value)}
                      style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "12px", fontFamily: "monospace", flex: 1 }}
                    >
                      <option value="">-- Select Run B (Candidate) --</option>
                      {historicalArtifacts.map((a) => (
                        <option key={`b-${a.certification_id}`} value={a.certification_id}>{a.certification_id} ({a.status})</option>
                      ))}
                    </select>
                    <button
                      onClick={handleCompareRuns}
                      disabled={!compareRunA || !compareRunB || comparingRuns}
                      style={{ background: "#0f172a", color: "#ffffff", border: "none", padding: "8px 18px", borderRadius: "6px", fontWeight: "600", fontSize: "13px", cursor: !compareRunA || !compareRunB ? "not-allowed" : "pointer" }}
                    >
                      {comparingRuns ? "Comparing..." : "Compare Runs"}
                    </button>
                  </div>

                  {comparisonResult && (
                    <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "16px", fontSize: "12px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                        <span style={{ fontWeight: "700", fontSize: "14px", color: "#0f172a" }}>Comparison Report: {comparisonResult.run_id_a} vs {comparisonResult.run_id_b}</span>
                        <span style={badgeStyle(
                          comparisonResult.is_equivalent_context ? "#dcfce7" : "#fffbeb",
                          comparisonResult.is_equivalent_context ? "#166534" : "#92400e"
                        )}>
                          {comparisonResult.is_equivalent_context ? "EQUIVALENT CONTEXT" : "NON-EQUIVALENT CONTEXT"}
                        </span>
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "10px", marginBottom: "12px" }}>
                        <div style={{ background: "#ffffff", padding: "8px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                          <span style={{ color: "#64748b" }}>Score Delta:</span>
                          <div style={{ fontWeight: "700", fontSize: "14px", color: comparisonResult.metrics_comparison.score_delta >= 0 ? "#059669" : "#dc2626" }}>
                            {comparisonResult.metrics_comparison.score_delta > 0 ? `+${(comparisonResult.metrics_comparison.score_delta * 100).toFixed(1)}%` : `${(comparisonResult.metrics_comparison.score_delta * 100).toFixed(1)}%`}
                          </div>
                        </div>
                        <div style={{ background: "#ffffff", padding: "8px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                          <span style={{ color: "#64748b" }}>Coverage Delta:</span>
                          <div style={{ fontWeight: "700", fontSize: "14px", color: "#0f172a" }}>
                            {comparisonResult.metrics_comparison.coverage_delta > 0 ? `+${(comparisonResult.metrics_comparison.coverage_delta * 100).toFixed(1)}%` : `${(comparisonResult.metrics_comparison.coverage_delta * 100).toFixed(1)}%`}
                          </div>
                        </div>
                        <div style={{ background: "#ffffff", padding: "8px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                          <span style={{ color: "#64748b" }}>Fixed Regressions:</span>
                          <div style={{ fontWeight: "700", fontSize: "14px", color: "#059669" }}>
                            {comparisonResult.differential_regressions.fixed_count}
                          </div>
                        </div>
                        <div style={{ background: "#ffffff", padding: "8px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                          <span style={{ color: "#64748b" }}>New Regressions:</span>
                          <div style={{ fontWeight: "700", fontSize: "14px", color: comparisonResult.differential_regressions.new_count > 0 ? "#dc2626" : "#059669" }}>
                            {comparisonResult.differential_regressions.new_count}
                          </div>
                        </div>
                      </div>
                      {comparisonResult.context_divergence_reasons?.length > 0 && (
                        <div style={{ color: "#92400e", background: "#fffbeb", padding: "8px", borderRadius: "6px", border: "1px solid #fde68a" }}>
                          <strong>Context Divergences:</strong> {comparisonResult.context_divergence_reasons.join("; ")}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div style={{ ...cardStyle, textAlign: "center", padding: "48px 24px" }}>
                <span style={{ fontSize: "40px" }}>📑</span>
                <h3 style={{ margin: "12px 0 6px", fontSize: "18px", fontWeight: "700", color: "#0f172a" }}>
                  Select a Certification Run to Open Evidence Dossier
                </h3>
                <p style={{ margin: "0 auto 20px", maxWidth: "600px", fontSize: "14px", color: "#64748b" }}>
                  Choose an active or historical certification run above to inspect the authoritative deterministic explanation, completeness report, traceability graph, and audit trail.
                </p>
              </div>
            )}
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB: OPERATIONS, HEALTH & RELIABILITY DASHBOARD                          */}
        {/* ========================================================================= */}
        {activeTab === "operations" && (
          <div>
            {/* 1. TOP SYSTEM HEALTH & CONTROLS BANNER */}
            <div style={{ ...cardStyle, background: "#0f172a", color: "#f8fafc", border: "1px solid #1e293b" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "16px" }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
                    <h2 style={{ margin: 0, fontSize: "18px", fontWeight: "700", color: "#f8fafc" }}>
                      ⚙️ Operational Diagnostics & Health Matrix
                    </h2>
                    <span style={badgeStyle(
                      operationsSummary?.system_status === "HEALTHY" ? "#064e3b" : "#78350f",
                      operationsSummary?.system_status === "HEALTHY" ? "#a7f3d0" : "#fde68a",
                      operationsSummary?.system_status === "HEALTHY" ? "#059669" : "#d97706"
                    )}>
                      {operationsSummary?.system_status || "CHECKING"}
                    </span>
                  </div>
                  <p style={{ margin: 0, fontSize: "13px", color: "#94a3b8" }}>
                    Continuous observability, liveness/readiness probes, non-sensitive diagnostics, and lifecycle telemetry.
                  </p>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "#cbd5e1", cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={autoRefreshOperations}
                      onChange={(e) => setAutoRefreshOperations(e.target.checked)}
                    />
                    Auto-refresh (3s)
                  </label>
                  <button
                    onClick={loadOperationsSummary}
                    disabled={operationsLoading}
                    style={{
                      background: "#3b82f6",
                      color: "#ffffff",
                      border: "none",
                      padding: "8px 14px",
                      borderRadius: "6px",
                      fontWeight: "600",
                      fontSize: "13px",
                      cursor: operationsLoading ? "not-allowed" : "pointer",
                    }}
                  >
                    {operationsLoading ? "Refreshing..." : "🔄 Refresh Metrics"}
                  </button>
                </div>
              </div>

              {/* Status Pills Grid */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "14px", marginTop: "18px" }}>
                <div style={{ background: "#1e293b", padding: "12px 14px", borderRadius: "8px", border: "1px solid #334155" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: "600" }}>Liveness Probe (/health/live)</div>
                  <div style={{ fontSize: "16px", fontWeight: "700", color: operationsSummary?.liveness === "UP" ? "#34d399" : "#f87171", marginTop: "4px" }}>
                    ● {operationsSummary?.liveness || "UP"}
                  </div>
                  <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>Process vital & responsive</div>
                </div>

                <div style={{ background: "#1e293b", padding: "12px 14px", borderRadius: "8px", border: "1px solid #334155" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: "600" }}>Readiness Probe (/health/ready)</div>
                  <div style={{ fontSize: "16px", fontWeight: "700", color: operationsSummary?.readiness === "READY" ? "#34d399" : "#f87171", marginTop: "4px" }}>
                    ● {operationsSummary?.readiness || "READY"}
                  </div>
                  <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>Accepting certification workloads</div>
                </div>

                <div style={{ background: "#1e293b", padding: "12px 14px", borderRadius: "8px", border: "1px solid #334155" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: "600" }}>Total Jobs Executed</div>
                  <div style={{ fontSize: "16px", fontWeight: "700", color: "#38bdf8", marginTop: "4px" }}>
                    {operationsSummary?.metrics?.certification_runs_total ?? 0}
                  </div>
                  <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>Success Rate: {(((operationsSummary?.metrics?.certification_runs_successful || 0) / Math.max(operationsSummary?.metrics?.certification_runs_total || 1, 1)) * 100).toFixed(0)}%</div>
                </div>

                <div style={{ background: "#1e293b", padding: "12px 14px", borderRadius: "8px", border: "1px solid #334155" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: "600" }}>Avg Certification Latency</div>
                  <div style={{ fontSize: "16px", fontWeight: "700", color: "#fbbf24", marginTop: "4px" }}>
                    {(operationsSummary?.metrics?.avg_certification_duration_ms || 0).toFixed(1)} ms
                  </div>
                  <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>Preflight avg: {(operationsSummary?.metrics?.avg_preflight_duration_ms || 0).toFixed(1)} ms</div>
                </div>
              </div>
            </div>

            {/* 2. DEPENDENCY HEALTH MATRIX */}
            <div style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
                <h3 style={{ margin: 0, fontSize: "16px", fontWeight: "700", color: "#0f172a" }}>
                  🔌 Subsystem & Dependency Status
                </h3>
                <span style={{ fontSize: "12px", color: "#64748b" }}>Zero secret/credential exposure guaranteed</span>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "14px" }}>
                {operationsSummary?.dependencies && Object.entries(operationsSummary.dependencies).map(([key, dep]) => {
                  const isHealthy = dep.status === "healthy";
                  const isDegraded = dep.status === "degraded" || dep.status === "not_configured";
                  const statusBg = isHealthy ? "#ecfdf5" : (isDegraded ? "#fffbeb" : "#fef2f2");
                  const statusColor = isHealthy ? "#065f46" : (isDegraded ? "#92400e" : "#991b1b");
                  const statusBorder = isHealthy ? "#10b981" : (isDegraded ? "#f59e0b" : "#ef4444");

                  return (
                    <div key={key} style={{ padding: "14px", borderRadius: "8px", border: `1px solid ${statusBorder}`, background: statusBg }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                        <strong style={{ fontSize: "13px", color: "#0f172a" }}>{dep.name}</strong>
                        <span style={badgeStyle(statusBg, statusColor, statusBorder)}>
                          {dep.status.toUpperCase()}
                        </span>
                      </div>
                      <div style={{ fontSize: "11px", color: "#475569", textTransform: "capitalize", marginBottom: "6px" }}>
                        Category: <strong>{dep.category}</strong>
                      </div>
                      {dep.details && (
                        <div style={{ fontSize: "11px", color: "#64748b", fontFamily: "monospace", background: "#ffffff", padding: "6px 8px", borderRadius: "4px", border: "1px solid #e2e8f0" }}>
                          {Object.entries(dep.details).map(([dk, dv]) => (
                            <div key={dk}>{dk}: {String(dv)}</div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* 3. OPERATIONAL METRICS & BREAKDOWNS */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "18px", marginBottom: "20px" }}>
              {/* Metrics Breakdown */}
              <div style={cardStyle}>
                <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                  📊 Certification Outcome Breakdown
                </h3>
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  {operationsSummary?.metrics?.certification_status_breakdown && Object.entries(operationsSummary.metrics.certification_status_breakdown).length > 0 ? (
                    Object.entries(operationsSummary.metrics.certification_status_breakdown).map(([st, cnt]) => {
                      const badgeInfo = statusBadgeStyles[st] || { bg: "#f1f5f9", border: "#cbd5e1", color: "#334155" };
                      return (
                        <div key={st} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 12px", background: "#f8fafc", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                          <span style={badgeStyle(badgeInfo.bg, badgeInfo.color, badgeInfo.border)}>{st}</span>
                          <strong style={{ fontSize: "13px", color: "#0f172a" }}>{cnt} runs</strong>
                        </div>
                      );
                    })
                  ) : (
                    <div style={{ padding: "16px", textAlign: "center", color: "#94a3b8", fontSize: "12px" }}>No certification run outcomes recorded yet.</div>
                  )}
                </div>
              </div>

              {/* Workload & Failure Diagnostics */}
              <div style={cardStyle}>
                <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: "700", color: "#0f172a" }}>
                  🛡️ Workload Protection & Error Diagnostics
                </h3>
                <div style={{ display: "flex", flexDirection: "column", gap: "8px", fontSize: "12px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 12px", background: "#f8fafc", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                    <span>Active Concurrent Jobs:</span>
                    <strong>{operationsSummary?.metrics?.active_jobs_count ?? 0} / 10 max</strong>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 12px", background: "#f8fafc", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                    <span>Provider Fallback Count:</span>
                    <strong style={{ color: (operationsSummary?.metrics?.provider_fallback_count || 0) > 0 ? "#d97706" : "#059669" }}>
                      {operationsSummary?.metrics?.provider_fallback_count ?? 0}
                    </strong>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 12px", background: "#f8fafc", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                    <span>Ingestion Failures:</span>
                    <strong style={{ color: (operationsSummary?.metrics?.ingestion_failures_total || 0) > 0 ? "#dc2626" : "#059669" }}>
                      {operationsSummary?.metrics?.ingestion_failures_total ?? 0}
                    </strong>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 12px", background: "#f8fafc", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                    <span>Preflight Validations Total:</span>
                    <strong>{operationsSummary?.metrics?.preflight_requests_total ?? 0}</strong>
                  </div>
                </div>
              </div>
            </div>

            {/* 4. REAL-TIME CERTIFICATION JOB LIFECYCLE TRACKER */}
            <div style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: "16px", fontWeight: "700", color: "#0f172a" }}>
                    📋 Certification Job Lifecycle Monitor
                  </h3>
                  <p style={{ margin: "2px 0 0", fontSize: "12px", color: "#64748b" }}>
                    Live execution state machine: ACCEPTED → VALIDATING → RUNNING → COMPLETED
                  </p>
                </div>

                <div style={{ display: "flex", gap: "8px" }}>
                  <input
                    type="text"
                    placeholder="Filter by project..."
                    value={operationsProjectFilter}
                    onChange={(e) => setOperationsProjectFilter(e.target.value)}
                    style={{ padding: "6px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "12px", width: "160px" }}
                  />
                </div>
              </div>

              {operationsSummary?.recent_jobs && operationsSummary.recent_jobs.length > 0 ? (
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                    <thead>
                      <tr style={{ background: "#f8fafc", borderBottom: "2px solid #e2e8f0", textAlign: "left" }}>
                        <th style={{ padding: "8px 10px" }}>Job ID</th>
                        <th style={{ padding: "8px 10px" }}>Project</th>
                        <th style={{ padding: "8px 10px" }}>Target</th>
                        <th style={{ padding: "8px 10px" }}>Job State</th>
                        <th style={{ padding: "8px 10px" }}>Outcome</th>
                        <th style={{ padding: "8px 10px" }}>Score</th>
                        <th style={{ padding: "8px 10px" }}>Latency</th>
                        <th style={{ padding: "8px 10px" }}>Created At</th>
                      </tr>
                    </thead>
                    <tbody>
                      {operationsSummary.recent_jobs
                        .filter((j) => !operationsProjectFilter || j.project_id.toLowerCase().includes(operationsProjectFilter.toLowerCase()))
                        .map((job) => {
                          const isComplete = job.state === "COMPLETED";
                          const isFailed = job.state === "FAILED";
                          const stateBg = isComplete ? "#ecfdf5" : (isFailed ? "#fef2f2" : "#eff6ff");
                          const stateColor = isComplete ? "#065f46" : (isFailed ? "#991b1b" : "#1e40af");
                          const stateBorder = isComplete ? "#10b981" : (isFailed ? "#ef4444" : "#3b82f6");

                          return (
                            <tr key={job.job_id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                              <td style={{ padding: "8px 10px", fontFamily: "monospace", fontWeight: "600", color: "#2563eb" }}>
                                {job.job_id}
                              </td>
                              <td style={{ padding: "8px 10px", color: "#475569" }}>{job.project_id}</td>
                              <td style={{ padding: "8px 10px", fontWeight: "500" }}>{job.benchmark_id || job.dataset_id}</td>
                              <td style={{ padding: "8px 10px" }}>
                                <span style={badgeStyle(stateBg, stateColor, stateBorder)}>{job.state}</span>
                              </td>
                              <td style={{ padding: "8px 10px" }}>
                                {job.certification_status ? (
                                  <span style={badgeStyle(
                                    job.certification_status === "CERTIFIED" ? "#ecfdf5" : "#fef2f2",
                                    job.certification_status === "CERTIFIED" ? "#065f46" : "#991b1b"
                                  )}>
                                    {job.certification_status}
                                  </span>
                                ) : "—"}
                              </td>
                              <td style={{ padding: "8px 10px", fontWeight: "600" }}>
                                {job.equivalence_score !== null && job.equivalence_score !== undefined ? `${(job.equivalence_score * 100).toFixed(1)}%` : "—"}
                              </td>
                              <td style={{ padding: "8px 10px", color: "#64748b" }}>
                                {job.duration_ms !== null && job.duration_ms !== undefined ? `${job.duration_ms.toFixed(1)} ms` : "—"}
                              </td>
                              <td style={{ padding: "8px 10px", color: "#94a3b8", fontSize: "11px" }}>
                                {job.created_at ? job.created_at.slice(0, 19).replace("T", " ") : "—"}
                              </td>
                            </tr>
                          );
                        })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ padding: "24px", textAlign: "center", color: "#94a3b8", fontSize: "13px" }}>
                  No certification jobs recorded in the current session.
                </div>
              )}
            </div>
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 3: CERTIFICATION HISTORY (BENCHMARK FILTERED)                          */}
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
  
      {/* Phase 17 Authentication & Login Modal */}
      {loginModalOpen && (
        <div style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: "rgba(15, 23, 42, 0.75)",
          backdropFilter: "blur(4px)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          zIndex: 9999,
        }}>
          <div style={{
            background: "#ffffff",
            borderRadius: "16px",
            padding: "28px",
            width: "440px",
            maxWidth: "90vw",
            boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.2)",
            border: "1px solid #e2e8f0",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ fontSize: "24px" }}>🔐</span>
                <h3 style={{ margin: 0, fontSize: "18px", fontWeight: "700", color: "#0f172a" }}>Sign In to BEACON</h3>
              </div>
              <button
                onClick={() => setLoginModalOpen(false)}
                style={{ background: "transparent", border: "none", fontSize: "18px", cursor: "pointer", color: "#64748b" }}
              >
                ✕
              </button>
            </div>

            <p style={{ margin: "0 0 16px 0", fontSize: "13px", color: "#64748b" }}>
              Authenticate with your credentials or select a quick demo profile to evaluate role-based access controls.
            </p>

            {loginError && (
              <div style={{ background: "#fef2f2", border: "1px solid #ef4444", color: "#991b1b", padding: "10px", borderRadius: "8px", fontSize: "12px", marginBottom: "16px" }}>
                ⚠️ {loginError}
              </div>
            )}

            {/* Quick Demo Profiles (Development Only) */}
            {IS_DEV && (
              <div style={{ marginBottom: "18px" }}>
                <div style={{ fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "8px" }}>1-Click Demo Profiles (Dev Mode):</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                  <button
                    type="button"
                    onClick={() => quickLogin("admin", "BeaconAdmin2026!")}
                    disabled={loginBusy}
                    style={{
                      background: "#fdf4ff",
                      border: "1px solid #c084fc",
                      color: "#6b21a8",
                      padding: "8px",
                      borderRadius: "8px",
                      fontSize: "12px",
                      fontWeight: "600",
                      cursor: "pointer",
                      textAlign: "left",
                      gridColumn: "span 2",
                    }}
                  >
                    👑 Admin (System Administrator)
                  </button>
                  <button
                    type="button"
                    onClick={() => quickLogin("alice_certifier", "AliceCert2026!")}
                    disabled={loginBusy}
                    style={{
                      background: "#eff6ff",
                      border: "1px solid #60a5fa",
                      color: "#1d4ed8",
                      padding: "8px",
                      borderRadius: "8px",
                      fontSize: "12px",
                      fontWeight: "600",
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                  >
                    ⚡ Alice (Certifier)
                  </button>
                  <button
                    type="button"
                    onClick={() => quickLogin("bob_viewer", "BobView2026!")}
                    disabled={loginBusy}
                    style={{
                      background: "#f8fafc",
                      border: "1px solid #94a3b8",
                      color: "#475569",
                      padding: "8px",
                      borderRadius: "8px",
                      fontSize: "12px",
                      fontWeight: "600",
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                  >
                    👁️ Bob (Viewer)
                  </button>
                  <button
                    type="button"
                    onClick={() => quickLogin("carol_auditor", "CarolAudit2026!")}
                    disabled={loginBusy}
                    style={{
                      background: "#fff7ed",
                      border: "1px solid #fb923c",
                      color: "#c2410c",
                      padding: "8px",
                      borderRadius: "8px",
                      fontSize: "12px",
                      fontWeight: "600",
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                  >
                    📋 Carol (Auditor)
                  </button>
                  <button
                    type="button"
                    onClick={() => quickLogin("dave_admin", "DaveAdmin2026!")}
                    disabled={loginBusy}
                    style={{
                      background: "#f0fdf4",
                      border: "1px solid #4ade80",
                      color: "#15803d",
                      padding: "8px",
                      borderRadius: "8px",
                      fontSize: "12px",
                      fontWeight: "600",
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                  >
                    🛡️ Dave (Admin)
                  </button>
                </div>
              </div>
            )}

            <div style={{ borderTop: "1px solid #e2e8f0", paddingTop: "14px", marginTop: "14px" }}>
              <div style={{ fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "8px" }}>Custom Credentials:</div>
              <div style={{ marginBottom: "10px" }}>
                <label style={{ display: "block", fontSize: "11px", fontWeight: "600", color: "#64748b", marginBottom: "4px" }}>Username</label>
                <input
                  type="text"
                  value={loginUsername}
                  onChange={(e) => setLoginUsername(e.target.value)}
                  style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>
              <div style={{ marginBottom: "16px" }}>
                <label style={{ display: "block", fontSize: "11px", fontWeight: "600", color: "#64748b", marginBottom: "4px" }}>Password</label>
                <input
                  type="password"
                  value={loginPassword}
                  onChange={(e) => setLoginPassword(e.target.value)}
                  style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>
              <button
                type="button"
                onClick={() => quickLogin(loginUsername, loginPassword)}
                disabled={loginBusy}
                style={{
                  width: "100%",
                  background: "#2563eb",
                  color: "#ffffff",
                  border: "none",
                  padding: "10px",
                  borderRadius: "8px",
                  fontSize: "13px",
                  fontWeight: "600",
                  cursor: loginBusy ? "not-allowed" : "pointer",
                }}
              >
                {loginBusy ? "Authenticating..." : "Sign In"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
