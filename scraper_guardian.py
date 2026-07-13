"""
Guardian Jobs Scraper
=====================
Scrapes job listings from Guardian Jobs (jobs.theguardian.com) using Playwright.

Guardian Jobs has strong creative/arts/media job coverage.
No aggressive bot detection — Playwright with stealth works fine.

Usage (standalone):
    python scraper_guardian.py
"""

import asyncio
import json
import os
import re
from datetime import datetime
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from scraper_helper import load_description_cache, fetch_descriptions_sequential

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "10_output")


def sanitize_filename(text: str, max_len: int = 80) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', "", text).strip().replace(" ", "_")
    return safe[:max_len]


async def _extract_guardian_jobs(page) -> list[dict]:
    """Extract job listings from the current Guardian Jobs search results page."""
    try:
        jobs = await page.evaluate("""() => {
            const results = [];
            const items = document.querySelectorAll('li.lister__item');

            items.forEach(li => {
                // Title from h3 heading link
                const titleEl = li.querySelector('h3.lister__header a span');
                if (!titleEl) return;
                const title = (titleEl.textContent || '').trim();
                if (!title) return;

                // Job URL from the title link
                const titleLink = li.querySelector('h3.lister__header a');
                const url = titleLink ? (titleLink.href || '') : '';

                // Location
                let location = '';
                const locationEl = li.querySelector('li.lister__meta-item--location');
                if (locationEl) location = locationEl.textContent.trim();

                // Salary
                let salary = '';
                const salaryEl = li.querySelector('li.lister__meta-item--salary');
                if (salaryEl) salary = salaryEl.textContent.trim();

                // Company (recruiter)
                let company = '';
                const companyEl = li.querySelector('li.lister__meta-item--recruiter');
                if (companyEl) company = companyEl.textContent.trim();

                // Description snippet
                let snippet = '';
                const descEl = li.querySelector('p.lister__description');
                if (descEl) snippet = descEl.textContent.trim().slice(0, 500);

                results.push({
                    title: title,
                    company: company,
                    location: location,
                    salary: salary,
                    snippet: snippet,
                    description: '',
                    url: url,
                    source: 'guardian',
                    type: 'auto',
                    source_site: 'Guardian Jobs',
                    scraped_at: new Date().toISOString(),
                });
            });

            return results;
        }""")
        return jobs if jobs else []
    except Exception:
        return []


async def _fetch_job_description(page, job_url: str) -> str:
    """Navigate to a job's detail page and extract the full description."""
    try:
        await page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)

        desc = await page.evaluate("""() => {
            const selectors = [
                '[class*=\"job-description\"]',
                '[class*=\"description\"]',
                '[data-qa=\"job-description\"]',
                '.job-detail__description',
                '.job-description__content',
                'main section:last-child',
                'article [class*=\"body\"]',
                'article [class*=\"content\"]',
                '.lister__description--full',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.textContent.trim().length > 100) {
                    return el.textContent.trim().slice(0, 5000);
                }
            }
            // Fallback: grab main content
            const main = document.querySelector('main');
            if (main) {
                const text = main.textContent.trim();
                if (text.length > 200) return text.slice(0, 5000);
            }
            return '';
        }""")
        return desc or ""
    except Exception:
        return ""


async def scrape_guardian(
    keyword: str,
    location: str = "",
    max_pages: int = 3,
    config: dict | None = None,
    cache: dict | None = None,
    playwright_instance=None,
) -> list[dict]:
    """
    Search Guardian Jobs and return job listings.

    Args:
        keyword: Job title / search term
        location: City or "Remote"
        max_pages: Number of result pages to scrape
        config: Configuration dict

    Returns:
        List of job dicts
    """
    jobs = []
    seen_urls = set()

    # Build search URL
    kw_q = quote_plus(keyword)
    loc_q = quote_plus(location) if location else ""
    if loc_q:
        search_url = f"https://jobs.theguardian.com/jobs/?q={kw_q}&location={loc_q}"
    else:
        search_url = f"https://jobs.theguardian.com/jobs/?q={kw_q}"

    if not playwright_instance:
        raise ValueError("playwright_instance is required — call from scrape_guardian_all")

    p = playwright_instance
    browser = await p.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )

    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1920, "height": 1080},
        locale="en-GB",
        timezone_id="Europe/London",
    )
    page = await context.new_page()

    print(f"🔍 Guardian Jobs: searching '{keyword}' in '{location}'...")
    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)
    except Exception as e:
        print(f"  ⚠ Navigation error for '{keyword}' in '{location}': {e}")
        try:
            print(f"  Retrying...")
            await page.wait_for_timeout(2000)
            await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
        except Exception as e2:
            print(f"  ✗ Skipping '{keyword}' in '{location}': {e2}")
            await browser.close()
            return []

    for page_num in range(1, max_pages + 1):
        # Check for no results
        page_title = await page.title()
        body_text = await page.evaluate("() => document.body.textContent.toLowerCase().slice(0, 500)")
        if "0 jobs" in body_text and "found" in body_text:
            print(f"  ⚠ No jobs found for this search.")
            break

        # Extract jobs from current page
        page_jobs = await _extract_guardian_jobs(page)
        print(f"  Page {page_num}: found {len(page_jobs)} job cards")

        for j in page_jobs:
            if j["url"] and j["url"] not in seen_urls:
                seen_urls.add(j["url"])
                jobs.append(j)

        # Navigate to next page
        if page_num >= max_pages:
            break

        next_url = None
        # Guardian uses numbered pagination: /jobs/2/, /jobs/3/, ...
        current_page_num = page_num + 1
        next_url = f"https://jobs.theguardian.com/jobs/{current_page_num}/?q={kw_q}"
        if loc_q:
            next_url += f"&location={loc_q}"

        try:
            await page.goto(next_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
        except Exception:
            print(f"  ⚠ Could not navigate to page {current_page_num}.")
            break

    # --- Fetch full descriptions from detail pages ---
    if jobs:
        if cache is None:
            cache = load_description_cache()
        await fetch_descriptions_sequential(
            context,
            jobs,
            cache,
            _fetch_job_description,
            sleep_delay=1.0
        )

    await browser.close()

    print(f"  ✓ Total: {len(jobs)} unique jobs from Guardian Jobs")
    return jobs


async def scrape_guardian_all(config: dict) -> list[dict]:
    """Run Guardian Jobs scraper for all keyword+location combos in config."""
    all_jobs = []
    seen = set()
    cache = load_description_cache()

    locations = config.get("locations", [""])
    keywords = config.get("keywords", [])
    max_pages = config.get("max_pages_per_search", 3)

    async with async_playwright() as p:
        for kw in keywords:
            for loc in locations:
                jobs = await scrape_guardian(kw, loc, max_pages=max_pages, config=config, cache=cache, playwright_instance=p)
                for j in jobs:
                    dedup_key = (j["title"], j.get("company", ""), j.get("location", ""))
                    if dedup_key not in seen:
                        seen.add(dedup_key)
                        all_jobs.append(j)

    return all_jobs


# ── CLI ──
if __name__ == "__main__":
    import yaml

    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    jobs = asyncio.run(scrape_guardian_all(cfg))
    from scraper_indeed import save_jobs
    save_jobs(jobs)
    print(f"\n✅ Done! {len(jobs)} jobs scraped from Guardian Jobs.")
