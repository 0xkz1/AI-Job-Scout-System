"""The repair loop's decisions, which are the part that can do damage.

loop_repair.py edits source without a human asking, so what it declines to do
matters more than what it does. These pin the declines.

The one that would hurt most is mistaking a budget skip for a broken scraper.
guardian was skipped five nights running in August 2026 because the sites ahead
of it spent the scrape budget; its yield history stayed frozen at one entry the
whole time. A loop that reads "no jobs for five nights" as "the selectors moved"
would spend a model on rewriting a scraper that was never given a chance to run.
"""
import json

import pytest

import loop_repair as lr


@pytest.fixture
def state(tmp_path, monkeypatch):
    """Point every file the loop reads at a temp copy."""
    monkeypatch.setattr(lr, "YIELD_HISTORY", tmp_path / "yield.json")
    monkeypatch.setattr(lr, "STATUS_HISTORY", tmp_path / "status.json")
    monkeypatch.setattr(lr, "REPAIR_STATE", tmp_path / "repair.json")
    return tmp_path


def write(path, obj):
    path.write_text(json.dumps(obj))


def test_two_empty_nights_from_a_site_that_ran_is_a_candidate(state):
    write(state / "yield.json", {"reed": [12, 0, 0]})
    write(state / "status.json", {"reed": ["ok", "ok", "ok"]})
    assert lr.dry_candidates() == ["reed"]


def test_a_skipped_site_is_never_a_candidate(state):
    """The failure guardian actually had. No yield entries because it never ran;
    the fault is the budget, and the scraper is not the file to edit."""
    write(state / "yield.json", {"guardian": [0, 0]})
    write(state / "status.json", {"guardian": ["skipped", "skipped"]})
    assert lr.dry_candidates() == []


def test_a_timed_out_site_is_not_a_candidate(state):
    """A timeout says the site was cut off, not that its selectors broke."""
    write(state / "yield.json", {"reed": [0, 0]})
    write(state / "status.json", {"reed": ["ok", "timeout"]})
    assert lr.dry_candidates() == []


def test_one_productive_night_disqualifies(state):
    write(state / "yield.json", {"reed": [0, 5]})
    write(state / "status.json", {"reed": ["ok", "ok"]})
    assert lr.dry_candidates() == []


def test_too_little_history_is_not_enough(state):
    """A site scraped once, returning nothing, has not shown a pattern yet."""
    write(state / "yield.json", {"reed": [0]})
    write(state / "status.json", {"reed": ["ok"]})
    assert lr.dry_candidates() == []


def test_missing_status_history_still_allows_a_candidate(state):
    """The status history is newer than the yield history. A site with yields
    recorded and no status yet must not be silently un-repairable."""
    write(state / "yield.json", {"reed": [0, 0]})
    write(state / "status.json", {})
    assert lr.dry_candidates() == ["reed"]


def test_attempts_are_capped(state, monkeypatch):
    write(state / "yield.json", {"reed": [0, 0]})
    write(state / "status.json", {"reed": ["ok", "ok"]})
    write(state / "repair.json",
          {"reed": {"attempts": lr.MAX_ATTEMPTS_PER_SITE, "outcome": "failed"}})
    site, why = lr.pick_site(None)
    assert site is None
    assert "attempted" in why


def test_a_site_already_waiting_on_a_human_is_left_alone(state):
    """A verified fix sits on a branch until someone merges it. Attempting the
    same site again would rebuild the same repair on top of an unmerged one."""
    write(state / "yield.json", {"reed": [0, 0]})
    write(state / "status.json", {"reed": ["ok", "ok"]})
    write(state / "repair.json",
          {"reed": {"attempts": 1, "branch": "loop/repair-reed-20260821"}})
    site, _ = lr.pick_site(None)
    assert site is None


def test_only_one_site_is_attempted_per_run(state):
    write(state / "yield.json", {"reed": [0, 0], "guardian": [0, 0]})
    write(state / "status.json", {"reed": ["ok", "ok"], "guardian": ["ok", "ok"]})
    assert len(lr.dry_candidates()) == 2
    site, _ = lr.pick_site(None)
    assert site in {"reed", "guardian"}


def test_a_site_with_no_scraper_file_is_skipped(state):
    write(state / "yield.json", {"nonesuch": [0, 0]})
    write(state / "status.json", {"nonesuch": ["ok", "ok"]})
    site, _ = lr.pick_site(None)
    assert site is None


def test_forcing_a_site_still_requires_the_file_to_exist(state):
    site, why = lr.pick_site("nonesuch")
    assert site is None
    assert "no scraper" in why


def test_corrupt_history_does_not_crash_the_loop(state):
    (state / "yield.json").write_text("not json")
    (state / "status.json").write_text("{{{")
    assert lr.dry_candidates() == []


def test_the_agent_gets_no_shell(state):
    """Verification is this script's job. An unattended agent with Bash is how a
    repair loop becomes an incident."""
    assert "Bash" not in lr.ALLOWED_TOOLS
    assert "Write" not in lr.ALLOWED_TOOLS


def test_the_prompt_names_the_scope_and_the_test(state):
    body = lr.PROMPT.format(scraper="scraper_reed.py", nights=2)
    assert "ONLY `scraper_reed.py`" in body
    assert "verified by actually running" in body.lower()


def test_kill_switch_is_a_file_in_the_repo(state):
    assert lr.KILL_SWITCH.name == ".loop-pause"
    assert lr.KILL_SWITCH.parent == lr.ROOT
