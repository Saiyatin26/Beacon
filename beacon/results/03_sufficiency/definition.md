# Evidence Coverage and Sufficiency: Formal Mathematical Definitions

**Project:** BEACON Research Evaluation (Comment 3 / Experiment 3)  
**Target Specification:** AWS CardDemo `COACTUPC` (8 Certified Ground-Truth Rules)  
**Primary Input Budget:** $B = 500$ Valid Transactions  
**Evidence-Sufficiency Gate Threshold:** $\text{min\_coverage} = 0.80$ ($80\%$), $\text{min\_reliability} = 0.90$ ($90\%$)

---

## 1. Mathematical Definitions

### Primary Metric: Rule-Directed Evidence Coverage ($f_1$)
Evidence coverage is defined strictly as the fraction of certified ground-truth specification rules that possess validated, targeted paired-execution trace evidence:

$$\text{Coverage}(E) = \frac{|\mathcal{R}_{\text{validated}}(E)|}{|\mathcal{R}_{\text{ground\_truth}}|}$$

Where:
- $\mathcal{R}_{\text{ground\_truth}}$ is the authoritative set of 8 certified specification rules for CardDemo `COACTUPC`:
  1. `RULE_01_FIRST_ENTRY_SIGNON` (calen=0 signon redirect)
  2. `RULE_02_PF3_MENU_RETURN` (PF3 caller menu return)
  3. `RULE_03_ACCOUNT_ID_VALIDATION` (lookup digit/non-zero format check)
  4. `RULE_04_ACCOUNT_LOOKUP_FOUND` (master record retrieval and display)
  5. `RULE_05_STATUS_VALIDATION` (active status 'Y'/'N' edit check)
  6. `RULE_06_CREDIT_LIMIT_DECIMAL` (decimal format and credit limit checks)
  7. `RULE_07_PREVIEW_CONFIRMATION` (preview transition and prompt display)
  8. `RULE_08_COMMIT_ON_PF5` (master record database rewrite on PF5)
- $\mathcal{R}_{\text{validated}}(E) \subseteq \mathcal{R}_{\text{ground\_truth}}$ represents the subset of rules for which targeted test inputs were executed, observed, and verified without unhandled crashes or integrity corruptions.

### Secondary Metric: Input Coverage ($f_2$)
Input coverage measures the empirical density of executed valid inputs relative to the nominal evaluation budget $B$:

$$\text{Input Coverage}(E) = \min\left(1.0, \frac{N_{\text{evaluated}}}{B}\right)$$

Where $B = 500$ in primary evaluation ($B = 100$ in sensitivity evaluation).

### Evidence Quality Composite ($Q$)
Evidence quality $Q$ aggregates the 6 empirical evidence factors $f_1..f_6$ weighted by vector $\mathbf{w}_0 = (0.30, 0.20, 0.20, 0.15, 0.10, 0.05)$:

$$Q(E) = \frac{\sum_{i=1}^6 w_i f_i}{\sum_{i=1}^6 w_i}$$

### Adjusted Behavioral Equivalence Score ($S_{\text{adj}}$)
$$S_{\text{adj}} = R \times Q(E)$$
Where $R = \frac{N_{\text{equivalent}}}{N_{\text{evaluated}}}$ is the raw behavioral agreement score.

---

## 2. Verdict Evaluation and Safety Gates

Full BEACON operates a fail-closed multi-gate policy:
- **$G_1$ (Input Count Floor):** Requires $N_{\text{evaluated}} > 0$. If $N = 0$, returns `INSUFFICIENT_COVERAGE`.
- **$G_2$ (Execution Reliability Floor):** Requires $f_3 \ge 0.90$. If $f_3 < 0.90$, returns `INSUFFICIENT_COVERAGE`.
- **$G_3$ (Cryptographic Integrity):** Requires input-set and source-code canonical SHA-256 digests to verify ($f_5 = 1.0, f_6 = 1.0$). If compromised, returns `NOT_CERTIFIED`.
- **$G_4$ (Provenance Verification):** Requires execution environment and model call metadata to be recorded.
- **$G_5$ (Evidence Coverage Floor):** Requires rule coverage $f_1 \ge \text{min\_coverage} = 0.80$. If $f_1 < 0.80$, returns `INSUFFICIENT_COVERAGE`.
- **$G_6$ (Behavioral Mismatch Gate):** Requires zero regressions ($R = 1.0$). Any demonstrated divergence on evaluated inputs immediately returns `NOT_CERTIFIED`.

### Metric Formulations:
- **Certification Rate:** $\frac{\text{Cases assigned CERTIFIED or CERTIFIED\_WITH\_WARNINGS}}{N_{\text{all}}}$
- **False-Certification Rate (FCR):** $\frac{\text{Defective cases assigned CERTIFIED or CERTIFIED\_WITH\_WARNINGS}}{N_{\text{defective}}}$
- **Insufficient-Coverage Rate (ICR):** $\frac{\text{Cases assigned INSUFFICIENT\_COVERAGE}}{N_{\text{all}}}$
