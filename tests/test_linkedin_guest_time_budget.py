"""LinkedIn stops on its own clock and keeps what it has.

The nightly kills it at LINKEDIN_TIMEOUT, and a killed process stages nothing:
on 2026-10-13 it died 54 searches and 922 postings in, 80 descriptions into the
fetch, and the night's LinkedIn yield was zero. The clock is faked here — the
module reads time.monotonic() and time.sleep() through its `time` attribute.
"""
from types import SimpleNamespace

import pytest

import invariants
import scraper_indeed
import scraper_linkedin_guest as guest

_LONG = "x" * 700  # over the cache's 600-char minimum


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    slept = []
    monkeypatch.setattr(guest, "time", SimpleNamespace(
        monotonic=lambda: now[0], sleep=lambda s: slept.append(s)))
    monkeypatch.setattr(guest, "_sleep", lambda: None)
    # Restored afterwards, so a run cut short here cannot leak into run.py's tests.
    monkeypatch.setattr(guest, "stopped_short", False)
    return SimpleNamespace(now=now, slept=slept)


def _no_request(*args, **kwargs):
    raise AssertionError("made a request with no time left")


def _posting(job_id, title):
    return {"job_id": job_id, "title": title, "company": "A", "location": "Edinburgh"}


def test_out_of_time_the_fetch_keeps_cache_hits_and_requests_nothing(monkeypatch, clock):
    monkeypatch.setattr(guest, "_deadline", clock.now[0] - 1)
    monkeypatch.setattr(guest, "_get", _no_request)
    jobs = [_posting("1", "Product Designer"), _posting("2", "Kitchen Porter")]
    cache = {("product designer", "a"): {"description": _LONG}}

    guest.fill_descriptions(jobs, cache)

    assert jobs[0]["description"] == _LONG
    assert "description" not in jobs[1]


def test_a_429_wait_that_would_overrun_gives_up_without_sleeping(monkeypatch, clock):
    monkeypatch.setattr(guest, "_deadline", clock.now[0] + 100)
    monkeypatch.setattr(guest.requests, "get", lambda *a, **k: SimpleNamespace(
        status_code=429, headers={"Retry-After": "600"}, text=""))

    assert guest._get("https://example.com") is None
    assert clock.slept == []
    assert guest.stopped_short


def test_the_search_loop_stops_when_the_budget_is_spent(monkeypatch, clock):
    monkeypatch.setenv("LINKEDIN_GUEST_BUDGET", "2400")  # stop at +2220s
    searched = []

    def search(kw, loc, max_pages):
        searched.append(kw)
        clock.now[0] += 1500
        return [_posting(kw, f"{kw} Designer")]

    monkeypatch.setattr(guest, "search", search)
    monkeypatch.setattr(guest, "_get", _no_request)
    monkeypatch.setattr("selection.max_pages_for", lambda site, config: 1)
    monkeypatch.setattr("selection.search_pairs", lambda config, site=None: [
        ("A", "Edinburgh"), ("B", "Edinburgh"), ("C", "Edinburgh")])
    monkeypatch.setattr("scraper_helper.load_description_cache", lambda: {
        ("a designer", "a"): {"description": _LONG}})
    monkeypatch.setattr(scraper_indeed, "filter_jobs_by_keywords", lambda jobs, keywords: jobs)

    out = guest.scrape_linkedin_guest_all({"keywords": ["Designer"]})

    assert searched == ["A", "B"]
    # B's posting had no cached text and no time to fetch it; A's survives.
    assert [j["job_id"] for j in out] == ["A"]
    assert guest._deadline is None
    assert guest.stopped_short


def test_a_run_that_finishes_in_time_is_not_cut_short(monkeypatch, clock):
    monkeypatch.setattr(guest, "stopped_short", True)  # left over from a past run
    monkeypatch.setattr(guest, "search", lambda kw, loc, max_pages: [_posting(kw, f"{kw} Designer")])
    monkeypatch.setattr(guest, "_get", _no_request)
    monkeypatch.setattr("selection.max_pages_for", lambda site, config: 1)
    monkeypatch.setattr("selection.search_pairs", lambda config, site=None: [("A", "Edinburgh")])
    monkeypatch.setattr("scraper_helper.load_description_cache", lambda: {
        ("a designer", "a"): {"description": _LONG}})
    monkeypatch.setattr(scraper_indeed, "filter_jobs_by_keywords", lambda jobs, keywords: jobs)

    out = guest.scrape_linkedin_guest_all({"keywords": ["Designer"]})

    assert [j["job_id"] for j in out] == ["A"]
    assert not guest.stopped_short


def test_the_deadline_is_cleared_when_the_run_raises(monkeypatch, clock):
    def search(kw, loc, max_pages):
        raise RuntimeError("boom")

    monkeypatch.setattr(guest, "search", search)
    monkeypatch.setattr("selection.max_pages_for", lambda site, config: 1)
    monkeypatch.setattr("selection.search_pairs", lambda config, site=None: [("A", "Edinburgh")])

    with pytest.raises(RuntimeError):
        guest.scrape_linkedin_guest_all({"keywords": ["Designer"]})
    # Left set, it would cut short the --dry-run CLI and every later test.
    assert guest._deadline is None


def test_the_budget_is_the_nightly_timeout_unless_overridden(monkeypatch):
    monkeypatch.delenv("LINKEDIN_GUEST_BUDGET", raising=False)
    assert guest._budget_seconds() == invariants._site_timeout("linkedin")
    monkeypatch.setenv("LINKEDIN_GUEST_BUDGET", "600")
    assert guest._budget_seconds() == 600.0
