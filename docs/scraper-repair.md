# Repairing a scraper in this repo

Written for the agent `loop_repair.py` spawns, so it does not re-derive the same
things every night from a prompt that grows each time someone learns one. Read
this before editing anything; it is the difference between a fix and a rewrite.

## The shape every scraper has

```
_extract_<site>_jobs(page)        parse one listing page  → list[dict]
_fetch_job_description(page, url) one posting's body      → str | dict
scrape_<site>(keyword, location, …)  one search           → list[dict]
scrape_<site>_all(config)         every search the budget allows
```

`remote_apis` is the exception: three HTTP APIs (Remotive, Arbeitnow,
WeWorkRemotely) behind one `scrape_remote_apis_all`, no browser.

A break is almost always in `_extract_*` or `_fetch_job_description`. The `_all`
function is budget and iteration, and it changes far less often than markup.

## The contract a returned job must satisfy

`run.py` stages results with `save_raw_to_saved`, which drops **every record
without a `url` key**. A parse that fills every field but names that key
something else produces a scraper reporting a full count and staging nothing —
the scrape looks healthy in the log and the site reads as dry. Nothing else in
the record is load-bearing at scrape time.

Keys the rest of the pipeline expects: `title`, `company`, `location`, `salary`,
`snippet`, `description`, `url`, `source`, `type`, `source_site`, `scraped_at`.

## Do not reintroduce the cross product

Every site iterates `selection.search_pairs(config)`, never its own
`keywords × locations`. `keyword_locations` in config.yaml narrows some keywords
to a subset of locations, so the product describes searches no scraper walks,
and the timeout invariant counts the same pairs the scrapers do. A "simplifying"
rewrite back to nested loops silently multiplies the night's cost.

## Time is the binding constraint, not correctness

Each site runs under a per-site timeout inside a shared wall-clock deadline, and
a site that overruns loses the sites after it — for six nights in August 2026
guardian, adzuna and remote_apis never started at all. Measured scrape times,
2026-08-21: remote_apis 43s, adzuna 144s, guardian 638s, reed ~1400s, linkedin
~1527s, indeed ~1615s.

So: do not add sleeps, do not add retries around something that already retries,
and do not add a second request per posting where one already serves. Where a
delay exists it is usually deliberate — LinkedIn's guest detail endpoint 429s
under bursts, and Arbeitnow rate-limits a fast page walk.

## Matching is anchored on purpose

Keyword matching goes through `_kw_pattern()` in `cv_generator.py`, which stops a
keyword firing inside a longer word — `rse` used to match `nurse`, `course` and
`parser`. Scraped descriptions lose whitespace at HTML block joins
(`Azure DevOpsKnowledge of Power Apps`), so the right edge bans only a lowercase
continuation and matching runs on the original casing. Do not case-fold the text
before matching; that throws the signal away.

## What a real fix looks like

The site moved its markup and the selectors match nothing. The scraper finds no
elements, returns an empty list, and exits 0.

Prefer a selector that survives markup churn — a stable data attribute, a role,
a structural relationship — over one tuned to today's DOM. Where a fallback
chain already exists, add to it rather than replacing the head of it: the old
selector still works for cached pages and for whichever region has not been
migrated yet.

## How your change is judged

`run.py --site <site> --scrape-only` runs against the live site, and the gate
reads what was actually staged rather than the count the scraper printed:

- distinct absolute URLs, against a floor of a quarter of that site's best
  recorded night (minimum 3)
- distinct titles, at least half the record count — filler repeats
- the test suite still passes

A diff touching any file but the one scraper is discarded without being read.
