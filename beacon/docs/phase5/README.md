# BEACON V2 — Phase 5: Business-Rule Understanding + Controlled Mode

## 1. Overview & Architectural Role

Phase 5 introduces **Controlled Mode** and a generic, domain-agnostic **Business-Rule Understanding** capability to BEACON V2.

```
                    ┌─────────────────────────┐
                    │       PHASE 3           │
                    │ Real Execution +        │
                    │ Evidence Capture        │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │       PHASE 4           │
                    │ Behavioral Equivalence  │
                    │                         │
                    │ Ref ≡ Target ?          │
                    └────────────┬────────────┘
                                 │
                     ┌───────────┴───────────┐
                     │                       │
                     ▼                       ▼
              Behavioral Result        Evidence
                     │                       │
                     └───────────┬───────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │       PHASE 5           │
                    │ Controlled Business     │
                    │ Rule Understanding      │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │ User-Defined Rules      │
                    │                         │
                    │ Rule → Evidence →       │
                    │ Expected Behavior       │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │ Rule Compliance         │
                    │                         │
                    │ PASS / FAIL /           │
                    │ INCONCLUSIVE / ERROR    │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │ Combined Certification  │
                    │ Evidence / Audit Report │
                    └─────────────────────────┘
```

In Controlled Mode, the **user is the authority**. The user explicitly specifies the business rules and behavioral constraints that BEACON must verify against the observed execution evidence (from Phase 3) and behavioral equivalence findings (from Phase 4).

---

## 2. Fundamental Distinction: Phase 4 vs Phase 5

| Aspect | Phase 4 (Behavioral Equivalence) | Phase 5 (Controlled Rule Compliance) |
| :--- | :--- | :--- |
| **Core Question** | *Did Reference and Target behave identically?* (`Ref ≡ Target ?`) | *Did observed behavior satisfy user rules?* (`Behavior ⊨ Rule ?`) |
| **Source of Truth** | Real observable Phase 3 evidence across output, error, state, workflow | User-defined `BusinessRule` specification and expectations |
| **Outcomes** | `EQUIVALENT`, `DIFFERENT`, `INCONCLUSIVE` | `PASS`, `FAIL`, `INCONCLUSIVE`, `NOT_APPLICABLE`, `ERROR` |
| **Role Separation** | Does not judge business validity; strictly compares observable behaviors | Evaluates whether reference/target outputs, status codes, and states comply with rules |

### Example Demonstrating the Separation
Suppose a user defines a rule: *"Requests with missing required parameters must be rejected with HTTP 400."*
- **Reference Behavior**: Returns `400 Bad Request` (Complies with Rule: `PASS`)
- **Target Behavior**: Returns `200 OK` (Violates Rule: `FAIL`)
- **Phase 4 Verdict**: `DIFFERENT`
- **Phase 5 Verdict**: Reference = `PASS`, Target = `FAIL` (Overall Rule Compliance = `FAIL`)

Both results are preserved in the certification dossier.

---

## 3. Strict Three-Valued Condition Semantics

To eliminate silent false-passes or incorrect applicability calculations, Phase 5 implements explicit **three-valued logic**:
- **`TRUE`**: The condition is definitely satisfied by the input/context.
- **`FALSE`**: The condition is definitely not satisfied by the input/context.
- **`UNKNOWN`**: The condition cannot be evaluated (e.g. referenced input fields are `MISSING`).

### Applicability Mapping
- $\text{TRUE} \longrightarrow \mathbf{APPLICABLE}$
- $\text{FALSE} \longrightarrow \mathbf{NOT\_APPLICABLE}$
- $\text{UNKNOWN} \longrightarrow \mathbf{INCONCLUSIVE}$ (Rule condition applicability is uncertain; never collapsed to `NOT_APPLICABLE` or `PASS`).

### Three-Valued Truth Tables
- **`AND`**:
  - `TRUE AND TRUE = TRUE`
  - `TRUE AND FALSE = FALSE`
  - `TRUE AND UNKNOWN = UNKNOWN`
  - `FALSE AND UNKNOWN = FALSE` (False dominates)
  - `UNKNOWN AND UNKNOWN = UNKNOWN`
- **`OR`**:
  - `TRUE OR FALSE = TRUE` (True dominates)
  - `TRUE OR UNKNOWN = TRUE`
  - `FALSE OR FALSE = FALSE`
  - `FALSE OR UNKNOWN = UNKNOWN`
  - `UNKNOWN OR UNKNOWN = UNKNOWN`
- **`NOT`**:
  - `NOT TRUE = FALSE`
  - `NOT FALSE = TRUE`
  - `NOT UNKNOWN = UNKNOWN`

### Exact Value State Preservation
The condition evaluator strictly distinguishes between:
1. `MISSING` (absent from dictionary context)
2. `NULL` (`None`)
3. `ZERO` (`0`)
4. `FALSE` (`False`)
5. `EMPTY STRING` (`""`)
6. `EMPTY ARRAY` (`[]`)
7. `ACTUAL VALUE`

---

## 4. Evidence Sufficiency as a Mandatory Precondition

Before evaluating behavioral compliance for an applicable rule, the engine executes an **evidence sufficiency check**:
1. **`ACCEPT`**: Requires captured output/HTTP execution evidence proving success.
2. **`REJECT`**: Requires observable output/error/HTTP execution evidence.
3. **`RETURN_VALUE`**: Requires captured output evidence containing the requested field.
4. **`RETURN_STATUS`**: Requires captured HTTP or process exit status evidence.
5. **`STATE_CHANGE`**: Requires database, filesystem, or HTTP call mutation evidence.
6. **`NO_STATE_CHANGE`**: Requires complete before/after state snapshots proving no state change occurred.
7. **`WORKFLOW_STEP`**: Requires captured trace evidence.
8. **`ERROR`**: Requires captured error/output evidence.

If evidence is **`INSUFFICIENT`**, the rule assessment immediately yields **`INCONCLUSIVE`** (preventing false passes).

---

## 5. Conservative Aggregation Policy

$$\mathbf{ERROR} \succ \mathbf{FAIL} \succ \mathbf{INCONCLUSIVE} \succ \mathbf{PASS} \succ \mathbf{NOT\_APPLICABLE}$$
- If any assessment results in `ERROR`, overall status is `ERROR`.
- Else if any applicable rule fails, overall status is `FAIL`.
- Else if any rule is `INCONCLUSIVE`, overall status is `INCONCLUSIVE`.
- Else if all applicable rules pass, overall status is `PASS`.
- If no rules applied across the input set, overall status is `NOT_APPLICABLE`.

---

## 6. LLM Boundary & Security Guarantees

- **No Execution of User Code**: Rule condition evaluation uses a deterministic AST walker without `eval()`, `exec()`, or `shell=True`.
- **Optional LLM Translation**: Any natural-language interpreter is strictly an optional translation adapter into the validated `BusinessRule` schema. The LLM is **never** the final certification authority.
- **Durable Persistence**: Rules and evaluation audits are stored in SQLite (`beacon_business_rules` and `beacon_controlled_evaluations`) ensuring immutable versioning and surviving process restarts.

---

## 7. Phase Boundary Audit Notice

> [!IMPORTANT]
> **Phase 6+ Feature Deferral Notice**
> The following capabilities are **intentionally deferred to Phase 6 and beyond** and are **NOT** implemented in Phase 5:
> - Automatic rule discovery from source code
> - Autonomous invariant mining
> - Automatic OracleSet generation
> - Dynamic threshold learning
> - Autonomous certification agents
> - RAG, PDF/DOCX document retrieval
