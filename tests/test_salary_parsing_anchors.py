"""A salary the posting states plainly must not read as "not specified".

Every annual pattern used to require a trailing period word, so only
"£42,744 to £53,000 per annum" parsed. The two commonest UK phrasings did not:
a labelled range ("SALARY: £42,744 - £53,000", which is line one of Lloyds
Banking Group's Software Engineer posting) and a bare range in a structured
salary field ("£45,000 - £45,000").

Measured 2026-08-25: 523 postings stated a figure in their description and were
recorded as unspecified; 2150 of 2756 non-empty salary FIELDS parsed to nothing.

The reason it was left that way is real and must survive: in a seven-thousand
character description an unanchored figure is the referral bonus or the
relocation package. So the fix anchors on the posting's own label rather than
loosening the number, and the unanchored patterns stay field-only.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import analyzer  # noqa: E402


def field(text):
    return analyzer.parse_salary(text)


def prose(text):
    return analyzer.parse_salary(text, analyzer.DESCRIPTION_SALARY_PATTERNS)


# --- the reported posting ---

def test_the_lloyds_description_line_parses():
    r = prose("JOB TITLE: Software Engineer\n"
              "SALARY: £42,744 - £53,000\n"
              "LOCATION(S): Edinburgh\n")
    assert (r["min"], r["max"], r["period"]) == (42744.0, 53000.0, "annual")


# --- label-anchored, safe in prose ---

@pytest.mark.parametrize("text,expected", [
    ("SALARY: £42,744 - £53,000", (42744.0, 53000.0)),
    ("Salary range £40,000 to £50,000", (40000.0, 50000.0)),
    ("Starting salary of £30000 - £33000 with a yearly bonus of up to £1,530",
     (30000.0, 33000.0)),
    ("The salary is £50,000 per annum.", (50000.0, 50000.0)),
])
def test_a_labelled_figure_is_read_as_pay(text, expected):
    r = prose(text)
    assert (r["min"], r["max"]) == expected


def test_a_range_is_never_truncated_to_its_floor():
    """The single-figure pattern would match the same text and report only the
    first number, so the range has to be tried first."""
    r = prose("Salary: £40,000 - £55,000")
    assert r["max"] == 55000.0


@pytest.mark.parametrize("text", [
    "we offer a £1,500 salary sacrifice scheme and a Peloton discount",
    "refer a friend and earn £1,000\nrelocation package of £5,000",
    "Bonus of up to £1,530 paid yearly",
    "37.5 hours per week, 25 days holiday",
])
def test_prose_that_is_not_pay_still_parses_to_nothing(text):
    """The failure this guards against is documented: eight postings were
    filtered out on a referral bonus, one of them a Creative Technologist role
    rejected for a "£1,500 salary"."""
    r = prose(text)
    assert r["min"] is None and r["max"] is None


def test_a_label_cannot_reach_into_the_next_paragraph():
    r = prose("Salary\nThe referral scheme pays £1,000")
    assert r["min"] is None and r["max"] is None


def test_a_labelled_figure_too_small_to_be_a_year_is_rejected():
    r = prose("Salary: £9,500 for the placement year")
    assert r["min"] is None and r["max"] is None


# --- unanchored, salary field only ---

@pytest.mark.parametrize("text,expected", [
    ("£45,000 - £45,000", (45000.0, 45000.0)),
    ("£50,000 - £60,000", (50000.0, 60000.0)),
    ("£45,000", (45000.0, 45000.0)),
    ("£50,000 per annum", (50000.0, 50000.0)),
])
def test_a_bare_figure_in_the_salary_field_parses(text, expected):
    r = field(text)
    assert (r["min"], r["max"]) == expected


def test_the_bare_patterns_are_not_reachable_from_a_description():
    """This is the whole reason the two lists differ. A bare range in prose is
    as likely to be the relocation package as the pay."""
    assert prose("£45,000 - £55,000")["min"] is None
    assert field("£45,000 - £55,000")["min"] == 45000.0
    for pattern in analyzer._FIELD_ONLY:
        assert pattern not in analyzer.DESCRIPTION_SALARY_PATTERNS


def test_an_hourly_field_missing_its_period_word_stays_unparsed():
    """"£25 - £35" must not become a £25 salary — four digits minimum. Unparsed
    is the honest answer; a £25 annual salary would fail the min_salary filter
    and drop a job that pays roughly £50k."""
    r = field("£25 - £35")
    assert r["min"] is None and r["max"] is None


def test_a_day_rate_is_left_alone():
    r = field("£400 - £450 per day")
    assert r["min"] is None and r["max"] is None


def test_non_numeric_fields_are_still_nothing():
    for text in ("Competitive salary", "Salary negotiable", "Negotiable"):
        r = field(text)
        assert r["min"] is None and r["max"] is None


# --- nothing that already worked may change ---

@pytest.mark.parametrize("text,expected,period", [
    ("£40,000 - £55,000 per year", (40000.0, 55000.0), "annual"),
    ("£42,744 to £53,000 per annum", (42744.0, 53000.0), "annual"),
    ("£25 - £35 per hour", (25.0, 35.0), "hourly"),
])
def test_the_period_anchored_patterns_are_unchanged(text, expected, period):
    r = prose(text)
    assert (r["min"], r["max"], r["period"]) == (*expected, period)


def test_up_to_and_plus_still_work_in_a_field():
    assert field("Up to £60,000")["max"] == 60000.0
    assert field("£50,000+")["min"] == 50000.0


def test_an_hourly_range_is_not_relabelled_annual_by_prose():
    """"37.5 hours per week" three paragraphs away once turned 144 annual ranges
    hourly. The period comes from which pattern matched, not from the text."""
    r = prose("£40,000 - £55,000 per year. Our week is 37.5 hours per week.")
    assert r["period"] == "annual"
