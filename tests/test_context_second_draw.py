"""One draw of a noisy measurement is not a verdict.

A stored LLM context score is reused forever, which is correct when the score
means something. Context does not repeat: the same posting, persona and code
scored nine times returned 0.40 through 0.88, while skills — measured the same
way — reproduced exactly. So 2186 of the 3888 jobs holding an LLM context score
sit at 0.30 or below permanently, whatever the draw happened to be.

The carve-out: when the reproducible term says the job fits and the noisy term
says it does not, the disagreement is evidence about the noisy term. Those jobs
(420 of 3888, measured 2026-08-24) are drawn once more and the draws averaged.
`context_draws` caps it there, so the extra spend happens once per job and never
again.
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
    """A job whose skills score clears skills_min, holding a stored LLM context."""
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


def _stored(score, draws=None):
    match = {
        "context_source": "llm",
        "context_score": score,
        "context_reasoning": "the first draw",
        "context_provider": "mistral",
    }
    if draws is not None:
        match["context_draws"] = draws
    return match


def _run(job, config, monkeypatch, second_draw, **kwargs):
    """analyze_match with the context call stubbed, counting how often it fires."""
    calls = []

    def _score(*a, **k):
        calls.append(a)
        return second_draw

    monkeypatch.setattr(matcher, "_load_persona_summary", lambda: "persona text " * 50)
    monkeypatch.setattr(matcher, "_ollama_context_score", _score)
    result = matcher.analyze_match(dict(job), config, skip_summary=True, **kwargs)
    return result, calls


def _skills_score(job, config, monkeypatch):
    m, _ = _run(dict(job, match=_stored(0.30, draws=2)), config, monkeypatch, None)
    return m["skills"]["score"]


# --- the trigger ---

def test_the_fixture_actually_disagrees(job, config, monkeypatch):
    """Guard: if this job's skills score fell under skills_min the tests below
    would pass by measuring nothing."""
    assert _skills_score(job, config, monkeypatch) >= config["context_rescore"]["skills_min"]


def test_a_low_context_under_high_skills_is_drawn_again(job, config, monkeypatch):
    job["match"] = _stored(0.20)
    m, calls = _run(job, config, monkeypatch, {"score": 0.80, "reasoning": "second", "provider": "groq"})
    assert len(calls) == 1, "the contradicted score was reused instead of re-measured"
    assert m["context_score"] == 0.50, "the two draws were not averaged"
    assert m["context_draws"] == 2


def test_the_second_draw_is_averaged_not_substituted(job, config, monkeypatch):
    """Both draws are samples of the same quantity. Taking only the newer one
    would throw away half the evidence and leave the variance where it was."""
    job["match"] = _stored(0.10)
    m, _ = _run(job, config, monkeypatch, {"score": 0.90, "reasoning": "second"})
    assert m["context_score"] == 0.50


def test_a_high_stored_context_keeps_its_luck(job, config, monkeypatch):
    """The correction is one-sided on purpose: symmetry would cost a second call
    on every job. A false low is a job never seen; a false high is a CV the
    review then rejects."""
    job["match"] = _stored(0.85)
    m, calls = _run(job, config, monkeypatch, {"score": 0.10})
    assert calls == [], "a high stored score was re-drawn"
    assert m["context_score"] == 0.85


def test_both_terms_reading_low_is_agreement_not_disagreement(job, config, monkeypatch):
    """Nothing contradicts a low context when skills is low too — that is two
    measurements saying the same thing, and re-drawing it buys nothing."""
    job["analysis"]["skills"] = ["Forklift", "Welding", "Scaffolding"]
    job["match"] = _stored(0.20)
    m, calls = _run(job, config, monkeypatch, {"score": 0.90})
    assert _skills_score(job, config, monkeypatch) < config["context_rescore"]["skills_min"]
    assert calls == []
    assert m["context_score"] == 0.20


# --- the cost is bounded ---

def test_a_job_already_drawn_twice_is_left_alone(job, config, monkeypatch):
    """Without this the trigger would pay for the same 420 jobs every night."""
    job["match"] = _stored(0.20, draws=2)
    m, calls = _run(job, config, monkeypatch, {"score": 0.90})
    assert calls == []
    assert m["context_score"] == 0.20
    assert m["context_draws"] == 2


def test_a_filtered_out_job_is_never_re_drawn(job, config, monkeypatch):
    """skip_llm_context is the filter's rejects. They are kept in the DB so a
    loosened keyword needs no re-scrape, and they must not buy model calls."""
    job["match"] = _stored(0.20)
    m, calls = _run(job, config, monkeypatch, {"score": 0.90}, skip_llm_context=True)
    assert calls == [], "a rejected posting paid for a second draw"
    assert m["context_score"] == 0.20


def test_a_failed_second_draw_keeps_what_was_measured(job, config, monkeypatch):
    """A call that never returned is not a draw. The stored score survives, the
    count does not advance, and the source stays "llm" — dropping to "unscored"
    here would discard a real measurement because a later one failed."""
    job["match"] = _stored(0.20)
    m, calls = _run(job, config, monkeypatch, None)
    assert len(calls) == 1
    assert m["context_score"] == 0.20
    assert m["context_source"] == "llm"
    assert m["context_draws"] == 1, "a failed call was banked as a draw"


def test_disabling_it_restores_plain_reuse(job, config, monkeypatch):
    job["match"] = _stored(0.20)
    off = dict(config, context_rescore=dict(config["context_rescore"], enabled=False))
    m, calls = _run(job, off, monkeypatch, {"score": 0.90})
    assert calls == []
    assert m["context_score"] == 0.20


def test_a_config_without_the_block_is_the_old_behaviour(job, config, monkeypatch):
    job["match"] = _stored(0.20)
    bare = {k: v for k, v in config.items() if k != "context_rescore"}
    m, calls = _run(job, bare, monkeypatch, {"score": 0.90})
    assert calls == []
    assert m["context_score"] == 0.20


# --- the count means what it says ---

def test_a_first_llm_score_records_one_draw(job, config, monkeypatch):
    m, calls = _run(job, config, monkeypatch, {"score": 0.70, "reasoning": "first"})
    assert len(calls) == 1
    assert m["context_source"] == "llm"
    assert m["context_draws"] == 1


def test_an_unmeasured_context_records_no_draws(job, config, monkeypatch):
    m, _ = _run(job, config, monkeypatch, None)
    assert m["context_source"] == "unscored"
    assert m["context_draws"] == 0


def test_tfidf_records_no_draws(job, config, monkeypatch):
    m, _ = _run(job, config, monkeypatch, None, skip_llm_context=True)
    assert m["context_source"] == "tfidf"
    assert m["context_draws"] == 0


def test_a_score_predating_the_count_is_treated_as_one_draw(job, config, monkeypatch):
    """Every stored score in the database was written before context_draws
    existed. Reading those as zero draws would re-draw the whole 3888, not the
    420 that disagree."""
    job["match"] = _stored(0.85)  # no context_draws key
    m, _ = _run(job, config, monkeypatch, {"score": 0.10})
    assert m["context_draws"] == 1


# --- the shipped config ---

def test_the_shipped_config_turns_this_on(config):
    cfg = config.get("context_rescore") or {}
    assert cfg.get("enabled") is True
    assert cfg.get("max_draws") == 2, "an unbounded re-draw pays for the same jobs nightly"


def test_the_skills_floor_is_above_the_databases_median(config):
    """skills median across the DB is 0.30. A floor at or below it would fire on
    half the database instead of on genuine disagreements."""
    assert config["context_rescore"]["skills_min"] > 0.30
