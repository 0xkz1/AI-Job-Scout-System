# Loop Budget — Job Intelligence System

Two loops, and their budgets are not the same shape. The nightly's ceiling is
wall-clock, because a scheduler kills it. The repair loop's ceiling is attempts,
because nothing kills a model call that keeps being worth retrying.

## L1 — the nightly scout

Runs no agents at all: `no_agent: true`, a shell script calling fixed Python. The
budget is time.

| Bound | Value | What it protects |
|-------|-------|------------------|
| Runs per day | 2 (02:00 early, 04:30 late) | — |
| `DEADLINE` | early 6600s / late 3600s | all scraping in that slot |
| `SITE_TIMEOUT` | 1500s, 2400s for indeed and linkedin | one site cannot take the budget of the sites after it |
| `MIN_SITE_SECONDS` | 180s | a site with less left is skipped rather than started and cut |
| `POST_DEADLINE` | late 5400s | the scoring passes leave room for notify |
| `SWEEP_DEADLINE` | 7020s | the whole run, 180s inside the Hermes cap |
| Sub-agent spawns | **0** | no model drives the run |

LLM spend inside it is bounded per stage by `--limit`, not by a token cap:
`skill_coverage_backfill --limit 400`, `llm_context_backfill --limit 250`,
`rescore_context --limit 400`. The gate that matters more is upstream — jobs the
filter already rejected must never reach a model call at all.

What each stage actually costs is now recorded rather than estimated:
`10_output/_llm_stats.tsv`, read with `llm_stats.py`. Use it before changing any
of the numbers above.

## L2 — the scraper repair loop

Runs one agent. The budget is attempts, and every bound below exists because the
failure it prevents is a standing bill rather than a single bad night.

| Bound | Value | What it prevents |
|-------|-------|------------------|
| Runs per day | 1 (07:00) | — |
| Sites per run | **1** | two at once doubles the spend before the first has proved anything |
| `MAX_ROUNDS` | 3 | an agent that will not converge retrying until the timeout |
| `MAX_ATTEMPTS_PER_SITE` | 2 | a genuinely unfixable scraper — one that now needs a login — being paid for every night forever |
| `AGENT_TIMEOUT` | 1200s | measured runs were 406s, 588s, 768s; 900 left no headroom |
| `VERIFY_TIMEOUT` / `TEST_TIMEOUT` | 900s / 600s | a hung scrape or suite holding the slot |
| Wrapper `timeout` | 5400s | the whole job, short of the Hermes cap so the summary still prints |
| Model rate | `deep-review` at rpm 4 / tpm 40000 | a Pro request eating the Gemini quota that flash callers share |

A startup failure — no credentials, unknown provider — is recorded as `blocked`
and **does not spend an attempt**. Without that, a config mistake would burn both
of a site's attempts and then stop trying a scraper no agent had ever looked at.

Most nights it spends nothing: no site is dry, so it selects nothing and exits
silent. The bounds are for the nights it does act.

## On budget exceed

1. `touch .loop-pause` in the repo root — the repair loop checks it first and
   exits before selecting anything.
2. To stop the nightly as well, disable its jobs:
   `HERMES_HOME=/home/kz003/.hermes/profiles/archivist hermes cron pause 45feb3a6d61c`
   (and `59283aceccaa`).
3. Note what happened under High Priority in [STATE.md](STATE.md). Nothing else
   writes there, so an unrecorded pause is an invisible one.

## Kill switch

`.loop-pause`, a file in the repo root. Present = the repair loop does nothing.
There is a test that pins its name and location, because a kill switch nobody
can find is not one.

It does not stop the nightly, deliberately: the nightly does not change code, and
stopping the thing that produces the documents is a different decision from
stopping the thing that edits the source.
