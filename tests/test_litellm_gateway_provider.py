"""_call_litellm_gateway is additive: it must not change any existing provider's
behavior, and it must dispatch correctly when asked for.

Added 2026-08-15 to try atelier/forge/litellm-gateway (localhost:4001) as a
provider without touching the 44-key chain already in production — that chain
was mid-run (a 470-pair CV/CL regeneration) when this was written, so nothing
above _call_litellm_gateway in llm_client.py may change.
"""
import llm_client
import pytest
import requests


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("LITELLM_GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("LITELLM_GATEWAY_URL", raising=False)
    monkeypatch.delenv("LITELLM_GATEWAY_MODEL", raising=False)


def test_dispatch_routes_litellm_gateway_to_its_own_function(monkeypatch):
    called = []

    def fake(*_a, **_k):
        called.append(True)
        return "ok"

    monkeypatch.setattr(llm_client, "_call_litellm_gateway", fake)
    out = llm_client._call_provider("litellm-gateway", [{"role": "user", "content": "x"}],
                                    "", 0.1, 50, 2)
    assert called == [True]
    assert out == "ok"


def test_dispatch_for_existing_providers_is_unchanged(monkeypatch):
    """The regression this guards: adding a new elif must not shift which
    branch an existing provider name falls into."""
    calls = []
    monkeypatch.setattr(llm_client, "_call_mistral",
                        lambda *a, **k: calls.append("mistral") or "m")
    monkeypatch.setattr(llm_client, "_call_ollama",
                        lambda *a, **k: calls.append("ollama") or "o")
    assert llm_client._call_provider("mistral", [], "", 0.1, 50, 2) == "m"
    assert llm_client._call_provider("some-unknown-provider", [], "", 0.1, 50, 2) == "o"
    assert calls == ["mistral", "ollama"]


def test_missing_api_key_raises_before_any_network_call(monkeypatch):
    def fail(*_a, **_k):
        raise AssertionError("should not reach the network with no key set")
    monkeypatch.setattr(requests, "post", fail)
    with pytest.raises(ValueError, match="LITELLM_GATEWAY_API_KEY"):
        llm_client._call_litellm_gateway([{"role": "user", "content": "x"}], "", 0.1, 50, 2)


def test_defaults_to_the_gateway_url_and_model(monkeypatch):
    monkeypatch.setenv("LITELLM_GATEWAY_API_KEY", "sk-test")
    seen = {}

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "ok"}}]}

    def post(url, headers, json, timeout):
        seen["url"] = url
        seen["model"] = json["model"]
        seen["auth"] = headers["Authorization"]
        return Resp()

    monkeypatch.setattr(requests, "post", post)
    out = llm_client._call_litellm_gateway([{"role": "user", "content": "x"}], "", 0.1, 50, 2)
    assert out == "ok"
    assert seen["url"] == "http://localhost:4001/v1/chat/completions"
    assert seen["model"] == "mistral-medium"
    assert seen["auth"] == "Bearer sk-test"


def test_an_explicit_model_override_is_honored(monkeypatch):
    monkeypatch.setenv("LITELLM_GATEWAY_API_KEY", "sk-test")
    seen = {}

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "ok"}}]}

    def post(url, headers, json, timeout):
        seen["model"] = json["model"]
        return Resp()

    monkeypatch.setattr(requests, "post", post)
    llm_client._call_litellm_gateway([{"role": "user", "content": "x"}], "", 0.1, 50, 2,
                                     model="zai-glm")
    assert seen["model"] == "zai-glm"


def test_empty_content_is_treated_as_a_failure(monkeypatch):
    """Same rule the other providers already follow — an empty reply is not a
    successful call, it is silent data loss for whatever awaited the answer."""
    monkeypatch.setenv("LITELLM_GATEWAY_API_KEY", "sk-test")

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": ""}}]}

    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp())
    with pytest.raises(RuntimeError, match="empty content"):
        llm_client._call_litellm_gateway([{"role": "user", "content": "x"}], "", 0.1, 50, 0)


def test_an_unresponsive_gateway_is_abandoned_after_one_attempt(monkeypatch):
    """The same fix from tonight's timeout work applies here too — a connection
    failure should not eat a full retry budget."""
    monkeypatch.setenv("LITELLM_GATEWAY_API_KEY", "sk-test")
    attempts = []

    def dead(*_a, **_k):
        attempts.append(1)
        raise requests.exceptions.ConnectTimeout("timed out")

    monkeypatch.setattr(requests, "post", dead)
    with pytest.raises(RuntimeError, match="after 1 attempts"):
        llm_client._call_litellm_gateway([{"role": "user", "content": "x"}], "", 0.1, 50, 2)
    assert len(attempts) == 1
