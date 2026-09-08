# BEACON V2 — Phase 6: Discovery Rule Types & Taxonomy

Phase 6 implements an 11-category, 100% domain-agnostic taxonomy for behavioral rule and invariant discovery.

---

## Taxonomy Overview

| DiscoveredRuleType | Description | Canonical Expression Format | Discovery Method |
| :--- | :--- | :--- | :--- |
| `INPUT_OUTPUT_RELATION` | Direct field copy, constant assignment, or linear arithmetic formula between inputs and outputs. | `output.y == 2 * input.x`, `output.code == 200`, `output.name == input.name` | `direct_relation`, `formula_fitting` |
| `OUTPUT_CONSISTENCY` | Key shape, structure, and collection format stability within outputs. | `keys(output) == ['id', 'status', 'value']` | `structural_mining` |
| `TYPE_SHAPE_INVARIANT` | Strict primitive or complex data type consistency across observations. | `typeof(output.amount) == 'number'`, `typeof(output.label) == 'string'` | `type_shape_analysis` |
| `NULLABILITY_PATTERN` | Guaranteed presence or non-nullness of output and state attributes. | `exists(output.id)`, `output.id != null` | `nullability_analysis` |
| `RELATIONAL_INVARIANT` | Ordering and comparison invariants between numeric or structural fields. | `output.min_val <= output.max_val`, `input.req_amount <= output.approved_limit` | `relational_mining` |
| `ERROR_BEHAVIOR` | Consistent error handling, absence of error on valid inputs, or stable error categories. | `has_error == false`, `error.category == 'VALIDATION_FAILED'` | `error_mining` |
| `STATE_INVARIANT` | State attributes remaining unchanged across executions or operations. | `state_after.balance == state_before.balance` | `state_invariant_analysis` |
| `STATE_TRANSITION` | Deterministic state changes between pre-execution and post-execution snapshots. | `state_after.status == 'PROCESSED'`, `state_after.count == state_before.count + 1` | `state_transition_analysis` |
| `WORKFLOW_INVARIANT` | Execution trace ordering and predecessor relationships across operations. | `trace_precedes(INIT, PROCESS)`, `trace_sequence == ['INIT', 'EXEC', 'FINISH']` | `sequence_mining` |
| `CROSS_INPUT_INVARIANT` | Behavioral relationships maintaining empirical stability across diverse independent inputs. | `output.status == 'SUCCESS'` (supported across independent inputs) | `cross_input_analysis` |
| `BOUNDARY_BEHAVIOR` | Empirical transition points in behavior discovered along numeric input distributions without domain labels. | `observed_boundary(input.score == 50.0)` | `boundary_analysis` |

---

## Candidate Validation Statuses

Every candidate discovered is evaluated against all available observation facts and assigned one of the following empirical statuses:

1. `VALIDATED`: Meets `minimum_support_count` and `minimum_confidence` with zero or acceptable contradictions.
2. `WEAK`: Demonstrates supporting observations but falls below confidence threshold or has minor contradictions.
3. `CONTRADICTED`: Directly violated by empirical observations (`confidence < 0.5`).
4. `INSUFFICIENT_COVERAGE`: Supported by all applicable observations, but total support count is below `minimum_support_count`.
5. `INCONCLUSIVE`: Applicable evidence was missing, partial, or malformed, preventing definitive evaluation.
