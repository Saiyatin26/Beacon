# BEACON Empirical Research Evaluation: Final Completion Report

**Report Date:** 2026-10-27  
**System Under Test:** AWS CardDemo `COACTUPC` (CICS COBOL vs Modern Python Reimplementation)  
**Evaluation Standard:** IEEE Transactions on Software Engineering Empirical Standards  
**Integrity Rule:** Rule 0 (Zero fabricated numbers; all metrics derived from executed runs)

---

## 1. Requirement-by-Requirement Completion Matrix

| Requirement ID | Description | Artifact Paths | Execution Evidence | Status |
|---|---|---|---|---|
| **REQ-01** | Audit previous 20-mutant Table XVII study | `results/00_audit.md` | Verified 13 targeted tests bundled in test suite; 0 equivalent controls | `complete` |
| **REQ-02** | Environment snapshot | `results/environment.json` | Real hardware, Python 3.11.9, GnuCOBOL 3.1.2.0, commit SHA | `complete` |
| **REQ-03** | Protocol deviations & budgets | `results/deviations.md` | $B=500$ primary, $B=100$ sensitivity, fixed base seed 12345 | `complete` |
| **REQ-04** | Ground truth specification | `results/ground_truth.json` | 76 cases measured over 10,000 random inputs; source SHA-256 digests | `complete` |
| **REQ-05** | Reference contract suite | `results/reference_suite.json` | 10 contract test cases with input and output digests | `complete` |
| **REQ-06** | Manual review sheet | `results/review_sheet.csv` | Full per-case spreadsheet with trigger rates and code diff summaries | `complete` |
| **REQ-07** | Table XIII: Benchmark profile | `results/01_benchmark/table13_benchmark_profile.json` | 60 defects (5 categories) + 15 equivalent + 1 clean candidate | `complete` |
| **REQ-08** | Table XIV: Case-level results | `results/01_benchmark/table14_case_results.json` | 76 cases across 5 repetitions with mean scores, Wilson CIs, outcomes | `complete` |
| **REQ-09** | Table XV: Confusion matrix & metrics | `results/01_benchmark/table15_confusion.json` | Recall 75.00%, Precision 100.0%, F1 0.8571, False Alarm Rate 0.0% | `complete` |
| **REQ-10** | Table XVII: Category results | `results/01_benchmark/table17_by_category.json` | Per-category detection breakdowns and CI intervals | `complete` |
| **REQ-11** | Representative case studies | `results/01_benchmark/representative_cases.json` | Diffs, triggering inputs, and reasoning for key cases | `complete` |
| **REQ-12** | Raw certificate traces | `results/raw/CERT-*.json` | 380 per-repetition raw certificate JSONs (76 cases × 5 repetitions) | `complete` |
| **REQ-13** | Table XVI: Baseline comparison | `results/02_baselines/table16_method_comparison.json` | M1–M4 across 5 reps, threshold sweep (0.80, 0.90, 0.95), McNemar tests | `complete` |
| **REQ-14** | Per-case baseline outputs | `results/02_baselines/per_case_by_method.json` | Individual per-case outputs across all 4 methods | `complete` |
| **REQ-15** | Baseline narrative report | `results/02_baselines/02_summary.md` | Detailed narrative analysis of baseline results | `complete` |
| **REQ-16** | Sufficiency definitions | `results/03_sufficiency/definition.md` | Formal definitions of input coverage, rule coverage, sufficiency factors | `complete` |
| **REQ-17** | Table XVIII: Sufficiency results | `results/03_sufficiency/table18_sufficiency_by_coverage.json` | 6 degradation patterns across 7 coverage levels {100%..0%} | `complete` |
| **REQ-18** | Table XIX: Verdict transitions | `results/03_sufficiency/table19_verdict_transitions.json` | Transition matrices as evidence coverage drops below policy floor | `complete` |
| **REQ-19** | Sufficiency curves & examples | `results/03_sufficiency/curves.json`, `examples.json` | Quantitative FCR vs coverage data and failure examples | `complete` |
| **REQ-20** | Table XX: Component ablation | `results/04_ablation/table20_ablation.json` | Ablations A1–A7 measuring gate and component contributions (A3 marked partial) | `complete` (A3: `partial`) |
| **REQ-21** | Table XXI: Weight sensitivity | `results/04_ablation/table21_weight_sensitivity.json` | 24 weight configurations (±25%, ±50%) with flip rates | `complete` |
| **REQ-22** | Table XXII: Cryptographic tampering | `results/04_ablation/table22_integrity_tampering.json` | 9 real verifier tamper tests on frozen `CertificationArtifact` | `complete` |
| **REQ-23** | Table XXIII: Scalability benchmarks | `results/05_scaling/table23_scaling.json` | Workloads W1..W4 (100 to 50,000 inputs) across 5 repetitions; microbenchmark | `complete` |
| **REQ-24** | Table XXIV: Stage breakdown | `results/05_scaling/table24_stage_breakdown.json` | Execution, discovery, reconciliation, verification timings | `complete` |
| **REQ-25** | Table XXV: Second benchmark | `results/05_scaling/table25_independent_benchmark.json` | Documented audit of masquerade-cobol lacking verified Python modernizations | `not_done` |
| **REQ-26** | Master manifest & verification | `results/manifest.json` | SHA-256 digests and generation commands for all artifacts | `complete` |
| **REQ-27** | Master execution script | `run_all.sh`, `README_EXPERIMENTS.md` | Reproducibility shell script and documentation | `complete` |
| **REQ-28** | Executive paper summary | `RESULTS_SUMMARY.md` | Publication-ready empirical synthesis | `complete` |

---

## 2. Previously Completed and Validated Artifacts

- `results/00_audit.md`: Audited prior 20-mutant study.
- `results/environment.json`: Hardware and platform specifications.
- `results/deviations.md`: Initial evaluation protocol parameters.
- `results/03_sufficiency/definition.md`: Mathematical definitions of evidence sufficiency.
- `results/05_scaling/table23_scaling.json`: Real empirical wall-clock scaling timings across 5 repetitions.
- `results/05_scaling/table24_stage_breakdown.json`: Stage breakdown timings.
- `results/05_scaling/table25_independent_benchmark.json`: Documented `not_done` status for masquerade-cobol.
- `results/05_scaling/scaling_curves.json`, `05_summary.md`.

---

## 3. Previously Existing but Invalid or Repaired Artifacts

- **Output Wrapper Benchmark (Repaired):** The initial `experiments/benchmark_cases.py` implemented defect cases and equivalent controls by calling `reference_runner(inp)` and modifying output dictionary fields or returning the reference output directly.
- **Repair Executed:** All 76 cases were completely rebuilt as **genuine standalone source files** under `experiments/mutants/` (`candidate_DEF_CALC_01.py` .. `candidate_EQUIV_15.py`, `candidate_CTRL_00.py`). Each mutant modifies actual source AST statements (e.g. inside `_validate_inputs`, `_apply_acct_input`, `_apply_cust_input`, `_commit_changes`, `_initial_display`), compiles cleanly, and executes via `process_account_update(...)`.
- **Sealed Ground Truth (Repaired):** Measured trigger rates on 10,000 random inputs using genuine source mutants, sealing `results/ground_truth.json` and `results/review_sheet.csv` with individual source file SHA-256 digests.

---

## 4. New Artifacts Generated by This Run

- `results/00_completion_audit.md`: Detailed audit identifying wrapper issues, reference harness status, and completion matrix.
- `experiments/build_source_mutants.py`: Generator script that synthesized and compile-validated all 76 candidate Python files.
- `experiments/mutants/candidate_*.py`: 76 standalone source mutant files.
- `results/source_mutants_manifest.json`: Manifest recording canonical and mutated SHA-256 hashes, changed lines, and operators for all 76 mutants.
- `results/FINAL_COMPLETION_REPORT.md`: This comprehensive completion report.

---

## 5. Experiments Actually Executed and Run Identifiers

1. **Benchmark Ground Truth Preparation:**
   - Script: `experiments/run_benchmark_prep.py`
   - Inputs: 10,000 independent random transactions (Seed 12345)
   - Verified 0 divergences on all 16 equivalent controls; identified 15 hard defects.
2. **Experiment 1 (Benchmark & Defect Detection):**
   - Script: `experiments/run_experiment_1_benchmark.py`
   - Seeds: 12345, 12346, 12347, 12348, 12349
   - Raw traces: 380 certificate JSONs in `results/raw/CERT-*-REP*-*.json`
   - Primary Budget: $B = 500$
3. **Experiment 2 (Baseline Comparisons):**
   - Script: `experiments/run_experiment_2_baselines.py`
   - Methods: M1 (Output-Only), M2 (Unweighted Score), M3 (No Sufficiency Gates), M4 (Full BEACON)
   - Seeds: 12345..12349; Thresholds $\Theta \in \{0.80, 0.90, 0.95\}$
4. **Experiment 3 (Evidence Sufficiency):**
   - Script: `experiments/run_experiment_3_sufficiency.py`
   - Evaluated 6 degradation patterns across 7 coverage levels $\{100\%, 90\%, 75\%, 50\%, 25\%, 10\%, 0\%\}$ across 5 seeds.
5. **Experiment 4 (Ablation, Weights, Cryptographic Tampering):**
   - Script: `experiments/run_experiment_4_ablation.py`
   - Ablations A1–A7, 24 weight configurations, 9 cryptographic tamper scenarios.
6. **Experiment 5 (Scalability & Profiling):**
   - Script: `experiments/run_experiment_5_scaling.py`
   - Workloads W1 (100) to W4 (50,000) across 5 repetitions.

---

## 6. Experiments Incomplete and Precise Reasons

- **Table XXV (Independent Benchmark on Second Program):**
  - **Status:** `not_done` per Rule 0.
  - **Audit Rationale:** The candidate external repository `masquerade-cobol` at `c:\Users\Navaneeth Motamarry\masquerade-cobol` contains legacy COBOL programs (`COTRN01C.cbl`, `COTRN02C.cbl`, etc.) and BMS map definitions, but lacks independently verified modern Python implementations. Creating an ad-hoc unverified modernization would violate Rule 0 (fabricated results). This is honestly documented in `results/05_scaling/table25_independent_benchmark.json`.

---

## 7. Benchmark Construction & Reference Execution Status

- **Reference Execution Environment:**
  - The repository possesses a functional WSL Ubuntu GnuCOBOL 3.1.2.0 harness (`cics_runner.py`), verified passing 3/3 tests in `backend/tests/test_real_cobol_end_to_end.py`.
  - The harness emulates CICS screen and data interactions via environment variables and stdout capture.
  - For massive-scale differential testing (190,000 transaction executions across 5 repetitions), the high-throughput Python companion model (`coactupc.py` + `carddemo_data.py`) was used as the reference runner to enable timely execution.
  - Both references were cross-validated on representative cases, confirming identical control flow and BMS screen field updates.

---

## 8. Baseline Results, Ties, and Negative Findings

- **M4 vs M1 (Output-Only Testing):**
  - Under complete test suites ($B=500$) with random inputs, M4 and M1 achieve identical defect recall (**75.00%**, 45/60 detected).
  - Both methods missed 15 subtle edge defects that require specific compound trigger conditions (e.g. `DEF_CALC_11` requiring credit limits $\ge 99999.00$, `DEF_TX_12` requiring `EIBCALEN == 1`).
  - **Ties & Negative Result:** When inputs happen to trigger defects, simple output checking is sufficient and ties BEACON's detection. BEACON does not magically detect unexercised code without targeted test generation.
  - **Where BEACON Outperforms M1:** Under incomplete evidence (Experiment 3), M1 falsely certifies up to **100%** of defective programs whose trigger inputs are omitted, whereas BEACON issues `INSUFFICIENT_COVERAGE` (0% false certifications).
- **M2 (Unweighted Scoring) Catastrophic Failure:**
  - M2 ($S = R \ge 0.90$) defect recall collapsed to **31.67% – 33.33%** (False Certification Rate = **66.67% – 68.33%**).
  - Without mismatch gate $G_6$, any defect triggering on $<10\%$ of inputs achieves $R \ge 0.90$ and is certified!
  - Paired McNemar test confirms M4 is significantly superior to M2 ($p = 1.16 \times 10^{-7}$).

---

## 9. Evidence Sufficiency, Ablation, Sensitivity, and Integrity Status

- **Evidence Sufficiency (Tables XVIII, XIX):**
  - When rule coverage or observation coverage drops below 80%, BEACON transitions to `INSUFFICIENT_COVERAGE`, keeping false certifications at 0.0%.
  - Output-only testing suffers monotonic false certification growth up to 100%.
- **Component Ablations (Table XX):**
  - Disabling mismatch gate $G_6$ (A4) causes defect recall to drop from 75.00% to 33.33%.
  - Disabling sufficiency gates $G_1, G_2, G_5$ (A1) permits certifications under incomplete suites.
- **Weight Sensitivity (Table XXI):**
  - Across 24 weight configurations (±25%, ±50%), mean score shift was $|\Delta S_{\text{adj}}| = 0.0084$, with a verdict flip rate of only $2.6\%$. Verdicts are driven by test evidence, not arbitrary weight tuning.
- **Cryptographic Tamper Detection (Table XXII):**
  - Caught 100% of payload tamper attempts (score edits, status flags, policy hashes, oracle digests, threshold fingerprints). Full cryptographic forgery without root key is undetected by local verification alone, matching the formal threat model.

---

## 10. Validation Results

- **JSON Validation:** All 13 primary JSON tables validate against strict schemas.
- **Metric Verification:**
  - $TP + FC + IC + RI = 45 + 15 + 0 + 0 = 60$ ($N_{\text{defective}}$)
  - $TN + FP + IC + RI = 16 + 0 + 0 + 0 = 16$ ($N_{\text{equivalent}}$)
  - Wilson 95% score confidence intervals verified.
- **Manifest Validation:** 100% of the 31 artifacts in `results/manifest.json` have verified matching SHA-256 digests.

---

## 11. Deviations, Exclusions, and Limitations

1. **Transaction Budget:** Primary evaluation used $B=500$ random transactions, with sensitivity at $B=100$. Under $B=500$, random testing does not exercise rare edge triggers ($<0.1\%$).
2. **Second Program Benchmark:** Retained as `not_done` due to lack of verified modern Python implementations in `masquerade-cobol`.
3. **Dual Reference Model:** Differential testing was executed against the validated Python reference companion, cross-checked against GnuCOBOL.

---

## 12. IEEE Paper Claims Supported by Validated Results

1. BEACON achieves 100% precision (0 false alarms) on semantics-preserving equivalent refactorings.
2. Unweighted evidence scoring ($S = R \ge \Theta$) fails catastrophically (FCR $>65\%$) without mismatch gating.
3. BEACON's sufficiency gates eliminate false certifications under degraded or incomplete test evidence by failing closed to `INSUFFICIENT_COVERAGE`.
4. BEACON's composite scoring is robust to weight perturbations (verdict flip rate $<3\%$).
5. BEACON scales with sub-linear wall-clock complexity ($\beta = 0.6835$), reaching $>28,000$ inputs/second.

---

## 13. IEEE Paper Claims That Must Be Corrected, Qualified, or Omitted

1. **Correct Prior 100% Recall Claim:** The prior Table XVII claim of 20/20 (100%) defect detection for all methods was an artifact of bundled targeted tests. In the new benchmark under random testing, defect recall is **75.00%** under $B=500$.
2. **Qualify M1 Superiority Claim:** BEACON does not outperform output-only testing on defect detection when tests trigger defects; BEACON's decisive advantage is **refusal to certify when evidence is incomplete**.
3. **Omit Claim of Cross-Application Evaluation:** Do not claim evaluation on programs beyond CardDemo `COACTUPC`; clearly state that multi-program evaluation remains future work due to legacy benchmark availability.
