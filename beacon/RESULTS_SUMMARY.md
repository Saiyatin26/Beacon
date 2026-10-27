# BEACON Empirical Research Evaluation: Executive Summary Report

**Authoritative Results for Manuscript Revision**  
**Subject System:** AWS CardDemo `COACTUPC` (Legacy CICS COBOL vs Modern Python Reimplementation)  
**Evaluation Scope:** 76 Paired Benchmark Cases (60 Defective across 5 Stratified Categories, 15 Semantics-Preserving Equivalent Controls, 1 Clean Candidate)  
**Evaluated Budgets:** $B = 500$ Transactions (Primary) and $B = 100$ Transactions (Sensitivity)  
**Repetitions:** 5 Independent Deterministic Repetitions with Distinct Seeds (12345..12349)

---

## 1. Summary of Findings by Research Question

### Comment 1 (Seeded-Defect Detection on AWS CardDemo — Tables XIII, XIV, XV, XVII)
- **Defect Detection Performance:** Full BEACON detected **58 of 60 effective defects** in primary evaluation (Recall = **96.67%**, 95% Wilson CI [88.6%, 99.1%]), with **100.0% precision** (58/58) and an F1-score of **0.9831**.
- **Equivalence Preservation:** Across all 16 control cases (15 refactored equivalent variants + 1 clean candidate), Full BEACON correctly certified **16/16 (100.0%)**, producing **0 false alarms** (False Alarm Rate = 0.0%).
- **Hard / Low-Trigger Defects:** Unlike the audited prior study (which relied on 13 targeted tests guaranteeing 100% detection for all tools), the new benchmark includes verified hard edge defects (e.g., `DEF_CALC_11` precision overflow triggering on $\le 0.05\%$ of inputs, `DEF_TX_12` calen=1 redirect triggering on $0.07\%$). These rare defects were missed under finite random input budgets, demonstrating genuine benchmark discrimination.
- **Categorical Breakdown (Table XVII):**
  - `incorrect_calculation`: 11/12 detected (91.7%)
  - `boundary_condition`: 12/12 detected (100.0%)
  - `altered_business_rule`: 12/12 detected (100.0%)
  - `missing_update`: 12/12 detected (100.0%)
  - `incorrect_transaction_handling`: 11/12 detected (91.7%)
  - `equivalent_control`: 15/15 certified (100.0% True Negatives)

### Comment 2 (Baseline Comparison — Table XVI)
- **Advantage Over Simpler Approaches:**
  - **M1 (Output-Only Comparison):** Achieved 96.67% recall but suffered false certifications whenever a defect was not exercised by random inputs. More critically, as shown in Experiment 3, under degraded or incomplete input suites, M1's false certification rate escalates up to **96.7%**, because it cannot distinguish between verified equivalence and missing evidence.
  - **M2 (Unweighted Evidence Scoring, $S = R \ge 0.90$):** Suffered a catastrophic defect detection recall drop to **21.67%–35.00%** (False Certification Rate = **65.0%–78.3%**). Because M2 lacks a regression mismatch gate ($G_6$), any defect with a trigger rate $< 10\%$ yields an agreement score $R \ge 0.90$, causing M2 to blindly certify defective systems.
  - **M3 (BEACON w/o Sufficiency Gates):** Lacks sufficiency gating ($G_1, G_2, G_5$), leaving it vulnerable to certifying under unexercised rule sets.
  - **M4 (Full BEACON):** Successfully eliminated false certifications under degraded evidence by safely issuing `INSUFFICIENT_COVERAGE` whenever rule coverage fell below the 80% threshold.

### Comment 3 (Evidence Sufficiency & Incomplete-Coverage — Tables XVIII, XIX)
- **Behavior Under Evidence Degradation:**
  - When evidence coverage dropped from 100% down to 0% across 6 degradation patterns (random removal, targeted removal, rule omission, unreliability, conflicting observations, and digest corruption), Full BEACON's false certification rate remained strictly at **0.0%**.
  - As coverage dropped below the policy floor ($80\%$), Full BEACON transitioned gracefully from `CERTIFIED` $	o$ `INSUFFICIENT_COVERAGE`.
  - In stark contrast, output-only testing exhibited a monotonic increase in false certifications from 3.3% up to **96.7%**, falsely certifying defective programs whose bugs were simply omitted from testing.

### Comment 4 (Ablations & Weight Sensitivity — Tables XX, XXI, XXII)
- **Component Contributions (Table XX):**
  - Disabling the mismatch gate ($G_6$) tanks defect recall by $>60\%$.
  - Disabling sufficiency gates ($G_1, G_2, G_5$) permits certification under zero or partial rule coverage.
  - Disabling deterministic rule validation (A3) permits ungrounded AI candidate rules to degrade evidence confidence.
- **Weight Sensitivity (Table XXI):**
  - Perturbing weights by $\pm 25\%$ and $\pm 50\%$ across 24 configurations shifted composite scores by an average of only $|\Delta S_{	ext{adj}}| = 0.0084$.
  - Verdict stability was high: the verdict-flip rate across the benchmark was $< 2.6\%$, confirming that certification outcomes are driven by empirical test evidence and safety gates rather than delicate manual weight tuning (Spearman $ho = 0.18$, $p = 0.41$).
- **Integrity Tamper Detection (Table XXII):**
  - Cryptographic verification caught 100% of payload tampering attempts (edited scores, modified status flags, swapped oracle digests, altered threshold fingerprints, and tampered source hashes).

### Comment 5 (Scalability & Second Benchmark — Tables XXIII, XXIV, XXV)
- **Runtime & Memory Scaling:**
  - Evaluated from 100 to 50,000 transaction inputs across up to 50 certified rules.
  - Total runtime scaled with a near-linear power law $O(N^{0.98})$ ($R^2 = 0.998$).
  - Throughput exceeded **42,000 transaction evaluations per second** on local hardware.
  - Paired execution dominated wall-clock time (>92%), while scoring, gates, and SHA-256 verification consumed <5% combined.
- **Second Benchmark Audit:**
  - `masquerade-cobol` was audited locally. While genuine legacy COBOL sources exist, no independently verified runnable modern implementation is available. In accordance with Rule 0, cross-system evaluation is marked `not_done` with documented rationale.

---

## 2. Table Index for Paper Authors

| Table ID | File Name | Recommended Paper Placement |
| :--- | :--- | :--- |
| **Table XIII** | `results/01_benchmark/table13_benchmark_profile.json` | Section V-A: Benchmark Characteristics |
| **Table XIV** | `results/01_benchmark/table14_case_results.json` | Section V-B: Defect-Level Certification Results |
| **Table XV** | `results/01_benchmark/table15_confusion.json` | Section V-B: Confusion Matrix & Metrics |
| **Table XVI** | `results/02_baselines/table16_method_comparison.json` | Section V-C: Baseline Comparison |
| **Table XVII** | `results/01_benchmark/table17_by_category.json` | Section V-B: Performance by Defect Category |
| **Table XVIII** | `results/03_sufficiency/table18_sufficiency_by_coverage.json` | Section V-D: Evidence Sufficiency |
| **Table XIX** | `results/03_sufficiency/table19_verdict_transitions.json` | Section V-D: Verdict Transition Matrix |
| **Table XX** | `results/04_ablation/table20_ablation.json` | Section V-E: Component Ablation Study |
| **Table XXI** | `results/04_ablation/table21_weight_sensitivity.json` | Section V-E: Weight Sensitivity Analysis |
| **Table XXII** | `results/04_ablation/table22_integrity_tampering.json` | Section V-E: Cryptographic Tamper Detection |
| **Table XXIII** | `results/05_scaling/table23_scaling.json` | Section V-F: Scalability Profile |
| **Table XXIV** | `results/05_scaling/table24_stage_breakdown.json` | Section V-F: Runtime Breakdown by Stage |
| **Table XXV** | `results/05_scaling/table25_independent_benchmark.json` | Section V-F: Cross-Benchmark Audit |
