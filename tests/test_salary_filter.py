"""min_salary_gbp is annual, so a non-annual figure must be converted first.

Comparing raw values rejected every hourly posting outright: "£30 - £35 per hour"
read as "max salary £35 < £26000" and was dropped, though it annualises to about
£67k. 33 rows in the DB carried a max under 100, all hourly rates — and the filter
threw away the well-paid ones along with the rest.

The other half is that parse_salary tags anything without "hour" in the text as
annual, so a stray pair of numbers in a description becomes min=1.0/max=2.0.
Rejecting a job for a "£2 salary" is worse than not filtering it at all.
"""
import pytest
from filter import _HOURS_PER_YEAR, _annualise, passes_filter


@pytest.fixture
def config():
    return {
        "min_salary_gbp": 26000,
        "exclude_title_keywords": [],
        "exclude_description_keywords": [],
        "include_levels": [],
        "employment_types": [],
    }


def _job(salary_min, salary_max, period, title="Web Developer"):
    return {
        "title": title,
        "description": "A real job description. " * 20,
        "analysis": {"salary": {"min": salary_min, "max": salary_max, "period": period},
                     "experience_level": "mid", "employment_types": ["full_time"]},
    }


def test_hourly_rate_is_annualised_before_comparison(config):
    """£30/hour is roughly £58k — it must not be read as "£30 a year"."""
    ok, reason = passes_filter(_job(30, 35, "hourly"), config)
    assert ok, reason


def test_genuinely_low_hourly_rate_is_still_rejected(config):
    """The conversion must not become a blanket exemption for hourly work."""
    ok, reason = passes_filter(_job(8, 9, "hourly"), config)
    assert not ok
    assert "hourly" in reason and "/yr" in reason


def test_hourly_boundary_matches_the_conversion(config):
    """26000 / 1950 h = £13.33, so £13.50 passes and £13.00 does not."""
    assert passes_filter(_job(13, 13.5, "hourly"), config)[0]
    assert not passes_filter(_job(12, 13, "hourly"), config)[0]


def test_implausible_annual_figure_is_treated_as_no_data(config):
    """"Salary negotiable" parsed to min=1.0/max=2.0 on real postings. That is not a
    £2 salary, it is a failed parse, and must not reject the job."""
    ok, reason = passes_filter(_job(1.0, 2.0, "annual"), config)
    assert ok, reason


def test_low_but_plausible_annual_figure_is_still_rejected(config):
    ok, reason = passes_filter(_job(20000, 25000, "annual"), config)
    assert not ok and "25000" in reason


def test_annual_above_the_floor_passes(config):
    assert passes_filter(_job(35000, 45000, "annual"), config)[0]


def test_missing_salary_never_rejects(config):
    """No stated salary must not be read as a low one."""
    assert passes_filter(_job(None, None, None), config)[0]


def test_annualise_returns_none_rather_than_zero_for_untrusted_input():
    """None means "do not filter on this"; zero would mean "pays nothing"."""
    assert _annualise(None, "annual") is None
    assert _annualise(2.0, "annual") is None
    assert _annualise(30, "hourly") == pytest.approx(30 * _HOURS_PER_YEAR)
    assert _annualise(35000, "annual") == 35000


def test_period_is_named_in_the_rejection_reason(config):
    """A reason of "max salary £9 < £26000" is what made this bug invisible; the
    unit and the conversion have to be visible."""
    _ok, reason = passes_filter(_job(8, 9, "hourly"), config)
    assert "(hourly)" in reason
    assert "≈" in reason
