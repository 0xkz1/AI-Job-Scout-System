"""The expiry checker must only ever conclude "closed" from real evidence.

The asymmetry is the point. Leaving a closed posting ticked as open costs one
wasted review; ticking a live posting as expired removes it from the pipeline
entirely — gen_version treats `expired` as a job-scoped lock, so the job is
refused a review, a regeneration, and a first CV, and nothing downstream asks
again. Every case below is a page that was measured on 2026-08-31, and half of
them are pages that LOOK closed and are not.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import check_expired as ce


def fetcher(status, html=""):
    """A fetch that records what it was asked for."""
    calls = []

    def fetch(url):
        calls.append(url)
        return status, html

    fetch.calls = calls
    return fetch


# --- the traps: pages that read as closed and are not ----------------------

def test_the_guardian_is_not_guessed_at():
    """Every Guardian job page server-renders "This job has expired" in its
    header, live ones included — a posting scraped in July and one scraped last
    week carry it byte-identically. Reading the phrase would expire all 41."""
    fetch = fetcher(200, "<p id='message'>This job has expired</p><h1>ML Engineer</h1>")
    verdict, _ = ce.check_url("https://jobs.theguardian.com/job/10146129/ml-engineer/",
                              "guardian", fetch)
    assert verdict == ce.UNSUPPORTED
    assert fetch.calls == [], "a source with no rule should not cost a request"


def test_indeed_is_not_guessed_at():
    """uk.indeed.com answers 401 "Authenticating..." to anything without a
    browser fingerprint, and that page is identical whether the job behind it is
    open or gone."""
    fetch = fetcher(401, "Authenticating...")
    verdict, _ = ce.check_url("https://uk.indeed.com/viewjob?jk=f7a7fdfc9b3ff2bd",
                              "indeed", fetch)
    assert verdict == ce.UNSUPPORTED


def test_an_adzuna_land_link_is_not_evidence():
    """The stored /jobs/land/ad/<id>?se=... links answer 400 for live and dead
    ads alike — the `se` token is short-lived, so the URL in the database has
    stopped carrying information about the ad."""
    verdict, _ = ce.check_url(
        "https://www.adzuna.co.uk/jobs/land/ad/5783345306?se=yHbjx0SI8RGrg5YQe_eAEA",
        "adzuna", fetcher(400))
    assert verdict == ce.BLOCKED


def test_a_rate_limit_is_never_an_expiry():
    for source, url in (("linkedin", "https://www.linkedin.com/jobs/view/4455358082"),
                        ("reed", "https://www.reed.co.uk/jobs/x/57148184"),
                        ("adzuna", "https://www.adzuna.co.uk/jobs/details/5855370285"),
                        ("arbeitnow", "https://www.arbeitnow.com/jobs/companies/a/b-1")):
        for status in (429, 403, 500, 0):
            verdict, _ = ce.check_url(url, source, fetcher(status))
            assert verdict == ce.BLOCKED, f"{source} {status}"


# --- the signals that do decide -------------------------------------------

def test_linkedin_closed_posting():
    fetch = fetcher(200, "<p>No longer accepting applications</p>")
    verdict, evidence = ce.check_url("https://www.linkedin.com/jobs/view/4443391346/",
                                     "linkedin", fetch)
    assert verdict == ce.GONE
    assert "no longer accepting" in evidence
    assert fetch.calls == [
        "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4443391346"]


def test_linkedin_live_posting():
    verdict, _ = ce.check_url("https://www.linkedin.com/jobs/view/4455358082",
                              "linkedin", fetcher(200, "<h1>Product Designer</h1>"))
    assert verdict == ce.LIVE


def test_linkedin_withdrawn_posting_404s():
    verdict, _ = ce.check_url("https://www.linkedin.com/jobs/view/4443391346",
                              "linkedin", fetcher(404))
    assert verdict == ce.GONE


def test_reed_expired_posting():
    fetch = fetcher(404, "<title>404 - page not found - reed.co.uk</title>"
                         "<h1>This job has expired</h1>")
    verdict, evidence = ce.check_url(
        "https://www.reed.co.uk/jobs/ai-engineer/57034200?source=searchResults",
        "reed", fetch)
    assert verdict == ce.GONE
    assert "This job has expired" in evidence
    # the tracking query is dropped, so the same posting is one URL not many
    assert fetch.calls == ["https://www.reed.co.uk/jobs/ai-engineer/57034200"]


def test_reed_live_posting():
    verdict, _ = ce.check_url("https://www.reed.co.uk/jobs/x/57148184", "reed",
                              fetcher(200, "<h1>Manufacturing Engineer</h1>"))
    assert verdict == ce.LIVE


def test_adzuna_is_asked_on_the_canonical_page_of_its_own_host():
    """The land link is useless, but the ad id in it is not — and adzuna runs a
    domain per country, so the host has to come from the stored URL."""
    fetch = fetcher(410)
    verdict, _ = ce.check_url("https://www.adzuna.de/jobs/land/ad/5783854084?se=x",
                              "adzuna", fetch)
    assert verdict == ce.GONE
    assert fetch.calls == ["https://www.adzuna.de/jobs/details/5783854084"]


def test_adzuna_live_ad():
    verdict, _ = ce.check_url("https://www.adzuna.co.uk/jobs/details/5855370285?utm_medium=api",
                              "adzuna", fetcher(200, "<title>IT Support Job in Horsham</title>"))
    assert verdict == ce.LIVE


@pytest.mark.parametrize("source", ["arbeitnow", "remotive"])
def test_the_small_boards_answer_410_when_a_posting_is_pulled(source):
    assert ce.check_url("https://example.test/jobs/x-1", source, fetcher(410))[0] == ce.GONE
    assert ce.check_url("https://example.test/jobs/x-1", source, fetcher(200, "<h1>x</h1>"))[0] == ce.LIVE


# --- writing the tick ------------------------------------------------------

REPORT = """---
match_score: 0.72
expired: false
applied: false
company: "Acme"
url: "https://www.reed.co.uk/jobs/x/1"
---

# Match Report: Designer
body stays put
"""


def test_ticking_changes_one_line_and_no_other(tmp_path):
    p = tmp_path / "Acme_Designer.md"
    p.write_text(REPORT, encoding="utf-8")
    assert ce.tick_expired(p) is True
    got = p.read_text(encoding="utf-8")
    assert "expired: true" in got
    assert "applied: false" in got
    assert 'company: "Acme"' in got
    assert "body stays put" in got
    assert got.count("expired:") == 1


def test_a_dry_run_writes_nothing(tmp_path):
    p = tmp_path / "Acme_Designer.md"
    p.write_text(REPORT, encoding="utf-8")
    assert ce.tick_expired(p, dry_run=True) is True
    assert p.read_text(encoding="utf-8") == REPORT


def test_a_report_without_the_key_is_reported_not_invented(tmp_path):
    """Older reports predate the checkbox. Adding one here would put the flag
    somewhere generate_match_report does not, so it is left for a regeneration."""
    p = tmp_path / "Old.md"
    p.write_text('---\nmatch_score: 0.5\n---\n\nbody\n', encoding="utf-8")
    assert ce.tick_expired(p) is False


def test_the_tick_reads_the_way_the_rest_of_the_pipeline_reads_it(tmp_path):
    """gen_version and matcher both decide the lock from this one line."""
    import gen_version
    from matcher import read_expired_flag
    p = tmp_path / "Acme_Designer.md"
    p.write_text(REPORT, encoding="utf-8")
    ce.tick_expired(p)
    assert read_expired_flag(p) is True
    assert gen_version.job_lock_reason("Acme_Designer", tmp_path) == "expired"


def test_reports_are_read_with_their_flags(tmp_path):
    (tmp_path / "A.md").write_text(REPORT, encoding="utf-8")
    (tmp_path / "B.md").write_text(REPORT.replace("expired: false", "expired: true"),
                                   encoding="utf-8")
    rows = {r["path"].name: r for r in ce.read_reports(tmp_path)}
    assert rows["A.md"]["expired"] is False and rows["B.md"]["expired"] is True
    assert rows["A.md"]["source"] == ""
    assert rows["A.md"]["score"] == pytest.approx(0.72)


def test_a_source_with_no_rule_does_not_use_up_the_run(tmp_path, monkeypatch, capsys):
    """A cap of 200 that spends 14 slots printing "no rule for guardian" is 14
    postings that went unchecked."""
    monkeypatch.setattr(ce, "MATCHES", tmp_path)
    monkeypatch.setattr(ce, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(ce, "ANALYZED", tmp_path / "db.json")
    (tmp_path / "db.json").write_text("[]", encoding="utf-8")
    (tmp_path / "G.md").write_text(
        REPORT.replace('url: "https://www.reed.co.uk/jobs/x/1"',
                       'source: "guardian"\nurl: "https://jobs.theguardian.com/job/1/x/"'),
        encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["check_expired.py", "--dry-run"])
    assert ce.main() == 0
    out = capsys.readouterr().out
    assert "no rule for their source" in out
    assert "checking" not in out
