"""Stage 2a — Candidate invariant generation (LLM Miner).

Feeds structured UnifiedEvidencePackage representations to Claude and asks it to
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


PROMPT_TEMPLATE = """You are analyzing a legacy system to find undocumented business rules.
The input is a structured UnifiedEvidencePackage containing both static facts and dynamic runtime traces.

Evidence Package Summary:
{evidence_summary}

Propose 1 to 5 candidate business-rule hypotheses that explain the observed patterns.
These are hypotheses that will be strictly validated downstream.

Respond with ONLY a JSON array of objects, no other text:
[
  {{
    "condition": "<readable boolean condition over input fields>",
    "consequence": "<the output field value the condition implies>",
    "severity": "critical|high|medium|low",
    "rationale": "<short explanation>",
    "supporting_evidence_ids": ["EV-S-xxx", "EV-D-yyy"],
    "source_lines": [line_numbers_if_any]
  }}
]
"""


class LLMCandidateGenerator(CandidateGenerator):
    def propose_candidates(self, evidence_package: UnifiedEvidencePackage) -> list[CandidateInvariant]:
        # Build a bounded summary of the evidence package
        summary = {
            "file": evidence_package.source_file,
            "static_conditions": [
                {"id": s.evidence_id, "cond": s.condition, "line": s.line}
                for s in evidence_package.static_evidence_items if s.type == "STATIC_CONDITION"
            ][:20],
            "dynamic_traces": [
                {"id": d.evidence_id, "inputs": d.inputs, "output": d.output}
                for d in evidence_package.dynamic_evidence_items
            ][:30],
        }

        prompt = PROMPT_TEMPLATE.format(evidence_summary=json.dumps(summary, indent=2))
        
        try:
            response = _get_client().messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = json.loads(text)
        except Exception:
            # Fallback or error handling if LLM fails or API key missing
            parsed = []

        candidates = []
        for c in parsed:
            candidates.append(CandidateInvariant(
                invariant_id=str(uuid.uuid4())[:8],
                condition=c.get("condition", ""),
                consequence=c.get("consequence", ""),
                severity=c.get("severity", "medium"),
                evidence_ids=c.get("supporting_evidence_ids", []),
                generation_method="llm",
                timestamp=evidence_package.timestamp,
                source_lines=c.get("source_lines", []),
                rationale=c.get("rationale")
            ))

        return candidates
