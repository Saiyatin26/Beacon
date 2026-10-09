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
        self._explicit_api_key = api_key
        self.model = model or settings.openrouter_model or "anthropic/claude-3.5-sonnet"
        self.base_url = (base_url or settings.openrouter_base_url or "https://openrouter.ai/api/v1").rstrip("/")
        self.timeout = timeout

    @property
    def api_key(self) -> str:
        if self._explicit_api_key is not None:
            return self._explicit_api_key.strip()
        return (settings.openrouter_api_key or "").strip()

    @api_key.setter
    def api_key(self, val: Optional[str]) -> None:
        self._explicit_api_key = val

    def is_available(self) -> bool:
        """Returns whether this provider can be attempted by the fallback chain."""
        return self.is_configured()

    def is_configured(self) -> bool:
        """Returns True when a non-empty API key is present."""
        return bool(self.api_key)

    def check_connectivity(self) -> bool:
        """Checks OpenRouter reachability and API key authorization without exposing credentials."""
        if not self.is_configured():
            return False

        request = urllib.request.Request(
            f"{self.base_url}/auth/key",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://github.com/Saiyatin26/Beacon",
                "X-Title": "BEACON Invariant Miner",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout, 5.0)) as response:
                if response.status == 200:
                    logger.info("OpenRouter authentication and connectivity check succeeded.")
                    return True
                return False
        except urllib.error.HTTPError as exc:
            logger.warning(f"OpenRouter connectivity check rejected with HTTP {exc.code} ({exc.reason}).")
            return False
        except Exception as exc:
            logger.warning(f"OpenRouter connectivity check failed: {exc}")
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
        requested_model = self.model
        actual_model = requested_model
        fallback_reason: Optional[str] = None
        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(endpoint, data=req_data, headers=headers, method="POST")

            def _fetch():
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    resp_bytes = resp.read()
                    return json.loads(resp_bytes.decode("utf-8"))

            from operations.resilience import execute_with_retry
            try:
                resp_json = execute_with_retry(
                    _fetch,
                    max_attempts=getattr(settings, "max_retry_attempts", 3),
                    base_delay_ms=getattr(settings, "retry_backoff_base_ms", 100.0),
                    operation_name=f"openrouter_chat_completion:{requested_model}",
                )
            except urllib.error.HTTPError as exc:
                fallback_model = (settings.openrouter_fallback_model or "").strip()
                if exc.code not in (402, 404) or not fallback_model or fallback_model == requested_model:
                    raise
                fallback_reason = (
                    f"Configured OpenRouter model '{requested_model}' returned HTTP {exc.code}; "
                    f"retried with configured fallback model '{fallback_model}'."
                )
                logger.warning(fallback_reason)
                actual_model = fallback_model
                payload["model"] = fallback_model
                req_data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(endpoint, data=req_data, headers=headers, method="POST")

                def _fetch_fallback():
                    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                        resp_bytes = resp.read()
                        return json.loads(resp_bytes.decode("utf-8"))

                resp_json = execute_with_retry(
                    _fetch_fallback,
                    max_attempts=getattr(settings, "max_retry_attempts", 3),
                    base_delay_ms=getattr(settings, "retry_backoff_base_ms", 100.0),
                    operation_name=f"openrouter_chat_completion:{fallback_model}",
                )

            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)


            choices = resp_json.get("choices", [])
            if not choices:
                return LLMResponse(
                    raw_text="",
                    provider_name=self.name,
                    model_name=actual_model,
                    requested_provider=self.name,
                    latency_ms=latency_ms,
                    fallback_occurred=fallback_reason is not None,
                    fallback_chain=[requested_model, actual_model] if fallback_reason else [actual_model],
                    fallback_reason=fallback_reason,
                    success=False,
                    error="OpenRouter response contained no choices.",
                    metadata={
                        "configured_model": requested_model,
                        "actual_model": actual_model,
                        "model_fallback_used": fallback_reason is not None,
                    },
                )

            raw_text = choices[0].get("message", {}).get("content", "")
            parsed_json = extract_json_payload(raw_text) if json_mode else None
            response_model = resp_json.get("model", actual_model)

            return LLMResponse(
                raw_text=raw_text,
                parsed_json=parsed_json,
                provider_name=self.name,
                model_name=response_model,
                requested_provider=self.name,
                latency_ms=latency_ms,
                fallback_occurred=fallback_reason is not None,
                fallback_chain=[requested_model, actual_model] if fallback_reason else [actual_model],
                fallback_reason=fallback_reason,
                success=True,
                metadata={
                    "usage": resp_json.get("usage", {}),
                    "model_id": response_model,
                    "configured_model": requested_model,
                    "actual_model": response_model,
                    "model_fallback_used": fallback_reason is not None,
                },
            )

        except urllib.error.HTTPError as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            err_msg = f"OpenRouter HTTP request failed with status {exc.code}: {exc.reason}."
            logger.error(err_msg)
            return LLMResponse(
                raw_text="",
                provider_name=self.name,
                model_name=actual_model,
                requested_provider=self.name,
                latency_ms=latency_ms,
                fallback_occurred=fallback_reason is not None,
                fallback_chain=[requested_model, actual_model] if fallback_reason else [actual_model],
                fallback_reason=fallback_reason,
                success=False,
                error=err_msg,
                metadata={
                    "configured_model": requested_model,
                    "actual_model": actual_model,
                    "model_fallback_used": fallback_reason is not None,
                },
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            err_msg = f"OpenRouter request failed: {exc}"
            logger.exception("OpenRouter request failed.")
            return LLMResponse(
                raw_text="",
                provider_name=self.name,
                model_name=actual_model,
                requested_provider=self.name,
                latency_ms=latency_ms,
                fallback_occurred=fallback_reason is not None,
                fallback_chain=[requested_model, actual_model] if fallback_reason else [actual_model],
                fallback_reason=fallback_reason,
                success=False,
                error=err_msg,
                metadata={
                    "configured_model": requested_model,
                    "actual_model": actual_model,
                    "model_fallback_used": fallback_reason is not None,
                },
            )
