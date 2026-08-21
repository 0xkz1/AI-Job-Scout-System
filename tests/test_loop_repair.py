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
    body = lr.PROMPT.format(scraper="scraper_reed.py", nights=2, doc=lr.SKILL_DOC)
    assert "ONLY `scraper_reed.py`" in body
    assert "verified by actually running" in body.lower()


def test_the_standing_knowledge_lives_in_a_file_the_prompt_points_at(state):
    """The loop-engineering frameworks call this the Skills element: write the
    project knowledge down once so the agent stops re-deriving it, and so the
    prompt stops growing a paragraph every time somebody learns something."""
    doc = lr.ROOT / lr.SKILL_DOC
    assert doc.exists(), f"{lr.SKILL_DOC} is missing; the prompt sends the agent to it"
    body = lr.PROMPT.format(scraper="scraper_reed.py", nights=2, doc=lr.SKILL_DOC)
    assert lr.SKILL_DOC in body


def test_the_skill_doc_states_the_staging_contract(state):
    """The break that is invisible in the log: a record without `url` is dropped
    by save_raw_to_saved, so the scraper reports a full count and stages
    nothing. An agent that does not know this can "fix" a parser into silence."""
    text = (lr.ROOT / lr.SKILL_DOC).read_text()
    assert "url" in text and "save_raw_to_saved" in text


def test_kill_switch_is_a_file_in_the_repo(state):
    assert lr.KILL_SWITCH.name == ".loop-pause"
    assert lr.KILL_SWITCH.parent == lr.ROOT


# ── The verification gate ────────────────────────────────────────────────────
#
# "Did it return anything at all" is a test an agent can pass without fixing
# anything: one fabricated record satisfies count > 0, and inventing a record is
# cheaper than repairing a parser. ever-better's rule for this is that the tool
# has to refuse the agent's laziest escape rather than instruct it not to take
# one. These pin the refusal.

def test_the_floor_is_drawn_from_the_sites_own_history(state):
    write(state / "yield.json", {"adzuna": [411, 833, 845, 0, 0]})
    assert lr.expected_floor("adzuna") == 845 // 4


def test_an_unknown_site_still_has_a_floor(state):
    """No history is not permission to pass on one record."""
    write(state / "yield.json", {})
    assert lr.expected_floor("nonesuch") == 3


def test_a_low_yielding_site_keeps_the_minimum_floor(state):
    write(state / "yield.json", {"guardian": [2, 0, 0]})
    assert lr.expected_floor("guardian") == 3


def _stage(work, site, rows):
    (work / "00_saved").mkdir(parents=True, exist_ok=True)
    (work / "00_saved" / f"_raw_{site}_20260821_000000.json").write_text(
        json.dumps(rows))


def test_staged_jobs_are_counted_by_distinct_absolute_url(tmp_path):
    """The number the scraper prints is a number the edited file chooses. What
    it actually staged is not."""
    _stage(tmp_path, "reed", [
        {"url": "https://reed.co.uk/1", "title": "A"},
        {"url": "https://reed.co.uk/1", "title": "A"},   # duplicate
        {"url": "not-a-url", "title": "B"},              # not absolute
        {"url": "https://reed.co.uk/2", "title": "C"},
    ])
    records, urls, titles = lr.inspect_staged(tmp_path, "reed")
    assert (records, urls, titles) == (4, 2, 3)


def test_missing_staging_reads_as_nothing(tmp_path):
    (tmp_path / "00_saved").mkdir()
    assert lr.inspect_staged(tmp_path, "reed") == (0, 0, 0)


def test_corrupt_staging_does_not_crash(tmp_path):
    (tmp_path / "00_saved").mkdir(parents=True)
    (tmp_path / "00_saved" / "_raw_reed_20260821_000000.json").write_text("{{{")
    assert lr.inspect_staged(tmp_path, "reed") == (0, 0, 0)


def test_repeated_titles_read_as_filler(tmp_path, state):
    """A parser that really walked a listing page returns about as many distinct
    titles as postings. Padding to clear the floor does not."""
    write(state / "yield.json", {"reed": [40, 0, 0]})
    rows = [{"url": f"https://reed.co.uk/{i}", "title": "Job"} for i in range(20)]
    _stage(tmp_path, "reed", rows)
    records, urls, titles = lr.inspect_staged(tmp_path, "reed")
    assert urls >= lr.expected_floor("reed"), "clears the URL floor"
    assert titles * 2 < records, "and is still rejected on distinct titles"


def test_the_agent_is_pluggable(state):
    """Neither installed agent worked unattended on 2026-08-21 — claude -p
    answers "Not logged in" from a subprocess and opencode's default provider
    account is suspended. Wiring the loop to one vendor would have made a setup
    problem into a rewrite."""
    assert lr.agent_command("hi")[0] == "claude"


def test_opencode_takes_its_model_from_the_environment(state, monkeypatch):
    monkeypatch.setattr(lr, "AGENT_KIND", "opencode")
    monkeypatch.setattr(lr, "AGENT_MODEL", "zai/glm-5.2")
    cmd = lr.agent_command("hi")
    assert cmd[:2] == ["opencode", "run"]
    assert "zai/glm-5.2" in cmd


def test_hermes_is_an_option_because_it_is_the_harness_the_cron_uses(state, monkeypatch):
    monkeypatch.setattr(lr, "AGENT_KIND", "hermes")
    monkeypatch.setattr(lr, "AGENT_PROFILE", "archivist")
    cmd = lr.agent_command("hi")
    assert cmd[0] == "hermes"
    assert "-z" in cmd and "archivist" in cmd


def test_every_observed_auth_failure_is_recognised(state):
    """All three harnesses report an auth failure on stdout and exit 0, so the
    return code cannot separate "could not start" from "found nothing to do"."""
    seen = ["Not logged in",                 # claude -p
            "Account kazuki001 is suspended",  # opencode default provider
            "No access token found for Nous Portal login",  # hermes default
            "No usable credentials found for provider 'zai'"]  # hermes archivist
    for line in seen:
        assert any(m.lower() in line.lower() for m in
                   ("not logged in", "is suspended", "model not found",
                    "invalid api key", "authentication",
                    "no access token found", "no usable credentials")), line
