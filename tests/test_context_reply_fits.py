"""Ask for one language, not two, so the reply fits in what is left to emit.

The context scorer's bilingual mode asks for the same 3-4 sentences in English
and in Japanese. That is what overruns the reply: the persona alone is 55k
characters and the whole request runs to ~61.5k, so the model has a few hundred
tokens left to write in regardless of max_tokens — completions came back at 353
to 1020 characters against a 900-token budget.

Measured over the same six postings, one call each:

  bilingual   2 of 6 truncated   scores .20 .75 .65 .15 .35 .15
  brief       0 of 6 truncated   scores .25 .75 .60 .15 .40 .10

The judgement does not change; the truncation stops. The persona is NOT the
thing to cut — it is the candidate's evidence, and a smaller one has already
been shipped and reverted here.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matcher  # noqa: E402


@pytest.fixture
def prompts(monkeypatch):
    """Capture the prompt the scorer would send, without calling anything."""
    seen = []

    def spy(**kw):
        seen.append("\n".join(m.get("content", "") for m in kw.get("messages", [])))
        return '{"ethos": 70, "role_fit": 60, "reasoning_en": "Fits."}'

    monkeypatch.setattr("llm_client.call_llm", spy)
    return seen


def test_one_language_is_the_default(prompts):
    matcher._ollama_context_score("a job description", "a persona")
    assert "reasoning_ja" not in prompts[0], \
        "the default still asks for both languages, which is what truncates"
    assert "reasoning_en" in prompts[0]


def test_both_languages_remain_available(prompts):
    matcher._ollama_context_score("a job description", "a persona", brief=False)
    assert "reasoning_ja" in prompts[0]


def test_the_analysis_path_uses_the_short_form(prompts, monkeypatch):
    """analyze_match is the caller that produced the truncated Moth reply."""
    monkeypatch.setattr(matcher, "_load_persona_summary", lambda: "persona " * 200)
    job = {"title": "Creative Technologist", "company": "Moth",
           "description": "Build prototypes and demos with artists. " * 20,
           "analysis": {"experience_level": "mid", "skills": ["Python"]}}
    matcher.analyze_match(job, {"weights": {"skills": 1.0}}, skip_summary=True)
    assert prompts, "no context call was made"
    assert "reasoning_ja" not in prompts[0]


def test_the_persona_still_reaches_the_model_whole(prompts, monkeypatch):
    """The fix must not have quietly become "send less persona"."""
    persona = "PERSONA-MARKER " * 4000
    matcher._ollama_context_score("a job description", persona)
    assert persona in prompts[0]


def test_the_persona_budget_is_a_guard_not_a_target():
    """PERSONA_CHAR_BUDGET exists to stop a runaway file, not to trim evidence.
    If the assembled persona ever reaches it, something is being cut silently."""
    matcher._persona_cache = None
    assembled = matcher._load_persona_summary()
    assert matcher._persona_assembled_chars <= matcher.PERSONA_CHAR_BUDGET, (
        f"the persona now assembles to {matcher._persona_assembled_chars} against a "
        f"budget of {matcher.PERSONA_CHAR_BUDGET} and is being truncated — raise the "
        f"guard rather than losing the evidence"
    )
    assert len(assembled) == matcher._persona_assembled_chars


def test_a_short_reply_still_carries_what_the_score_needs(monkeypatch):
    monkeypatch.setattr("llm_client.call_llm",
                        lambda **kw: '{"ethos": 88, "role_fit": 72, '
                                     '"role_requirement": "Building prototypes", '
                                     '"reasoning_en": "Strong overlap with creative tooling."}')
    out = matcher._ollama_context_score("a job description", "a persona")
    assert out["score"] == 0.72
    assert out["ethos"] == 0.88
    assert out["reasoning_en"]
    assert out["reasoning_ja"] == "", "Japanese is deferred to the backfill, not invented here"
