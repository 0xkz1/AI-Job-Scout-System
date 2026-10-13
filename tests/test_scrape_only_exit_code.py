"""--scrape-only reports a failed site in its exit code.

The nightly runs every site as `run.py --site X --scrape-only` and writes the
exit code into the run summary. That path returned before main()'s own
exit-code rule, so on 2026-10-13 Guardian's browser died at launch and the
summary recorded rc 0 — a failure the notification called a clean night.
"""
import asyncio
import sys

import pytest

import run
import scraper_linkedin_guest


@pytest.fixture
def staged(monkeypatch):
    """Nothing reaches 00_saved or the yield file; what would have is recorded."""
    calls = {"saved": [], "yield": []}
    monkeypatch.setattr(run, "save_raw_to_saved",
                        lambda jobs, source: calls["saved"].append((source, len(jobs))))
    monkeypatch.setattr(run, "record_site_yield",
                        lambda site, count: calls["yield"].append((site, count)))
    return calls


def _scrape_only(monkeypatch, site):
    monkeypatch.setattr(sys, "argv", ["run.py", "--site", site, "--scrape-only"])
    return asyncio.run(run.main())


async def _dead(config):
    raise RuntimeError("BrowserType.launch: headed browser without an X server")


async def _two_jobs(config):
    return [{"title": "A", "company": "X", "url": "https://example.com/1"},
            {"title": "B", "company": "Y", "url": "https://example.com/2"}]


def test_the_only_site_failing_exits_non_zero(monkeypatch, staged):
    monkeypatch.setattr(run, "scrape_guardian_all", _dead)
    assert _scrape_only(monkeypatch, "guardian") == 1
    # And it leaves no yield row: a 0 there reads as "ran, found nothing".
    assert staged["yield"] == []


def test_a_site_that_scraped_exits_zero_and_records_its_yield(monkeypatch, staged):
    monkeypatch.setattr(run, "scrape_guardian_all", _two_jobs)
    assert _scrape_only(monkeypatch, "guardian") == 0
    assert staged["saved"] == [("guardian", 2)]
    assert staged["yield"] == [("guardian", 2)]


def test_a_site_that_ran_clean_and_found_nothing_is_still_success(monkeypatch, staged):
    async def nothing(config):
        return []
    monkeypatch.setattr(run, "scrape_guardian_all", nothing)
    assert _scrape_only(monkeypatch, "guardian") == 0
    assert staged["yield"] == [("guardian", 0)]


@pytest.mark.parametrize("cut_short, code", [(True, 124), (False, 0)])
def test_a_site_stopped_by_its_own_budget_exits_as_a_timeout(monkeypatch, staged,
                                                             cut_short, code):
    # LinkedIn used to be killed by the nightly's timeout, which the run summary
    # recorded as 124. Stopping itself keeps the jobs; it must not also turn the
    # night into a clean one, or two rate-limited nights read as a dry site.
    async def linkedin(config):
        monkeypatch.setattr(scraper_linkedin_guest, "stopped_short", cut_short)
        return await _two_jobs(config)
    monkeypatch.setattr(run, "scrape_linkedin_all", linkedin)
    assert _scrape_only(monkeypatch, "linkedin") == code
    assert staged["saved"] == [("linkedin", 2)]
    assert staged["yield"] == [("linkedin", 2)]
