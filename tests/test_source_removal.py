"""WeWorkRemotely is no longer scraped, and two dead sources leave no reports.

Dropped 2026-08-22 at the user's request. The scraper function stays in the file
— the board works, the decision is about where this pipeline spends its budget —
so the thing to pin is that nothing CALLS it, which is a one-line difference and
exactly the kind that gets undone by accident.

remoteok is a second case: nothing has scraped it for some time, but 15 of its
postings were still in the database, so every regeneration rebuilt their match
reports. A source that is gone should stop producing files.
"""
import inspect
import json
from pathlib import Path

import pytest

import scraper_remote_apis

ROOT = Path(__file__).resolve().parent.parent
DROPPED_SOURCES = ("weworkremotely", "remoteok")


def test_the_run_no_longer_calls_weworkremotely():
    src = inspect.getsource(scraper_remote_apis.scrape_remote_apis_all)
    assert "scrape_weworkremotely(" not in src


def test_the_scraper_itself_is_kept():
    """Deleting it would turn a budget decision into lost work. Re-adding the
    board should be one line, not a rewrite."""
    assert hasattr(scraper_remote_apis, "scrape_weworkremotely")


def test_the_boards_that_remain_are_still_called():
    src = inspect.getsource(scraper_remote_apis.scrape_remote_apis_all)
    assert "scrape_remotive(" in src
    assert "scrape_arbeitnow(" in src


@pytest.mark.parametrize("source", DROPPED_SOURCES)
def test_no_dropped_source_survives_in_the_database(source):
    """The reports are rebuilt from the DB, so deleting the files alone puts
    them back on the next regeneration."""
    path = ROOT / "10_output" / "_analyzed.json"
    if not path.exists():
        pytest.skip("no analysed DB to check")
    jobs = json.loads(path.read_text(encoding="utf-8"))
    left = [j for j in jobs if (j.get("source") or "") == source]
    assert not left, f"{len(left)} {source} postings still in the DB"
