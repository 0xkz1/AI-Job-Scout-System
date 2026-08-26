"""Two towns is two jobs, however identical the advert.

Duplicate merging groups on (company, title) and then requires the descriptions
to match at 0.9. A recruitment agency copy-pastes one advert across its patch,
so the text matches at ~1.0 while the postings are separate vacancies a
candidate would apply to separately — and the location, the only thing that
tells them apart, was never consulted.

Measured 2026-08-26 over the 5260-job database: of 533 merges, 130 joined
postings in DIFFERENT towns, and every one came through the similarity test
rather than the missing-description path. IT Talent Solutions' Web Developer in
Caversham swallowed Hadleigh and Basildon; CITRUS CONNECT's Sales Designer in
Cardiff took Newport, Liverpool and East London.

The guard has to stay hard to satisfy, because the SAME vacancy is written
differently by every board — "London, England, United Kingdom", "LONDON, UK,",
"Newington, South East London" all name one place.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import run  # noqa: E402


AD = ("We are recruiting a Web Developer for a growing consultancy. You will "
      "build and maintain client sites, work with the design team, and support "
      "releases. Competitive package and excellent progression. " * 6)


def _job(location, **over):
    j = {"company": "IT Talent Solutions", "title": "Web Developer",
         "location": location, "description": AD, "source": "adzuna",
         "url": f"https://www.adzuna.co.uk/jobs/details/{abs(hash(location)) % 10**7}"}
    j.update(over)
    return j


# --- the reported case ---

def test_one_advert_in_two_towns_is_two_postings():
    assert not run._same_posting(_job("Caversham, Reading"), _job("Hadleigh, Benfleet"))


def test_the_agency_postings_all_survive():
    towns = ["Caversham, Reading", "Hadleigh, Benfleet", "BASILDON, ESSEX, SS13"]
    kept, archived = run.dedupe_by_company_title([_job(t) for t in towns])
    assert len(kept) == 3
    assert archived == []


def test_every_merge_still_joins_a_place_it_could_share():
    """The invariant the fix buys: nothing is archived into a posting that names
    a town it cannot be in."""
    towns = ["Grangetown, Cardiff", "Bettws, Newport", "Low Hill, Liverpool",
             "Wapping, East London", "Grangetown, Cardiff"]
    kept, archived = run.dedupe_by_company_title([_job(t) for t in towns])
    for a in archived:
        assert any(not run._different_place(a, k) for k in kept)


# --- one vacancy, many spellings, must still merge ---

@pytest.mark.parametrize("pair", [
    ("London, England, United Kingdom", "LONDON, UK,"),
    ("London, England, United Kingdom", "Newington, South East London"),
    ("Greater London Area", "London"),
    ("Edinburgh, Scotland, United Kingdom", "Edinburgh"),
])
def test_the_same_place_written_differently_still_matches(pair):
    a, b = pair
    assert not run._different_place(_job(a), _job(b))
    assert run._same_posting(_job(a), _job(b))


@pytest.mark.parametrize("pair", [
    ("United Kingdom", "UK"),
    ("Remote", "Remote, UK"),
    ("", "Edinburgh"),
    ("UK", ""),
])
def test_a_location_naming_no_town_is_not_a_disagreement(pair):
    """A country, a work style or a blank is not evidence of a different place,
    and reading it as one would stop a genuine cross-board duplicate merging."""
    a, b = pair
    assert not run._different_place(_job(a), _job(b))


# --- the rest of the rule is untouched ---

def test_different_descriptions_in_one_town_are_still_two_postings():
    a = _job("Edinburgh")
    b = _job("Edinburgh", description="An entirely different role about pipework welding. " * 20)
    assert not run._same_posting(a, b)


def test_a_missing_description_in_the_same_town_still_counts_as_a_duplicate():
    a = _job("Edinburgh")
    b = _job("Edinburgh", description="short")
    assert run._same_posting(a, b)


def test_a_missing_description_does_not_override_a_different_town():
    """The weakest evidence must not beat the strongest: an absent description
    cannot prove that Cardiff and Newport are the same vacancy."""
    a = _job("Grangetown, Cardiff", description="short")
    b = _job("Bettws, Newport")
    assert not run._same_posting(a, b)
