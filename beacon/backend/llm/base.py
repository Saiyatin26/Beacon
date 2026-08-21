"""Base abstractions and common response models for BEACON's LLM Provider Layer."""

from abc import ABC, abstractmethod
import json
import re
from typing import Any, Optional
from pydantic import BaseModel, Field


class LLMResponse(BaseModel):
    """Standardized response format returned across all LLM providers."""
    model_config = {"protected_namespaces": ()}

    raw_text: str = ""
    parsed_json: Optional[Any] = None
    provider_name: str
    model_name: str
    requested_provider: str = "auto"
    latency_ms: Optional[float] = None
    fallback_occurred: bool = False
    fallback_chain: list[str] = Field(default_factory=list)
    fallback_reason: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    success: bool = True


def extract_json_payload(text: str) -> Optional[Any]:
    """Helper to cleanly extract JSON payload from raw LLM text outputs,
    stripping markdown blocks if present.
    """
    if not text:
        return None

    cleaned = text.strip()
    # Strip markdown fenced code blocks if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try finding the first '[' or '{' and the last ']' or '}'
        start_bracket = cleaned.find("[")
        start_brace = cleaned.find("{")

        if start_bracket != -1 and (start_brace == -1 or start_bracket < start_brace):
            end_bracket = cleaned.rfind("]")
            if end_bracket != -1 and end_bracket > start_bracket:
                try:
                    return json.loads(cleaned[start_bracket : end_bracket + 1])
                except json.JSONDecodeError:
                    pass
        elif start_brace != -1:
            end_brace = cleaned.rfind("}")
            if end_brace != -1 and end_brace > start_brace:
                try:
                    return json.loads(cleaned[start_brace : end_brace + 1])
                except json.JSONDecodeError:
                    pass
    return None


class LLMProvider(ABC):
    """Common interface for all LLM providers (OpenRouter, Anthropic, Ollama, Offline)."""

    name: str = "base"
    model: str = "base-model"

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = True,
    ) -> LLMResponse:
        """Executes candidate generation prompt and returns a standardized LLMResponse."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True if the provider is configured and available for requests."""
        pass

    def get_metadata(self) -> dict[str, Any]:
        """Returns non-sensitive metadata describing the provider and model."""
        return {
            "provider": self.name,
            "model": self.model,
            "available": self.is_available(),
        }
