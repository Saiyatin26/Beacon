# Phases 1–7 Baseline & Architectural Verification

## Overview
This document records the baseline results and architectural verification of the BEACON system at the completion of Phase 7 and the Decoupled Multi-Provider Infrastructure Layer (OpenRouter, Anthropic, Ollama, Offline).

The verified end-to-end flow is:
```
                      LEGACY SOFTWARE
                            │
               ┌────────────┴────────────┐
               ▼                         ▼
        STATIC ANALYSIS            RUNTIME TRACING
               │                         │
               ▼                         ▼
        STATIC EVIDENCE             DYNAMIC EVIDENCE
               │                         │
               └────────────┬────────────┘
                            ▼
                 UNIFIED EVIDENCE PACKAGE
                            │
                            ▼
                ┌───────────────────────┐
                │ PHASE 6               │
                │ EVIDENCE SELECTION    │
                └───────────┬───────────┘
                            ▼
                    STRUCTURED PROMPT
                            │
                            ▼
                ┌───────────────────────┐
                │   PROVIDER MANAGER    │
                │  (OpenRouter Primary, │
                │   Anthropic Supported,│
                │   Ollama Local,       │
                │   Offline Fallback)   │
                └───────────┬───────────┘
                            │
                            ▼
                   CANDIDATE INVARIANT
               (with full LLM provenance)
                            │
                            ▼
                      NORMALIZATION
                            │
                            ▼
                       DEDUPLICATION
                            │
                            ▼
                   SEMANTIC GROUNDING
                   ┌────────┴────────┐
                   ▼                 ▼
               GROUNDED         GROUNDING_FAILED
                   │
                   ▼
                ┌────────────────────────┐
                │ PHASE 7                │
                │ ADVERSARIAL VALIDATOR  │
                └───────────┬────────────┘
                            │
                ┌───────────┼────────────┐
                ▼           ▼            ▼
            BOUNDARY    NEAR-BOUNDARY  DIVERSE
              TESTS        TESTS       TESTS
                └───────────┼────────────┘
                            ▼
                    LEGACY EXECUTION
                            │
                            ▼
                    PROPERTY EVALUATION
                            │
                   ┌────────┴────────┐
                   ▼                 ▼
                 PASS              FAIL
                   │                 │
                   │           COUNTEREXAMPLE
                   │                 │
                   │           MINIMIZE/SHRINK
                   │                 │
                   └────────┬────────┘
                            ▼
                   CONTRADICTION CHECK
                            │
                            ▼
                   VALIDATION REPORT
                            │
                            ▼
                   CENTRAL CONFIDENCE
                        SCORER
                            │
                            ▼
                       0.8 GATE
                      /         \
                     ▼           ▼
              UNCONFIRMED    VALIDATED
              / INVALIDATED     │
                                ▼
                           PHASE 8 ORACLES
```

## System Environment & Specification
- **Operating System**: Windows (win32)
- **Python Version**: Python 3.11.9
- **Current Active Parser**: Python AST parser (`backend/ingestion/legacy_parser.py`, `backend/ingestion/static_analyzer.py`), extracting structured facts (conditions, comparisons, assignments, function calls, return statements, and source lines).
- **Multi-Provider LLM Hierarchy**: OpenRouter (Primary), Anthropic (Supported), Ollama Qwen/Mistral (Local), Offline Rule Synthesizer (Deterministic fallback).
- **Test Suite Status**: **87 passed in 12.39s** (`python -m pytest -q`).

## Deterministic Demonstration Execution

Command:
```powershell
python .\scripts\run_demo_pipeline.py
```

Console Output:
```text
==================================================================
           BEACON DETERMINISTIC DEMONSTRATION RUNNER             
==================================================================

Stage 1b: Loaded 325 execution traces into TraceEvent objects.
Stage 1c: Static AST extraction completed for legacy_sample/legacy_loan_approval.py.
Stage 1d: Built UnifiedEvidencePackage containing 7 correlated facts.

Running deterministic local invariant mining and validation.

Stage 2: Mined & Validated Invariants:
  - [GRADUATED] Invariant #local-c7180ce5: IF credit_score < 500 THEN REJECT (Confidence: 0.94, Severity: critical)
  - [GRADUATED] Invariant #local-1b27dc7b: IF credit_score < 600 and debt_ratio > 0.4 THEN REJECT (Confidence: 0.93, Severity: critical)
  - [UNCONFIRMED] Hypothesis #local-9aae83ec: IF annual_income < 20000 and debt_ratio > 0.6 THEN REJECT (Failed gate with Confidence: 0.63)

Stage 3: Synthesized Executable Oracles:
  - Oracle #local-c7180ce5: Property -> "(credit_score < 500) implies (decision == 'REJECT')"
  - Oracle #local-1b27dc7b: Property -> "(credit_score < 600 and debt_ratio > 0.4) implies (decision == 'REJECT')"

Stage 4: Certifying Modernized Application against Legacy System Oracles...

BEHAVIORAL EQUIVALENCE REPORT — run b00cca61
Overall Equivalence Score: 50.2%

By domain:
  Loan approval                50%

Checked: 49   Violated: 11

Invariant #local-1b27dc7b
  Expected:       (credit_score < 600 and debt_ratio > 0.4) implies (decision == 'REJECT')
  Legacy output:  REJECT
  Modern output:  APPROVE
  Counterexample: {'credit_score': 598, 'debt_ratio': 0.6469415316592227, 'annual_income': 133033.79203576746}
  Confidence: 0.93   Severity: critical

Saved this certification run to data/beacon.sqlite3 for the dashboard.
```

## Architectural Highlights Verified
1. **Decoupled Multi-Provider Layer**: `LLMCandidateGenerator` communicates strictly with `ProviderManager`. Supports OpenRouter (primary), Anthropic (supported), Ollama (local), and offline fallback.
2. **Generic Infrastructure**: Zero hardcoded domain or business-rule conditions exist in generic infrastructure (`backend/evidence/builder.py`, `backend/ingestion/runtime_tracer.py`, `backend/mining/evidence_collector.py`, `backend/mining/grounding_checker.py`, `backend/mining/adversarial.py`).
3. **Authoritative Evidence Package & Normalization**: `UnifiedEvidencePackage` is the authoritative source. Expressions are normalized to allow commutative AST matching and recover matching execution IDs and static evidence.
4. **Semantic Grounding**: Candidates citing invalid variables, unsupported thresholds, nonexistent evidence IDs, mismatched source lines, or unsupported consequences are rejected immediately with `GROUNDING_FAILED`.
5. **Adversarial Validation & Separated Metrics**: Multi-strategy testing generates exact boundaries ($T-\epsilon, T, T+\epsilon$), near-boundary jitters, combinatorial truth tables, and diverse property inputs, tracking `boundary_pass_rate` and `diverse_input_pass_rate` separately.
6. **Counterexample Minimization & Refutation**: Deliberately incorrect candidates (e.g. `credit_score < 600 -> APPROVE`) are actively refuted, minimized to clean counterexamples, marked `INVALIDATED`, and strictly refused graduation.
7. **Centralized Confidence Gating**: Confidence is scored centrally in `confidence_scorer.py` using weighted evidence, diversity, boundary pass rate, and contradiction penalties with an authoritative 0.8 gate.
8. **Independent Certification**: Certification (Phases 9–10) executes against compiled executable oracles without calling any LLM.
