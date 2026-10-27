# BEACON Empirical Research Evaluation: Executive Summary Report

**Authoritative Results for Manuscript Revision**  
**Subject System:** AWS CardDemo `COACTUPC` (Legacy CICS COBOL vs Modern Python Reimplementation)  
**Reference Methodology:** Validated High-Throughput Python Companion Reference Model (cross-validated against WSL GnuCOBOL 3.1.2.0 on representative CICS transactions; reported accurately as Python-reference-model evaluation)  
**Evaluation Scope:** 76 Paired Benchmark Cases (60 Defective across 5 Stratified Categories, 15 Semantics-Preserving Equivalent Controls, 1 Clean Candidate)  
**Evaluated Budgets:** $B = 500$ Transactions (Primary) and $B = 100$ Transactions (Sensitivity)  
**Repetitions:** 5 Independent Deterministic Repetitions with Distinct Seeds (12345..12349)

---

## 1. Summary of Findings by Research Question

### Comment 1 (Seeded-Defect Detection on AWS CardDemo — Tables XIII, XIV, XV, XVII)
- **Defect Detection Performance:** Full BEACON detected **45 of 60 effective defects** in primary evaluation (Recall = **75.00%**, 95% Wilson CI [62.8%, 84.2%]), with **100.0% precision** (45/45) and an F1-score of **0.8571**.
- **Equivalence Preservation:** Across all 16 control cases (15 refactored equivalent variants + 1 clean candidate), Full BEACON correctly certified **16/16 (100.0%)**, producing **0 false alarms** (False Alarm Rate = 0.0%).
- **Hard / Low-Trigger Defects:** Unlike the audited prior study (which relied on 13 targeted tests guaranteeing 100% detection for all tools), the new benchmark includes verified hard edge defects (e.g., `DEF_CALC_11` precision overflow, `DEF_TX_12` calen=1 redirect, and unexposed database updates in `missing_update`). These rare defects were missed under finite random input budgets ($B=500$), demonstrating genuine benchmark discrimination.
- **Categorical Breakdown (Table XVII):**
  - `incorrect_calculation`: 10/12 detected (83.3%)
  - `boundary_condition`: 8/12 detected (66.7%)
  - `altered_business_rule`: 11/12 detected (91.7%)
  - `missing_update`: 5/12 detected (41.7%)
  - `incorrect_transaction_handling`: 11/12 detected (91.7%)
  - `equivalent_control`: 15/15 certified (True Negatives) (100.0%)

### Comment 2 (Baseline Comparison — Table XVI)
- **Advantage Over Simpler Approaches:**
  - **M1 (Output-Only Comparison):** Achieved 75.0% recall (45/60) but suffered false certifications whenever a defect was not exercised by random inputs (FCR = 25.0%). Under degraded input suites (Experiment 3), M1's false certification rate escalates up to **100.0%**, because it cannot distinguish between verified equivalence and missing evidence.
  - **M2 (Unweighted Evidence Scoring, $S = R \ge 0.90$):** Suffered a catastrophic defect detection recall drop to **31.67%–33.33%** (False Certification Rate = **66.67%–68.33%**). Because M2 lacks a regression mismatch gate ($G_6$), any defect with a trigger rate $< 10\%$ yields an agreement score $R \ge 0.90$, causing M2 to blindly certify defective systems ($p = 1.16 \times 10^{-7}$).
  - **M3 (BEACON w/o Sufficiency Gates):** Lacks sufficiency gating ($G_1, G_2, G_5$), leaving it vulnerable to certifying under unexercised rule sets.
  - **M4 (Full BEACON):** Successfully eliminated false certifications under degraded evidence by safely issuing `INSUFFICIENT_COVERAGE` whenever rule coverage fell below the 80% threshold.

### Comment 3 (Evidence Sufficiency & Incomplete-Coverage — Tables XVIII, XIX)
- **Behavior Under Evidence Degradation:**
  - Evaluated across 6 empirical degradation conditions (random input removal, targeted input removal, rule set omission, execution timeouts / observation removal, contradictory observations, and cryptographic digest corruption).
  - When rule coverage or observation reliability dropped below policy floors, Full BEACON transitioned to `INSUFFICIENT_COVERAGE`, keeping false certifications at **0.0%**.
  - In stark contrast, output-only testing exhibited a monotonic increase in false certifications from 25.0% up to **100.0%**, falsely certifying defective programs whose bugs were simply omitted from testing.

### Comment 4 (Ablations & Weight Sensitivity — Tables XX, XXI, XXII)
- **Component Contributions (Table XX):**
  - Production evaluation path invoked with individual components isolated.
  - Ablations A0, A1, A2, A4 are classified as `complete`.
  - Ablation A3 (deterministic rule validation) is classified as `partial` because specification rules in this benchmark are static and cannot be dynamically isolated without artificial parameter injection; deterministic rule validation is unit-tested in `backend/rules/validator.py`.
  - Disabling the mismatch gate ($G_6$) tanks defect recall from 75.00% to 33.33%.
  - Disabling sufficiency gates ($G_1, G_2, G_5$) permits certification under zero or partial rule coverage.
- **Weight Sensitivity (Table XXI):**
  - Perturbing weights by $\pm 25\%$ and $\pm 50\%$ across 24 configurations shifted composite scores by an average of only $|\Delta S_{\text{adj}}| = 0.0084$.
  - Verdict stability was high: the verdict-flip rate across the benchmark was $< 2.6\%$, confirming that certification outcomes are driven by empirical test evidence and safety gates rather than delicate manual weight tuning.
- **Integrity Tamper Detection (Table XXII):**
  - Cryptographic verification caught 100% of payload tampering attempts (edited scores, modified status flags, swapped oracle digests, altered threshold fingerprints, and tampered source hashes).

### Comment 5 (Scalability & Second Benchmark — Tables XXIII, XXIV, XXV)
- **Component Processing Microbenchmark (Tables XXIII, XXIV):**
  - Evaluated across scaling workloads from 100 to 50,000 transaction inputs and 5 to 50 certified rules across 5 repetitions on local hardware.
  - Total runtime scaled with empirical power law.
  - Paired execution of genuine candidate modules (`candidate_CTRL_00.py`) dominated wall-clock time (>93%), while AST rule validation via `RuleValidator` and SHA-256 verification consumed <5% combined.
  - Unsupported end-to-end distributed system scalability claims have been explicitly removed.
- **Second Benchmark Audit (Table XXV):**
  - `masquerade-cobol` was audited locally. While genuine legacy COBOL sources exist, no independently verified runnable modern implementation is available. In accordance with Rule 0, cross-system evaluation is marked `not_done` with documented rationale.

---

## 2. Table Index for Paper Authors

| Table ID | File Name | Recommended Paper Placement | Status |
| :--- | :--- | :--- | :--- |
| **Table XIII** | `results/01_benchmark/table13_benchmark_profile.json` | Section V-A: Benchmark Characteristics | `complete` |
| **Table XIV** | `results/01_benchmark/table14_case_results.json` | Section V-B: Defect-Level Certification Results | `complete` |
| **Table XV** | `results/01_benchmark/table15_confusion.json` | Section V-B: Confusion Matrix & Metrics | `complete` |
| **Table XVI** | `results/02_baselines/table16_method_comparison.json` | Section V-C: Baseline Comparison | `complete` |
| **Table XVII** | `results/01_benchmark/table17_by_category.json` | Section V-B: Performance by Defect Category | `complete` |
| **Table XVIII** | `results/03_sufficiency/table18_sufficiency_by_coverage.json` | Section V-D: Evidence Sufficiency | `complete` |
| **Table XIX** | `results/03_sufficiency/table19_verdict_transitions.json` | Section V-D: Verdict Transition Matrix | `complete` |
| **Table XX** | `results/04_ablation/table20_ablation.json` | Section V-E: Component Ablation Study | `complete` (A3: `partial`) |
| **Table XXI** | `results/04_ablation/table21_weight_sensitivity.json` | Section V-E: Weight Sensitivity Analysis | `complete` |
| **Table XXII** | `results/04_ablation/table22_integrity_tampering.json` | Section V-E: Cryptographic Tamper Detection | `complete` |
| **Table XXIII** | `results/05_scaling/table23_scaling.json` | Section V-F: Scalability Profile (Microbenchmark) | `complete` |
| **Table XXIV** | `results/05_scaling/table24_stage_breakdown.json` | Section V-F: Runtime Breakdown by Stage | `complete` |
| **Table XXV** | `results/05_scaling/table25_independent_benchmark.json` | Section V-F: Cross-Benchmark Audit | `not_done` (Rule 0 Rationale) |
