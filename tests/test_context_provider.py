"""A stored context score must record WHICH model produced it.

context carries 0.64 of the composite weight, and the provider chain changes what
answers without saying so: on 2026-07-26 all ten Mistral keys hit their monthly
limit mid-run and scoring fell through to ollama, stored identically because
context_source only distinguishes "llm" from "tfidf". Worse, `--reanalyze
--llm-context` skips anything already tagged "llm", so the weaker scores would
never be refreshed — the DB would silently hold three models' judgements as one.
"""
import llm_client
import matcher
import pytest


@pytest.fixture(autouse=True)
def reset_last_provider():
    llm_client.last_provider = None
    yield
    llm_client.last_provider = None


def test_call_llm_records_the_provider_that_answered(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "mistral")
    monkeypatch.delenv("FALLBACK_PROVIDERS", raising=False)
    monkeypatch.setattr(llm_client, "_quarantine_filter_chain", lambda chain: chain)
    monkeypatch.setattr(llm_client, "_call_provider",
                        lambda provider, *a, **k: "answer")
    llm_client.call_llm([{"role": "user", "content": "hi"}])
    assert llm_client.last_provider == "mistral"


def test_provider_recorded_is_the_fallback_not_the_primary(monkeypatch):
    """The whole point: when the primary is spent, the record must name what actually
    answered, not what was asked first."""
    monkeypatch.setenv("ANALYSIS_PROVIDER", "mistral")
    monkeypatch.setenv("FALLBACK_PROVIDERS", "ollama")
    monkeypatch.setattr(llm_client, "_quarantine_filter_chain", lambda chain: chain)

    def only_ollama_works(provider, *_a, **_k):
        if provider != "ollama":
            raise RuntimeError("429 rate limit")
        return "answer"

    monkeypatch.setattr(llm_client, "_call_provider", only_ollama_works)
    llm_client.call_llm([{"role": "user", "content": "hi"}])
    assert llm_client.last_provider == "ollama"


def test_context_score_carries_the_provider(monkeypatch):
    """_ollama_context_score must attach it, so analyze_match can store it."""
    monkeypatch.setattr(matcher, "_call_llm",
                        lambda **_k: '{"score": 72, "reasoning_en": "Fits."}',
                        raising=False)
    monkeypatch.setattr(llm_client, "call_llm",
                        lambda *a, **k: '{"score": 72, "reasoning_en": "Fits."}')
    llm_client.last_provider = "ollama"
    out = matcher._ollama_context_score("A long job description. " * 20, "persona")
    assert out is not None
    assert out["score"] == 0.72
    assert out["provider"] == "ollama"


def test_stored_provider_survives_a_rerun_that_reuses_the_score():
    """analyze_match reuses a stored LLM context score rather than re-paying for it;
    that path must not blank the provider, or the record is lost on first rerun."""
    old = {
        "context_source": "llm",
        "context_score": 0.8,
        "context_reasoning": "r",
        "context_reasoning_en": "r",
        "context_reasoning_ja": "",
        "context_top_terms": [],
        "context_provider": "mistral-denary",
    }
    # Mirrors the reuse branch in analyze_match.
    reused = {
        "score": old.get("context_score", 0),
        "reasoning": old.get("context_reasoning", ""),
        "reasoning_en": old.get("context_reasoning_en", ""),
        "reasoning_ja": old.get("context_reasoning_ja", ""),
        "top_terms": old.get("context_top_terms", []),
        "provider": old.get("context_provider"),
    }
    assert reused["provider"] == "mistral-denary"


def test_analyze_match_stores_context_provider(monkeypatch):
    """End to end: the field reaches the stored match dict."""
    monkeypatch.setattr(matcher, "_load_persona_summary", lambda: "persona")
    monkeypatch.setattr(matcher, "_ollama_context_score",
                        lambda *a, **k: {"score": 0.7, "reasoning": "r",
                                         "reasoning_en": "r", "reasoning_ja": "",
                                         "provider": "ollama"})
    job = {
        "title": "Web Developer",
        "company": "Acme",
        "location": "London",
        "description": "Build responsive sites with JavaScript and CSS. " * 20,
        "analysis": {"skills": ["JavaScript"], "experience_level": "mid",
                     "employment_types": ["full_time"], "work_style": "hybrid",
                     "salary": {"min": 35000, "max": 45000}},
    }
    out = matcher.analyze_match(job, {"min_salary_gbp": 26000}, skip_summary=True)
    assert out["context_provider"] == "ollama"


def test_unquoted_prose_value_is_repaired():
    """The two-axis prompt asks for four fields and the model returns the long
    free-text one bare often enough to matter: `"reasoning_en": The candidate's
    ethos aligns...`. json.loads(strict=False) does not save it — an unquoted
    value is a syntax error, not a control-character one — so the whole reply
    was dropped and _ollama_context_score returned None. brief=True is the mode
    llm_context_backfill runs nightly, so every new posting lost its score."""
    import json
    from matcher import _repair_json

    blob = ('{\n "ethos": 92,\n "role_fit": 88,\n'
            ' "role_requirement": "3D web viewers",\n'
            ' "reasoning_en": The "systems" ethos aligns, valuing flexibility.\n}')

    data = json.loads(_repair_json(blob), strict=False)

    assert data["role_fit"] == 88
    assert data["reasoning_en"].startswith("The 'systems' ethos")


def test_valid_json_is_left_alone():
    import json
    from matcher import _repair_json

    blob = '{"ethos": 50, "role_fit": 40, "reasoning_en": "already quoted"}'

    assert json.loads(_repair_json(blob))["reasoning_en"] == "already quoted"
