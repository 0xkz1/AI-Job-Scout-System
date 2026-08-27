"""The digest reports what the reviewers keep saying. It must not act on it.

Aggregating a thousand reviews is safe and useful; applying their rewrites is
neither. Measured 2026-08-27 over 1065 CV reviews: the reviewers agree readily
on WHICH sentence is a problem — one is flagged 68 times — and hardly ever on
the replacement. Those 68 flags proposed 55 distinct rewrites, the most popular
appearing 3 times, so a majority rule fires on the complaint and picks noise on
the fix. A second group, flagged 41 times, is not in any authored file at all
and could not be edited even if the rewrites agreed.

These tests exist so a later "while we're here, just apply the obvious ones"
cannot land quietly.
"""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCRIPT = ROOT / "review_feedback_digest.py"
SOURCE = SCRIPT.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)

import review_feedback_digest as digest  # noqa: E402


# --- it writes exactly one file, and that file is the digest ---

def test_only_one_write_call_exists():
    writes = [n for n in ast.walk(TREE)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr in ("write_text", "write_bytes", "writelines", "write")]
    assert len(writes) == 1, (
        f"{len(writes)} write calls — the digest is supposed to produce one report "
        "and change nothing else"
    )


def test_nothing_that_edits_a_document_is_imported():
    names = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(a.name for a in node.names)
    for writer in ("cv_generator", "cover_letter_generator", "generate_cv",
                   "save_cover_letter", "reviewer", "shutil"):
        assert writer not in names, f"the digest imports {writer}"


def test_the_authored_directories_are_only_ever_read():
    """SOURCE_DIRS is where the CV actually comes from. The script locates
    sentences in it; it must never open one for writing."""
    for d in digest.SOURCE_DIRS:
        assert "w" not in str(d)  # cheap guard against a path being reused as a mode
    opened = [n for n in ast.walk(TREE)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open"]
    assert not opened, "uses open() — read authored files through read_text only"


# --- locating a sentence ---

def test_a_sentence_from_an_authored_file_is_located(tmp_path):
    f = tmp_path / "profile.md"
    f.write_text("intro line\nProduct designer with a systems-level approach to UX and UI.\n",
                 encoding="utf-8")
    index = [(f, 2, "Product designer with a systems-level approach to UX and UI.")]
    assert digest._locate("Product designer with a systems-level approach to UX and UI.", index)


def test_an_llm_written_span_is_reported_as_unlocatable():
    """The tailored opening of a cover letter is written per job and is in no
    file — saying so is the useful answer, not leaving the reader to search."""
    index = [(Path("x.md"), 1, "something entirely different")]
    assert digest._locate("A sentence the model wrote for one posting only.", index) is None


def test_a_fragment_too_short_to_identify_matches_nothing():
    index = [(Path("x.md"), 1, "designer")]
    assert digest._locate("designer", index) is None


# --- the numbers that make the output honest ---

def test_the_report_states_how_much_the_rewrites_agree():
    assert "修正案の一致" in SOURCE, (
        "without the agreement figure a 68-flag group reads as a verdict when its "
        "rewrites are 55-way split"
    )


def test_the_report_states_which_roles_raised_it():
    """A group raised almost entirely by one discipline is that discipline
    asking for tailoring, not a defect in the source."""
    assert "flagged by roles" in SOURCE


def test_the_report_says_nothing_was_applied():
    assert "Nothing below has been applied" in SOURCE
