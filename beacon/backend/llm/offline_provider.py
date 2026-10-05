"""Deterministic Offline LLM Provider — Final Local Fallback for BEACON."""

import json
import logging
import re
import time
from typing import Any, Optional

from .base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class OfflineProvider(LLMProvider):
    """Deterministic Rule Synthesizer acting as an offline LLM provider."""

    name: str = "offline"
    model: str = "deterministic-rule-miner"

    def is_available(self) -> bool:
        """Offline provider is always available without network dependencies."""
        return True

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = True,
    ) -> LLMResponse:
        start_time = time.perf_counter()
        candidates: list[dict[str, Any]] = []

        # Extract correlated business rules from prompt text if present
        # Format in prompt: - Rule: <cond> -> <consequence> (Observations: ..., Evidence IDs: [...], Lines: [...])
        rule_pattern = re.compile(
            r"-\s*Rule:\s*(.+?)\s*->\s*([A-Z_]+)(?:.*?Evidence IDs:\s*(\[[^\]]*\]))?(?:.*?Lines:\s*(\[[^\]]*\]))?",
            re.MULTILINE | re.DOTALL,
        )

        matches = rule_pattern.findall(prompt)
        for cond_str, consequence, ev_ids_str, lines_str in matches:
            cond = cond_str.strip()
            conseq = consequence.strip()
            ev_ids = []
            lines = []

            if ev_ids_str:
                try:
                    ev_ids = json.loads(ev_ids_str)
                except Exception:
                    ev_ids = re.findall(r"EV-[A-Z]-\d+", ev_ids_str)

            if lines_str:
                try:
                    lines = json.loads(lines_str)
                except Exception:
                    lines = [int(x) for x in re.findall(r"\b\d+\b", lines_str)]

            candidates.append({
                "condition": cond,
                "consequence": conseq,
                "domain": "business_logic",
                "severity": "critical" if conseq in ("REJECT", "ERROR", "FAIL") else "medium",
                "rationale": "Deterministic extraction from structured evidence context.",
                "supporting_evidence_ids": ev_ids,
                "source_lines": lines,
            })

        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        raw_text = json.dumps(candidates, indent=2)

        return LLMResponse(
            raw_text=raw_text,
            parsed_json=candidates if json_mode else None,
            provider_name=self.name,
            model_name=self.model,
            latency_ms=latency_ms,
            success=True,
            metadata={"candidate_count": len(candidates)},
        )
