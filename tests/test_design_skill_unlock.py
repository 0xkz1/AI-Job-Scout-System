"""A bare "Design" requirement is only the candidate's design when the job is one.

"Design"/"Designer" with nothing beside it is discipline-ambiguous — it covers
gas mains and automotive CAD as readily as UI work — so matcher demotes it
unless the job shows digital-design context. That demotion had a second way to
be switched off: role affinity. `web_developer`'s keyword list, shared with CV
routing, contains "software engineer", and a title keyword counts double, so
every posting titled "Software Engineer" cleared the bar on its title alone and
handed its bare "Design" requirement the candidate's 90% design skill.

Lloyds Banking Group's insider-risk engineering role scored skills 0.66 that
way, matching Agile, Design, Git, Kanban, Kubernetes, React and Scrum while
missing Azure and Java — the only two terms that describe the actual job.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matcher  # noqa: E402
from cv_generator import ROLE_KEYWORDS  # noqa: E402


LLOYDS = ["Agile", "Azure", "Design", "Docker", "Git", "Java",
          "Kanban", "Kubernetes", "React", "Scrum"]


@pytest.fixture
def skills():
    return matcher.load_user_skills()


def _match(job_skills, title="", description="", skills=None):
    return matcher.calculate_skill_match(job_skills, skills, title, description)


# --- the reported job ---

def test_a_backend_job_does_not_borrow_the_candidates_design_skill(skills):
    m = _match(LLOYDS, "Software Engineer", "insider risk detection tooling", skills)
    assert "Design" not in [x["skill"] for x in m["matched"]], \
        "a bare Design requirement still counts as matched in a security engineering role"
    assert "Design" in m["unattributed"]


def test_an_unreadable_design_term_is_not_recorded_as_a_gap(skills):
    """Calling it missing asserts two things, and the second is false: that the
    job requires design, and that the candidate does not have it. They are a
    designer. The term is dropped from the denominator instead — the same
    treatment _is_non_skill and the LLM's "not_a_skill" verdict already get."""
    m = _match(LLOYDS, "Software Engineer", "", skills)
    assert "Design" not in m["missing"]
    assert m["missing"] == ["Azure", "Java"]


def test_dropping_it_scores_higher_than_calling_it_a_gap(skills):
    """Measured: of 885 postings carrying an unreadable design term, 94 score
    higher for it not being counted against them."""
    dropped = _match(["Design", "Java", "Azure"], "Software Engineer", "", skills)["score"]
    as_gap = _match(["Nuclear Decommissioning", "Java", "Azure"], "Software Engineer", "",
                    skills)["score"]
    assert dropped >= as_gap


def test_the_word_is_reported_rather_than_vanishing(skills):
    """A requirement the posting names, scored as neither, has to be visible
    somewhere or it reads as a bug."""
    m = _match(LLOYDS, "Software Engineer", "", skills)
    named = ([x["skill"] for x in m["matched"]] + [x["skill"] for x in m["partial"]]
             + m["missing"] + m["unattributed"])
    assert set(named) == set(LLOYDS)


def test_the_specific_terms_are_the_ones_it_misses(skills):
    """The complaint in one line: everything generic matched, everything that
    names the job did not."""
    m = _match(LLOYDS, "Software Engineer", "", skills)
    assert {"Azure", "Java"} <= set(m["missing"])


# --- the mechanism ---

def test_a_software_engineer_title_no_longer_grants_design_context():
    """It used to reach the threshold on the title alone, twice over."""
    assert matcher._digital_role_affinity("Software Engineer", [], "") \
        < matcher._DIGITAL_ROLE_MIN_AFFINITY


@pytest.mark.parametrize("title", [
    "Software Engineer", "Frontend Engineer", "Backend Engineer",
    "Full Stack Developer", "Python Developer",
])
def test_no_engineering_title_alone_grants_design_context(title):
    assert matcher._digital_role_affinity(title, [], "") \
        < matcher._DIGITAL_ROLE_MIN_AFFINITY


def test_the_role_set_holds_only_design_disciplines():
    """web_developer is the one that broke this: its keywords are shared with CV
    routing and cannot be narrowed there without changing which CV is written."""
    assert "web_developer" not in matcher._DIGITAL_ROLE_SET
    assert "software engineer" in ROLE_KEYWORDS["web_developer"], \
        "the keyword this guards against is gone — re-check whether the exclusion is still needed"


# --- what must still work ---

@pytest.mark.parametrize("title", [
    "Visual Designer", "Interaction Designer", "Motion Designer",
    "Graphic Designer", "UX Designer", "Product Designer", "Digital Designer",
    "Technical Artist", "Creative Technologist", "Midweight Designer",
])
def test_a_real_design_title_still_grants_design_context(title):
    """Several of these score EXACTLY 2.0 from the title, which is why the
    threshold was not raised instead — that fix would have dropped them."""
    assert matcher._digital_role_affinity(title, [], "") \
        >= matcher._DIGITAL_ROLE_MIN_AFFINITY


def test_a_design_title_keeps_its_bare_design_skill(skills):
    m = _match(["Design", "Adobe Creative Suite", "Typography"], "Graphic Designer", "", skills)
    assert "Design" not in m["missing"]


def test_a_web_job_that_names_its_design_work_is_unaffected(skills):
    """Removing web_developer costs nothing when the job's own skill list says
    the work is visual — _has_digital_design_context sees that directly."""
    web = ["Design", "HTML", "CSS", "JavaScript"]
    assert matcher._has_digital_design_context(web)
    m = _match(web, "Web Developer", "", skills)
    assert "Design" not in m["missing"]


def test_a_dotnet_web_job_that_does_not_is_demoted(skills):
    """The measured cost of the change, stated on purpose: "design" in a posting
    whose skills are C# and Elasticsearch means software design."""
    backend = ["Design", ".Net", "C#", "Elasticsearch"]
    assert not matcher._has_digital_design_context(backend)
    m = _match(backend, "Senior Web Developer - Tools", "", skills)
    assert "Design" in m["unattributed"]


def test_the_physical_design_case_that_started_all_this(skills):
    """A Gas Designer posting once scored 0.64 on skills alone."""
    m = _match(["Design", "CAD", "AutoCAD", "Pipework"], "Gas Designer", "", skills)
    assert "Design" in m["unattributed"]
    assert m["score"] == 0.0, "the 0.64 this guard exists to prevent is back"
