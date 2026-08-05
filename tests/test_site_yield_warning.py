"""A site that exits 0 having scraped nothing must be reported.

The exit code cannot express this: a scraper whose selectors stopped matching
returns an empty list and exits clean, which is exactly how Indeed contributed
nothing for 11 consecutive nights while the cron recorded success every time.
LinkedIn is the standing risk now — scraper_linkedin_guest.py parses LinkedIn's
public class names, which LinkedIn can rename without notice.
"""
import json

import pytest

import nightly_scout
import run


@pytest.fixture
def yield_files(tmp_path, monkeypatch):
    monkeypatch.setattr(nightly_scout, "SITE_YIELD", tmp_path / "yield.tsv")
    monkeypatch.setattr(nightly_scout, "YIELD_HISTORY", tmp_path / "history.json")
    return tmp_path


def _run_night(counts: dict[str, int]) -> list[str]:
    """One night's bookkeeping: record the counts, return the flagged sites."""
    yields = counts
    history = nightly_scout.update_yield_history(yields)
    return nightly_scout.dry_sites(history, yields)


def test_single_quiet_night_is_not_reported(yield_files):
    # A narrow keyword set genuinely returns nothing some nights. Warning on the
    # first one would train the user to ignore the warning.
    assert _run_night({"linkedin": 0, "reed": 12}) == []


def test_two_consecutive_dry_nights_are_reported(yield_files):
    _run_night({"linkedin": 0, "reed": 12})
    flagged = _run_night({"linkedin": 0, "reed": 9})
    assert len(flagged) == 1
    assert flagged[0].startswith("linkedin")


def test_a_productive_night_clears_the_streak(yield_files):
    _run_night({"linkedin": 0})
    _run_night({"linkedin": 7})
    assert _run_night({"linkedin": 0}) == []


def test_site_absent_tonight_is_not_flagged(yield_files):
    # Dropping a site from the nightly must not accumulate phantom zeroes that
    # eventually warn about a scraper nobody runs.
    _run_night({"linkedin": 0})
    _run_night({"linkedin": 0})
    assert _run_night({"reed": 5}) == []


def test_history_is_bounded(yield_files):
    for _ in range(nightly_scout.YIELD_HISTORY_KEEP + 5):
        _run_night({"reed": 3})
    history = json.loads((yield_files / "history.json").read_text())
    assert len(history["reed"]) == nightly_scout.YIELD_HISTORY_KEEP


def test_load_site_yield_parses_and_skips_junk(yield_files):
    (yield_files / "yield.tsv").write_text(
        "linkedin\t0\nreed\t12\nmalformed line\nadzuna\tnot-a-number\n"
    )
    assert nightly_scout.load_site_yield() == {"linkedin": 0, "reed": 12}


def test_load_site_yield_absent_file_is_empty(yield_files):
    assert nightly_scout.load_site_yield() == {}


def test_record_site_yield_writes_only_when_env_names_a_file(tmp_path, monkeypatch):
    path = tmp_path / "yield.tsv"
    monkeypatch.delenv("JIS_YIELD_FILE", raising=False)
    run.record_site_yield("linkedin", 4)
    assert not path.exists()

    monkeypatch.setenv("JIS_YIELD_FILE", str(path))
    run.record_site_yield("linkedin", 4)
    run.record_site_yield("reed", 0)
    assert path.read_text() == "linkedin\t4\nreed\t0\n"
