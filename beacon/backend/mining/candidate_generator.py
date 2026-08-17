"""Stage 2a — Candidate invariant generation (LLM Miner).

Feeds structured UnifiedEvidencePackage representations (including correlated condition evidence,
static AST facts, and observed runtime outcomes) to Claude and asks it to
propose candidate business-rule invariants.
"""

import json
import uuid
from anthropic import Anthropic
from common.config import settings
from common.models import CandidateInvariant
from evidence.models import UnifiedEvidencePackage
from .base_generator import CandidateGenerator

_client = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


PROMPT_TEMPLATE = """You are analyzing a legacy system to discover invariant business rules from static AST and dynamic runtime evidence.
The input is a structured UnifiedEvidencePackage containing correlated conditions, static facts, and dynamic observations.

Evidence Package Summary:
{evidence_summary}

Propose candidate business-rule hypotheses explaining the observed legacy system behavior.
Each candidate MUST be grounded in the provided static and dynamic evidence items.
Downstream pipeline stages will independently subject every candidate to adversarial property validation and confidence scoring.

Respond with ONLY a valid JSON array of objects, no other text:
[
  {{
    "condition": "<boolean expression over input fields>",
    "consequence": "<expected output decision/value when condition holds>",
    "severity": "critical|high|medium|low",
    "rationale": "<grounded explanation referencing static and dynamic evidence>",
    "supporting_evidence_ids": ["EV-S-001", "EV-D-002"],
    "source_lines": [12]
  }}
]
"""


class LLMCandidateGenerator(CandidateGenerator):
    """LLM-based candidate generator consuming the UnifiedEvidencePackage."""

    def propose_candidates(self, evidence_package: UnifiedEvidencePackage) -> list[CandidateInvariant]:
        # Build comprehensive structured summary from UnifiedEvidencePackage
        summary = {
            "source_file": evidence_package.source_file,
            "language": evidence_package.language,
            "correlated_evidence": [
                {
                    "condition": c.condition_expr,
                    "static_support": c.static_support,
                    "source_locations": c.source_locations,
                    "static_evidence_id": c.static_item.evidence_id if c.static_item else None,
                    "runtime_observations": c.runtime_observations,
                    "unique_inputs": c.unique_inputs,
                    "boundary_cases": c.boundary_cases,
                    "observed_outcomes": c.observed_outcomes,
                    "sample_execution_ids": c.execution_ids[:10],
                }
                for c in evidence_package.correlated_conditions
            ],
            "static_conditions": [
                {
                    "evidence_id": s.evidence_id,
                    "condition": s.condition,
                    "line": s.line,
                    "function": s.function,
                }
                for s in evidence_package.static_evidence_items
                if s.type == "STATIC_CONDITION"
            ][:20],
            "sample_dynamic_traces": [
                {
                    "evidence_id": d.evidence_id,
                    "execution_id": d.execution_id,
                    "inputs": d.inputs,
                    "output": d.output,
                }
                for d in evidence_package.dynamic_evidence_items[:25]
            ],
        }

        prompt = PROMPT_TEMPLATE.format(evidence_summary=json.dumps(summary, indent=2))
        
        try:
            response = _get_client().messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = json.loads(text)
        except Exception:
            parsed = []

        candidates: list[CandidateInvariant] = []
        for c in parsed:
            inv_id = "llm-" + uuid.uuid4().hex[:8]
            ev_ids = c.get("supporting_evidence_ids", [])
            lines = c.get("source_lines", [])

            # Extract execution IDs if any matching dynamic evidence was correlated
            exec_ids: list[str] = []
            for corr in evidence_package.correlated_conditions:
                if corr.condition_expr == c.get("condition"):
                    exec_ids.extend(corr.execution_ids[:20])

            candidates.append(CandidateInvariant(
                invariant_id=inv_id,
                condition=c.get("condition", ""),
                consequence=c.get("consequence", ""),
                source_file=evidence_package.source_file,
                source_lines=lines,
                severity=c.get("severity", "medium"),
                evidence_ids=ev_ids,
                execution_ids=exec_ids,
                generation_method="llm",
                timestamp=evidence_package.timestamp,
                rationale=c.get("rationale"),
            ))

        return candidates
