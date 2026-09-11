"""A generated document must be reachable from its match report.

The fault, measured 2026-09-11: run.py derives a report's cv:/cover_letter:
links from what is on disk, but that check runs before the expensive half
writes the files. So every job receiving its FIRST documents got a report that
predated them — 16 of 16 in one run, SmartPA's among them.

It survived because it is silent. The report is present and reads correctly on
its own; only the CV/CL columns and the apply_priority formula in the Obsidian
Bases come out blank, and the 🎯 優先度 view, which filters on cv_review_score
existing, drops the job from the table altogether. The run printed "Saved 3977
match reports" and "Saved 16 tailored CVs" and nothing said the two had not
been joined up.

Two hand-run repair scripts existed for exactly this — patch_report_doc_links
and patch_review_scores — and were called by nothing. The data was fixed
repeatedly while the generator kept reproducing the fault. That is the pattern
these tests are here to break.
"""
import pathlib

import invariants as inv


def _tree(tmp_path, *, cv=False, cl=False, links=()):
    out = tmp_path / "10_output"
    (out / "00_matches").mkdir(parents=True)
    (out / "10_cvs").mkdir(parents=True)
    (out / "10_cover-letters").mkdir(parents=True)

    stem = "Acme_Product_Designer"
    fm = ['match_score_pct: 71', 'company: "Acme"', 'title: "Product Designer"',
          'url: "https://example.invalid/job/1"']
    fm += list(links)
    (out / "00_matches" / f"{stem}.md").write_text(
        "---\n" + "\n".join(fm) + "\n---\n\n# Acme\n", encoding="utf-8")
    if cv:
        (out / "10_cvs" / f"{stem}_CV.md").write_text("# CV", encoding="utf-8")
    if cl:
        (out / "10_cover-letters" / f"{stem}_CL.md").write_text("# CL", encoding="utf-8")
    return out, stem


def test_a_cv_on_disk_with_no_link_is_a_violation(tmp_path, monkeypatch):
    out, stem = _tree(tmp_path, cv=True, cl=True)
    monkeypatch.setattr(inv, "OUTPUT", out)

    found = inv.check_reports_link_their_documents({})
    assert len(found) == 1
    assert stem in found[0]
    assert "cv" in found[0] and "cover_letter" in found[0]
    # The message has to say what to run, or it is another silent finding.
    assert "patch_report_doc_links.py --apply" in found[0]


def test_a_linked_report_is_clean(tmp_path, monkeypatch):
    out, stem = _tree(tmp_path, cv=True, cl=True, links=(
        f'cv: "[[{ "Acme_Product_Designer" }_CV]]"',
        f'cover_letter: "[[Acme_Product_Designer_CL]]"',
    ))
    monkeypatch.setattr(inv, "OUTPUT", out)
    assert inv.check_reports_link_their_documents({}) == []


def test_a_report_with_no_documents_is_not_a_violation(tmp_path, monkeypatch):
    """Most jobs never earn documents — they are below the generation cutoff.
    Flagging those would bury the real finding under thousands of rows."""
    out, _ = _tree(tmp_path)
    monkeypatch.setattr(inv, "OUTPUT", out)
    assert inv.check_reports_link_their_documents({}) == []


def test_only_the_document_that_exists_is_demanded(tmp_path, monkeypatch):
    """A CV without a cover letter is a real state — the letter assembler
    refuses rather than emit one missing its identity block. Demanding both
    would turn that into a permanent false violation."""
    out, stem = _tree(tmp_path, cv=True, links=(
        'cv: "[[Acme_Product_Designer_CV]]"',
    ))
    monkeypatch.setattr(inv, "OUTPUT", out)
    assert inv.check_reports_link_their_documents({}) == []


def test_the_check_is_registered():
    """An invariant nothing runs is the shape of bug it exists to catch."""
    assert inv.check_reports_link_their_documents in inv.CHECKS


def test_the_chain_runs_the_invariants():
    """Until 2026-09-11 only nightly_scout did, so the WebUI button — which is
    how the URL-list route is actually driven — checked nothing it wrote."""
    root = pathlib.Path(inv.__file__).resolve().parent
    chain = (root / "run_saved_chain.py").read_text(encoding="utf-8")
    assert "from invariants import report" in chain, (
        "run_saved_chain no longer runs the integrity checks"
    )


def test_run_py_refinishes_reports_after_generating_documents():
    """The ordering fix itself. The links are derived before the expensive half
    writes the files, so the reports have to be revisited after it."""
    root = pathlib.Path(inv.__file__).resolve().parent
    src = (root / "run.py").read_text(encoding="utf-8")
    assert "from patch_report_doc_links import patch" in src, (
        "run.py no longer re-links the reports for documents it just wrote"
    )
    assert "from patch_review_scores import patch" in src, (
        "run.py no longer back-fills review scores for documents it just wrote"
    )
    # After the generation block, not before it — the whole point.
    assert src.index("_write_documents") < src.index("from patch_report_doc_links import patch")
