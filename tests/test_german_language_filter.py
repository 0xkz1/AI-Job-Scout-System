"""Native-level German is a requirement the candidate cannot meet.

It appears in 6 of 13 Arbeitnow postings — the single biggest reason EU jobs are
unusable — so it belongs in exclude_description_keywords rather than being
discovered again at review time.

The word boundary is what makes this safe. "deutschlandticket" is a commuter-pass
perk, and it appears in the Berlin posting that reviewed at 79 (the best EU match
found so far). A substring match on "deutsch" would have discarded exactly the job
worth having, which is how the requirement was first mis-measured: a naive
regex reported 10 of 13 postings as demanding German when the real figure is 6.
"""
import re

import pytest
import yaml
from pathlib import Path

from filter import passes_filter

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def config():
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def _job(description, title="UX Designer"):
    return {
        "title": title,
        "description": description,
        "analysis": {"experience_level": "mid", "employment_types": ["full_time"],
                     "salary": {"min": None, "max": None, "period": None},
                     "skills": [], "work_style": "remote"},
    }


@pytest.mark.parametrize("phrase", [
    "Deutschkenntnisse mindestens C1",
    "Sehr gute Deutschkenntnisse in Wort und Schrift",
    "Gute Deutschkenntnisse erforderlich",
    "sehr gute Deutsch- und Englischkenntnisse in Wort und Schrift",
])
def test_german_language_requirement_is_excluded(config, phrase):
    """All four forms are taken from the live corpus, not invented."""
    ok, reason = passes_filter(_job(f"Wir suchen einen Designer. {phrase} Benefits: ..."),
                               config)
    assert not ok
    assert "excluded keyword" in reason


def test_deutschlandticket_perk_does_not_count_as_a_language_requirement(config):
    """The 79-point Berlin posting. A substring match would have dropped it."""
    desc = ("Modern office space in Berlin. Budget for self-improvement, Gympass, "
            "Deutschlandticket subscription, dedicated time for learning. "
            "We work in English across the team.")
    ok, reason = passes_filter(_job(desc, title="Founding Product Designer"), config)
    assert ok, reason


def test_english_language_german_company_still_passes(config):
    desc = ("We are a Berlin-based startup building B2B SaaS. Working language is "
            "English. You will own the full design lifecycle. " * 4)
    assert passes_filter(_job(desc), config)[0]


def test_configured_phrases_all_occur_in_the_corpus(config):
    """Guards against the list growing by guesswork. Every German phrase here was
    verified present; "fluent german", "german language skills" and the Spanish and
    French equivalents matched zero postings and were deliberately left out.

    Skipped when the DB is unavailable — this asserts a property of the corpus.
    """
    import json

    db_path = ROOT / "10_output" / "_analyzed.json"
    if not db_path.exists():
        pytest.skip("no live DB")
    descriptions = [(j.get("description") or "").lower()
                    for j in json.loads(db_path.read_text(encoding="utf-8"))]
    german = [k for k in config.get("exclude_description_keywords", [])
              if "deutsch" in k.lower()]
    assert german, "the German-requirement phrases have gone missing from config"
    unused = [k for k in german
              if not any(re.search(r"\b" + re.escape(k.lower()) + r"\b", d)
                         for d in descriptions)]
    assert not unused, (
        f"these phrases match nothing in the corpus and are guesses, not "
        f"observations: {unused}"
    )
