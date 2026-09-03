"""OpenRouter LLM Provider — Primary Cloud Provider for BEACON."""

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from common.config import settings
from .base import LLMProvider, LLMResponse, extract_json_payload

logger = logging.getLogger(__name__)


class OpenRouterProvider(LLMProvider):
    """OpenRouter Cloud Provider (Primary Cloud Provider)."""

    name: str = "openrouter"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.api_key = (api_key or settings.openrouter_api_key or "").strip()
        self.model = model or settings.openrouter_model or "anthropic/claude-3.5-sonnet"
        self.base_url = (base_url or settings.openrouter_base_url or "https://openrouter.ai/api/v1").rstrip("/")
        self.timeout = timeout

    def is_available(self) -> bool:
        """Returns whether this provider can be attempted by the fallback chain."""
        return self.is_configured()

    def is_configured(self) -> bool:
        """Returns True when a non-empty API key is present."""
        return bool(self.api_key)

    def check_connectivity(self) -> bool:
        """Checks OpenRouter reachability without exposing credentials or response data."""
        if not self.is_configured():
            return False

        request = urllib.request.Request(
            f"{self.base_url}/models",
            headers={"Authorization": f"Bearer {self.api_key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout, 5.0)) as response:
                response.read(1)
            logger.info("OpenRouter connectivity check succeeded")
            return True
        except Exception:
            logger.warning("OpenRouter connectivity check failed")
            return False

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = True,
    ) -> LLMResponse:
        if not self.is_available():
            return LLMResponse(
                raw_text="",
                provider_name=self.name,
                model_name=self.model,
                success=False,
                error="OpenRouter API key not configured.",
            )

        endpoint = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/Saiyatin26/Beacon",
            "X-Title": "BEACON Invariant Miner",
        }

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
        }

        start_time = time.perf_counter()
        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(endpoint, data=req_data, headers=headers, method="POST")

            def _fetch():
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    resp_bytes = resp.read()
                    return json.loads(resp_bytes.decode("utf-8"))

            from backend.operations.resilience import execute_with_retry
            resp_json = execute_with_retry(
                _fetch,
                max_attempts=getattr(settings, "max_retry_attempts", 3),
                base_delay_ms=getattr(settings, "retry_backoff_base_ms", 100.0),
                operation_name=f"openrouter_chat_completion:{self.model}",
            )

            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)


            choices = resp_json.get("choices", [])
            if not choices:
                return LLMResponse(
                    raw_text="",
                    provider_name=self.name,
                    model_name=self.model,
                    latency_ms=latency_ms,
                    success=False,
                    error="OpenRouter response contained no choices.",
                )

            raw_text = choices[0].get("message", {}).get("content", "")
            parsed_json = extract_json_payload(raw_text) if json_mode else None

            return LLMResponse(
                raw_text=raw_text,
                parsed_json=parsed_json,
                provider_name=self.name,
                model_name=self.model,
                latency_ms=latency_ms,
                success=True,
                metadata={
                    "usage": resp_json.get("usage", {}),
                    "model_id": resp_json.get("model", self.model),
                },
            )

        except urllib.error.HTTPError as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            err_msg = f"OpenRouter HTTP request failed with status {exc.code}."
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
            err_msg = "OpenRouter request failed."
            logger.error(err_msg)
            return LLMResponse(
                raw_text="",
                provider_name=self.name,
                model_name=self.model,
                latency_ms=latency_ms,
                success=False,
                error=err_msg,
            )
