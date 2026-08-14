"""A site that never gets to run must eventually be reported as such.

summarize_sites already names tonight's timeouts and budget skips, so no single
night hides them. What it cannot say is whether tonight was unlucky or whether
the site has quietly left the nightly: between 2026-08-12 and 08-15, guardian,
adzuna and remote_apis were skipped every night, each message read
"予算切れで未実行", and nobody decided those three should stop being scraped.

dry_sites cannot cover this. It judges the yield history, and a site that never
starts records no yield at all — guardian's history sat frozen at a single entry
for the whole stretch.
"""
import json

import pytest

import nightly_scout


@pytest.fixture
def status_file(tmp_path, monkeypatch):
    monkeypatch.setattr(nightly_scout, "STATUS_HISTORY", tmp_path / "status.json")
    return tmp_path


def _summary(**sites: str) -> list[dict]:
    """Tonight's run summary, as load_run_summary would return it."""
    return [{"site": s, "exit": 0, "elapsed": 0, "status": st} for s, st in sites.items()]


def _run_night(**sites: str) -> list[str]:
    summary = _summary(**sites)
    return nightly_scout.stale_sites(nightly_scout.update_status_history(summary), summary)


def test_one_skipped_night_is_not_reported(status_file):
    # The budget is genuinely spent by a slow night now and again.
    assert _run_night(guardian="skipped", linkedin="ok") == []


def test_two_skipped_nights_are_still_below_the_threshold(status_file):
    _run_night(guardian="skipped")
    assert _run_night(guardian="skipped") == []


def test_three_consecutive_nights_without_a_scrape_are_reported(status_file):
    _run_night(guardian="skipped", linkedin="ok")
    _run_night(guardian="skipped", linkedin="ok")
    flagged = _run_night(guardian="skipped", linkedin="ok")
    assert flagged == ["guardian(3晩連続未取得)"]


def test_timeouts_and_skips_count_toward_the_same_streak(status_file):
    # Both mean the same thing to the reader: no jobs came from that site.
    _run_night(reed="timeout")
    _run_night(reed="skipped")
    assert _run_night(reed="error") == ["reed(3晩連続未取得)"]


def test_one_good_night_clears_the_streak(status_file):
    _run_night(adzuna="skipped")
    _run_night(adzuna="skipped")
    _run_night(adzuna="ok")
    assert _run_night(adzuna="skipped") == []


def test_site_absent_tonight_is_not_flagged(status_file):
    # Retiring a site from the nightly must stop the warning, not entrench it.
    _run_night(guardian="skipped")
    _run_night(guardian="skipped")
    _run_night(guardian="skipped")
    assert _run_night(linkedin="ok") == []


def test_absent_site_keeps_its_history_rather_than_recording_a_pass(status_file):
    _run_night(guardian="skipped")
    _run_night(guardian="skipped")
    _run_night(linkedin="ok")
    # Returning does not reset the streak: two bad nights are still on record,
    # so a third completes it.
    assert _run_night(guardian="skipped") == ["guardian(3晩連続未取得)"]


def test_history_is_bounded(status_file):
    for _ in range(nightly_scout.YIELD_HISTORY_KEEP + 5):
        _run_night(reed="ok")
    history = json.loads((status_file / "status.json").read_text())
    assert len(history["reed"]) == nightly_scout.YIELD_HISTORY_KEEP


def test_corrupt_history_does_not_break_the_night(status_file):
    (status_file / "status.json").write_text("not json at all")
    assert _run_night(guardian="skipped") == []


def test_a_stale_site_always_makes_the_night_non_silent(status_file):
    # stale never needs its own clause in the silence check: the last entry in
    # the streak is tonight's, and it is non-ok by construction, so
    # summarize_sites has already set any_failure.
    summary = _summary(guardian="skipped", linkedin="ok")
    _run_night(guardian="skipped")
    _run_night(guardian="skipped")
    _, any_failure = nightly_scout.summarize_sites(summary)
    assert nightly_scout.stale_sites(nightly_scout.update_status_history(summary), summary)
    assert any_failure
