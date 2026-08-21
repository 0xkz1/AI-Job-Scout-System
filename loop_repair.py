#!/usr/bin/env python3
"""L2 repair loop — attempt one scraper fix a night, verify it, stop at a branch.

This is the first thing here that changes source code without a human asking. It
is allowed to because the failure it targets has an objective test: a scraper
whose selectors stopped matching returns zero jobs while exiting clean, and
`run.py --site X --scrape-only` says in under three minutes whether that is
still true. Nothing else in this repo has a pass/fail that cheap, which is why
the loop is scoped to this one failure and not to "fix what is broken".

What it will not do, by construction rather than by instruction:

  * It never works in the main tree. Every attempt happens in a `git worktree`
    that is deleted unless the fix verifies.
  * It never merges, never pushes, never touches the nightly script, the cron
    jobs, config.yaml or .env. A verified fix is left on a branch for a human.
  * The agent it spawns has no Bash tool. It reads and edits, and this script
    runs the verification. Unattended arbitrary command execution is the thing
    that turns a repair loop into an incident.
  * A diff touching anything but the one scraper is discarded unread.
  * Two failed attempts on a site and it stops trying until a human clears the
    state file. A loop that retries a genuinely unfixable scraper every night is
    a standing bill with no ceiling.

Trigger is `dry_sites`, not `stale_sites`. Dry means the site ran, exited clean
and returned nothing — a broken scraper. Stale includes budget skips and
timeouts, where the scraper is usually fine and the fault is in how long the
sites before it took; pointing an agent at scraper_guardian.py because the
budget ran out would be a fix for the wrong file.

Usage:
    python3 loop_repair.py                # one attempt, if a site qualifies
    python3 loop_repair.py --dry-run      # decide and report, spawn nothing
    python3 loop_repair.py --site reed    # force a candidate (still verified)

Its stdout is a Telegram message when it did something and empty when it did
not, matching the nightly's contract.
"""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "10_output"
YIELD_HISTORY = OUTPUT_DIR / "_nightly_site_yield_history.json"
STATUS_HISTORY = OUTPUT_DIR / "_nightly_site_status_history.json"
REPAIR_STATE = OUTPUT_DIR / "_loop_repair_state.json"
RUN_LOG = ROOT / "loop-run-log.md"
KILL_SWITCH = ROOT / ".loop-pause"

# Matches nightly_scout.DRY_NIGHTS_BEFORE_WARNING. Imported rather than repeated
# where possible; this constant is the fallback if that import fails.
DRY_NIGHTS = 2

# Two attempts, then the site is left alone until a human empties the state file.
# The loop cannot tell "the selectors moved again" from "this site now needs a
# login", and the second is not something an agent fixes by editing a file.
MAX_ATTEMPTS_PER_SITE = 2

# Every entry in the run log names a human. An autonomous change with no owner
# is one nobody is accountable for reading, and unread agent-written code is how
# comprehension debt accumulates until the repo stops being understood.
OWNER = os.environ.get("LOOP_OWNER", "kz003")

# Rounds of edit-then-verify inside one attempt.
#
# Three runs against the same planted break on 2026-08-21: groq-review fixed the
# wrong thing and reported success; mistral-medium fixed it exactly (69 distinct
# URLs against a floor of 16); mistral-medium again diagnosed it correctly in
# prose — "the _job() function would create entries without the required url
# key" — and then edited the callers instead of _job(). Same model, opposite
# outcomes. The variance is in the agent, and the gate caught every wrong answer.
#
# The third agent ended its report with "To verify: run scraper_remote_apis.py
# and check for non-zero job counts". It wanted the check and had no way to run
# one, by design. So the loop runs it and hands back the result, rather than
# handing over a shell.
MAX_ROUNDS = 3

AGENT_TIMEOUT = 900
VERIFY_TIMEOUT = 900
TEST_TIMEOUT = 600

# No Bash. The agent reads the scraper and edits it; this script runs the only
# command that decides anything.
ALLOWED_TOOLS = "Read,Edit,Grep,Glob"

# Which coding agent does the editing. Configurable because on 2026-08-21
# neither installed one worked unattended out of the box, and the loop is
# otherwise complete: `claude -p` answers "Not logged in" from a subprocess even
# with ANTHROPIC_BASE_URL unset — this harness holds its credentials in-process —
# and `opencode run` authenticates fine but its default provider account is
# suspended. Both are one line of setup away, and neither is a reason to wire the
# loop to one vendor.
#
#   LOOP_AGENT=hermes    (default)  through the LiteLLM gateway on :4001
#   LOOP_AGENT=claude               needs `claude /login`, or ANTHROPIC_API_KEY
#   LOOP_AGENT=opencode             needs LOOP_AGENT_MODEL=<provider>/<model>
#
# hermes, because it is the harness the nightly cron already runs under and the
# one whose sessions accumulate. Getting there took two wrong conclusions worth
# recording: `hermes -z` fails on a profile whose model has no key AND DOES NOT
# FALL THROUGH — archivist has a five-deep fallback chain ending at local ollama
# and still aborted on the first entry, because a missing credential is a config
# error at startup and the chain only catches API errors at runtime. And the
# gateway was already wired: `custom:litellm-gateway` on http://localhost:4001/v1
# has been in the default profile's providers the whole time, serving groq,
# mistral, nvidia, zai and ollama behind one endpoint.
#
# `-t file` is the safety property. It leaves the agent patch, read_file,
# search_files and write_file, and no way to run a shell — verified by asking it.
AGENT_KIND = os.environ.get("LOOP_AGENT", "hermes")
AGENT_MODEL = os.environ.get("LOOP_AGENT_MODEL", "groq-review")
AGENT_PROVIDER = os.environ.get("LOOP_AGENT_PROVIDER", "custom:litellm-gateway")
AGENT_PROFILE = os.environ.get("LOOP_AGENT_PROFILE", "")
AGENT_TOOLSETS = os.environ.get("LOOP_AGENT_TOOLSETS", "file")

PY = str(ROOT / ".venv" / "bin" / "python3")
if not os.access(PY, os.X_OK):
    PY = "python3"


def _log(msg: str) -> None:
    """Progress goes to stderr. stdout is reserved for the Telegram message."""
    print(msg, file=sys.stderr, flush=True)


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 60,
         env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, timeout=timeout,
                          capture_output=True, text=True,
                          env={**os.environ, **(env or {})})


# ── State ────────────────────────────────────────────────────────────────────

def load_json(path: Path, default):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, type(default)) else default
    except Exception:
        return default


def save_repair_state(state: dict) -> None:
    try:
        REPAIR_STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False))
    except OSError as e:
        _log(f"  could not write repair state: {e}")


# ── Candidate selection ──────────────────────────────────────────────────────

def dry_candidates() -> list[str]:
    """Sites that ran and returned nothing for DRY_NIGHTS consecutive nights.

    Read from the same history nightly_scout reports from, so the loop acts on
    exactly what the human was told. A site with no history yet, or one whose
    last night produced anything, is not a candidate.
    """
    try:
        sys.path.insert(0, str(ROOT))
        import nightly_scout
        nights = nightly_scout.DRY_NIGHTS_BEFORE_WARNING
    except Exception:
        nights = DRY_NIGHTS

    yields = load_json(YIELD_HISTORY, {})
    statuses = load_json(STATUS_HISTORY, {})
    out = []
    for site, history in yields.items():
        if not isinstance(history, list):
            continue
        recent = history[-nights:]
        if len(recent) < nights or any(recent):
            continue
        # It has to have RUN those nights. A site skipped on the budget records
        # no yield entry at all, so its history can look dry while the scraper
        # was never given a chance — that is a budget problem, not this loop's.
        recent_status = (statuses.get(site) or [])[-nights:]
        if recent_status and not all(s == "ok" for s in recent_status):
            continue
        out.append(site)
    return sorted(out)


def scraper_path(site: str) -> Path | None:
    for name in (f"scraper_{site}.py", f"scraper_{site}_guest.py"):
        if (ROOT / name).exists():
            return ROOT / name
    return None


def pick_site(forced: str | None) -> tuple[str | None, str]:
    """(site, why-not). Exactly one site per run: an attempt is a real spend and
    two at once doubles it before the first has proved the loop works."""
    state = load_json(REPAIR_STATE, {})

    if forced:
        if not scraper_path(forced):
            return None, f"no scraper file for {forced}"
        return forced, ""

    candidates = dry_candidates()
    if not candidates:
        return None, "no site has been dry long enough"

    for site in candidates:
        entry = state.get(site) or {}
        if entry.get("attempts", 0) >= MAX_ATTEMPTS_PER_SITE:
            _log(f"  {site}: {entry['attempts']} attempts already, leaving it")
            continue
        if entry.get("branch"):
            _log(f"  {site}: fix already waiting on {entry['branch']}")
            continue
        if not scraper_path(site):
            _log(f"  {site}: no scraper file")
            continue
        return site, ""
    return None, "every dry site is already attempted or waiting on a human"


# ── The attempt ──────────────────────────────────────────────────────────────

# The knowledge that does not change between attempts lives in docs/, not here.
# A prompt that re-explains the repo every night is one that grows by a
# paragraph every time somebody learns something, and the agent re-derives the
# same conclusions from it each run. This says what is wrong tonight; the file
# says how scrapers here work.
SKILL_DOC = "docs/scraper-repair.md"

PROMPT = """\
`{scraper}` in this repository has stopped returning results. It runs to
completion and exits 0, and has scraped exactly zero jobs on each of the last
{nights} nightly runs. Every other site is still returning normally, so the
fault is in this file rather than in the network or the pipeline around it.

Read `{doc}` first. It covers the shape every scraper here has, the one key a
returned job must carry, the budget mechanism not to rewrite, the measured time
each site is allowed, and how your change will be judged. It exists so you do
not have to work any of that out from the code.

Then read `{scraper}` and fix the selection so it matches the page again.

Constraints, all of them enforced after you finish:

  * Edit ONLY `{scraper}`. A change to any other file causes the whole attempt
    to be thrown away, including your work on this one.
  * Do not add dependencies, do not change the function signatures other modules
    call, and do not touch anything to do with credentials.
  * Do not write tests, documentation, or comments explaining what you tried.
    Comment the code where the reason for a choice is not obvious from it.

Your change is verified by actually running the scraper against the live site.
So do not describe a fix — make one.
"""

RETRY_PROMPT = """\
Your previous change to `{scraper}` did not work. The scraper was run against
the live site and the result was:

    {why}

This is your change so far:

```diff
{diff}
```

The verification is not a style opinion — it counts the distinct absolute URLs
that actually reached staging. {floor_note}

Read the file again and reconsider. A correct diagnosis followed by an edit in
the wrong place is the common failure here: check that the line you are changing
is the one that produces the value being lost, and follow it all the way to
where the job dictionary is built.

The same constraints hold: edit ONLY `{scraper}`, no new dependencies, no
signature changes. Attempt {round} of {max_rounds}.
"""


def prepare_worktree(site: str, branch: str) -> Path:
    """A worktree with the untracked files a scrape needs, and its own staging.

    `.env` is symlinked because adzuna and the remote APIs need their keys, and
    00_saved is a fresh directory rather than the real one so a verification run
    cannot put jobs into tonight's staging.
    """
    path = Path(tempfile.mkdtemp(prefix=f"loop-repair-{site}-"))
    shutil.rmtree(path)  # git worktree add wants to create it
    _run(["git", "worktree", "add", "-b", branch, str(path), "HEAD"],
         cwd=ROOT, timeout=120)

    env_file = ROOT / ".env"
    if env_file.exists():
        try:
            (path / ".env").symlink_to(env_file)
        except OSError as e:
            _log(f"  could not link .env: {e}")
    (path / "00_saved").mkdir(exist_ok=True)
    (path / "10_output").mkdir(exist_ok=True)
    return path


def discard_worktree(path: Path, branch: str) -> None:
    _run(["git", "worktree", "remove", "--force", str(path)], cwd=ROOT, timeout=120)
    _run(["git", "branch", "-D", branch], cwd=ROOT, timeout=60)


def agent_command(prompt: str) -> list[str]:
    """The argv for whichever agent LOOP_AGENT names."""
    if AGENT_KIND == "opencode":
        cmd = ["opencode", "run"]
        if AGENT_MODEL:
            cmd += ["-m", AGENT_MODEL]
        return cmd + [prompt]
    if AGENT_KIND == "hermes":
        cmd = ["hermes", "-t", AGENT_TOOLSETS]
        if AGENT_PROFILE:
            cmd += ["-p", AGENT_PROFILE]
        if AGENT_MODEL:
            cmd += ["-m", AGENT_MODEL]
        if AGENT_PROVIDER:
            cmd += ["--provider", AGENT_PROVIDER]
        return cmd + ["-z", prompt]
    return ["claude", "-p", prompt,
            "--allowedTools", ALLOWED_TOOLS,
            "--permission-mode", "acceptEdits"]


def run_agent(work: Path, site: str, scraper: str, nights: int,
              retry: dict | None = None) -> str:
    if retry:
        prompt = RETRY_PROMPT.format(scraper=scraper, max_rounds=MAX_ROUNDS, **retry)
    else:
        prompt = PROMPT.format(scraper=scraper, nights=nights, doc=SKILL_DOC)
    result = _run(agent_command(prompt), cwd=work, timeout=AGENT_TIMEOUT)
    if result.returncode != 0:
        _log(f"  agent exited {result.returncode}: {result.stderr[-400:]}")
    # Both agents report an auth failure on stdout and still exit 0, so the
    # return code does not separate "could not start" from "found nothing to
    # change". Without this the loop would burn an attempt, record a no-op and
    # count it against MAX_ATTEMPTS_PER_SITE, twice, and then stop trying — all
    # without an agent ever having run.
    out = (result.stdout or "") + (result.stderr or "")
    for marker in ("Not logged in", "is suspended", "Model not found",
                   "Invalid API key", "authentication",
                   "No access token found", "No usable credentials"):
        if marker.lower() in out.lower():
            raise RuntimeError(f"agent could not start: {marker}")
    return out[-2000:]


def changed_files(work: Path) -> list[str]:
    result = _run(["git", "status", "--porcelain"], cwd=work, timeout=60)
    files = []
    for line in result.stdout.splitlines():
        if len(line) > 3:
            files.append(line[3:].strip())
    return files


def expected_floor(site: str) -> int:
    """How many jobs a restored scraper has to return to count as restored.

    A quarter of this site's best recorded night, never below three. The point
    is not statistical: it is that "did it return anything at all" is a test the
    agent can pass without fixing anything. One fabricated record satisfies
    count > 0, and the cheapest way to make a scraper return something is not to
    repair it. The gate has to be expensive to fake and cheap to pass honestly,
    and a real fix returns what the site used to return.
    """
    history = [n for n in (load_json(YIELD_HISTORY, {}).get(site) or [])
               if isinstance(n, int)]
    best = max(history) if history else 0
    return max(3, best // 4)


def inspect_staged(work: Path, site: str) -> tuple[int, int, int]:
    """(records, distinct absolute URLs, distinct titles) from what the scrape
    staged. The worktree has its own 00_saved, so this is only this run."""
    staged = sorted((work / "00_saved").glob(f"_raw_{site}_*.json"))
    records, urls, titles = 0, set(), set()
    for path in staged:
        try:
            rows = json.loads(path.read_text())
        except Exception:
            continue
        for row in rows if isinstance(rows, list) else []:
            records += 1
            url = str(row.get("url") or "")
            if url.startswith(("http://", "https://")):
                urls.add(url)
            title = str(row.get("title") or "").strip()
            if title:
                titles.add(title)
    return records, len(urls), len(titles)


def failing_tests(work: Path) -> tuple[set[str], str]:
    """Which tests are red right now, as a set of node ids.

    Not `-x`: stopping at the first one cannot tell a pre-existing failure from
    one the agent caused, and there is at least one of the former. Under a fresh
    worktree `tests/test_pdf_bare_name_stays_frozen.py` errors during collection
    on `NameError: name 'jobs' is not defined` while the same suite is green in
    the main tree, because importing app.py picks up state the worktree has not
    got.
    """
    try:
        result = _run([PY, "-m", "pytest", "tests/", "-q", "--no-header",
                       "-p", "no:cacheprovider"],
                      cwd=work, timeout=TEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"__timeout__"}, "test suite timed out"
    out = (result.stdout or "") + (result.stderr or "")
    red = set()
    for line in out.splitlines():
        line = line.strip()
        for prefix in ("FAILED ", "ERROR "):
            if line.startswith(prefix):
                red.add(line[len(prefix):].split(" ")[0])
    return red, ""


def tests_have_no_new_failures(work: Path, baseline: set[str]) -> tuple[bool, str]:
    """The second half of the quality gate, measured against a baseline rather
    than against green.

    Demanding an absolutely green suite failed a correct fix on 2026-08-21:
    mistral-medium repaired the break exactly, the scrape returned 69 distinct
    URLs against a floor of 16, and the run was thrown away over a collection
    error that was already there before the agent touched anything.

    So the baseline is taken in the same worktree before the agent runs, and
    only tests that were passing and are now red count. This is ever-better's
    freeze: hold the line where it is, and refuse anything that moves it the
    wrong way.
    """
    red, why = failing_tests(work)
    if why:
        return False, why
    new = red - baseline
    if new:
        listed = ", ".join(sorted(new)[:3])
        return False, f"{len(new)} test(s) newly failing: {listed}"
    return True, ""


def verify(work: Path, site: str, baseline: set[str] | None = None) -> tuple[bool, int, str]:
    """Run the real scraper in the worktree and judge what it brought back.

    --scrape-only is what makes this affordable: it stops before the merge and
    the LLM work, so a check costs the scrape alone — 43s for remote_apis, 144s
    for adzuna, 638s for guardian, measured 2026-08-21. Before that flag existed,
    verifying a scraper meant paying for the whole pool's analysis and could not
    finish inside any sensible timeout.

    Judged on distinct absolute URLs rather than the count the scraper reports,
    against a floor drawn from the site's own history. Both halves matter: the
    reported count is a number the edited file chooses, and a floor of one is a
    test that can be passed by fabricating a record instead of fixing anything.
    """
    yield_file = work / "10_output" / "_verify_yield.tsv"
    try:
        yield_file.unlink()
    except FileNotFoundError:
        pass
    try:
        result = _run([PY, "run.py", "--site", site, "--scrape-only"],
                      cwd=work, timeout=VERIFY_TIMEOUT,
                      env={"JIS_YIELD_FILE": str(yield_file)})
    except subprocess.TimeoutExpired:
        return False, 0, "verification timed out"

    if result.returncode != 0:
        return False, 0, f"scraper exited {result.returncode}"

    records, urls, titles = inspect_staged(work, site)
    floor = expected_floor(site)
    if urls < floor:
        return False, urls, (f"{urls} distinct URLs, floor is {floor}"
                             if urls else "still returns nothing")
    # Filler repeats. A scraper that really parsed a listing page returns as many
    # distinct titles as postings, give or take genuine duplicates.
    if titles * 2 < records:
        return False, urls, f"{titles} distinct titles across {records} records"

    ok, why = tests_have_no_new_failures(work, baseline or set())
    if not ok:
        return False, urls, why
    return True, urls, ""


# ── Reporting ────────────────────────────────────────────────────────────────

def append_run_log(entry: dict) -> None:
    """The run log has been an empty template since the day it was created. An
    L1 pipeline had nothing to write here; this loop does."""
    marker = "<!-- Loop appends below this line -->"
    try:
        text = RUN_LOG.read_text()
    except OSError:
        return
    line = "\n```json\n" + json.dumps(entry, indent=1, ensure_ascii=False) + "\n```\n"
    if marker in text:
        text = text.replace(marker, marker + line, 1)
    else:
        text = text.rstrip("\n") + "\n" + line
    try:
        RUN_LOG.write_text(text)
    except OSError as e:
        _log(f"  could not append to run log: {e}")


def attempt_repair(work: Path, site: str, scraper: str, nights: int,
                   baseline: set[str]) -> tuple[bool, int, str, list[str], int]:
    """Edit, verify, and retry inside one worktree.

    Returns (verified, distinct_urls, why_not, files_touched, rounds_used).

    The worktree is NOT reset between rounds, so a fix that lands on round two
    arrives on top of whatever round one did. Verified against a two-round run
    on 2026-08-21: round one changed the location field, round two fixed the url
    key, and the branch carried both — the scrape returned 69 URLs and the suite
    was clean, so nothing rejected the leftover. Rounds used is reported for that
    reason: a branch built in more than one round is one to read for edits that
    are not the fix.

    Extracted from main so the end-to-end harness exercises the retry rounds
    rather than a single call to run_agent — which is what it was doing, and why
    the first run with rounds enabled finished in half the time and never
    retried once.
    """
    floor = expected_floor(site)
    ok, count, why = False, 0, ""
    source_touched: list[str] = []

    for rnd in range(1, MAX_ROUNDS + 1):
        if rnd == 1:
            run_agent(work, site, scraper, nights)
        else:
            _log(f"  round {rnd}: {why}")
            diff = _run(["git", "diff", "--", scraper], cwd=work, timeout=60)
            run_agent(work, site, scraper, nights, retry={
                "why": why,
                "diff": (diff.stdout or "")[:3000],
                "round": rnd,
                "floor_note": (f"It needs at least {floor} of them; "
                               f"the last run produced {count}."),
            })

        touched = changed_files(work)
        # Untracked scratch the scrape itself leaves behind is not the agent's
        # diff; only tracked source counts as scope.
        source_touched = [f for f in touched
                          if not f.startswith(("00_saved/", "10_output/", ".env"))]
        if source_touched and source_touched != [scraper]:
            break  # out of scope: no point verifying or retrying
        if not source_touched:
            why = "agent changed nothing"
            continue
        ok, count, why = verify(work, site, baseline)
        if ok:
            break

    return ok, count, why, source_touched, rnd


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Decide and report, spawn nothing")
    ap.add_argument("--site", default=None, help="Force a candidate")
    args = ap.parse_args()

    if KILL_SWITCH.exists():
        _log(f"paused: {KILL_SWITCH.name} exists")
        return 0

    # The nightly holds the files this would scrape into and rewrites the
    # histories this reads. Overlapping them makes both unreliable.
    running = _run(["pgrep", "-f", "job_scout_nightly.sh"], timeout=30)
    if running.returncode == 0:
        _log("nightly is still running, not starting a repair")
        return 0

    site, why_not = pick_site(args.site)
    if not site:
        _log(f"nothing to repair: {why_not}")
        return 0

    scraper = scraper_path(site).name
    nights = len((load_json(YIELD_HISTORY, {}).get(site) or []))
    _log(f"candidate: {site} ({scraper})")

    if args.dry_run:
        print(f"🔁 loop-repair (dry run): {site} would be attempted — {scraper}")
        return 0

    started = dt.datetime.now()
    branch = f"loop/repair-{site}-{started:%Y%m%d}"
    state = load_json(REPAIR_STATE, {})
    entry = state.setdefault(site, {"attempts": 0})
    entry["attempts"] = entry.get("attempts", 0) + 1
    entry["last_attempt"] = started.isoformat(timespec="seconds")

    work = prepare_worktree(site, branch)
    _log(f"worktree: {work} on {branch}")
    outcome = "no-op"
    detail = ""
    count = 0
    try:
        # Before the agent touches anything, so a failure it did not cause
        # cannot be charged to it.
        baseline, base_why = failing_tests(work)
        if base_why:
            raise RuntimeError(f"baseline test run: {base_why}")
        if baseline:
            _log(f"  baseline: {len(baseline)} test(s) already red")

        ok, count, why, source_touched, rounds = attempt_repair(
            work, site, scraper, nights, baseline)

        if source_touched and source_touched != [scraper]:
            outcome, detail = "rejected", f"touched {', '.join(source_touched)}"
        elif not source_touched:
            outcome, detail = "no-op", "agent changed nothing"
        else:
            if ok:
                _run(["git", "add", scraper], cwd=work, timeout=60)
                leftover = ("\n\nBuilt over %d rounds — the worktree is not reset "
                            "between them, so read this diff for edits that are "
                            "not the fix.\n" % rounds) if rounds > 1 else "\n"
                _run(["git", "commit", "-m",
                      f"fix({site}): restore selectors after {nights} empty nights\n\n"
                      f"Verified by scraping the live site: {count} distinct URLs.\n"
                      f"Written by loop_repair.py. Unreviewed.{leftover}"],
                     cwd=work, timeout=60)
                outcome, detail = "fix-proposed", f"{count} jobs in {rounds} round(s)"
                entry["branch"] = branch
            else:
                outcome, detail = "failed", f"{why} (after {MAX_ROUNDS} rounds)"
    except subprocess.TimeoutExpired:
        outcome, detail = "failed", "agent timed out"
    except RuntimeError as e:
        # The agent never ran. Charging this to the site's attempt budget would
        # spend both on a setup problem and then stop trying a scraper nobody
        # ever looked at.
        outcome, detail = "blocked", str(e)
        entry["attempts"] -= 1
    except Exception as e:
        outcome, detail = "failed", f"{type(e).__name__}: {e}"
    finally:
        if outcome != "fix-proposed":
            discard_worktree(work, branch)

    entry["outcome"] = outcome
    save_repair_state(state)

    append_run_log({
        "run_id": started.isoformat(timespec="seconds"),
        "pattern": "scraper-repair",
        "owner": OWNER,
        "site": site,
        "duration_s": int((dt.datetime.now() - started).total_seconds()),
        "attempt": entry["attempts"],
        "verified_jobs": count,
        "rounds": rounds,
        "outcome": outcome,
        "detail": detail,
    })

    # stdout is the Telegram message. A no-op night says nothing.
    if outcome == "fix-proposed":
        print(f"🔧 loop-repair: {site} のスクレイパーを修正、検証済み({count}件取得)\n"
              f"   ブランチ `{branch}` にコミット済み。マージは人間の判断:\n"
              f"   git diff main...{branch}")
    elif outcome == "rejected":
        print(f"🔁 loop-repair: {site} の修正を破棄 — 範囲外のファイルを変更({detail})")
    elif outcome == "failed":
        print(f"🔁 loop-repair: {site} の修正に失敗 — {detail}"
              f"({entry['attempts']}/{MAX_ATTEMPTS_PER_SITE}回目)")
    elif outcome == "blocked":
        print(f"⚠️ loop-repair: エージェントを起動できず — {detail}\n"
              f"   {site} は未着手のまま。試行回数は消費していない。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
