# BEACON V2 — Phase 7: Rule Reconciliation & OracleSet Architecture

## 1. Executive Summary
Phase 7 answers the core specification question:
> **"Which behavioral rules, relationships, and invariants should form the certified behavioral specification (OracleSet)?"**

Phase 7 does **NOT** discover rules (Phase 6), execute targets (Phase 3), or certify equivalence (later phases). Its sole responsibility is to ingest **Phase 5 User-Defined Rules** (intentional specifications) and **Phase 6 Discovered Candidate Rules** (empirical hypotheses), and deterministically reconcile them into an auditable, provenance-preserving, frozen **`OracleSet`**.

---

## 2. Fundamental Architectural Boundary
```
   DISCOVERY (Phase 6)        ≠        RECONCILIATION (Phase 7)        ≠        CERTIFICATION (Future)
"What rules appear to exist?"    "What rules belong in OracleSet?"     "Does target satisfy specification?"
```

---

## 3. High-Level Reconciliation Pipeline

```
                    Phase 5 User Rules             Phase 6 Discovered Candidates
                   (Intentional Spec)                (Empirical Hypotheses)
                            │                                   │
                            │                                   ▼
                            │                          ┌─────────────────┐
                            │                          │   Eligibility   │ (Filters VALIDATED; blocks
                            │                          │     Filter      │  CONTRADICTED/WEAK/INCONCLUSIVE)
                            │                          └────────┬────────┘
                            │                                   │
                            └─────────────────┬─────────────────┘
                                              ▼
                                   ┌──────────────────────┐
                                   │  Rule Normalization  │ (Standardizes AST expressions,
                                   │    & Fingerprints    │  operators, and field paths)
                                   └──────────┬───────────┘
                                              ▼
                                   ┌──────────────────────┐
                                   │     Semantic De-     │ (Merges identical semantic rules;
                                   │     duplication      │  fuses provenance from all sources)
                                   └──────────┬───────────┘
                                              ▼
                                   ┌──────────────────────┐
                                   │    Relationship &    │ (Classifies EQUIVALENT, SPECIALIZATION,
                                   │  Conflict Detection  │  GENERALIZATION, CONFLICT, COMPATIBLE)
                                   └──────────┬───────────┘
                                              ▼
                                   ┌──────────────────────┐
                                   │   Approval Policy    │ (Approves unconflicted rules;
                                   │   & Reconciliation   │  quarantines unresolved conflicts)
                                   └──────────┬───────────┘
                                              ▼
                                     ┌────────┴────────┐
                                     ▼                 ▼
                              Approved Rules   Unresolved Conflicts
                                     │                 │
                                     ▼                 ▼
                              ┌─────────────┐   ┌──────────────┐
                              │  OracleSet  │   │ Conflict Log │
                              └──────┬──────┘   └──────────────┘
                                     ▼
                              Integrity Hash (SHA-256)
                                     ▼
                            SQLite Persistence
                                     ▼
                        Certification-Ready Spec
```

---

## 4. Key Subsystem Components

### 4.1 Eligibility Gate
Filters incoming Phase 6 candidate hypotheses fail-closed:
- `VALIDATED` candidates meeting `minimum_support_count` ($\ge 2$) and `minimum_confidence` ($\ge 0.8$) are admitted for reconciliation.
- `WEAK`, `CONTRADICTED`, `INSUFFICIENT_COVERAGE`, and `INCONCLUSIVE` candidates are rejected.
- Detailed rejection reasons are logged in `DecisionTraceRecord`s.

### 4.2 Canonical Normalizer
Converts Phase 5 `BusinessRule` and Phase 6 `DiscoveredCandidate` objects into a unified canonical intermediate representation (`NormalizedRuleRepresentation`):
- Standardizes relational operator spacing and symbols (`==`, `!=`, `<=`, `>=`, `<`, `>`).
- Normalizes condition trees and expected behavior payloads.
- Computes deterministic SHA-256 semantic fingerprints.

### 4.3 Semantic Deduplication & Provenance Fusion
- Groups semantically equivalent rules across multiple observation runs and user submissions.
- Fuses evidence IDs (`evidence_ids`), input IDs (`input_ids`), source rule IDs (`source_rule_ids`), and candidate fingerprints (`candidate_fingerprints`).
- Sets provenance source to `MERGED` when user and discovered sources coincide.

### 4.4 Relationship & Conflict Analysis
Evaluates all rule pairs across the observation domain:
- **`EQUIVALENT`**: Identical conditions and identical expected outcomes.
- **`SPECIALIZATION` / `GENERALIZATION`**: Sub-case rules (e.g. `Gold AND amount > 1000 -> 15%`) are differentiated from base rules (e.g. `Gold -> 10%`) without spurious conflict.
- **`CONFLICT`**: Identical or overlapping conditions with incompatible expected outcomes (e.g. `Gold -> 10%` vs `Gold -> 15%`, or `User A: x -> 10` vs `User B: x -> 20`).
- **`INDEPENDENT`**: Disjoint condition and field spaces.

### 4.5 OracleSet Status & Integrity
- **`READY`**: Reconciled and completely free of unresolved behavioral conflicts.
- **`BLOCKED`**: Material unresolved conflicts exist; quarantined from certification.
- **`oracle_set_hash`**: Deterministic SHA-256 digest over canonical rule representations and conflict records.

### 4.6 Provenance Audit Graph
Every admitted rule answers:
> *"Where did this rule come from, what evidence backs it, what other rules were considered, and why was it admitted into the OracleSet?"*

---

## 5. Security & Domain Agnosticity
- **Zero dynamic code execution**: Zero usage of `eval()`, `exec()`, or dynamic shell interpreters.
- **100% Domain-Agnostic**: Operates over abstract fields, operators, and conditions with zero hardcoded business domain vocabulary (banking, healthcare, insurance, retail, etc.).
- **Strict Phase Boundary**: Zero dynamic thresholding (Phase 8), zero RAG (Phase 9), zero autonomous LLM agents (Phase 10).
