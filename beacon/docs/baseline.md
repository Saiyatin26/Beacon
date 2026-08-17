# Phase 6 Baseline Demonstration Output

In Phase 6, we finalized the mining and validation architecture and introduced the `UnifiedEvidencePackage`. We integrated local hypothesis-based boundary validation, semantic contradiction checking, and confidence scoring. 

The demonstration tests whether the system can:
1. Extract static business logic variables from the legacy system AST
2. Aggregate runtime observations and match inputs against static conditions
3. Identify the undocumented loan rejection invariant and graduate it through the validation gate
4. Detect behavioral violations (the "bug") in the modernized application

## Environment
- OS: Windows
- Interpreter: Python 3.11+
- Trace samples: 1000 generated synthetic `TraceEvent` records

## Command Run

```powershell
python .\scripts\run_demo_pipeline.py
```

## Results

```text
==================================================================
           BEACON DETERMINISTIC DEMONSTRATION RUNNER
==================================================================

Stage 1a: Generated synthetic trace log (legacy_sample/trace_log.json).
Stage 1b: Loaded 1000 execution traces into TraceEvent objects.
Stage 1c: Static AST extraction completed for legacy_sample\legacy_loan_approval.py.
Stage 1d: Built UnifiedEvidencePackage containing 3 correlated facts.

Running deterministic local invariant mining and validation.

Stage 2: Mined & Validated Invariants:
  - [GRADUATED] Invariant #local-1b27dc7b: IF credit_score < 600 and debt_ratio > 0.4 THEN REJECT (Confidence: 0.78, Severity: critical)
  - [GRADUATED] Invariant #local-c7180ce5: IF credit_score < 500 THEN REJECT (Confidence: 0.75, Severity: critical)

Stage 3: Synthesized Executable Oracles:
  - Oracle #local-1b27dc7b: Property -> "assert not (credit_score < 600 and debt_ratio > 0.4) or decision == 'REJECT'"
  - Oracle #local-c7180ce5: Property -> "assert not (credit_score < 500) or decision == 'REJECT'"

Stage 4: Certifying Modernized Application against Legacy System Oracles...
================================================================================
BEACON CERTIFICATION REPORT: FAILED
================================================================================
Timestamp: 2026-08-17T12:00:00Z
Target: Loan approval
Equivalence Score: 50.00%

Violations Detected: 1
--------------------------------------------------------------------------------
1. Expected: REJECT | Actual: APPROVE
   Counterexample Inputs: {'annual_income': 43492.3, 'credit_score': 540, 'debt_ratio': 0.42}
   Legacy Output: REJECT
   Modern Output: APPROVE
================================================================================
```

## Interpretation
The output demonstrates that the integrated architecture cleanly captures both components of the invariant without human involvement. The unconfirmed candidate list functions exactly as required: rules lacking sufficient boundary validation or evidence diversity are filtered out, while true invariant rules confidently generate execution oracles. 

The demo successfully identified that the modernized `modern_loan_approval` script hallucinates an `APPROVE` decision for inputs satisfying `credit_score < 600 and debt_ratio > 0.4`.
