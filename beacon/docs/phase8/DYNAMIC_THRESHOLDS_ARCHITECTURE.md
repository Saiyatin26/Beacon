# BEACON V2 — Phase 8: Dynamic / Evidence-Driven Thresholds Architecture

## 1. Executive Summary
Phase 8 answers the core behavioral evaluation question:
> **"Given the observed behavioral evidence and established behavioral expectations, what amount of deviation is acceptable, and why?"**

Phase 8 does **NOT** discover new rules (Phase 6), decide authoritative specification contents (Phase 7), execute targets (Phase 3), or implement Phase 9 RAG / Phase 10 LLM certification. Its sole responsibility is to evaluate differences between Reference and Target behavioral observations using evidence-based, deterministic, bounded, explainable, and auditable tolerance thresholds.

---

## 2. Core Architectural Flow

```
                      REFERENCE EVIDENCE
                              │
                              ▼
                      Evidence Validation
                              │
                              ▼
                      Sample Sufficiency
                              │
                          ┌───┴───┐
                          │       │
                         NO      YES
                          │       │
                          ▼       ▼
                   INCONCLUSIVE  Estimator
                                  │
                                  ▼
                            Raw Threshold
                                  │
                                  ▼
                            Min / Max Bounds
                                  │
                                  ▼
                          Frozen Resolution
                                  │
                                  ▼
                         Reference vs Target
                                  │
                                  ▼
                            Final Verdict
```

---

## 3. Key Invariants & Guarantees

### 3.1 Anti-Target-Contamination Rule
Thresholds derived from evidence are calculated strictly and exclusively from **Reference / Historical Evidence**. Target observations are strictly prohibited from participating in threshold calculation, preventing circular self-justification (i.e. expanding tolerance to force a target pass).

### 3.2 Evidence Sufficiency & Fail-Closed Behavior
If reference evidence contains fewer observations than `minimum_samples`, the threshold resolution status becomes `INSUFFICIENT_EVIDENCE`. Evaluation yields `INCONCLUSIVE` unless an explicit, deterministic fallback strategy and value are configured.

### 3.3 Strict Bounds Enforcement
Dynamic thresholds support optional lower and upper bounds (`minimum_bound`, `maximum_bound`). Raw calculated thresholds are clamped deterministically into this range:
$$\text{final\_threshold} = \min(\max(\text{raw\_threshold}, \text{minimum\_bound}), \text{maximum\_bound})$$

### 3.4 Threshold Freezing & Traceability
Once resolved for an evaluation run, the threshold decision is frozen into an immutable `ThresholdResolution` with a canonical SHA-256 fingerprint.

---

## 4. Supported Threshold Strategies

| Strategy | Semantics |
|---|---|
| **`FIXED`** | Explicit fixed numerical tolerance parameter. |
| **`ABSOLUTE`** | Absolute numerical delta: $|T - R| \le \text{tolerance}$. |
| **`RELATIVE`** | Relative deviation: $\frac{|T - R|}{|R|} \le \text{tolerance}$ (with zero-reference safety). |
| **`PERCENTAGE`** | Percentage deviation: $\frac{|T - R|}{|R|} \times 100 \le \text{tolerance}$. |
| **`STATISTICAL`** | Variance / spread estimator over reference observations. |
| **`EVIDENCE_DERIVED`** | Dynamic tolerance computed from reference variance with bounds and outlier handling. |

---

## 5. Statistical Estimators

- **`MEAN_STDDEV`**: $k \times \sigma$, where $\sigma = \sqrt{\frac{1}{N-1}\sum (x_i - \bar{x})^2}$.
- **`IQR_ROBUST`**: $k \times (Q_3 - Q_1)$.
- **`MAX_OBSERVED_DELTA`**: $\max(|x_i - \bar{x}|)$.
- **`PERCENTILE_95`**: 95th percentile of observed deviations.
- **`RANGE_FRACTION`**: $k \times (\max(x) - \min(x))$.

---

## 6. Outlier Handling Policies

- **`NONE`**: All valid observations are used.
- **`CLIPPED`**: Observations outside $[Q_1 - 1.5 \times \text{IQR}, Q_3 + 1.5 \times \text{IQR}]$ are clamped to the fences.
- **`ROBUST`**: Observations outside $[Q_1 - 1.5 \times \text{IQR}, Q_3 + 1.5 \times \text{IQR}]$ are excluded.

---

## 7. Conservative Verdict Aggregation

- $\text{PASS} + \text{PASS} \rightarrow \text{EQUIVALENT}$
- $\text{PASS} + \text{FAIL} \rightarrow \text{DIFFERENT}$
- $\text{PASS} + \text{INCONCLUSIVE} \rightarrow \text{INCONCLUSIVE}$
- $\text{FAIL} + \text{INCONCLUSIVE} \rightarrow \text{DIFFERENT}$
- $\text{BLOCKED OracleSet} \rightarrow \text{INCONCLUSIVE}$
