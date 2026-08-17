"""Stage 2b — Evidence collection.

Consumes the UnifiedEvidencePackage directly to measure dynamic corroboration,
input diversity, and provenance linkage for candidate invariants without
independently reconstructing evidence from raw trace logs.
"""

import json
import math
from typing import Optional, Union

from common.dsl_eval import eval_condition
from common.models import CandidateInvariant, EvidenceReport, TraceEvent
from evidence.models import UnifiedEvidencePackage


def _condition_holds(condition_expr: str, inputs: dict) -> bool:
    try:
        return eval_condition(condition_expr, inputs)
    except Exception:
        return False


def _output_matches(consequence: str, output: dict) -> bool:
    if isinstance(output, dict):
        if "decision" in output:
            return str(output["decision"]).upper() == consequence.upper()
        if "result" in output:
            return str(output["result"]).upper() == consequence.upper()
        if len(output) == 1:
            return str(next(iter(output.values()))).upper() == consequence.upper()
    return str(output).upper() == consequence.upper()


def _diversity(corroborating_inputs: list[dict]) -> float:
    """Normalized spread of numeric input fields across corroborating traces.
    Combines input count diversity and coefficient of variation clamped to [0, 1].
    """
    if len(corroborating_inputs) < 2:
        return 0.0

    # Calculate unique input ratio
    unique_count = len({json.dumps(inp, sort_keys=True) for inp in corroborating_inputs})
    unique_ratio = min(unique_count / 15.0, 1.0)

    numeric_fields = [
        k for k, v in corroborating_inputs[0].items() if isinstance(v, (int, float))
    ]
    if not numeric_fields:
        return unique_ratio

    scores = []
    for field in numeric_fields:
        values = [t[field] for t in corroborating_inputs if field in t and isinstance(t[field], (int, float))]
        if len(values) < 2:
            continue
        mean = sum(values) / len(values)
        if mean == 0:
            continue
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = math.sqrt(variance)
        cv = std / abs(mean)
        scores.append(min(cv, 1.0))

    spread_score = sum(scores) / len(scores) if scores else 0.0
    return round(0.5 * unique_ratio + 0.5 * spread_score, 4)


def collect_evidence(
    candidate: CandidateInvariant,
    evidence_package: Union[UnifiedEvidencePackage, list[TraceEvent]],
    corpus_size: Optional[int] = None,
) -> EvidenceReport:
    """Collects evidence metrics and provenance IDs for candidate from UnifiedEvidencePackage."""
    
    if isinstance(evidence_package, UnifiedEvidencePackage):
        total_traces = len(evidence_package.dynamic_evidence_items)
        target_corr = None
        for corr in evidence_package.correlated_conditions:
            if corr.condition_expr == candidate.condition:
                target_corr = corr
                break

        if target_corr:
            matching_dynamic = target_corr.dynamic_items
            evidence_count = target_corr.runtime_observations
            static_ids = [target_corr.static_item.evidence_id] if target_corr.static_item else []
            dyn_ids = [d.evidence_id for d in matching_dynamic]
            exec_ids = list(target_corr.execution_ids)
            inputs_list = [d.inputs for d in matching_dynamic]
        else:
            # Evaluate directly over dynamic evidence items in package
            matching_dynamic = [
                d for d in evidence_package.dynamic_evidence_items
                if _condition_holds(candidate.condition, d.inputs) and _output_matches(candidate.consequence, d.output)
            ]
            evidence_count = len(matching_dynamic)
            static_ids = [s.evidence_id for s in evidence_package.static_evidence_items if s.condition == candidate.condition]
            dyn_ids = [d.evidence_id for d in matching_dynamic]
            exec_ids = [d.execution_id for d in matching_dynamic]
            inputs_list = [d.inputs for d in matching_dynamic]

        # Populate provenance on candidate
        if static_ids or dyn_ids:
            all_ids = list(dict.fromkeys(candidate.evidence_ids + static_ids + dyn_ids[:30]))
            candidate.evidence_ids = all_ids
        if exec_ids:
            candidate.execution_ids = list(dict.fromkeys(candidate.execution_ids + exec_ids[:30]))
        if evidence_package.source_file and not candidate.source_file:
            candidate.source_file = evidence_package.source_file

        norm_base = 50.0  # 50 corroborating executions indicates robust empirical support
        evidence_count_norm = min(evidence_count / norm_base, 1.0)
        input_div = _diversity(inputs_list)

        return EvidenceReport(
            invariant_id=candidate.invariant_id,
            evidence_count=evidence_count,
            evidence_count_norm=round(evidence_count_norm, 4),
            input_diversity=input_div,
            matching_execution_ids=exec_ids[:30],
            static_evidence_ids=static_ids,
            dynamic_evidence_ids=dyn_ids[:30],
        )

    else:
        # Fallback for list[TraceEvent]
        traces = evidence_package
        c_size = corpus_size or len(traces)
        corroborating = [
            t for t in traces
            if _condition_holds(candidate.condition, t.inputs) and _output_matches(candidate.consequence, t.output)
        ]
        count = len(corroborating)
        norm_base = 50.0
        return EvidenceReport(
            invariant_id=candidate.invariant_id,
            evidence_count=count,
            evidence_count_norm=round(min(count / norm_base, 1.0), 4),
            input_diversity=_diversity([t.inputs for t in corroborating]),
        )
