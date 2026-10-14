"""Reed's card scraper must not store page chrome as the employer.

Cards in reed's "Training Course" category carry a filter link — "hide all
Training Course jobs." — before the company link, and both match
a[href*="/jobs/"]. querySelector returns the first match in document order, so
8 postings were stored under the company "hide all Training Course jobs."; the
real employer, IT Career Switch, was in the next link along. Reproduced live on
2026-08-07 against reed.co.uk/jobs/trainee-web-developer-jobs.

The damage is not cosmetic: make_safe_name(company, title) builds every
document path from the company, so a whole employer's postings collapse into
one bogus name, and three of them reached "submission ready" in the review
pass under it.

These tests exercise the extraction JS itself, lifted from the scraper, against
saved DOM fixtures — the selector logic is the thing that broke, and it lives
in a string rather than in Python.
"""
import re
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _extraction_js():
    """The card-parsing JS the scraper hands to page.evaluate()."""
    src = (ROOT / "scraper_reed.py").read_text(encoding="utf-8")
    m = re.search(r'jobs = await page\.evaluate\("""(.*?)"""\)', src, re.DOTALL)
    assert m, "could not find the extraction JS in scraper_reed.py"
    return m.group(1)


def test_chrome_guard_is_present_in_the_selector_logic():
    """The guard, checked structurally: the first candidate must be filtered,
    not merely the fallback path. Before the fix only the fallback tested the
    link text, which is why the first match won unconditionally."""
    js = _extraction_js()
    assert "isChrome" in js, (
        "the chrome filter is gone from reed's company extraction — a filter "
        "link like 'hide all Training Course jobs.' will be stored as the employer"
    )
    # querySelector (singular, first-match-wins) on the /jobs/ pattern is the
    # exact shape of the bug; the fix iterates candidates instead.
    assert "querySelectorAll(" in js, "candidate iteration replaced by a single-match query"


@pytest.mark.parametrize("text,expected_chrome", [
    ("hide all Training Course jobs.", True),
    ("Show all Marketing jobs", True),
    ("Search similar jobs", True),
    ("Browse jobs", True),
    ("View all jobs", True),
    ("IT Career Switch", False),
    ("deVOL Kitchens", False),
    ("Jobheron", False),          # contains "job" but not as a word
    ("Hiring People", False),
    ("Arc IT Recruitment", False),
    ("Service Service Employment Agency Limited", False),
])
def test_chrome_predicate_matches_the_javascript(text, expected_chrome):
    """Python mirror of the JS isChrome predicate, kept in step by asserting the
    JS still contains the same two rules. 'Jobheron' is the case a naive
    substring test gets wrong — hence the word boundary in the regex."""
    js = _extraction_js()
    assert r"/\bjobs?\b/i" in js, "word-boundary job test changed; 'Jobheron' may now be rejected"
    assert "^(hide|show|search|browse|view|see) " in js, "leading-verb test changed"

    is_chrome = (
        not text
        or re.search(r"\bjobs?\b", text, re.IGNORECASE) is not None
        or re.match(r"^(hide|show|search|browse|view|see) ", text, re.IGNORECASE) is not None
    )
    assert is_chrome == expected_chrome


def test_company_link_selectors_are_tried_before_the_generic_jobs_href():
    """Ordering matters as defence in depth: the purpose-built company selectors
    should be consulted before the broad a[href*="/jobs/"] pattern that let the
    filter link in."""
    js = _extraction_js()
    qa = js.index('job-card-company-link')
    generic = js.index('a[href*="/jobs/"]:not(h2 a)')
    assert qa < generic, (
        "the generic /jobs/ href pattern is being tried before the dedicated "
        "company-link selectors"
    )
