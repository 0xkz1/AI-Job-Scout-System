"""The stage that spends the night's LLM time picks its own leader.

ANALYSIS_PROVIDER names one primary for the whole pipeline. Analyzer is 62% of
the nightly LLM time on a median 829-character prompt, and the provider it was
leading with takes a median 18.5s to answer that against groq's 0.9s — while
returning FEWER skills (40 vs 76 over 12 real postings). These pin the routing
that fixes it, and the two things that must not break with it: an explicit
provider= argument, and the size filter that keeps groq away from the 58k and
98k prompts it cannot accept.
"""
import pytest

import llm_client


@pytest.fixture(autouse=True)
def _stable_chain(monkeypatch):
    """Route on the table alone — not on which keys happen to be spent today."""
    monkeypatch.setenv("ANALYSIS_PROVIDER", "litellm-gateway")
    monkeypatch.setenv("FALLBACK_PROVIDERS", "groq,groq-back,litellm-gateway,ollama")
    monkeypatch.delenv("JIS_STAGE_PRIMARY", raising=False)
    monkeypatch.setattr(llm_client, "_quarantine_filter_chain", lambda chain: chain)


def _attempts(monkeypatch, stage, messages=None, **kwargs):
    """Every provider call_llm reaches, in order."""
    seen = []

    def _fail(prov, *a, **kw):
        seen.append(prov)
        raise RuntimeError("503 service unavailable")

    monkeypatch.setattr(llm_client, "_calling_stage", lambda: stage)
    monkeypatch.setattr(llm_client, "_call_provider", _fail)
    with pytest.raises(Exception):
        llm_client.call_llm(messages or [{"role": "user", "content": "hi"}],
                            retries=1, **kwargs)
    return seen


def test_the_analyzer_leads_with_the_fast_provider(monkeypatch):
    seen = _attempts(monkeypatch, "analyzer")
    assert seen[0] in llm_client.GROQ_PROVIDERS, seen[:3]


def test_the_configured_provider_is_still_reachable_behind_it(monkeypatch):
    """Leading with groq must cost a hop on failure, not the answer."""
    seen = _attempts(monkeypatch, "analyzer")
    assert "litellm-gateway" in seen, seen


def test_an_unlisted_stage_keeps_the_configured_primary(monkeypatch):
    seen = _attempts(monkeypatch, "cover_letter_generator")
    assert seen[0] == "litellm-gateway", seen[:3]


def test_an_explicit_provider_argument_wins(monkeypatch):
    """A caller naming its provider has a reason the table cannot see."""
    seen = _attempts(monkeypatch, "analyzer", provider="ollama")
    assert seen[0] == "ollama", seen[:3]


def test_the_environment_can_undo_a_bad_route(monkeypatch):
    monkeypatch.setenv("JIS_STAGE_PRIMARY", "")
    seen = _attempts(monkeypatch, "analyzer")
    assert seen[0] == "litellm-gateway", seen[:3]


def test_the_environment_can_route_another_stage(monkeypatch):
    monkeypatch.setenv("JIS_STAGE_PRIMARY", "reviewer=ollama")
    assert _attempts(monkeypatch, "reviewer")[0] == "ollama"
    # Replaces the table rather than overlaying it: analyzer is no longer routed.
    assert _attempts(monkeypatch, "analyzer")[0] == "litellm-gateway"


def test_a_prompt_groq_cannot_hold_still_routes_past_it(monkeypatch):
    """The size filter outranks the head of the chain, for any stage."""
    big = [{"role": "user", "content": "x" * 60000}]
    seen = _attempts(monkeypatch, "analyzer", messages=big)
    assert not (set(seen) & set(llm_client.GROQ_PROVIDERS)), seen
