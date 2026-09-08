# BEACON V2 — Phase 6: Discovery Architecture

## 1. Pipeline Overview

The Phase 6 Rule / Invariant Discovery Engine transforms raw execution evidence into verified, ranked candidate behavioral hypotheses through a strictly bounded, deterministic pipeline:

```
[ EvidenceBundle ]
       │
       ▼
1. Validation & Extraction
   • Validates Phase 3 evidence records and manifests.
   • Builds ObservationFact items for each input and role with fail-closed status normalization.
       │
       ▼
2. Observation Matrix Construction
   • Assembles ObservationMatrix with strictly partitioned Reference & Target facts.
   • Preserves value distinctions (None vs empty dict vs empty list vs 0 vs False vs "").
       │
       ▼
3. Domain-Agnostic Candidate Generation
   • Input/Output Generator (Equality, Copy, Constants, Bounded Linear Formulas)
   • Cross-Input Generator (Monotonic trends, Cross-Input Shape Stability across >=2 inputs)
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
   • Scope Classification: PER_FACT vs CROSS_OBSERVATION (aggregate).
   • Computes support_count, contradiction_count, unknown_count, applicable_count.
   • Calculates support_ratio and empirical confidence.
   • Classifies into VALIDATED, WEAK, CONTRADICTED, INSUFFICIENT_COVERAGE, INCONCLUSIVE.
       │
       ▼
6. Role-Scoped Separation & Independent Mining
   • Reference rules (role_scope="reference")
   • Target rules (role_scope="target")
   • Common rules surfaced via common_fingerprints without synthetic reconciliation.
   • NEVER performs rule reconciliation (strictly deferred to Phase 7).
       │
       ▼
7. Deduplication & Deterministic Ranking
   • Deduplicates candidates sharing canonical fingerprints per role scope.
   • Deterministically sorts by confidence desc, support desc, complexity asc, expression asc.
       │
       ▼
8. Persistence & API
   • Explicit SQLite storage into `discoveries` and `discovered_candidates` (using candidate_instance_id).
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

## 3. Validation Scopes: Per-Fact vs Cross-Observation

The candidate validator classifies hypotheses into two explicit evaluation scopes:
1. **PER_FACT**: Evaluates hypotheses against each observation independently (e.g. arithmetic relations, types, shapes, nullability, single-observation state/error properties).
2. **CROSS_OBSERVATION**: Evaluates aggregate properties across the observation group (e.g. `monotonic_non_decreasing(input.x -> output.y)`). Observations are filtered for validity, sorted deterministically by input value, and compared pairwise to ensure monotonicity and detect conflicting duplicate inputs.

---

## 4. Provenance & Determinism

Every candidate maintains complete provenance:
- `discovery_method`: Generator method string (e.g., `direct_relation`, `cross_input_analysis`, `sequence_mining`, `state_delta_analysis`).
- `input_ids`: Sorted list of input IDs whose observations support the candidate.
- `evidence_ids`: Sorted list of Phase 3 evidence IDs directly backing the candidate.
- `fingerprint`: Cryptographic SHA-256 digest of `rule_type`, `canonical_expression`, `variables`, and `source_fields`. Role scope is excluded so identical hypotheses discovered on Reference and Target share the semantic fingerprint while remaining independent records.
- `candidate_instance_id`: Unique persistent instance ID in SQLite, separating historical execution instances from semantic identity.
- `result_hash`: Deterministic SHA-256 digest across all ranked candidate fingerprints for a given run.

---

## 5. Security & Safety

- **No `eval()` / `exec()`**: All candidate expressions are parsed and evaluated using deterministic regex, AST parsers, and bounded mathematical functions with strict numeric tolerance.
- **Complexity Limits**: Formula discovery and sequence mining are bounded by explicit maximum depth and count constraints defined in `DiscoveryPolicy`.
- **Denial of Service Prevention**: Maximum candidates per run is strictly enforced (`maximum_candidates = 100`).
