"""A context score that could not be measured must not read as a bad one.

The LLM context call fails roughly one time in five. It used to fall back to
TF-IDF, which across the whole database reads 0.11 median against the LLM's
0.30 — so a failed call did not record "we could not tell", it recorded "this
is a poor match". The score is then reused permanently by the
context_source == "llm" reuse branch, so one rate-limited call marked a good
posting weak forever.
"""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matcher  # noqa: E402


@pytest.fixture
def config():
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}


@pytest.fixture
def job():
    return {
        "title": "Full-stack Engineer",
        "company": "Probe",
        "location": "Remote, UK",
        "description": (
            "We build real-time retail software in Python and React. You will own "
            "features from the data layer to the interface, deploy them, and use "
            "automation to keep the pipeline honest. " * 6
        ),
        "analysis": {
            "experience_level": "mid",
            "skills": ["Python", "React", "PostgreSQL", "CI/CD", "Docker"],
        },
    }


def _score(job, config, monkeypatch, llm_result):
    """Run analyze_match with the LLM context call stubbed to one outcome."""
    monkeypatch.setattr(matcher, "_load_persona_summary", lambda: "persona text " * 50)
    monkeypatch.setattr(matcher, "_ollama_context_score",
                        lambda *a, **k: llm_result)
    return matcher.analyze_match(dict(job), config, skip_summary=True)


def test_a_failed_context_call_is_marked_unscored_not_scored_low(job, config, monkeypatch):
    m = _score(job, config, monkeypatch, None)
    assert m["context_source"] == "unscored", \
        "a failed LLM call fell back to TF-IDF and invented a low context score"


def test_an_unscored_context_does_not_drag_the_composite_to_zero(job, config, monkeypatch):
    """The context term is dropped and the rest renormalised, so the composite
    reflects the four axes that were measured rather than a fabricated fifth."""
    failed = _score(job, config, monkeypatch, None)
    scored = _score(job, config, monkeypatch,
                    {"score": 0.0, "reasoning": "", "provider": "stub"})
    assert failed["composite_score"] > scored["composite_score"], (
        "an unmeasured context scored the same as a measured zero — the weight "
        "was not renormalised"
    )


def test_an_unscored_context_cannot_reach_strong_match(job, config, monkeypatch):
    """Strong Match asserts a confirmed semantic read. Nothing confirmed it."""
    m = _score(job, config, monkeypatch, None)
    assert "Strong" not in m["tier"]


def test_a_deliberate_skip_still_uses_tfidf(job, config, monkeypatch):
    """skip_llm_context is the filter's rejects, where TF-IDF is the intended
    cheap answer — the change must not sweep that path up with real failures."""
    monkeypatch.setattr(matcher, "_load_persona_summary", lambda: "persona text " * 50)
    monkeypatch.setattr(matcher, "_ollama_context_score",
                        lambda *a, **k: pytest.fail("LLM called despite skip_llm_context"))
    m = matcher.analyze_match(dict(job), config, skip_summary=True, skip_llm_context=True)
    assert m["context_source"] == "tfidf"


def test_the_weights_still_sum_to_one(config):
    w = config["weights"]
    assert abs(sum(w.values()) - 1.0) < 1e-9, w


def test_context_no_longer_outweighs_skills(config):
    """The two predict the CV review equally well (r +0.238 vs +0.237) and only
    one of them reproduces: context spread 0.48 across nine runs of one posting,
    skills was identical every time."""
    w = config["weights"]
    assert w["context"] <= w["skills"], (
        f"context {w['context']} still outweighs skills {w['skills']} despite "
        "equal predictive power and far worse reproducibility"
    )
