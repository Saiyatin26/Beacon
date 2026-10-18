# Technical Disclosure: Evidence-Adjusted Behavioral Equivalence Certification (BEACON)

> **Document Type:** Technical & Engineering Disclosure for Patent Review  
> **System:** BEACON (Behavioral Equivalence Certifier) — Full Mode  
> **Version:** 2.1 (implementation-aligned)
> **Notice:** This is an engineering disclosure, not a novelty search, legal opinion, or guarantee of patentability. It distinguishes the implemented mechanism from legal findings that require qualified patent counsel and a jurisdiction-specific prior-art search.

---

## 1. Technical Field and Problem Definition

### 1.1 Field of the Invention
The present invention relates generally to software engineering, software verification, differential testing, and legacy software modernization. More specifically, it relates to methods, deterministic algorithms, and computer-readable systems for certifying behavioral equivalence between a legacy source program (such as COBOL/CICS mainframe code) and a modernized target implementation (such as Python or Java services) through evidence-calibrated scoring and cryptographically bound execution proof.

### 1.2 Technical Problem
During legacy system migration, software engineers must verify whether a newly constructed implementation behaves identically to the original legacy software across all relevant operational scenarios. Existing verification systems suffer from critical technical deficiencies:

1. **Illusion of Perfect Equivalence Under Sparse Evidence:**  
   In classical differential testing and regression testing, behavioral agreement is calculated purely as:
   $$\text{Agreement} = \frac{|\text{Matching Outputs}|}{|\text{Executed Test Cases}|}$$
   If an evaluation executes only 1 or 2 trivial cases that happen to pass, the raw equivalence score is $1.0$ (100%), even when 99% of business logic branches, copybook data validations, and error conditions remain unexercised. High raw scores on sparse test sets create an unearned illusion of correctness.

2. **Conflation of Mismatch vs. Lack of Evidence:**  
   Conventional test suites either fail completely or yield a boolean pass/fail. They fail to distinguish between:
   - A *demonstrated defect* (where both implementations executed and produced conflicting business outputs), versus
   - *Epistemic uncertainty* (where executions were unreliable, inputs were ungrounded, or evidence factors were missing).

3. **Vulnerability to Tampering and Fabricated Provenance:**  
   When modern language models (LLMs) are used to assist in test discovery or rule generation, traditional test runners treat the generated cases as trusted oracles without enforcing cryptographic provenance, boundary validation against program ASTs, or tamper-evident binding between the evaluated source code, the input set, and the certificate.

4. **Unattributed Discovery Evidence:**
   If generated candidates are used without recording their provider and model provenance, reviewers cannot determine how the input or rule evidence was produced.

---

## 2. Proposed Technical Mechanism and System Architecture

BEACON implements a **two-tier certification engine** that separates observed empirical agreement from the quality of the supporting run evidence. Full BEACON Mode records the actual provider and model for each extraction, alignment, and test-generation call. Missing provenance, fallback, or source/evidence integrity failure is not accepted as a successful Full BEACON run.

```
+--------------------------------------------------------------------------------------------------+
|                                    BEACON FULL SYSTEM ARCHITECTURE                               |
+--------------------------------------------------------------------------------------------------+
|                                                                                                  |
|   +-----------------------+     +------------------------+                                       |
|   | Legacy Source         |     | Modern Source          |                                       |
|   +-----------+-----------+     +-----------+------------+                                       |
|               |                             |                                                    |
|               +-------------> + <-----------+                                                    |
|                               | Source-tree hashes and independent AI rule extraction            |
|                               v                                                                  |
|   +------------------------------------------------------+                                       |
|   |         Provenance-Recorded Candidate Synthesis      |                                       |
|   |  - Separate extraction from both source trees        |                                       |
|   |  - Provider/model provenance and source anchors      |                                       |
|   +---------------------------+--------------------------+                                       |
|                               | Candidates & Proposed Rules                                      |
|                               v                                                                  |
|   +------------------------------------------------------+                                       |
|   |         Deterministic Local Candidate Validation     |                                       |
|   |  - Exact source-line and source-file hash checks      |                                       |
|   |  - Supported condition/output contract validation    |                                       |
|   |  - Alignment and unsupported-behavior gap tracking   |                                       |
|   +---------------------------+--------------------------+                                       |
|                               | Rule-directed input set (canonical SHA-256 hash)                   |
|                               v                                                                  |
|   +------------------------------------------------------+                                       |
|   |         Synchronous Paired Behavioral Execution      |                                       |
|   |  - Legacy Adapter (GnuCOBOL / BMS / Terminal)        |                                       |
|   |  - Modern Adapter (Python / Structured Results)      |                                       |
|   |  - Canonical Output Normalization & Diff Evaluation  |                                       |
|   +---------------------------+--------------------------+                                       |
|                               | Raw Observations & Comparison Metrics                            |
|                               v                                                                  |
|   +------------------------------------------------------+                                       |
|   |     Evidence-Adjusted Scoring Engine (The Invention) |                                       |
|   |  1. Compute Raw Behavioral Score: R in [0.0, 1.0]     |                                       |
|   |  2. Measure 6 Evidence Quality Factors: f_i          |                                       |
|   |  3. Dynamic Availability-Aware Renormalization       |                                       |
|   |  4. Compute Evidence Quality: Q in [0.0, 1.0]        |                                       |
|   |  5. Compute Evidence-Adjusted Score: S_adj = R * Q   |                                       |
|   +---------------------------+--------------------------+                                       |
|                               | S_adj, R, Q, and Factor Breakdown                                |
|                               v                                                                  |
|   +------------------------------------------------------+                                       |
|   |     Mandatory Deterministic Certification Policy      |                                       |
|   |  - Gate 1: Zero-Input Protection (Inputs > 0)        |                                       |
|   |  - Gate 2: Reliability Threshold (Rel >= 0.90)       |                                       |
|   |  - Gate 3: Adjusted Score Threshold (S_adj >= Theta) |                                       |
|   |  - Source, input, and evaluation integrity gates      |                                       |
|   |  - Provider, alignment, and targeted-coverage gates  |                                       |
|   +---------------------------+--------------------------+                                       |
|                               | Final Verdict                                                    |
|                               v                                                                  |
|   +------------------------------------------------------+                                       |
|   |   Verifiable Certificate Artifact (JSON, MD, PDF)    |                                       |
|   |   - Cryptographic Provenance & Tamper Detection      |                                       |
|   +------------------------------------------------------+                                       |
+--------------------------------------------------------------------------------------------------+
```

---

## 3. Mathematical Formulation and Scoring Equations

### 3.1 Raw Behavioral Score ($R$)
The raw behavioral score quantifies the empirical agreement observed across successfully evaluated test cases under a defined normalization policy:

$$R = \frac{\sum_{k=1}^{N_{\text{eval}}} \mathbb{I}(\text{Norm}(\text{Output}_{\text{legacy}}^{(k)}) \equiv \text{Norm}(\text{Output}_{\text{modern}}^{(k)}))}{N_{\text{eval}}}$$

Where:
- $N_{\text{eval}}$ is the number of test cases where both implementations executed to completion.
- If $N_{\text{total}} = 0$ or $N_{\text{eval}} = 0$, $R \equiv 0.0$ (fail-closed; never $1.0$).

### 3.2 Evidence Quality Factors ($f_i$)
BEACON defines six normalized quality dimensions $f_i \in [0.0, 1.0]$:

1. **Oracle Coverage ($f_1$):** Ratio of verified behavioral rules exercised by the evaluated test cases relative to all discovered rules:
   $$f_1 = \frac{|\text{Rules}_{\text{exercised}}|}{|\text{Rules}_{\text{total}}|}$$
2. **Input Space Coverage ($f_2$):** Diversity of accepted test vectors across program entry points and boundary partitions:
   $$f_2 = \min\left(1.0, \frac{N_{\text{unique\_inputs}}}{N_{\text{target\_coverage}}}\right)$$
3. **Execution Reliability ($f_3$):** Fraction of paired executions that completed without adapter crash, timeout, or environment error:
   $$f_3 = \frac{N_{\text{successful\_executions}}}{N_{\text{total\_attempted}}}$$
4. **Oracle Confidence ($f_4$):** Average semantic confidence and grounding certainty of active rules ($f_4 \in [0.0, 1.0]$).
5. **Input-Set Integrity ($f_5$):** Cryptographic verification factor ($1.0$ if the SHA-256 digest of executed inputs matches the canonical hash of the accepted input set; $0.0$ if tampered or missing).
6. **Source-Hash Integrity ($f_6$):** Cryptographic verification factor ($1.0$ if the SHA-256 digests of the legacy and modern source trees match the recorded provenance metadata; $0.0$ if altered).

### 3.3 Dynamic Availability-Aware Renormalization
Each factor $f_i$ is associated with a configured base weight $w_i > 0$. The default weight vector is:
$$\mathbf{w} = [w_1=0.30, w_2=0.20, w_3=0.20, w_4=0.15, w_5=0.10, w_6=0.05], \quad \sum_{i=1}^6 w_i = 1.00$$

When a factor is *unavailable* (e.g., source hashes were not tracked, or oracle confidence was unmeasured), BEACON does **not** assume $f_i = 1.0$ (which would inflate the score) nor $f_i = 0.0$ (which would arbitrarily punish unmeasured attributes). Instead, it defines the set of available factor indices $\mathcal{A} \subseteq \{1, \dots, 6\}$ and dynamically renormalizes:

$$\hat{w}_i = \frac{w_i}{\sum_{j \in \mathcal{A}} w_j}, \quad \forall i \in \mathcal{A}$$

The aggregate **Evidence Quality Score ($Q$)** is computed as:
$$Q = \sum_{i \in \mathcal{A}} \hat{w}_i f_i = \frac{\sum_{i \in \mathcal{A}} w_i f_i}{\sum_{i \in \mathcal{A}} w_i}$$

If $\mathcal{A} = \emptyset$ (no evidence factors available), the system fails closed and raises an `EvidenceScoringError`.

### 3.4 Evidence-Adjusted Certification Score ($S_{\text{adj}}$)
The final evidence-adjusted score is the scalar product of observed behavioral agreement and empirical evidence quality:

$$S_{\text{adj}} = R \times Q$$

**Key Mathematical Properties:**
1. **Monotonicity:** $\frac{\partial S_{\text{adj}}}{\partial R} = Q \ge 0$, and $\frac{\partial S_{\text{adj}}}{\partial f_i} = R \cdot \hat{w}_i \ge 0$.
2. **Strict Bounding:** Because $R \in [0, 1]$ and $Q \in [0, 1]$, $S_{\text{adj}} \in [0, 1]$.
3. **Upper Bound by Observation:** $S_{\text{adj}} \le R$ (evidence quality can penalize an agreement score, but can never elevate an observed mismatch above the observed agreement).
4. **Upper Bound by Evidence:** $S_{\text{adj}} \le Q$ (even 100% agreement on 1 test case with $Q = 0.50$ is capped at $S_{\text{adj}} = 0.50$).

---

## 4. Certification Policy and Gating Architecture

The evidence-adjusted score $S_{\text{adj}}$ does not replace deterministic certification gates; it works in tandem with them. A certificate of equivalence is issued **only** if all mandatory gates pass:

$$\text{Verdict} = \begin{cases}
\text{CERTIFIED} & \text{if } S_{\text{adj}} \ge \Theta \land \text{All Gates Pass} \\
\text{NOT\_EQUIVALENT} & \text{if } R < \Theta_{\text{mismatch}} \lor \text{Regressions Detected} \\
\text{INSUFFICIENT\_EVIDENCE} & \text{if } Q < \Theta_{\text{quality}} \lor N_{\text{eval}} = 0 \lor \text{Gates Fail}
\end{cases}$$

### Deterministic Gates:
- **Gate 1 (Zero-Input Protection):** If $N_{\text{total}} = 0$ or $N_{\text{eval}} = 0$, status is immediately `INSUFFICIENT_COVERAGE` / `BLOCKED`. $R$ is assigned $0.0$, and certification is forbidden.
- **Gate 2 (Execution Reliability Floor):** $f_{\text{reliability}} \ge 0.90$. If flaky execution or crashes exceed 10%, certification is blocked regardless of score.
- **Gate 3 (Integrity Invariant):** $f_{\text{input\_integrity}} = 1.0$ and $f_{\text{source\_integrity}} = 1.0$. Any hash mismatch immediately invalidates the run.
- **Gate 4 (Full-Mode Provider Provenance):** In `FULL_BEACON` mode, the legacy extraction, modern extraction, alignment, and test-generation calls must each record an actual supported provider and model, with no fallback.
- **Gate 5 (Source-Rule Evidence):** A source-rule manifest, current source/tree hashes, exact condition/effect anchors, resolved dual-source alignment, and targeted paired-execution coverage must all validate.

### 4.1 Implemented Safety Boundary

The implementation in `backend/certification/certification_engine.py` evaluates the existing composite score and also records categorical evidence gates in every new certificate. In Full BEACON, certification is blocked if execution reliability is below the policy floor, input/evaluation integrity fails, source hashes or exact rule anchors are stale, provider provenance is absent, rules are unresolved, targeted rule coverage is incomplete, or behavior mismatches are observed. These gates are intentionally not compensable by a high score. Factor values and gate results are stored in `CertificationMetrics` and surfaced in the result UI.

---

## 5. Detailed Algorithm and Pseudocode

```text
1. Hash both repository snapshots.
2. Ask the configured AI provider to extract each source independently; retain provider/model
   provenance and exact condition/effect line anchors for every candidate.
3. Reject malformed, duplicate, unsupported, or source-unanchored rules deterministically.
   Ask the AI to align the remaining rules; retain unresolved, missing, or conflicting behavior
   as gaps rather than converting it into a pass.
4. Generate rule-directed inputs; validate the supported input/output assertions locally and
   bind the ordered input set to its canonical hash.
5. Execute both adapters on identical inputs. Persist and compare actual outputs, execution
   status, errors, and available state observations; bind results to rule/input/evidence IDs.
6. Recheck source tree hashes, exact anchors, input-set hash, evaluation hash, provider
   provenance, rule alignment, and targeted-rule coverage before certification.
7. Apply the existing evidence-adjusted score and policy thresholds. Issue a certificate only
   when every mandatory gate passes; otherwise return the specific block reason.
```

The current extracted-rule assertion contract is intentionally limited to one input comparison and one flat scalar output-field assertion per rule. Other behavior may still be captured and compared in execution evidence, but a rule outside this contract is a gap and cannot count as validated targeted coverage.

---

## 6. Comprehensive Prior-Art Comparison Table

| Reference | Technical Scope & Disclosed Features | Similarities to BEACON | Differences & Deficiencies Addressed by BEACON |
|:---|:---|:---|:---|
| **Diffy (Twitter / Open Source)** | Differential testing comparing candidate vs. primary vs. secondary responses to isolate noise. | Dual/triple execution of software versions and comparing output diffs. | Diffy does not calibrate equivalence scores by rule/input coverage; has no evidence-quality weighting; lacks AI candidate generation and cryptographic proof binding. |
| **US9672137B1 (Amazon)** *"Shadow test replay service"* | Captures production requests and replays them to shadow candidate environments. | Replays inputs across two environments and monitors return codes/metrics. | Amazon US'137 relies on replaying observed production traffic, not AI-grounded boundary generation; does not adjust equivalence scores via coverage-quality factors. |
| **US8001422B1 (Amazon)** *"Shadow testing services"* | Simulates production traffic across a target version and monitors failure rates. | Compares behavior of updated services against production baselines. | Focuses on operational health metrics (latency, 5xx rates), not semantic equivalence certification; no dynamic availability renormalization formula. |
| **IEEE ISSRE 2016 (Adaptive Sampling)** | Reliability assessment of software using adaptive random sampling and Bayesian confidence intervals. | Mathematical modeling of testing confidence based on sample size and execution count. | Addresses single-system operational reliability, not cross-language legacy-to-modern equivalence; does not couple source/input hashing to certification certificates. |
| **ICTSS 2011 (Test Adequacy for Black-Box)** | Statistical inference methods to estimate black-box test suite adequacy. | Recognizes that test suite size influences test adequacy. | Relies on statistical approximations without paired differential execution; lacks deterministic certification gates and AI provenance tracking. |
| **PLOS ONE 2022 (TLS Differential Testing)** | Coverage-guided syntax mutation for differential fuzzing of cryptographic libraries. | Uses code coverage metrics alongside differential execution. | Coverage is used solely to guide the fuzzing generator; does not compute an evidence-adjusted certification score $S_{\text{adj}} = R \times Q$. |
| **ChatUniTest (arXiv:2305.04764)** | LLM-based unit test generation with AST extraction, compilation repair, and execution validation. | Uses LLMs to generate tests and validates them with local compilers. | Generates unit tests for a single codebase; does not perform paired cross-paradigm equivalence certification; lacks evidence-calibrated scoring. |

---

## 7. Candidate Claims Outline for Patent Professional Review

The following claim outline is structured to facilitate preparation of formal patent application claims by patent counsel:

### Independent Claim 1 (System / Method):
> A computer-implemented method for evidence-calibrated certification of behavioral equivalence between a legacy software program and a modernized software program, comprising:
> 1. Ingesting, by a processor, legacy source code and modern source code, and computing cryptographic hash digests identifying said source codes;
> 2. Generating, via a strictly configured artificial intelligence provider lacking unverified local fallback, candidate behavioral rules and candidate input test cases grounded in observable interfaces of said source codes;
> 3. Validating each candidate input test case against an identifier vocabulary extracted from an abstract syntax tree of said legacy source code to produce an accepted canonical input set;
> 4. Executing each test case of the accepted canonical input set across both the legacy software program and the modernized software program to produce legacy outputs and modern outputs;
> 5. Computing a raw behavioral equivalence score ($R$) representing normalized agreement between legacy and modern outputs;
> 6. Measuring a plurality of evidence quality factors ($f_i$) comprising at least oracle coverage, input space coverage, execution reliability, and cryptographic input-set integrity;
> 7. Dynamically renormalizing weights corresponding to currently available evidence quality factors to compute an aggregate evidence quality score ($Q$);
> 8. Computing an evidence-adjusted certification score ($S_{\text{adj}} = R \times Q$);
> 9. Evaluating a multi-gate certification policy comprising at least a zero-input protection gate and an execution reliability gate; and
> 10. In response to passing all gates, generating an immutable, cryptographically verifiable equivalence certificate binding the legacy hash digest, modern hash digest, canonical input set digest, raw score, quality score, and evidence-adjusted score.

### Dependent Claims (Technical Specifics):
- **Claim 2:** The method of Claim 1, wherein said zero-input protection gate immediately assigns a raw score of zero and blocks certification if the count of evaluated test cases is zero.
- **Claim 3:** The method of Claim 1, wherein dynamic renormalization calculates $\hat{w}_i = w_i / \sum_{j \in \mathcal{A}} w_j$ over the subset of measured evidence factors $\mathcal{A}$, failing closed if $\mathcal{A}$ is empty.
- **Claim 4:** The method of Claim 1, wherein candidate test cases containing fields not present in said abstract syntax tree vocabulary are rejected prior to execution.
- **Claim 5:** The method of Claim 1, wherein tampering with any test input after generation is detected via discrepancy with a canonical SHA-256 Merkle root of the accepted input set.

---

## 8. Implementation Files and Verified Interfaces

| Component | File Path | Function / Class | Verified Role |
|:---|:---|:---|:---|
| **Scoring Algorithm** | `backend/certification/scorer.py` | `evidence_adjusted_score()` | Mathematical implementation of $S_{\text{adj}} = R \times Q$ with dynamic renormalization. |
| **Certification Engine** | `backend/certification/certification_engine.py` | `CertificationEngine.certify_run()` | Gatekeeper evaluating Zero-Input Protection, Reliability floors, and issuing verdicts. |
| **Dual-Source Extraction** | `backend/mining/source_rule_extractor.py` | `extract_dual_source_rules()` | Independent provider calls, exact source anchors, alignment, and targeted-test proposals. |
| **Candidate Grounding** | `backend/application/input_discovery.py` | `InputDiscoveryEngine.discover_inputs()` | Deterministic rule/anchor validation, input generation, and provenance assembly. |
| **Paired Workflow** | `backend/workflow/engine.py` | `WorkflowEngine` | Paired execution, evidence links, stale-source/input checks, and Full BEACON certification context. |
| **Evaluation Integrity** | `backend/evaluation/models.py` | `compute_evaluation_result_hash()` | Canonical hash shared by evaluation and certification integrity verification. |
| **Experimental Harness** | `scripts/run_inventive_step_experiments.py` | `main()` | Reproducible execution of EXP-01 through EXP-08 with JSON export. |

---

## 9. Known Limitations and Remaining Questions for Legal Counsel

1. **Deterministic Heuristic vs. Statistical Probability:**  
   The evidence-adjusted score $S_{\text{adj}}$ is a deterministic, bounded engineering heuristic, not a frequentist $p$-value or Bayesian posterior probability distribution. Claims must accurately describe it as an evidence-calibrated composite score rather than a probability of universal correctness.
2. **Mainframe Emulation Boundaries:**  
   The legacy execution adapter relies on GnuCOBOL and simulated terminal/BMS map parsing. It does not replicate proprietary CICS internal transaction managers or z/OS hardware features.
3. **Patent Search Completeness:**  
   The prior-art scan conducted herein was bounded by accessible academic and patent databases. Prior to filing, patent counsel should conduct a formal novelty search across USPTO, EPO, and WIPO databases focusing on IPC subclasses G06F 11/36 (testing/monitoring software) and G06F 8/71 (version management).

This document describes an engineering implementation and a research direction only. It is not a patentability opinion, and no legal novelty or non-obviousness conclusion is made here.
