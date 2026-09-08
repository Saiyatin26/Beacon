# BEACON V2 — Phase 6: Full Behavioral Rule / Invariant Discovery Engine

## Mission
Phase 6 answers the foundational question:
> **"What behavioral rules and invariants can BEACON discover from the evidence that was actually observed?"**

While Phase 5 verified compliance against user-supplied rules (*"Does the application satisfy explicitly provided rules?"*), Phase 6 autonomously synthesizes candidate behavioral hypotheses directly from Phase 3 evidence without human bias, domain assumptions, or hard-coded business semantics.

---

## Key Principles & Scope Boundaries

1. **Evidence-First Discovery**:
   - Candidates are mined strictly from observed facts in tamper-evident `EvidenceBundle` instances.
   - Status normalization is **fail-closed**: any unrecognized or invalid capture status strictly becomes `UNKNOWN`.
   - Model defaults never masquerade as observed facts (`has_error: Optional[bool]`, `state_mutated: Optional[bool]`).
   - Every candidate contains complete cryptographic and relational provenance (`input_ids`, `evidence_ids`, `observation_count`).
   - Missing evidence is treated strictly as `UNKNOWN`, never conflated with support or contradiction.

2. **Domain Agnostic**:
   - Zero hardcoded domain concepts (no universal banking, healthcare, retail, or ERP business logic).
   - Rules are formulated using canonical, structural, mathematical, and observational expressions.

3. **Hypotheses vs Certified Truth**:
   - Phase 6 produces `DiscoveredCandidate` records with explicit empirical statuses (`VALIDATED`, `WEAK`, `CONTRADICTED`, `INSUFFICIENT_COVERAGE`, `INCONCLUSIVE`).
   - Phase 6 **DOES NOT** produce an `OracleSet` or perform certification. Candidate reconciliation and OracleSet selection belong exclusively to Phase 7.

4. **Persistence & Diagnostic History**:
   - Separates semantic candidate identity (`fingerprint`) from historical persistence identity (`candidate_instance_id`). Multiple discovery runs preserve full history without overwriting.
   - Failures and warnings are explicitly surfaced via `DiscoveryDiagnostic` records and `overall_status`.

---

## Directory Structure
- `backend/discovery/models.py`: Domain-agnostic taxonomy (`DiscoveredRuleType`), validation status, deterministic fingerprints, `DiscoveryDiagnostic`, and policy models.
- `backend/discovery/matrix.py`: `ObservationMatrixBuilder` with `normalize_capture_status` normalizing Phase 3 evidence records into a structured 3-valued observation matrix.
- `backend/discovery/normalizer.py`: `CandidateNormalizer` performing commutative canonicalization and AST-like expression sorting.
- `backend/discovery/generators/`: Bounded candidate generators:
  - `input_output.py`: Constants, copies, bounded linear formulas.
  - `cross_input.py`: Cross-input response invariants across diverse independent inputs.
  - `type_shape.py`: Primitive types and object key shape consistency.
  - `nullability.py`: Field presence and non-nullness.
  - `relational.py`: Relational ordering invariants (`<=`, `>=`, `==`).
  - `error_behavior.py`: Error categories and success invariants.
  - `state.py`: Pre/post state delta transitions and table count invariants.
  - `workflow.py`: Workflow sequence mining and event predecessor chains.
  - `boundary.py`: Generic boundary transitions across numeric input distributions.
- `backend/discovery/validator.py`: `CandidateValidator` evaluating hypotheses across applicable observations.
- `backend/discovery/ranking.py`: `CandidateRanker` providing deterministic deduplication and score ranking.
- `backend/discovery/persistence.py`: `DiscoveryPersistenceStore` providing SQLite persistence (`discoveries` and `discovered_candidates`).
- `backend/discovery/engine.py`: `RuleDiscoveryEngine` orchestrating Reference, Target, and Shared candidate discovery with structured diagnostics.
- `backend/api/discovery_router.py`: REST API router mounted at `/api/v2/discovery`.
- `tests/test_v2_phase6_discovery.py`: Complete test suite covering all discovery algorithms, validation metrics, role isolation, and persistence.
