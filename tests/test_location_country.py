"""Location scoring must not depend on how a place name is spelled.

The text route matches against a hand-kept alias list, so the same country scored
differently by spelling: "Deutschland" was recognised as German on-site (0.20),
while "Hagsfeld, Karlsruhe" and "España" missed every alias and fell through to
0.15 "location unknown".

The inversion is the actual bug. 0.15 is HIGHER than the 0.20 given to on-site
abroad, so an unrecognised spelling scored better than a recognised one — the alias
list being incomplete quietly promoted the jobs it failed to identify. A hand-kept
list of European place names cannot be completed; the Adzuna country code needs no
completing.
"""
import pytest
from matcher import calculate_location_match


def score(location, work_style="unknown", country=None):
    return calculate_location_match(location, work_style, {}, country=country)["score"]


@pytest.mark.parametrize("location", [
    "España",                      # Spanish spelling, not in the alias list
    "Hagsfeld, Karlsruhe",         # German city, not in the alias list
    "Bernau bei Berlin, Barnim (Kreis)",
    "Deutschland",                 # in the alias list
])
def test_same_country_scores_the_same_whatever_the_spelling(location):
    """All four are on-site in a target market, so all four must score 0.20."""
    country = "Spain" if "aña" in location else "Germany"
    assert score(location, country=country) == 0.20


def test_unrecognised_spelling_no_longer_outranks_a_recognised_one():
    """Guards the inversion directly: the alias-list miss used to score higher."""
    recognised = score("Deutschland", country="Germany")
    unrecognised = score("Hagsfeld, Karlsruhe", country="Germany")
    assert unrecognised <= recognised


def test_remote_in_a_target_market_is_in_scope():
    """The whole point of the multi-country expansion: remote is holdable from the
    UK, on-site is not."""
    assert score("Hagsfeld, Karlsruhe", "remote", country="Germany") == 0.85
    assert score("Hagsfeld, Karlsruhe", "unknown", country="Germany") == 0.20


def test_country_outside_the_target_list_is_out_of_scope():
    """Japan used to land on 0.15 "unknown", above on-site abroad."""
    assert score("Tokyo", country="Japan") < 0.20
    assert score("Tokyo", "remote", country="Japan") < 0.85


def test_us_stays_out_of_scope_by_country():
    assert score("Austin, TX", country="US") == 0.05
    assert score("Austin, TX", "remote", country="US") == 0.18


@pytest.mark.parametrize("location,expected", [
    ("Edinburgh", 1.0),
    ("Remote", 0.95),
])
def test_uk_jobs_still_use_the_detailed_city_tiers(location, expected):
    """country="UK" must fall through, not short-circuit — the UK tiers carry the
    Edinburgh/Glasgow/Scotland distinctions that drive the whole ranking."""
    assert score(location, "remote" if location == "Remote" else "unknown",
                 country="UK") == expected


def test_scoring_without_a_country_still_works():
    """The parameter is optional; callers that lack a country code (and every
    existing test) must keep the text-based behaviour."""
    assert score("Edinburgh") == 1.0
    assert score("Deutschland") == 0.20


def test_analyze_match_supplies_the_country(monkeypatch):
    """End to end: the country reaches location scoring, so a Karlsruhe posting is
    not scored as "location unknown"."""
    import matcher

    monkeypatch.setattr(matcher, "_load_persona_summary", lambda: "persona")
    monkeypatch.setattr(matcher, "_ollama_context_score",
                        lambda *a, **k: {"score": 0.5, "reasoning": "r",
                                         "reasoning_en": "r", "reasoning_ja": "",
                                         "provider": "test"})
    job = {
        "title": "Web Developer",
        "company": "Acme",
        "location": "Hagsfeld, Karlsruhe",
        "source_site": "Adzuna DE",
        "description": "Build responsive sites with JavaScript. " * 20,
        "analysis": {"skills": ["JavaScript"], "experience_level": "mid",
                     "employment_types": ["full_time"], "work_style": "onsite",
                     "salary": {"min": 40000, "max": 50000}},
    }
    out = matcher.analyze_match(job, {"min_salary_gbp": 26000}, skip_summary=True)
    assert out["location"]["score"] == 0.20
    assert "Germany" in out["location"]["notes"][0]
