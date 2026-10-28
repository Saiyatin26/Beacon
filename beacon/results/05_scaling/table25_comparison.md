# Table XXV. Independent Benchmark Evaluation: CardDemo versus Masquerade

**Generated:** 2026-10-28T08:10:44Z  
**Evaluation Standard:** IEEE Transactions on Software Engineering Empirical Standards  
**Integrity Rule:** Rule 0 (Empirical execution records only; no fabricated numbers)

---

## 1. Primary Benchmark Comparison Matrix

| Evaluation Dimension | AWS CardDemo Benchmark | Masquerade Independent Benchmark |
|:---|:---|:---|
| **Evaluated Program** | `COACTUPC` (Account Update) | `CBTRN02C` (Daily Transaction Posting) |
| **Architectural Domain** | Online CICS Transaction Screen | Batch Financial Transaction & Balancing |
| **Reference Implementation** | CICS COBOL 85 (GnuCOBOL 3.1.2.0 compatibility harness) | Standard Batch COBOL 85 (Native WSL GnuCOBOL binary) |
| **Candidate Implementation** | AWS Modernization Python (`coactupc.py`) | Masquerade Python Modernization (`cbtrn02c.py`) |
| **Execution Environment** | WSL Ubuntu 22.04 LTS / GnuCOBOL 3.1.2.0 | WSL Ubuntu 22.04 LTS / GnuCOBOL 3.1.2.0 |
| **Adaptations Required** | CICS BMS screen mapping, `DFHEIBLK` injection | Environment file bindings (`DALYTRAN`, `XREFFILE`, etc.) |
| **Total Cases Evaluated** | **76** | **30** |
| **Defective Candidate Cases** | **60** (5 categories: CALC, VAL, TX, CTRL, FLOW) | **24** (5 categories: CALC, VAL, STATE, TX, FLOW) |
| **Behavior-Preserving Controls** | **16** (15 semantic refactorings + 1 clean) | **6** (5 semantic refactorings + 1 clean) |
| **Defects Detected ($TP$)** | **45** | **15** |
| **Defects Missed ($FN$)** | **15** (subtle edge triggers $<0.1\%$) | **9** (subtle edge triggers $<0.5\%$) |
| **False Certifications ($FC$)** | **15** ($25.00\%$) | **9** (37.50%) |
| **False Alarms ($FP$)** | **0** ($0.0\%$) | **0** (0.00%) |
| **Insufficient Coverage ($IC$)** | **0** | **0** |
| **Defect Detection Recall** | **75.00%** (95% CI: [62.77%, 84.24%]) | **62.50%** (95% CI: [0.4271, 0.7884]) |
| **Certification Precision** | **100.00%** (95% CI: [92.13%, 100.00%]) | **100.00%** (95% CI: [0.7961, 1.0000]) |
| **F1-Score** | **0.8571** | **0.7692** |
| **False-Certification Rate** | **25.00%** ($15 / 60$) | **37.50%** ($9 / 24$) |
| **Execution Failures / Exclusions** | **0** | **0** |

---

## 2. Comparative Findings and Cross-System Analysis

1. **Precision Invariance Across Paradigms:**
   - On both the CICS online interactive screen (`COACTUPC`) and the batch transaction posting batch program (`CBTRN02C`), BEACON achieved **100.0% precision** (0 false alarms on equivalent controls).
   - This empirically confirms that BEACON's sufficiency gating and evidence scoring do not penalize semantics-preserving refactorings (e.g., De Morgan condition rewrites, helper extraction, dictionary lookups) regardless of the architectural style.

2. **Consistent Defect Recall Characteristics:**
   - Defect recall on CardDemo is **75.00%** (45/60 detected) and on Masquerade is **62.50%** (15/24 detected).
   - In both benchmarks, missed defects are strictly confined to subtle edge cases requiring specific compound preconditions (e.g., boundary equality or unexposed internal fields) that random input distributions rarely trigger without concolic test generation.

3. **Execution Fidelity:**
   - CardDemo utilized CICS emulation with simulated BMS screen maps.
   - Masquerade `CBTRN02C` compiles cleanly to a native ELF binary under WSL GnuCOBOL 3.1.2.0 (`cobc -x -std=ibm`), providing genuine batch COBOL execution.

4. **Documented Limitations:**
   - Generalization across the broader software industry cannot be established by two benchmarks alone.
   - The Masquerade evaluation tests batch record persistence and balance updates, but does not exercise distributed messaging (MQ) or hierarchical databases (IMS DB2).
