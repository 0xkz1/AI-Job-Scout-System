"""An empty completion must move to the next provider, not end the chain.

A reasoning model can spend its whole max_tokens budget on hidden reasoning and
return HTTP 200 with an empty content string. _call_openai_compatible raises on
that, and the comment at the raise says the point is to let the caller's chain
fall through to the next model — but _is_transient_error did not recognise the
message, so call_llm took it as fatal and stopped at the provider that produced
it.

That provider was groq, which leads the chain, and groq/gpt-oss-120b produces
this deterministically on short-output calls. So every cover-letter bridge
failed on the FIRST provider with eight live Mistral keys further down the
chain, and the letter shipped with the static fallback bridge.
"""
import llm_client


EMPTY = RuntimeError(
    "groq/openai/gpt-oss-120b returned empty content "
    "(reasoning-token exhaustion at max_tokens=200?)"
)


def test_an_empty_completion_is_transient():
    assert llm_client._is_transient_error(EMPTY)


def test_an_auth_failure_is_still_fatal():
    """The marker must not turn every RuntimeError into a retry — a bad key
    should fail fast rather than walk forty-eight providers."""
    assert not llm_client._is_transient_error(RuntimeError("401 Client Error: Unauthorized"))
    assert not llm_client._is_transient_error(RuntimeError("403 Client Error: Forbidden"))


def test_the_chain_reaches_the_next_provider_after_an_empty_completion(monkeypatch):
    tried = []

    def fake_provider(prov, messages, system_prompt, temperature, max_tokens, retries, model):
        tried.append(prov)
        if prov == "groq":
            raise EMPTY
        return "the bridge sentences"

    monkeypatch.setenv("ANALYSIS_PROVIDER", "groq")
    monkeypatch.setenv("FALLBACK_PROVIDERS", "mistral-tertiary")
    monkeypatch.setattr(llm_client, "_call_provider", fake_provider)
    monkeypatch.setattr(llm_client, "_quarantine_filter_chain", lambda chain: chain)
    monkeypatch.setattr(llm_client, "_size_filter_chain", lambda chain, m, s: chain)
    monkeypatch.setattr(llm_client, "_maybe_quarantine", lambda prov, err: None)

    out = llm_client.call_llm(messages=[{"role": "user", "content": "hi"}], max_tokens=200)

    assert out == "the bridge sentences"
    assert tried == ["groq", "mistral-tertiary"]
