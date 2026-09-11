"""Scrape the URL list, then analyse what it staged — as one process.

The app used to drive this as two subprocesses: it launched the scrape, waited
for its exit code inside the Streamlit rerun loop, and only then launched the
analysis. That made stage two conditional on Streamlit still being alive and
still holding the same session_state, which it is not after an auto-reload —
editing any watched source file restarts the script and the pending chain is
simply forgotten. On 2026-08-12 a run scraped 40 postings, began enriching
1,004, and stopped at 100 with no error anywhere: the parent had gone.

Running both stages here means the only thing Streamlit does is read a log
file. Close the tab, reload the app, edit a module — the work still finishes.

Exit codes: 0 all stages ran, 2 another process holds the url_list lock (the
scraper's own code for that, passed through), 1 a stage failed.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK_BUSY = 2


def _run(label: str, cmd: list[str]) -> int:
    print(f"\n{'=' * 60}\n{label}  ({datetime.now():%H:%M:%S})\n{'=' * 60}", flush=True)
    # Inherit stdout/stderr: the caller redirects them to the log file the app
    # tails, so both stages land in one file in the order they happened.
    return subprocess.run([sys.executable, "-u", *cmd], cwd=str(ROOT)).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scrape-only", action="store_true",
                    help="stage one only, leaving the staged jobs unanalysed")
    args = ap.parse_args()

    code = _run("① Scrape url-list.md", ["scraper_url_list.py"])
    if code == LOCK_BUSY:
        print("\n⚠ scrape skipped — another process holds the url_list lock", flush=True)
        return LOCK_BUSY
    if code != 0:
        print(f"\n❌ scrape failed (exit {code}) — not analysing", flush=True)
        return 1
    # Pages the network path cannot reach are saved out of a browser into
    # 00_saved/local_html/, and this is what reads them. Nothing ran it before
    # 2026-09-11, so the workaround the WebUI documents for a blocked Indeed
    # URL produced nothing no matter how many pages were saved.
    #
    # Not fatal: it is the secondary route, and stage ① may have staged real
    # work that should still be analysed.
    code = _run("①b Extract 00_saved/local_html/", ["scraper_local_html.py"])
    if code != 0:
        print(f"\n⚠ saved-HTML extraction failed (exit {code}) — continuing", flush=True)

    if args.scrape_only:
        print("\n✅ scrape done (--scrape-only)", flush=True)
        return 0

    # The scrape has exited, so its file lock is released and run.py can take
    # it — both use the "url_list_jobs" lock.
    code = _run("② Analyse (run.py --from-saved)", ["run.py", "--from-saved"])
    if code == LOCK_BUSY:
        print("\n⚠ analysis skipped — another process holds the url_list lock", flush=True)
        return LOCK_BUSY
    if code != 0:
        print(f"\n❌ analysis failed (exit {code})", flush=True)
        return 1

    # Integrity checks last, over what the run just produced.
    #
    # invariants.py carries twenty-odd of these and, until 2026-09-11, only
    # nightly_scout ran them — so the WebUI button, which is how the URL-list
    # route is actually driven, never checked anything it wrote. Every fault
    # this pipeline has had was silent: a report present and correct-looking
    # with no link to the CV beside it, a wall banked as a job page. Nothing
    # errors, so nothing gets looked at.
    #
    # Printed, never fatal: the scrape and the analysis have already banked
    # their work, and a violation is a thing to read, not a reason to discard
    # the run.
    try:
        sys.path.insert(0, str(ROOT))
        from invariants import report as _invariant_report
        print(f"\n{'=' * 60}\n③ Integrity checks  ({datetime.now():%H:%M:%S})\n{'=' * 60}",
              flush=True)
        _invariant_report()
    except Exception as e:  # noqa: BLE001 - never let the check take the run down
        print(f"⚠️ 整合性チェックを実行できませんでした: {type(e).__name__}: {e}", flush=True)

    print(f"\n✅ chain complete  ({datetime.now():%H:%M:%S})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
