"""exclude_title_exceptions must be surgical, and must be observations.

`director` is a seniority marker and also half of "Art Director", which in UK
agencies is a mid-level craft title. Before this list existed, all four Art
Director postings in the corpus were filtered, two of them wrongly: "Junior Art
Director" and "Marketing Designer / Art Director (1 year FTC)".

The exception therefore has to be a SPAN, not a whole-title allowlist. "Senior Art
Director" contains the phrase and must still be excluded, because `senior` matches
outside it. These tests pin both directions, and sweep the live corpus so that a
future entry cannot quietly admit a class of jobs nobody looked at.
"""
import json
import re
from pathlib import Path

import pytest
import yaml

from filter import _exception_spans, _within_any, passes_filter

ROOT = Path(__file__).resolve().parent.parent
ANALYZED = ROOT / "10_output" / "_analyzed.json"

JOB = {
    "description": "A real job description. " * 30,
    "analysis": {"experience_level": "mid", "employment_types": ["full_time"],
                 "salary": {"min": None, "max": None, "period": None}},
}


@pytest.fixture(scope="module")
def config():
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus():
    if not ANALYZED.exists():
        pytest.skip("no live DB")
    return json.loads(ANALYZED.read_text(encoding="utf-8"))


def _passes(config, title):
    return passes_filter(dict(JOB, title=title), config)[0]


@pytest.mark.parametrize("title", [
    "Junior Art Director",
    "Marketing Designer / Art Director (1 year FTC)",
    "Art Director",
    "Lead Generation Specialist",
])
def test_exempted_titles_now_pass(config, title):
    """All four are real corpus titles that the exclusions used to remove."""
    assert _passes(config, title)


@pytest.mark.parametrize("title", [
    # The phrase is present, but a DIFFERENT exclusion applies outside it.
    "Senior Art Director - Web",
    "Senior Art Director (Move to Dubai)",
    # The phrase is absent — these are the roles `director` exists to remove.
    "Creative Director",
    "Design Director",
    "Associate Creative Director, Design",
    "Director, Creative Technology",
    "Head of Design",
    # `lead` outside "lead generation" still fires.
    "Lead UX Designer",
    "Lead Technical Artist",
])
def test_exceptions_do_not_open_the_gate(config, title):
    assert not _passes(config, title)


def test_every_exception_rescues_something_in_the_corpus(config, corpus):
    """Same rule as exclude_title_keywords: entries are observations, not guesses.

    A phrase that rescues nothing is either a dead entry or a guess about a market
    that has not been looked at. The German keyword list grew two invented phrases
    exactly this way.
    """
    titles = [j.get("title") or "" for j in corpus]
    no_exceptions = dict(config, exclude_title_exceptions=[])
    idle = []
    for phrase in config.get("exclude_title_exceptions", []):
        rescued = [
            t for t in titles
            if _passes(config, t) and not _passes(no_exceptions, t)
            and re.search(r"\b" + re.escape(phrase.lower()) + r"\b", t.lower())
        ]
        if not rescued:
            idle.append(phrase)
    assert not idle, (
        f"these exceptions rescue no posting in the corpus and are guesses, not "
        f"observations: {idle}"
    )


def test_nothing_is_admitted_without_an_exception_phrase(config, corpus):
    """The whole corpus, both ways round.

    Every title the exception list newly admits must contain one of its phrases.
    If a span calculation ever goes wrong, this is where a whole class of senior
    postings would show up.
    """
    no_exceptions = dict(config, exclude_title_exceptions=[])
    phrases = [p.lower() for p in config.get("exclude_title_exceptions", [])]
    rogue = []
    for title in {j.get("title") or "" for j in corpus}:
        if _passes(config, title) and not _passes(no_exceptions, title):
            if not any(re.search(r"\b" + re.escape(p) + r"\b", title.lower())
                       for p in phrases):
                rogue.append(title)
    assert not rogue, f"admitted without matching any exception phrase: {rogue[:5]}"


def test_span_containment_is_strict():
    """_within_any must require containment, not overlap.

    An overlap test would let "art" in "Art Directorate" exempt a `director` hit
    that starts inside the phrase and ends outside it.
    """
    spans = _exception_spans("junior art director", ["art director"])
    assert spans == [(7, 19)]
    assert _within_any((11, 19), spans)       # "director", inside
    assert not _within_any((0, 6), spans)     # "junior", outside
    assert not _within_any((7, 25), spans)    # starts inside, ends outside
