"""Re-fetch full descriptions for jobs held out as unscoreable.

The backlog these target came from two scraper faults, both since fixed:
adzuna's detail-page selector matched its own tracking scripts and stored
`window.addEventListener(...tokenData...)` as the description (67 jobs), and
some postings stored nothing at all (20 jobs). Every one was scraped on
2026-07-11/12, before commit b84bf12 landed the extraction fix — so re-fetching
with today's code should recover them.

Why not `run.py --fetch-descriptions`: it only targets jobs where the description
is FALSY, so the 67 JavaScript ones are invisible to it; it applies
scraper_indeed's extractor to every URL regardless of host; and it launches
headless=False, so it cannot run unattended.

It also covers the standing case, not just that backlog. With ADZUNA_APP_ID set,
scrape_adzuna_all takes the API branch, and the Adzuna API caps `description` at
500 characters ending in "…" with no full-text field at all — so every job it
returns is marked description_truncated and held out of review until this script
fills it in from the detail page.

Prefer `--top-only` for routine use. Detail pages are rate-limited (adzuna starts
answering 403 "suspicious behaviour" and then blocks everything), so the budget
should go to jobs a stage will actually act on; a truncated description is already
enough to rank one.

Runs in small batches by design (DEFAULT_BATCH). Adzuna tolerates a short burst
then refuses: 7 of 12 succeeded, and an uncapped 103-target run that followed
recovered 0 of 5 before being stopped — and left the site more hostile for the next
attempt. Working through a large backlog means repeating this command over hours,
not raising the cap.

    python3 refetch_unscoreable.py --dry-run
    python3 refetch_unscoreable.py --top-only        # routine, 12 at a time
    python3 refetch_unscoreable.py --top-only --limit 0   # no cap (expect blocks)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from matcher import is_junk_description  # noqa: E402
from selection import unscoreable_jobs  # noqa: E402

ANALYZED = ROOT / "10_output" / "_analyzed.json"
# Adzuna answers 403 "Our systems have detected suspicious behaviour" once it
# decides a client is scraping, and every request after that returns a ~288-char
# block page. At 2s between requests it tripped partway through a 5-job trial, so
# the delay is deliberately slower than the scrapers' own and rises after a block.
SETTLE_MS = 6000
BLOCKED_BACKOFF_MS = 60000
# Default cap per run. Adzuna tolerates a short burst and then refuses: 7 of 12
# succeeded, and the next run — 103 targets, no cap — recovered 0 of 5 before being
# stopped. Small batches spaced hours apart get through; one long run does not, and
# it deepens the block for the next attempt. Override with --limit.
DEFAULT_BATCH = 12
# Consecutive blocks after which continuing only deepens the ban. The remaining
# jobs are left untouched for a later run rather than recorded as unrecoverable.
MAX_CONSECUTIVE_BLOCKS = 3
# Write recoveries to disk this often. Small, because each page costs ~4s: losing
# 10 fetches to a crash is 40 seconds, losing 100 is most of the run.
CHECKPOINT_EVERY = 10


def _extractor(source: str):
    """(module-level fetch fn, returns_dict) for a job source, or None.

    Each scraper carries selectors for its own site, and reed's returns a dict
    while the others return a string — dispatching on source keeps the wrong
    site's selectors from being applied, which is what made run.py's shared
    indeed extractor useless here.
    """
    try:
        if source == "adzuna":
            from scraper_adzuna import _fetch_job_description
            return _fetch_job_description, False
        if source == "reed":
            from scraper_reed import _fetch_job_description
            return _fetch_job_description, True
        if source == "guardian":
            from scraper_guardian import _fetch_job_description
            return _fetch_job_description, False
        if source in ("indeed", "url_list"):
            from scraper_indeed import _fetch_job_description
            return _fetch_job_description, False
    except ImportError:
        return None
    return None


def _apply(got: dict[str, str], gone: list[str], backup: bool = False) -> int:
    """Write recovered descriptions and removal marks into the DB. Returns the count.

    Called as results arrive, not only at the end. The results used to be applied
    after the whole loop, so a browser error on the first URL discarded everything —
    and a rate-limit stop partway through discarded the recoveries already made.
    Rewriting the file per batch is cheap next to a 4s-per-page fetch.
    """
    if not got and not gone:
        return 0
    db = json.loads(ANALYZED.read_text(encoding="utf-8"))
    updated = 0
    for job in db:
        url = job.get("url")
        if url in gone:
            # Marked, not deleted: the job stays out of every re-fetch attempt from
            # here on, while remaining visible as a lead lost to a dead listing
            # rather than silently vanishing from the backlog.
            job["listing_removed"] = True
            continue
        desc = got.get(url)
        if desc and job.get("description") != desc:
            job["description"] = desc
            # Full text now, so the API-summary flag no longer applies — leaving it
            # set would keep the job out of review after it had been repaired.
            job.pop("description_truncated", None)
            # Drop the analysis computed from the broken text: skills were
            # extracted from JavaScript, and context was scored on it. Leaving
            # them would keep a fixed description paired with a poisoned score.
            job.pop("match", None)
            if isinstance(job.get("analysis"), dict):
                job["analysis"].pop("skills", None)
                job["analysis"].pop("skill_coverage", None)
            updated += 1
    if backup:
        shutil.copy2(ANALYZED, ANALYZED.with_suffix(".json.prerefetch"))
    ANALYZED.write_text(json.dumps(db, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
    return updated


async def _page_state(page, url: str) -> str:
    """'ok' | 'blocked' | 'gone' — checked before extraction.

    A 0-character result has three unrelated causes that must not be conflated: the
    posting was taken down (permanent), the site is rate-limiting us (retry later),
    or the selectors are stale (a bug). Treating a 403 block as "unrecoverable"
    would discard live postings, and treating it as a normal miss would keep
    hammering a site that has already started refusing.
    """
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
    except Exception:
        return "blocked"
    status = resp.status if resp else 0

    # Adzuna's /jobs/land/ad/ links bounce through a redirect, and evaluating while
    # that is in flight raises "Execution context was destroyed" — which killed the
    # whole run on its first URL. Settle first, then treat an evaluate failure as
    # "cannot tell", not as a crash: the caller's extractor gets its own attempt.
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass
    await page.wait_for_timeout(1500)

    async def _probe(js: str, default):
        try:
            return await page.evaluate(js)
        except Exception:
            return default

    body = (await _probe(
        "() => (document.body.innerText || '').slice(0, 400)", "") or "").lower()
    if status == 403 or "suspicious behaviour" in body or "unusual behaviour" in body:
        return "blocked"
    if "no longer available" in body or (status == 404 and "adp-body" not in body):
        # 404 alone is not proof: some removed-listing pages still render the
        # posting body, so the visible notice decides. Defaulting to False (not
        # gone) when the probe fails keeps a live posting from being written off.
        if await _probe(
                "() => document.querySelectorAll('[class*=\"adp-body\"]').length === 0",
                False):
            return "gone"
    return "ok"


async def refetch(targets: list[dict], headless: bool = True) -> tuple[dict[str, str], list[str]]:
    """({url: description}, gone_urls) — gone_urls are confirmed-removed postings."""
    from playwright.async_api import async_playwright

    got: dict[str, str] = {}
    gone: list[str] = []
    blocks = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox",
                  "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-GB",
            timezone_id="Europe/London",
        )
        page = await context.new_page()
        for i, job in enumerate(targets, 1):
            url, source = job.get("url"), job.get("source") or ""
            found = _extractor(source)
            if not url or not found:
                print(f"  [{i}/{len(targets)}] skip ({source}: no extractor)", flush=True)
                continue
            fetch_fn, returns_dict = found
            # Guard the probe too, not just fetch_fn. An unguarded browser call
            # anywhere in this loop ends the run and loses every recovery made so
            # far — "Execution context was destroyed" on the FIRST url did exactly
            # that, and the results were only written after the loop.
            try:
                state = await _page_state(page, url)
            except Exception as e:
                print(f"  [{i}/{len(targets)}] ✗ probe {type(e).__name__}: "
                      f"{str(e)[:50]}", flush=True)
                continue
            if state == "blocked":
                blocks += 1
                print(f"  [{i}/{len(targets)}] ⛔ rate-limited ({blocks}/"
                      f"{MAX_CONSECUTIVE_BLOCKS})", flush=True)
                if blocks >= MAX_CONSECUTIVE_BLOCKS:
                    print(f"  stopping: {len(targets) - i} jobs left untouched for a "
                          f"later run", flush=True)
                    break
                await page.wait_for_timeout(BLOCKED_BACKOFF_MS)
                continue
            blocks = 0
            if state == "gone":
                gone.append(url)
                print(f"  [{i}/{len(targets)}] ✗ removed  {(job.get('title') or '?')[:42]}",
                      flush=True)
                await page.wait_for_timeout(SETTLE_MS)
                continue
            try:
                result = await fetch_fn(page, url)
                desc = (result.get("description", "") if returns_dict and isinstance(result, dict)
                        else result) or ""
                desc = desc.strip()
            except Exception as e:
                print(f"  [{i}/{len(targets)}] ✗ {type(e).__name__}: {str(e)[:50]}", flush=True)
                continue
            # An empty extraction on a page that answered 200 is soft throttling:
            # the block page renders, so _page_state sees no 403 and no notice, but
            # the selectors find nothing. Counting it as a plain miss reset the block
            # counter, so alternating block/empty results never reached
            # MAX_CONSECUTIVE_BLOCKS and the run kept hammering a site that had
            # already stopped answering — 0 recoveries in 5 attempts, right after 7
            # of 12 had succeeded. Treated as a block so the backoff applies.
            if not desc:
                blocks += 1
                print(f"  [{i}/{len(targets)}] ⛔ empty extraction — treating as "
                      f"throttling ({blocks}/{MAX_CONSECUTIVE_BLOCKS})", flush=True)
                if blocks >= MAX_CONSECUTIVE_BLOCKS:
                    print(f"  stopping: {len(targets) - i} jobs left for a later run "
                          f"(site is refusing; retry in a few hours)", flush=True)
                    break
                await page.wait_for_timeout(BLOCKED_BACKOFF_MS)
                continue
            # Same bar the exclusion uses, so a "recovered" job cannot come back
            # still unreviewable — a short or scripted result is not a recovery.
            if len(desc) < 400 or is_junk_description(desc):
                reason = "junk" if is_junk_description(desc) else f"{len(desc)}c"
                print(f"  [{i}/{len(targets)}] – {reason:6s} {(job.get('title') or '?')[:42]}",
                      flush=True)
                continue
            got[url] = desc
            print(f"  [{i}/{len(targets)}] ✓ {len(desc):5d}c {(job.get('title') or '?')[:42]}",
                  flush=True)
            # Checkpoint. Whatever ends the run next — a browser error, a
            # rate-limit stop, an interrupt — the work up to here is already on disk.
            if len(got) % CHECKPOINT_EVERY == 0:
                print(f"    💾 checkpoint: {_apply(got, gone)} jobs written", flush=True)
            await page.wait_for_timeout(SETTLE_MS)
        await browser.close()
    return got, gone


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=DEFAULT_BATCH,
                    help=f"jobs per run (default {DEFAULT_BATCH}); 0 for no cap. "
                         f"Adzuna refuses after a short burst, so repeat small "
                         f"batches hours apart rather than raising this")
    ap.add_argument("--source", help="only this source (e.g. adzuna)")
    ap.add_argument("--show-browser", action="store_true",
                    help="run with a visible browser (debugging a blocked site)")
    ap.add_argument("--top-only", action="store_true",
                    help="only jobs inside the generation/review top-%% — use this for "
                         "routine runs, where fetching the whole backlog would spend "
                         "the rate-limit budget on jobs no stage will act on")
    args = ap.parse_args()

    targets = unscoreable_jobs()
    if args.top_only:
        # Ranking works from a truncated description; only review needs the full
        # text, so the fetch budget belongs to jobs that actually reach a stage.
        # ranked_jobs excludes unscoreable jobs, so the top-% must be computed from
        # the pool WITH them present — otherwise nothing here would ever qualify.
        from selection import _dedupe, load_config, stage_percent, top_percent_count
        from filter import passes_filter

        cfg = load_config()
        pool = [
            j for j in _dedupe(json.loads(ANALYZED.read_text(encoding="utf-8")))
            if j.get("match") and passes_filter(j, cfg)[0]
            and j.get("match", {}).get("composite_score", 0) > 0
        ]
        pool.sort(key=lambda j: j["match"]["composite_score"], reverse=True)
        pct = max(stage_percent(cfg, s) for s in ("generation", "review"))
        wanted = {id(j) for j in pool[: top_percent_count(len(pool), pct)]}
        by_url = {j.get("url") for j in pool if id(j) in wanted}
        targets = [j for j in targets if j.get("url") in by_url]
        print(f"--top-only: {len(targets)} of the backlog sit inside the top {pct:g}%")
    if args.source:
        targets = [j for j in targets if j.get("source") == args.source]
    targets = [j for j in targets if j.get("url") and not j.get("listing_removed")]
    if args.limit:  # 0 disables the cap
        targets = targets[: args.limit]

    from collections import Counter
    print(f"unscoreable with a URL: {len(targets)}  "
          f"{dict(Counter(j.get('source') for j in targets))}")
    if args.dry_run:
        for j in targets:
            state = "junk" if is_junk_description(j.get("description") or "") else \
                f"{len((j.get('description') or '').strip())}c"
            print(f"  {j.get('source'):9s} {state:6s} {(j.get('title') or '?')[:46]}")
        print("\nDRY RUN — nothing fetched")
        return 0
    if not targets:
        return 0

    try:
        got, gone = asyncio.run(refetch(targets, headless=not args.show_browser))
    except Exception as e:
        # Browser teardown or the loop itself can still fail. The checkpoints have
        # already persisted the recoveries, so report and exit non-zero rather than
        # dying with a traceback that implies nothing was saved.
        print(f"\n✗ run ended early: {type(e).__name__}: {str(e)[:100]}")
        print("  recoveries written before this point are already saved "
              "(checkpointed); re-run to continue.")
        return 1
    print(f"\nrecovered: {len(got)}/{len(targets)}   confirmed removed: {len(gone)}")
    if not got and not gone:
        return 0

    updated = _apply(got, gone, backup=True)
    print(f"updated {updated} jobs in {ANALYZED.name}")
    print("\nNext: re-analyse the cleared jobs, then re-review them:")
    print("  .venv/bin/python3 run.py --reanalyze --llm-context")
    print("  .venv/bin/python3 rereview_top.py --new-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
