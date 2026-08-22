# Loop Run Log — Job Intelligence System

Written by `loop_repair.py`, one entry per attempt. Prune entries older than
30 days.

Only the L2 repair loop writes here. The nightly does not: it produces documents
and a Telegram summary, and has nothing to say that `_nightly_run_summary.tsv`
does not already record. This section stayed empty from the day loop-init
created the file until 2026-08-22, which is most of why a readiness score could
report 100/100 over a repo where no loop had ever run.

## Format

```json
{
  "run_id": "2026-06-09T08:15:00Z",
  "pattern": "daily-triage",
  "duration_s": 45,
  "items_found": 4,
  "actions_taken": 1,
  "escalations": 0,
  "tokens_estimate": 52000,
  "outcome": "report-only | fix-proposed | escalated | no-op"
}
```

## Recent Runs

<!-- Loop appends below this line -->