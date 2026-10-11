# Technical Disclosure: Evidence-Adjusted Behavioral Equivalence Certification (BEACON)

> **Document Type:** Technical & Engineering Disclosure for Patent Review  
> **System:** BEACON (Behavioral Equivalence Certifier) — Full Mode  
> **Version:** 2.0 (Verified Implementation)  
> **Notice:** This document constitutes an engineering and research disclosure describing the implemented technical mechanism and reproducible experimental evidence. It is prepared for review by a qualified patent attorney or patent agent. It does not constitute formal legal advice or a guarantee of patent grant or validity.

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

4. **Silent Provider Fallback and Pollution:**  
   Existing multi-provider architectures silently degrade to local or offline mock providers when primary API calls fail, allowing ungrounded or mock test cases to masquerade as authentic verification evidence.

---

## 2. Proposed Technical Mechanism and System Architecture

BEACON introduces a **two-tier certification engine** that separates observed empirical agreement from the epistemic quality of the supporting evidence:

```
+--------------------------------------------------------------------------------------------------+
|                                    BEACON FULL SYSTEM ARCHITECTURE                               |
+--------------------------------------------------------------------------------------------------+
|                                                                                                  |
|   +-----------------------+     +------------------------+                                       |
|   | Legacy Source (COBOL) |     | Modern Source (Python) |                                       |
|   +-----------+-----------+     +-----------+------------+                                       |
|               |                             |                                                    |
|               +-------------> + <-----------+                                                    |
|                               | SHA-256 Repository Hashes & AST AST Extraction                   |
|                               v                                                                  |
|   +------------------------------------------------------+                                       |
|   |         Strict OpenRouter-Only AI Synthesis          |                                       |
|   |  - Zero Fallback Policy (No Ollama/Offline/Mocks)    |                                       |
|   |  - Hypothesizes Behavioral Rules & Test Candidates   |                                       |
|   +---------------------------+--------------------------+                                       |
|                               | Candidates & Proposed Rules                                      |
|                               v                                                                  |
|   +------------------------------------------------------+                                       |
|   |         Deterministic Local Candidate Validation     |                                       |
|   |  - AST & Copybook Identifier Vocabulary Verification  |                                       |
|   |  - Structural & Field Grounding Gate                 |                                       |
|   |  - Deterministic Canonical Candidate Deduplication   |                                       |
|   +---------------------------+--------------------------+                                       |
|                               | Accepted Authoritative Input Set (SHA-256 Merkle Root)           |
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
|   |  - Gate 4: SHA-256 Cryptographic Evidence Binding    |                                       |
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
$$\mathbf{w} = [w_1=0.30, w_2=0.20, w_3=0.20, w_4=0.10, w_5=0.10, w_6=0.10], \quad \sum_{i=1}^6 w_i = 1.00$$

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
- **Gate 4 (Provider Exclusivity Invariant):** In `FULL_BEACON` mode, all accepted inputs must originate from an authentic OpenRouter response with traceable model provenance.

---

## 5. Detailed Algorithm and Pseudocode

```python
def compute_evidence_adjusted_certification(
    legacy_source_files: list[Path],
    modern_source_files: list[Path],
    openrouter_client: OpenRouterProvider,
    policy_threshold: float = 0.85,
) -> CertificationResult:
    # 1. Compute Cryptographic Source Hashes
    legacy_hash = sha256_tree(legacy_source_files)
    modern_hash = sha256_tree(modern_source_files)

    # 2. Strict OpenRouter Rule & Input Generation (No Fallbacks)
    ai_response = openrouter_client.generate_candidates(legacy_source_files, modern_source_files)
    if not ai_response.success or ai_response.provider != "openrouter":
        return CertificationResult(status="BLOCKED", reason=ai_response.error_category)

    # 3. Local Grounding & AST Validation
    accepted_inputs = []
    identifier_vocab = extract_ast_vocabulary(legacy_source_files, modern_source_files)
    for candidate in ai_response.proposed_candidates:
        if all(field in identifier_vocab for field in candidate.keys()):
            if candidate not in accepted_inputs:
                accepted_inputs.append(candidate)

    if len(accepted_inputs) == 0:
        return CertificationResult(status="INSUFFICIENT_COVERAGE", score=0.0)

    # 4. Canonical Input Set Merkle Hash
    input_set_hash = sha256_canonical([c.hash() for c in accepted_inputs])

    # 5. Paired Behavioral Execution
    matching_cases = 0
    executed_cases = 0
    for inp in accepted_inputs:
        legacy_out = execute_legacy_adapter(inp)
        modern_out = execute_modern_adapter(inp)
        if legacy_out.status == "OK" and modern_out.status == "OK":
            executed_cases += 1
            if normalize(legacy_out.data) == normalize(modern_out.data):
                matching_cases += 1

    # 6. Compute Raw Behavioral Score
    raw_score = matching_cases / executed_cases if executed_cases > 0 else 0.0

    # 7. Compute Evidence Quality Factors
    factors = {
        "oracle_coverage": compute_rule_coverage(accepted_inputs, ai_response.rules),
        "input_coverage": min(1.0, len(accepted_inputs) / 20.0),
        "execution_reliability": executed_cases / len(accepted_inputs),
        "oracle_confidence": 0.85,
        "input_set_integrity": 1.0 if verify_hash(accepted_inputs, input_set_hash) else 0.0,
        "source_hash_integrity": 1.0,
    }

    # 8. Dynamic Availability-Aware Renormalization & Scoring
    quality_score = sum(WEIGHTS[k] * factors[k] for k in factors) / sum(WEIGHTS[k] for k in factors)
    adjusted_score = raw_score * quality_score

    # 9. Deterministic Certification Gating
    verdict = "CERTIFIED" if (adjusted_score >= policy_threshold and factors["execution_reliability"] >= 0.90) else "NOT_EQUIVALENT"

    return CertificationResult(
        verdict=verdict,
        raw_score=raw_score,
        quality_score=quality_score,
        adjusted_score=adjusted_score,
        factors=factors,
        input_set_hash=input_set_hash,
        legacy_hash=legacy_hash,
        modern_hash=modern_hash,
    )
```

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
| **Strict AI Policy** | `backend/llm/manager.py` | `ProviderManager.generate()` | Enforces OpenRouter-only generation; strictly rejects Ollama, Gemini, and mock fallbacks. |
| **Candidate Grounding** | `backend/application/input_discovery.py` | `InputDiscoveryEngine.discover_inputs()` | AST identifier validation, deduplication, and Merkle root calculation. |
| **Experimental Harness** | `scripts/run_inventive_step_experiments.py` | `main()` | Reproducible execution of EXP-01 through EXP-08 with JSON export. |

---

## 9. Known Limitations and Remaining Questions for Legal Counsel

1. **Deterministic Heuristic vs. Statistical Probability:**  
   The evidence-adjusted score $S_{\text{adj}}$ is a deterministic, bounded engineering heuristic, not a frequentist $p$-value or Bayesian posterior probability distribution. Claims must accurately describe it as an evidence-calibrated composite score rather than a probability of universal correctness.
2. **Mainframe Emulation Boundaries:**  
   The legacy execution adapter relies on GnuCOBOL and simulated terminal/BMS map parsing. It does not replicate proprietary CICS internal transaction managers or z/OS hardware features.
3. **Patent Search Completeness:**  
   The prior-art scan conducted herein was bounded by accessible academic and patent databases. Prior to filing, patent counsel should conduct a formal novelty search across USPTO, EPO, and WIPO databases focusing on IPC subclasses G06F 11/36 (testing/monitoring software) and G06F 8/71 (version management).
