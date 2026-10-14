"""exclude_title_keywords must be observations, not guesses.

The German description keywords grew two invented phrases ("fließend deutsch",
"verhandlungssicheres deutsch") that matched zero postings, so the same guard
applies here: every configured term has to match something in the live corpus, and
no term may take out a job that is currently good enough to generate documents for.

The trade terms exist because the composite score does not reject off-trade work
reliably. "Electrical Design Engineer" reached 0.78 — "design" and "engineer" read
as relevant — so 54 such jobs sat in the ranked pool, each having already been paid
for in LLM enrichment, which runs on everything that passes the filter.
"""
import json
import re

import pytest
import yaml
from pathlib import Path

from filter import passes_filter

ROOT = Path(__file__).resolve().parent.parent
ANALYZED = ROOT / "10_output" / "_analyzed.json"

# Seniority terms describe a level, not a trade, and are expected to appear in the
# corpus for a different reason. The corpus assertions below are about the trade
# terms — a seniority word matching nothing would mean the search itself changed.
SENIORITY = {"senior", "lead", "head of", "director", "manager"}


@pytest.fixture(scope="module")
def config():
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus():
    if not ANALYZED.exists():
        pytest.skip("no live DB")
    return json.loads(ANALYZED.read_text(encoding="utf-8"))


def _matches(keyword, title):
    return re.search(r"\b" + re.escape(keyword.lower()) + r"\b", (title or "").lower())


def test_every_excluded_title_keyword_occurs_in_the_corpus(config, corpus):
    """Guards against the list growing by guesswork."""
    titles = [j.get("title") or "" for j in corpus]
    unused = [k for k in config.get("exclude_title_keywords", [])
              if not any(_matches(k, t) for t in titles)]
    assert not unused, (
        f"these title keywords match nothing in the corpus and are guesses, not "
        f"observations: {unused}"
    )


def test_no_excluded_keyword_removes_a_job_from_the_generation_set(config, corpus):
    """The exclusions were adopted on the measurement that they cost nothing. If a
    future term takes out a job good enough to write a CV for, that measurement no
    longer holds and the term needs re-justifying."""
    from selection import select_top

    trade = [k for k in config.get("exclude_title_keywords", [])
             if k.lower() not in SENIORITY]
    if not trade:
        pytest.skip("no trade terms configured")
    unfiltered = dict(config, exclude_title_keywords=list(SENIORITY))
    generation = select_top("generation", unfiltered)
    # Jobs on the lowest score in the set are admitted as a block, on the grounds
    # that there is no basis for preferring one of them over another — not because
    # they beat the job below. Their membership is a tie-breaking policy, so one of
    # them matching a trade term says nothing about whether that term is justified;
    # "Civil Engineer" arrived this way, on exactly the 0.53 boundary. Measure the
    # jobs that are in the set on score alone.
    boundary = min((j["match"]["composite_score"] for j in generation), default=None)
    casualties = [
        (j.get("title"), k)
        for j in generation
        if j["match"]["composite_score"] > boundary
        for k in trade
        if _matches(k, j.get("title"))
    ]
    assert not casualties, (
        f"these keywords remove jobs that are in the generation set: {casualties}"
    )


@pytest.mark.parametrize("title", [
    "Electrical Design Engineer",
    "Mechanical Design Engineer",
    "Graduate Geotechnical Design Engineer",
    "Quantity Surveyor - Roofing & Render",
    "Registered Nurse",
    "HGV Driver Trainer",
])
def test_off_trade_titles_are_rejected(config, title):
    """All six are real titles from the corpus that passed the filter before."""
    ok, reason = passes_filter(
        {"title": title, "description": "A real job description. " * 30,
         "analysis": {"experience_level": "mid", "employment_types": ["full_time"],
                      "salary": {"min": None, "max": None, "period": None}}},
        config)
    assert not ok
    assert "excluded keyword" in reason


@pytest.mark.parametrize("title", [
    "Technical Artist",
    "Creative Technologist",
    "Product Designer",
    "Web Developer",
    "Digital Designer",
    "UX Designer - Design systems",
])
def test_target_titles_still_pass(config, title):
    """The trade terms must not clip the roles the search exists to find. "Technical
    Artist" is the specific risk: it is the best-performing keyword in the config at
    42.9%, and a substring match on "technician" would not touch it — but a careless
    addition of "technical" would."""
    ok, reason = passes_filter(
        {"title": title, "description": "A real job description. " * 30,
         "analysis": {"experience_level": "mid", "employment_types": ["full_time"],
                      "salary": {"min": None, "max": None, "period": None}}},
        config)
    assert ok, reason
