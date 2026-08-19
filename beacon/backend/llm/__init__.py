"""BEACON Multi-Provider LLM Abstraction Layer.

Decouples candidate invariant reasoning from specific model providers:
OpenRouter (Primary) -> Anthropic (Supported) -> Ollama (Local) -> Offline (Deterministic)
"""

from .base import LLMProvider, LLMResponse, extract_json_payload
from .manager import ProviderManager, get_provider_manager
from .openrouter_provider import OpenRouterProvider
from .anthropic_provider import AnthropicProvider
from .ollama_provider import OllamaProvider
from .offline_provider import OfflineProvider

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "extract_json_payload",
    "ProviderManager",
    "get_provider_manager",
    "OpenRouterProvider",
    "AnthropicProvider",
    "OllamaProvider",
    "OfflineProvider",
]
