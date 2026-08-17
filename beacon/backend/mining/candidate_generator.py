"""Stage 2a — AI-Assisted Candidate Invariant Generator (Phase 6).

Full Phase-6 Pipeline:
UnifiedEvidencePackage
      ↓
Evidence Relevance Selection (evidence_selector)
      ↓
LLM Context / Prompt Construction (prompt_builder)
      ↓
Claude API Execution (with robust error handling)
      ↓
Structured JSON Candidate Parsing
      ↓
Candidate Normalization (normalizer)
      ↓
Candidate Deduplication & Provenance Merging
      ↓
Evidence Grounding Check (grounding_checker)
      ↓
Provenance Attachment
      ↓
Returns CandidateInvariant list for Existing Validation Pipeline.
"""

import json
import logging
import uuid
from typing import Optional

from anthropic import Anthropic, APIConnectionError, APIStatusError, RateLimitError
from common.config import settings
from common.models import CandidateInvariant
from evidence.models import UnifiedEvidencePackage
from .base_generator import CandidateGenerator
from .evidence_selector import select_relevant_evidence
from .grounding_checker import filter_grounded_candidates
from .normalizer import normalize_candidate
from .prompt_builder import PROMPT_VERSION, build_mining_prompt

logger = logging.getLogger(__name__)

_client: Optional[Anthropic] = None
DEFAULT_MODEL = "claude-sonnet-4-6"


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.anthropic_api_key or "mock-key")
    return _client


def deduplicate_candidates(candidates: list[CandidateInvariant]) -> list[CandidateInvariant]:
    """Deduplicates candidates sharing the same canonical (condition, consequence) pair,
    merging evidence IDs and execution IDs without assigning artificial confidence.
    """
    dedup_map: dict[tuple[str, str], CandidateInvariant] = {}

    for cand in candidates:
        key = (cand.condition, cand.consequence)
        if key not in dedup_map:
            dedup_map[key] = cand
        else:
            existing = dedup_map[key]
            # Merge evidence IDs and execution IDs
            merged_ev = list(dict.fromkeys(existing.evidence_ids + cand.evidence_ids))
            merged_ex = list(dict.fromkeys(existing.execution_ids + cand.execution_ids))
            merged_lines = sorted(list(set(existing.source_lines + cand.source_lines)))
            existing.evidence_ids = merged_ev
            existing.execution_ids = merged_ex
            existing.source_lines = merged_lines

    return list(dedup_map.values())


class LLMCandidateGenerator(CandidateGenerator):
    """Phase 6 AI-Assisted Candidate Invariant Generator."""

    def __init__(self, model_name: str = DEFAULT_MODEL, prompt_version: str = PROMPT_VERSION):
        self.model_name = model_name
        self.prompt_version = prompt_version

    def propose_candidates(self, evidence_package: UnifiedEvidencePackage) -> list[CandidateInvariant]:
        """Orchestrates evidence selection, prompt generation, LLM querying, normalization,
        deduplication, grounding checks, and provenance attachment.
        """
        # 1. Evidence Relevance Selection
        selected_context = select_relevant_evidence(evidence_package)

        # 2. Structured Prompt Construction
        prompt = build_mining_prompt(selected_context)

        # 3. LLM Execution with Graceful Failure Handling
        raw_candidates_data = self._call_llm_safe(prompt)
        if not raw_candidates_data:
            return []

        # 4. Parse candidates into initial CandidateInvariant objects
        unnormalized_candidates: list[CandidateInvariant] = []
        for c in raw_candidates_data:
            if not isinstance(c, dict):
                continue
            cond = str(c.get("condition", "")).strip()
            consequence = str(c.get("consequence", "")).strip().upper()
            if not cond or not consequence:
                continue

            inv_id = "llm-" + uuid.uuid4().hex[:8]
            supporting_ev = c.get("supporting_evidence_ids", [])
            lines = c.get("source_lines", [])

            # Extract execution IDs from correlated package evidence if present
            exec_ids: list[str] = []
            for corr in evidence_package.correlated_conditions:
                if corr.condition_expr == cond:
                    exec_ids.extend(corr.execution_ids[:20])

            unnormalized_candidates.append(CandidateInvariant(
                invariant_id=inv_id,
                condition=cond,
                consequence=consequence,
                source_file=evidence_package.source_file,
                source_lines=lines if isinstance(lines, list) else [],
                severity=c.get("severity", "medium"),
                evidence_ids=supporting_ev if isinstance(supporting_ev, list) else [],
                execution_ids=list(dict.fromkeys(exec_ids)),
                generation_method="llm",
                timestamp=evidence_package.timestamp,
                rationale=c.get("rationale"),
                confidence_components={
                    "model": self.model_name,
                    "prompt_version": self.prompt_version,
                },
            ))

        # 5. Candidate Normalization (commutative AST sorting)
        normalized_candidates = [normalize_candidate(cand) for cand in unnormalized_candidates]

        # 6. Candidate Deduplication & Provenance Merging
        deduped_candidates = deduplicate_candidates(normalized_candidates)

        # 7. Evidence Grounding Check (Rejects Hallucinations)
        grounded_candidates, rejected_candidates = filter_grounded_candidates(
            deduped_candidates, evidence_package
        )

        for rej in rejected_candidates:
            logger.warning(f"LLM candidate rejected by grounding checker: {rej.condition} -> {rej.rationale}")

        return grounded_candidates

    def _call_llm_safe(self, prompt: str) -> list[dict]:
        """Calls Claude with comprehensive error handling for API, rate limits, timeouts, and JSON parsing."""
        try:
            client = _get_client()
            response = client.messages.create(
                model=self.model_name,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            
            # Clean markdown JSON wrapping if present
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            elif isinstance(parsed, dict):
                return [parsed]
            return []
        except RateLimitError as exc:
            logger.error(f"Claude API Rate Limit reached: {exc}")
            return []
        except APIConnectionError as exc:
            logger.error(f"Claude API Connection error / timeout: {exc}")
            return []
        except APIStatusError as exc:
            logger.error(f"Claude API HTTP Error {exc.status_code}: {exc.message}")
            return []
        except json.JSONDecodeError as exc:
            logger.error(f"Failed to parse LLM response as JSON: {exc}")
            return []
        except Exception as exc:
            logger.error(f"Unexpected error during LLM candidate generation: {exc}")
            return []
