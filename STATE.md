# Loop State — Job Intelligence System

Human-maintained. Nothing in the pipeline writes this file; a stale date here
means nobody updated it, **not** that a loop stopped. See [LOOP.md](LOOP.md).

Last verified: 2026-08-27

## Loop health

All times JST — the machine is `Asia/Tokyo`. UK equivalents in brackets, since
the job market is British and the two land on different calendar days.

| Loop | Schedule | Last run | Result |
|------|----------|----------|--------|
| job-scout-early | `0 2 * * *` (18:00 BST prev. day) | 2026-08-27 02:00 → 02:59 | ok |
| job-scout-late | `30 4 * * *` (20:30 BST prev. day) | 2026-08-27 04:30, running at time of writing | previous 2026-08-26 ok |
| loop-repair (L2) | `0 7 * * *` (23:00 BST prev. day) | 2026-08-26 07:00 | ok — no candidate, silent |
| loop-readiness-daily (L3) | `0 9 * * *` | 2026-08-26 09:03 | ok — scores files, not runs |

Verify:

```bash
cat 10_output/_nightly_run_summary.tsv
grep -a "job-scout-nightly =====" 10_output/_nightly_scout.log | tail -3
```

**Reading `hermes cron list` without misdiagnosing it.** `Next run` advances when
a run STARTS; `Last run` only moves when it finishes. A long slot therefore shows
a next run a full day ahead while it is still executing, which reads exactly like
a skipped night. It cost one wrong diagnosis on 08-27. Check for the process
before concluding anything from the two dates:

```bash
pgrep -af job_scout_nightly.sh
```

### 2026-08-22 — the first night every site completed

```
linkedin      0  1547s      early slot: 3346s of 6600
adzuna        0   140s
indeed        0  1659s
reed          0  1315s      late slot:  2010s of 3600
remote_apis   0    49s
guardian      0   646s
```

No skips, no timeouts, first time in the recorded history. guardian produced a
number at all for the first time — 3 jobs, which is what guardian is.

Two changes did it, and neither was the one tried first. Reordering the sites
could not work: 5400s against a 1500s per-site cap admits three, so the order
only ever chose which three. `--scrape-only` was the real fix — a site's elapsed
time had been dominated by the analysis `run.py` ran afterwards over the whole
pool, not by its own scrape, so six invocations meant six analysis passes.
Scraping alone fits; scraping plus six analyses never could.

Yield history, ten nights:

```
linkedin     [377, 377, 366, 387, 395, 379, 390, 409, 404, 395]
adzuna       [411, 833, 845, 830, 824, 832]
indeed       [0, 168, 168, 167, 169, 151, 150, 0, 167, 163]
remote_apis  [67, 57, 58, 72]
reed         [120, 163, 163]
guardian     [2, 3]
```

### 2026-08-22 — L2 ran for the first time on a schedule

`loop-repair` fired at 07:00:47, found no site dry, wrote nothing and said
nothing. `last_status: ok`, no run-log entry, no state file, zero bytes on
stdout. That is the correct outcome and it was the last untested path: every
earlier experiment called `attempt_repair` directly, so `main`'s own work — the
kill switch, the nightly-running check, candidate selection, the run log, the
Telegram wording — had never executed.

## High Priority (loops waiting on a human)

- **Nothing.** Both loops are scheduled, both ran, both behaved.

## Watch List

- **The retry rounds have never run in production.** Verified by forcing them
  with a stubbed agent — round one failed, round two was told why and fixed it —
  but no real night has needed a second round. The first one that does is worth
  reading: the worktree is not reset between rounds, so a two-round branch can
  carry round one's wrong edit alongside round two's fix, and nothing rejects it
  when the leftover is merely harmless.
- **`SWEEP_DEADLINE` (7020s) and the Hermes cap (7200) are 180s apart.** Crossed
  on 08-14. A run that crosses it completes and notifies nobody.
- **The analyzer retiering is committed but not yet observed in a night.**
  `7171a47` routes the analyzer stage to groq. Nothing has run through it yet at
  the time of writing — tonight's `late` slot is the first. Read
  `10_output/_llm_stats.tsv` with `llm_stats.py` afterwards and compare against
  the 614 calls / 16,293s it replaces. A zero-byte stats file before the scoring
  phase is expected: `early` truncates it and scrapes without scoring.
- **`vault-drift-check` is failing.** `error: Script exited with code 1`,
  2026-08-27 04:28. Unrelated to the job loops — listed because it shares the
  archivist scheduler and nothing else reports it.
- **Five profiles still have no working agent path.** archivist, investigator,
  researcher, visualizer and writer point at `z-ai/glm-5.2` via the built-in
  `zai` provider, whose keys live in the gateway's `.env` and not in Hermes's
  secret scope. builder, review-editor and strategist were moved to
  `custom:litellm-gateway` with `key_env` and work; the same change fixes these.
  Only archivist matters today, and only because its nightly is `no_agent`.
- **`00_matches` has no `*_match.md` at any depth** — reports live inside
  per-job directories. Any script globbing `*_match.md` reports 0 and always has.

## Recently closed

- **Delivery path unverified** → 2026-08-14. `telegram:5766380505,local` resolves
  to chat "KZ"; `last_delivery_error` is `None` on successful runs.
- **No escalation for sites that never run** → 2026-08-15, `stale_sites`.
- **A timeout counted as a failure to produce** → 2026-08-19, `partial`.
- **Six sites in one window** → 2026-08-20, `--scrape-only` and the two-slot
  split. Confirmed by the 08-22 run above.
- **`zai-glm` always 429'd** → 2026-08-22. All eleven keys are live; `glm-5.2` is
  paid and these accounts are free. Repointed at `glm-4.5-flash`, the only free
  one, with thinking disabled. It sat mid-chain in four fallback chains, so every
  chain had been burning a retry on a guaranteed failure.
- **No L2 loop** → 2026-08-22. Scheduled, ran, silent.
- **Per-stage model tiering undecided** → 2026-08-27, `7171a47`. Decided from the
  measured rows, not from stage names. analyzer was 614 calls and 16,293s in one
  night — 62% of the night's LLM time — on a median 829-character prompt, at a
  median 18.5s against groq's 0.9s for the same call. Compared head to head on 12
  real postings the slow model was also the lossy one: 40 skills against 76, five
  postings left with none against three, agreeing on experience_level and
  work_style 11 times out of 12. See `loop-budget.md` for the table and the
  `JIS_STAGE_PRIMARY` escape hatch.

## Stopped / dead automation

| What | Where | Action |
|------|-------|--------|
| `agency` scrape, 3×/day | user crontab | Stopped 08-13 — commented out; 322 runs, ~10 useful rows after day one |
| `job-scraper-nightly` | builder, `b84b7835506e` | Paused 08-13 — `Script not found` since 07-27 |
| `job-scout-nightly` (single slot) | archivist, `74bac7a999d0` | Disabled 08-21, superseded by the split |
| `job-scout-nightly` (old copy) | default, `20e08388d5df` | Paused 07-20 |
| `~/.hermes/scripts/job_scout_nightly.sh` | — | Stale duplicate; nothing calls it |
| `~/.hermes/scripts/run_cron.sh` | — | 15-line older version; nothing calls it |
