# BEACON Experimental Reproduction Package

This package contains the complete, automated experimental harness reproducing all empirical findings requested for the BEACON research paper (Reviewer Comments 1–5).

## Directory Structure
```
results/
  00_audit.md                               # Step Zero audit of previous Table XVII study
  environment.json                          # Hardware, OS, Python, GnuCOBOL, commit metadata
  deviations.md                             # Protocol decisions and non-negotiable rules
  ground_truth.json                         # Sealed ground-truth specifications for 76 cases
  reference_suite.json                      # Reference contract test suite (clean pair certified)
  review_sheet.csv                          # Full case review sheet with measured trigger rates
  01_benchmark/                             # Comment 1: Seeded-Defect Benchmark
    table13_benchmark_profile.json          # Table XIII: Benchmark profile
    table14_case_results.json               # Table XIV: Defect-level certification results
    table15_confusion.json                  # Table XV: Confusion matrix & defect detection
    table17_by_category.json                # Table XVII: Performance by defect category
    representative_cases.json               # Qualitative representative case traces
  02_baselines/                             # Comment 2: Baseline Comparison
    table16_method_comparison.json          # Table XVI: M1 (Output-only), M2, M3, M4 comparison
    per_case_by_method.json                 # Per-case decisions across all 4 methods
    02_summary.md                           # False certification vs insufficient coverage analysis
  03_sufficiency/                           # Comment 3: Evidence Sufficiency Experiments
    definition.md                           # Formal definition of evidence coverage & factors
    table18_sufficiency_by_coverage.json    # Table XVIII: Coverage vs certification & error rates
    table19_verdict_transitions.json        # Table XIX: Verdict transition matrix under degradation
    curves.json                             # Plot data for Figures 17 & 18
    examples.json                           # Examples of correct refusals vs false certification
  04_ablation/                              # Comment 4: Ablations & Weight Sensitivity
    table20_ablation.json                   # Table XX: Component removal (A0-A4)
    table21_weight_sensitivity.json         # Table XXI: Weight perturbation sweep (Theta 0.70-0.95)
    table22_integrity_tampering.json        # Table XXII: Cryptographic tamper detection results
    weight_vs_error.json                    # L1 distance vs verdict-change rate (Spearman rho)
    weight_flip_cases.json                  # Specific cases flipping under weight variation
    ablation_transitions.json               # Case transitions under component ablation
    ablation_examples.json                  # Representative ablation examples
  05_scaling/                               # Comment 5: Runtime, Memory & Second Benchmark
    table23_scaling.json                    # Table XXIII: Workload scaling (100 to 50,000 cases)
    table24_stage_breakdown.json            # Table XXIV: Processing stage runtime breakdown
    table25_independent_benchmark.json      # Table XXV: Masquerade COBOL audit & rationale
    scaling_curves.json                     # Log-log power law scaling regression
    05_summary.md                           # Empirical scaling limitations
  raw/                                      # 380 raw certificate JSONs (76 cases x 5 reps)
  manifest.json                             # Canonical SHA-256 digests of all output artifacts
```

## Quick Start
```bash
# Run all experiments sequentially
bash run_all.sh
```
