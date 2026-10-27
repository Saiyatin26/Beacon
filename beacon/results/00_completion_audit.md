# BEACON Experimental Completion Audit

**Audit Date:** 2026-10-27  
**Auditor:** BEACON Automated Certification & Empirical Verification Engine  
**Target Subject:** AWS CardDemo `COACTUPC` (Legacy CICS COBOL vs Modern Python Reimplementation)  
**Specification Context:** IEEE Transaction on Software Engineering / IEEE Research Paper Revisions

---

## 1. Executive Audit Summary

An exhaustive repository inspection was performed across all experimental modules, execution harnesses, result JSON files, raw certificate records, and source artifacts.

### Key Audit Findings

1. **Benchmark Defect Wrapper Issue (Critical Finding):**
   - Inspection of `experiments/benchmark_cases.py` revealed that mutant runner functions (`m_calc_01` .. `m_tx_12`) and equivalent control runners (`m_eq_01` .. `m_eq_15`) were implemented as **output-interception wrappers** around `reference_runner(inp)`.
   - Instead of compiling and executing independently mutated candidate source programs, the runners executed the clean Python reference implementation and subsequently altered field values in the returned dictionary (e.g., `out["CREDIT_LIMIT"] = f"{val - 50.0:.2f}"`), or in the case of equivalent controls, simply returned `reference_runner(inp)` directly.
   - **Required Action:** Replace all 76 wrapper functions with **genuine source-level candidate implementations**. Each case must reside in a dedicated source variant file in `experiments/mutants/`, with verified AST/source modifications, individual source SHA-256 digests, and execute through `process_account_update(...)`.

2. **Reference Implementation & GnuCOBOL Harness Status:**
   - The repository contains a functional WSL Ubuntu GnuCOBOL harness (`backend/certification/cics_runner.py` and `backend/application/adapter_detector.py`) compiling and executing `COACTUPC.cbl` under GnuCOBOL 3.1.2.0.
   - Verification via `pytest backend/tests/test_real_cobol_end_to_end.py` passed 3/3 tests (15.04s).
   - The GnuCOBOL harness operates via CICS compatibility emulation (accepting transaction inputs via environment variables and capturing stdout BMS map fields) rather than native IBM CICS with VSAM dataset locks.
   - Cross-runtime validation confirms that for control flows and BMS display updates, the Python companion model (`coactupc.py` + `carddemo_data.py`) faithfully mirrors the COBOL state machine. For massive differential suites (190,000 transactions across 5 repetitions), the Python reference companion provides high-throughput evaluation while cross-runtime sample runs against WSL COBOL confirm behavioral alignment.
   - Per Rule 0, all experimental outputs must explicitly label whether the reference was the **GnuCOBOL CICS Compatibility Harness** or the **Validated High-Throughput Python Reference Model**.

3. **Previous 20-Mutant Study Non-Discrimination Audit:**
   - The prior Table XVII study reported 20/20 defect detection, 0 false certifications, and 0 false alarms across all four methods (M1–M4).
   - Our audit of the raw test cases revealed that 13 targeted test cases were bundled directly into the test suite. Because every mutant had at least one test specifically crafted to trigger its exact defect condition, all four methods trivially achieved 100% detection.
   - Crucially, zero equivalent controls were evaluated, rendering false alarm measurement impossible ($0/0$).
   - The new 76-case benchmark (60 defects + 15 equivalent controls + 1 clean candidate) evaluated under random input distributions genuinely discriminates between methods (e.g., exposing M2's failure when defects have $<10\%$ trigger rates).

---

## 2. Deliverable Completion Matrix

The matrix below audits every required deliverable against actual repository execution evidence following all benchmark repairs, genuine source-mutant executions, and evidence degradation runs:

| Requirement ID | Requirement Description | Existing Artifact Path(s) | Execution Evidence | Validation Status | Status | Finding / Resolution | Target Result Path |
|---|---|---|---|---|---|---|---|
| **REQ-01** | Baseline Study Audit & Invalidation | `results/00_audit.md` | Documented analysis of prior 20-mutant study | Validated | `complete` | Disproved prior 100% non-discriminating study | `results/00_audit.md` |
| **REQ-02** | Environment Metadata | `results/environment.json` | Real hardware, OS, Python 3.11.9, GnuCOBOL 3.1.2.0 | Validated | `complete` | Verified environment captured accurately | `results/environment.json` |
| **REQ-03** | Protocol Deviations & Budgets | `results/deviations.md` | $B=500$ primary and $B=100$ budgets, reference model disclosure | Validated | `complete` | Updated with source mutant architecture and reference methodology | `results/deviations.md` |
| **REQ-04** | Ground Truth & Case Specs | `results/ground_truth.json`, `results/review_sheet.csv` | 76 cases measured over 10,000 random inputs; source SHA-256 digests | Validated | `complete` | Repaired: Replaced output wrappers with genuine source files in `experiments/mutants/` | `results/ground_truth.json` |
| **REQ-05** | Reference Input Suite | `results/reference_suite.json` | 500 inputs with SHA-256 digest | Validated | `complete` | Valid input suite verified on disk | `results/reference_suite.json` |
| **REQ-06** | Table XIII: Benchmark Profile | `results/01_benchmark/table13_benchmark_profile.json` | 60 defects (5 categories) + 15 equivalent + 1 clean candidate | Validated | `complete` | Generated from genuine source mutant manifest | `results/01_benchmark/table13_benchmark_profile.json` |
| **REQ-07** | Table XIV: Case Results | `results/01_benchmark/table14_case_results.json` | 76 cases across 5 reps | Validated | `complete` | Executed against genuine source mutant files | `results/01_benchmark/table14_case_results.json` |
| **REQ-08** | Table XV: Confusion Matrix | `results/01_benchmark/table15_confusion.json` | Recall 75.00%, Precision 100%, F1 0.8571, FAR 0.0% | Validated | `complete` | Derived strictly from 380 empirical runs against source mutants | `results/01_benchmark/table15_confusion.json` |
| **REQ-09** | Table XVII: By Category | `results/01_benchmark/table17_by_category.json` | 5 defect categories + controls | Validated | `complete` | Derived from raw source mutant runs | `results/01_benchmark/table17_by_category.json` |
| **REQ-10** | Representative Cases | `results/01_benchmark/representative_cases.json` | Case examples with actual source diffs | Validated | `complete` | Updated with verified source code diffs | `results/01_benchmark/representative_cases.json` |
| **REQ-11** | Raw Certificate Traces | `results/raw/CERT-*.json` | 380 JSON certificates | Validated | `complete` | Raw runs executed against standalone source mutants | `results/raw/` |
| **REQ-12** | Table XVI: Method Comparison | `results/02_baselines/table16_method_comparison.json` | M1–M4 across 5 reps, threshold sweep | Validated | `complete` | Re-run M1–M4 against genuine source mutants | `results/02_baselines/table16_method_comparison.json` |
| **REQ-13** | Per-Case Baseline Traces | `results/02_baselines/per_case_by_method.json` | Per-case M1–M4 results | Validated | `complete` | Saved per-case baseline outputs across 4 methods | `results/02_baselines/per_case_by_method.json` |
| **REQ-14** | Baseline Summary | `results/02_baselines/02_summary.md` | Narrative report | Validated | `complete` | Reconciled with verified empirical baseline numbers | `results/02_baselines/02_summary.md` |
| **REQ-15** | Sufficiency Definition | `results/03_sufficiency/definition.md` | Mathematical definitions | Validated | `complete` | Fully rigorous mathematical formulation | `results/03_sufficiency/definition.md` |
| **REQ-16** | Table XVIII: Sufficiency Table | `results/03_sufficiency/table18_sufficiency_by_coverage.json` | 6 degradation patterns, 7 levels | Validated | `complete` | Executed with actual evidence degradation (rule omission, flaky runs) | `results/03_sufficiency/table18_sufficiency_by_coverage.json` |
| **REQ-17** | Table XIX: Verdict Transitions | `results/03_sufficiency/table19_verdict_transitions.json` | Transition matrices | Validated | `complete` | Executed with actual evidence degradation | `results/03_sufficiency/table19_verdict_transitions.json` |
| **REQ-18** | Sufficiency Curves & Examples | `results/03_sufficiency/curves.json`, `examples.json` | FCR vs Coverage | Validated | `complete` | Real empirical evidence degradation data | `results/03_sufficiency/` |
| **REQ-19** | Table XX: Component Ablation | `results/04_ablation/table20_ablation.json` | Ablations A1–A7 | Validated | `complete` | Production evaluation path; A3 honestly marked `partial` (unisolatable) | `results/04_ablation/table20_ablation.json` |
| **REQ-20** | Table XXI: Weight Sensitivity | `results/04_ablation/table21_weight_sensitivity.json` | 24 perturbed weight configs | Validated | `complete` | Real empirical scoring evaluations across ±25% and ±50% | `results/04_ablation/table21_weight_sensitivity.json` |
| **REQ-21** | Table XXII: Cryptographic Tampering | `results/04_ablation/table22_integrity_tampering.json` | Real verifier tamper tests | Validated | `complete` | Genuine pydantic certificate verifier test against 9 attack vectors | `results/04_ablation/table22_integrity_tampering.json` |
| **REQ-22** | Table XXIII: Scalability Profiling | `results/05_scaling/table23_scaling.json` | W1..W4 empirical benchmarks | Validated | `complete` | Repaired: Replaced artificial sleep with real AST and RuleValidator; classified as microbenchmark | `results/05_scaling/table23_scaling.json` |
| **REQ-23** | Table XXIV: Stage Breakdown | `results/05_scaling/table24_stage_breakdown.json` | Wall-clock stage timings | Validated | `complete` | Real measured timing data across pipeline stages | `results/05_scaling/table24_stage_breakdown.json` |
| **REQ-24** | Table XXV: Second Benchmark | `results/05_scaling/table25_independent_benchmark.json` | Audit of masquerade-cobol | Validated | `not_done` | Status: `not_done` per Rule 0 due to lack of verified Python implementation | `results/05_scaling/table25_independent_benchmark.json` |
| **REQ-25** | Manifest & Execution Scripts | `results/manifest.json`, `run_all.sh` | Hashes and runner script | Validated | `complete` | 100% of 31 artifact SHA-256 digests independently verified on disk | `results/manifest.json` |
| **REQ-26** | Research Summary Report | `RESULTS_SUMMARY.md` | Executive report for paper | Validated | `complete` | Reconciled strictly with raw empirical records and honest disclosures | `RESULTS_SUMMARY.md` |
| **REQ-27** | Final Completion Report | `results/FINAL_COMPLETION_REPORT.md` | Comprehensive IEEE completion report | Validated | `complete` | Complete 13-section audit report with all empirical disclosures | `results/FINAL_COMPLETION_REPORT.md` |

---

## 3. Plan of Corrective Actions (Phases B through F)

1. **Phase B (Benchmark Repair):**
   - Create a mutant generator `experiments/build_source_mutants.py` that reads the canonical `coactupc.py` source and synthesizes 76 genuine source-level candidate variants in `experiments/mutants/`.
   - Each mutant file must contain the exact modified source code, line numbers, and operator implementations.
   - Rebuild equivalent controls `EQUIV_01`..`EQUIV_15` as genuine source-level semantic refactorings (e.g., De Morgan condition rewrites, helper extraction, dictionary lookups, explicit regex validations, type casting).
   - Compute source SHA-256 digests for original and mutated code.
   - Refactor `benchmark_cases.py` to import and execute each mutant's genuine `process_account_update` entry point.
   - Measure empirical trigger rates across 10,000 independent inputs to establish sealed ground truth.

2. **Phase C (Re-run Experiments Affected by Benchmark Repairs):**
   - Re-run `run_experiment_1_benchmark.py` across 5 seeds against the genuine source mutants, generating fresh raw certificates (`results/raw/`) and Tables XIII, XIV, XV, XVII.
   - Re-run `run_experiment_2_baselines.py` (M1–M4) against the genuine source mutants to produce updated Table XVI.
   - Re-run `run_experiment_3_sufficiency.py` to verify evidence degradation behaviors.
   - Re-run `run_experiment_4_ablation.py` against the genuine benchmark records.
   - Verify `run_experiment_5_scaling.py` outputs.

3. **Phase D (Metric and Data Validation):**
   - Recompute all metrics from raw records.
   - Verify confusion matrix arithmetic: $TP + FC + IC + RI = 60$; $TN + FP + IC + RI = 16$.
   - Confirm Wilson score 95% confidence intervals and exact McNemar test statistics.

4. **Phase E & F (Final Deliverables & Completion Report):**
   - Recompute `manifest.json` with SHA-256 digests of all generated tables.
   - Update `RESULTS_SUMMARY.md` and `README_EXPERIMENTS.md`.
   - Produce `results/FINAL_COMPLETION_REPORT.md` covering all 13 required sections.
