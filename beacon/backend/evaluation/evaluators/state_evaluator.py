"""BEACON V2 — Phase 4 State & Side-Effect Evaluator.

Evaluates behavioral equivalence across database mutations, filesystem deltas,
and outbound HTTP calls recorded in Phase 3 evidence.
"""

from typing import Any, Optional

from ..evidence_status import EvidenceSufficiency
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
        # Convention 1: list-of-records calling convention
        if isinstance(reference_db_or_records, list) and isinstance(target_db_or_records, list):
            ref_records = reference_db_or_records
            target_records = target_db_or_records
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

        ref_db = self._extract_payload_by_type(ref_records, EvidenceType.DATABASE)
        target_db = self._extract_payload_by_type(target_records, EvidenceType.DATABASE)

        ref_file = self._extract_payload_by_type(ref_records, EvidenceType.FILESYSTEM)
        target_file = self._extract_payload_by_type(target_records, EvidenceType.FILESYSTEM)

        ref_http = self._extract_payload_by_type(ref_records, EvidenceType.HTTP)
        target_http = self._extract_payload_by_type(target_records, EvidenceType.HTTP)

        ref_eid = ref_records[0].evidence_id if ref_records else None
        target_eid = target_records[0].evidence_id if target_records else None

        return self._evaluate_typed(
            input_id=input_id,
            reference_db=ref_db,
            target_db=target_db,
            reference_file=ref_file,
            target_file=target_file,
            reference_http=ref_http,
            target_http=target_http,
            policy=policy,
            reference_evidence_id=ref_eid,
            target_evidence_id=target_eid,
        )

    def _extract_payload_by_type(self, records: list, etype: Any) -> Optional[Any]:
        """Extracts payload dict from a list of EvidenceRecord objects matching evidence_type."""
        try:
            for rec in records:
                if getattr(rec, "evidence_type", None) == etype:
                    return getattr(rec, "payload", rec)
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
        """Core state evaluation using typed evidence objects or payloads."""
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

        # If one implementation recorded state/side-effects while the other has none -> INCONCLUSIVE
        if has_ref_state != has_target_state:
            diff = BehaviorDifference(
                dimension=BehaviorDimension.STATE,
                input_id=input_id,
                difference_type=DifferenceType.EVIDENCE_MISSING,
                reference_evidence_id=reference_evidence_id,
                target_evidence_id=target_evidence_id,
                reference_value={"has_state": has_ref_state},
                target_value={"has_state": has_target_state},
                comparison_method="presence_check",
                details={
                    "message": "State/side-effect evidence present on one side but absent on the other.",
                    "reference_has_state": has_ref_state,
                    "target_has_state": has_target_state,
                },
            )
            return DimensionResult(
                dimension=BehaviorDimension.STATE,
                status=EvaluationVerdict.INCONCLUSIVE,
                verdict=EvaluationVerdict.INCONCLUSIVE,
                comparison_method="presence_check",
                difference_type=DifferenceType.EVIDENCE_MISSING,
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

        # Distinguish missing evidence from actual observed behavioral differences
        actual_diffs = [d for d in differences if d.difference_type != DifferenceType.EVIDENCE_MISSING]
        if not actual_diffs:
            return DimensionResult(
                dimension=BehaviorDimension.STATE,
                status=EvaluationVerdict.INCONCLUSIVE,
                verdict=EvaluationVerdict.INCONCLUSIVE,
                comparison_method="state_snapshots",
                difference_type=DifferenceType.EVIDENCE_MISSING,
                differences=differences,
                evidence_references=evidence_refs,
                details={"message": "State evidence is missing or insufficient on one or more subsystems."},
            )

        return DimensionResult(
            dimension=BehaviorDimension.STATE,
            status=EvaluationVerdict.DIFFERENT,
            verdict=EvaluationVerdict.DIFFERENT,
            comparison_method="state_snapshots",
            difference_type=actual_diffs[0].difference_type,
            differences=differences,
            evidence_references=evidence_refs,
            details={"total_differences": len(differences)},
        )

    # =========================================================================
    # Helpers
    # =========================================================================
    @staticmethod
    def _get(obj: Any, *keys: str, default: Any = None) -> Any:
        """Safely extracts field from dict, Pydantic model, or generic object."""
        if obj is None:
            return default
        if isinstance(obj, dict):
            for k in keys:
                if k in obj and obj[k] is not None:
                    return obj[k]
            return default
        for k in keys:
            if hasattr(obj, k):
                val = getattr(obj, k)
                if val is not None:
                    return val
        if hasattr(obj, "__dict__"):
            d = getattr(obj, "__dict__", {})
            for k in keys:
                if k in d and d[k] is not None:
                    return d[k]
        if hasattr(obj, "model_extra") and getattr(obj, "model_extra"):
            extra = getattr(obj, "model_extra")
            for k in keys:
                if k in extra and extra[k] is not None:
                    return extra[k]
        return default

    # =========================================================================
    # Database Comparison
    # =========================================================================
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
        """Evaluates database mutations across Phase 3 DatabaseEvidence models and payloads."""
        if ref_db is None or target_db is None:
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    field_path="database",
                    reference_value=bool(ref_db),
                    target_value=bool(target_db),
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="db_presence",
                )
            )
            return

        _get = self._get

        # 0. Check capture status (e.g. PARTIAL, NOT_SUPPORTED, FAILED, UNAVAILABLE, CONFIGURATION_ERROR)
        if EvidenceSufficiency.is_insufficient(ref_db) or EvidenceSufficiency.is_insufficient(target_db):
            ref_status = EvidenceSufficiency.get_status_str(ref_db) or "CAPTURED"
            target_status = EvidenceSufficiency.get_status_str(target_db) or "CAPTURED"
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    field_path="database.status",
                    reference_value=ref_status,
                    target_value=target_status,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="db_capture_status",
                    details={"message": f"Database capture status is insufficient (ref: {ref_status}, target: {target_status})."},
                )
            )

        # 1. Check delta_detected flags
        ref_delta = _get(ref_db, "delta_detected")
        target_delta = _get(target_db, "delta_detected")
        if (ref_delta is None) != (target_delta is None):
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    field_path="database.delta_detected",
                    reference_value=ref_delta,
                    target_value=target_delta,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="delta_presence",
                    details={"message": "delta_detected present on one side but missing on the other."},
                )
            )
        elif ref_delta is not None and target_delta is not None and ref_delta != target_delta:
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.DATABASE_MUTATION_MISMATCH,
                    field_path="database.delta_detected",
                    reference_value=ref_delta,
                    target_value=target_delta,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="delta_flag",
                    details={"ref_delta_detected": ref_delta, "target_delta_detected": target_delta},
                )
            )

        # 2. Check Phase 3 before/after snapshots (snapshot_before, snapshot_after)
        for snap_key in ("snapshot_before", "snapshot_after"):
            ref_snap = _get(ref_db, snap_key)
            target_snap = _get(target_db, snap_key)
            if (ref_snap is None) != (target_snap is None):
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.EVIDENCE_MISSING,
                        field_path=f"database.{snap_key}",
                        reference_value=bool(ref_snap),
                        target_value=bool(target_snap),
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="snapshot_presence",
                        details={"message": f"{snap_key} present on one side but missing on the other."},
                    )
                )
            elif ref_snap is not None and target_snap is not None and ref_snap != target_snap:
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.DATABASE_MUTATION_MISMATCH,
                        field_path=f"database.{snap_key}",
                        reference_value=ref_snap,
                        target_value=target_snap,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="snapshot_hash",
                    )
                )

        # 3. Check Phase 3 before/after row counts: table_row_counts_before, table_row_counts_after
        ref_counts_before = _get(ref_db, "table_row_counts_before", default={}) or {}
        target_counts_before = _get(target_db, "table_row_counts_before", default={}) or {}
        ref_counts_after = _get(ref_db, "table_row_counts_after", default={}) or {}
        target_counts_after = _get(target_db, "table_row_counts_after", default={}) or {}

        # 4. Check configured_tables and multi-table dictionaries
        ref_cfg_tables = _get(ref_db, "configured_tables", default=[]) or []
        target_cfg_tables = _get(target_db, "configured_tables", default=[]) or []
        ref_affected = _get(ref_db, "affected_tables", "tables", default={}) or {}
        target_affected = _get(target_db, "affected_tables", "tables", default={}) or {}

        # Collect all tracked tables across both implementations
        all_tables: set[str] = set()
        for src in (ref_counts_before, target_counts_before, ref_counts_after, target_counts_after):
            if isinstance(src, dict):
                all_tables.update(src.keys())
        all_tables.update(ref_cfg_tables if isinstance(ref_cfg_tables, (list, set)) else [])
        all_tables.update(target_cfg_tables if isinstance(target_cfg_tables, (list, set)) else [])
        if isinstance(ref_affected, dict):
            all_tables.update(ref_affected.keys())
        elif isinstance(ref_affected, (list, set)):
            all_tables.update(ref_affected)
        if isinstance(target_affected, dict):
            all_tables.update(target_affected.keys())
        elif isinstance(target_affected, (list, set)):
            all_tables.update(target_affected)

        all_tables = all_tables - set(policy.ignored_tables)

        # 5. Multi-table / Phase 3 canonical evaluation if tables are tracked
        if all_tables:
            for tbl in sorted(all_tables):
                # Check table presence
                ref_tracked = tbl in ref_cfg_tables or tbl in ref_counts_before or tbl in ref_counts_after or tbl in ref_affected
                target_tracked = tbl in target_cfg_tables or tbl in target_counts_before or tbl in target_counts_after or tbl in target_affected
                if ref_tracked != target_tracked:
                    differences.append(
                        BehaviorDifference(
                            dimension=BehaviorDimension.STATE,
                            input_id=input_id,
                            difference_type=DifferenceType.EVIDENCE_MISSING,
                            field_path=f"database.tables.{tbl}",
                            reference_value=ref_tracked,
                            target_value=target_tracked,
                            reference_evidence_id=ref_eid,
                            target_evidence_id=target_eid,
                            comparison_method="table_presence",
                            details={"message": f"Table '{tbl}' tracked on one side but missing on the other."},
                        )
                    )
                    continue

                # Check before count
                r_b = ref_counts_before.get(tbl) if isinstance(ref_counts_before, dict) else None
                t_b = target_counts_before.get(tbl) if isinstance(target_counts_before, dict) else None
                if (r_b is None) != (t_b is None):
                    differences.append(
                        BehaviorDifference(
                            dimension=BehaviorDimension.STATE,
                            input_id=input_id,
                            difference_type=DifferenceType.EVIDENCE_MISSING,
                            field_path=f"database.tables.{tbl}.before_count",
                            reference_value=r_b,
                            target_value=t_b,
                            reference_evidence_id=ref_eid,
                            target_evidence_id=target_eid,
                            comparison_method="table_before_count",
                            details={"message": f"Before row count for table '{tbl}' present on one side but missing on the other."},
                        )
                    )

                # Check after count
                r_a = ref_counts_after.get(tbl) if isinstance(ref_counts_after, dict) else None
                t_a = target_counts_after.get(tbl) if isinstance(target_counts_after, dict) else None
                if (r_a is None) != (t_a is None):
                    differences.append(
                        BehaviorDifference(
                            dimension=BehaviorDimension.STATE,
                            input_id=input_id,
                            difference_type=DifferenceType.EVIDENCE_MISSING,
                            field_path=f"database.tables.{tbl}.after_count",
                            reference_value=r_a,
                            target_value=t_a,
                            reference_evidence_id=ref_eid,
                            target_evidence_id=target_eid,
                            comparison_method="table_after_count",
                            details={"message": f"After row count for table '{tbl}' present on one side but missing on the other."},
                        )
                    )

                # Check net deltas and after counts
                if r_a is not None and t_a is not None:
                    if r_b is not None and t_b is not None:
                        ref_net_delta = r_a - r_b
                        target_net_delta = t_a - t_b
                        if ref_net_delta != target_net_delta or r_a != t_a:
                            differences.append(
                                BehaviorDifference(
                                    dimension=BehaviorDimension.STATE,
                                    input_id=input_id,
                                    difference_type=DifferenceType.DATABASE_ROW_COUNT_MISMATCH,
                                    field_path=f"database.tables.{tbl}.row_count",
                                    reference_value={"before": r_b, "after": r_a, "net_delta": ref_net_delta},
                                    target_value={"before": t_b, "after": t_a, "net_delta": target_net_delta},
                                    reference_evidence_id=ref_eid,
                                    target_evidence_id=target_eid,
                                    comparison_method="table_row_count_delta",
                                    details={
                                        "table": tbl,
                                        "ref_before": r_b,
                                        "ref_after": r_a,
                                        "ref_net_delta": ref_net_delta,
                                        "target_before": t_b,
                                        "target_after": t_a,
                                        "target_net_delta": target_net_delta,
                                    },
                                )
                            )
                    elif r_a != t_a:
                        differences.append(
                            BehaviorDifference(
                                dimension=BehaviorDimension.STATE,
                                input_id=input_id,
                                difference_type=DifferenceType.DATABASE_ROW_COUNT_MISMATCH,
                                field_path=f"database.tables.{tbl}.row_count",
                                reference_value=r_a,
                                target_value=t_a,
                                reference_evidence_id=ref_eid,
                                target_evidence_id=target_eid,
                                comparison_method="table_row_count",
                            )
                        )

        # 6. Single-table payload comparison (table, operation, row_count, records)
        ref_table = _get(ref_db, "table")
        target_table = _get(target_db, "table")
        ref_op = _get(ref_db, "operation", "op", "action")
        target_op = _get(target_db, "operation", "op", "action")

        if ref_table is not None or target_table is not None:
            if (ref_table is None) != (target_table is None):
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.EVIDENCE_MISSING,
                        field_path="database.table",
                        reference_value=ref_table,
                        target_value=target_table,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="table_name",
                        details={"message": "Table name present on one side but missing on the other."},
                    )
                )
                return

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

            # Check operation field
            if (ref_op is None) != (target_op is None):
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.EVIDENCE_MISSING,
                        field_path="database.operation",
                        reference_value=ref_op,
                        target_value=target_op,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="db_operation",
                        details={"message": "Database operation field present on one side but missing on the other."},
                    )
                )
            elif ref_op is not None and target_op is not None and str(ref_op).upper() != str(target_op).upper():
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.DATABASE_MUTATION_MISMATCH,
                        field_path="database.operation",
                        reference_value=ref_op,
                        target_value=target_op,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="db_operation",
                        details={"ref_operation": ref_op, "target_operation": target_op},
                    )
                )

            # Check row count field
            ref_row_count = _get(ref_db, "row_count", "rows_affected", "rows")
            target_row_count = _get(target_db, "row_count", "rows_affected", "rows")

            if (ref_row_count is None) != (target_row_count is None):
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.EVIDENCE_MISSING,
                        field_path=f"database.tables.{ref_table or target_table}.row_count",
                        reference_value=ref_row_count,
                        target_value=target_row_count,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="table_row_count",
                        details={"message": "Database row count field present on one side but missing on the other."},
                    )
                )
            elif ref_row_count is not None and target_row_count is not None and ref_row_count != target_row_count:
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

            # Check records field
            ref_data = _get(ref_db, "records", "data", "rows_data")
            target_data = _get(target_db, "records", "data", "rows_data")

            if (ref_data is None) != (target_data is None):
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.EVIDENCE_MISSING,
                        field_path=f"database.tables.{ref_table or target_table}.records",
                        reference_value=ref_data,
                        target_value=target_data,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="db_records",
                        details={"message": "Database records field present on one side but missing on the other."},
                    )
                )
            elif ref_data is not None and target_data is not None and ref_data != target_data:
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.DATABASE_MUTATION_MISMATCH,
                        field_path=f"database.tables.{ref_table or target_table}.records",
                        reference_value=ref_data,
                        target_value=target_data,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="db_records",
                    )
                )

    # =========================================================================
    # Filesystem Comparison
    # =========================================================================
    def _compare_file_state(
        self,
        input_id: str,
        ref_file: Any,
        target_file: Any,
        differences: list[BehaviorDifference],
        ref_eid: Optional[str],
        target_eid: Optional[str],
    ) -> None:
        """Evaluates filesystem state across Phase 3 FileEvidence snapshots and deltas."""
        if ref_file is None or target_file is None:
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    field_path="filesystem",
                    reference_value=bool(ref_file),
                    target_value=bool(target_file),
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="file_presence",
                )
            )
            return

        _get = self._get

        # 0. Check capture status (e.g. PARTIAL, NOT_SUPPORTED, FAILED, UNAVAILABLE, CONFIGURATION_ERROR)
        if EvidenceSufficiency.is_insufficient(ref_file) or EvidenceSufficiency.is_insufficient(target_file):
            ref_status = EvidenceSufficiency.get_status_str(ref_file) or "CAPTURED"
            target_status = EvidenceSufficiency.get_status_str(target_file) or "CAPTURED"
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    field_path="filesystem.status",
                    reference_value=ref_status,
                    target_value=target_status,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="file_capture_status",
                    details={"message": f"Filesystem capture status is insufficient (ref: {ref_status}, target: {target_status})."},
                )
            )

        # 1. Check delta_detected flags
        ref_delta = _get(ref_file, "delta_detected")
        target_delta = _get(target_file, "delta_detected")
        if (ref_delta is None) != (target_delta is None):
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    field_path="filesystem.delta_detected",
                    reference_value=ref_delta,
                    target_value=target_delta,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="file_delta_presence",
                )
            )
        elif ref_delta is not None and target_delta is not None and ref_delta != target_delta:
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.FILESYSTEM_DELTA_MISMATCH,
                    field_path="filesystem.delta_detected",
                    reference_value=ref_delta,
                    target_value=target_delta,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="file_delta_flag",
                )
            )

        # 2. Check Phase 3 before/after snapshots: before_state, after_state
        ref_after = _get(ref_file, "after_state", default={}) or {}
        target_after = _get(target_file, "after_state", default={}) or {}
        ref_before = _get(ref_file, "before_state", default={}) or {}
        target_before = _get(target_file, "before_state", default={}) or {}
        ref_cfg_paths = _get(ref_file, "configured_paths", default=[]) or []
        target_cfg_paths = _get(target_file, "configured_paths", default=[]) or []

        all_paths: set[str] = set()
        if isinstance(ref_after, dict):
            all_paths.update(ref_after.keys())
        if isinstance(target_after, dict):
            all_paths.update(target_after.keys())
        if isinstance(ref_before, dict):
            all_paths.update(ref_before.keys())
        if isinstance(target_before, dict):
            all_paths.update(target_before.keys())
        all_paths.update(ref_cfg_paths if isinstance(ref_cfg_paths, (list, set)) else [])
        all_paths.update(target_cfg_paths if isinstance(target_cfg_paths, (list, set)) else [])

        for path in sorted(all_paths):
            r_snap = ref_after.get(path) if isinstance(ref_after, dict) else None
            t_snap = target_after.get(path) if isinstance(target_after, dict) else None

            if (r_snap is None) != (t_snap is None):
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.EVIDENCE_MISSING,
                        field_path=f"filesystem.paths['{path}'].after_state",
                        reference_value=bool(r_snap),
                        target_value=bool(t_snap),
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="path_snapshot_presence",
                        details={"message": f"after_state for path '{path}' present on one side but missing on the other."},
                    )
                )
            elif r_snap is not None and t_snap is not None:
                r_exists = _get(r_snap, "exists")
                t_exists = _get(t_snap, "exists")
                r_hash = _get(r_snap, "sha256_hash", "hash")
                t_hash = _get(t_snap, "sha256_hash", "hash")
                r_size = _get(r_snap, "size_bytes", "size")
                t_size = _get(t_snap, "size_bytes", "size")

                # Check existence equivalence
                if (r_exists is not None) != (t_exists is not None):
                    differences.append(
                        BehaviorDifference(
                            dimension=BehaviorDimension.STATE,
                            input_id=input_id,
                            difference_type=DifferenceType.EVIDENCE_MISSING,
                            field_path=f"filesystem.paths['{path}'].exists",
                            reference_value=r_exists,
                            target_value=t_exists,
                            reference_evidence_id=ref_eid,
                            target_evidence_id=target_eid,
                            comparison_method="path_exists_presence",
                        )
                    )
                elif r_exists != t_exists:
                    differences.append(
                        BehaviorDifference(
                            dimension=BehaviorDimension.STATE,
                            input_id=input_id,
                            difference_type=DifferenceType.FILESYSTEM_DELTA_MISMATCH,
                            field_path=f"filesystem.paths['{path}'].exists",
                            reference_value=r_exists,
                            target_value=t_exists,
                            reference_evidence_id=ref_eid,
                            target_evidence_id=target_eid,
                            comparison_method="path_exists_mismatch",
                        )
                    )

                # If file exists on both sides, check hash completeness & equivalence
                if r_exists and t_exists:
                    if (r_hash is None) != (t_hash is None):
                        differences.append(
                            BehaviorDifference(
                                dimension=BehaviorDimension.STATE,
                                input_id=input_id,
                                difference_type=DifferenceType.EVIDENCE_MISSING,
                                field_path=f"filesystem.paths['{path}'].sha256_hash",
                                reference_value=r_hash,
                                target_value=t_hash,
                                reference_evidence_id=ref_eid,
                                target_evidence_id=target_eid,
                                comparison_method="path_hash_presence",
                                details={"message": f"SHA-256 hash for path '{path}' present on one side but missing on the other."},
                            )
                        )
                    elif r_hash is not None and t_hash is not None and r_hash != t_hash:
                        differences.append(
                            BehaviorDifference(
                                dimension=BehaviorDimension.STATE,
                                input_id=input_id,
                                difference_type=DifferenceType.FILESYSTEM_DELTA_MISMATCH,
                                field_path=f"filesystem.paths['{path}'].sha256_hash",
                                reference_value=r_hash,
                                target_value=t_hash,
                                reference_evidence_id=ref_eid,
                                target_evidence_id=target_eid,
                                comparison_method="file_snapshot_hash",
                                details={"path": path, "ref_hash": r_hash, "target_hash": t_hash},
                            )
                        )

                    # Check size completeness & equivalence
                    if (r_size is None) != (t_size is None):
                        differences.append(
                            BehaviorDifference(
                                dimension=BehaviorDimension.STATE,
                                input_id=input_id,
                                difference_type=DifferenceType.EVIDENCE_MISSING,
                                field_path=f"filesystem.paths['{path}'].size_bytes",
                                reference_value=r_size,
                                target_value=t_size,
                                reference_evidence_id=ref_eid,
                                target_evidence_id=target_eid,
                                comparison_method="path_size_presence",
                            )
                        )
                    elif r_size is not None and t_size is not None and r_size != t_size:
                        differences.append(
                            BehaviorDifference(
                                dimension=BehaviorDimension.STATE,
                                input_id=input_id,
                                difference_type=DifferenceType.FILESYSTEM_DELTA_MISMATCH,
                                field_path=f"filesystem.paths['{path}'].size_bytes",
                                reference_value=r_size,
                                target_value=t_size,
                                reference_evidence_id=ref_eid,
                                target_evidence_id=target_eid,
                                comparison_method="file_snapshot_size",
                            )
                        )

        # 3. Check created_files, modified_files, deleted_files lists
        for field_name in ("created_files", "modified_files", "deleted_files"):
            ref_list = _get(ref_file, field_name)
            target_list = _get(target_file, field_name)

            if (ref_list is not None) or (target_list is not None):
                if (ref_list is None) != (target_list is None):
                    differences.append(
                        BehaviorDifference(
                            dimension=BehaviorDimension.STATE,
                            input_id=input_id,
                            difference_type=DifferenceType.EVIDENCE_MISSING,
                            field_path=f"filesystem.{field_name}",
                            reference_value=ref_list,
                            target_value=target_list,
                            reference_evidence_id=ref_eid,
                            target_evidence_id=target_eid,
                            comparison_method=f"{field_name}_presence",
                            details={"message": f"Filesystem field '{field_name}' present on one side but missing on the other."},
                        )
                    )
                else:
                    ref_set = set(ref_list or [])
                    target_set = set(target_list or [])
                    if ref_set != target_set:
                        differences.append(
                            BehaviorDifference(
                                dimension=BehaviorDimension.STATE,
                                input_id=input_id,
                                difference_type=DifferenceType.FILESYSTEM_DELTA_MISMATCH,
                                field_path=f"filesystem.{field_name}",
                                reference_value=sorted(list(ref_set)),
                                target_value=sorted(list(target_set)),
                                reference_evidence_id=ref_eid,
                                target_evidence_id=target_eid,
                                comparison_method=f"{field_name}_set",
                            )
                        )

    # =========================================================================
    # HTTP Side-Effect Comparison
    # =========================================================================
    def _compare_http_state(
        self,
        input_id: str,
        ref_http: Any,
        target_http: Any,
        differences: list[BehaviorDifference],
        ref_eid: Optional[str],
        target_eid: Optional[str],
    ) -> None:
        """Evaluates HTTP outbound transaction side-effects."""
        if ref_http is None or target_http is None:
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    field_path="http",
                    reference_value=bool(ref_http),
                    target_value=bool(target_http),
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="http_presence",
                )
            )
            return

        # 0. Check capture status
        if EvidenceSufficiency.is_insufficient(ref_http) or EvidenceSufficiency.is_insufficient(target_http):
            ref_status = EvidenceSufficiency.get_status_str(ref_http) or "CAPTURED"
            target_status = EvidenceSufficiency.get_status_str(target_http) or "CAPTURED"
            differences.append(
                BehaviorDifference(
                    dimension=BehaviorDimension.STATE,
                    input_id=input_id,
                    difference_type=DifferenceType.EVIDENCE_MISSING,
                    field_path="http.status",
                    reference_value=ref_status,
                    target_value=target_status,
                    reference_evidence_id=ref_eid,
                    target_evidence_id=target_eid,
                    comparison_method="http_capture_status",
                    details={"message": f"HTTP capture status is insufficient (ref: {ref_status}, target: {target_status})."},
                )
            )

        def _get_calls(obj: Any) -> list:
            if isinstance(obj, list):
                return obj
            if isinstance(obj, dict):
                if "calls" in obj and obj["calls"] is not None:
                    return obj["calls"]
                if "endpoints" in obj and obj["endpoints"] is not None:
                    return obj["endpoints"]
                return [obj]
            if hasattr(obj, "calls") and getattr(obj, "calls") is not None:
                return getattr(obj, "calls")
            if hasattr(obj, "endpoints") and getattr(obj, "endpoints") is not None:
                return getattr(obj, "endpoints")
            if hasattr(obj, "__dict__"):
                d = getattr(obj, "__dict__", {})
                if "calls" in d and d["calls"] is not None:
                    return d["calls"]
                if "endpoints" in d and d["endpoints"] is not None:
                    return d["endpoints"]
            if hasattr(obj, "model_extra") and getattr(obj, "model_extra"):
                extra = getattr(obj, "model_extra")
                if "calls" in extra and extra["calls"] is not None:
                    return extra["calls"]
            return [obj]

        ref_calls = _get_calls(ref_http)
        target_calls = _get_calls(target_http)

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
            return

        _get = self._get

        # Compare detailed HTTP call side-effects (method, url/endpoint, status, payload)
        for idx, (rc, tc) in enumerate(zip(ref_calls, target_calls)):
            r_method = _get(rc, "method")
            t_method = _get(tc, "method")
            r_url = _get(rc, "url_or_endpoint", "url", "endpoint", "path")
            t_url = _get(tc, "url_or_endpoint", "url", "endpoint", "path")
            r_status = _get(rc, "response_status", "status", "status_code", "http_status")
            t_status = _get(tc, "response_status", "status", "status_code", "http_status")
            r_req_body = _get(rc, "request_body", "payload", "body")
            t_req_body = _get(tc, "request_body", "payload", "body")

            if (r_method is None) != (t_method is None):
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.EVIDENCE_MISSING,
                        field_path=f"http.calls[{idx}].method",
                        reference_value=r_method,
                        target_value=t_method,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="http_call_method",
                    )
                )
            elif r_method is not None and t_method is not None and str(r_method).upper() != str(t_method).upper():
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.HTTP_SIDE_EFFECT_MISMATCH,
                        field_path=f"http.calls[{idx}].method",
                        reference_value=r_method,
                        target_value=t_method,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="http_call_method",
                    )
                )

            if (r_url is None) != (t_url is None):
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.EVIDENCE_MISSING,
                        field_path=f"http.calls[{idx}].url",
                        reference_value=r_url,
                        target_value=t_url,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="http_call_url",
                    )
                )
            elif r_url is not None and t_url is not None and str(r_url) != str(t_url):
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.HTTP_SIDE_EFFECT_MISMATCH,
                        field_path=f"http.calls[{idx}].url",
                        reference_value=r_url,
                        target_value=t_url,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="http_call_url",
                    )
                )

            if (r_status is None) != (t_status is None):
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.EVIDENCE_MISSING,
                        field_path=f"http.calls[{idx}].status",
                        reference_value=r_status,
                        target_value=t_status,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="http_call_status",
                    )
                )
            elif r_status is not None and t_status is not None and r_status != t_status:
                differences.append(
                    BehaviorDifference(
                        dimension=BehaviorDimension.STATE,
                        input_id=input_id,
                        difference_type=DifferenceType.HTTP_SIDE_EFFECT_MISMATCH,
                        field_path=f"http.calls[{idx}].status",
                        reference_value=r_status,
                        target_value=t_status,
                        reference_evidence_id=ref_eid,
                        target_evidence_id=target_eid,
                        comparison_method="http_call_status",
                    )
                )

            if (r_req_body is not None) or (t_req_body is not None):
                if (r_req_body is None) != (t_req_body is None):
                    differences.append(
                        BehaviorDifference(
                            dimension=BehaviorDimension.STATE,
                            input_id=input_id,
                            difference_type=DifferenceType.EVIDENCE_MISSING,
                            field_path=f"http.calls[{idx}].request_body",
                            reference_value=r_req_body,
                            target_value=t_req_body,
                            reference_evidence_id=ref_eid,
                            target_evidence_id=target_eid,
                            comparison_method="http_call_payload",
                        )
                    )
                elif r_req_body != t_req_body:
                    differences.append(
                        BehaviorDifference(
                            dimension=BehaviorDimension.STATE,
                            input_id=input_id,
                            difference_type=DifferenceType.HTTP_SIDE_EFFECT_MISMATCH,
                            field_path=f"http.calls[{idx}].request_body",
                            reference_value=r_req_body,
                            target_value=t_req_body,
                            reference_evidence_id=ref_eid,
                            target_evidence_id=target_eid,
                            comparison_method="http_call_payload",
                        )
                    )


state_evaluator = StateEvaluator()
