# Loop State — Job Intelligence System

Human-maintained. Nothing in the pipeline writes this file; a stale date here
means nobody updated it, **not** that a loop stopped. See [LOOP.md](LOOP.md).

Last verified: 2026-08-28

## GitHub main integration — 2026-10-14

- The user requested that the default GitHub branch show the current system
  for recruiter review. Integrated the 191 published development commits from
  `feat/strategy-layer-and-visa-clock` (`eb064ea`) into the updated README/image
  baseline on `main` (`958d300`), in an isolated worktree.
- The only merge conflict was README.md. Preserved the current Job Scout System
  title and detailed v3 diagram, and updated checkout instructions and links
  to use main. All Python files match the published development commit.
- Preserved main's `.env.example` because `.env.*` is protected. Actual
  environment files and the production checkout's uncommitted work were not
  imported or changed. The current local deployment's scraper_indeed.py edit
  and untracked manual probes remain outside this publication.
- Validation: 216 tracked Python files compile. With the local model endpoint
  disabled for regression tests, the full tests/ suite completed in 16.83s:
  **1,353 passed, 20 skipped, 1 failed**. The same failing legacy cover-letter
  test reproduces before integration:
  `test_an_invented_figure_or_audience_is_rejected` (the "ten years" case).
  The quantity guard accepts that number from the verification record even
  though this test expects rejection. This is an existing failure, not a new
  regression; no change to its guard or test was included in the merge.
- An initial test run was interrupted because an unmocked summary call was
  waiting for the live local model. No live scraping, application submission,
  model-mode change or nightly schedule change was part of this integration.

## Edinburgh local-work overnight follow-up — 2026-10-13

- Checked actual early/late run evidence: LinkedIn timed out at 2400s after
  repeated 429s; Indeed hit an unattended challenge and returned zero; Guardian
  failed headed Chromium launch without DISPLAY but was recorded as success.
  Reed returned 296 in 1761s, Adzuna 819 in 146s, remote APIs 64 in 31s.
- Fixed in the existing L2 worktree and integrated: shared local metadata in
  every report renderer, local exclusions before explicit regeneration/review
  count limits, verified local CV facts and provenance in nightly rescoring,
  headless Guardian launch without DISPLAY. Preserved current Jev code.
- Restored only local_job_role/shared_cv lines in 162 existing reports; all
  other bytes preserved. Backup and hash ledger:
  `10_output/_local_followup_report_repair_20261013/`. All 173 local reports
  now have a role. Filter-passed local jobs: 128 (admin80/manual9/kitchen39).
- Intermediate validation: 427 passed. Final provenance refinement: 101 focused
  tests passed, then 428 passed with none skipped (127.91s). That 428 was a
  subset; the whole suite is ~1,370 tests and takes far longer.
- Monitoring follow-up (same day, morning), integrated from worktree
  `monitoring-fix-20261013`, not committed:
  - `--scrape-only` exits 1 when every requested site failed, so a crashed
    scraper is recorded as `error` instead of an `ok` zero. The nightly runs
    one site per process.
  - Indeed raises when no search succeeded.
  - LinkedIn guest stops 180s before its own timeout and stages what it has.
  - The UI Save writes only the changed keys and refuses on a clash
    (`config_save.py`).
  - A LinkedIn run that lost a search, request or description to its own
    budget exits 124, the code the nightly recorded when its timeout killed
    the scraper. `nightly_scout.py` already reads that as `timeout` (and
    `partial` in the history when jobs were staged), so two rate-limited
    nights are never an L2 dry target. Jobs are still staged and counted.
  - Guardian is always headless, because the nightly inherits `DISPLAY=:20`
    with no X server behind it. A real fetch under that env returned a
    genuine 0 in 181–200s. With approval, the uncommitted debug diff of
    unknown origin was removed: `scraper_guardian.py` is now HEAD plus a
    4-line comment. The removed code is saved in
    `docs/GUARDIAN_DEBUG_REMOVED_2026-10-13.patch`.
  - Patch: `docs/MONITORING_FIX_2026-10-13.patch`.
  - Full live suite after the 124 change: 1,373 passed, 2 failed (247.57s). Both failures are
    pre-existing and come from `trial_jev_pipeline.py` (`test_doc_paths`,
    `test_no_unguarded_report_writers`).
- Open:
  - Who added the Guardian debug diff is unknown (possibly an L2 worktree
    leak around 10-08; a hypothesis only).
  - Guardian is still a dry candidate, but `pick_site()` skips it: it has 2
    of `MAX_ATTEMPTS_PER_SITE = 2` attempts in `_loop_repair_state.json`.
    Clearing that file makes it a target again.
  - A partial Indeed abort (at least one search succeeded) still exits 0, on
    purpose: the challenge is intermittent, and its yield is above 0, so it
    never becomes a dry target.
  - Telegram's dry list (`dry_sites`) counts yields only, so two 0-job 124
    nights show `linkedin(2晩連続0件)` next to the timeout. True; left as is.
  - LinkedIn's full 2400s budget is safe: it runs first in the early slot
    (DEADLINE 6600s), right after `scraper_saved.py`.
  - A UI save still drops config comments.
  - LinkedIn 429s and Indeed interactive verification remain.
  - Full evidence and limits: `docs/EDINBURGH_LOCAL_WORK_FOLLOWUP_2026-10-13.md`.

## Jev production-source confirmation — 2026-10-13

- Confirmed all 13 installed files match the installation ledger hashes in
  `10_output/_jev_pipeline_trial_20261012/installed_sources.json`.
  The production checkout contains the tested Jev trial implementation.
- Installation is separate from activation: the default remains `legacy`, and
  the production `.env` has no `JIS_DOCUMENT_MODE` setting. Jev requires
  `JIS_DOCUMENT_MODE=jev` for that execution; no permanent activation was made.
- The 93.33s → 2.77s measurement is a document/report batch for 11 jobs:
  22 documents versus 21, with one CL withheld. It is not a single-letter time.
  See [production status and evidence](docs/JEV_PIPELINE_TRIAL_2026-10-12.md).

## Jev document trial integration — 2026-10-12

- The user authorised testing Jev through the JIS system rather than only as a
  standalone component. Developed and checked on `experiment/jev-pipeline-trial-20261012`
  in `10_output/_worktrees/jev-pipeline-trial-20261012`, then installed the tested
  sources in this checkout. Normal CV/CL entrypoints accept the opt-in
  `JIS_DOCUMENT_MODE=jev`; the default and scheduled operation remain legacy.
- CV project IDs and prepared CL paragraph IDs are selected by pinned Jev.
  Bodies are assembled from source text. Out-of-scope CLs are withheld; uncertain
  choices use a labelled neutral draft. Every trial document requires review.
- Found and fixed first-load cache races in CL identity/facts during parallel
  generation. Regression and integration checks: 157 passed in the worktree;
  149 post-installation checks plus 53 local-job/Japanese-CV checks passed here.
- Same frozen 40 saved postings and settings, three workers, fixed runtime code:
  filter and match results equal for all 40. Generation/report stage 93.33s
  legacy versus 2.77s Jev. CVs 11 versus 11; CLs 11 versus 10, with one physical
  product role deliberately withheld. This is not equal-quality 11-pair speedup.
  Jev: 21 pinned responses, zero generation LLM calls, eight selected bridges
  and two uncertain/neutral. All 11 CV and 10 CL bodies match source reassembly.
- Actual-root replay also completed two GLM-5.3 reviews per mode. Generation
  62.27s versus 2.70s; review 208.20s versus 76.44s; total 272.34s versus 81.24s.
  Review latency varied without a reviewer change; do not attribute the entire
  wall-time difference to Jev. A configured phone was flagged as lacking a
  review reference; human fit labels remain zero, so no quality accuracy claimed.
- Added the existing user-maintained CV contact values to reviewer factual
  references. Related combined post-fix tests: **208 passed**. A real re-review
  of the same CV removed the phone finding (`fact_block: false`, score 58), but
  took 482.54s and completed via GLM-5.3 key 4. This extra validation is separate
  from the benchmark and confirms substantial upstream/retry latency remains.
- Prior source backups, frozen input, installation hashes and audit records:
  `10_output/_jev_pipeline_trial_20261012/`. Fixed-code measurements are in the
  worktree's `10_output/pipeline_fixed_{legacy,jev}_20261012/`. Trial outputs and
  quarantine state are isolated. No application document replacement, schedule
  switch, Kanban write, commit, push or merge. Live scraping/new enrichment/full
  review throughput and ordinary nightly operation were not measured.
- Details: [trial integration and measurements](docs/JEV_PIPELINE_TRIAL_2026-10-12.md).

## Edinburgh local work — 2026-10-12

- L2 explicitly enabled by the user. Implemented in
  `/home/kz003/.codex/worktrees/52cd/Job-Intelligence-System`, branch
  `loop/edinburgh-local-20261012`; integrated into the production working tree
  after explicit human approval. The initial nine-file patch and the later
  eight-file audit patch preserve unrelated changes;
  rollback copies are in `/tmp/jis-local-integration-backup-20261012/`.
  Post-integration validation: 337 related tests passed, none skipped
  (126.80s). Existing nightly invokes this production directory and reads
  its configuration, so no schedule change is required.
- Added eight Edinburgh-only admin/manual/kitchen search terms (44 pairs total;
  LinkedIn 54 including existing Japan searches). Reed depth is 2 to fit its
  measured timeout budget; other site depths are unchanged.
- Templates relocated to canonical `career/cv/` and `career/cover-letter/`
  at the user's request; local profile paths now reference `career/cv/`.
  Relocation check: 39 local-job tests passed; all 11 research-report local
  links resolve. Legacy helper capture and PDF routing passed isolated smoke checks.
- Title-scoped salary-floor exceptions and verified shared CV references keep
  local work visible without consuming professional generation/review slots.
  Seniority, driving and clinical exclusions remain enforced.
- Validation: 328 related tests passed, 9 existing-data-dependent tests skipped.
  No full live scrape, schedule change, push, merge or application submission.
- Additional audit after the user's reliability question reproduced three gaps:
  shared CVs missing from the standard CV/PDF views, missed festive/plural titles,
  and distant local jobs admitted by location-blind search sources. Fixes were
  prepared in the same worktree and integrated within the already-approved scope.
  Worktree validation: 384 passed, 9 data-dependent skips. Production validation:
  393 passed, none skipped (128.78s). A real Streamlit AppTest rendered the shared PDF download control
  without exceptions. API local terms now use gb + where=Edinburgh; professional
  multi-country searches retain their existing behaviour. Unknown locations still
  require human checking. No full nightly/live-board run has been performed.
- Details and task-only patch: `docs/EDINBURGH_LOCAL_WORK_2026-10-12.md`.

## Conservative expiry checker — 2026-10-12

- The user explicitly enabled L2 for the expiry-checker implementation.
  Code and tests are isolated on `loop/expiry-safe-20261012` in
  `10_output/_worktrees/expiry-safe-20261012`; no production integration or
  schedule change has been made.
- Default execution is a dry run. `--apply` requires two fresh observations
  of the same dedicated, exact closure notice on LinkedIn, Reed or Guardian.
  Generic 404/410, access failures, redirects, quotes/negations, contradictory
  Apply controls and legacy `listing_removed`/cache flags cannot expire a job.
  Other sources remain manual. Only repeated access failures stop a source;
  healthy inconclusive pages do not halt the sweep.
- Applying saves evidence and original reports under `_expiry_runs/`, updates
  only an unchanged report's `expired` line, preserves cache history and leaves
  `_analyzed.json` alone. An apply lock prevents concurrent runs of this script.
- Validation: 230 relevant tests pass. A read-only 12-posting live sample found
  4 confirmed closures and 8 unknowns, with 0 ticks. All Markdown bytes under
  `00_matches`, expiry state and analyzed data have matching before/after hashes.
  Details: `10_output/_expiry_validation_20261012/` and the worktree's
  `docs/EXPIRED_CHECK_SAFE_2026-10-12.md`. These are confirmation timestamps,
  not actual deadlines; website correctness or future reopening is not guaranteed.
- Run the new script from the repository root with the existing `.venv/bin/python`
  and `--data-dir 10_output`; the default data path inside the worktree is empty.
  Existing production `check_expired.py` remains the old implementation.

## GLM-5.3 key fallback — 2026-10-10

- The user requested the existing Mistral-style key fallback for GLM-5.3.
  Changes are isolated on `fix/glm53-key-fallback-20261010` in
  `10_output/_worktrees/glm53-key-fallback-20261010`.
- The default CV/CL review and annotation-dialogue chain tries Gateway aliases
  `review-strong-glm53-key1` through `review-strong-glm53-key7` in order, using
  the seven existing NVIDIA keys and the same GLM-5.3 reasoning-low model.
  Each key has one attempt. Errors or unusable reviews advance to the next key.
- Reuses the existing quarantine system, scoped per key alias. A failed key
  cannot quarantine the remaining six or the shared Gateway. Rate-limit errors
  have a 15-minute cooldown; auth/quota errors use the existing 14-day cooldown.
  These are retry schedules, not claims about when upstream quota resets.
- If every key fails, the existing review remains untouched. Explicit
  `REVIEW_FALLBACKS` remains available. The original pooled alias and other
  Gateway aliases, their fallback chains and global router settings are retained.
- Validation: 110 relevant tests pass, including per-key isolation, 401/402/403/
  429 failures, six failures followed by key 7, interrupted/unusable responses,
  annotation dialogue and all-key failure preserving existing reviews.
  The installed LiteLLM Router also passed six local-upstream failure scenarios.
- Production integration is complete. All seven new aliases answered through
  the JIS virtual key; the production client confirmed its default seven-key
  chain and GLM-5.3 response. Gateway readiness and dashboard health returned 200
  after restart. Production files match the tested worktree.
- Deployment and live connectivity results are recorded in
  `10_output/_glm53_key_fallback_20261010/`. Existing loop-health dates below
  have not been re-verified by this work.

## Review model deployment — 2026-10-09

- The user explicitly enabled L2 and approved tested production deployment.
  Work is isolated on `fix/review-glm53-20261009` in
  `10_output/_worktrees/review-glm53-20261009`.
- The JIS Python CV/CL review and annotation-dialogue route now defaults to
  `litellm-gateway:review-strong-glm53` (NVIDIA NIM GLM-5.3, reasoning low).
  Seven existing NVIDIA key references are reused; each passed a short probe.
  Existing Gateway aliases and global router settings are preserved.
- New reviews receive the complete document. This route buffers streamed text
  and requires normal completion; errors or partial answers fail the request.
  No automatic retries or weaker-model fallbacks are used on the new route.
  Explicit `REVIEW_FALLBACKS` overrides remain available.
- Validation: 60 relevant tests pass. The isolated JIS client completed a
  100,071-character real review prompt in 39.249 seconds, with a usable CV
  review and the served model confirmed as `openai/z-ai/glm-5.3`.
- Non-streaming long requests timed out during deployment. A complete
  streamed Gateway review also passed in 63.945 seconds. These measurements
  establish a working route, not a future availability guarantee.
- Previous reviews and application documents are retained. No mass re-review,
  Hermes profile model change, commit or push was performed. Human factual
  review remains necessary; the model still made mistakes in the small benchmark.
- Details: [review model validation](docs/REVIEW_MODEL_2026-10-09.md).
  Production source matches the tested worktree. The dashboard was restarted;
  Gateway readiness and dashboard health returned 200, and the production
  client confirmed the served GLM-5.3 model through the JIS virtual key.
  Existing loop-health dates below have not been re-verified.

## Dashboard integration — 2026-10-09

- UI work is isolated on `feat/application-history-20261009` in
  `10_output/_worktrees/application-history-20261009`. The user approved
  integration on 2026-10-09, and the changes are integrated into the existing
  dashboard. Existing loop-health dates below have not been re-verified.
- Adds a Streamlit application-history tab: monthly calendar, daily job list,
  application/expiry totals, undated jobs, and Obsidian links across synced devices.
- Reads Obsidian report flags and `_expiry_checks.json` without changing them.
  Application dates remain the existing date-only estimates; automated expiry
  timestamps mean confirmation time, not the site's actual deadline. Manual
  checkbox timestamps are still unavailable; this candidate displays existing data.
- Verified in the live dashboard: 25 applications, 3,650 expired jobs after
  exact-URL deduplication, 93 expired jobs without a known confirmation time.
  These are a snapshot; the dashboard reads current records when refreshed.
- Validation: 38 relevant tests pass; browser checks cover daily selection,
  expiry view, the mobile calendar, and dark calendar colors. Streamlit refresh
  checks cover an empty vault and checked/unchecked jobs. No source records
  were rewritten.
- Dashboard: `http://192.168.3.99:8501` (application-history tab). Daily
  selection and the expiry view passed browser checks at this existing URL;
  its health endpoint returned 200. The temporary port-8510 preview is stopped.

## Loop health

All times JST — the machine is `Asia/Tokyo`. UK equivalents in brackets, since
the job market is British and the two land on different calendar days.

| Loop | Schedule | Last run | Result |
|------|----------|----------|--------|
| job-scout-early | `0 2 * * *` (18:00 BST prev. day) | 2026-08-28 02:00 | ok |
| job-scout-late | `30 4 * * *` (20:30 BST prev. day) | 2026-08-28 04:30 → 06:01 | ok — 5484s of the 7020s sweep budget |
| loop-repair (L2) | `0 7 * * *` (23:00 BST prev. day) | 2026-08-28 07:00 | ok — no candidate, silent |
| loop-readiness-daily (L3) | `0 9 * * *` | 2026-08-28 09:00 | ok — scores files, not runs |

L2 has still never produced a branch. `git branch --list 'loop/*'` is empty, which
is the correct outcome of a trigger that fires only on a scraper that ran clean
and returned nothing. Dormant is not broken.

Verify:

```bash
cat 10_output/_nightly_run_summary.tsv
grep -a "job-scout-nightly =====" 10_output/_nightly_scout.log | tail -3
```

**Reading `hermes cron list` without misdiagnosing it.** `Next run` advances when
a run STARTS; `Last run` only moves when it finishes. A long slot therefore shows
a next run a full day ahead while it is still executing, which reads exactly like
a skipped night. It cost one wrong diagnosis on 08-27. Check for the process
before concluding anything from the two dates — and **exclude your own shell**,
because the pattern you are grepping for is sitting in its command line. Written
the naive way this reports the night as still running hours after it finished,
which cost a second wrong diagnosis the same morning:

```bash
pgrep -af job_scout_nightly | grep -v "shell-snapshots\|eval"
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

- **The action tiers have no outcome data to be calibrated against, and none is
  being collected.** `record_outcome.py` exists and `10_output/_outcomes.json`
  does not — zero applications have had their result recorded. Until that file
  starts filling, `strategy._TIER1` / `_TIER2` / `_MONITOR_MIN` /
  `_OPPORTUNISTIC_MIN` stay a starting rule table and can never become a
  measurement. Nothing in the loop can fix this: it needs a human to record what
  happened after applying. Cheapest useful version is a single line per
  application — applied / screened / interviewed / rejected / offered.

## Deferred by decision

Recorded so they are not silently re-proposed. Each has its measurement written
down; see `EXPANSION_2026-08-29.md` for the numbers.

- **`app.py` does not surface the strategy layer.** Zero hits for `action_tier`
  or `strategic_value` in the Streamlit UI. Not urgent — the eleven new fields
  are in the match-report frontmatter, so Obsidian and Dataview already have
  them, which is where these get read. Worth doing only if the UI becomes the
  place decisions are made.
- **QA Analyst stays on a sample of three.** It measures like the two keywords
  dropped on 2026-08-30 (24 past the filter, 3 reviewed, mean 53.3, none at
  >=75) and was kept anyway: it is the most written-first job on the list, which
  is the candidate's stated constraint, and three reviews is not a measurement.
  Revisit when it has a real sample — not before, and not on the same evidence.
- **The keyword budget now has 8 spare pairs (36 of 44).** Do not fill them by
  guessing. "Graphic Designer" is the obvious candidate and the wrong one: it
  already produces more submission-ready documents than any searched term (125
  reviewed, 33 at >=75) on zero pairs, arriving as by-catch of `Designer`.
  Anything added here needs a measured reason, the way the two removals had one.
- **Level Fit on `required_years` is dead.** r = -0.068 against the review score
  over 278 postings; the years a posting asks for do not predict how it reviews.
  The field stays as evidence. Do not re-propose the dimension.
- **No immigration score, ever.** Only 4.0% of postings mention sponsorship at
  all. The flag records evidence with a verbatim quote and an invariant enforces
  it; a score over that base would be computed from silence.

## Watch List

- **The retry rounds have never run in production.** Verified by forcing them
  with a stubbed agent — round one failed, round two was told why and fixed it —
  but no real night has needed a second round. The first one that does is worth
  reading: the worktree is not reset between rounds, so a two-round branch can
  carry round one's wrong edit alongside round two's fix, and nothing rejects it
  when the leftover is merely harmless.
- **`SWEEP_DEADLINE` (7020s) and the Hermes cap (7200) are 180s apart.** Crossed
  on 08-14. A run that crosses it completes and notifies nobody.
- **`matcher` is now the night's largest LLM cost, and the analyzer's fix does
  not transfer to it.** Measured 2026-08-27: 1404 calls, 12,785s, 54% of the
  night. Its median prompt is 59,069 characters — over groq's 21,000 cap — so
  `_size_filter_chain` drops groq from its chain whatever `_STAGE_PRIMARY` says,
  and no reordering can help. `reviewer` is worse per call (median 42.1s on
  96,556 characters) but runs 48 times, so it is 2,092s and not worth touching
  first.

  **Prompt size is not the lever, measured 2026-08-27.** The obvious move is to
  cut or cache the 55k-character persona that leads every one of those calls.
  The same night's rows say it would not pay: matcher's own small calls average
  5,275 characters and 7.07s against the big ones' 61,070 characters and 10.08s
  — 11.6x the prompt for 1.43x the time — and inside the big calls the
  relationship is absent or inverted, mean time falling 13.26s to 8.95s as the
  quintiles rise from 57,912 to 64,781 characters. Making the persona free
  entirely is worth (10.08 - 7.07) x 950 = 2,860s, 22% of matcher and 12% of the
  night, and only in the limit. Cost here is a fixed per-call floor of roughly
  7s times 950 calls. The levers are call COUNT and provider latency.
  Independently, shrinking the persona was shipped and reverted once already for
  correctness — see the docstring on `_ollama_context_score`. Do not spend the
  refactor.

  **The call count is not a lever either, measured 2026-08-28.** The obvious
  suspect was the `context_rescore` second draw. It is not: `context_draws` over
  the database reads 3736 at one draw, 402 at two, 923 never asked, and only 22
  gate hits are still waiting for a second. The rescore was a one-time backlog
  drain and it is essentially finished, so tightening `context_max`, `skills_min`
  or `max_draws` now saves 22 calls in total. (402 spent against 157 that still
  match the gate is the mechanism working — averaging the second draw lifted the
  rest above 0.30 and out of it.) What remains is roughly 950 FIRST draws a night
  on newly scraped postings, which scales with how much is scraped, not with any
  parameter. Reducing it means collecting fewer jobs, which is a smaller system
  rather than a cheaper one.

  So matcher has no cheap lever left, and it does not currently need one: the
  night finishes in 5484s against a 7020s budget. Revisit if the sweep starts
  crossing its deadline, not before.
- **All twelve groq keys 429 together.** On the first night of the retiering they
  were quarantined within one second of each other, after about six calls each,
  and the chain fell through to `litellm-gateway` for the 15-minute cooldown.
  Twelve keys are not twelve buckets under `analysis_workers: 8`. The routing
  still paid for itself; the point is that it buys a burst rather than a night,
  and `analysis_workers` is the lever to test before adding keys.
- **`vault-drift-check` reports drift in the taifunome vault.** Its cron line
  reads `error: Script exited with code 1` and that is NOT a failure — the script
  is silent and exits 0 when every vault is clean, and exits 1 with a report when
  one is not, so that a `--no-agent` job only speaks when something is wrong.
  Hermes renders the deliberate signal as an error. Running it by hand shows the
  content: `taifunome: provenance_errors: 1`,
  `wiki/meta/ledgers/source-ledger.json does not match current file bytes`. It
  belongs to the taifunome repo, not this one, and the script is explicit that
  re-ingest is a reviewed transaction and never unattended.
- **Five profiles still have no working agent path.** archivist, investigator,
  researcher, visualizer and writer point at `z-ai/glm-5.2` via the built-in
  `zai` provider, whose keys live in the gateway's `.env` and not in Hermes's
  secret scope. builder, review-editor and strategist were moved to
  `custom:litellm-gateway` with `key_env` and work; the same change fixes these.
  Only archivist matters today, and only because its nightly is `no_agent`.
- **`00_matches` has no `*_match.md` at any depth** — reports live inside
  per-job directories. Any script globbing `*_match.md` reports 0 and always has.

## Recently closed

- **Five of the six invariant violations** → 2026-09-01. `recompute_skill_scores.py`
  applied `title_relevance` to stored composites (216 tiers moved), closing the
  title-excluded jobs sitting inside the generation and review selections;
  `invalidate_unscoreable_reviews.py` nulled 67 review scores written off failed
  scrapes; and `selection._dedupe` now keys on the document path rather than
  (company, title), closing both document-path collisions. One violation remains
  and needs a network fetch: 273 postings still hold a 500-char Adzuna summary
  instead of a description (`refetch_unscoreable.py --top-only`, in batches —
  adzuna refuses long runs).

- **The strategy layer had never run in production** → 2026-08-30. The nightly
  completed with it: 24 postings scraped, all 24 carrying every new field
  (`contract_kind`, `contract_months`, `sponsorship`, `remote_scope`,
  `runway_fit`, `strategic_value`, `action_tier`), and 5247 of 5254 match
  reports regenerated with the new frontmatter. The seven without it are
  Syncthing conflict files and `Untitled.md`. No new invariant violations.

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
- **The analyzer retiering, unobserved** → 2026-08-27, measured over a full
  night. 1,661 calls in 5,968s against the 614 calls / 16,293s it replaces: 2.7x
  the calls on 4.4x larger prompts (829 → 3,611 median characters, from the
  analyzer rewrites landed in between) for 63% less total time. Per call 26.5s →
  3.59s, median 18.5s → 1.5s. 119 of the calls failed over to the gateway and
  cost 76.7s in total, which is the one-hop fallback behaving as designed.
  Attribution is not clean: the gateway itself answered far faster this night
  than when the baseline was taken, on the same default `mistral-medium`. The
  direction is not in doubt; the exact share is.
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
