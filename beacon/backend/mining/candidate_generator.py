"""Stage 2a — Decoupled AI-Assisted Candidate Invariant Generator (Phase 6 & Infrastructure).

Full Pipeline:
UnifiedEvidencePackage
      ↓
Evidence Relevance Selection (evidence_selector)
      ↓
LLM Context / Prompt Construction (prompt_builder)
      ↓
ProviderManager Execution (OpenRouter -> Anthropic -> Ollama -> Offline)
      ↓
Structured JSON Candidate Parsing
      ↓
Candidate Normalization (normalizer)
      ↓
Normalization-Aware Provenance Matching & Deduplication
      ↓
Semantic Evidence Grounding Check (grounding_checker)
      ↓
Provenance & Reproducibility Attachment
      ↓
Returns CandidateInvariant list for Existing Validation Pipeline.
"""

import json
import logging
import uuid
from typing import Optional

from common.models import CandidateInvariant
from evidence.models import UnifiedEvidencePackage
from llm.base import LLMResponse
from llm.manager import get_provider_manager
from .base_generator import CandidateGenerator
from .evidence_selector import select_relevant_evidence
from .grounding_checker import filter_grounded_candidates
from .normalizer import normalize_candidate, normalize_condition
from .prompt_builder import PROMPT_VERSION, build_mining_prompt

logger = logging.getLogger(__name__)


def deduplicate_candidates(candidates: list[CandidateInvariant]) -> list[CandidateInvariant]:
    """Deduplicates candidates sharing the same canonical (condition, consequence) pair,
    merging evidence IDs, execution IDs, and source lines without assigning artificial confidence.
    """
    dedup_map: dict[tuple[str, str], CandidateInvariant] = {}

    for cand in candidates:
        key = (cand.condition, cand.consequence)
        if key not in dedup_map:
            dedup_map[key] = cand
        else:
            existing = dedup_map[key]
            # Merge evidence IDs, execution IDs, and source lines
            merged_ev = list(dict.fromkeys(existing.evidence_ids + cand.evidence_ids))
            merged_ex = list(dict.fromkeys(existing.execution_ids + cand.execution_ids))
            merged_lines = sorted(list(set(existing.source_lines + cand.source_lines)))
            existing.evidence_ids = merged_ev
            existing.execution_ids = merged_ex
            existing.source_lines = merged_lines

    return list(dedup_map.values())


class LLMCandidateGenerator(CandidateGenerator):
    """Provider-decoupled AI-Assisted Candidate Invariant Generator."""

    def __init__(
        self,
        provider_name: Optional[str] = None,
        prompt_version: str = PROMPT_VERSION,
    ):
        self.provider_name = provider_name
        self.prompt_version = prompt_version
        self.manager = get_provider_manager()

    def propose_candidates(self, evidence_package: UnifiedEvidencePackage) -> list[CandidateInvariant]:
        """Orchestrates evidence selection, prompt generation, provider execution, normalization,
        normalization-aware provenance matching, deduplication, grounding checks, and provenance attachment.
        """
        # 1. Evidence Relevance Selection
        selected_context = select_relevant_evidence(evidence_package)

        # 2. Structured Prompt Construction
        prompt = build_mining_prompt(selected_context)

        # 3. Provider Execution through Decoupled ProviderManager
        llm_resp: LLMResponse = self.manager.generate(
            prompt=prompt,
            json_mode=True,
            preferred_provider=self.provider_name,
        )

        if not llm_resp.success or not llm_resp.parsed_json:
            logger.warning(f"LLM Candidate Generation failed or returned empty: {llm_resp.error}")
            return []

        raw_candidates_data = llm_resp.parsed_json
        if isinstance(raw_candidates_data, dict):
            raw_candidates_data = [raw_candidates_data]

        # 4. Parse candidates into initial CandidateInvariant objects
        unnormalized_candidates: list[CandidateInvariant] = []
        for c in raw_candidates_data:
            if not isinstance(c, dict):
                continue
            raw_cond = str(c.get("condition", "")).strip()
            consequence = str(c.get("consequence", "")).strip().upper()
            if not raw_cond or not consequence:
                continue

            inv_id = f"{llm_resp.provider_name}-" + uuid.uuid4().hex[:8]
            supporting_ev = c.get("supporting_evidence_ids", [])
            lines = c.get("source_lines", [])

            # Normalization-aware recovery of execution IDs & correlated evidence
            norm_cond = normalize_condition(raw_cond)
            exec_ids: list[str] = []
            ev_ids: list[str] = list(supporting_ev) if isinstance(supporting_ev, list) else []

            for corr in evidence_package.correlated_conditions:
                if normalize_condition(corr.condition_expr) == norm_cond:
                    exec_ids.extend(corr.execution_ids[:20])
                    for d in corr.dynamic_items:
                        ev_ids.append(d.evidence_id)

            for s in evidence_package.static_evidence_items:
                if s.condition and normalize_condition(s.condition) == norm_cond:
                    ev_ids.append(s.evidence_id)
                    s_line = getattr(s, "line", None) or getattr(s, "source_line", None)
                    if s_line and isinstance(lines, list) and s_line not in lines:
                        lines.append(s_line)

            gen_method = "offline" if llm_resp.provider_name == "offline" else "llm"

            reproducibility = {
                "provider": llm_resp.provider_name,
                "actual_provider": llm_resp.provider_name,
                "model": llm_resp.model_name,
                "actual_model": llm_resp.model_name,
                "requested_provider": getattr(llm_resp, "requested_provider", self.provider_name or "auto"),
                "prompt_version": self.prompt_version,
                "package_id": evidence_package.package_id,
                "generator_type": gen_method,
                "latency_ms": llm_resp.latency_ms,
                "fallback_occurred": llm_resp.fallback_occurred,
                "fallback_chain": llm_resp.fallback_chain,
                "fallback_reason": getattr(llm_resp, "fallback_reason", None),
            }

            confidence_components = {
                "provider": llm_resp.provider_name,
                "actual_provider": llm_resp.provider_name,
                "model": llm_resp.model_name,
                "actual_model": llm_resp.model_name,
                "requested_provider": getattr(llm_resp, "requested_provider", self.provider_name or "auto"),
                "prompt_version": self.prompt_version,
            }

            unnormalized_candidates.append(CandidateInvariant(
                invariant_id=inv_id,
                condition=raw_cond,
                raw_condition=raw_cond,
                consequence=consequence,
                source_file=evidence_package.source_file,
                source_lines=lines if isinstance(lines, list) else [],
                severity=c.get("severity", "medium"),
                evidence_ids=list(dict.fromkeys(ev_ids)),
                execution_ids=list(dict.fromkeys(exec_ids)),
                generation_method=gen_method,
                timestamp=evidence_package.timestamp,
                rationale=c.get("rationale"),
                confidence_components=confidence_components,
                reproducibility=reproducibility,
            ))

        # 5. Candidate Normalization (commutative AST sorting)
        normalized_candidates = [normalize_candidate(cand) for cand in unnormalized_candidates]

        # 6. Candidate Deduplication & Provenance Merging
        deduped_candidates = deduplicate_candidates(normalized_candidates)

        # 7. Semantic Evidence Grounding Check (Rejects Hallucinations & Mismatches)
        grounded_candidates, rejected_candidates = filter_grounded_candidates(
            deduped_candidates, evidence_package
        )

        for rej in rejected_candidates:
            logger.warning(f"Candidate rejected by grounding checker: {rej.condition} -> {rej.rationale}")

        return grounded_candidates
