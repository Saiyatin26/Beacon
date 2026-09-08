# BEACON V2 — Phase 6: Full Behavioral Rule / Invariant Discovery Engine

## Mission
Phase 6 answers the foundational question:
> **"What behavioral rules and invariants can BEACON discover from the evidence that was actually observed?"**

While Phase 5 verified compliance against user-supplied rules (*"Does the application satisfy explicitly provided rules?"*), Phase 6 autonomously synthesizes candidate behavioral hypotheses directly from Phase 3 evidence without human bias, domain assumptions, or hard-coded business semantics.

---

## Key Principles & Scope Boundaries

1. **Evidence-First Discovery**:
   - Candidates are mined strictly from observed facts in tamper-evident `EvidenceBundle` instances.
   - Every candidate contains complete cryptographic and relational provenance (`input_ids`, `evidence_ids`, `observation_count`).
   - Missing evidence is treated strictly as `UNKNOWN`, never conflated with support or contradiction.

2. **Domain Agnostic**:
   - Zero hardcoded domain concepts (no universal banking, healthcare, retail, or ERP business logic).
   - Rules are formulated using canonical, structural, mathematical, and observational expressions.

3. **Hypotheses vs Certified Truth**:
   - Phase 6 produces `DiscoveredCandidate` records with explicit empirical statuses (`VALIDATED`, `WEAK`, `CONTRADICTED`, `INSUFFICIENT_COVERAGE`, `INCONCLUSIVE`).
   - Phase 6 **DOES NOT** produce an `OracleSet` or perform certification. Candidate reconciliation and OracleSet selection belong exclusively to Phase 7.

4. **No Dynamic Thresholds / No LLM Certification**:
   - Thresholds are deterministic and explicitly configured in `DiscoveryPolicy`.
   - LLM/RAG/Agents are not used for invariant generation or verification.

---

## Architecture & Flow
```
         Phase 3 EvidenceBundle
                   │
                   ▼
       ObservationMatrixBuilder
       (Normalized Observation Facts)
                   │
                   ▼
         Candidate Generators
    (Bounded, Domain-Agnostic Mining)
                   │
                   ▼
          CandidateValidator
     (Empirical Support, Contradiction,
      Unknown, Confidence, Status)
                   │
                   ▼
           CandidateRanker
    (Deterministic Deduplication & Sorting)
                   │
                   ▼
            DiscoveryResult
          (Persisted to SQLite)
```

---

## Directory Structure
- `backend/discovery/models.py`: Domain-agnostic taxonomy (`DiscoveredRuleType`), validation status, deterministic fingerprints, and policy models.
- `backend/discovery/matrix.py`: `ObservationMatrixBuilder` normalizing Phase 3 evidence records into a structured 3-valued observation matrix.
- `backend/discovery/normalizer.py`: `CandidateNormalizer` performing commutative canonicalization and AST-like expression sorting.
- `backend/discovery/generators/`: Bounded candidate generators for Input/Output formulas, Type/Shape invariants, Nullability/Presence, Relational ordering, Error behavior, State invariants/transitions, Workflow sequences, and Boundary points.
- `backend/discovery/validator.py`: `CandidateValidator` evaluating hypotheses across applicable observations.
- `backend/discovery/ranking.py`: `CandidateRanker` providing deterministic deduplication and score ranking.
- `backend/discovery/persistence.py`: `DiscoveryPersistenceStore` providing SQLite persistence (`discoveries` and `discovered_candidates`).
- `backend/discovery/engine.py`: `RuleDiscoveryEngine` orchestrating Reference, Target, and Shared candidate discovery.
- `backend/api/discovery_router.py`: REST API router mounted at `/api/v2/discovery`.
- `tests/test_v2_phase6_discovery.py`: Complete test suite covering all discovery algorithms, validation metrics, role isolation, and persistence.
