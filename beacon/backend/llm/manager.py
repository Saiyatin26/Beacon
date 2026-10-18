"""Provider Manager and Factory Layer for BEACON's Decoupled LLM Architecture."""

import logging
from typing import Any, Optional

from common.config import settings
from .anthropic_provider import AnthropicProvider
from .base import LLMProvider, LLMResponse
from .gemini_provider import GeminiProvider
from .offline_provider import OfflineProvider
from .ollama_provider import OllamaProvider
from .openrouter_provider import OpenRouterProvider

logger = logging.getLogger(__name__)


class ProviderManager:
    """Manages LLM providers with automatic fallback priority:
    OpenRouter (Primary) -> Gemini (Supported) -> Anthropic (Supported) -> Ollama (Local) -> Offline (Deterministic)
    """

    def __init__(self):
        self.providers: dict[str, LLMProvider] = {
            "openrouter": OpenRouterProvider(),
            "gemini": GeminiProvider(),
            "anthropic": AnthropicProvider(),
            "ollama": OllamaProvider(),
            "offline": OfflineProvider(),
        }
        self.fallback_priority = ["gemini", "openrouter", "anthropic", "ollama", "offline"]

    def get_provider(self, name: str) -> Optional[LLMProvider]:
        return self.providers.get(name.lower().strip())

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = True,
        preferred_provider: Optional[str] = None,
        allow_fallback: Optional[bool] = None,
    ) -> LLMResponse:
        mode = (preferred_provider or settings.llm_provider or "gemini").lower().strip()
        allow_fallback_effective = (
            allow_fallback
            if allow_fallback is not None
            else settings.allow_auto_fallback
        )

        # Strict single-provider policy when fallback is disabled
        if not allow_fallback_effective:
            target_provider_name = mode if mode in self.providers else "gemini"
            provider = self.providers.get(target_provider_name)
            if not provider:
                return LLMResponse(
                    raw_text="",
                    provider_name=target_provider_name,
                    model_name="unknown",
                    requested_provider=target_provider_name,
                    success=False,
                    error_category=f"{target_provider_name.upper()}_MODEL_UNAVAILABLE",
                    error=f"{target_provider_name.title()} provider is not registered in ProviderManager.",
                    metadata={"requested_provider": target_provider_name, "fallback_used": False},
                )

            if not provider.is_available():
                return LLMResponse(
                    raw_text="",
                    provider_name=provider.name,
                    model_name=provider.model,
                    requested_provider=target_provider_name,
                    success=False,
                    error_category=f"{target_provider_name.upper()}_API_KEY_MISSING",
                    error=f"{target_provider_name.title()} API key is not configured or missing.",
                    metadata={
                        "requested_provider": target_provider_name,
                        "actual_provider": provider.name,
                        "fallback_used": False,
                        "error_category": f"{target_provider_name.upper()}_API_KEY_MISSING",
                    },
                )

            resp = provider.generate(prompt, system=system, json_mode=json_mode)
            resp.requested_provider = target_provider_name

            # Strict provenance verification: reject if provider mismatch
            if resp.provider_name.lower().strip() != target_provider_name:
                return LLMResponse(
                    raw_text="",
                    provider_name=resp.provider_name,
                    model_name=resp.model_name,
                    requested_provider=target_provider_name,
                    success=False,
                    error_category=f"{target_provider_name.upper()}_INVALID_RESPONSE",
                    error=f"Provenance rejection: requested {target_provider_name} but response reported provider '{resp.provider_name}'.",
                    metadata={
                        "requested_provider": target_provider_name,
                        "actual_provider": resp.provider_name,
                        "fallback_used": False,
                        "error_category": f"{target_provider_name.upper()}_INVALID_RESPONSE",
                    },
                )

            resp.fallback_chain = [target_provider_name]
            resp.metadata["provider_config"] = f"{resp.provider_name}:{resp.model_name}"
            resp.metadata["requested_provider"] = target_provider_name
            resp.metadata["actual_provider"] = resp.provider_name
            resp.metadata["fallback_used"] = False
            return resp

        # Explicit non-OpenRouter single provider mode with fallback check
        if mode != "auto" and mode in self.providers:
            provider = self.providers[mode]
            if not provider.is_available() and not allow_fallback_effective:
                return LLMResponse(
                    raw_text="",
                    provider_name=provider.name,
                    model_name=provider.model,
                    requested_provider=mode,
                    success=False,
                    error=f"Explicitly requested provider '{mode}' is not configured or available.",
                    metadata={
                        "requested_provider": mode,
                        "actual_provider": provider.name,
                        "fallback_used": False,
                    },
                )

            resp = provider.generate(prompt, system=system, json_mode=json_mode)
            resp.requested_provider = mode
            if resp.success or not allow_fallback_effective:
                resp.fallback_chain = [mode]
                resp.metadata["provider_config"] = f"{resp.provider_name}:{resp.model_name}"
                resp.metadata["requested_provider"] = mode
                resp.metadata["actual_provider"] = resp.provider_name
                resp.metadata["fallback_used"] = resp.fallback_occurred
                return resp

            logger.warning(
                f"Explicit provider '{mode}' failed ({resp.error}). Falling back via auto chain."
            )

        # Auto Mode / Fallback Chain: OpenRouter -> Gemini -> Anthropic -> Ollama -> Offline
        fallback_chain: list[str] = []
        last_error: Optional[str] = None

        for p_name in self.fallback_priority:
            if mode != "auto" and p_name == mode:
                continue
            provider = self.providers[p_name]
            fallback_chain.append(p_name)

            if not provider.is_available():
                logger.info(f"LLM Provider '{p_name}' not configured/available. Checking next provider.")
                continue

            try:
                resp = provider.generate(prompt, system=system, json_mode=json_mode)
                resp.requested_provider = mode
                if resp.success and (resp.parsed_json is not None or not json_mode):
                    fallback_used = resp.fallback_occurred or (mode != "auto" and resp.provider_name.lower() != mode) or (mode == "auto" and len(fallback_chain) > 1)
                    resp.fallback_occurred = fallback_used
                    resp.fallback_chain = list(fallback_chain)
                    if resp.fallback_occurred and last_error:
                        resp.fallback_reason = last_error
                    resp.metadata["provider_config"] = f"{resp.provider_name}:{resp.model_name}"
                    resp.metadata["requested_provider"] = mode
                    resp.metadata["actual_provider"] = resp.provider_name
                    resp.metadata["fallback_used"] = resp.fallback_occurred
                    return resp
                else:
                    last_error = resp.error or "Invalid response / failed JSON parsing"
                    logger.warning(f"Provider '{p_name}' execution failed: {last_error}. Trying next fallback.")
            except Exception as exc:
                last_error = str(exc)
                logger.warning(f"Provider '{p_name}' raised exception: {exc}. Trying next fallback.")

        # Guaranteed fallback to Offline provider
        offline_provider = self.providers["offline"]
        offline_resp = offline_provider.generate(prompt, system=system, json_mode=json_mode)
        offline_resp.requested_provider = mode
        offline_resp.fallback_occurred = True
        offline_resp.fallback_chain = list(fallback_chain) if "offline" in fallback_chain else list(fallback_chain) + ["offline"]
        offline_resp.fallback_reason = last_error or "Configured model path unavailable"
        offline_resp.metadata["prior_error"] = last_error or "Configured model path unavailable"
        offline_resp.metadata["provider_config"] = f"{offline_resp.provider_name}:{offline_resp.model_name}"
        offline_resp.metadata["requested_provider"] = mode
        offline_resp.metadata["actual_provider"] = offline_resp.provider_name
        offline_resp.metadata["fallback_used"] = True
        return offline_resp

    def get_status(self) -> dict[str, Any]:
        """Returns sanitized status information for all providers."""
        status_info = {
            "configured_mode": settings.llm_provider,
            "allow_auto_fallback": settings.allow_auto_fallback,
            "providers": {
                "openrouter": {
                    "available": self.providers["openrouter"].check_connectivity(),
                    "model": settings.openrouter_model,
                    "configured": self.providers["openrouter"].is_configured(),
                    "role": "Fallback Cloud Provider" if settings.llm_provider == "gemini" else "Primary Cloud Provider",
                },
                "gemini": {
                    "available": self.providers["gemini"].check_connectivity(),
                    "model": settings.gemini_model,
                    "configured": self.providers["gemini"].is_configured(),
                    "role": "Primary Cloud Provider" if settings.llm_provider == "gemini" else "Supported Cloud Provider",
                },
                "anthropic": {
                    "available": self.providers["anthropic"].is_available(),
                    "model": settings.anthropic_model,
                    "configured": bool(settings.anthropic_api_key),
                    "role": "Supported Cloud Provider",
                },
                "ollama": {
                    "available": self.providers["ollama"].is_available(),
                    "model": settings.ollama_model,
                    "endpoint": settings.ollama_base_url,
                    "role": "Local Fallback Provider",
                },
                "offline": {
                    "available": True,
                    "model": "deterministic-rule-miner",
                    "role": "Deterministic Offline Fallback",
                },
            },
        }

        # Determine active provider
        active_provider = "offline"
        if settings.llm_provider in self.providers and settings.llm_provider != "auto":
            active_provider = settings.llm_provider
        else:
            for p in self.fallback_priority:
                if self.providers[p].is_available():
                    active_provider = p
                    break

        status_info["active_provider"] = active_provider
        return status_info


def get_provider_manager() -> ProviderManager:
    """Returns a ProviderManager instance."""
    return ProviderManager()
