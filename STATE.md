# Loop State — Job Intelligence System

Human-maintained. Nothing in the pipeline writes this file; a stale date here
means nobody updated it, **not** that the loop stopped. See [LOOP.md](LOOP.md).

Last verified: 2026-08-18

## Loop health

| Check | Value |
|-------|-------|
| Scheduler | Hermes cron, archivist profile, job `74bac7a999d0` |
| Cadence | `0 2 * * *` — **single slot; the two-slot split is written but not yet scheduled, see below** |
| Runs recorded | 30, from 2026-07-20 to 2026-08-18, no gaps |
| Last run | 2026-08-18 02:00 → 03:30 JST (90 min), status `ok` |
| Notable | 2026-08-14: Hermes recorded `Script timed out after 7200s`; the script itself finished ~04:58 and its Telegram message went nowhere |

Verify last run:

```bash
grep -a "job-scout-nightly =====" 10_output/_nightly_scout.log | tail -3
```

## High Priority (loop is waiting on a human)

- **The two-slot split is committed but not scheduled.** `job_scout_nightly.sh`
  takes a `PHASE` argument (dotfiles `edde451`) and the two wrappers exist
  (`a9abbe8`), but the cron jobs still point at the old single-slot script, so
  nothing has changed on the schedule yet. Two commands finish it:

  ```bash
  HERMES_HOME=/home/kz003/.hermes/profiles/archivist hermes cron edit 74bac7a999d0 --script job_scout_early.sh --name job-scout-early
  ```
  ```bash
  HERMES_HOME=/home/kz003/.hermes/profiles/archivist hermes cron create --name job-scout-late --script job_scout_late.sh --schedule "30 4 * * *" --no-agent --deliver "telegram:5766380505,local"
  ```

  Until both land, the nightly runs `all` in one slot and three sites are still
  skipped every night.

### Why the split, and what the reorder bought

The 2026-08-18 run, the first under the reordered single slot:

| site | exit | elapsed | jobs |
|------|------|---------|------|
| linkedin | 0 | 1261s | 379 |
| adzuna | 124 (timeout) | 1500s | **833** |
| remote_apis | 124 (timeout) | 1500s | 57 |
| reed | 124 (timeout) | 1073s | 0 |
| guardian | 125 (skipped) | 0s | — |
| indeed | 125 (skipped) | 0s | — |

1269 jobs against the previous night's 545. adzuna, which had not run for four
nights, returned more in one night than any site here ever has.

But still three sites, because 5400s of scrape budget against a 1500s per-site
cap admits three and no more. The order only ever chose which three — which is
what the split is for. Measured yield per second, used to assign the groups:
adzuna 0.56, linkedin 0.30, indeed 0.07, remote_apis 0.038, reed 0, guardian ~0.

One assumption was wrong and is worth not repeating: remote_apis was placed
third on the belief that an HTTP API costs about a minute. It took the full
1500s and returned 57 jobs — the worst value per second on the list.

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
- **`stale_sites` reached its threshold on 2026-08-18 and nobody has confirmed
  the alert arrived.** guardian's status history is `["skipped","skipped",
  "skipped"]`, so `🚨 guardian(3晩連続未取得)` should have been in that morning's
  Telegram message. It cannot be checked from the log — the warning goes to
  stdout, which is the message itself, and only stderr reaches
  `_nightly_scout.log`. Confirming it is the first end-to-end test that the
  alarm added on 08-15 actually reaches a human.
- **`platform_engineer` changes match scores, not just CV templates.**
  `cv_generator.ROLE_KEYWORDS` is also read by `role_affinity()`, which
  matcher.py uses, so the new role type affects scoring for every job. Its
  body-signal keywords (`devops`, `observability`) can also win by default in
  `detect_role_type`: with no title matching any role, one body hit scores 1
  against everything else's 0. No test covers role detection at all.

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
