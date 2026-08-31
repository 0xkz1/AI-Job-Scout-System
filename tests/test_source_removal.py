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
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scraper_remote_apis

CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
# Read from the config rather than repeated here: the list decides what the
# staging loader drops on the way in, and a second copy in the test would go
# stale the first time a board is added or restored.
DROPPED_SOURCES = tuple(CONFIG.get("dropped_sources", []))


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

# --- the way back in ---

def test_the_config_names_the_dropped_boards():
    assert set(DROPPED_SOURCES) >= {"weworkremotely", "remoteok"}


def test_dropping_a_board_does_not_drop_the_scraper_that_reaches_it():
    """remote_apis is ONE site returning arbeitnow, remotive, weworkremotely and
    remoteok. Deriving the drop list from `sites` would take the first two with
    it, which is why dropped_sources is its own key."""
    assert "remote_apis" in (CONFIG.get("sites") or [])
    assert "arbeitnow" not in DROPPED_SOURCES
    assert "remotive" not in DROPPED_SOURCES


def test_staging_no_longer_feeds_a_dropped_source_back_in(tmp_path, monkeypatch):
    """00_saved is append-only, so every --from-saved run replays a month of
    scrapes. Purging the database on 2026-08-27 was undone by the next nightly:
    the rows came back out of the 15 staging files that still hold them, still
    carrying their original scraped_at."""
    import run
    staging = tmp_path / "00_saved"
    staging.mkdir()
    (staging / "_raw_remote_apis_20260801_000000.json").write_text(json.dumps([
        {"title": "Brand Designer", "company": "Symbiotic", "source": "remoteok",
         "url": "https://remoteok.test/1"},
        {"title": "Product Designer", "company": "Real", "source": "arbeitnow",
         "url": "https://arbeitnow.test/2"},
    ]), encoding="utf-8")
    monkeypatch.setattr(run, "SAVED_DIR", str(staging))
    monkeypatch.setattr(run, "load_saved_from_index", lambda: [])
    got = run.load_all_from_saved({"dropped_sources": ["remoteok"]})
    assert [j["source"] for j in got] == ["arbeitnow"]


def test_the_staging_files_themselves_are_left_alone(tmp_path, monkeypatch):
    """They record what a scrape returned. Rewriting that to match a later
    decision is not something this pipeline should do — the drop belongs on the
    read side, where one config line undoes it."""
    import run
    staging = tmp_path / "00_saved"
    staging.mkdir()
    f = staging / "_raw_remote_apis_20260801_000000.json"
    payload = json.dumps([{"title": "X", "source": "remoteok", "url": "u"}])
    f.write_text(payload, encoding="utf-8")
    monkeypatch.setattr(run, "SAVED_DIR", str(staging))
    monkeypatch.setattr(run, "load_saved_from_index", lambda: [])
    run.load_all_from_saved({"dropped_sources": ["remoteok"]})
    assert f.read_text(encoding="utf-8") == payload


def test_an_empty_drop_list_changes_nothing(tmp_path, monkeypatch):
    import run
    staging = tmp_path / "00_saved"
    staging.mkdir()
    (staging / "_raw_x_20260801_000000.json").write_text(
        json.dumps([{"title": "X", "source": "remoteok", "url": "u"}]), encoding="utf-8")
    monkeypatch.setattr(run, "SAVED_DIR", str(staging))
    monkeypatch.setattr(run, "load_saved_from_index", lambda: [])
    assert len(run.load_all_from_saved({})) == 1


# --- talents.studysmarter.co.uk, dropped 2026-08-31 as a fraudulent site ---

def test_the_config_names_talents():
    """Not a budget decision like the others: the user identified the site as
    fraudulent, so its postings are not leads at any price."""
    assert "talents" in DROPPED_SOURCES


def test_a_pasted_url_from_a_dropped_source_is_never_fetched():
    """talents arrived through url-list.md, not a scraper, and the staging-side
    drop in run.py only discards the result — the page load and the extraction
    call had already been paid for."""
    import scraper_url_list
    keep, skip = scraper_url_list.drop_dropped_sources([
        "https://talents.studysmarter.co.uk/companies/x/designer-1/",
        "https://www.linkedin.com/jobs/view/4445522521",
    ])
    assert keep == ["https://www.linkedin.com/jobs/view/4445522521"]
    assert len(skip) == 1


def test_no_talents_document_is_left_behind():
    """The reports, CVs, letters and reviews it produced were deleted with the
    rows. A file surviving here would be re-scored and re-listed."""
    out = ROOT / "10_output"
    if not out.exists():
        pytest.skip("no output tree to check")
    stray = [
        p for d in ("00_matches", "10_cvs", "10_cover-letters", "15_reviews")
        for p in (out / d).rglob("*.md")
        if "studysmarter" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not stray, f"{len(stray)} talents document(s) left: {stray[:3]}"
