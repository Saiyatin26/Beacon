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

## 3. Generic BusinessRule Schema

Rules are defined as structured AST objects without domain-specific assumptions:

```json
{
  "rule_id": "R-001",
  "name": "Minimum Age Requirement",
  "description": "Requests with customer_age >= 18 must be accepted",
  "version": 1,
  "source": "USER_DEFINED",
  "severity": "CRITICAL",
  "status": "ACTIVE",
  "condition": {
    "field": "customer_age",
    "operator": "GTE",
    "value": 18
  },
  "expected_behavior": {
    "type": "ACCEPT"
  },
  "referenced_fields": ["customer_age"],
  "metadata": {}
}
```

### Supported AST Condition Operators
- **Comparison**: `EQ` (`==`), `NE` (`!=`), `GT` (`>`), `GTE` (`>=`), `LT` (`<`), `LTE` (`<=`)
- **Membership**: `IN`, `NOT_IN`, `CONTAINS`, `NOT_CONTAINS`
- **Existence & Nullability**: `IS_NULL`, `IS_NOT_NULL`, `EXISTS`, `NOT_EXISTS`
- **Logical Composition**: Recursive `AND`, `OR`, `NOT` nodes

### Expected Behavior Types
- `ACCEPT`: HTTP 2xx / success return / non-error outcome
- `REJECT`: HTTP 4xx / rejection status / input rejection
- `RETURN_STATUS`: Explicit expected status code (e.g. `400`, `403`)
- `RETURN_VALUE`: Specific field/payload equality
- `ERROR`: Exception / HTTP 5xx error
- `STATE_CHANGE`: Valid database/state mutation
- `NO_STATE_CHANGE`: Absence of database/state mutation
- `WORKFLOW_STEP`: Specific workflow event transition

---

## 4. Evaluation Semantics

1. **Applicability Evaluation**:
   - The condition is evaluated against canonical input fields and initial state.
   - If the condition evaluates to `False`, the rule is **`NOT_APPLICABLE`** for that input (it does not generate a false `PASS`).
   - If a referenced field is completely absent from the input payload, the condition evaluates to `UNKNOWN`, yielding an **`ERROR`** or **`INCONCLUSIVE`** assessment depending on policy.

2. **Compliance Evaluation (when Applicable)**:
   - Evaluated independently for Reference and Target observable outcomes.
   - **`PASS`**: Observed behavior matches expected behavior.
   - **`FAIL`**: Observed behavior explicitly contradicts expected behavior.
   - **`INCONCLUSIVE`**: Evidence required to verify expected behavior is missing, partial, or unverified.
   - **`ERROR`**: Invalid rule structure, unresolvable field references, or incompatible operand types.

3. **Conservative Aggregation Policy**:
   - `ERROR` > `FAIL` > `INCONCLUSIVE` > `PASS` > `NOT_APPLICABLE`
   - If any rule assessment results in `ERROR`, overall status is `ERROR`.
   - Else if any applicable rule fails, overall status is `FAIL`.
   - Else if any rule is `INCONCLUSIVE`, overall status is `INCONCLUSIVE`.
   - Else if all applicable rules pass, overall status is `PASS`.
   - If no rules applied across the input set, overall status is `NOT_APPLICABLE`.

---

## 5. LLM Boundary & Security Guarantees

- **No Execution of User Code**: Rule evaluation is strictly executed via deterministic Python AST traversal in `RuleConditionEvaluator`. `eval()`, `exec()`, and `shell=True` are strictly prohibited.
- **Optional LLM Translation**: If an LLM or natural language interface is used to translate text like *"If age is below 18, reject"* into a rule, the translation is:
  1. Translated into the validated `BusinessRule` schema.
  2. Normalized and checked by `RuleValidator`.
  3. Audited with rule fingerprints.
  4. **Never** given authority to issue a certification verdict directly.
- **Offline & Deterministic**: The entire Controlled Mode engine operates offline without requiring external network calls or LLM dependencies.

---

## 6. Phase Boundary Audit Notice

> [!IMPORTANT]
> **Phase 6+ Feature Deferral Notice**
> The following capabilities are **intentionally deferred to Phase 6 and beyond** and are **NOT** implemented in Phase 5:
> - Automatic rule discovery from source code
> - Autonomous invariant mining
> - Automatic OracleSet generation
> - Dynamic threshold learning
> - Autonomous certification agents
> - RAG, PDF/DOCX document retrieval
