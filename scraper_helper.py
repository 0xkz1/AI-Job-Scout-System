"""
Scraper Optimization Helper
===========================
Provides high-performance, ethical, and speed optimizations for AI Job Scout System scrapers:
1. Cache-based deduplication: Load historical job descriptions to completely skip HTTP requests.
2. Resource blocking: Intercept images, CSS, fonts, and trackers in Playwright to load detail pages 6x faster.
3. Concurrent fetching: Fetch multiple descriptions concurrently using Playwright browser contexts with Semaphore.
"""

import os
import json
import asyncio
from typing import Dict, Tuple, List

# Define resource types and domains to block
BLOCKED_RESOURCES = {"image", "font", "stylesheet", "media", "websocket", "eventsource"}
BLOCKED_DOMAINS = [
    "analytics", "telemetry", "google-analytics", "doubleclick", "facebook", "tracking",
    "adsystem", "googlesyndication", "adsense", "hotjar", "sentry", "datadog", "mixpanel",
    "optimizely", "intercom", "amplitude", "segment", "crazyegg", "mouseflow", "hubspot"
]

def load_description_cache() -> Dict[Tuple[str, str], dict]:
    """
    Scans 10_output/_analyzed.json and 00_saved/*.json files to build a mapping of
    (title, company) -> job_dict where the description is already fetched.
    """
    cache = {}
    base_dir = "/media/kz003/atelier/00_Kazuki/career/Job-Intelligence-System"
    
    # 1. Load from _analyzed.json (final analyzed database)
    analyzed_path = os.path.join(base_dir, "10_output", "_analyzed.json")
    if os.path.exists(analyzed_path):
        try:
            with open(analyzed_path, "r", encoding="utf-8") as f:
                jobs = json.load(f)
                for job in jobs:
                    title = job.get("title", "").strip().lower()
                    company = job.get("company", "").strip().lower()
                    if title and company and job.get("description"):
                        cache[(title, company)] = job
        except Exception as e:
            print(f"  ⚠ Helper Cache: Error loading _analyzed.json: {e}")
            
    # 2. Load from 00_saved/*.json (staging/raw files)
    saved_dir = os.path.join(base_dir, "00_saved")
    if os.path.exists(saved_dir):
        for f in os.listdir(saved_dir):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(saved_dir, f), "r", encoding="utf-8") as fh:
                        jobs = json.load(fh)
                        for job in jobs:
                            title = job.get("title", "").strip().lower()
                            company = job.get("company", "").strip().lower()
                            if title and company and job.get("description"):
                                cache[(title, company)] = job
                except Exception:
                    pass
                    
    if cache:
        print(f"  🧠 Helper Cache: Loaded {len(cache)} historical job descriptions into memory.")
    return cache


async def block_media_and_trackers(route):
    """Intercepts and aborts resource requests in Playwright to maximize load speed."""
    req = route.request
    resource_type = req.resource_type
    url = req.url.lower()
    
    if resource_type in BLOCKED_RESOURCES:
        await route.abort()
        return
        
    for domain in BLOCKED_DOMAINS:
        if domain in url:
            await route.abort()
            return
            
    await route.continue_()


async def fetch_descriptions_sequential(
    context, 
    jobs: List[dict], 
    cache: Dict[Tuple[str, str], dict], 
    fetch_fn, 
    sleep_delay: float = 1.0
):
    """
    Fetch missing descriptions for jobs using a single reused page.
    - Plan A: Skip if cache hit (title, company)
    - Plan B: Block media/trackers for faster page loads
    - Plan C: Dropped — concurrency causes EPIPE on this environment. Serial is slower but stable.
    """
    fetched_count = 0
    skipped_count = 0
    total_jobs = len(jobs)
    
    jobs_needing_fetch = []
    
    # 1. 🎯 Cache Hit check — skip fetch entirely
    for job in jobs:
        title = job.get("title", "").strip().lower()
        company = job.get("company", "").strip().lower()
        key = (title, company)
        
        if key in cache:
            cached_job = cache[key]
            if cached_job.get("description"):
                job["description"] = cached_job["description"]
                job["snippet"] = cached_job.get("snippet", cached_job["description"][:300])
                if "analysis" in cached_job:
                    job["analysis"] = cached_job["analysis"]
                skipped_count += 1
                continue
        
        if job.get("url") and not job.get("description"):
            jobs_needing_fetch.append(job)
    
    print(f"  📄 Processing descriptions for {total_jobs} jobs ({skipped_count} cache hits, {len(jobs_needing_fetch)} to fetch)...")
    
    if not jobs_needing_fetch:
        print(f"    → Fast Fetch Done: 0 fetched, {skipped_count} skipped (cache hits) out of {total_jobs} jobs.")
        return
    
    # 2. 🌐 Live Fetch — serial, single reused page (no EPIPE)
    page = await context.new_page()
    try:
        await page.route("**/*", block_media_and_trackers)
        
        for job in jobs_needing_fetch:
            try:
                url = job.get("url")
                if not url:
                    continue
                desc = await fetch_fn(page, url)
                if desc:
                    job["description"] = desc
                    job["snippet"] = desc[:300]
                    title = job.get("title", "").strip().lower()
                    company = job.get("company", "").strip().lower()
                    cache[(title, company)] = job
                    fetched_count += 1
                    if fetched_count % 5 == 0:
                        print(f"    → Fetched {fetched_count} descriptions...")
                if sleep_delay > 0:
                    await asyncio.sleep(sleep_delay)
            except Exception:
                pass
    finally:
        try:
            await page.close()
        except Exception:
            pass
    
    print(f"    → Fast Fetch Done: {fetched_count} fetched, {skipped_count} skipped (cache hits) out of {total_jobs} jobs.")
