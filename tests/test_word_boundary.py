"""Regression tests for the substring-matching bug found 2026-07-16:
keyword classifiers matched inside unrelated words ("lead" inside "Leading
video game company" -> senior; "intern" inside "internationally" ->
internship), silently misclassifying 124/305 experience levels and
192/305 employment types in production data.
"""
from analyzer import classify_experience_level, classify_employment_type


def test_lead_does_not_match_leading():
    level = classify_experience_level(
        "ML Engineer",
        "A leading video game company in Edinburgh is looking for an engineer.",
    )
    assert level != "senior"


def test_intern_does_not_match_internationally():
    types = classify_employment_type(
        "Full Stack Engineer as the business scales internationally and internally."
    )
    assert "internship" not in types


def test_experience_level_is_title_only():
    # Description-only trap phrases must NOT influence the result — this is
    # a deliberate design choice (user instruction), not just a boundary fix.
    level = classify_experience_level(
        "Junior Designer",
        "You will work closely with senior stakeholders and the leadership team.",
    )
    assert level == "entry_level"


def test_real_senior_title_still_matches():
    assert classify_experience_level("Senior Software Engineer", "") == "senior"


def test_real_internship_title_still_matches():
    assert classify_experience_level("Marketing Intern", "") == "internship"


def test_associate_is_entry_level():
    assert classify_experience_level("Associate Art Production Coordinator", "") == "entry_level"


def test_full_time_matches_whole_word_only():
    types = classify_employment_type("Full-time contract role, permanent position")
    assert "full_time" in types
    assert "contract" in types
