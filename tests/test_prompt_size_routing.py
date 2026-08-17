"""Oversized prompts must route past providers that cannot accept them.

Groq's account-level request-body limit (~22k prompt chars, measured 2026-08-17
by bisection: 21,812 accepted / 22,281 refused, identically on every model it
serves) is not a context window and no model swap escapes it. 413 is also not
transient, so walking 12 groq keys that will each refuse the same body is pure
latency — hence the pre-call filter, which is what allows groq to sit at the
FRONT of the chain despite not being able to serve the two heavyweight call
sites (reviewer ~98k chars, matcher role_fit ~63k chars).
"""
import llm_client
import pytest


@pytest.fixture(autouse=True)
def chain_env(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "groq")
    monkeypatch.setenv("FALLBACK_PROVIDERS", "groq-back,mistral,ollama")
    # Quarantine state is real on this machine; keep it out of these assertions.
    monkeypatch.setattr(llm_client, "_quarantine_filter_chain", lambda chain: chain)


def _tried(monkeypatch):
    """Record which providers _call_provider is asked for, failing each one."""
    order = []

    def fake(prov, *_a, **_k):
        order.append(prov)
        raise RuntimeError("429 rate limit")

    monkeypatch.setattr(llm_client, "_call_provider", fake)
    monkeypatch.setattr(llm_client, "_maybe_quarantine", lambda *a, **k: None)
    return order


def test_a_small_prompt_still_reaches_groq_first(monkeypatch):
    order = _tried(monkeypatch)
    with pytest.raises(RuntimeError):
        llm_client.call_llm([{"role": "user", "content": "x" * 5_000}])
    assert order[0] == "groq"
    assert "groq-back" in order


def test_an_oversized_prompt_skips_every_groq_key(monkeypatch):
    order = _tried(monkeypatch)
    with pytest.raises(RuntimeError):
        llm_client.call_llm([{"role": "user", "content": "x" * 63_000}])
    assert not [p for p in order if p.startswith("groq")], \
        "a 63k prompt must not be offered to groq — it can only answer 413"
    assert order == ["mistral", "ollama"]


def test_the_system_prompt_counts_toward_the_size(monkeypatch):
    """The system prompt is part of the same body, so a prompt that only fits
    without it must not be routed as if it fits."""
    order = _tried(monkeypatch)
    with pytest.raises(RuntimeError):
        llm_client.call_llm([{"role": "user", "content": "x" * 20_000}],
                            system_prompt="y" * 5_000)
    assert not [p for p in order if p.startswith("groq")]


def test_size_filter_never_empties_the_chain():
    """If every provider looked too small, try them anyway — one 413 beats
    making no call at all."""
    kept = llm_client._size_filter_chain(["groq", "groq-back"],
                                         [{"role": "user", "content": "x" * 99_000}], "")
    assert kept == ["groq", "groq-back"]


def test_providers_with_no_declared_cap_are_never_filtered():
    kept = llm_client._size_filter_chain(["mistral", "ollama", "nvidia"],
                                         [{"role": "user", "content": "x" * 500_000}], "")
    assert kept == ["mistral", "ollama", "nvidia"]


def test_every_groq_key_carries_the_cap():
    """A key added to GROQ_PROVIDERS without a cap would silently start
    collecting 413s on the big call sites."""
    assert set(llm_client.GROQ_PROVIDERS) <= set(llm_client._PROVIDER_MAX_PROMPT_CHARS)
