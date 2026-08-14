# Loop Configuration — Job Intelligence System

## Active Loop

| Pattern | Cadence | Level | Runs via |
|---------|---------|-------|----------|
| Nightly job scout | `0 2 * * *` | L1 — generates artifacts, notifies, never acts outward | Hermes cron, **archivist** profile, job `74bac7a999d0` |

The scheduler is Hermes, not the system crontab and not systemd, and the job
lives in the archivist profile — so `crontab -l`, `systemctl --user
list-timers`, and a bare `hermes cron list` all show nothing. `hermes cron list`
reads the default profile only; each profile has its own `cron/jobs.json`.

```bash
HERMES_HOME=/home/kz003/.hermes/profiles/archivist hermes cron list
```

The default profile holds a paused copy (`20e08388d5df`, `paused_reason: "moved
to archivist profile cron (2026-07-20)"`). Do not re-enable it — two copies on
one cron expression would run two pipelines against one `_analyzed.json`.

### The script

```
/home/kz003/.hermes/profiles/archivist/scripts/job_scout_nightly.sh
```

Note the path: it is the **profile's** script directory. There is a stale
same-named file at `~/.hermes/scripts/job_scout_nightly.sh` that nothing calls;
editing that one changes nothing.

`no_agent: true` — no model drives the run. The script is the loop. Its stdout
**is** the Telegram message, so only `nightly_scout.py` may print to stdout.
Empty stdout = silent night.

The repo's `run_cron.sh` is the manual/foreground equivalent — same stages,
simpler budgeting, no Telegram. Its own header explains why it must never be
scheduled. Anything that belongs in the real nightly belongs in
`job_scout_nightly.sh`.

### Stages

Scrape, in order, each with its own timeout and a shared wall-clock deadline:
`linkedin`, `indeed --headless`, `reed`, `guardian`, `adzuna`, `remote_apis`.
Then: LLM context pass (600s) → persona rescore (1800s) → re-render match
reports (600s) → **notify** → review backlog sweep → re-render (post-sweep) →
stamp flag dates.

The notification fires mid-script, before the sweep. Stages after it run on
`SWEEP_DEADLINE` rather than the pre-notify budget.

### Budgets

| Constant | Value | Governs |
|----------|-------|---------|
| `SITE_TIMEOUT` | 1500s | one ordinary site |
| `INDEED_TIMEOUT` / `LINKEDIN_TIMEOUT` | 2400s | the two slow ones |
| `MIN_SITE_SECONDS` | 180s | below this remaining, a site is skipped (exit 125) |
| `MIN_STAGE_SECONDS` | 60s | same idea for post-scrape stages |
| `SWEEP_DEADLINE` | now + 7020s | the whole run |
| `script_timeout_seconds` | 7200 | Hermes kills the job here |

The 180s margin between `SWEEP_DEADLINE` and the Hermes cap is the whole safety
budget. On 2026-08-14 the run overran it: Hermes recorded `Script timed out
after 7200s` at 04:00:25 and stopped listening, the script kept going and
finished around 04:58, and the Telegram message it printed after 04:00 went
nowhere. `last_delivery_error` was `None` because no delivery was attempted.
A run can therefore complete and still notify nobody.

### State

| File | Written by | Meaning |
|------|-----------|---------|
| `10_output/_nightly_state.json` | `nightly_scout.py` | seen-URL set; the diff basis for "new" |
| `10_output/_nightly_run_summary.tsv` | the script | per-site exit code + elapsed (`125` = skipped) |
| `10_output/_nightly_site_yield.tsv` | `run.py` | per-site job counts for tonight |
| `10_output/_nightly_site_yield_history.json` | `nightly_scout.py` | rolling yields, **sites that ran only** |
| `10_output/_nightly_site_status_history.json` | `nightly_scout.py` | rolling per-site status, skips and timeouts included |
| `10_output/_nightly_scout.log` | the script | full run output (39 MB — never read whole) |
| [STATE.md](STATE.md) | human | what the loop is waiting on a human for |

`STATE.md` is not machine-written. A stale timestamp there means nobody wrote
it, not that the loop stopped. Last-run truth:

```bash
grep -a "job-scout-nightly =====" 10_output/_nightly_scout.log | tail -3
```

## Human gates

The loop stops at generated documents. It never sends an application, never
emails, never edits source, never commits. Every outbound action is human.

Escalation is one channel: the Telegram summary. Three warnings ride it —
`summarize_sites` (tonight's per-site outcome), `stale_sites` (three consecutive
nights with no clean scrape), `dry_sites` (two consecutive clean-but-empty
nights). A night is silent only when every site was ok and nothing is new.

## Known failure modes

- **A completed run that notifies nobody.** See the budget note above. The
  Hermes cap and the script's own deadline are 180s apart and the script has
  crossed it.
- **Sites that never start.** `exit 125` means the budget was spent before the
  site ran. `dry_sites` is blind to it by design — the yield history only
  records sites that ran — which is why `stale_sites` reads the status history
  instead. guardian, adzuna and remote_apis were skipped every night from
  2026-08-12 to 08-15 without that ever escalating.
- **Silent coverage failure.** The skill-coverage layer can succeed on every
  call while discarding the verdicts. Its `⚠️` warnings are lifted onto stdout
  so they ride the Telegram message; if a parsing change stops them appearing,
  verify the grep still matches before trusting the silence.

## Budget

- Sub-agent spawns per run: 0. `no_agent: true` — no agent is involved.
- LLM spend is bounded by per-stage `--limit` caps, not by a token cap. Jobs the
  filter already rejected must never reach a model call.

## Companion jobs (archivist profile)

| ID | Name | Schedule |
|----|------|----------|
| `74bac7a999d0` | job-scout-nightly | `0 2 * * *` |
| `ea108e2cb268` | loop-readiness-daily | `0 9 * * *` |
| `18bbf240eeff` | taifunome-daily-start | `0 15 * * *` |

`loop-readiness-daily` scores this repo by checking that loop scaffolding files
exist. It does not verify that any loop ran. A 100/100 from it is a statement
about this file's existence, not about last night's scrape.
