"""The scheduled entrypoints must give Indeed a display and the right interpreter.

Two failures that only ever showed up on the cron path, never interactively:

1. Indeed answers a headless browser with a Cloudflare challenge, and the only
   way through is a headed relaunch, which needs an X display. Cron has none, so
   scraper_indeed raises CloudflareBlocked and the searches are lost — its own
   message says to wrap the command in xvfb-run, and neither entrypoint did.
   Verified by hand: under `xvfb-run -a`, DISPLAY becomes :99,
   _headed_display_available() returns True, and a headed chromium starts.

2. scraper_runner.sh called bare `python3` while run_cron.sh called the venv.
   They are not interchangeable — on 2026-08-13 scikit-learn was importable from
   the system interpreter and missing from the venv, so matcher's TF-IDF context
   fallback returned a constant 0.5 under one and a real score under the other.

Both are shell, so these are text assertions. They are still worth having: the
failure mode is a scheduled job that exits 0 while scraping nothing, which is
how Indeed once went 11 days contributing nothing with a green cron log.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINTS = [ROOT / "run_cron.sh", ROOT / "scraper_runner.sh"]


@pytest.mark.parametrize("script", ENTRYPOINTS, ids=lambda p: p.name)
def test_entrypoint_is_valid_bash(script):
    assert script.exists(), f"{script.name} is missing"
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, f"{script.name} has a syntax error: {result.stderr}"


@pytest.mark.parametrize("script", ENTRYPOINTS, ids=lambda p: p.name)
def test_entrypoint_falls_back_to_xvfb(script):
    text = script.read_text(encoding="utf-8")
    assert "xvfb-run" in text, (
        f"{script.name} runs Indeed with no X display fallback, so every "
        f"Cloudflare-challenged search is lost while the job still exits 0"
    )


@pytest.mark.parametrize("script", ENTRYPOINTS, ids=lambda p: p.name)
def test_the_display_socket_is_checked_not_just_the_variable(script):
    """DISPLAY set does not mean an X server is reachable. Cron inherits it from
    the desktop session that installed the crontab while having no access to
    that server — the exact condition that produced 11 silent days."""
    text = script.read_text(encoding="utf-8")
    assert "/tmp/.X11-unix/" in text, (
        f"{script.name} decides on DISPLAY alone; it must test the socket, "
        f"because an inherited-but-unreachable DISPLAY is the failure case"
    )


@pytest.mark.parametrize("script", ENTRYPOINTS, ids=lambda p: p.name)
def test_python_is_the_venv_not_whatever_is_on_path(script):
    text = script.read_text(encoding="utf-8")
    assert ".venv/bin/python" in text, (
        f"{script.name} does not prefer the venv interpreter; the two disagree "
        f"about which packages exist, and scikit-learn's absence silently turns "
        f"the TF-IDF context score into a constant"
    )
    bare = re.findall(r"^\s*(?:if\s+)?python3\s+\w+\.py", text, re.M)
    assert not bare, f"{script.name} still invokes a bare python3: {bare}"


HERMES_NIGHTLY = Path(
    "/home/kz003/dotfiles/hermes/profiles/archivist/scripts/job_scout_nightly.sh")


def test_run_cron_says_it_is_not_the_scheduled_one():
    """The scheduled nightly is a Hermes cron job on the `archivist` profile,
    invisible to `crontab -l`, to systemd timers, and to a bare
    `hermes cron list` — that shows the default profile only. Believing nothing
    was scheduled is how run_cron.sh got rewritten as a parallel nightly;
    scheduling both would run two pipelines against one _analyzed.json."""
    text = (ROOT / "run_cron.sh").read_text(encoding="utf-8")
    assert "NOT the scheduled nightly" in text
    assert "job_scout_nightly.sh" in text, (
        "run_cron.sh must name the script that really runs, or the next reader "
        "repeats the same mistake"
    )


@pytest.mark.skipif(not HERMES_NIGHTLY.exists(), reason="hermes dotfiles not present")
@pytest.mark.parametrize("script,reason", [
    ("rescore_context.py", "scores stay on whatever persona produced them; "
                           "llm_context_backfill skips anything already LLM-scored"),
    ("rereview_top.py", "only new arrivals are reviewed, so each night's "
                        "leftovers accumulate unreviewed forever"),
])
def test_the_real_nightly_has_the_stages_this_repo_added(script, reason):
    text = HERMES_NIGHTLY.read_text(encoding="utf-8")
    assert script in text, f"the scheduled nightly omits {script}: {reason}"


@pytest.mark.skipif(not HERMES_NIGHTLY.exists(), reason="hermes dotfiles not present")
def test_the_real_nightly_sweeps_after_it_notifies():
    """notify() diffs against _nightly_state.json, so it reviews what is new.
    Sweeping first would review tonight's arrivals and notify would review them
    again — the diff is keyed on state, not on whether a review file exists."""
    text = HERMES_NIGHTLY.read_text(encoding="utf-8")
    assert text.index("\nnotify\n") < text.index("rereview_top.py"), (
        "the backlog sweep runs before notify, duplicating tonight's reviews"
    )


def test_the_scraper_still_tells_the_operator_to_use_xvfb():
    """The entrypoints implement what scraper_indeed's message advises. If that
    advice is ever reworded away, these wrappers lose their stated reason."""
    text = (ROOT / "scraper_indeed.py").read_text(encoding="utf-8")
    assert "xvfb-run" in text
    assert "_headed_display_available" in text


# The nightly is only a nightly if it runs every stage. Each of these was
# missing at some point and the absence showed up as a quiet backlog rather than
# an error: url-list.md unread for weeks, five of six sites never scraped, and
# 237 jobs carrying a generated CV with no review because nothing invoked the
# reviewer.
@pytest.mark.parametrize("script,reason", [
    ("scraper_url_list.py", "pasted job links are never ingested"),
    ("scraper_saved.py", "manually saved jobs are never ingested"),
    ("run.py", "nothing is scraped, analysed or matched"),
    ("nightly_scout.py", "new arrivals are never reviewed — run.py does not review"),
    ("rereview_top.py", "the un-reviewed backlog is never swept, only new arrivals"),
    ("rescore_context.py", "jobs already in the DB keep scores from an older persona"),
])
def test_the_nightly_runs_every_stage(script, reason):
    text = (ROOT / "run_cron.sh").read_text(encoding="utf-8")
    assert script in text, f"run_cron.sh omits {script}: {reason}"


def test_the_backfill_does_not_rewrite_reviews_it_already_has():
    """rereview_top.py overwrites existing reviews by default — correct when the
    reviewer's logic has changed, ruinous as a nightly habit, since it would pay
    for every review in the selection every single night."""
    commands = _commands(ROOT / "run_cron.sh")
    assert "rereview_top.py --new-only" in commands, (
        "the nightly backfill must pass --new-only or it re-reviews the whole "
        "selection every night"
    )


def test_the_rescore_is_capped_and_runs_before_the_reviews():
    """Two things at once, because both are easy to get wrong.

    Capped: context_persona_chars keys a score to the persona that produced it,
    so one edited line of timeline.md marks every job stale — 1,642 of them the
    night this was added. Uncapped that is a six-hour LLM bill for a profile
    tweak; capped it converges over a few nights.

    Ordered: the review stages rank the pool, so they have to see scores from
    the persona in force now, not the one from before the pipeline ran.
    """
    commands = _commands(ROOT / "run_cron.sh")
    rescore = re.search(r"^stage\s+rescore\s.*$", commands, re.M)
    assert rescore, "no rescore stage"
    assert "--limit" in rescore.group(0), (
        "an uncapped rescore turns any profile edit into a full-corpus LLM run"
    )
    order = re.findall(r"^stage\s+(\w+)\s", commands, re.M)
    assert order.index("rescore") < order.index("review"), (
        "reviews would rank on scores the rescore is about to replace"
    )
    assert order.index("pipeline") < order.index("rescore"), (
        "the rescore should see everything the pipeline just ingested"
    )


def test_every_stage_counts_towards_the_exit_code():
    """The summary loop and the exit-code loop are separate lists, so a stage
    added to one and not the other is silently excluded from the verdict."""
    commands = _commands(ROOT / "run_cron.sh")
    declared = set(re.findall(r"^stage\s+(\w+)\s", commands, re.M))
    assert declared, "no stages found"
    for names in re.findall(r"for k in ([\w\s]+); do", commands):
        listed = set(names.split())
        assert listed == declared, (
            f"stage list {sorted(listed)} does not match the stages actually "
            f"run, {sorted(declared)}"
        )


def _commands(script: Path) -> str:
    """The script with comments stripped.

    Asserting over raw text is what made this test fail on the comment
    explaining the very flag it forbids. Behaviour lives in the commands.
    """
    return "\n".join(line for line in script.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#"))


def test_the_pipeline_stage_is_not_pinned_to_one_site():
    """A single-site nightly meant LinkedIn, Reed, Adzuna, Guardian and the
    remote APIs contributed nothing on the scheduled path."""
    assert "--site" not in _commands(ROOT / "run_cron.sh"), (
        "the nightly pins run.py to one site; with no --site it covers them all"
    )


def test_one_failing_stage_does_not_cancel_the_others():
    """A flaky site must not cost the night its reviews. `set -e` would end the
    run on the first non-zero exit."""
    text = (ROOT / "run_cron.sh").read_text(encoding="utf-8")
    assert "set -euo" not in text, "set -e aborts the nightly on the first stage that fails"
    assert "timeout" in text, "a hung browser would otherwise eat the whole night"


# --- the stage lists have to stay in step with the stages -------------------

def _stage_names(text: str) -> list[str]:
    return re.findall(r"^stage\s+(\S+)\s", text, re.MULTILINE)


def test_run_cron_reports_every_stage_it_runs():
    """run_cron.sh's own comment: the summary "silently under-reports if a stage
    is added and not listed here". Two lists, both hand-maintained — and the
    second one decides the exit code, so a stage missing from it cannot rescue a
    night where everything else failed."""
    text = (ROOT / "run_cron.sh").read_text(encoding="utf-8")
    stages = _stage_names(text)
    assert stages, "no stages found — the parser has drifted from the script"
    for loop in re.findall(r"^for k in ([^;]+); do", text, re.MULTILINE):
        listed = loop.split()
        missing = [s for s in stages if s not in listed]
        assert not missing, f"stages missing from a summary/exit list: {missing}"


def test_the_expiry_check_runs_before_anything_that_spends_on_a_posting():
    """A closed posting was re-scored, re-reviewed and handed fresh documents
    for as long as it sat in the database. The tick is a job-scoped lock, so it
    only helps if it is set before the stages that read it."""
    text = (ROOT / "run_cron.sh").read_text(encoding="utf-8")
    stages = _stage_names(text)
    assert "expiry" in stages, "run_cron.sh no longer checks for closed postings"
    for later in ("rescore", "review", "backfill"):
        assert stages.index("expiry") < stages.index(later), (
            f"expiry runs after {later}, so {later} still pays for closed postings")


def test_the_expiry_check_runs_after_the_pipeline():
    """run_stage clamps a stage to the remaining budget, so a check placed above
    the night's real work takes its hours."""
    stages = _stage_names((ROOT / "run_cron.sh").read_text(encoding="utf-8"))
    assert stages.index("pipeline") < stages.index("expiry")


NIGHTLY = Path.home() / "dotfiles/hermes/profiles/archivist/scripts/job_scout_nightly.sh"


def test_the_scheduled_nightly_checks_for_closed_postings_too():
    """run_cron.sh is the manual equivalent, not the scheduled job — its own
    header says anything belonging in the real nightly belongs in
    job_scout_nightly.sh. A fix applied to one and not the other is a fix that
    never runs."""
    if not NIGHTLY.exists():
        pytest.skip("hermes archivist profile not present on this machine")
    text = NIGHTLY.read_text(encoding="utf-8")
    assert "check_expired.py" in text, (
        "the scheduled nightly does not check for closed postings, so the "
        "review and regeneration stages keep paying for them")
    assert text.index("run.py --from-saved") < text.index("check_expired.py"), (
        "the expiry check must not take budget from the analysis pass")
    for later in ("rescore_context.py", "rereview_top.py", "regen_match_reports.py"):
        assert text.index("check_expired.py") < text.index(later), (
            f"{later} runs before the expiry check, so it still pays for "
            f"closed postings")
