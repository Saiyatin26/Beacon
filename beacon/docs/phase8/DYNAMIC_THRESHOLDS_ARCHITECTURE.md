# BEACON V2 — Phase 8: Dynamic / Evidence-Driven Thresholds Architecture

## 1. Executive Summary
Phase 8 answers the core behavioral evaluation question:
> **"Given the observed behavioral evidence and established behavioral expectations, what amount of deviation is acceptable, and why?"**

Phase 8 does **NOT** discover new rules (Phase 6), mutate authoritative specifications (Phase 7), execute targets (Phase 3), or implement Phase 9 RAG / Phase 10 LLM certification. Its sole responsibility is to evaluate differences between Reference and Target behavioral observations using evidence-based, deterministic, bounded, explainable, and auditable tolerance thresholds.

---

## 2. Core Architectural Flow

```
                      Phase 3 Execution
                              │
                      Evidence Records / Sessions
                              │
                              ├──────────────────────┐
                              ▼                      ▼
                     Reference Evidence        Target Evidence
                              │                      │
                              ▼                      │
                      Evidence Validation            │
                              │                      │
                              ▼                      │
                      Sample Sufficiency             │
                              │                      │
                          ┌───┴───┐                  │
                          │       │                  │
                         NO      YES                 │
                          │       │                  │
                          ▼       ▼                  │
                   INCONCLUSIVE  Estimator           │
                                  │                  │
                                  ▼                  │
                            Raw Threshold            │
                                  │                  │
                                  ▼                  │
                            Min / Max Bounds         │
                                  │                  │
                                  ▼                  │
                          Frozen Resolution          │
                                  │                  │
                                  ├──────────────────┘
                                  ▼
                         Phase 7 OracleSet (Read-Only)
                                  │
                                  ▼
                         Behavioral Evaluator
                                  │
                                  ▼
                          Authoritative Verdict
                                  │
                                  ▼
                           Frontend Display
```

---

## 3. Key Invariants & Hardening Guarantees

### 3.1 Real Evidence Wiring & Role Validation (Issue A)
When an evaluation request specifies `reference_session_id` and `target_session_id`, the evaluator loads actual execution records from the Phase 3 `execution_repository` and `evidence_store`.
- Session roles are strictly validated (`REFERENCE` vs `TARGET`). Role confusion is rejected with HTTP 400.
- Missing sessions are rejected with HTTP 404 and never silently substituted with fabricated empty collections.
- Legitimate captured empty observations (`{}`) remain distinguishable from capture failures.

### 3.2 Authoritative Backend & Display-Only Frontend (Issue B)
The backend REST API (`/api/v2/evaluation/advanced`) is the sole authoritative evaluation engine. The frontend sandbox functions exclusively as a simulation preview (clearly badged as non-authoritative) and submits evaluation requests to the backend for authoritative verdicts.

### 3.3 Evidence-Sensitive Resolution Identity (Issue C)
The canonical SHA-256 resolution fingerprint and `resolution_id` are derived from:
- Difference metric
- Policy configuration hash
- Stably sorted (canonical) `evidence_ids`
- Numerical observations
Different evidence sets with identical sample counts produce distinct fingerprints.

### 3.4 Complete Metric Implementation (Issue D)
All 7 advertised metrics are implemented end-to-end:
1. `ABSOLUTE_DIFF`: $|T - R| \le \text{tol}$
2. `RELATIVE_DIFF`: $\frac{|T - R|}{|R|} \le \text{tol}$ (zero-safe)
3. `PERCENTAGE_DIFF`: $\frac{|T - R|}{|R|} \times 100 \le \text{tol}$ (zero-safe)
4. `COUNT_DIFF`: $|int(T) - int(R)| \le \text{tol}$
5. `LATENCY_DIFF`: $|T_{ms} - R_{ms}| \le \text{tol}$
6. `SEQUENCE_DISTANCE`: Normalized Levenshtein distance $\le \text{tol}$
7. `STRUCTURAL_SIMILARITY`: Jaccard key/path structural difference $\le \text{tol}$

### 3.5 Strict Policy Validation (Issue E)
Pydantic model validation strictly rejects:
- Negative tolerances or values
- `minimum_bound > maximum_bound`
- Negative `minimum_samples`
- Non-finite numbers (`NaN`, `Inf`)

### 3.6 Fail-Closed Sufficiency (Issue F)
If reference evidence contains fewer observations than `minimum_samples`, the resolution status becomes `INSUFFICIENT_EVIDENCE` and evaluation yields `INCONCLUSIVE` (unless an explicit fallback strategy is configured). Missing evidence never produces `PASS` or `0.0` delta.

### 3.7 Anti-Target-Contamination Rule (Issue G)
Thresholds derived from evidence are calculated strictly and exclusively from **Reference Evidence**. Target observations are strictly prohibited from participating in threshold calculation (`TargetContaminationError`). Extreme target observations cannot inflate tolerances.

### 3.8 Phase 7 OracleSet Authority & Immutability (Issue H)
The Phase 7 `OracleSet` is read-only. Rules, consequences, and hashes are immutable during Phase 8 evaluation.

---

## 4. Conservative Verdict Aggregation

- $\text{PASS} + \text{PASS} \rightarrow \text{EQUIVALENT}$
- $\text{PASS} + \text{FAIL} \rightarrow \text{DIFFERENT}$
- $\text{PASS} + \text{INCONCLUSIVE} \rightarrow \text{INCONCLUSIVE}$
- $\text{FAIL} + \text{INCONCLUSIVE} \rightarrow \text{DIFFERENT}$
- $\text{BLOCKED OracleSet} \rightarrow \text{INCONCLUSIVE}$
