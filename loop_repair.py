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

AGENT_TIMEOUT = 900
VERIFY_TIMEOUT = 600

# No Bash. The agent reads the scraper and edits it; this script runs the only
# command that decides anything.
ALLOWED_TOOLS = "Read,Edit,Grep,Glob"

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

PROMPT = """\
`{scraper}` in this repository has stopped returning results. It runs to
completion and exits 0, and has scraped exactly zero jobs on each of the last
{nights} nightly runs. Every other site is still returning normally, so the
fault is in this file rather than in the network or the pipeline around it.

That pattern almost always means the site changed its markup and the selectors
no longer match anything. The scraper finds no elements, produces an empty list,
and reports success.

Read the file and fix the selection so it matches the page again. Work from what
the code tells you: which selectors are used, whether there is a fallback chain,
whether anything logs what it found. Prefer the smallest change that could
plausibly restore results, and prefer a selector that is more tolerant of markup
churn over one tuned to the exact current DOM.

Constraints, all of them enforced after you finish:

  * Edit ONLY `{scraper}`. A change to any other file causes the whole attempt
    to be thrown away, including your work on this one.
  * Do not add dependencies, do not change the function signatures other modules
    call, and do not touch anything to do with credentials.
  * Do not write tests, documentation, or comments explaining what you tried.
    Comment the code where the reason for a choice is not obvious from it.

Your change is verified by actually running the scraper against the live site.
If it returns jobs the fix is kept on a branch for a human to review; if it
returns nothing the work is discarded. So do not describe a fix — make one.
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


def run_agent(work: Path, site: str, scraper: str, nights: int) -> str:
    prompt = PROMPT.format(scraper=scraper, nights=nights)
    result = _run(
        ["claude", "-p", prompt,
         "--allowedTools", ALLOWED_TOOLS,
         "--permission-mode", "acceptEdits"],
        cwd=work, timeout=AGENT_TIMEOUT)
    if result.returncode != 0:
        _log(f"  agent exited {result.returncode}: {result.stderr[-400:]}")
    return (result.stdout or "")[-2000:]


def changed_files(work: Path) -> list[str]:
    result = _run(["git", "status", "--porcelain"], cwd=work, timeout=60)
    files = []
    for line in result.stdout.splitlines():
        if len(line) > 3:
            files.append(line[3:].strip())
    return files


def verify(work: Path, site: str) -> tuple[bool, int, str]:
    """Run the real scraper in the worktree. Truth is the yield file it writes.

    --scrape-only is what makes this affordable: it stops before the merge and
    the LLM work, so a check costs the scrape alone — 43s for remote_apis and
    144s for adzuna, measured 2026-08-21. Before that flag existed, verifying a
    scraper meant paying for the whole pool's analysis and could not finish
    inside any sensible timeout.
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

    count = 0
    try:
        for line in yield_file.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) == 2 and parts[0] == site:
                count = int(parts[1])
    except Exception:
        pass

    if result.returncode != 0:
        return False, count, f"scraper exited {result.returncode}"
    return count > 0, count, "" if count else "still returns nothing"


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
        run_agent(work, site, scraper, nights)

        touched = changed_files(work)
        # Untracked scratch the scrape itself leaves behind is not the agent's
        # diff; only tracked source counts as scope.
        source_touched = [f for f in touched
                          if not f.startswith(("00_saved/", "10_output/", ".env"))]
        if not source_touched:
            outcome, detail = "no-op", "agent changed nothing"
        elif source_touched != [scraper]:
            outcome, detail = "rejected", f"touched {', '.join(source_touched)}"
        else:
            ok, count, why = verify(work, site)
            if ok:
                _run(["git", "add", scraper], cwd=work, timeout=60)
                _run(["git", "commit", "-m",
                      f"fix({site}): restore selectors after {nights} empty nights\n\n"
                      f"Verified by scraping the live site: {count} jobs.\n"
                      f"Written by loop_repair.py. Unreviewed.\n"],
                     cwd=work, timeout=60)
                outcome, detail = "fix-proposed", f"{count} jobs"
                entry["branch"] = branch
            else:
                outcome, detail = "failed", why
    except subprocess.TimeoutExpired:
        outcome, detail = "failed", "agent timed out"
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
        "site": site,
        "duration_s": int((dt.datetime.now() - started).total_seconds()),
        "attempt": entry["attempts"],
        "verified_jobs": count,
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
