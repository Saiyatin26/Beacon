"""Unit tests for Gemini Provider and multi-provider selection in BEACON."""

import json
import pytest

from common.config import settings
from llm.base import LLMResponse
from llm.gemini_provider import GeminiProvider
from llm.manager import ProviderManager


class MockHttpResponse:
    def __init__(self, data: dict, status: int = 200):
        self.data = data
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.data).encode("utf-8")


def test_gemini_missing_api_key():
    provider = GeminiProvider(api_key="", model="gemini-1.5-flash")
    resp = provider.generate("Extract rules")

    assert resp.success is False
    assert resp.error_category == "GEMINI_API_KEY_MISSING"
    assert "GEMINI_API_KEY" in resp.error or "missing" in resp.error.lower()


def test_gemini_success_with_valid_response(monkeypatch):
    def fake_urlopen(req, timeout=30.0):
        return MockHttpResponse({
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"rules": [{"rule_id": "RULE-01"}], "test_cases": []}'}]
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"totalTokenCount": 42},
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = GeminiProvider(api_key="AIzaSyTestGeminiKey", model="gemini-1.5-flash")
    resp = provider.generate("Extract rules", json_mode=True)

    assert resp.success is True
    assert resp.provider_name == "gemini"
    assert resp.model_name == "gemini-1.5-flash"
    assert resp.parsed_json == {"rules": [{"rule_id": "RULE-01"}], "test_cases": []}


def test_provider_manager_with_gemini_provider(monkeypatch):
    def fake_urlopen(req, timeout=30.0):
        return MockHttpResponse({
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"rules": [], "test_cases": []}'}]
                    },
                    "finishReason": "STOP",
                }
            ],
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    pm = ProviderManager()
    gemini_prov = pm.get_provider("gemini")
    assert gemini_prov is not None
    gemini_prov.api_key = "AIzaSyTestGeminiKey"

    # Strictly generate via preferred_provider="gemini" with allow_fallback=False
    resp = pm.generate(
        "Analyze code",
        preferred_provider="gemini",
        allow_fallback=False,
    )

    assert resp.success is True
    assert resp.provider_name == "gemini"
    assert resp.requested_provider == "gemini"


def test_provider_manager_gemini_missing_key_fails_closed():
    pm = ProviderManager()
    gemini_prov = pm.get_provider("gemini")
    assert gemini_prov is not None
    gemini_prov.api_key = ""  # Explicitly empty

    resp = pm.generate(
        "Analyze code",
        preferred_provider="gemini",
        allow_fallback=False,
    )

    assert resp.success is False
    assert resp.error_category == "GEMINI_API_KEY_MISSING"
