# Experimental Design: Verification of Evidence-Adjusted Behavioral Equivalence Certification

> **Document Type:** Formal Experimental Protocol & Verification Design  
> **System:** BEACON (Behavioral Equivalence Certifier)  
> **Target Mechanism:** Evidence-Adjusted Certification Scoring ($S_{\text{adj}} = R \times Q$)  
> **Execution Harness:** `scripts/run_inventive_step_experiments.py`  
> **Machine-Readable Results:** `benchmarks/evidence_scoring_experiments.json`

---

## 1. Research Objectives and Overview

The objective of this experimental evaluation is to empirically verify the technical effect of BEACON's proposed inventive contribution: **evidence-calibrated equivalence certification**. 

Specifically, this protocol tests whether the mathematical implementation of evidence quality adjustment ($Q$) and adjusted scoring ($S_{\text{adj}}$) reliably:
1. Dampens unearned high behavioral agreement scores when supporting evidence is sparse or degraded.
2. Scales monotonically and predictably with individual evidence factors in accordance with analytical partial derivatives.
3. Adapts dynamically to omitted evidence dimensions via availability-aware weight renormalization without inflating scores.
4. Enforces a strict fail-closed boundary on zero-input or unexecutable test suites.
5. Accurately flags genuine behavioral regressions regardless of evidence quality.
6. Blocks certification when runtime execution reliability falls below acceptable thresholds.
7. Detects post-certification tampering of inputs, source code, or execution records.
8. Yields strictly reproducible, deterministic results across repeated runs.

---

## 2. Experimental Variables & Controls

### 2.1 Controlled Variables
Across all controlled experiments, the following parameters remain constant unless explicitly varied by the experiment design:
- **Baseline Factor Weights:** $\mathbf{w} = [w_1=0.30, w_2=0.20, w_3=0.20, w_4=0.10, w_5=0.10, w_6=0.10]$ (Sum $= 1.00$).
- **Certification Threshold ($\Theta$):** $0.85$ (Adjusted score requirement).
- **Minimum Execution Reliability Floor:** $0.90$.
- **Hashing Function:** SHA-256 with canonical JSON key serialization.

### 2.2 Independent Variables
- Raw behavioral agreement score ($R \in [0.0, 1.0]$).
- Individual evidence quality factors ($f_i \in [0.0, 1.0]$ for $i \in \{1, \dots, 6\}$).
- Factor availability mask ($\mathcal{A} \subseteq \{1, \dots, 6\}$).
- Number of evaluated test cases ($N_{\text{eval}} \ge 0$).
- Integrity status of test input vectors and source trees.

### 2.3 Dependent Variables
- Aggregate evidence quality score ($Q \in [0.0, 1.0]$).
- Final evidence-adjusted certification score ($S_{\text{adj}} \in [0.0, 1.0]$).
- Gate status (Pass / Fail for Zero-Input, Reliability, Integrity).
- Certification verdict (`CERTIFIED`, `NOT_EQUIVALENT`, `INSUFFICIENT_COVERAGE`, `INCONCLUSIVE`, `BLOCKED`).

---

## 3. Detailed Experiment Protocols (EXP-01 through EXP-08)

### Experiment 1: Raw versus Adjusted Score Verification (EXP-01)
- **Hypothesis $H_1$:** For any fixed high raw agreement score ($R = 0.95$), reducing evidence quality factors will strictly penalize the adjusted score $S_{\text{adj}} = R \times Q$ in exact accordance with the multiplicative model.
- **Scenarios:**
  1. *Perfect Evidence:* $f_i = 1.0 \implies Q = 1.0 \implies S_{\text{adj}} = 0.95$.
  2. *Degraded Evidence:* $f_1=0.7, f_2=0.5, f_3=0.8, f_4=0.9, f_5=1.0, f_6=1.0 \implies Q = 0.775 \implies S_{\text{adj}} = 0.73625$.
  3. *Poor Evidence:* $f_1=0.2, f_2=0.3, f_3=0.5, f_4=0.6, f_5=1.0, f_6=1.0 \implies Q = 0.510 \implies S_{\text{adj}} = 0.4845$.
  4. *Moderate Agreement, Perfect Evidence:* $R = 0.80, Q = 1.0 \implies S_{\text{adj}} = 0.80$.
  5. *Zero Agreement, Perfect Evidence:* $R = 0.0, Q = 1.0 \implies S_{\text{adj}} = 0.0$.
- **Verification Criterion:** Absolute difference $|S_{\text{adj}}^{\text{observed}} - S_{\text{adj}}^{\text{expected}}| \le 10^{-6}$.

### Experiment 2: One-Factor Sensitivity Analysis (EXP-02)
- **Hypothesis $H_2$:** Varying a single evidence factor $f_k \in \{1.0, 0.75, 0.50, 0.25, 0.0\}$ while holding all other factors at $1.0$ produces a linear change in quality score with slope exactly equal to the factor's normalized weight:
  $$\frac{\Delta Q}{\Delta f_k} = w_k \implies \Delta S_{\text{adj}} = R \cdot w_k \cdot \Delta f_k$$
- **Evaluated Factors:**
  - Oracle Coverage ($w_1 = 0.30$)
  - Input Space Coverage ($w_2 = 0.20$)
  - Execution Reliability ($w_3 = 0.20$)
  - Oracle Confidence ($w_4 = 0.10$)
  - Input-Set Integrity ($w_5 = 0.10$)
  - Source-Hash Integrity ($w_6 = 0.10$)
- **Verification Criterion:** Linear regression $R^2 = 1.000$ and zero deviation from theoretical values across all step evaluations.

### Experiment 3: Missing Evidence & Dynamic Renormalization (EXP-03)
- **Hypothesis $H_3$:** When factors are omitted from measurement, dynamic weight renormalization calculates $\hat{w}_i = w_i / \sum_{j \in \mathcal{A}} w_j$ such that remaining factors sum to $1.0$, while complete absence of evidence ($\mathcal{A} = \emptyset$) fails closed.
- **Scenarios:**
  - Omit Oracle Confidence ($w_4 = 0.10$ removed; remaining weights normalized over $0.90$).
  - Omit Source Hash & Input Integrity ($w_5, w_6$ removed; remaining weights normalized over $0.80$).
  - Single active factor (Oracle Coverage only; normalized weight becomes $1.0$).
  - Total omission of all factors ($\mathcal{A} = \emptyset \implies$ `EvidenceScoringError` raised).
- **Verification Criterion:** Exact match with renormalized analytical weights; successful exception capture on empty sets.

### Experiment 4: Zero Evaluated Inputs Fail-Closed Verification (EXP-04)
- **Hypothesis $H_4$:** A test run with zero discovered or executed inputs ($N_{\text{total}} = 0$ or $N_{\text{eval}} = 0$) must never be assigned a default score of $1.0$; it must evaluate to raw score $0.0$, quality score $0.0$, adjusted score $0.0$, and certification status `INSUFFICIENT_COVERAGE` / `BLOCKED`.
- **Scenarios:**
  - Empty input list passed to `scorer.evidence_adjusted_score`.
  - Zero inputs processed by `CertificationEngine.certify_run`.
- **Verification Criterion:** Raw score is strictly $0.0$; certification verdict is blocked; no passing certificate is issued.

### Experiment 5: Genuine Behavioral Mismatch Detection (EXP-05)
- **Hypothesis $H_5$:** Controlled semantic differences between legacy and modern program outputs must be accurately detected by the normalization and comparison engine, driving the raw score and adjusted score downward and triggering a `NOT_EQUIVALENT` verdict.
- **Scenarios:**
  - Zero mismatches ($100\%$ agreement $\implies R = 1.0$).
  - 1 mismatch out of 10 cases ($90\%$ agreement $\implies R = 0.90$).
  - 5 mismatches out of 10 cases ($50\%$ agreement $\implies R = 0.50$).
  - 10 mismatches out of 10 cases ($0\%$ agreement $\implies R = 0.00$).
- **Verification Criterion:** Mismatch count matches ground truth injection; verdict transitions from `CERTIFIED` to `NOT_EQUIVALENT` when agreement drops below policy threshold.

### Experiment 6: Unreliable Execution Degradation (EXP-06)
- **Hypothesis $H_6$:** Environmental failures, adapter crashes, and process timeouts degrade the Execution Reliability factor $f_3$, causing $S_{\text{adj}}$ to drop and triggering the mandatory reliability policy gate ($f_3 < 0.90 \implies$ Blocked).
- **Scenarios:**
  - $10/10$ successful executions ($f_3 = 1.0 \implies$ Pass).
  - $8/10$ successful executions, 2 timeouts ($f_3 = 0.80 \implies$ Reliability gate trip, Blocked).
  - $5/10$ successful executions, 5 adapter crashes ($f_3 = 0.50 \implies$ Reliability gate trip, Blocked).
- **Verification Criterion:** Gate trips whenever $f_3 < 0.90$; certification is denied even if surviving executions had $100\%$ agreement.

### Experiment 7: Cryptographic Tamper Detection (EXP-07)
- **Hypothesis $H_7$:** Modifying any canonical test case value, changing source files, or altering certificate payloads after generation invalidates the SHA-256 Merkle digest and triggers an immediate tamper alert.
- **Scenarios:**
  - Authentic baseline: Hash matches.
  - Candidate payload tampering: Mutate single field in one test input $\implies$ SHA-256 digest mismatch detected.
  - Source file tampering: Mutate single byte in legacy COBOL program $\implies$ Source hash mismatch detected.
  - Certificate payload tampering: Alter raw score from $0.80$ to $1.00$ in certificate dictionary $\implies$ Canonical hash mismatch detected.
- **Verification Criterion:** Integrity verification returns `False`; certification engine rejects tampered artifacts.

### Experiment 8: Deterministic Scoring & Hashing Reproducibility (EXP-08)
- **Hypothesis $H_8$:** Executing the identical input set, factor weights, and execution evidence across repeated independent trials produces bitwise-identical canonical hashes and floating-point scores.
- **Scenarios:**
  - 100 consecutive executions of identical test runs.
- **Verification Criterion:** Exact equality of $S_{\text{adj}}$, $R$, $Q$, and SHA-256 hashes across all 100 trials ($100\%$ deterministic reproducibility).

---

## 4. Execution and Reproduction Instructions

To reproduce the complete experimental suite and generate fresh machine-readable benchmark records:

```powershell
# Set Python path to backend and workspace root
$env:PYTHONPATH="backend;."

# Execute the standalone experiment harness
python scripts/run_inventive_step_experiments.py

# Execute the automated regression tests covering EXP-01 through EXP-08
pytest backend/tests/test_evidence_scoring.py -v
```
