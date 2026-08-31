"""A cut-off model reply must not reach the CV as a sentence that stops.

The failure does not look like a failure by the time the file is written. The
reply stops mid-bullet, the body comes out short, and _pad_experience_body then
appends whole entries rendered from source to fill the page — so the CV arrives
full-length, correctly formatted, and with one sentence in the middle that ends
after two words. It was found by a human reading a CV, which is the only place
it could have been found: 43 of the 1294 CVs on disk carry one.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv_generator as cg


# The exact shape observed in Wondrous_Creations_Web_Artist: the model's last
# entry stops mid-sentence, and everything after it is padding rendered from
# source, so nothing downstream sees a short body.
TRUNCATED = """**TAIFUNOME — Research & Creative Technology Platform | Independent Studio | 2026 – Present**
• Founded TAIFUNOME, an independent research-and-art platform, and designed it end to end — positioning, logo

**Portfolio Website Design & Development | Independent Studio | 2026 – Present**
• Designed and developed a personal website (kazukiyunome.com) unifying scattered profiles."""


def unfinished(body: str) -> list[str]:
    return [l.strip() for l in body.split("\n") if cg._bullet_is_unfinished(l)]


def test_every_source_bullet_ends_in_terminal_punctuation():
    """The premise the detector rests on. If a project file ever ships a bullet
    without it, the detector starts calling a real bullet truncated."""
    for project in cg.PROJECTS:
        for lang, key in (("en", "description"), ("ja", "description_ja")):
            for line in (project.get(key) or "").split("\n"):
                s = line.strip()
                if s.startswith("•"):
                    assert re.search(r'[.!?)\]”"。]\s*$', s), f"{project['id']} {lang}: {s[-40:]}"


def test_a_cut_off_bullet_is_restored_from_its_source():
    repaired = cg._repair_truncated_entries(TRUNCATED)
    assert unfinished(repaired) == []
    # restored, not deleted: the entry is still there and still first
    assert repaired.split("\n", 1)[0].startswith("**TAIFUNOME")
    assert len(cg._split_entries(repaired)) == 2


def test_the_restored_text_is_the_source_text():
    repaired = cg._repair_truncated_entries(TRUNCATED)
    entry = cg._split_entries(repaired)[0]
    project = cg._project_for_title("TAIFUNOME — Research & Creative Technology Platform")
    assert project is not None
    for line in (project["description"] or "").split("\n"):
        if line.strip().startswith("•"):
            assert line.strip() in entry


def test_a_complete_body_is_left_exactly_as_it_is():
    """The repair runs on every CV, so it has to be a no-op on the good ones."""
    for role in ("general", "web_developer", "platform_engineer"):
        body = cg._get_static_experience(role)
        assert cg._repair_truncated_entries(body) == body


def test_an_entry_naming_no_known_project_is_dropped_not_kept_broken():
    """There is nothing to restore it from, and _other_projects_line puts the
    project back on the breadth line either way — but a sentence that stops
    mid-word must not ship."""
    body = "**Some Project I Invented | Studio | 2026**\n• half a sentence that stops"
    assert cg._repair_truncated_entries(body) == ""


def test_a_heading_the_model_rewrote_still_resolves():
    """The model drops leading possessives as it reorders: "My Personal Identity
    Mark" comes back as "Personal Identity Mark"."""
    assert cg._project_for_title("Personal Identity Mark") is not None
    assert cg._project_for_title("My Personal Identity Mark") is not None
    assert cg._project_for_title("Something Entirely Unrelated") is None


@pytest.mark.parametrize("line,expected", [
    ("• A finished sentence.", False),
    ("• A finished sentence with a citation (2026)", False),
    ("• designed it end to end — positioning, logo", True),
    ("• evaluate urgency, importance, dependency, and", True),
    ("• Leveraged Illustrator, Affinity,", True),
    ("**A title line | Studio | 2026**", False),
    ("", False),
])
def test_the_detector_reads_the_end_of_the_line(line, expected):
    assert cg._bullet_is_unfinished(line) is expected


def test_the_repair_is_wired_into_the_english_body():
    """A fix that is written and never called is the same as no fix."""
    import inspect
    src = inspect.getsource(cg._experience_body)
    assert "_repair_truncated_entries" in src


# --- the CVs already on disk ----------------------------------------------

def test_no_unlocked_cv_still_carries_a_cut_off_bullet():
    """43 were repaired by repair_truncated_cvs.py. The four left are locked —
    `applied` means the file IS the record of what was submitted, and an expired
    posting's documents are frozen for the same reason nothing else rewrites
    them. Anything else appearing here is a CV written after the fix."""
    import gen_version
    cvs = ROOT / "10_output" / "10_cvs"
    matches = ROOT / "10_output" / "00_matches"
    if not cvs.exists():
        pytest.skip("no CV output tree")
    stray = []
    for path in sorted(cvs.glob("*_CV.md")):
        text = path.read_text(encoding="utf-8")
        section = re.search(r"## SELECTED PROJECTS\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
        if not section or not unfinished(section.group(1)):
            continue
        if gen_version.lock_reason(path.name[: -len("_CV.md")], text, matches):
            continue
        stray.append(path.name)
    assert not stray, f"{len(stray)} unlocked CV(s) with a cut-off bullet: {stray[:5]}"


def test_the_repair_leaves_a_healthy_cv_alone():
    import repair_truncated_cvs as rt
    cvs = ROOT / "10_output" / "10_cvs"
    if not cvs.exists():
        pytest.skip("no CV output tree")
    checked = 0
    for path in sorted(cvs.glob("*_CV.md"))[:40]:
        text = path.read_text(encoding="utf-8")
        section = re.search(r"## SELECTED PROJECTS\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
        if not section or unfinished(section.group(1)):
            continue
        assert rt.repair_text(text) is None, path.name
        checked += 1
    assert checked, "no healthy CV was available to check against"


def test_the_breadth_line_is_rebuilt_not_duplicated():
    """_finish_experience appends the "Other projects" line, so the existing one
    has to come off first — otherwise every repaired CV grows a second."""
    import repair_truncated_cvs as rt
    cv = ROOT / "10_output" / "10_cvs" / "Wondrous_Creations_Web_Artist__Web_Designer__Digital_Artist_CV.md"
    if not cv.exists():
        pytest.skip("sample CV not present")
    text = cv.read_text(encoding="utf-8")
    assert len(rt.OTHER_LINE.findall(text)) == 1
