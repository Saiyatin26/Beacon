"""OpenRouter LLM Provider — Primary Cloud Provider for BEACON."""

import json
import logging
import re
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
                requested_provider=self.name,
                success=False,
                error_category="OPENROUTER_API_KEY_MISSING",
                error="OpenRouter API key not configured or missing.",
                metadata={"error_category": "OPENROUTER_API_KEY_MISSING"},
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
            "max_tokens": getattr(settings, "openrouter_max_tokens", 1500),
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
                    error_category="OPENROUTER_INVALID_RESPONSE",
                    error="OpenRouter response contained no choices.",
                    metadata={
                        "configured_model": requested_model,
                        "actual_model": actual_model,
                        "model_fallback_used": fallback_reason is not None,
                        "error_category": "OPENROUTER_INVALID_RESPONSE",
                    },
                )

            msg = choices[0].get("message", {})
            raw_text = (msg.get("content") or msg.get("reasoning") or "").strip()
            parsed_json = extract_json_payload(raw_text) if json_mode else None
            response_model = resp_json.get("model", actual_model)

            if json_mode and parsed_json is None:
                return LLMResponse(
                    raw_text=raw_text,
                    parsed_json=None,
                    provider_name=self.name,
                    model_name=response_model,
                    requested_provider=self.name,
                    latency_ms=latency_ms,
                    fallback_occurred=fallback_reason is not None,
                    fallback_chain=[requested_model, actual_model] if fallback_reason else [actual_model],
                    fallback_reason=fallback_reason,
                    success=False,
                    error_category="OPENROUTER_INVALID_RESPONSE",
                    error="OpenRouter response could not be parsed as valid JSON.",
                    metadata={
                        "usage": resp_json.get("usage", {}),
                        "model_id": response_model,
                        "configured_model": requested_model,
                        "actual_model": response_model,
                        "model_fallback_used": fallback_reason is not None,
                        "error_category": "OPENROUTER_INVALID_RESPONSE",
                    },
                )

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
            server_detail = ""
            try:
                body = exc.read().decode("utf-8", errors="ignore")
                parsed_err = json.loads(body)
                if isinstance(parsed_err, dict) and "error" in parsed_err:
                    err_val = parsed_err["error"]
                    if isinstance(err_val, dict):
                        server_detail = str(err_val.get("message", "")).strip()
                    elif isinstance(err_val, str):
                        server_detail = err_val.strip()
            except Exception:
                pass

            if exc.code in (401, 403):
                err_cat = "OPENROUTER_AUTHENTICATION_FAILED"
            elif exc.code == 402:
                err_cat = "OPENROUTER_INSUFFICIENT_CREDITS"
                if "in-flight requests" in server_detail.lower():
                    logger.warning("OpenRouter 402 due to in-flight credit reservations; waiting 6s for requests to settle...")
                    time.sleep(6.0)
                    retry_req = urllib.request.Request(endpoint, data=req_data, headers=headers, method="POST")
                    try:
                        with urllib.request.urlopen(retry_req, timeout=self.timeout) as retry_resp:
                            retry_json = json.loads(retry_resp.read().decode("utf-8"))
                            r_choices = retry_json.get("choices", [])
                            if r_choices:
                                r_raw_text = (r_choices[0].get("message", {}).get("content") or "").strip()
                                r_parsed_json = extract_json_payload(r_raw_text) if json_mode else None
                                r_model = retry_json.get("model", actual_model)
                                return LLMResponse(
                                    raw_text=r_raw_text,
                                    parsed_json=r_parsed_json,
                                    provider_name=self.name,
                                    model_name=r_model,
                                    requested_provider=self.name,
                                    latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                                    fallback_occurred=True,
                                    fallback_reason="Retried after in-flight requests settled",
                                    success=True,
                                    metadata={
                                        "usage": retry_json.get("usage", {}),
                                        "model_id": r_model,
                                        "configured_model": requested_model,
                                        "actual_model": r_model,
                                    },
                                )
                    except Exception as retry_err:
                        logger.error(f"In-flight retry failed: {retry_err}")
                afford_m = re.search(r"can only afford (\d+)", server_detail)
                if afford_m:
                    affordable = int(afford_m.group(1))
                    curr_max = payload.get("max_tokens", 600)
                    if affordable >= 100:
                        retry_max = max(100, int(affordable * 0.75))
                        logger.warning(
                            f"OpenRouter 402: requested {curr_max} max_tokens, can only afford {affordable}. "
                            f"Auto-adjusting max_tokens to {retry_max} and retrying..."
                        )
                        payload["max_tokens"] = retry_max
                        req_data = json.dumps(payload).encode("utf-8")
                        retry_req = urllib.request.Request(endpoint, data=req_data, headers=headers, method="POST")
                        try:
                            with urllib.request.urlopen(retry_req, timeout=self.timeout) as retry_resp:
                                retry_json = json.loads(retry_resp.read().decode("utf-8"))
                                r_choices = retry_json.get("choices", [])
                                if r_choices:
                                    r_raw_text = (r_choices[0].get("message", {}).get("content") or "").strip()
                                    r_parsed_json = extract_json_payload(r_raw_text) if json_mode else None
                                    r_model = retry_json.get("model", actual_model)
                                    return LLMResponse(
                                        raw_text=r_raw_text,
                                        parsed_json=r_parsed_json,
                                        provider_name=self.name,
                                        model_name=r_model,
                                        requested_provider=self.name,
                                        latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                                        fallback_occurred=True,
                                        fallback_reason=f"Auto-reduced max_tokens to {retry_max} to match OpenRouter capacity",
                                        success=True,
                                        metadata={
                                            "usage": retry_json.get("usage", {}),
                                            "model_id": r_model,
                                            "configured_model": requested_model,
                                            "actual_model": r_model,
                                        },
                                    )
                        except Exception as retry_err:
                            logger.error(f"Auto-token reduction retry failed: {retry_err}")
            elif exc.code == 429:
                err_cat = "OPENROUTER_RATE_LIMITED"
            elif exc.code == 404:
                err_cat = "OPENROUTER_MODEL_UNAVAILABLE"
            else:
                err_cat = f"OPENROUTER_HTTP_{exc.code}"

            detail_suffix = f": {server_detail}" if server_detail else ""
            err_msg = f"OpenRouter HTTP request rejected: {err_cat} (status {exc.code}){detail_suffix}."
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
                error_category=err_cat,
                error=err_msg,
                metadata={
                    "configured_model": requested_model,
                    "actual_model": actual_model,
                    "model_fallback_used": fallback_reason is not None,
                    "http_status": exc.code,
                    "error_category": err_cat,
                },
            )
        except urllib.error.URLError as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            is_timeout = "timed out" in str(getattr(exc, "reason", "")).lower() or isinstance(getattr(exc, "reason", None), TimeoutError)
            err_cat = "OPENROUTER_REQUEST_TIMEOUT" if is_timeout else "OPENROUTER_NETWORK_ERROR"
            err_msg = f"OpenRouter network connection error: {err_cat}."
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
                error_category=err_cat,
                error=err_msg,
                metadata={
                    "configured_model": requested_model,
                    "actual_model": actual_model,
                    "model_fallback_used": fallback_reason is not None,
                    "error_category": err_cat,
                },
            )
        except (TimeoutError, Exception) as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            is_timeout = isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()
            err_cat = "OPENROUTER_REQUEST_TIMEOUT" if is_timeout else "OPENROUTER_NETWORK_ERROR"
            err_msg = f"OpenRouter request error: {err_cat} ({exc})."
            logger.error(err_msg, exc_info=True)
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
                error_category=err_cat,
                error=err_msg,
                metadata={
                    "configured_model": requested_model,
                    "actual_model": actual_model,
                    "model_fallback_used": fallback_reason is not None,
                    "error_category": err_cat,
                },
            )
