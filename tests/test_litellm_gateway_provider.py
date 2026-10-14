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
        headers = {}
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
        headers = {}
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


# --- which model actually answered ---

def _served_resp(group="zai-glm", model="openai/glm-4.5-flash"):
    class Resp:
        status_code = 200
        headers = {"x-litellm-model-group": group, "x-litellm-model-name": model}
        def raise_for_status(self): pass
        # body.model echoes the requested group on some routes: must be ignored
        def json(self): return {"model": group, "choices": [{"message": {"content": "ok"}}]}
    return Resp()


def test_the_served_model_is_recorded_not_the_requested_one(monkeypatch):
    """Asked for mistral-medium, answered by zai-glm: the gateway's fallback
    chain returns 200 either way, so only its own headers say who answered."""
    monkeypatch.setenv("LITELLM_GATEWAY_API_KEY", "sk-test")
    monkeypatch.setattr(requests, "post", lambda *a, **k: _served_resp())
    llm_client._call_litellm_gateway([{"role": "user", "content": "x"}], "", 0.1, 50, 0)
    assert llm_client.current_served_model() == "zai-glm:openai/glm-4.5-flash"


def test_a_later_non_gateway_call_clears_the_served_model(monkeypatch):
    """call_llm resets it per attempt, so a thread that last used the gateway
    cannot stamp the gateway's answer onto a different provider's reply."""
    llm_client._provider_tls.served = "zai-glm:openai/glm-4.5-flash"
    monkeypatch.setattr(llm_client, "_call_provider", lambda *a, **k: "ok")
    llm_client.call_llm([{"role": "user", "content": "x"}], "", provider="ollama",
                        use_fallbacks=False)
    assert llm_client.current_served_model() is None


def test_review_model_names_the_served_model(monkeypatch, tmp_path):
    import reviewer
    monkeypatch.setattr(reviewer, "_review_chain",
                        lambda: [("litellm-gateway", "mistral-medium")])
    monkeypatch.setattr(reviewer, "_load_review_facts", lambda: "facts")
    monkeypatch.setattr(reviewer, "_load_skills_md", lambda: "skills")
    monkeypatch.setattr(reviewer, "_load_decisions", lambda: "decisions")
    monkeypatch.setattr(reviewer, "REVIEWS_DIR", tmp_path)

    def fake_llm(*_a, **_k):
        llm_client._provider_tls.served = "zai-glm:openai/glm-4.5-flash"
        return "### 総評\n問題なし\n"

    monkeypatch.setattr(reviewer, "call_llm", fake_llm)
    monkeypatch.setattr(reviewer, "_review_is_unusable", lambda *_: None)
    doc = tmp_path / "X_CL.md"
    doc.write_text("---\ntype: cl\n---\n\nDear Hiring Team,\n\nbody\n")

    out = reviewer.run_review("CL", doc, {"company": "X", "title": "Y", "description": "d"})

    text = out.read_text(encoding="utf-8")
    assert 'review_model: "litellm-gateway/zai-glm:openai/glm-4.5-flash"' in text
    assert "mistral-medium" not in text


def test_non_breaking_hyphens_are_written_as_hyphens(monkeypatch):
    """gpt-oss emits U+2011 inside compounds; 63 letters carried it by 2026-10-08."""
    monkeypatch.setattr(llm_client, "_call_provider",
                        lambda *a, **k: "a systems‑oriented approach")
    out = llm_client.call_llm([{"role": "user", "content": "x"}], "", provider="ollama",
                              use_fallbacks=False)
    assert out == "a systems-oriented approach"
