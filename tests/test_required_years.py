"""The years a posting demands of the candidate — and whose years they are not.

classify_experience_level reads the title only, so most postings ("UX/UI
designer") name no level and fall through to an LLM guess. Measured on the
corpus, 18% of the postings that state a years figure state one outside the
band their title-derived level implies, and 17% of postings the title calls
"mid" pay above the median senior salary. The number the employer wrote is a
better-grounded signal than a model's reading — but only if it is the
candidate's number.

A bare \\d+ years regex mostly picks up the company bragging about itself. The
exclusions here were written against 400 sampled postings, and every case below
is a real string from the corpus.
"""
import analyzer
import pytest


def _level(text):
    stated = analyzer.required_years(text)
    return analyzer.level_from_years(*stated) if stated else None


@pytest.mark.parametrize("text,expected_years", [
    ("Requirements: 5+ years' experience in graphic design.", 5),
    ("Skills And Experience Required 1+ years of design experience", 1),
    ("Experience Required A minimum of 3 years + of experience within a broker", 3),
    ("We're looking for someone who has: 3-5 years' Product Design experience.", 3),
    ("Qualifications: Minimum 5 years of experience in Identity and Access Management.", 5),
    ("understanding of costs will come from a min of 7years high end AV integration", 7),
])
def test_a_stated_requirement_is_read(text, expected_years):
    stated = analyzer.required_years(text)
    assert stated is not None, "a plainly stated requirement was missed"
    assert stated[0] == expected_years


@pytest.mark.parametrize("text,why", [
    ("For over 25 years, Turnitin has partnered with educators. Requirements: portfolio.",
     "the company's age"),
    ("Backed by a recruitment group with 20 years experience. Requirements: portfolio.",
     "the parent company's age"),
    ("Be mentored by a hands-on manager with 20+ years of industry experience. Requirements: drive.",
     "the manager's experience"),
    ("Founded in 2023 by a family with over 40 years of combined experience. Requirements: CV.",
     "combined experience of the founders"),
    ("A People Advisor on a 2-year Fixed Term Contract. Requirements: CIPD.",
     "the contract length"),
    ("Applicant must have resided continuously within the UK for the last 5 years. Requirements: SC.",
     "a residency rule"),
    ("Must have shipped meaningful design work in the last 2 years. Requirements: portfolio.",
     "a recency window, not a floor"),
])
def test_years_that_belong_to_someone_else_are_ignored(text, why):
    assert analyzer.required_years(text) is None, f"read {why} as a requirement"


@pytest.mark.parametrize("text", [
    "Junior Design Engineer - You should have no more than 2 years of industry experience.",
    "Those still early in their careers (&lt;4 years) and recent grads. Requirements: portfolio.",
])
def test_a_ceiling_is_a_junior_posting_not_a_senior_one(text):
    """"no more than 2 years" is the posting turning experience away. Read as a
    floor it says mid, which is the opposite of what it means."""
    stated = analyzer.required_years(text)
    assert stated is not None and stated[1] is True
    assert _level(text) == "entry_level"


def test_a_ceiling_outvotes_a_floor_elsewhere_in_the_same_posting():
    """A junior posting still carries ordinary requirement phrasing further
    down, which would otherwise win on the max()."""
    text = ("Junior Design Engineer. You should have no more than 2 years of industry "
            "experience. Requirements: a degree, and at least 5 years using Adobe tools.")
    assert _level(text) == "entry_level"


@pytest.mark.parametrize("years,expected", [
    (1, "entry_level"), (2, "mid"), (4, "mid"), (5, "senior"), (10, "senior"),
])
def test_bands_match_what_the_salaries_say(years, expected):
    """Not guessed. Median advertised salary by stated years, over the 94
    postings carrying both: 1y £28,375 / 2y £37,500 / 3y £39,500 / 5y £56,500 /
    10y £72,500, against £32,500 for titles that say junior and £60,000 for
    titles that say senior."""
    assert analyzer.level_from_years(years) == expected


def test_the_scan_is_not_quadratic():
    """The first version put \\s* between optional groups four times over, so
    the engine had many ways to split the same run of spaces and backtracked
    through all of them — 116ms per posting, about six minutes over the corpus.
    """
    import time
    text = ("Requirements and experience: " + "lorem ipsum 1234 " * 400
            + " 5+ years of design experience")
    start = time.perf_counter()
    analyzer.required_years(text)
    assert time.perf_counter() - start < 0.05


def test_the_level_filter_is_not_gated_on_this_yet():
    """Deliberate: required_years is recorded as evidence but must not move
    experience_level, because include_levels is [entry_level, mid, internship]
    and 45 postings — including one already applied to — stop passing the
    filter the moment it does. It is as accurate as the LLM classifier, not
    better (95% CI on the difference [-0.067, +0.183]), so that is not a trade
    worth making silently."""
    text = ("Web developer. We are looking for a developer to join us. "
            "Requirements: 5+ years of commercial experience with React.")
    assert analyzer.required_years(text) == (5, False)
    assert analyzer.classify_experience_level("Web developer", text) == "unknown"
