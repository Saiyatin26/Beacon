# Experimental Results: Empirical Evaluation of BEACON Evidence-Adjusted Certification

> **Document Type:** Empirical Results & Technical Verification Report  
> **System:** BEACON (Behavioral Equivalence Certifier) — Full Mode  
> **Execution Date:** 2026-10-11  
> **Source Harness:** `scripts/run_inventive_step_experiments.py`  
> **Source Artifact:** `benchmarks/evidence_scoring_experiments.json`  
> **Status:** 8 of 8 Controlled Experiments PASSED (100% Pass Rate)

---

## 1. Executive Summary

This report documents the empirical results of eight controlled experiments conducted to evaluate the technical effect of BEACON's evidence-adjusted equivalence certification mechanism ($S_{\text{adj}} = R \times Q$).

The experiments prove that:
1. **Evidence Quality Penalization:** An unearned high behavioral agreement score ($R = 0.95$) is dampened down to $S_{\text{adj}} = 0.4845$ when empirical evidence is poor ($Q = 0.510$).
2. **Analytical Monotonicity & Sensitivity:** Each evidence factor changes the composite score linearly with slope strictly equal to its weight ($\Delta Q = w_k \cdot \Delta f_k$), with zero deviation from theoretical models.
3. **Availability-Aware Robustness:** Omitting evidence factors triggers dynamic renormalization across active factor weights, whereas complete evidence omission fails closed with an `EvidenceScoringError`.
4. **Zero-Input Protection:** A test set containing zero inputs produces raw score $0.0$, quality score $0.0$, and adjusted score $0.0$, triggering an immediate `INSUFFICIENT_COVERAGE` blocking gate.
5. **Regression Isolation:** True behavioral mismatches drop the agreement score and trigger a `NOT_EQUIVALENT` / `NOT_CERTIFIED` verdict, preventing certification regardless of high evidence quality.
6. **Execution Flakiness Protection:** Degraded adapter reliability ($50\%$ failure rate) depresses evidence quality and trips certification threshold gates.
7. **Tamper Proofing:** Altering certificate scores, policy versions, or execution status invalidates the canonical SHA-256 digest and is immediately detected.
8. **Deterministic Reproducibility:** Repeated evaluation over 100 trials produces bitwise-identical digests and floating-point scores.

---

## 2. Detailed Results by Experiment

### Experiment 1: Raw versus Adjusted Score Verification (EXP-01)
- **Objective:** Verify that $S_{\text{adj}} = R \times Q$ accurately penalizes raw behavioral agreement when evidence quality varies.
- **Outcome:** **PASSED** (All 5 scenarios matched theoretical expectations with zero error).

| Scenario | Raw Score ($R$) | Quality Score ($Q$) | Expected $S_{\text{adj}}$ | Observed $S_{\text{adj}}$ | Absolute Error | Verdict |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Perfect Evidence, High Agreement** | $0.9500$ | $1.0000$ | $0.950000$ | $0.950000$ | $0.000000$ | **PASS** |
| **Degraded Evidence, High Agreement** | $0.9500$ | $0.7750$ | $0.736250$ | $0.736250$ | $0.000000$ | **PASS** |
| **Poor Evidence, High Agreement** | $0.9500$ | $0.5100$ | $0.484500$ | $0.484500$ | $0.000000$ | **PASS** |
| **Moderate Agreement, Perfect Evidence** | $0.8000$ | $1.0000$ | $0.800000$ | $0.800000$ | $0.000000$ | **PASS** |
| **Zero Agreement, Perfect Evidence** | $0.0000$ | $1.0000$ | $0.000000$ | $0.000000$ | $0.000000$ | **PASS** |

---

### Experiment 2: One-Factor Sensitivity Analysis (EXP-02)
- **Objective:** Verify that $\frac{\partial Q}{\partial f_k} = w_k$ across each of the 6 normalized evidence factors.
- **Outcome:** **PASSED** (All 30 steps across 6 factors strictly adhered to the linear model).

#### Factor Sensitivity Breakdown:
1. **Oracle Coverage ($w_1 = 0.30$):**
   - $f_1 = 1.00 \implies Q = 1.0000, S_{\text{adj}} = 1.0000$
   - $f_1 = 0.75 \implies Q = 0.9250, S_{\text{adj}} = 0.9250$ ($\Delta Q = -0.0750$)
   - $f_1 = 0.50 \implies Q = 0.8500, S_{\text{adj}} = 0.8500$ ($\Delta Q = -0.1500$)
   - $f_1 = 0.25 \implies Q = 0.7750, S_{\text{adj}} = 0.7750$ ($\Delta Q = -0.2250$)
   - $f_1 = 0.00 \implies Q = 0.7000, S_{\text{adj}} = 0.7000$ ($\Delta Q = -0.3000$)
2. **Input Coverage ($w_2 = 0.20$):**
   - Step values: $1.00 \to 0.00 \implies Q: 1.000 \to 0.800$ (Slope $= 0.200$).
3. **Execution Reliability ($w_3 = 0.20$):**
   - Step values: $1.00 \to 0.00 \implies Q: 1.000 \to 0.800$ (Slope $= 0.200$).
4. **Oracle Confidence ($w_4 = 0.15$):**
   - Step values: $1.00 \to 0.00 \implies Q: 1.000 \to 0.850$ (Slope $= 0.150$).
5. **Input-Set Integrity ($w_5 = 0.10$):**
   - Step values: $1.00 \to 0.00 \implies Q: 1.000 \to 0.900$ (Slope $= 0.100$).
6. **Source-Hash Integrity ($w_6 = 0.05$):**
   - Step values: $1.00 \to 0.00 \implies Q: 1.000 \to 0.950$ (Slope $= 0.050$).

---

### Experiment 3: Missing Evidence & Dynamic Renormalization (EXP-03)
- **Objective:** Verify dynamic weight renormalization $\hat{w}_i = w_i / \sum_{j \in \mathcal{A}} w_j$ when factors are unmeasured.
- **Outcome:** **PASSED** (Weights sum to $1.0$ across active factors; total omission raises exception).

| Omitted Factor | Omitted Weight | Active Weight Sum | Observed $Q$ | Expected $Q$ | Observed $S_{\text{adj}}$ | Verdict |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| `oracle_coverage` | $0.30$ | $0.70$ | $0.8000$ | $0.8000$ | $0.6800$ | **PASS** |
| `input_coverage` | $0.20$ | $0.80$ | $0.8000$ | $0.8000$ | $0.6800$ | **PASS** |
| `execution_reliability` | $0.20$ | $0.80$ | $0.8000$ | $0.8000$ | $0.6800$ | **PASS** |
| `oracle_confidence` | $0.15$ | $0.85$ | $0.8000$ | $0.8000$ | $0.6800$ | **PASS** |
| `input_set_integrity` | $0.10$ | $0.90$ | $0.8000$ | $0.8000$ | $0.6800$ | **PASS** |
| `source_hash_integrity` | $0.05$ | $0.95$ | $0.8000$ | $0.8000$ | $0.6800$ | **PASS** |
| **All Factors Omitted** | $1.00$ | $0.00$ | *Exception Raised* | `EvidenceScoringError` | N/A | **PASS** |

---

### Experiment 4: Zero Evaluated Inputs Fail-Closed Verification (EXP-04)
- **Objective:** Demonstrate that zero evaluated cases cannot receive a passing score or certificate.
- **Outcome:** **PASSED**.
  - `scorer.evidence_adjusted_score` with empty inputs returned: $0.0$ (previously defaulted to $1.0$).
  - Certification Engine Status: `INSUFFICIENT_COVERAGE`.
  - Certified: `False`.
  - Blocking Reason: `"Zero evaluated inputs: Equivalence certification requires genuine input evidence"`.

---

### Experiment 5: Genuine Behavioral Mismatch Detection (EXP-05)
- **Objective:** Verify that a known semantic regression prevents certification even when evidence quality is high.
- **Outcome:** **PASSED**.
  - Injected Output Deviation: $0.300000$ (Threshold $= 0.050000$).
  - Regressions Detected: $1$.
  - Raw Behavioral Score: $0.7000$ ($70.0\%$).
  - Evidence-Adjusted Score: $61.3\%$ (Policy Threshold $= 95.0\%$).
  - Certification Status: `NOT_CERTIFIED`.
  - Certified: `False`.
  - Blocking Reasons:
    1. `"Observed deviation (0.300000) exceeds resolved dynamic threshold (0.050000)"`
    2. `"Evidence-adjusted score (61.3%) is below the policy threshold (95.0%)"`

---

### Experiment 6: Unreliable Execution Degradation (EXP-06)
- **Objective:** Verify that flakiness and runtime errors degrade the composite score and block certification.
- **Outcome:** **PASSED**.
  - Injected Adapter Failure Rate: $50\%$ ($f_3 = 0.50$).
  - Evidence Quality Score ($Q$): $0.7500$ (Depressed by $-25\%$).
  - Evidence-Adjusted Score ($S_{\text{adj}}$): $0.7500$.
  - Certification Status: Blocked (`certified = False`).
  - Blocking Reason: `"Evidence-adjusted score (75.0%) is below the policy threshold (90.0%)"`.

---

### Experiment 7: Cryptographic Tamper Detection (EXP-07)
- **Objective:** Verify detection of post-certification modifications to scores, policy, or status.
- **Outcome:** **PASSED**.
  - Baseline Certificate Verification: `True` (SHA-256 integrity intact).
  - Score Tamper Detected (`score: 0.85 -> 0.99`): `True` (Digest mismatch).
  - Policy Version Tamper Detected (`policy_version: 1.0 -> 2.0`): `True` (Digest mismatch).
  - Status Tamper Detected (`status: INCONCLUSIVE -> CERTIFIED`): `True` (Digest mismatch).

---

### Experiment 8: Deterministic Scoring & Hashing Reproducibility (EXP-08)
- **Objective:** Verify bitwise identity of hashes and floating-point scores across repeated executions.
- **Outcome:** **PASSED**.
  - Evaluations: 100 independent trials.
  - Adjusted Score ($S_{\text{adj}}$): $0.83444$ across all 100 trials ($0.000$ variance).
  - Evidence Quality Score ($Q$): $0.90700$ across all 100 trials ($0.000$ variance).
  - Canonical Input Set Hash: `48496ee815c18246e492209cee002c840c120ae49de7218d46a387239c0a04af` across all 100 trials.
  - Bitwise Identical: `True` (100% deterministic reproducibility).

---

## 3. Comparison Against Unadjusted Baseline

| Evaluation Scenario | Baseline (Raw Score Only) | Proposed (Evidence-Adjusted $S_{\text{adj}}$) | Behavioral Impact & Technical Benefit |
|:---|:---:|:---:|:---|
| **1 Test Case, High Agreement** | **1.00 (100%)** | **0.50 (50.0%)** | Baseline falsely declares equivalence; BEACON penalizes inadequate coverage ($Q = 0.50$). |
| **Flaky Adapters (50% Crash Rate)** | **1.00 (100%)** | **0.75 (75.0%)** | Baseline ignores crash rate on completed runs; BEACON trips reliability gate. |
| **Zero Evaluated Inputs** | **1.00 (100%)** | **0.00 (0.0%)** | Baseline had zero-division defect yielding 1.0; BEACON fails closed. |
| **Genuine Business Mismatch** | **0.70 (70%)** | **0.61 (61.3%)** | Both detect mismatch; BEACON prevents certificate issuance via multiple gates. |
| **Post-Issuance Score Alteration** | Untracked | **Rejected (Tamper)** | Baseline trusts JSON fields; BEACON validates SHA-256 canonical Merkle root. |
