# Protocol Deviations & Design Decisions Log

**Project:** BEACON Research Evaluation (Comments 1–5 Re-evaluation)  
**Base Seed:** `12345`  
**Reference Program:** AWS CardDemo `COACTUPC` (Legacy COBOL under GnuCOBOL 3.1.2.0 vs Modern Python)

---

## 1. Initial Protocol Specifications & Design Decisions

### Decision 1: Input Budget Selection ($B = 500$ primary, $B = 100$ sensitivity)
- **Rationale:** An input budget of $B = 500$ per evaluated case provides sufficient empirical density to detect moderate-frequency bugs while remaining computationally tractable across $>75$ cases and 5 repetitions. $B = 100$ is evaluated as a sensitivity check to demonstrate behavior under constrained testing budgets.
- **Enforcement:** Both reference and candidate implementations are evaluated against byte-identical input sets whose canonical SHA-256 digests are asserted in code before execution.

### Decision 2: Ground-Truth Isolation
- **Rationale:** Ground-truth labels (`DEFECTIVE` vs `EQUIVALENT`) are established and serialized into `results/ground_truth.json` prior to running any baseline or certification tool.
- **Enforcement:** Neither BEACON nor the baselines have access to `ground_truth.json`.

### Decision 3: Empirical Trigger Rate Measurement
- **Rationale:** Reviewer Comment 1 requires that defect difficulty be determined by empirical measurement rather than human guessing.
- **Enforcement:** Each defect mutant is evaluated against 10,000 independent pseudo-random valid-format transactions generated with seed `12345`.
  - **Easy:** Measured trigger rate $> 1.0\%$
  - **Medium:** Measured trigger rate $0.1\%$ to $1.0\%$
  - **Hard:** Measured trigger rate $\le 0.1\%$

### Decision 4: Preserving Scorer and Gate Logic During Experimentation
- **Enforcement:** In accordance with Rule 0, no weights, thresholds, or gate conditions are altered retroactively based on observed outcomes. If an engineering bug is identified, it will be logged here with its resolution, committed separately, and all affected experiments re-run from scratch.

---

## 2. Logged Deviations During Execution

*(Any retroactive changes or post-hoc adjustments will be recorded below with timestamps and rationale. Currently: Zero deviations).*
