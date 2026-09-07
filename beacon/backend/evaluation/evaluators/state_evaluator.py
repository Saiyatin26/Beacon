"""BEACON V2 — Phase 4 State & Side-Effect Evaluator.

Evaluates behavioral equivalence across database mutations, filesystem deltas,
and outbound HTTP calls recorded in Phase 3 evidence.
"""

from typing import Any, Optional

from ..models import (
    BehaviorDifference,
    BehaviorDimension,
    DifferenceType,
    DimensionResult,
    EvaluationVerdict,
)
from ..policies import ComparisonPolicy, StateComparisonPolicy


class StateEvaluator:
    """Evaluates state and side-effect equivalence between Reference and Target."""

    def evaluate(
        self,
        input_id: str,
        reference_db_or_records: Optional[Any] = None,
        target_db_or_records: Optional[Any] = None,
        policy_or_file: Optional[Any] = None,
        reference_file: Optional[Any] = None,
        target_file: Optional[Any] = None,
        reference_http: Optional[Any] = None,
        target_http: Optional[Any] = None,
        policy: Optional[ComparisonPolicy] = None,
        reference_evidence_id: Optional[str] = None,
        target_evidence_id: Optional[str] = None,
    ) -> DimensionResult:
        """Evaluates database, filesystem, and HTTP side-effect deltas.

        Accepts two calling conventions:
        1. (input_id, ref_records_list, target_records_list, policy)
           where records are list[EvidenceRecord] or list[dict].
        2. (input_id, ref_db, target_db, ref_file, target_file, ref_http, target_http, policy)
           where each argument is a typed evidence object.
        """
        # --- Detect calling convention ---
        # Convention 1: third argument is a list (records-based)
        if isinstance(reference_db_or_records, list) and isinstance(target_db_or_records, list):
            ref_records = reference_db_or_records
            target_records = target_db_or_records
            # policy_or_file is actually the policy in this convention
            effective_policy = policy_or_file if isinstance(policy_or_file, ComparisonPolicy) else policy
            if effective_policy is None:
                from ..policies import DEFAULT_COMPARISON_POLICY
                effective_policy = DEFAULT_COMPARISON_POLICY
            return self._evaluate_from_records(input_id, ref_records, target_records, effective_policy)

        # Convention 2: per-type arguments
        reference_db = reference_db_or_records
        target_db = target_db_or_records
        if isinstance(policy_or_file, ComparisonPolicy):
            effective_policy = policy_or_file
        else:
            effective_policy = policy
            reference_file = policy_or_file if reference_file is None else reference_file

        if effective_policy is None:
            from ..policies import DEFAULT_COMPARISON_POLICY
            effective_policy = DEFAULT_COMPARISON_POLICY

        return self._evaluate_typed(
            input_id=input_id,
            reference_db=reference_db,
            target_db=target_db,
            reference_file=reference_file,
            target_file=target_file,
            reference_http=reference_http,
            target_http=target_http,
            policy=effective_policy,
            reference_evidence_id=reference_evidence_id,
            target_evidence_id=target_evidence_id,
        )

    def _evaluate_from_records(
        self,
        input_id: str,
        ref_records: list,
        target_records: list,
        policy: ComparisonPolicy,
    ) -> DimensionResult:
        """Evaluates state from lists of EvidenceRecord objects."""
        from execution.evidence_models import EvidenceType

        ref_db = self._extract_db_from_records(ref_records)
        target_db = self._extract_db_from_records(target_records)

        ref_eid = ref_records[0].evidence_id if ref_records else None
        target_eid = target_records[0].evidence_id if target_records else None

        return self._evaluate_typed(
            input_id=input_id,
            reference_db=ref_db,
            target_db=target_db,
            reference_file=None,
            target_file=None,
            reference_http=None,
            target_http=None,
            policy=policy,
            reference_evidence_id=ref_eid,
            target_evidence_id=target_eid,
        )

    def _extract_db_from_records(self, records: list) -> Optional[Any]:
        """Extracts DB evidence payload dict from a list of EvidenceRecord objects."""
        try:
            from execution.evidence_models import EvidenceType
            for rec in records:
                if rec.evidence_type == EvidenceType.DATABASE:
                    return rec.payload
        except Exception:
            pass
        return None

    def _evaluate_typed(
        self,
        input_id: str,
        reference_db: Optional[Any],
        target_db: Optional[Any],
        reference_file: Optional[Any],
        target_file: Optional[Any],
        reference_http: Optional[Any],
        target_http: Optional[Any],
        policy: ComparisonPolicy,
        reference_evidence_id: Optional[str] = None,
        target_evidence_id: Optional[str] = None,
    ) -> DimensionResult:
        """Core state evaluation using typed evidence objects."""
        state_policy = policy.state_policy
        evidence_refs = [eid for eid in (reference_evidence_id, target_evidence_id) if eid]

        has_ref_state = (reference_db is not None) or (reference_file is not None) or (reference_http is not None)
        has_target_state = (target_db is not None) or (target_file is not None) or (target_http is not None)

        # If neither implementation has state evidence
        if not has_ref_state and not has_target_state:
            return DimensionResult(
                dimension=BehaviorDimension.STATE,
                status=EvaluationVerdict.NOT_APPLICABLE,
                verdict=EvaluationVerdict.NOT_APPLICABLE,
                comparison_method="none",
                details={"message": "No state or side-effect evidence recorded for either implementation."},
            )

        # If one implementation mutated state and the other did not
        if has_ref_state != has_target_state:
            diff = BehaviorDifference(
                dimension=BehaviorDimension.STATE,
                input_id=input_id,
                difference_type=DifferenceType.STATE_DELTA_MISMATCH,
                reference_evidence_id=reference_evidence_id,
                target_evidence_id=target_evidence_id,
                reference_value={"has_state": has_ref_state},
                target_value={"has_state": has_target_state},
                comparison_method="presence_check",
                details={
                    "message": "One implementation recorded state/side-effects while the other recorded none.",
                    "reference_has_state": has_ref_state,
                    "target_has_state": has_target_state,
                },
            )
            return DimensionResult(
                dimension=BehaviorDimension.STATE,
                status=EvaluationVerdict.DIFFERENT,
                verdict=EvaluationVerdict.DIFFERENT,
                comparison_method="presence_check",
                difference_type=DifferenceType.STATE_DELTA_MISMATCH,
                differences=[diff],
                evidence_references=evidence_refs,
            )

        differences: list[BehaviorDifference] = []

        # 1. Database State Comparison
        if state_policy.compare_database and (reference_db is not None or target_db is not None):
            self._compare_db_state(
                input_id=input_id,
                ref_db=reference_db,
                target_db=target_db,
                policy=state_policy,
                differences=differences,
                ref_eid=reference_evidence_id,
                target_eid=target_evidence_id,
            )

        # 2. Filesystem Delta Comparison
        if state_policy.compare_filesystem and (reference_file is not None or target_file is not None):
            self._compare_file_state(
                input_id=input_id,
                ref_file=reference_file,
                target_file=target_file,
                differences=differences,
                ref_eid=reference_evidence_id,
                target_eid=target_evidence_id,
            )

        # 3. HTTP Call Side-Effect Comparison
        if state_policy.compare_http and (reference_http is not None or target_http is not None):
            self._compare_http_state(
                input_id=input_id,
                ref_http=reference_http,
                target_http=target_http,
                differences=differences,
                ref_eid=reference_evidence_id,
                target_eid=target_evidence_id,
            )

        if not differences:
            return DimensionResult(
                dimension=BehaviorDimension.STATE,
                status=EvaluationVerdict.EQUIVALENT,
                verdict=EvaluationVerdict.EQUIVALENT,
                comparison_method="state_snapshots",
                evidence_references=evidence_refs,
                details={"message": "All observable state mutations and side-effects are equivalent."},
            )

        return DimensionResult(
            dimension=BehaviorDimension.STATE,
            status=EvaluationVerdict.DIFFERENT,
            verdict=EvaluationVerdict.DIFFERENT,
            comparison_method="state_snapshots",
            difference_type=differences[0].difference_type,
            differences=differences,
            evidence_references=evidence_refs,
            details={"total_differences": len(differences)},
        )

    def _compare_db_state(
        self,
        input_id: str,
        ref_db: Any,
        target_db: Any,
        policy: StateComparisonPolicy,
        differences: list[BehaviorDifference],
        ref_eid: Optional[str],
        target_eid: Optional[str],
    ) -> None:
        if ref_db is None or target_db is None:
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.DATABASE_MUTATION_MISMATCH,
                    field_path="database",
                    reference_value=bool(ref_db),
                    target_value=bool(target_db),
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="db_presence",
                )
            )
            return

        # Helper: get field from dict OR object attribute
        def _get(obj: Any, *keys: str, default: Any = None) -> Any:
            if isinstance(obj, dict):
                for k in keys:
                    if k in obj:
                        return obj[k]
                return default
            for k in keys:
                v = getattr(obj, k, None)
                if v is not None:
                    return v
            return default

        # Compare single-table payloads ({"table": "...", "row_count": ...})
        ref_table = _get(ref_db, "table")
        target_table = _get(target_db, "table")

        if ref_table is not None or target_table is not None:
            # Single-table comparison mode
            if ref_table != target_table and ref_table not in policy.ignored_tables and target_table not in policy.ignored_tables:
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.DATABASE_MUTATION_MISMATCH,
                        field_path="database.table",
                        reference_value=ref_table,
                        target_value=target_table,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="table_name",
                    )
                )
                return

            ref_row_count = _get(ref_db, "row_count", "rows_affected", "rows")
            target_row_count = _get(target_db, "row_count", "rows_affected", "rows")

            if ref_row_count is not None and target_row_count is not None:
                if ref_row_count != target_row_count:
                    differences.append(
                        BehaviorDifference(
                            dimension=BehaviorDimension.STATE,
                            input_id=input_id,
                            difference_type=DifferenceType.DATABASE_ROW_COUNT_MISMATCH,
                            field_path=f"database.tables.{ref_table or target_table}.row_count",
                            reference_value=ref_row_count,
                            target_value=target_row_count,
                            reference_evidence_id=ref_eid,
                            target_evidence_id=target_eid,
                            comparison_method="table_row_count",
                        )
                    )
            return

        # Multi-table payload (affected_tables / tables dict)
        ref_tables_raw = _get(ref_db, "affected_tables", "tables", default={})
        target_tables_raw = _get(target_db, "affected_tables", "tables", default={})

        if isinstance(ref_tables_raw, list):
            ref_t_set = set(ref_tables_raw) - set(policy.ignored_tables)
        elif isinstance(ref_tables_raw, dict):
            ref_t_set = set(ref_tables_raw.keys()) - set(policy.ignored_tables)
        else:
            ref_t_set = set()

        if isinstance(target_tables_raw, list):
            target_t_set = set(target_tables_raw) - set(policy.ignored_tables)
        elif isinstance(target_tables_raw, dict):
            target_t_set = set(target_tables_raw.keys()) - set(policy.ignored_tables)
        else:
            target_t_set = set()

        if ref_t_set != target_t_set:
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.DATABASE_MUTATION_MISMATCH,
                    field_path="database.affected_tables",
                    reference_value=sorted(list(ref_t_set)),
                    target_value=sorted(list(target_t_set)),
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="table_set",
                )
            )

        # Check row count deltas if available
        ref_counts = _get(ref_db, "row_counts", default={}) or {}
        target_counts = _get(target_db, "row_counts", default={}) or {}
        for tbl in ref_t_set & target_t_set:
            if tbl in ref_counts and tbl in target_counts:
                if ref_counts[tbl] != target_counts[tbl]:
                    differences.append(
                        BehaviorDifference(
                            dimension=BehaviorDimension.STATE,
                            input_id=input_id,
                            difference_type=DifferenceType.DATABASE_ROW_COUNT_MISMATCH,
                            field_path=f"database.tables.{tbl}.row_count",
                            reference_value=ref_counts[tbl],
                            target_value=target_counts[tbl],
                            reference_evidence_id=ref_eid,
                            target_evidence_id=target_eid,
                            comparison_method="table_row_count",
                        )
                    )


    def _compare_file_state(
        self,
        input_id: str,
        ref_file: Any,
        target_file: Any,
        differences: list[BehaviorDifference],
        ref_eid: Optional[str],
        target_eid: Optional[str],
    ) -> None:
        if ref_file is None or target_file is None:
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.FILESYSTEM_DELTA_MISMATCH,
                    field_path="filesystem",
                    reference_value=bool(ref_file),
                    target_value=bool(target_file),
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="file_presence",
                )
            )
            return

        ref_created = set(getattr(ref_file, "created_files", []) or [])
        target_created = set(getattr(target_file, "created_files", []) or [])
        if ref_created != target_created:
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.FILESYSTEM_DELTA_MISMATCH,
                    field_path="filesystem.created_files",
                    reference_value=sorted(list(ref_created)),
                    target_value=sorted(list(target_created)),
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="created_files_set",
                )
            )

    def _compare_http_state(
        self,
        input_id: str,
        ref_http: Any,
        target_http: Any,
        differences: list[BehaviorDifference],
        ref_eid: Optional[str],
        target_eid: Optional[str],
    ) -> None:
        if ref_http is None or target_http is None:
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.HTTP_SIDE_EFFECT_MISMATCH,
                    field_path="http",
                    reference_value=bool(ref_http),
                    target_value=bool(target_http),
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="http_presence",
                )
            )
            return

        ref_calls = getattr(ref_http, "calls", []) or getattr(ref_http, "endpoints", []) or []
        target_calls = getattr(target_http, "calls", []) or getattr(target_http, "endpoints", []) or []

        if len(ref_calls) != len(target_calls):
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.HTTP_SIDE_EFFECT_MISMATCH,
                    field_path="http.call_count",
                    reference_value=len(ref_calls),
                    target_value=len(target_calls),
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="http_call_count",
                )
            )


state_evaluator = StateEvaluator()
