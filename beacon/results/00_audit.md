# Audit of Existing Seeded-Defect Benchmark (Table XVII)

**Date of Audit:** 2026-10-27  
**Auditor:** Automated Verification Agent (BEACON Research Framework)  
**Evaluated Artifacts:** `BEACON_seeded_defect_results.json`, `BEACON_seeded_defect_README.md`, `seeded_defects/dataset.py`, `seeded_defects/evaluator.py`, `seeded_defects/mutations.py`, `seeded_defects/run_table_xvii_evaluation.py`, `llm_judge_rerun_results.json`

---

## 1. Executive Summary & Audit Verdict

The existing Seeded-Defect Study (reported in Table XVII of the manuscript) reports a uniform result across all four evaluation methods:

| Method | Detected / $K$ | False Certifications | False Alarms | Time (s) |
| :--- | :---: | :---: | :---: | :---: |
| **Differential (random)** | 20/20 (100.0%) | 0 (0.0%) | 0 (0.0%) | 0.02 |
| **BEACON, $R$ only** | 20/20 (100.0%) | 0 (0.0%) | 0 (0.0%) | 0.01 |
| **BEACON Full** | 20/20 (100.0%) | 0 (0.0%) | 0 (0.0%) | 0.52 |
| **LLM-as-judge** | 20/20 (100.0%) | 0 (0.0%) | 0 (0.0%) | 169.35 |

### Audit Finding
**The existing benchmark is empirically NON-DISCRIMINATING.**  
A benchmark in which even a naive differential tester with 15 random inputs achieves 100% detection and 0% false alarms provides **zero empirical evidence** that BEACON's evidence-quality adjustment ($Q$), dynamic policy thresholds ($\Theta$), or safety gates ($G_1$–$G_6$) provide any benefit over simpler methods.

---

## 2. Detailed Root-Cause Analysis

### 2.1 Test Suite Contamination & Mutant Coupling
In `seeded_defects/dataset.py`, every evaluated mutant case was evaluated against a fixed test suite called `STANDARD_TEST_SUITE` containing 13 hand-crafted test cases (`TC_01` through `TC_13`).
Each mutant in `seeded_defects/mutations.py` was crafted such that at least one of these 13 tests directly and deterministically triggers the defect:
- `DEF_BRANCH_01` (PF3 navigation) was tested directly by `TC_07_PF3_RETURN`.
- `DEF_BRANCH_02` (Zero account error suppression) was tested directly by `TC_08_ZERO_ACCT`.
- `DEF_VAL_01` (Active status validation bypass) was tested directly by `TC_05_VALIDATION_ERROR_STATUS`.
- `DEF_BOUND_01` (Zero limit boundary) was tested directly by `TC_10_ZERO_LIMIT`.
- `DEF_VAL_02` (Empty last name bypass) was tested directly by `TC_11_EMPTY_LAST_NAME`.
- `DEF_BOUND_02` (Negative limit bypass) was tested directly by `TC_12_NEGATIVE_LIMIT`.

In `seeded_defects/evaluator.py`, the differential baseline (`DifferentialRandomEvaluator`) did not rely solely on random inputs; rather, line 82 explicitly appended `STANDARD_TEST_SUITE` to the input probe set:
```python
all_inputs = [tc.inputs for tc in case.test_cases]
for _ in range(self.probe_count):  # probe_count was only 15!
    all_inputs.append(self.generate_random_input())
```
Because the 13 hand-crafted targeted probes were executed on every case, the differential runner encountered a divergence immediately on the targeted test, guaranteeing 100% detection regardless of the random inputs.

### 2.2 Lack of Semantics-Preserving Equivalent Controls
The benchmark dataset contains:
- $K = 20$ defective mutants.
- 10 "control" cases (`CTRL_01` to `CTRL_10`).
However, inspection of `dataset.py` (lines 289–303) reveals that all 10 control cases simply execute the **exact unmodified reference program 10 times**:
```python
for i in range(1, control_cases_count + 1):
    ctrl_id = f"CTRL_{i:02d}"
    evaluated_cases.append(EvaluatedCase(
        case_id=f"CASE_{ctrl_id}",
        ground_truth="CORRECT",
        target_runner=reference_runner,  # Unmodified reference code!
        ...
    ))
```
Only one equivalent mutation was created (`EXCL_EQUIV_01`), and it was **excluded** prior to evaluation. Thus, the benchmark included **zero semantics-preserving code transformations** (e.g., refactored loops, equivalent condition reordering, simplified arithmetic expressions). Consequently, none of the methods were tested on their ability to certify equivalent code variants without false alarms.

### 2.3 LLM-as-Judge Execution Mode
The original Table XVII results recorded a wall-clock time of 169.35 seconds for the LLM judge.
Audit of `rerun_llm_judge.py` and `llm_judge_rerun_results.json` confirms:
1. The LLM was prompted using `gemini-flash-lite-latest` via Google Gemini API direct provider.
2. However, the prompt given to the LLM (`LlmAsJudgeEvaluator.build_case_prompt`) explicitly included the side-by-side execution trace outputs of the 13 targeted tests:
   ```json
   {
     "program": "CardDemo Account Update (COACTUPC)",
     "tests": [{"test": "TC_05_VALIDATION_ERROR_STATUS", "ref": {"ERROR": "Y"}, "target": {"ERROR": "N"}}]
   }
   ```
   Because the side-by-side mismatch was explicitly presented in the JSON payload, the LLM simply acted as a JSON diff comparator. The LLM was not required to independently discover or reason over unguided inputs.

### 2.4 Trigger Rates & Defect Difficulty
Under purely random inputs adhering to the CardDemo transaction schema, the 20 existing defects had high trigger rates when their scenario was selected because the input generator in `evaluator.py` only selected among 7 coarse scenarios.
There were **no low-trigger-rate defects** (trigger rate $\le 1\%$ or $\le 0.1\%$ of random inputs), such as:
- Arithmetic overflow on specific decimal combinations.
- Off-by-one errors active only on leap years or end-of-month boundaries.
- Boundary conditions active only when multiple fields simultaneously hit edge values.
Without low-trigger-rate defects, random differential testing cannot fail, making it impossible to demonstrate the necessity of rule-directed test generation or evidence sufficiency gating.

---

## 3. Specifications for the New Benchmark (§2)

To satisfy the reviewer's mandate and provide a rigorous, publishable evaluation, the new benchmark must satisfy:

1. **Scale & Stratification:**
   - $\ge 60$ verified defective cases distributed across 5 core categories:
     - `incorrect_calculation` ($\ge 12$ cases)
     - `boundary_condition` ($\ge 12$ cases)
     - `altered_business_rule` ($\ge 12$ cases)
     - `missing_update` ($\ge 12$ cases)
     - `incorrect_transaction_handling` ($\ge 12$ cases)
   - $\ge 15$ semantics-preserving `equivalent_control` cases (refactored implementations that preserve CICS contract semantics).
   - Clean candidate control #0 (`CTRL_00`).
2. **Empirical Trigger Rate Quantification:**
   - For every defect case, measure the empirical trigger rate over **10,000 independent random valid-format inputs**.
   - Classify difficulty:
     - **Easy:** trigger rate $> 1.0\%$
     - **Medium:** trigger rate $0.1\%$ to $1.0\%$
     - **Hard:** trigger rate $\le 0.1\%$ (rare edge cases where random testing is expected to fail at budget $B = 500$ or $B = 100$).
3. **Strict Method Isolation & Identical Inputs:**
   - All methods must receive **identical input sets** with recorded SHA-256 digests.
   - Ground truth fixed and sealed in `results/ground_truth.json` prior to method execution.
   - Seed fixed at base `12345` with $\ge 5$ deterministic repetitions for stochastic components.
4. **Independent Baselines:**
   - Four distinct methods: M1 (Output-only), M2 (Unweighted evidence scoring), M3 (BEACON without sufficiency gates), M4 (Full BEACON).
   - Primary threshold $\Theta = 0.90$ (with sensitivity at $0.80$ and $0.95$).
