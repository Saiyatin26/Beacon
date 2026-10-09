import json
import urllib.error

from llm.openrouter_provider import OpenRouterProvider


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(
            {
                "model": "fallback/model",
                "choices": [{"message": {"content": '{"ok": true}'}}],
            }
        ).encode("utf-8")


def test_openrouter_retries_invalid_model_with_fallback(monkeypatch):
    import operations.resilience
    from common.config import settings

    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if len(requests) == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Model not found",
                None,
                None,
            )
        return FakeResponse()

    monkeypatch.setattr(operations.resilience, "execute_with_retry", lambda operation, **_: operation())
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(settings, "openrouter_fallback_model", "fallback/model")
    provider = OpenRouterProvider(
        api_key="test-key-not-a-real-credential",
        model="retired/model",
        base_url="https://openrouter.example/api/v1",
    )

    response = provider.generate("Return a JSON object.", json_mode=True)

    assert response.success
    assert response.model_name == "fallback/model"
    assert response.fallback_occurred
    assert response.fallback_chain == ["retired/model", "fallback/model"]
    assert response.metadata["configured_model"] == "retired/model"
    assert response.metadata["actual_model"] == "fallback/model"
    assert len(requests) == 2
    assert json.loads(requests[0].data)["model"] == "retired/model"
    assert json.loads(requests[1].data)["model"] == "fallback/model"
    assert requests[0].get_header("Authorization") == "Bearer test-key-not-a-real-credential"
