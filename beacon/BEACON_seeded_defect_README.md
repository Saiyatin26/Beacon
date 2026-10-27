# BEACON Seeded-Defect Evaluation Reproduction Guide (Table XVII)

This document provides complete instructions to independently replicate and verify the empirical findings presented in **Table XVII** of the BEACON research paper.

---

## 1. Overview & Evaluation Architecture

Table XVII evaluates four behavioral equivalence certification and verification methods on the enterprise modernization benchmark **AWS CardDemo Account Update (`COACTUPC`)**:

1. **Differential (random):** Pseudo-random input generator producing syntactically and semantically valid account transactions according to the CICS contract, executing differential comparison across legacy COBOL and modern Python implementations.
2. **BEACON, $R$ only:** Raw behavioral agreement scoring ($R = m/N$) evaluated against standard policy threshold ($0.80$), without evidence discounting or safety gating.
3. **BEACON Full:** The complete BEACON V2 verification pipeline implementing evidence-adjusted scoring ($S_{\text{adj}} = R \times Q$), dynamic policy thresholds, and fail-closed safety gates (execution reliability floor, input integrity, regression absence, and source hash integrity).
4. **LLM-as-judge:** Direct model audit using frontier model (`gemini-flash-lite-latest` via Google Gemini API) given program specifications and side-by-side execution trace evidence with zero ground-truth label leakage.

---

## 2. Dataset Structure

The benchmark evaluates $N = 30$ cases:
- **Verified Effective Defects ($K = 20$):** 20 isolated mutations across 8 distinct failure categories:
  - Arithmetic & Monetary Calculations (`ARITH_01`, `ARITH_02`)
  - Conditional Branching (`BRANCH_01`, `BRANCH_02`)
  - Input Validation Logic (`VALID_01`, `VALID_02`, `VALID_03`)
  - Boundary Conditions (`BOUND_01`, `BOUND_02`, `BOUND_03`)
  - Error-Handling Transitions (`ERR_01`, `ERR_02`)
  - Database Transactions & State Updates (`TX_01`, `TX_02`, `TX_03`)
  - State Machine Lifecycle (`STATE_01`, `STATE_02`, `STATE_03`)
  - Observable Side Effects & Field Mapping (`SIDE_01`, `SIDE_02`)
- **Excluded Mutations (2):**
  - `EXCL_SYNTAX_01`: Excluded due to compile-time syntax errors (not effective runtime defect).
  - `EXCL_EQUIV_01`: Excluded due to semantic equivalence (no observable behavioral divergence).
- **Paired Controls (10):**
  - Unmodified, verified correct implementations (`CTRL_01` to `CTRL_10`) evaluated under identical test harnesses to detect False Alarms.

---

## 3. Environment & Prerequisites

- **Host OS:** Windows 10/11 x64
- **Python:** 3.11.x
- **Legacy Runtime:** WSL Ubuntu with GnuCOBOL 3.1.2.0 (`cobc`)
- **Key Dependencies:** `pydantic>=2.0`, `pytest>=8.0`, `hypothesis>=6.0`, `python-dotenv`
- **LLM Credentials:** Google Gemini API Key configured in `beacon/.env` (`GEMINI_API_KEY`)

---

## 4. Quick Reproduction Steps

### Step 1: Set up the environment
```bash
cd beacon
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Ensure dependencies are installed
pip install -r requirements.txt
```

### Step 2: Verify Legacy COBOL Compiler
```bash
wsl cobc --version
# Output should verify GnuCOBOL 3.1.2.0
```

### Step 3: Run the Complete Seeded-Defect Evaluation
```bash
python seeded_defects/run_table_xvii_evaluation.py
```

### Step 4: Run the Isolated LLM-as-Judge Evaluation (Rerun)
```bash
python seeded_defects/rerun_llm_judge.py
```

This command:
1. Loads the 20 verified mutations and 10 control programs.
2. Executes the LLM audit queries with bounded exponential backoff and rate-limit pacing.
3. Generates all versioned LLM rerun artifacts (`llm_judge_rerun_results.json`, `.csv`, `.md`, `.txt`).
4. Updates the LLM row in `BEACON_seeded_defect_results.json`.

---

## 5. Metric Formulations

- **$\text{Detected}/K$:** Fraction of verified effective defects ($K=20$) correctly rejected.
- **False Certification Rate:** $\frac{\text{Defective cases incorrectly Certified}}{\text{Total defective cases evaluated } (K=20)}$.
- **False Alarm Rate:** $\frac{\text{Correct control cases incorrectly Rejected}}{\text{Total control cases evaluated } (10)}$.
- **Time (s):** Measured elapsed wall-clock execution time under isolated process conditions.

---

## 6. Table XVII Summary (Empirical Measurements)

| Method | Detected / $K$ | False Cert. | False Alarm | Time (s) |
| :--- | :---: | :---: | :---: | :---: |
| Differential (random) | 20/20 (100.0%) | 0 (0.0%) | 0 (0.0%) | 0.02 |
| BEACON, $R$ only | 20/20 (100.0%) | 0 (0.0%) | 0 (0.0%) | 0.01 |
| BEACON Full | 20/20 (100.0%) | 0 (0.0%) | 0 (0.0%) | 0.52 |
| LLM-as-judge | 20/20 (100.0%) | 0 (0.0%) | 0 (0.0%) | 169.35 |

---

## 7. Output Files & Artifacts

- `BEACON_seeded_defect_results.json`: Canonical machine-readable JSON containing full environment provenance, dataset hashes, per-case decision records, cross-method validation checks, and publication-ready Table XVII metrics.
- `llm_judge_rerun_results.json`: Detailed machine-readable JSON containing individual audit records, latency, attempt counts, and confusion matrix for the LLM rerun.
- `llm_judge_rerun_results.csv`: Flat per-case CSV for auditing and verification.
- `llm_judge_rerun_diagnostics.md`: Formal diagnostic report detailing the failure causes, resolution, and verification.
- `llm_judge_rerun_summary.txt`: Terminal-style summary of LLM rerun metrics.
- `seeded_defects/dataset.py`: Reproducible dataset generator and probe suite.
- `seeded_defects/evaluator.py`: Isolated evaluators for all four methods.
- `seeded_defects/mutations.py`: Formal defect definitions and mutation specifications.
- `seeded_defects/rerun_llm_judge.py`: Dedicated rerun and validation harness.
