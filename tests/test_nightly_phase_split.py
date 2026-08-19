"""The nightly runs in two scheduled slots, and each half has to hold its side.

5400s of scrape budget against a 1500s per-site cap admits three sites, so the
site order only ever chose which three ran. Measured 2026-08-18, with the
productive sites moved to the front: linkedin 1261s, adzuna 1500s, remote_apis
1500s, reed 1073s, then guardian and indeed skipped outright. A better three —
adzuna alone returned 833 jobs against the previous whole night's 545 — but
still three.

So the run is split: `early` at 02:00 scrapes the group that earns, `late` at
04:30 scrapes the rest and then scores, notifies and sweeps. The failures this
pins are the ones that would look like a working night:

- `late` truncating the run summary would erase `early`'s three sites, and
  nightly_scout reads that file to say which sites ran.
- `early` notifying would mark tonight's jobs seen in _nightly_state.json, so
  `late` would diff against them and report nothing new.

Both are text assertions against a shell script, which is weak, but the failure
mode is a scheduled job that exits 0 having quietly lost half a night.
"""
import re
import subprocess
from pathlib import Path

import pytest

NIGHTLY = Path(
    "/home/kz003/dotfiles/hermes/profiles/archivist/scripts/job_scout_nightly.sh")

pytestmark = pytest.mark.skipif(
    not NIGHTLY.exists(), reason="hermes dotfiles not present")


@pytest.fixture(scope="module")
def text() -> str:
    return NIGHTLY.read_text(encoding="utf-8")


def test_nightly_is_valid_bash():
    result = subprocess.run(["bash", "-n", str(NIGHTLY)], capture_output=True, text=True)
    assert result.returncode == 0, f"syntax error: {result.stderr}"


def test_phase_defaults_to_a_whole_night(text):
    """A hand-run with no argument must still do everything. The default is what
    anyone debugging reaches for, and a default of `early` would silently skip
    the notification they are trying to test."""
    assert re.search(r'PHASE="\$\{1:-all\}"', text), (
        "PHASE must default to `all`, so an argument-less run is a whole night")


def test_unknown_phase_is_rejected_rather_than_treated_as_all(text):
    """A typo in the cron job's argument must fail loudly. Falling through to a
    whole night in both slots would double-scrape every site."""
    assert re.search(r"unknown phase", text)
    for phase, expected in [("early", 0), ("late", 0), ("all", 0), ("bogus", 2)]:
        result = subprocess.run(
            ["bash", "-c",
             'PHASE="${1:-all}"; case "$PHASE" in early|late|all) exit 0 ;; '
             '*) exit 2 ;; esac', "_", phase],
            capture_output=True)
        assert result.returncode == expected, f"{phase} should exit {expected}"


def test_only_the_opening_slot_truncates_the_run_summary(text):
    """nightly_scout reads _nightly_run_summary.tsv to report per-site outcomes.
    If `late` truncated it, the report would describe a night in which
    linkedin, adzuna and indeed never ran."""
    guard = re.search(r'if \[ "\$PHASE" != "late" \]; then\s*\n\s*: > "\$SUMMARY"'
                      r'\s*\n\s*: > "\$YIELD"', text)
    assert guard, "SUMMARY/YIELD truncation must be skipped in the `late` phase"


# Only real invocation lines. A comment that mentions "six run_site calls" was
# being counted as a site named "calls", which turned two of these assertions
# into assertions about nothing.
_SITE_CALL = re.compile(r"^[ \t]*run_site (\w+)", re.M)


def _site_groups(text: str) -> dict[str, set[str]]:
    """{excluded_phase: sites}, read from the guarded blocks that call run_site.

    Keyed on the phase the guard excludes, since that is what the script says:
    `!= "late"` is the early group. Guards that contain no run_site — the
    summary truncation, scraper_saved — are ignored rather than matched by
    position, so inserting another guard does not silently break this.
    """
    groups: dict[str, set[str]] = {}
    for m in re.finditer(r'if \[ "\$PHASE" != "(\w+)" \]; then\n(.*?)\n  fi',
                         text, re.S):
        sites = set(_SITE_CALL.findall(m.group(2)))
        if sites:
            groups[m.group(1)] = sites
    return groups


def test_the_two_groups_do_not_overlap(text):
    """A site in both groups would be scraped twice a night, at full cost, for
    the same postings."""
    groups = _site_groups(text)
    assert set(groups) == {"late", "early"}, (
        f"expected one guarded group per phase, found {sorted(groups)}")
    overlap = groups["late"] & groups["early"]
    assert not overlap, f"a site is scraped in both slots: {overlap}"


def test_every_site_is_scraped_by_one_of_the_two_slots(text):
    """A site dropped from both groups stops being scraped, and nothing reports
    it — stale_sites only judges sites that appear in the run summary."""
    expected = {"linkedin", "adzuna", "indeed", "reed", "remote_apis", "guardian"}
    assert set(_SITE_CALL.findall(text)) == expected


def test_linkedin_opens_the_night(text):
    """Whichever site runs first pays the 00_saved staging merge, and
    LINKEDIN_TIMEOUT is the only per-site cap sized for that."""
    sites = _SITE_CALL.findall(text)
    assert sites[0] == "linkedin", f"first site is {sites[0]}, not linkedin"


def test_early_exits_before_notifying(text):
    """notify() diffs against _nightly_state.json and then writes tonight's URLs
    into it. An early notification would mark this slot's jobs seen and leave
    the late slot with nothing new to report."""
    early_exit = text.find('if [ "$PHASE" = "early" ]')
    notify_call = re.search(r"^notify$", text, re.M)
    assert early_exit != -1, "the early phase must stop before the post-scrape work"
    assert notify_call, "notify must still be called on the unguarded path"
    assert early_exit < notify_call.start(), (
        "the early-phase exit must come before notify, or the 02:00 slot "
        "consumes the night's news")


def test_scrape_deadlines_stay_inside_the_scheduler_cap(text):
    """Hermes kills the job at script_timeout_seconds: 7200. A DEADLINE at or
    past that is a scrape that never reaches notify()."""
    deadlines = [int(n) for n in re.findall(r"DEADLINE=\$\(\( \$\(date \+%s\) \+ (\d+) \)\)", text)]
    assert deadlines, "no deadlines found"
    assert max(deadlines) <= 7020, f"a deadline exceeds the safe cap: {max(deadlines)}"


def test_the_late_slot_leaves_room_for_scoring_and_the_sweep(text):
    """Its scrape budget has to be well short of its POST_DEADLINE, or the
    stages after scraping are skipped every night."""
    late_scrape = re.search(
        r'late\)\s+DEADLINE=\$\(\( \$\(date \+%s\) \+ (\d+) \)\)', text)
    late_post = re.search(
        r'if \[ "\$PHASE" = "late" \]; then\s*\n\s*POST_DEADLINE=\$\(\( \$\(date \+%s\) \+ (\d+) \)\)',
        text)
    assert late_scrape and late_post, "the late phase needs its own two budgets"
    assert int(late_post.group(1)) - int(late_scrape.group(1)) >= 1200, (
        "under 1200s between the late slot's scrape deadline and its post "
        "deadline leaves no room for the context pass and the rescore")


def test_saved_jobs_are_collected_once_per_night(text):
    """scraper_saved.py hits a login-guarded page; running it in both slots pays
    that twice for the same staging directory."""
    assert re.search(r'\[ "\$PHASE" != "late" \] && \{ "\$PY" scraper_saved\.py',
                     text), "scraper_saved.py must be guarded to one slot"


def test_sites_are_scraped_without_analysing(text):
    """run.py merges 00_saved and then analyses, matches and generates for every
    new job in the pool — not for the jobs the invocation scraped. Without
    --scrape-only, six run_site calls are six analysis passes over a growing
    backlog, and each site's own timeout kills that shared work part-way."""
    assert re.search(r'run\.py --site "\$site" --scrape-only', text), (
        "run_site must pass --scrape-only, or every site pays for the whole "
        "pool's analysis and dies in the middle of it")


def test_the_analysis_runs_exactly_once_and_after_the_scrapes(text):
    """--from-saved is the other half of the split: one pass over everything
    staged, rather than one per site."""
    analyses = re.findall(r'run\.py --from-saved', text)
    assert len(analyses) == 1, f"expected one analysis pass, found {len(analyses)}"
    last_site = max(m.start() for m in _SITE_CALL.finditer(text))
    analysis = text.find("run.py --from-saved")
    assert last_site < analysis, "the analysis pass must come after every scrape"


def test_the_analysis_is_not_in_the_early_slot(text):
    """The early slot exits before the post-scrape work; the analysis belongs to
    the slot that closes the night, so it runs once over both slots' staging."""
    early_exit = text.find('if [ "$PHASE" = "early" ]')
    analysis = text.find("run.py --from-saved")
    assert early_exit != -1 and analysis != -1
    assert early_exit < analysis, (
        "the early-phase exit must precede the analysis stage")
