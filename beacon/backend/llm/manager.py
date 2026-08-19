"""Provider Manager and Factory Layer for BEACON's Decoupled LLM Architecture."""

import logging
from typing import Any, Optional

from common.config import settings
from .anthropic_provider import AnthropicProvider
from .base import LLMProvider, LLMResponse
from .offline_provider import OfflineProvider
from .ollama_provider import OllamaProvider
from .openrouter_provider import OpenRouterProvider

logger = logging.getLogger(__name__)


class ProviderManager:
    """Manages LLM providers with automatic fallback priority:
    OpenRouter (Primary) -> Anthropic (Supported) -> Ollama (Local) -> Offline (Deterministic)
    """

    def __init__(self):
        self.providers: dict[str, LLMProvider] = {
            "openrouter": OpenRouterProvider(),
            "anthropic": AnthropicProvider(),
            "ollama": OllamaProvider(),
            "offline": OfflineProvider(),
        }
        self.fallback_priority = ["openrouter", "anthropic", "ollama", "offline"]

    def get_provider(self, name: str) -> Optional[LLMProvider]:
        return self.providers.get(name.lower().strip())

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = True,
        preferred_provider: Optional[str] = None,
    ) -> LLMResponse:
        mode = (preferred_provider or settings.llm_provider or "auto").lower().strip()

        # Explicit single provider mode
        if mode != "auto" and mode in self.providers:
            provider = self.providers[mode]
            if not provider.is_available() and not settings.allow_auto_fallback:
                return LLMResponse(
                    raw_text="",
                    provider_name=provider.name,
                    model_name=provider.model,
                    success=False,
                    error=f"Explicitly requested provider '{mode}' is not configured or available.",
                )
            
            resp = provider.generate(prompt, system=system, json_mode=json_mode)
            if resp.success or not settings.allow_auto_fallback:
                return resp
            
            logger.warning(
                f"Explicit provider '{mode}' failed ({resp.error}). Falling back via auto chain."
            )

        # Auto Mode / Fallback Chain: OpenRouter -> Anthropic -> Ollama -> Offline
        fallback_chain: list[str] = []
        last_error: Optional[str] = None

        for p_name in self.fallback_priority:
            provider = self.providers[p_name]
            fallback_chain.append(p_name)

            if not provider.is_available():
                logger.info(f"LLM Provider '{p_name}' not configured/available. Checking next provider.")
                continue

            try:
                resp = provider.generate(prompt, system=system, json_mode=json_mode)
                if resp.success and resp.parsed_json is not None:
                    resp.fallback_occurred = len(fallback_chain) > 1
                    resp.fallback_chain = fallback_chain
                    return resp
                elif resp.success and not json_mode:
                    resp.fallback_occurred = len(fallback_chain) > 1
                    resp.fallback_chain = fallback_chain
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
        offline_resp.fallback_occurred = True
        offline_resp.fallback_chain = fallback_chain
        if last_error:
            offline_resp.metadata["prior_error"] = last_error
        return offline_resp

    def get_status(self) -> dict[str, Any]:
        """Returns sanitized status information for all providers."""
        status_info = {
            "configured_mode": settings.llm_provider,
            "allow_auto_fallback": settings.allow_auto_fallback,
            "providers": {
                "openrouter": {
                    "available": self.providers["openrouter"].is_available(),
                    "model": settings.openrouter_model,
                    "configured": bool(settings.openrouter_api_key),
                    "role": "Primary Cloud Provider",
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
