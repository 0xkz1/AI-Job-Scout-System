"""regen_match_reports.py must never reset the applied/expired checkboxes or
drop the cv_pdf/cl_pdf/cv_review/cl_review links it did not itself write.

generate_match_report defaults expired/applied to False and carried to None
when a caller omits them (matcher.py's own docstring warns every caller must
pass both). regen_match_reports.py omitted all three parameters, so on
2026-08-06 the nightly's `regen_match_reports.py --apply` step reset applied
and expired to false on every report whose score-derived content had
changed, and dropped cv_pdf/cl_pdf/cv_review/cl_review the same way — wiping
hand-ticked checkboxes and PDF links for jobs already applied to (Wordsmith
AI, Lloyds Banking Group among them). No error, no log line: matched jobs
kept scoring normally, the loss only visible in Obsidian.
"""
import json
from datetime import datetime

import regen_match_reports as regen


def _match(composite, tier, *, skills, experience, context):
    """A match dict shaped like matcher.analyze_match's real output — nested
    per-category dicts, not flat *_score keys."""
    return {
        "composite_score": composite,
        "tier": tier,
        "skills": {"score": skills, "matched": [], "partial": [], "missing": []},
        "experience": {"score": experience, "job_level": "mid",
                       "user_estimated_years": 4, "note": ""},
        "location": {"score": 1.0, "notes": []},
        "salary": {"score": 1.0, "note": ""},
        "context_score": context,
        "weights": {"skills": 0.40, "experience": 0.25, "location": 0.10,
                    "salary": 0.05, "context": 0.20},
    }


def _write_report(path, *, applied, expired, extra_frontmatter="", score="0.70"):
    path.write_text(f"""---
match_score: {score}
match_score_pct: 70
tier: "Good Match"
company: "Acme"
title: "Product Designer"
location: "Edinburgh"
url: "https://example.com/job/1"
source: "reed"
type: "auto"
saved_at: 2026-08-01
analyzed_at: 2026-08-01
skills_score: 50
experience_score: 50
location_score: 100
salary_score: 100
context_score: 50
expired: {"true" if expired else "false"}
applied: {"true" if applied else "false"}
{extra_frontmatter}---

## Overall Match

body text here.
""", encoding="utf-8")


def test_flags_survive_when_the_lock_is_bypassed(tmp_path, monkeypatch):
    """Defence in depth behind the lock.

    A locked report is skipped entirely (see the lock tests below), so in
    normal operation this path is unreachable. It still matters: it is the
    difference between "the tick is preserved" and "the tick is silently
    cleared" if the lock is ever loosened, reordered, or bypassed — which is
    exactly what happened on 2026-08-06, when nothing guarded the report and
    generate_match_report's expired/applied defaults quietly wrote false.
    """
    match_dir = tmp_path / "00_matches"
    match_dir.mkdir()
    report = match_dir / "Acme_Product_Designer.md"
    _write_report(report, applied=True, expired=True)
    monkeypatch.setattr(regen.gen_version, "job_lock_reason", lambda *a, **k: None)

    db = [{
        "title": "Product Designer", "company": "Acme", "location": "Edinburgh",
        "url": "https://example.com/job/1", "source": "reed", "type": "auto",
        "scraped_at": "2026-08-01T00:00:00",
        # A different score forces this report into the "changed" set — the
        # exact condition that triggered the original bug (unchanged reports
        # were never rewritten, so the bug only bit files whose score moved).
        "match": _match(0.85, "Strong Match", skills=0.90, experience=0.80, context=0.70),
    }]
    db_path = tmp_path / "_analyzed.json"
    db_path.write_text(json.dumps(db))

    monkeypatch.setattr(regen, "MATCH_DIR", match_dir)
    monkeypatch.setattr(regen, "DB_PATH", db_path)
    monkeypatch.setattr(regen, "APPLY", True)

    regen.main()

    new_text = report.read_text(encoding="utf-8")
    assert "match_score: 0.85" in new_text, "the score must actually have been rewritten"
    assert "applied: true" in new_text, "the applied tick must survive a score-driven rewrite"
    assert "expired: true" in new_text, "the expired tick must survive a score-driven rewrite"


def test_carried_pdf_and_review_links_survive_a_regeneration(tmp_path, monkeypatch):
    # An ordinary, unlocked job: its PDF and review links are written by later
    # steps that this renderer cannot derive, so they must be carried across.
    match_dir = tmp_path / "00_matches"
    match_dir.mkdir()
    report = match_dir / "Acme_Product_Designer.md"
    _write_report(
        report, applied=False, expired=False,
        extra_frontmatter=(
            'cv_pdf: "[[Acme_Product_Designer_CV.pdf]]"\n'
            'cl_pdf: "[[Acme_Product_Designer_CL.pdf]]"\n'
            'cv_review_score: 79\n'
        ),
    )

    db = [{
        "title": "Product Designer", "company": "Acme", "location": "Edinburgh",
        "url": "https://example.com/job/1", "source": "reed", "type": "auto",
        "scraped_at": "2026-08-01T00:00:00",
        "match": _match(0.90, "Strong Match", skills=0.95, experience=0.90, context=0.80),
    }]
    db_path = tmp_path / "_analyzed.json"
    db_path.write_text(json.dumps(db))

    monkeypatch.setattr(regen, "MATCH_DIR", match_dir)
    monkeypatch.setattr(regen, "DB_PATH", db_path)
    monkeypatch.setattr(regen, "APPLY", True)

    regen.main()

    new_text = report.read_text(encoding="utf-8")
    assert "match_score: 0.9" in new_text
    assert "cv_pdf:" in new_text and "Acme_Product_Designer_CV.pdf" in new_text
    assert "cl_pdf:" in new_text and "Acme_Product_Designer_CL.pdf" in new_text


def test_an_applied_report_is_not_rewritten_at_all(tmp_path, monkeypatch):
    """gen_version's `applied` lock says a submitted application's files "must
    stop moving". Those locks were written to guard the CV/CL, and nothing
    guarded the match report the lock flag is itself read from — so this script
    re-rendered it, moving the record and (before the flags were passed
    through) clearing the tick outright."""
    match_dir = tmp_path / "00_matches"
    match_dir.mkdir()
    report = match_dir / "Acme_Product_Designer.md"
    _write_report(report, applied=True, expired=False)
    before = report.read_bytes()
    before_mtime = report.stat().st_mtime_ns

    db = [{
        "title": "Product Designer", "company": "Acme", "location": "Edinburgh",
        "url": "https://example.com/job/1", "source": "reed", "type": "auto",
        "scraped_at": "2026-08-01T00:00:00",
        # A very different score — the render would certainly differ.
        "match": _match(0.95, "Strong Match", skills=0.99, experience=0.99, context=0.99),
    }]
    db_path = tmp_path / "_analyzed.json"
    db_path.write_text(json.dumps(db))

    monkeypatch.setattr(regen, "MATCH_DIR", match_dir)
    monkeypatch.setattr(regen, "DB_PATH", db_path)
    monkeypatch.setattr(regen, "APPLY", True)

    regen.main()

    assert report.read_bytes() == before
    assert report.stat().st_mtime_ns == before_mtime


def test_an_expired_report_is_not_rewritten_at_all(tmp_path, monkeypatch):
    match_dir = tmp_path / "00_matches"
    match_dir.mkdir()
    report = match_dir / "Acme_Product_Designer.md"
    _write_report(report, applied=False, expired=True)
    before = report.read_bytes()

    db = [{
        "title": "Product Designer", "company": "Acme", "location": "Edinburgh",
        "url": "https://example.com/job/1", "source": "reed", "type": "auto",
        "scraped_at": "2026-08-01T00:00:00",
        "match": _match(0.95, "Strong Match", skills=0.99, experience=0.99, context=0.99),
    }]
    db_path = tmp_path / "_analyzed.json"
    db_path.write_text(json.dumps(db))

    monkeypatch.setattr(regen, "MATCH_DIR", match_dir)
    monkeypatch.setattr(regen, "DB_PATH", db_path)
    monkeypatch.setattr(regen, "APPLY", True)

    regen.main()

    assert report.read_bytes() == before


def test_an_unlocked_report_is_still_rewritten(tmp_path, monkeypatch):
    # The lock must not become a blanket freeze — an ordinary job still needs
    # its score re-rendered, which is the whole point of this script.
    match_dir = tmp_path / "00_matches"
    match_dir.mkdir()
    report = match_dir / "Acme_Product_Designer.md"
    _write_report(report, applied=False, expired=False)

    db = [{
        "title": "Product Designer", "company": "Acme", "location": "Edinburgh",
        "url": "https://example.com/job/1", "source": "reed", "type": "auto",
        "scraped_at": "2026-08-01T00:00:00",
        "match": _match(0.95, "Strong Match", skills=0.99, experience=0.99, context=0.99),
    }]
    db_path = tmp_path / "_analyzed.json"
    db_path.write_text(json.dumps(db))

    monkeypatch.setattr(regen, "MATCH_DIR", match_dir)
    monkeypatch.setattr(regen, "DB_PATH", db_path)
    monkeypatch.setattr(regen, "APPLY", True)

    regen.main()

    assert "match_score: 0.95" in report.read_text(encoding="utf-8")


def test_an_unchanged_report_is_not_rewritten_at_all(tmp_path, monkeypatch):
    # Byte-identical output must skip the write entirely — the vault-churn
    # guard the module's docstring promises. Built via generate_match_report
    # itself (rather than hand-written frontmatter) so analyzed_at matches
    # exactly what a fresh run would also stamp, with nothing in the DB
    # changed between the two renders.
    from matcher import generate_match_report

    match_dir = tmp_path / "00_matches"
    match_dir.mkdir()
    report = match_dir / "Acme_Product_Designer.md"

    job = {
        "title": "Product Designer", "company": "Acme", "location": "Edinburgh",
        "url": "https://example.com/job/1", "source": "reed", "type": "auto",
        "scraped_at": "2026-08-01T00:00:00",
    }
    match = _match(0.85, "Good Match", skills=0.50, experience=0.50, context=0.50)
    report.write_text(
        generate_match_report(job, match, applied=True, expired=False),
        encoding="utf-8",
    )
    before_mtime = report.stat().st_mtime_ns

    db = [{**job, "match": match}]
    db_path = tmp_path / "_analyzed.json"
    db_path.write_text(json.dumps(db))

    monkeypatch.setattr(regen, "MATCH_DIR", match_dir)
    monkeypatch.setattr(regen, "DB_PATH", db_path)
    monkeypatch.setattr(regen, "APPLY", True)

    regen.main()

    assert report.stat().st_mtime_ns == before_mtime
