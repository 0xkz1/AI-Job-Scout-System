# Loop State — Job Intelligence System

Human-maintained. Nothing in the pipeline writes this file; a stale date here
means nobody updated it, **not** that the loop stopped. See [LOOP.md](LOOP.md).

Last verified: 2026-08-15

## Loop health

| Check | Value |
|-------|-------|
| Scheduler | Hermes cron, archivist profile, job `74bac7a999d0` |
| Cadence | `0 2 * * *` |
| Runs recorded | 27, from 2026-07-20 to 2026-08-15, no gaps |
| Last run | 2026-08-15 02:00 → 03:52 JST (112 min), status `ok` |
| Previous run | 2026-08-14, Hermes recorded `Script timed out after 7200s`; the script itself finished ~04:58 and its Telegram message went nowhere |

Verify last run:

```bash
grep -a "job-scout-nightly =====" 10_output/_nightly_scout.log | tail -3
```

## High Priority (loop is waiting on a human)

- **Verify tonight (2026-08-16) that the reorder worked.** The site order was
  changed in `job_scout_nightly.sh` (dotfiles `2cc5cdf`) to
  `linkedin, adzuna, remote_apis, reed, guardian, indeed`. Expected: five sites
  complete, indeed truncated instead of three sites skipped. Check with

  ```bash
  cat 10_output/_nightly_run_summary.tsv
  ```

  Any row with exit `125` means the budget still does not stretch, and the next
  move is two cron slots rather than another reorder.

### The finding that prompted it

- **Four of six sites were not being scraped.** The 2026-08-15 run summary:

  | site | exit | elapsed |
  |------|------|---------|
  | linkedin | 0 | 1818s |
  | indeed | 124 (timeout) | 2400s |
  | reed | 124 (timeout) | 1116s |
  | guardian | 125 (skipped) | 0s |
  | adzuna | 125 (skipped) | 0s |
  | remote_apis | 125 (skipped) | 0s |

  The review backlog sweep also aborted on timeout. Only linkedin completed.
  This was the standing shape of the run, not one bad night — the yield history
  for reed, guardian, adzuna and remote_apis had been frozen at one entry each
  since 08-12.

  A budget question, not a scraper question: 1818 + 2400 + 1116 = 5334s of the
  5400s scrape `DEADLINE`, leaving 66s against a 180s `MIN_SITE_SECONDS`. The
  highest-yielding site of all, adzuna at 411 jobs, was sitting fourth in line
  behind the two most expensive ones.

## Watch List

- **`SWEEP_DEADLINE` (7020s) and Hermes `script_timeout_seconds` (7200) are 180s
  apart.** Crossed once already, on 08-14. A run that crosses it completes and
  notifies nobody.
- **`00_matches` has no `*_match.md` at any depth** — reports live inside
  per-job directories. Any script globbing `*_match.md` reports 0 and always has.

## Recently closed

- **Delivery path unverified** → resolved 2026-08-14. `deliver:
  telegram:5766380505,local` resolves to chat "KZ"; `last_delivery_error` is
  `None` on successful runs.
- **No escalation for sites that never run** → resolved 2026-08-15 by
  `stale_sites` in `nightly_scout.py` (commit `8165c5a`). Three consecutive
  nights without a clean scrape now rides the Telegram message. The status
  history starts empty, so the first warning can fire three nights after that
  commit at the earliest.

## Stopped / dead automation

| What | Where | Action taken |
|------|-------|--------------|
| `agency` scrape, 3×/day | user crontab | **Stopped 2026-08-13** — commented out, not deleted; 322 runs, ~10 useful DB rows after day one |
| `job-scraper-nightly` | Hermes builder profile, `b84b7835506e` | **Paused 2026-08-13** — `Script not found` since 2026-07-27, duplicate of `74bac7a999d0` |
| `job-scout-nightly` (old copy) | Hermes default profile, `20e08388d5df` | Already paused 2026-07-20, correctly |
| `~/.hermes/scripts/job_scout_nightly.sh` | — | Stale duplicate of the profile script; nothing calls it |
| `~/.hermes/scripts/run_cron.sh` | — | 15-line older version; nothing calls it |
