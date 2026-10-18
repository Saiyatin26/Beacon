"""Google Gemini LLM Provider — First-Class Cloud Provider for BEACON."""

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from common.config import settings
from .base import LLMProvider, LLMResponse, extract_json_payload

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """Google Gemini Cloud Provider implementation using direct HTTPS endpoints."""

    name: str = "gemini"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ):
        self._explicit_api_key = api_key
        self._explicit_model = model
        self.base_url = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.timeout = timeout

    @property
    def model(self) -> str:
        if self._explicit_model is not None:
            return self._explicit_model.strip()
        return (settings.gemini_model or "gemini-3.8-flash").strip()

    @model.setter
    def model(self, val: Optional[str]) -> None:
        self._explicit_model = val

    @property
    def api_key(self) -> str:
        if self._explicit_api_key is not None:
            return self._explicit_api_key.strip()
        return (settings.gemini_api_key or "").strip()

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
        """Checks Gemini reachability and API key authorization without exposing credentials."""
        if not self.is_configured():
            return False

        probe_url = f"{self.base_url}/models?key={self.api_key}"
        request = urllib.request.Request(
            probe_url,
            headers={"User-Agent": "BEACON-V2/1.0"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout, 5.0)) as response:
                if response.status == 200:
                    logger.info("Google Gemini authentication and connectivity check succeeded.")
                    return True
                return False
        except urllib.error.HTTPError as exc:
            logger.warning(f"Google Gemini connectivity check rejected with HTTP {exc.code} ({exc.reason}).")
            return False
        except Exception as exc:
            logger.warning(f"Google Gemini connectivity check failed: {exc}")
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
                error_category="GEMINI_API_KEY_MISSING",
                error="Google Gemini API key not configured or missing in .env (GEMINI_API_KEY).",
                metadata={"error_category": "GEMINI_API_KEY_MISSING"},
            )

        endpoint = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "BEACON-V2/1.0",
        }

        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
            },
        }

        if system:
            payload["systemInstruction"] = {
                "parts": [{"text": system}],
            }

        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        start_time = time.perf_counter()
        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(endpoint, data=req_data, headers=headers, method="POST")

            def _fetch():
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    resp_bytes = resp.read()
                    return json.loads(resp_bytes.decode("utf-8"))

            from operations.resilience import execute_with_retry

            resp_json = execute_with_retry(
                _fetch,
                max_attempts=getattr(settings, "max_retry_attempts", 3),
                base_delay_ms=getattr(settings, "retry_backoff_base_ms", 100.0),
                operation_name=f"gemini_generate_content:{self.model}",
            )

            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

            candidates = resp_json.get("candidates", [])
            if not candidates:
                return LLMResponse(
                    raw_text="",
                    provider_name=self.name,
                    model_name=self.model,
                    latency_ms=latency_ms,
                    success=False,
                    error="Google Gemini response contained no candidates.",
                )

            parts = candidates[0].get("content", {}).get("parts", [])
            raw_text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
            parsed_json = extract_json_payload(raw_text) if json_mode else None

            return LLMResponse(
                raw_text=raw_text,
                parsed_json=parsed_json,
                provider_name=self.name,
                model_name=self.model,
                latency_ms=latency_ms,
                success=True,
                metadata={
                    "usage": resp_json.get("usageMetadata", {}),
                    "model_id": self.model,
                    "finish_reason": candidates[0].get("finishReason"),
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

            if exc.code in (400, 401, 403):
                err_cat = "GEMINI_AUTHENTICATION_FAILED" if "key" in server_detail.lower() or "auth" in server_detail.lower() or "api_key" in server_detail.lower() else f"GEMINI_HTTP_{exc.code}"
            elif exc.code == 429:
                err_cat = "GEMINI_RATE_LIMITED"
            elif exc.code == 404:
                err_cat = "GEMINI_MODEL_UNAVAILABLE"
            else:
                err_cat = f"GEMINI_HTTP_{exc.code}"

            detail_suffix = f": {server_detail}" if server_detail else f": {exc.reason}"
            err_msg = f"Google Gemini HTTP request rejected ({err_cat}, status {exc.code}){detail_suffix}."
            logger.error(err_msg)
            return LLMResponse(
                raw_text="",
                provider_name=self.name,
                model_name=self.model,
                requested_provider=self.name,
                latency_ms=latency_ms,
                success=False,
                error_category=err_cat,
                error=err_msg,
                metadata={"error_category": err_cat, "http_status": exc.code},
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            err_cat = "GEMINI_NETWORK_ERROR"
            err_msg = f"Google Gemini request error: {str(exc)}"
            logger.error(err_msg)
            return LLMResponse(
                raw_text="",
                provider_name=self.name,
                model_name=self.model,
                requested_provider=self.name,
                latency_ms=latency_ms,
                success=False,
                error_category=err_cat,
                error=err_msg,
                metadata={"error_category": err_cat},
            )
