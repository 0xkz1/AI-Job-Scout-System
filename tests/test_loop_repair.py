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
    """claude -p answers "Not logged in" from a subprocess and opencode's default
    provider account is suspended. Wiring the loop to one vendor would have made
    a setup problem into a rewrite."""
    assert lr.agent_command("hi")[0] == "hermes"


def test_the_default_agent_has_no_shell(state):
    """`-t file` leaves patch, read_file, search_files and write_file, and no way
    to run a shell — verified by asking the agent directly on 2026-08-21. The
    diff-scope check is what covers write_file being in that set."""
    cmd = lr.agent_command("hi")
    assert "-t" in cmd
    assert cmd[cmd.index("-t") + 1] == "file"
    assert "terminal" not in cmd


def test_the_default_route_is_the_gateway_not_a_profile_model(state):
    """archivist's own model needs a zai key nothing carries, and its five-deep
    fallback chain does not catch that — a missing credential aborts at startup
    while the chain only handles API errors at runtime."""
    cmd = lr.agent_command("hi")
    assert "custom:litellm-gateway" in cmd


def test_opencode_takes_its_model_from_the_environment(state, monkeypatch):
    monkeypatch.setattr(lr, "AGENT_KIND", "opencode")
    monkeypatch.setattr(lr, "AGENT_MODEL", "zai/glm-5.2")
    cmd = lr.agent_command("hi")
    assert cmd[:2] == ["opencode", "run"]
    assert "zai/glm-5.2" in cmd


def test_claude_remains_available_as_a_fallback_harness(state, monkeypatch):
    monkeypatch.setattr(lr, "AGENT_KIND", "claude")
    cmd = lr.agent_command("hi")
    assert cmd[0] == "claude" and "-p" in cmd
    assert "Bash" not in " ".join(cmd)


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


# ── The test gate ────────────────────────────────────────────────────────────
#
# Demanding an absolutely green suite failed a correct fix on 2026-08-21:
# mistral-medium repaired the break exactly, the scrape returned 69 distinct
# URLs against a floor of 16, and the attempt was discarded over a collection
# error that predated the agent. A gate that cannot tell "you broke this" from
# "this was already broken" rejects good work and teaches nobody anything.

def test_a_pre_existing_failure_does_not_sink_a_good_fix(state, monkeypatch):
    baseline = {"tests/test_pdf_bare_name_stays_frozen.py"}
    monkeypatch.setattr(lr, "failing_tests", lambda work: (set(baseline), ""))
    ok, why = lr.tests_have_no_new_failures(None, baseline)
    assert ok, why


def test_a_failure_the_agent_caused_is_still_caught(state, monkeypatch):
    baseline = {"tests/test_pdf_bare_name_stays_frozen.py"}
    after = baseline | {"tests/test_site_yield_warning.py::test_history_is_bounded"}
    monkeypatch.setattr(lr, "failing_tests", lambda work: (set(after), ""))
    ok, why = lr.tests_have_no_new_failures(None, baseline)
    assert not ok
    assert "newly failing" in why


def test_a_fixed_test_does_not_count_against_the_agent(state, monkeypatch):
    """Fewer red than the baseline is an improvement, not a violation."""
    baseline = {"a", "b"}
    monkeypatch.setattr(lr, "failing_tests", lambda work: ({"a"}, ""))
    ok, _ = lr.tests_have_no_new_failures(None, baseline)
    assert ok


def test_a_timed_out_suite_is_not_read_as_green(state, monkeypatch):
    monkeypatch.setattr(lr, "failing_tests",
                        lambda work: ({"__timeout__"}, "test suite timed out"))
    ok, why = lr.tests_have_no_new_failures(None, set())
    assert not ok and "timed out" in why


def test_the_gate_does_not_stop_at_the_first_failure(state):
    """-x cannot separate a pre-existing failure from a caused one, because it
    stops before seeing whether the rest moved."""
    import inspect
    src = inspect.getsource(lr.failing_tests)
    assert '"-x"' not in src


# ── Retry rounds ─────────────────────────────────────────────────────────────
#
# The agent cannot run the scraper, by design, so it cannot see whether its edit
# worked. Three runs against one planted break on 2026-08-21 produced one correct
# fix and two wrong ones from the same two models — and the third wrong one had
# diagnosed the bug correctly in prose before editing the wrong lines. Feeding
# the verifier's result back is the reflection step; handing over a shell is not.

def test_a_retry_carries_the_failure_and_the_diff(state):
    body = lr.RETRY_PROMPT.format(
        scraper="scraper_reed.py", why="still returns nothing",
        diff="- a\n+ b", round=2, max_rounds=lr.MAX_ROUNDS,
        floor_note="It needs at least 16 of them; the last run produced 0.")
    assert "still returns nothing" in body
    assert "- a" in body and "+ b" in body
    assert "Attempt 2 of" in body


def test_the_retry_names_the_common_failure(state):
    """A correct diagnosis followed by an edit in the wrong place is what
    actually happened, twice. Naming it is cheaper than hoping."""
    body = lr.RETRY_PROMPT.format(
        scraper="s.py", why="w", diff="d", round=2,
        max_rounds=lr.MAX_ROUNDS, floor_note="n")
    assert "wrong place" in body


def test_the_retry_keeps_the_same_scope_rule(state):
    body = lr.RETRY_PROMPT.format(
        scraper="scraper_reed.py", why="w", diff="d", round=2,
        max_rounds=lr.MAX_ROUNDS, floor_note="n")
    assert "ONLY `scraper_reed.py`" in body


def test_rounds_are_bounded(state):
    """Unbounded retry against a scraper that now needs a login is a standing
    bill. MAX_ATTEMPTS_PER_SITE bounds the nights; this bounds one night."""
    assert 2 <= lr.MAX_ROUNDS <= 5


def test_run_agent_uses_the_first_prompt_without_a_retry(state, monkeypatch):
    seen = {}
    monkeypatch.setattr(lr, "_run", lambda cmd, **kw: type(
        "R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    monkeypatch.setattr(lr, "agent_command",
                        lambda prompt: seen.setdefault("p", prompt) or ["true"])
    lr.run_agent(lr.ROOT, "reed", "scraper_reed.py", 2)
    assert "has stopped returning results" in seen["p"]
    assert "did not work" not in seen["p"]


# ── main()'s outer ring ──────────────────────────────────────────────────────
#
# Every experiment so far called attempt_repair directly, so the run log, the
# state file and the Telegram wording have never executed. loop-run-log.md has
# had an empty "Recent Runs" section since the day loop-init created it; an L1
# pipeline had nothing to write there and nothing ever did.

def test_a_run_is_appended_below_the_marker(tmp_path, monkeypatch):
    log = tmp_path / "loop-run-log.md"
    log.write_text("# Loop Run Log\n\n## Recent Runs\n\n"
                   "<!-- Loop appends below this line -->\n")
    monkeypatch.setattr(lr, "RUN_LOG", log)
    lr.append_run_log({"run_id": "2026-08-21T23:00:00", "outcome": "fix-proposed"})
    text = log.read_text()
    assert "<!-- Loop appends below this line -->" in text, "marker must survive"
    assert "fix-proposed" in text
    assert text.index("Recent Runs") < text.index("fix-proposed")


def test_a_second_run_does_not_overwrite_the_first(tmp_path, monkeypatch):
    log = tmp_path / "loop-run-log.md"
    log.write_text("<!-- Loop appends below this line -->\n")
    monkeypatch.setattr(lr, "RUN_LOG", log)
    lr.append_run_log({"run_id": "first"})
    lr.append_run_log({"run_id": "second"})
    text = log.read_text()
    assert "first" in text and "second" in text


def test_a_missing_run_log_does_not_crash_the_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(lr, "RUN_LOG", tmp_path / "nope.md")
    lr.append_run_log({"run_id": "x"})  # must not raise


def test_the_run_log_entry_carries_an_owner(state):
    """Owner, deadline, max rounds, evidence, stop reason — the loop-engineering
    checklist. An autonomous change with nobody accountable for reading it is
    how comprehension debt accumulates."""
    assert lr.OWNER


def test_the_state_file_survives_a_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(lr, "REPAIR_STATE", tmp_path / "repair.json")
    lr.save_repair_state({"reed": {"attempts": 1, "outcome": "failed"}})
    assert lr.load_json(tmp_path / "repair.json", {})["reed"]["attempts"] == 1
