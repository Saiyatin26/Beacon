# BEACON V2 — Phase 3 Evidence Contract & Sufficiency Specification
**Phase 5 Contract-Lock: Observation Authority, Schema Guarantees & Sufficiency Boundaries**

---

## 1. Executive Summary & First Principle

In BEACON V2, behavioral certification relies on a strict separation of concerns across lifecycle phases:

```
┌─────────────────────────────────┐
│     PHASE 3: EXECUTION          │
│   "WHAT WAS ACTUALLY OBSERVED"  │
│  (Database, Filesystem, HTTP,   │
│   Output, Error, Traces, Logs)  │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│     PHASE 5: CONTROLLED MODE    │
│  "WHAT BUSINESS RULES CAN BE    │
│   CONCLUDED FROM OBSERVATIONS"  │
│  (Rule Engine, 3-Valued Logic,  │
│   Role Isolation, Source Zones) │
└─────────────────────────────────┘
```

**First Principle**: Phase 5 interprets Phase 3 evidence. Phase 5 must NEVER manufacture observation semantics from arbitrary payload shapes or Pydantic `extra="allow"` dictionary fields. Syntactically plausible structures (e.g. arbitrary row lists, primary-key maps, raw queries without before/after states) do not constitute certified observational state.

---

## 2. Phase 3 Evidence Producer Contract Matrix

The following matrix documents every behavioral evidence model in `backend/execution/evidence_models.py` and its corresponding producer in `backend/execution/evidence_providers.py`:

| Evidence Type | Model Name | Primary Producer | Producer Output Schema | Required Fields | Sufficiency Guarantee | Phase 5 Rule Engine Interpretation |
|---|---|---|---|---|---|---|
| **DATABASE** | `DatabaseEvidence` | `DatabaseEvidenceProvider` | `{"configured_tables": list[str], "snapshot_before": dict, "snapshot_after": dict, "table_row_counts_before": dict, "table_row_counts_after": dict, "delta_detected": bool, "status": str}` | `status`, `configured_tables` | Valid before & after table snapshots (`table_hash`, `row_count`, `rows`) OR matching row count dictionaries | Proves `STATE_CHANGE` if before $\neq$ after; proves `NO_STATE_CHANGE` if before $==$ after. Single queries or unanchored row counts yield `INSUFFICIENT` $\to$ `UNKNOWN`. |
| **FILESYSTEM** | `FileEvidence` | `FileEvidenceProvider` | `{"configured_paths": list[str], "before_state": dict[str, FileStateSnapshot], "after_state": dict[str, FileStateSnapshot], "created_files": list, "modified_files": list, "deleted_files": list, "delta_detected": bool, "status": str}` | `status`, `configured_paths` | Valid before & after path snapshots (size, SHA-256, exists) OR explicit mutation lists | Proves `STATE_CHANGE` if path modified/created/deleted; proves `NO_STATE_CHANGE` if snapshots identical. Partial/failed capture yields `INSUFFICIENT` $\to$ `UNKNOWN`. |
| **OUTPUT** | `OutputEvidence` | `ProcessExecutionAdapter` / `FunctionExecutionAdapter` | `{"raw_output": Any, "normalized_output": dict, "stdout": str, "stderr": str, "exit_code": int, "http_status": int, "duration_ms": float, "status": str}` | `status`, `exit_code` or `raw_output` | Captured output with `exit_code` / `http_status` | Evaluates `ACCEPT`, `REJECT`, `RETURN_VALUE`, `RETURN_STATUS`. Missing output yields `INSUFFICIENT` $\to$ `UNKNOWN`. |
| **ERROR** | `ErrorEvidence` | Adapter Exception Traps | `{"category": str, "message": str, "phase": str, "exception_type": str, "stack_trace": str, "status": str}` | `status`, `category`, `message` | Captured error record | Evaluates `ERROR`, `REJECT`. Absence of error evidence when error expected yields `FAIL` if execution succeeded, or `UNKNOWN` if uncaptured. |
| **HTTP** | `HttpEvidence` | `HttpExecutionAdapter` | `{"method": str, "url_or_endpoint": str, "request_headers": dict, "request_body": Any, "response_status": int, "response_headers": dict, "response_body": Any, "latency_ms": float, "status": str}` | `status`, `response_status` | Captured HTTP exchange with status code & body | Evaluates `RETURN_STATUS`, `RETURN_VALUE`, `ACCEPT`, `REJECT`. |
| **TRACE** | `TraceEvidence` | `TraceEvidenceProvider` | `{"events": list[TraceEvent], "status": str}` | `status`, `events` | Chronological list of `TraceEvent` records with `event_type` | Evaluates `WORKFLOW_STEP`. Missing trace yields `INSUFFICIENT` $\to$ `UNKNOWN`. |
| **LOG** | `LogEvidence` | `LogCollector` | `{"stdout_log": str, "stderr_log": str, "application_log": str, "log_status": str}` | `log_status` | Standard and application logs | Diagnostic context. |
| **METADATA** | `MetadataEvidence` | Session Coordinator | `{"configuration_snapshot": dict, "reproducibility_metadata": dict, "tags": list}` | Reproducibility hashes | Execution environment and reproducibility metadata | Field source `metadata` evaluation. |
| **ATOMIC RECORD** | `EvidenceRecord` | Framework Pipeline | `{"evidence_id": str, "session_id": str, "role": str, "input_id": str, "evidence_type": str, "payload": dict, "content_hash": str, "capture_status": str}` | `evidence_id`, `role`, `evidence_type`, `payload`, `content_hash`, `capture_status` | Tamper-evident SHA-256 record | Canonical atom of evidence correlated by `EvaluationInputAdapter`. |

---

## 3. Database Snapshot Schema & Validation Contract

### 3.1 Authoritative Phase 3 Database Snapshot Format
`DatabaseEvidenceProvider` captures database state via `sqlite3` using parameterized queries and SHA-256 canonical hashing:

```json
{
  "users": {
    "row_count": 2,
    "rows": [
      {"id": 1, "name": "Alice", "balance": 100.0},
      {"id": 2, "name": "Bob", "balance": 250.0}
    ],
    "table_hash": "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0"
  }
}
```

### 3.2 Legitimate Captured Empty State
An actually observed empty table is represented strictly under the Phase 3 schema as:

```json
{
  "users": {
    "row_count": 0,
    "rows": [],
    "table_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  }
}
```
Phase 5 certifies this as a genuine observational state. When Reference and Target both produce this structure before and after, `NO_STATE_CHANGE` evaluates to `PASS`.

### 3.3 Rejected Malformed & Uncontracted Structures
The following structures do NOT conform to the Phase 3 contract and are rejected by `_is_valid_db_table_snapshot`:
1. **Empty Placeholder**: `{}` $\to$ `INSUFFICIENT` (`UNKNOWN` / `INCONCLUSIVE`).
2. **Error Dictionary**: `{"error": "capture failed"}` $\to$ `INSUFFICIENT`.
3. **Empty Table Dictionary**: `{"users": {}}` $\to$ `INSUFFICIENT`.
4. **Arbitrary Non-Contract Dictionary**: `{"users": {"bad": "x"}}` $\to$ `INSUFFICIENT`.
5. **Arbitrary Row List**: `{"users": [{"id": 1}]}` $\to$ `INSUFFICIENT`.
6. **Primary-Key Map**: `{"users": {"42": {"balance": 100}}}` $\to$ `INSUFFICIENT`.
7. **Non-Dict Value**: `{"fake_table": 123}` $\to$ `INSUFFICIENT`.

---

## 4. State Mutation & Invariance Rules

1. **Before/After Snapshot Precedence**:
   - `snapshot_before == snapshot_after` $\implies$ `NO_STATE_CHANGE = PASS`, `STATE_CHANGE = FAIL`.
   - `snapshot_before != snapshot_after` $\implies$ `STATE_CHANGE = PASS`, `NO_STATE_CHANGE = FAIL`.
2. **Table Row Counts**:
   - Supported when `table_row_counts_before` and `table_row_counts_after` contain non-negative integer counts for valid table names matching configured tables.
3. **Fields Phase 3 Does NOT Guarantee**:
   - `affected_rows` and `mutation_confirmed` are NOT produced by Phase 3 `DatabaseEvidenceProvider` and are NOT part of `DatabaseEvidence`.
   - Arbitrary payloads containing `{"affected_rows": 1}` without Phase 3 before/after snapshots or row counts are rejected as `INSUFFICIENT` $\to$ `UNKNOWN`.
   - Generic records (e.g. `[{"query": "SELECT * FROM users"}]`) do NOT prove state change.

---

## 5. Three-Valued Logic & Evidence Sufficiency

Controlled rule evaluation preserves strict Three-Valued Logic:

$$\text{Verdict} \in \{\text{PASS (TRUE)}, \text{FAIL (FALSE)}, \text{INCONCLUSIVE (UNKNOWN)}\}$$

- **TRUE / PASS**: Conclusively proven by sufficient observational evidence meeting all rule criteria.
- **FALSE / FAIL**: Conclusively contradicted by sufficient observational evidence.
- **UNKNOWN / INCONCLUSIVE**: Missing, partial, failed, malformed, or uncontracted evidence.

**Aggregation Rule**:
- Any required rule evaluating to `INCONCLUSIVE` produces an overall verdict of `INCONCLUSIVE`.
- Any required rule evaluating to `FAIL` produces an overall verdict of `FAIL` (or `REJECT`).
- Overall verdict is `PASS` if and only if ALL required rules evaluate to `PASS`.

---

## 6. Role & Source Isolation Guarantees

1. **Role Isolation**: Reference evidence and Target evidence are maintained in strict isolation during condition and behavior evaluation. Reference evidence cannot satisfy Target expectations, and Target evidence cannot satisfy Reference expectations.
2. **Source Isolation**: Evaluation contexts are partitioned into isolated source zones (`input`, `output`, `state`, `error`, `metadata`). Rules specifying `field_source="output"` cannot read data from `state` or `error`.
