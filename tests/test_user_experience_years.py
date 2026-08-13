"""Years of experience must come from the profile's own list, not from prose.

load_user_experience used to read about.md and key on the literal string
"Feral", inferring Python/Linux/automation years from a creative project's date
range — its own comment ended in a question mark. On 2026-08-13 a heading was
reworded (`### "Feral" — Narrative World Development (2023 – Present)` became
`### TAIFUNOME — Independent Studio (2023 – Present)`, with Feral demoted to a
bullet), the regex's `.` did not cross the newline, and years_python,
years_linux and years_automation all silently became 0. user_estimated_years
halved from 4 to 2 and 1,547 jobs were matched on it before anyone noticed,
because a wrong number looks exactly like a right one.

timeline.md states these facts outright under "Skills Acquisition Timeline" and
always did.

The second thing under test is the distinction that keeps the CV honest: a
calendar span is not professional experience. timeline.md says Python since
2019 AND "roughly 4 years of paid work between Jul 2019 and Jul 2023". Scoring
against the span would claim 8 years where the document says 4.
"""
import matcher
import pytest


@pytest.fixture
def profile(tmp_path, monkeypatch):
    def write(timeline_text: str):
        (tmp_path / "timeline.md").write_text(timeline_text, encoding="utf-8")
        monkeypatch.setattr(matcher, "USER_PROFILE_DIR", tmp_path)
        return matcher.load_user_experience()
    return write


SKILLS = """# Timeline

## Skills Acquisition Timeline

- **Python/Linux/Automation:** 2019–present (self-taught through projects)
- **AI/ML:** 2022–present (ComfyUI, Stable Diffusion, Ollama)
- **Photography:** 2020–present (architectural, interior)
- **Web Dev:** 2019–present (vanilla JS, TypeScript)
"""


def test_one_label_can_carry_several_skills(profile):
    """"Python/Linux/Automation" is a single bullet naming three things."""
    exp = profile(SKILLS)
    assert exp["years_python"] > 0
    assert exp["years_linux"] == exp["years_python"]
    assert exp["years_automation"] == exp["years_python"]


def test_a_span_is_measured_to_the_current_year(profile):
    import datetime
    exp = profile(SKILLS)
    assert exp["years_python"] == datetime.datetime.now().year - 2019 + 1


def test_a_closed_span_ends_where_it_says(profile):
    exp = profile("## Skills Acquisition Timeline\n\n- **Python:** 2019–2023 (contract work)\n")
    assert exp["years_python"] == 5


def test_paid_work_is_read_separately_from_the_span(profile):
    """The profile qualifies its own dates; the qualification has to survive."""
    exp = profile(SKILLS + "\n- Freelance programming, worked in stretches rather than "
                           "continuously — roughly 4 years of paid work between Jul 2019 "
                           "and Jul 2023.\n")
    assert exp["years_professional"] == 4
    assert exp["years_python"] > 4, "the calendar span should be longer than the paid years"


def test_the_score_uses_paid_years_not_the_calendar_span(profile):
    """A posting asking for "5+ years" means paid work. Scoring the span would
    claim 8 where the profile says 4 — the same overstatement as listing an
    unfinished logo as delivered."""
    exp = profile(SKILLS + "\n- roughly 4 years of paid work between Jul 2019 and Jul 2023.\n")
    result = matcher.calculate_experience_match("senior", exp)
    assert result["user_estimated_years"] == 4
    assert "4 years" in result["note"]


def test_without_a_paid_work_statement_it_falls_back_to_the_longest_span(profile):
    exp = profile(SKILLS)
    result = matcher.calculate_experience_match("mid", exp)
    assert result["user_estimated_years"] == exp["years_python"]


def test_overlapping_spans_are_not_summed(profile):
    """Python 2019 and Web Dev 2019 are the same years, not twice as many."""
    exp = profile(SKILLS)
    result = matcher.calculate_experience_match("mid", exp)
    assert result["user_estimated_years"] == exp["years_python"]


def test_a_missing_timeline_returns_zeros_rather_than_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(matcher, "USER_PROFILE_DIR", tmp_path)
    exp = matcher.load_user_experience()
    assert exp["years_python"] == 0
    assert exp["years_professional"] == 0


def test_the_live_profile_reports_nonzero_years():
    """The regression itself: a real profile that parses to 0 is the bug."""
    exp = matcher.load_user_experience()
    assert exp["years_python"] > 0, (
        "timeline.md parsed to 0 years of Python — the profile parser has lost "
        "its source again"
    )
    assert exp["years_professional"] > 0
