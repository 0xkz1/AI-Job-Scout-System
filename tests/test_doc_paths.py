"""Guards on directory listings, so a Syncthing conflict copy is never data.

The vault is a synced folder. When two devices touch a file between syncs,
Syncthing keeps the loser as `<stem>.sync-conflict-<date>-<device><suffix>` beside
the winner. Patterns that name a document kind survive that — `*_CV.md` does not
match `X_CV.sync-conflict-....md` — but `glob("*.md")` does not, and by
2026-09-04 twelve conflict copies had collected in the vault. Four sat in
10_output/00_matches, where check_expired.py spent a live HTTP request on each,
run.py counted them in its archive sweep, and the frontmatter stampers wrote
flags into files nothing would read again.
"""
import ast
import pathlib

import pytest

from doc_paths import is_conflict_copy, md_files

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def docs(tmp_path):
    (tmp_path / "b.md").write_text("live b", encoding="utf-8")
    (tmp_path / "a.md").write_text("live a", encoding="utf-8")
    (tmp_path / "a.sync-conflict-20260804-033938-3S5LBAJ.md").write_text(
        "the other device's a", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not markdown", encoding="utf-8")
    return tmp_path


def test_conflict_copies_are_not_listed(docs):
    assert [p.name for p in md_files(docs)] == ["a.md", "b.md"]


def test_listing_is_sorted(docs):
    """Several callers stamp or renumber in listing order. Leaving that to the
    filesystem makes the outcome depend on which machine ran it."""
    names = [p.name for p in md_files(docs)]
    assert names == sorted(names)


def test_a_missing_directory_is_empty_not_an_error(tmp_path):
    """A caller reading an output directory that has not been generated yet
    wants "nothing there", not a traceback."""
    assert md_files(tmp_path / "never_created") == []


def test_recursive_also_filters(docs):
    sub = docs / "nested"
    sub.mkdir()
    (sub / "c.md").write_text("live c", encoding="utf-8")
    (sub / "c.sync-conflict-20260805-061214-EUJRC47.md").write_text(
        "loser", encoding="utf-8")
    names = [p.name for p in md_files(docs, recursive=True)]
    assert "c.md" in names
    assert not any(is_conflict_copy(p) for p in md_files(docs, recursive=True))


def test_a_named_pattern_still_works(docs):
    (docs / "X_CV.md").write_text("cv", encoding="utf-8")
    assert [p.name for p in md_files(docs, "*_CV.md")] == ["X_CV.md"]


# ── the invariant, over the repository itself ───────────────────────────────
def _source_files():
    """Every module the pipeline runs. tests/ is excluded because a test may
    legitimately build a fixture listing; 00_saved is scraped staging, not code;
    .backup holds pre-refactor snapshots that are read by nobody."""
    skip = {"tests", "00_saved", ".backup", ".venv", "archive", "doc_paths.py"}
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if set(rel.parts) & skip or rel.name in skip:
            continue
        yield path


def test_no_module_globs_markdown_without_the_filter():
    """A new `glob("*.md")` is a new place a conflict copy becomes data.

    Parsed rather than grepped: the string appears in prose comments explaining
    this very rule, and a grep would have to be taught to ignore them.
    """
    offenders = []
    for path in _source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in ("glob", "rglob"):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            if node.args[0].value == "*.md":
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, (
        "these list markdown without filtering Syncthing conflict copies — "
        f"use doc_paths.md_files: {offenders}")
