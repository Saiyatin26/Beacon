"""Ollama LLM Provider — Local Fallback Provider for BEACON (Qwen / Mistral)."""

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from common.config import settings
from .base import LLMProvider, LLMResponse, extract_json_payload

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """Local Ollama Provider (Qwen2.5-Coder / Mistral local model)."""

    name: str = "ollama"

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.base_url = (base_url or settings.ollama_base_url or "http://localhost:11434").rstrip("/")
        self.model = model or settings.ollama_model or "qwen2.5-coder:7b"
        self.timeout = timeout

    def is_available(self) -> bool:
        """Checks if local Ollama daemon is reachable."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                return resp.getcode() == 200
        except Exception:
            return False

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = True,
    ) -> LLMResponse:
        endpoint = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json" if json_mode else "",
        }
        if system:
            payload["system"] = system

        start_time = time.perf_counter()
        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_bytes = resp.read()
                resp_json = json.loads(resp_bytes.decode("utf-8"))

            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            raw_text = resp_json.get("response", "")
            parsed_json = extract_json_payload(raw_text) if json_mode else None

            return LLMResponse(
                raw_text=raw_text,
                parsed_json=parsed_json,
                provider_name=self.name,
                model_name=self.model,
                latency_ms=latency_ms,
                success=True,
                metadata={
                    "total_duration": resp_json.get("total_duration"),
                    "eval_count": resp_json.get("eval_count"),
                },
            )

        except urllib.error.URLError as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            err_msg = f"Ollama connection error: {exc.reason}"
            logger.error(err_msg)
            return LLMResponse(
                raw_text="",
                provider_name=self.name,
                model_name=self.model,
                latency_ms=latency_ms,
                success=False,
                error=err_msg,
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            err_msg = f"Ollama unexpected error: {exc}"
            logger.error(err_msg)
            return LLMResponse(
                raw_text="",
                provider_name=self.name,
                model_name=self.model,
                latency_ms=latency_ms,
                success=False,
                error=err_msg,
            )
