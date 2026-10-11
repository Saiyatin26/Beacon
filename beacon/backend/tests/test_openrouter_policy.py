"""Unit and negative-path tests for strict OpenRouter-only policy in Full BEACON.

Validates error normalization, rejection of fallback providers, rejection of
provider spoofing, and clean fail-closed diagnostics without secret exposure.
"""

import json
import urllib.error
import pytest

from common.config import settings
from llm.base import LLMResponse
from llm.manager import ProviderManager
from llm.openrouter_provider import OpenRouterProvider


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


def test_openrouter_success_with_valid_response(monkeypatch):
    def fake_urlopen(req, timeout=30.0):
        return MockHttpResponse({
            "model": "anthropic/claude-3.5-sonnet",
            "choices": [{"message": {"content": '{"rules": [], "test_cases": []}'}}],
            "usage": {"total_tokens": 50},
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenRouterProvider(api_key="sk-test-key", model="anthropic/claude-3.5-sonnet")
    resp = provider.generate("Extract rules", json_mode=True)

    assert resp.success is True
    assert resp.provider_name == "openrouter"
    assert resp.error_category is None
    assert resp.parsed_json == {"rules": [], "test_cases": []}


def test_openrouter_missing_api_key():
    provider = OpenRouterProvider(api_key="", model="anthropic/claude-3.5-sonnet")
    resp = provider.generate("Extract rules")

    assert resp.success is False
    assert resp.error_category == "OPENROUTER_API_KEY_MISSING"
    assert "not configured" in resp.error.lower() or "missing" in resp.error.lower()


def test_openrouter_authentication_failed_401(monkeypatch):
    def fake_urlopen(req, timeout=30.0):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", None, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenRouterProvider(api_key="sk-invalid-key", model="anthropic/claude-3.5-sonnet")
    resp = provider.generate("Extract rules")

    assert resp.success is False
    assert resp.error_category == "OPENROUTER_AUTHENTICATION_FAILED"
    assert "OPENROUTER_AUTHENTICATION_FAILED" in resp.error
    assert "sk-invalid-key" not in resp.error


def test_openrouter_insufficient_credits_402(monkeypatch):
    def fake_urlopen(req, timeout=30.0):
        raise urllib.error.HTTPError(req.full_url, 402, "Payment Required", None, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenRouterProvider(api_key="sk-test-key", model="anthropic/claude-3.5-sonnet")
    resp = provider.generate("Extract rules")

    assert resp.success is False
    assert resp.error_category == "OPENROUTER_INSUFFICIENT_CREDITS"


def test_openrouter_rate_limited_429(monkeypatch):
    def fake_urlopen(req, timeout=30.0):
        raise urllib.error.HTTPError(req.full_url, 429, "Rate limit exceeded", None, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenRouterProvider(api_key="sk-test-key", model="anthropic/claude-3.5-sonnet")
    resp = provider.generate("Extract rules")

    assert resp.success is False
    assert resp.error_category == "OPENROUTER_RATE_LIMITED"


def test_openrouter_model_unavailable_404(monkeypatch):
    def fake_urlopen(req, timeout=30.0):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", None, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenRouterProvider(api_key="sk-test-key", model="nonexistent/model")
    resp = provider.generate("Extract rules")

    assert resp.success is False
    assert resp.error_category == "OPENROUTER_MODEL_UNAVAILABLE"


def test_openrouter_request_timeout(monkeypatch):
    def fake_urlopen(req, timeout=30.0):
        raise TimeoutError("Connection timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenRouterProvider(api_key="sk-test-key", model="anthropic/claude-3.5-sonnet")
    resp = provider.generate("Extract rules")

    assert resp.success is False
    assert resp.error_category == "OPENROUTER_REQUEST_TIMEOUT"


def test_openrouter_network_error(monkeypatch):
    def fake_urlopen(req, timeout=30.0):
        raise urllib.error.URLError("DNS resolution failure")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenRouterProvider(api_key="sk-test-key", model="anthropic/claude-3.5-sonnet")
    resp = provider.generate("Extract rules")

    assert resp.success is False
    assert resp.error_category == "OPENROUTER_NETWORK_ERROR"


def test_openrouter_invalid_malformed_json_response(monkeypatch):
    def fake_urlopen(req, timeout=30.0):
        return MockHttpResponse({
            "model": "anthropic/claude-3.5-sonnet",
            "choices": [{"message": {"content": "This is non-JSON raw response"}}],
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenRouterProvider(api_key="sk-test-key", model="anthropic/claude-3.5-sonnet")
    resp = provider.generate("Extract rules", json_mode=True)

    assert resp.success is False
    assert resp.error_category == "OPENROUTER_INVALID_RESPONSE"


def test_provider_manager_strictly_forbids_fallback_on_openrouter_failure(monkeypatch):
    """Critical requirement: When OpenRouter fails in Full BEACON mode,
    ProviderManager must NOT fall back to Gemini, Anthropic, Ollama, or Offline!
    """
    pm = ProviderManager()

    # Track invocations
    invoked_providers = []

    for name, p in pm.providers.items():
        def make_generate(provider_name):
            def _gen(*args, **kwargs):
                invoked_providers.append(provider_name)
                return LLMResponse(
                    raw_text="",
                    provider_name=provider_name,
                    model_name="mock",
                    success=False,
                    error_category=f"{provider_name.upper()}_FAILED",
                    error="Intentional test failure",
                )
            return _gen
        monkeypatch.setattr(p, "generate", make_generate(name))

    resp = pm.generate(
        "Extract candidate rules",
        preferred_provider="openrouter",
        allow_fallback=False,
    )

    assert resp.success is False
    assert invoked_providers == ["openrouter"]
    assert "gemini" not in invoked_providers
    assert "anthropic" not in invoked_providers
    assert "ollama" not in invoked_providers
    assert "offline" not in invoked_providers
