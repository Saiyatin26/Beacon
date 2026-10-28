#!/usr/bin/env bash
# BEACON Evaluation Master Reproduction Script
# Re-runs all experiments from scratch in strict sequence.

set -e

echo "=== Step 1: Benchmark Preparation & Trigger Rate Quantification ==="
python experiments/run_benchmark_prep.py

echo "=== Step 2: Experiment 1 (Benchmark Profile & Defect Certification) ==="
python experiments/run_experiment_1_benchmark.py

echo "=== Step 3: Experiment 2 (Comparative Baseline Evaluation) ==="
python experiments/run_experiment_2_baselines.py

echo "=== Step 4: Experiment 3 (Evidence Sufficiency & Incomplete Coverage) ==="
python experiments/run_experiment_3_sufficiency.py

echo "=== Step 5: Experiment 4 (Component Ablation & Sensitivity Analysis) ==="
python experiments/run_experiment_4_ablation.py

echo "=== Step 6: Experiment 5 (Runtime & Memory Scaling Microbenchmark) ==="
python experiments/run_experiment_5_scaling.py

echo "=== Step 7: Experiment 6 (Independent Benchmark — Masquerade CBTRN02C) ==="
python experiments/run_experiment_6_masquerade.py

echo "=== Step 8: Manifest Generation & Verification ==="
python experiments/generate_manifest_and_summary.py

echo "=== ALL BEACON EXPERIMENTS COMPLETED SUCCESSFULLY ==="
