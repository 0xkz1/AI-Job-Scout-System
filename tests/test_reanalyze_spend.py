"""A re-analysis does not buy context calls for jobs the filter already threw out.

`match_all` is shared by the live scrape path — which only ever hands it jobs
that already survived the filter — and by `--reanalyze`, which hands it the
whole database. In the second case most of what lacks an LLM context lacks it on
purpose: skip_llm_context is what leaves a filter-rejected posting on TF-IDF.

Measured 2026-08-26 over 5260 stored jobs: 1071 carry a TF-IDF context and 910
of those are filter rejects. Re-analysing without this check spends 1504 context
calls where 619 is the honest number.
"""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import run  # noqa: E402


@pytest.fixture
def config():
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}


def _job(title, **over):
    job = {
        "title": title,
        "company": "Probe",
        "location": "Edinburgh, Scotland",
        "url": f"https://example.test/{title}",
        "description": "We build web software in Python and React. " * 30,
        "analysis": {"experience_level": "mid", "work_style": "remote",
                     "skills": ["Python", "React"], "employment_types": ["full_time"],
                     "salary": {"min": None, "max": None}},
    }
    job.update(over)
    return job


@pytest.fixture
def seen(monkeypatch):
    """Record the skip_llm_context each job was scored with."""
    calls = {}

    def fake(job, config, **kw):
        calls[job["title"]] = kw.get("skip_llm_context")
        return {"composite_score": 0.5}

    monkeypatch.setattr(run, "analyze_match", fake)
    return calls


def test_a_filter_rejected_job_is_scored_without_paying_for_context(seen, config):
    """"senior" is an excluded title keyword — the filter has already said no."""
    run.match_all([_job("Senior Software Engineer")], config)
    assert seen["Senior Software Engineer"] is True


def test_a_filter_passing_job_still_gets_its_context_call(seen, config):
    run.match_all([_job("Web Developer")], config)
    assert seen["Web Developer"] is False


def test_both_are_decided_per_job_in_one_batch(seen, config):
    run.match_all([_job("Web Developer"), _job("Senior Software Engineer")], config)
    assert seen["Web Developer"] is False
    assert seen["Senior Software Engineer"] is True


def test_an_explicit_caller_choice_still_wins(seen, config):
    """A caller that has already decided — the deliberate cheap pass — is not
    second-guessed, in either direction."""
    run.match_all([_job("Web Developer")], config, skip_llm_context=True)
    assert seen["Web Developer"] is True
    seen.clear()
    run.match_all([_job("Senior Software Engineer")], config, skip_llm_context=False)
    assert seen["Senior Software Engineer"] is False


def test_a_filter_error_never_silences_a_score(seen, config, monkeypatch):
    """Failing open costs a call; failing closed loses the score entirely."""
    monkeypatch.setattr(run, "passes_filter",
                        lambda job, cfg: (_ for _ in ()).throw(RuntimeError("boom")))
    run.match_all([_job("Web Developer")], config)
    assert seen["Web Developer"] is False


def test_other_keyword_arguments_are_still_passed_through(config, monkeypatch):
    got = {}
    monkeypatch.setattr(run, "analyze_match",
                        lambda job, config, **kw: got.update(kw) or {"composite_score": 0.1})
    run.match_all([_job("Web Developer")], config, skip_summary=True)
    assert got["skip_summary"] is True
    assert "skip_llm_context" in got
