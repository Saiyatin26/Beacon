# BEACON V2 — Phase 6: Discovery Architecture

## 1. Pipeline Overview

The Phase 6 Rule / Invariant Discovery Engine transforms raw execution evidence into verified, ranked candidate behavioral hypotheses through a strictly bounded, deterministic pipeline:

```
[ EvidenceBundle ]
       │
       ▼
1. Validation & Extraction
   • Validates Phase 3 evidence records and manifests.
   • Builds ObservationFact items for each input and role.
       │
       ▼
2. Observation Matrix Construction
   • Assembles ObservationMatrix with distinct Reference & Target facts.
   • Preserves value distinctions (None vs empty dict vs empty list vs 0 vs False vs "").
       │
       ▼
3. Domain-Agnostic Candidate Generation
   • Input/Output Generator (Equality, Copy, Constants, Bounded Linear Formulas)
   • Type & Shape Invariant Generator
   • Nullability & Presence Pattern Generator
   • Relational Invariant Generator (<=, >=, ==)
   • Error Behavior Generator (Success Invariants, Category Association)
   • State Invariant & Transition Generator (Pre/Post Verified State Snapshots)
   • Workflow Sequence Generator (Direct Predecessors, Sequence Chains)
   • Boundary Generator (Empirical Transition Points on Input Distributions)
       │
       ▼
4. Candidate Canonicalization & Normalization
   • Commutative operand ordering (A == B vs B == A).
   • Deterministic SHA-256 fingerprint generation.
       │
       ▼
5. Empirical Candidate Validation
   • Computes support_count, contradiction_count, unknown_count, applicable_count.
   • Calculates support_ratio and empirical confidence.
   • Classifies into VALIDATED, WEAK, CONTRADICTED, INSUFFICIENT_COVERAGE, INCONCLUSIVE.
       │
       ▼
6. Role-Scoped Separation & Shared Candidate Tagging
   • Reference rules (role_scope="reference")
   • Target rules (role_scope="target")
   • Cross-Implementation Shared candidates (role_scope="both")
   • NEVER performs rule reconciliation (strictly deferred to Phase 7).
       │
       ▼
7. Deduplication & Deterministic Ranking
   • Deduplicates candidates sharing canonical fingerprints.
   • Deterministically sorts by confidence desc, support desc, complexity asc, expression asc.
       │
       ▼
8. Persistence & API
   • Explicit SQLite storage into `discoveries` and `discovered_candidates`.
   • Exposes REST endpoints via `/api/v2/discovery`.
```

---

## 2. Observation Matrix & 3-Valued Evidence Semantics

The discovery engine normalizes evidence once into structured `ObservationFact` models. Missing or corrupt data is never fabricated:
- **Missing Data**: If an observation lacks output or state, evaluating an output/state candidate yields `UNKNOWN` (evaluates to `None`), which increments `unknown_count`.
- **Applicability**: If an observation has valid evidence but does not contain the fields referenced by a candidate, the observation is considered not applicable and does not count as a contradiction.
- **Support**: Observation explicitly satisfies the hypothesis.
- **Contradiction**: Observation contains the requisite fields and explicitly violates the hypothesis.

```
Total Observations = Applicable Observations + Inapplicable/Unknown Observations
Applicable Observations = Support Count + Contradiction Count
Support Ratio = Support Count / Total Observations
Confidence = Support Count / Applicable Observations
```

---

## 3. Provenance & Determinism

Every candidate maintains complete provenance:
- `discovery_method`: Generator method string (e.g., `formula_fitting`, `structural_mining`, `sequence_mining`, `transition_analysis`).
- `input_ids`: Sorted list of input IDs whose observations support the candidate.
- `evidence_ids`: Sorted list of Phase 3 evidence IDs directly backing the candidate.
- `fingerprint`: Cryptographic SHA-256 digest of `rule_type`, `canonical_expression`, `role_scope`, and `variables`.
- `result_hash`: Deterministic SHA-256 digest across all ranked candidate fingerprints for a given run.

---

## 4. Security & Safety

- **No `eval()` / `exec()`**: All candidate expressions are parsed and evaluated using deterministic regex, AST parsers, and bounded mathematical functions with strict numeric tolerance.
- **Complexity Limits**: Formula discovery and sequence mining are bounded by explicit maximum depth and count constraints defined in `DiscoveryPolicy`.
- **Denial of Service Prevention**: Maximum candidates per run is strictly enforced (default: 200).
