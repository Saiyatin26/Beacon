import { useState, useEffect } from "react";

export default function KnowledgeMode({ apiBase = "", authFetch, badgeStyle, cardStyle }) {
  // Application Scope State
  const [appId, setAppId] = useState("");
  
  // Ingestion State
  const [selectedFile, setSelectedFile] = useState(null);
  const [chunkSize, setChunkSize] = useState("500");
  const [chunkOverlap, setChunkOverlap] = useState("100");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);
  const [uploadSuccess, setUploadSuccess] = useState(null);

  // Document List State
  const [documents, setDocuments] = useState([]);
  const [isLoadingDocs, setIsLoadingDocs] = useState(false);
  const [docsError, setDocsError] = useState(null);
  const [expandedDocChunks, setExpandedDocChunks] = useState(null);
  const [activeDocChunks, setActiveDocChunks] = useState([]);
  const [isLoadingChunks, setIsLoadingChunks] = useState(false);

  // Retrieval Tester State
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState("5");
  const [minScore, setMinScore] = useState("0.01");
  const [isRetrieving, setIsRetrieving] = useState(false);
  const [retrievalResult, setRetrievalResult] = useState(null);
  const [retrievalError, setRetrievalError] = useState(null);

  // Load documents for current scope
  const loadDocuments = async () => {
    setIsLoadingDocs(true);
    setDocsError(null);
    try {
      const url = appId.trim()
        ? `${apiBase}/api/v2/knowledge/documents?application_id=${encodeURIComponent(appId.trim())}`
        : `${apiBase}/api/v2/knowledge/documents`;
      const resp = await (authFetch || fetch)(url);
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to list documents (HTTP ${resp.status})`);
      }
      const data = await resp.json();
      setDocuments(data);
    } catch (err) {
      setDocsError(err.message || String(err));
    } finally {
      setIsLoadingDocs(false);
    }
  };

  // Upload and ingest document
  const handleUpload = async (e) => {
    e.preventDefault();
    if (!selectedFile) {
      setUploadError("Please select a PDF or DOCX file to upload.");
      return;
    }

    setIsUploading(true);
    setUploadError(null);
    setUploadSuccess(null);

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      formData.append("application_id", appId.trim());
      formData.append("chunk_size", parseInt(chunkSize, 10) || 500);
      formData.append("chunk_overlap", parseInt(chunkOverlap, 10) || 100);

      const resp = await (authFetch || fetch)(`${apiBase}/api/v2/knowledge/documents/upload`, {
        method: "POST",
        body: formData,
      });

      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `Upload failed with HTTP ${resp.status}`);
      }

      const data = await resp.json();
      setUploadSuccess(`Document '${data.filename}' ingested successfully (Status: ${data.status}, Chunks: ${data.chunk_count}).`);
      setSelectedFile(null);
      // Reset file input element
      const fileInput = document.getElementById("knowledge-file-picker");
      if (fileInput) fileInput.value = "";
      
      await loadDocuments();
    } catch (err) {
      setUploadError(err.message || String(err));
    } finally {
      setIsUploading(false);
    }
  };

  // Delete document
  const handleDelete = async (docId) => {
    if (!window.confirm("Are you sure you want to delete this document and its indexed chunks?")) {
      return;
    }
    try {
      const resp = await (authFetch || fetch)(`${apiBase}/api/v2/knowledge/documents/${encodeURIComponent(docId)}`, {
        method: "DELETE",
      });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `Delete failed with HTTP ${resp.status}`);
      }
      if (expandedDocChunks === docId) {
        setExpandedDocChunks(null);
        setActiveDocChunks([]);
      }
      await loadDocuments();
    } catch (err) {
      alert(`Delete error: ${err.message || String(err)}`);
    }
  };

  // View chunks for a document
  const handleViewChunks = async (docId) => {
    if (expandedDocChunks === docId) {
      setExpandedDocChunks(null);
      setActiveDocChunks([]);
      return;
    }

    setExpandedDocChunks(docId);
    setIsLoadingChunks(true);
    try {
      const resp = await (authFetch || fetch)(`${apiBase}/api/v2/knowledge/documents/${encodeURIComponent(docId)}/chunks`);
      if (!resp.ok) {
        throw new Error("Failed to load document chunks.");
      }
      const data = await resp.json();
      setActiveDocChunks(data);
    } catch (err) {
      alert(`Error: ${err.message}`);
    } finally {
      setIsLoadingChunks(false);
    }
  };

  // Execute knowledge retrieval query
  const handleRetrieve = async (e) => {
    e.preventDefault();
    if (!query.trim()) {
      setRetrievalError("Please enter a search query.");
      return;
    }

    setIsRetrieving(true);
    setRetrievalError(null);
    setRetrievalResult(null);

    try {
      const payload = {
        application_id: appId.trim(),
        query: query.trim(),
        top_k: parseInt(topK, 10) || 5,
        min_relevance_score: parseFloat(minScore) || 0.01,
      };

      const resp = await (authFetch || fetch)(`${apiBase}/api/v2/knowledge/retrieve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.detail || `Retrieval failed with HTTP ${resp.status}`);
      }

      const data = await resp.json();
      setRetrievalResult(data);
    } catch (err) {
      setRetrievalError(err.message || String(err));
    } finally {
      setIsRetrieving(false);
    }
  };

  useEffect(() => {
    loadDocuments();
  }, [appId]);

  return (
    <div style={{ maxWidth: "1400px", margin: "0 auto", padding: "10px" }}>
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
            <h2 style={{ fontSize: "22px", fontWeight: "700", margin: "0 0 6px 0", color: "#38bdf8" }}>
              📚 BEACON V2 — Company Knowledge RAG Infrastructure
            </h2>
            <p style={{ margin: 0, fontSize: "14px", color: "#94a3b8" }}>
              Enterprise document ingestion (PDF/DOCX), deterministic chunking, and scoped lexical retrieval for grounded explanations.
            </p>
          </div>
          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            <span style={badgeStyle("#0369a1", "#e0f2fe", "#0284c7")}>
              Phase 9 Active
            </span>
            <span style={badgeStyle("#334155", "#cbd5e1", "#475569")}>
              PDF / DOCX
            </span>
          </div>
        </div>
      </div>

      {/* Non-Authoritative Disclaimer Banner */}
      <div
        style={{
          background: "#f0fdf4",
          border: "1px solid #bbf7d0",
          borderRadius: "8px",
          padding: "12px 16px",
          marginBottom: "20px",
          display: "flex",
          alignItems: "center",
          gap: "10px",
          fontSize: "13px",
          color: "#166534",
        }}
      >
        <span style={{ fontSize: "18px" }}>ℹ️</span>
        <div>
          <strong>Authority Boundary:</strong> Company knowledge RAG is <em>supplementary context</em> for future intelligent explanations (Phase 10). RAG knowledge does <strong>NOT</strong> determine certification passes/fails or alter deterministic evaluation verdicts.
        </div>
      </div>

      {/* Global Scope Selector Bar */}
      <div style={{ ...cardStyle, padding: "14px 20px", display: "flex", alignItems: "center", gap: "16px", marginBottom: "20px" }}>
        <label style={{ fontSize: "13px", fontWeight: "700", color: "#1e293b" }}>
          🏢 Knowledge Application Scope:
        </label>
        <input
          type="text"
          value={appId}
          onChange={(e) => setAppId(e.target.value)}
          placeholder="Application ID (from repository analysis)..."
          style={{
            padding: "8px 12px",
            borderRadius: "6px",
            border: "1px solid #cbd5e1",
            fontSize: "13px",
            width: "280px",
            fontFamily: "monospace",
          }}
        />
        <button
          onClick={loadDocuments}
          disabled={isLoadingDocs}
          style={{
            background: "#f1f5f9",
            border: "1px solid #cbd5e1",
            padding: "8px 14px",
            borderRadius: "6px",
            fontSize: "13px",
            fontWeight: "600",
            cursor: "pointer",
          }}
        >
          {isLoadingDocs ? "Refreshing..." : "🔄 Refresh Documents"}
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px", marginBottom: "20px" }}>
        {/* Document Ingestion Card */}
        <div style={cardStyle}>
          <h3 style={{ fontSize: "16px", fontWeight: "600", marginBottom: "14px", color: "#1e293b" }}>
            1. Ingest Company Knowledge Document
          </h3>
          <p style={{ fontSize: "13px", color: "#64748b", margin: "0 0 16px 0" }}>
            Upload enterprise policy documents, business rules, or specifications in PDF or DOCX format.
          </p>

          <form onSubmit={handleUpload}>
            <div style={{ marginBottom: "14px" }}>
              <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "6px" }}>
                Select PDF or DOCX File *
              </label>
              <input
                id="knowledge-file-picker"
                type="file"
                accept=".pdf,.docx"
                onChange={(e) => setSelectedFile(e.target.files[0] || null)}
                style={{
                  width: "100%",
                  padding: "8px",
                  borderRadius: "6px",
                  border: "1px dashed #94a3b8",
                  background: "#f8fafc",
                  fontSize: "13px",
                }}
              />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "16px" }}>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>
                  Chunk Size (chars)
                </label>
                <input
                  type="number"
                  value={chunkSize}
                  onChange={(e) => setChunkSize(e.target.value)}
                  style={{ width: "100%", padding: "7px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>
                  Chunk Overlap (chars)
                </label>
                <input
                  type="number"
                  value={chunkOverlap}
                  onChange={(e) => setChunkOverlap(e.target.value)}
                  style={{ width: "100%", padding: "7px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>
            </div>

            {uploadError && (
              <div style={{ padding: "10px", background: "#fef2f2", color: "#b91c1c", borderRadius: "6px", fontSize: "12px", marginBottom: "14px" }}>
                ⚠️ {uploadError}
              </div>
            )}

            {uploadSuccess && (
              <div style={{ padding: "10px", background: "#f0fdf4", color: "#166534", borderRadius: "6px", fontSize: "12px", marginBottom: "14px" }}>
                ✅ {uploadSuccess}
              </div>
            )}

            <button
              type="submit"
              disabled={isUploading || !selectedFile}
              style={{
                width: "100%",
                padding: "10px",
                background: !selectedFile ? "#94a3b8" : "#2563eb",
                color: "#ffffff",
                border: "none",
                borderRadius: "8px",
                fontWeight: "600",
                fontSize: "14px",
                cursor: !selectedFile || isUploading ? "not-allowed" : "pointer",
              }}
            >
              {isUploading ? "Extracting & Indexing..." : "📤 Upload & Index Document"}
            </button>
          </form>
        </div>

        {/* Knowledge Retrieval Tester Card */}
        <div style={cardStyle}>
          <h3 style={{ fontSize: "16px", fontWeight: "600", marginBottom: "14px", color: "#1e293b" }}>
            2. Scoped Knowledge Retrieval Tester
          </h3>
          <p style={{ fontSize: "13px", color: "#64748b", margin: "0 0 16px 0" }}>
            Execute deterministic BM25 lexical queries against the indexed knowledge of scope: <code>{appId || "all"}</code>.
          </p>

          <form onSubmit={handleRetrieve}>
            <div style={{ marginBottom: "12px" }}>
              <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>
                Natural Language Query *
              </label>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="e.g. discount policy for VIP tier members"
                style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
              />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "16px" }}>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>
                  Top-K Results
                </label>
                <input
                  type="number"
                  min="1"
                  max="20"
                  value={topK}
                  onChange={(e) => setTopK(e.target.value)}
                  style={{ width: "100%", padding: "7px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#475569", marginBottom: "4px" }}>
                  Min Relevance Score
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  max="1"
                  value={minScore}
                  onChange={(e) => setMinScore(e.target.value)}
                  style={{ width: "100%", padding: "7px 10px", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>
            </div>

            {retrievalError && (
              <div style={{ padding: "10px", background: "#fef2f2", color: "#b91c1c", borderRadius: "6px", fontSize: "12px", marginBottom: "14px" }}>
                ⚠️ {retrievalError}
              </div>
            )}

            <button
              type="submit"
              disabled={isRetrieving || !query.trim()}
              style={{
                width: "100%",
                padding: "10px",
                background: !query.trim() ? "#94a3b8" : "#0f172a",
                color: "#ffffff",
                border: "none",
                borderRadius: "8px",
                fontWeight: "600",
                fontSize: "14px",
                cursor: !query.trim() || isRetrieving ? "not-allowed" : "pointer",
              }}
            >
              {isRetrieving ? "Retrieving..." : "🔍 Execute Scoped Retrieval"}
            </button>
          </form>
        </div>
      </div>

      {/* Retrieval Results Display */}
      {retrievalResult && (
        <div style={{ ...cardStyle, marginBottom: "20px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
            <h3 style={{ fontSize: "16px", fontWeight: "700", color: "#0f172a", margin: 0 }}>
              Retrieval Results ({retrievalResult.retrieved_chunks.length} Chunks Matched)
            </h3>
            <span
              style={
                retrievalResult.status === "SUCCESS_WITH_RESULTS"
                  ? badgeStyle("#ecfdf5", "#047857", "#10b981")
                  : badgeStyle("#f8fafc", "#64748b", "#cbd5e1")
              }
            >
              {retrievalResult.status}
            </span>
          </div>

          <div style={{ fontSize: "12px", color: "#64748b", marginBottom: "14px", display: "flex", gap: "16px", flexWrap: "wrap" }}>
            <span>Scope: <strong>{retrievalResult.application_id}</strong></span>
            <span>Evaluated Chunks: <strong>{retrievalResult.total_chunks_evaluated}</strong></span>
            <span>Sources: <strong>{retrievalResult.sources?.join(", ") || "None"}</strong></span>
            <span>Fingerprint: <code style={{ color: "#2563eb" }}>{retrievalResult.retrieval_fingerprint?.slice(0, 16)}...</code></span>
          </div>

          {retrievalResult.retrieved_chunks.length === 0 ? (
            <div style={{ padding: "20px", textAlign: "center", color: "#64748b", background: "#f8fafc", borderRadius: "8px" }}>
              No relevant knowledge chunks found matching query '{retrievalResult.query}' under minimum score threshold.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              {retrievalResult.retrieved_chunks.map((chunk, idx) => (
                <div
                  key={chunk.chunk_id}
                  style={{
                    padding: "14px",
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: "8px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                    <div style={{ fontSize: "13px", fontWeight: "700", color: "#1e293b" }}>
                      #{idx + 1} • {chunk.filename} {chunk.page_start ? `(Page ${chunk.page_start})` : ""}
                    </div>
                    <span style={badgeStyle("#eff6ff", "#1d4ed8", "#93c5fd")}>
                      Score: {(chunk.relevance_score * 100).toFixed(1)}%
                    </span>
                  </div>
                  <p style={{ margin: "0 0 8px 0", fontSize: "13px", color: "#334155", whiteSpace: "pre-wrap", lineHeight: "1.5" }}>
                    {chunk.text}
                  </p>
                  <div style={{ fontSize: "11px", color: "#94a3b8", fontFamily: "monospace" }}>
                    Chunk ID: {chunk.chunk_id} • Hash: {chunk.content_hash?.slice(0, 12)}...
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Ingested Documents List */}
      <div style={cardStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
          <h3 style={{ fontSize: "16px", fontWeight: "600", margin: 0, color: "#1e293b" }}>
            3. Ingested Company Documents ({documents.length})
          </h3>
          <span style={{ fontSize: "12px", color: "#64748b" }}>
            Scope: <strong>{appId || "All"}</strong>
          </span>
        </div>

        {docsError && (
          <div style={{ padding: "10px", background: "#fef2f2", color: "#b91c1c", borderRadius: "6px", fontSize: "12px", marginBottom: "12px" }}>
            Error loading documents: {docsError}
          </div>
        )}

        {documents.length === 0 ? (
          <div style={{ padding: "30px", textAlign: "center", color: "#94a3b8", fontSize: "13px", background: "#f8fafc", borderRadius: "8px" }}>
            No company documents uploaded yet for this scope. Upload a PDF or DOCX file above to enable grounded RAG retrieval.
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
              <thead>
                <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0", textAlign: "left" }}>
                  <th style={{ padding: "8px 10px" }}>Filename</th>
                  <th style={{ padding: "8px 10px" }}>Type</th>
                  <th style={{ padding: "8px 10px" }}>Status</th>
                  <th style={{ padding: "8px 10px" }}>Pages</th>
                  <th style={{ padding: "8px 10px" }}>Chunks</th>
                  <th style={{ padding: "8px 10px" }}>Size</th>
                  <th style={{ padding: "8px 10px" }}>Content Hash</th>
                  <th style={{ padding: "8px 10px" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr key={doc.document_id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                    <td style={{ padding: "8px 10px", fontWeight: "600", color: "#0f172a" }}>
                      {doc.filename}
                    </td>
                    <td style={{ padding: "8px 10px" }}>
                      <span style={badgeStyle("#f1f5f9", "#475569", "#cbd5e1")}>{doc.document_type}</span>
                    </td>
                    <td style={{ padding: "8px 10px" }}>
                      <span
                        style={
                          doc.status === "READY"
                            ? badgeStyle("#ecfdf5", "#047857", "#10b981")
                            : doc.status === "DUPLICATE"
                            ? badgeStyle("#eff6ff", "#1d4ed8", "#3b82f6")
                            : doc.status === "EMPTY"
                            ? badgeStyle("#fff7ed", "#c2410c", "#f97316")
                            : badgeStyle("#fef2f2", "#b91c1c", "#ef4444")
                        }
                      >
                        {doc.status}
                      </span>
                    </td>
                    <td style={{ padding: "8px 10px" }}>{doc.page_count}</td>
                    <td style={{ padding: "8px 10px", fontWeight: "600" }}>{doc.chunk_count}</td>
                    <td style={{ padding: "8px 10px", color: "#64748b" }}>
                      {(doc.size_bytes / 1024).toFixed(1)} KB
                    </td>
                    <td style={{ padding: "8px 10px", fontFamily: "monospace", fontSize: "11px", color: "#64748b" }}>
                      {doc.content_hash?.slice(0, 10)}...
                    </td>
                    <td style={{ padding: "8px 10px", display: "flex", gap: "6px" }}>
                      <button
                        onClick={() => handleViewChunks(doc.document_id)}
                        style={{
                          background: expandedDocChunks === doc.document_id ? "#2563eb" : "#f1f5f9",
                          color: expandedDocChunks === doc.document_id ? "#ffffff" : "#1e293b",
                          border: "1px solid #cbd5e1",
                          borderRadius: "4px",
                          padding: "4px 8px",
                          fontSize: "11px",
                          fontWeight: "600",
                          cursor: "pointer",
                        }}
                      >
                        {expandedDocChunks === doc.document_id ? "Hide Chunks" : "View Chunks"}
                      </button>
                      <button
                        onClick={() => handleDelete(doc.document_id)}
                        style={{
                          background: "#fef2f2",
                          color: "#dc2626",
                          border: "1px solid #fecaca",
                          borderRadius: "4px",
                          padding: "4px 8px",
                          fontSize: "11px",
                          fontWeight: "600",
                          cursor: "pointer",
                        }}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Chunks Inspector Panel */}
        {expandedDocChunks && (
          <div style={{ marginTop: "16px", padding: "16px", background: "#f8fafc", border: "1px solid #cbd5e1", borderRadius: "8px" }}>
            <h4 style={{ margin: "0 0 10px 0", fontSize: "14px", fontWeight: "700", color: "#0f172a" }}>
              Indexed Chunks for Document: <code>{expandedDocChunks}</code>
            </h4>
            {isLoadingChunks ? (
              <div style={{ fontSize: "12px", color: "#64748b" }}>Loading chunks...</div>
            ) : activeDocChunks.length === 0 ? (
              <div style={{ fontSize: "12px", color: "#94a3b8" }}>No chunks indexed for this document.</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", maxHeight: "300px", overflowY: "auto" }}>
                {activeDocChunks.map((c) => (
                  <div key={c.chunk_id} style={{ padding: "10px", background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: "6px", fontSize: "12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px", color: "#64748b", fontSize: "11px" }}>
                      <span style={{ fontWeight: "700", color: "#2563eb" }}>Chunk #{c.chunk_index}</span>
                      <span>Page: {c.metadata.page_start || 1} • Length: {c.text.length} chars</span>
                    </div>
                    <div style={{ color: "#334155", whiteSpace: "pre-wrap" }}>{c.text}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
