"""llm_client provider-chain tests — no real network calls (mocked).

Covers: chained fallback on transient errors, skipping providers with a
missing API key, and NOT falling through on non-transient errors.
"""
import pytest

import llm_client


@pytest.fixture(autouse=True)
def _reset_provider(monkeypatch):
    # Isolate from the real .env
    monkeypatch.delenv("FALLBACK_PROVIDERS", raising=False)
    monkeypatch.delenv("FALLBACK_PROVIDER", raising=False)


def test_falls_through_transient_error_to_next_provider(monkeypatch):
    monkeypatch.setenv("FALLBACK_PROVIDERS", "stepfun,ollama")
    calls = []

    def fake_call_provider(provider, *a, **k):
        calls.append(provider)
        if provider in ("mistral", "stepfun"):
            raise RuntimeError("429 rate limit")
        return "OK from ollama"

    monkeypatch.setattr(llm_client, "_call_provider", fake_call_provider)
    result = llm_client.call_llm([{"role": "user", "content": "hi"}], provider="mistral")

    assert result == "OK from ollama"
    assert calls == ["mistral", "stepfun", "ollama"]


def test_skips_provider_with_missing_api_key(monkeypatch):
    monkeypatch.setenv("FALLBACK_PROVIDERS", "stepfun,ollama")
    calls = []

    def fake_call_provider(provider, *a, **k):
        calls.append(provider)
        if provider == "mistral":
            raise RuntimeError("timeout")
        if provider == "stepfun":
            raise ValueError("STEPFUN_API_KEY not set")
        return "OK from ollama"

    monkeypatch.setattr(llm_client, "_call_provider", fake_call_provider)
    result = llm_client.call_llm([{"role": "user", "content": "hi"}], provider="mistral")

    assert result == "OK from ollama"
    assert calls == ["mistral", "stepfun", "ollama"]


def test_non_transient_error_does_not_fall_through(monkeypatch):
    monkeypatch.setenv("FALLBACK_PROVIDERS", "ollama")
    calls = []

    def fake_call_provider(provider, *a, **k):
        calls.append(provider)
        raise RuntimeError("400 bad request: invalid model")

    monkeypatch.setattr(llm_client, "_call_provider", fake_call_provider)
    with pytest.raises(RuntimeError):
        llm_client.call_llm([{"role": "user", "content": "hi"}], provider="mistral")

    assert calls == ["mistral"]


def test_no_fallback_configured_raises_after_primary(monkeypatch):
    def fake_call_provider(provider, *a, **k):
        raise RuntimeError("500 server error")

    monkeypatch.setattr(llm_client, "_call_provider", fake_call_provider)
    with pytest.raises(RuntimeError):
        llm_client.call_llm([{"role": "user", "content": "hi"}], provider="mistral")


def test_is_transient_error_classification():
    assert llm_client._is_transient_error(RuntimeError("429 rate limit"))
    assert llm_client._is_transient_error(RuntimeError("503 Service Unavailable"))
    assert llm_client._is_transient_error(RuntimeError("Read timed out"))
    assert not llm_client._is_transient_error(RuntimeError("400 bad request"))
    assert not llm_client._is_transient_error(RuntimeError("invalid api key"))
