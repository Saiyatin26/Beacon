"""Stage 1 Evidence Package Builder (Phase 5).

TECHNICAL MECHANISM DOCUMENTATION:
=================================
Problem Solved:
  Integrates disjoint static AST facts and dynamic trace records into a unified,
  serializable evidence package with full provenance tracking.
  All extraction and correlation is generic and domain-agnostic.

How It Works:
  The EvidencePackageBuilder iterates over extracted static AST conditions/comparisons
  and dynamic trace events, maps execution IDs to source file locations, and builds
  CorrelatedConditionEvidence objects aggregating static support, runtime observation counts,
  unique input coverage, boundary cases, and outcome frequencies.

Inputs:
  - StaticAnalysisResult (from Stage 1 / Phase 3)
  - TraceEvent list (from Stage 1 / Phase 4)

Outputs:
  - UnifiedEvidencePackage containing full provenance and correlated evidence data.
"""

from datetime import datetime, timezone
import json
import re
import uuid
from typing import Optional

from common.models import StaticAnalysisResult, TraceEvent
from common.dsl_eval import eval_condition
from .models import (
    CorrelatedConditionEvidence,
    DynamicEvidenceItem,
    StaticEvidenceItem,
    UnifiedEvidencePackage,
)


class EvidencePackageBuilder:
    """Builder class for assembling UnifiedEvidencePackage instances."""

    def __init__(
        self,
        static_analysis: Optional[StaticAnalysisResult] = None,
        runtime_traces: Optional[list[TraceEvent]] = None,
    ):
        self.static_analysis = static_analysis
        self.runtime_traces = runtime_traces or []

    def build_package(
        self, project_id: str = "beacon-project", package_id: Optional[str] = None
    ) -> UnifiedEvidencePackage:
        pkg_id = package_id or f"PKG-{uuid.uuid4().hex[:6]}"
        timestamp = datetime.now(timezone.utc).isoformat()
        source_file = self.static_analysis.file if self.static_analysis else "unknown"
        language = self.static_analysis.language if self.static_analysis else "python"

        static_items = self._build_static_items()
        dynamic_items = self._build_dynamic_items()
        correlated = self._build_correlated_evidence(static_items, dynamic_items)

        return UnifiedEvidencePackage(
            package_id=pkg_id,
            project_id=project_id,
            source_file=source_file,
            language=language,
            timestamp=timestamp,
            static_analysis=self.static_analysis,
            runtime_traces=self.runtime_traces,
            static_evidence_items=static_items,
            dynamic_evidence_items=dynamic_items,
            correlated_conditions=correlated,
        )

    def _build_static_items(self) -> list[StaticEvidenceItem]:
        items: list[StaticEvidenceItem] = []
        if not self.static_analysis:
            return items

        s_count = 0
        # Process AST conditions
        for cond in self.static_analysis.conditions:
            s_count += 1
            loc_str = f"{cond.location.file}:{cond.location.line}" if cond.location else ""
            item = StaticEvidenceItem(
                evidence_id=f"EV-S-{s_count:03d}",
                type="STATIC_CONDITION",
                file=cond.location.file if cond.location else self.static_analysis.file,
                line=cond.location.line if cond.location else 0,
                column=cond.location.column if cond.location else None,
                function=cond.location.function if cond.location else None,
                condition=cond.expression,
                strength=0.7,
                source_location_id=loc_str,
            )
            items.append(item)

        # Process AST comparisons
        for comp in self.static_analysis.comparisons:
            s_count += 1
            loc_str = f"{comp.location.file}:{comp.location.line}" if comp.location else ""
            comp_expr = f"{comp.left} {comp.operator} {comp.right}"
            item = StaticEvidenceItem(
                evidence_id=f"EV-S-{s_count:03d}",
                type="STATIC_COMPARISON",
                file=comp.location.file if comp.location else self.static_analysis.file,
                line=comp.location.line if comp.location else 0,
                column=comp.location.column if comp.location else None,
                function=comp.location.function if comp.location else None,
                condition=comp_expr,
                operator=comp.operator,
                left=comp.left,
                right=comp.right,
                strength=0.7,
                source_location_id=loc_str,
            )
            items.append(item)

        return items

    def _build_dynamic_items(self) -> list[DynamicEvidenceItem]:
        items: list[DynamicEvidenceItem] = []
        d_count = 0

        for trace in self.runtime_traces:
            d_count += 1
            exec_id = trace.execution_id or f"EX-{d_count:03d}"
            ts = trace.timestamp or datetime.now(timezone.utc).isoformat()

            # Flatten executed branch entries into a single dictionary
            branch_res: dict[str, bool] = {}
            for eb in trace.executed_branches:
                for k, v in eb.items():
                    if k != "line" and isinstance(v, bool):
                        branch_res[k] = v

            # Extract latest variable snapshot
            latest_vars: dict = {}
            if trace.variable_states:
                latest_vars = trace.variable_states[-1].get("variables", {})

            item = DynamicEvidenceItem(
                evidence_id=f"EV-D-{d_count:03d}",
                type="RUNTIME_OBSERVATION",
                execution_id=exec_id,
                timestamp=ts,
                function=trace.function,
                inputs=trace.inputs,
                output=trace.output,
                branch_results=branch_res,
                variable_snapshot=latest_vars,
            )
            items.append(item)

        return items

    def _build_correlated_evidence(
        self, static_items: list[StaticEvidenceItem], dynamic_items: list[DynamicEvidenceItem]
    ) -> list[CorrelatedConditionEvidence]:
        correlated_list: list[CorrelatedConditionEvidence] = []
        seen_conditions: dict[str, Optional[StaticEvidenceItem]] = {}

        for s_item in static_items:
            if s_item.condition and s_item.condition not in seen_conditions:
                seen_conditions[s_item.condition] = s_item

        # Also incorporate any branch condition keys discovered during runtime execution
        for d_item in dynamic_items:
            for b_cond in d_item.branch_results.keys():
                if b_cond not in seen_conditions:
                    seen_conditions[b_cond] = None

        for cond_expr, s_item in seen_conditions.items():
            matching_dynamic: list[DynamicEvidenceItem] = []
            exec_ids: list[str] = []
            unique_inputs_set: set[str] = set()
            outcomes: dict[str, int] = {}
            boundary_cases = 0

            # Generic literal extraction for domain-agnostic boundary proximity analysis
            literals = [float(x) for x in re.findall(r"-?\b\d+(?:\.\d+)?\b", cond_expr)]

            for d_item in dynamic_items:
                # Check if condition holds for this runtime input
                holds = False
                try:
                    holds = eval_condition(cond_expr, d_item.inputs)
                except Exception:
                    # If inputs don't have variables for cond_expr, check recorded branch_results
                    holds = d_item.branch_results.get(cond_expr, False)

                if holds:
                    matching_dynamic.append(d_item)
                    exec_ids.append(d_item.execution_id)
                    inp_key = json.dumps(d_item.inputs, sort_keys=True)
                    unique_inputs_set.add(inp_key)

                    # Tally observed outcome generically
                    raw_out = d_item.output
                    decision_val = None
                    if isinstance(raw_out, dict):
                        if "decision" in raw_out:
                            decision_val = str(raw_out["decision"]).upper()
                        elif "result" in raw_out:
                            decision_val = str(raw_out["result"]).upper()
                        elif len(raw_out) == 1:
                            decision_val = str(next(iter(raw_out.values()))).upper()
                        else:
                            decision_val = json.dumps(raw_out)
                    elif raw_out is not None:
                        decision_val = str(raw_out).upper()

                    if decision_val:
                        outcomes[decision_val] = outcomes.get(decision_val, 0) + 1

                    # Domain-agnostic boundary proximity check
                    if literals and isinstance(d_item.inputs, dict):
                        is_boundary = False
                        for val in d_item.inputs.values():
                            if isinstance(val, (int, float)):
                                for lit in literals:
                                    tolerance = max(abs(lit) * 0.05, 5.0) if lit != 0 else 1.0
                                    if abs(val - lit) <= tolerance:
                                        is_boundary = True
                                        break
                            if is_boundary:
                                break
                        if is_boundary:
                            boundary_cases += 1

            source_locs = [s_item.source_location_id] if s_item and s_item.source_location_id else []

            correlated = CorrelatedConditionEvidence(
                condition_expr=cond_expr,
                static_item=s_item,
                dynamic_items=matching_dynamic,
                static_support=s_item is not None,
                runtime_observations=len(matching_dynamic),
                unique_inputs=len(unique_inputs_set),
                boundary_cases=boundary_cases,
                contradictions=0,
                source_locations=source_locs,
                execution_ids=exec_ids,
                observed_outcomes=outcomes,
            )
            correlated_list.append(correlated)

        return correlated_list


def build_evidence_package(
    static_analysis: Optional[StaticAnalysisResult] = None,
    runtime_traces: Optional[list[TraceEvent]] = None,
    project_id: str = "beacon-project",
) -> UnifiedEvidencePackage:
    """Helper function to build a UnifiedEvidencePackage."""
    builder = EvidencePackageBuilder(static_analysis, runtime_traces)
    return builder.build_package(project_id=project_id)
