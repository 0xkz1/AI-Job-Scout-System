"""A skill the posting lists under "nice to have" is not a gap in the candidate.

The skill extractor returns one flat list and is drawn to concrete tool names —
which is exactly where a posting's OPTIONAL section lives. Moth's Creative
Technologist posting asks for three-to-five years of creative technology, an
audiovisual sensibility, familiarity with generative AI, a portfolio, and
"programming fluency in at least one language (Python, C++,
JavaScript/TypeScript)". The six skills extracted from it were Arduino,
Blender, C++, Python, Unity and Unreal Engine: four out of "What will set you
apart", plus the unchosen half of the one-language list. Scored as
requirements, a candidate who satisfies every stated requirement read as
holding one skill in six — 0.22, on the flagship target role.

Measured across the database: 301 postings change, every one upward, median
+0.11 and up to +0.54.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matcher  # noqa: E402


MOTH_SKILLS = ["Arduino", "Blender", "C++", "Python", "Unity", "Unreal Engine"]

MOTH_DESCRIPTION = """What we're looking for
3-5+ years' experience in creative technology, or a related role bridging
creative practice and computation.
Programming fluency in at least one language (Python, C++, JavaScript/TypeScript),
with the ability to work across multiple languages as needed.
Familiarity with generative AI and creative ML workflows.
A portfolio showcasing experimental, artistic, or interdisciplinary projects.
What will set you apart
Exposure to quantum computing frameworks (Qiskit, Cirq, PennyLane).
Experience with real-time or creative frameworks such as TouchDesigner, Unreal,
Unity, Blender, three.js, or generative AI/ML tooling.
Experience with audio/DSP, shader programming, or physical computing (Max/MSP,
Pure Data, Arduino, Raspberry Pi).
"""


@pytest.fixture
def skills():
    return matcher.load_user_skills()


def _unrequired(job_skills, description, skills):
    return matcher._unrequired_skills(job_skills, description, skills)


# --- the reported posting ---

def test_the_optional_section_is_recognised(skills):
    found = _unrequired(MOTH_SKILLS, MOTH_DESCRIPTION, skills)
    assert {"Arduino", "Unity", "Unreal Engine"} <= found


def test_the_unchosen_half_of_an_at_least_one_list_is_not_a_gap(skills):
    """"at least one language (Python, C++, JavaScript/TypeScript)" is ONE
    requirement. The candidate holds Python, so C++ is not an unmet anything."""
    assert "C++" in _unrequired(MOTH_SKILLS, MOTH_DESCRIPTION, skills)


def test_the_candidate_has_no_gaps_against_this_posting(skills):
    m = matcher.calculate_skill_match(MOTH_SKILLS, skills, "Creative Technologist",
                                      MOTH_DESCRIPTION)
    assert m["missing"] == [], \
        f"still reporting gaps against a posting whose requirements are met: {m['missing']}"
    assert "Python" in [x["skill"] for x in m["matched"]]


def test_the_score_rises_once_the_wishes_stop_counting(skills):
    with_rule = matcher.calculate_skill_match(MOTH_SKILLS, skills, "Creative Technologist",
                                              MOTH_DESCRIPTION)["score"]
    without = matcher.calculate_skill_match(MOTH_SKILLS, skills, "Creative Technologist",
                                            "")["score"]
    assert with_rule > without


# --- credit is not removed, only the penalty ---

def test_holding_a_nice_to_have_still_counts_for_you(skills):
    """Blender sits in the optional section and the candidate partly holds it.
    That is real credit and must survive — the rule only stops an ABSENCE
    counting as a gap."""
    m = matcher.calculate_skill_match(MOTH_SKILLS, skills, "Creative Technologist",
                                      MOTH_DESCRIPTION)
    held = [x["skill"] for x in m["matched"] + m["partial"]]
    assert "Blender" in held
    assert "Blender" not in m["unattributed"]


def test_an_unheld_optional_skill_is_reported_not_hidden(skills):
    m = matcher.calculate_skill_match(MOTH_SKILLS, skills, "Creative Technologist",
                                      MOTH_DESCRIPTION)
    assert {"Arduino", "Unity", "Unreal Engine"} <= set(m["unattributed"])


# --- it must not soften real requirements ---

def test_a_requirement_stated_before_the_optional_section_is_still_a_gap(skills):
    desc = ("What we need\nDeep experience with Kubernetes and Terraform.\n"
            "Nice to have\nExposure to Rust.\n")
    found = _unrequired(["Kubernetes", "Terraform", "Rust"], desc, skills)
    assert "Rust" in found
    assert "Kubernetes" not in found and "Terraform" not in found


def test_a_posting_with_no_optional_section_is_unchanged(skills):
    desc = "You will need strong Java and Azure experience across the stack."
    assert _unrequired(["Java", "Azure"], desc, skills) == set()


def test_an_or_list_the_candidate_cannot_satisfy_stays_a_gap(skills):
    """The list is only discharged by actually holding one of its members."""
    desc = "Fluency in at least one of Fortran, COBOL or Ada is required."
    assert _unrequired(["Fortran", "COBOL", "Ada"], desc, skills) == set()


def test_an_empty_description_changes_nothing(skills):
    assert _unrequired(MOTH_SKILLS, "", skills) == set()


def test_a_skill_named_in_both_sections_counts_as_required(skills):
    desc = ("Requirements\nStrong Python.\nNice to have\nMore Python, plus Rust.\n")
    found = _unrequired(["Python", "Rust"], desc, skills)
    assert "Python" not in found


# --- locating terms the extractor rewrote ---

def test_a_term_the_extractor_expanded_is_still_located():
    """The posting says "Unreal"; the LLM returned "Unreal Engine". A term that
    cannot be found cannot be placed in a section."""
    assert matcher._locate("Unreal Engine", "such as touchdesigner, unreal, unity")


def test_locating_respects_word_boundaries():
    assert matcher._locate("Unity", "work with our community every day") == []
