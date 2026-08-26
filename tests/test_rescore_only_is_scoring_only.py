"""Re-scoring must not be able to rewrite an application document.

`run.py --reanalyze` is the obvious way to apply a scoring change to jobs
already on disk, and it runs the whole downstream pipeline: selecting jobs,
generating CVs and cover letters, reviewing them. Applying a scoring change
that way on 2026-08-26 queued 88 new document sets nobody had asked for, at two
LLM passes each, and stopping it partway left five CVs without their letters.

Existing documents were never at risk — run.py decides `want_cv = not
os.path.exists(cv_path)` before queueing — but a scoring pass should not be
writing documents at all.

rescore_only.py exists so that pass has a door that only does the one thing.
The point of these tests is that it STAYS that way: a later edit that imports a
generator into it would put the hazard straight back.
"""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCRIPT = ROOT / "rescore_only.py"
SOURCE = SCRIPT.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _imported_names() -> set[str]:
    names = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(a.name for a in node.names)
    return names


def test_it_exists():
    assert SCRIPT.exists()


@pytest.mark.parametrize("generator", [
    "cv_generator", "cover_letter_generator", "reviewer", "generate_cv",
    "save_cover_letter", "run_review", "generate_match_report",
])
def test_no_generator_is_reachable(generator):
    """Nothing that writes a document may be imported here."""
    assert generator not in _imported_names(), (
        f"rescore_only.py imports {generator} — a scoring pass can write documents again"
    )


def _code_strings() -> list[str]:
    """Every string constant the CODE uses, excluding docstrings.

    The prose in this file names the document directories on purpose — to say
    it does not go near them — so the check has to look at what the code does,
    not at what it says."""
    docstrings = set()
    for node in ast.walk(TREE):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    # Text handed to print() is a message to the reader, not a path — the
    # closing line tells you to run regen_match_reports.py next, and naming the
    # directory there is the point of saying it.
    printed = set()
    for node in ast.walk(TREE):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "print"):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    printed.add(sub.value)
    return [n.value for n in ast.walk(TREE)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value not in docstrings and n.value not in printed]


@pytest.mark.parametrize("directory", [
    "10_cvs", "10_cover-letters", "15_reviews", "00_matches", "20_pdfs",
])
def test_no_document_directory_is_reachable(directory):
    hits = [s for s in _code_strings() if directory in s]
    assert not hits, (
        f"rescore_only.py builds a path naming {directory}: {hits!r} — "
        "it is supposed to touch the database only"
    )


def test_it_scores_through_the_shared_path():
    """Not a private copy of the scoring loop — the same match_all everything
    else uses, so the filter-aware skip_llm_context applies here too."""
    assert "match_all" in _imported_names()


def test_the_database_is_backed_up_before_it_is_overwritten():
    assert "shutil" in _imported_names()
    assert "bak_pre_rescore" in SOURCE


def test_a_dry_run_is_available_and_writes_nothing():
    """The measurement that says how much a pass will cost has to be safe to
    run: 577 calls was worth knowing before spending it."""
    assert "--dry-run" in SOURCE
    dry = SOURCE[SOURCE.index("if args.dry_run:"):]
    body = dry[:dry.index("# Backed up because")]
    assert "write_text" not in body


def test_it_says_what_to_run_next():
    """A pass that leaves the reports stale without saying so is how the DB and
    what a human reads drifted apart before."""
    assert "regen_match_reports" in SOURCE
