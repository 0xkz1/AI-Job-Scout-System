"""A report that carries a review score must link the document it reviewed.

regen_match_reports.py rewrites 00_matches from the DB and carries the
non-score frontmatter forward off the file it is about to overwrite — cv,
cover_letter, route, saved_at, expired, applied. That is right for everything
that only lives in the file. It is wrong for the document links, because
nothing ever puts one there after the fact: a CV written AFTER its match report
was last rendered stays invisible in the only file a human reads, and no rerun
repairs it, because the rerun reads the same empty field it wrote.

Measured 2026-08-27: 69 reports had a CV on disk and no link to it, 70 had a
cover letter. Lothian Buses' Junior Digital Designer showed `cv_review_score:
58` above no CV link at all — a review score for a document the report did not
admit existed.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import regen_match_reports as rmr  # noqa: E402


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    cv, cl = tmp_path / "cvs", tmp_path / "cls"
    cv.mkdir()
    cl.mkdir()
    monkeypatch.setattr(rmr, "CV_DIR", cv)
    monkeypatch.setattr(rmr, "CL_DIR", cl)
    return cv, cl


def test_a_cv_on_disk_is_found_when_the_report_names_none(dirs):
    cv, _ = dirs
    (cv / "Lothian_Buses_Junior_Digital_Designer_CV.md").write_text("x", encoding="utf-8")
    assert rmr._document_on_disk("Lothian_Buses_Junior_Digital_Designer", "CV") == \
        "Lothian_Buses_Junior_Digital_Designer_CV.md"


def test_a_cover_letter_on_disk_is_found_too(dirs):
    _, cl = dirs
    (cl / "Probe_Designer_CL.md").write_text("x", encoding="utf-8")
    assert rmr._document_on_disk("Probe_Designer", "CL") == "Probe_Designer_CL.md"


def test_nothing_is_invented_when_the_file_does_not_exist(dirs):
    assert rmr._document_on_disk("Probe_Designer", "CV") is None
    assert rmr._document_on_disk("Probe_Designer", "CL") is None


def test_only_this_report_s_own_base_name_is_matched(dirs):
    """The link is derived from the report's stem, so a near-miss must not be
    picked up — three different Lothian employers sit beside each other."""
    cv, _ = dirs
    (cv / "Lothian_Valuation_Joint_Board_ICT_CV.md").write_text("x", encoding="utf-8")
    assert rmr._document_on_disk("Lothian_Buses_Junior_Digital_Designer", "CV") is None


def test_an_existing_link_is_never_replaced():
    """The fallback only fills a gap. A hand-corrected link — pointing at a
    renamed or manually written document — has to survive a rerun."""
    source = (ROOT / "regen_match_reports.py").read_text(encoding="utf-8")
    line = next(l for l in source.splitlines() if l.strip().startswith("cv = wikilink_to_filename"))
    assert " or _document_on_disk" in line, (
        "the disk lookup must sit AFTER the frontmatter value, not before it"
    )


def test_the_carried_frontmatter_is_still_carried():
    """The links are the only thing this change touches. expired/applied and the
    carried review lines were lost once before by a rewrite that forgot them."""
    source = (ROOT / "regen_match_reports.py").read_text(encoding="utf-8")
    for name in ("read_expired_flag", "read_applied_flag", "read_carried_properties"):
        assert name in source, f"{name} is no longer passed through"
