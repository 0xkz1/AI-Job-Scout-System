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

def test_a_source_with_no_rule_costs_no_request():
    fetch = fetcher(200, "<h1>Something</h1>")
    verdict, _ = ce.check_url("https://example.test/job/1", "somewhere-new", fetch)
    assert verdict == ce.UNSUPPORTED
    assert fetch.calls == []


def test_the_guardian_banner_is_matched_as_an_element_not_a_phrase():
    """A live Guardian posting has no #message element at all; a closed one
    carries the banner. The first two postings drawn from this database both had
    it, which made the banner look unconditional until one taken off the site's
    own live listing turned out to have none — so the element is the signal, and
    a banner this code has not been shown is not evidence of anything."""
    gone, evidence = ce.check_url("https://jobs.theguardian.com/job/10146129/ml-engineer/",
                                  "guardian",
                                  fetcher(200, '<p id="message" class="mds-message">'
                                               'This job has expired</p><h1>ML Engineer</h1>'))
    assert gone == ce.GONE and evidence == "This job has expired"

    live, _ = ce.check_url("https://jobs.theguardian.com/job/10169290/quality-manager/",
                           "guardian", fetcher(200, "<h1>Quality Manager</h1>"))
    assert live == ce.LIVE

    other, _ = ce.check_url("https://jobs.theguardian.com/job/1/x/", "guardian",
                            fetcher(200, '<p id="message">Applications are paused</p>'))
    assert other == ce.BLOCKED


def test_the_guardian_phrase_outside_the_banner_decides_nothing():
    verdict, _ = ce.check_url(
        "https://jobs.theguardian.com/job/1/x/", "guardian",
        fetcher(200, "<h1>Designer</h1><p>Tell us why this job has expired</p>"))
    assert verdict == ce.LIVE


def test_indeed_is_not_guessed_at():
    """uk.indeed.com answers 401 "Authenticating..." to a plain request, 403 to
    the /m/ path, and Cloudflare's "Additional Verification Required" to a
    headless browser with stealth and the saved cookies — the same page for a
    known-dead jk as for a live one. There is no per-posting page to ask."""
    fetch = fetcher(401, "Authenticating...")
    verdict, _ = ce.check_url("https://uk.indeed.com/viewjob?jk=f7a7fdfc9b3ff2bd",
                              "indeed", fetch)
    assert verdict == ce.UNSUPPORTED
    assert fetch.calls == [], "a blocked site should not be asked at all"
    assert "indeed" not in ce.SUPPORTED_SOURCES


def test_an_indeed_link_is_handed_over_in_a_form_a_human_can_open():
    """The stored /rc/clk link is 300 characters of tracking around one jk, and
    the manual list exists to be clicked. Cloudflare lets a real browser
    through where it refuses this script."""
    got = ce.clickable(
        "https://uk.indeed.com/rc/clk?jk=13edc870860bed60&bb=xx&xkcb=yy&vjs=3", "indeed")
    assert got == "https://uk.indeed.com/viewjob?jk=13edc870860bed60"
    same = "https://www.reed.co.uk/jobs/x/1"
    assert ce.clickable(same, "reed") == same


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
                       'source: "indeed"\nurl: "https://uk.indeed.com/viewjob?jk=abc123"'),
        encoding="utf-8")
    # nothing here may reach the network: the point is that it never gets that far
    monkeypatch.setattr(ce, "make_fetch",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched")))
    monkeypatch.setattr(sys, "argv", ["check_expired.py", "--dry-run"])
    assert ce.main() == 0
    out = capsys.readouterr().out
    assert "no rule for their source" in out
    assert "checking" not in out


def test_one_posting_can_be_checked_on_its_own(tmp_path, monkeypatch, capsys):
    """"This one was expired and you did not catch it" is how the gaps surface,
    so checking a single report has to be one command, not a full pass."""
    monkeypatch.setattr(ce, "MATCHES", tmp_path)
    monkeypatch.setattr(ce, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(ce, "ANALYZED", tmp_path / "db.json")
    (tmp_path / "db.json").write_text("[]", encoding="utf-8")
    (tmp_path / "Wanted_Designer.md").write_text(REPORT.replace(
        'expired: false', 'source: "reed"\nexpired: false'), encoding="utf-8")
    (tmp_path / "Other_Designer.md").write_text(REPORT.replace(
        'expired: false', 'source: "reed"\nexpired: false'), encoding="utf-8")
    monkeypatch.setattr(ce, "make_fetch", lambda *a, **k: (lambda url: (404, "<h1>This job has expired</h1>")))
    monkeypatch.setattr(sys, "argv", ["check_expired.py", "--match", "wanted"])
    assert ce.main() == 0
    out = capsys.readouterr().out
    assert "checking 1 posting(s)" in out
    assert "Wanted_Designer" in out and "Other_Designer" not in out
    assert "expired: true" in (tmp_path / "Wanted_Designer.md").read_text(encoding="utf-8")
    assert "expired: false" in (tmp_path / "Other_Designer.md").read_text(encoding="utf-8")
