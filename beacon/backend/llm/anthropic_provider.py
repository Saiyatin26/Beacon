"""Anthropic LLM Provider — Supported Cloud Provider for BEACON."""

import logging
import time
from typing import Any, Optional

from anthropic import Anthropic, APIConnectionError, APIStatusError, RateLimitError
from common.config import settings
from .base import LLMProvider, LLMResponse, extract_json_payload

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic Cloud Provider (Supported Cloud Provider)."""

    name: str = "anthropic"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = (api_key or settings.anthropic_api_key or "").strip()
        self.model = model or settings.anthropic_model or "claude-sonnet-4-6"
        self._client: Optional[Anthropic] = None

    def _get_client(self) -> Anthropic:
        if self._client is None:
            self._client = Anthropic(api_key=self.api_key or "unconfigured")
        return self._client

    def is_available(self) -> bool:
        """Returns True if the Anthropic API key is configured."""
        return bool(self.api_key)

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
                error="Anthropic API key not configured.",
            )

        start_time = time.perf_counter()
        try:
            client = self._get_client()
            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                kwargs["system"] = system

            from backend.operations.resilience import execute_with_retry
            response = execute_with_retry(
                lambda: client.messages.create(**kwargs),
                max_attempts=getattr(settings, "max_retry_attempts", 3),
                base_delay_ms=getattr(settings, "retry_backoff_base_ms", 100.0),
                operation_name=f"anthropic_messages_create:{self.model}",
            )
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)


            raw_text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
            parsed_json = extract_json_payload(raw_text) if json_mode else None

            usage = {
                "input_tokens": getattr(response.usage, "input_tokens", None),
                "output_tokens": getattr(response.usage, "output_tokens", None),
            }

            return LLMResponse(
                raw_text=raw_text,
                parsed_json=parsed_json,
                provider_name=self.name,
                model_name=self.model,
                latency_ms=latency_ms,
                success=True,
                metadata={"usage": usage, "model_id": response.model},
            )

        except RateLimitError as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            err_msg = f"Anthropic RateLimitError: {exc}"
            logger.error(err_msg)
            return LLMResponse(
                raw_text="",
                provider_name=self.name,
                model_name=self.model,
                latency_ms=latency_ms,
                success=False,
                error=err_msg,
            )
        except APIConnectionError as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            err_msg = f"Anthropic Connection/Timeout Error: {exc}"
            logger.error(err_msg)
            return LLMResponse(
                raw_text="",
                provider_name=self.name,
                model_name=self.model,
                latency_ms=latency_ms,
                success=False,
                error=err_msg,
            )
        except APIStatusError as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            err_msg = f"Anthropic HTTP Status Error {exc.status_code}: {exc.message}"
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
            err_msg = f"Anthropic unexpected error: {exc}"
            logger.error(err_msg)
            return LLMResponse(
                raw_text="",
                provider_name=self.name,
                model_name=self.model,
                latency_ms=latency_ms,
                success=False,
                error=err_msg,
            )
