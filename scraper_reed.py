"""
Reed.co.uk Job Scraper
======================
Scrapes job listings from Reed.co.uk using Playwright.

Reed is the UK's largest job board. No aggressive bot detection —
Playwright with stealth works fine.

Usage (standalone):
    python scraper_reed.py
"""

import asyncio
import json
import os
import re
import requests as _requests_sync
from datetime import datetime
from html import unescape
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from scraper_helper import load_description_cache, fetch_descriptions_sequential

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "10_output")


def sanitize_filename(text: str, max_len: int = 80) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', "", text).strip().replace(" ", "_")
    return safe[:max_len]


async def _handle_cookie_consent(page):
    """Accept cookie consent if shown (OneTrust on Reed)."""
    try:
        await page.evaluate("""() => {
            const btn = document.querySelector(
                '#onetrust-accept-btn-handler, ' +
                '.ot-btn-container button, ' +
                '[id*="accept"], ' +
                '[class*="accept"]'
            );
            if (btn) btn.click();
        }""")
        await page.wait_for_timeout(500)
    except Exception:
        pass


async def _extract_reed_jobs(page) -> list[dict]:
    """Extract job listings from the current Reed search results page."""
    try:
        jobs = await page.evaluate("""() => {
            const results = [];
            const articles = document.querySelectorAll('article');

            articles.forEach(article => {
                // Title from h2 heading link
                const titleEl = article.querySelector('h2 a');
                if (!titleEl) return;
                const title = (titleEl.textContent || '').trim();
                if (!title) return;

                // Job URL
                const url = titleEl.href || '';

                // Company — in a link after "by" text, or in a company link
                const companyEl = article.querySelector(
                    'a[href*="/jobs/"]:not(h2 a), ' +
                    'a[data-qa="job-card-company-link"], ' +
                    'sectionheader a[href*="-jobs"], ' +
                    'a[class*="company"]'
                );
                // Fallback: find the link that's not the title link
                let company = '';
                if (companyEl) {
                    company = companyEl.textContent.trim();
                } else {
                    // Try finding "by" text and getting next link
                    const allLinks = article.querySelectorAll('a');
                    const titleLink = titleEl.getAttribute('href') || '';
                    for (const link of allLinks) {
                        const href = link.getAttribute('href') || '';
                        const text = link.textContent.trim();
                        if (href !== titleLink && text && 
                            !href.includes('#') && 
                            !text.includes('jobs') &&
                            link.closest('sectionheader')) {
                            company = text;
                            break;
                        }
                    }
                }

                // List items with metadata
                const metaItems = article.querySelectorAll('li');
                let salary = '';
                let location = '';
                let employment_type = '';

                metaItems.forEach(li => {
                    const text = li.textContent.trim();
                    const img = li.querySelector('img');
                    if (img) {
                        const alt = (img.getAttribute('alt') || img.getAttribute('aria-label') || '').toLowerCase();
                        if (alt.includes('salary')) salary = text.replace(img.outerHTML, '').trim();
                        else if (alt.includes('location')) location = text.replace(img.outerHTML, '').trim();
                        else if (alt.includes('clock') || alt.includes('time')) employment_type = text.replace(img.outerHTML, '').trim();
                    }
                    // Fallback detection by text patterns
                    if (!salary && /£\\d|salary|negotiable|competitive|DOE/i.test(text)) salary = text;
                    if (!location && /edinburgh|glasgow|london|remote|united kingdom/i.test(text)) location = text;
                    if (!employment_type && /permanent|contract|full.time|part.time|temporary/i.test(text)) employment_type = text;
                });

                // Description snippet — if the "See job description" section is expanded
                const descSection = article.querySelector('[class*="see-more"], [class*="description"], [class*="job-description"]');
                const snippet = descSection ? descSection.textContent.trim().slice(0, 500) : '';

                results.push({
                    title: title,
                    company: company,
                    location: location,
                    salary: salary,
                    snippet: snippet,
                    description: '',
                    url: url,
                    source: 'reed',
                    type: 'auto',
                    source_site: 'Reed',
                    scraped_at: new Date().toISOString(),
                });
            });

            return results;
        }""")
        return jobs if jobs else []
    except Exception:
        return []


def _fetch_reed_description_sync(job_url: str) -> str:
    """
    Fetch full job description from a Reed detail page via HTTP (no browser needed).
    Extracts from Schema.org JSON-LD (type=JobPosting) which Reed always includes
    in its server-rendered HTML. Falls back to data-qa="job-description" HTML parsing.
    """
    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
    }
    try:
        resp = _requests_sync.get(job_url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # 1) Try JSON-LD (Schema.org JobPosting) — most reliable
        ld_blocks = re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL
        )
        for block in ld_blocks:
            try:
                data = json.loads(block)
                if isinstance(data, dict) and data.get("@type") == "JobPosting":
                    raw_desc = data.get("description", "")
                    if raw_desc:
                        # Strip HTML tags, unescape entities
                        clean = re.sub(r"<[^>]+>", " ", raw_desc)
                        clean = unescape(clean)
                        clean = re.sub(r"\s+", " ", clean).strip()
                        if len(clean) > 100:
                            return clean[:6000]
            except (json.JSONDecodeError, Exception):
                continue

        # 2) Fallback: data-qa="job-description" HTML block
        m = re.search(
            r'data-qa=["\']job-description["\'][^>]*>(.*?)</(?:div|section|article)>',
            html, re.DOTALL
        )
        if m:
            raw = m.group(1)
            clean = re.sub(r"<[^>]+>", " ", raw)
            clean = unescape(clean)
            clean = re.sub(r"\s+", " ", clean).strip()
            if len(clean) > 100:
                return clean[:6000]

        return ""
    except Exception as e:
        print(f"  ⚠ Reed HTTP fetch error for {job_url}: {e}")
        return ""


async def _fetch_job_description(page, job_url: str) -> str:
    """
    Async wrapper for Reed description fetch — uses synchronous HTTP (not Playwright)
    for reliability. The `page` arg is kept for interface compatibility but not used.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_reed_description_sync, job_url)


async def scrape_reed(
    keyword: str,
    location: str = "",
    max_pages: int = 3,
    config: dict | None = None,
    cache: dict | None = None,
    playwright_instance=None,
) -> list[dict]:
    """
    Search Reed.co.uk and return job listings.

    Args:
        keyword: Job title / search term
        location: City or "Remote"
        max_pages: Number of result pages to scrape
        config: Configuration dict (for cookie paths, etc.)
        playwright_instance: A playwright instance from async_playwright() — avoids creating a new Node.js process each call

    Returns:
        List of job dicts
    """
    jobs = []
    seen_urls = set()

    # Build search URL — Reed uses hyphenated paths or query params
    kw_slug = keyword.lower().replace(" ", "-")
    loc_slug = location.lower().replace(" ", "-") if location else ""
    if loc_slug:
        search_url = f"https://www.reed.co.uk/jobs/{kw_slug}-jobs-in-{loc_slug}"
    else:
        search_url = f"https://www.reed.co.uk/jobs/{kw_slug}-jobs"

    if not playwright_instance:
        raise ValueError("playwright_instance is required — call from scrape_reed_all")

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

    print(f"🔍 Reed: searching '{keyword}' in '{location}'...")
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

    # Handle cookie consent
    await _handle_cookie_consent(page)

    for page_num in range(1, max_pages + 1):
        # Check if we got search results (not an error/no-results page)
        page_title = await page.title()
        if "0 jobs" in page_title.lower() or "no jobs" in page_title.lower():
            print(f"  ⚠ No jobs found for this search.")
            break

        # Extract jobs from current page
        page_jobs = await _extract_reed_jobs(page)
        print(f"  Page {page_num}: found {len(page_jobs)} job cards")

        for j in page_jobs:
            if j["url"] and j["url"] not in seen_urls:
                seen_urls.add(j["url"])
                jobs.append(j)

        # Try to go to next page
        next_link = await page.query_selector(
            'a[rel="next"], '
            'a:has-text("Next"), '
            'a:has-text("next"), '
            'a.pagination__next, '
            'li.pagination__next a'
        )
        if next_link:
            try:
                href = await next_link.get_attribute("href")
                if href and href != "#":
                    await page.goto(
                        "https://www.reed.co.uk" + href if href.startswith("/") else href,
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    await page.wait_for_timeout(2000)
                    await _handle_cookie_consent(page)
                else:
                    print("  ✓ No more pages.")
                    break
            except Exception:
                print("  ⚠ Could not navigate to next page.")
                break
        else:
            print("  ✓ No more pages.")
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

    print(f"  ✓ Total: {len(jobs)} unique jobs from Reed")
    return jobs


async def scrape_reed_all(config: dict) -> list[dict]:
    """Run Reed scraper for all keyword+location combos in config."""
    all_jobs = []
    seen = set()
    cache = load_description_cache()

    locations = config.get("locations", [""])
    keywords = config.get("keywords", [])
    max_pages = config.get("max_pages_per_search", 3)

    async with async_playwright() as p:
        for kw in keywords:
            for loc in locations:
                jobs = await scrape_reed(kw, loc, max_pages=max_pages, config=config, cache=cache, playwright_instance=p)
                for j in jobs:
                    dedup_key = (j["title"], j.get("company", ""), j.get("location", ""))
                    if dedup_key not in seen:
                        seen.add(dedup_key)
                        all_jobs.append(j)

    # --- Filter by keywords ---
    from scraper_indeed import filter_jobs_by_keywords
    all_jobs = filter_jobs_by_keywords(all_jobs, keywords)

    return all_jobs


# ── CLI ──
if __name__ == "__main__":
    import yaml

    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    jobs = asyncio.run(scrape_reed_all(cfg))
    from scraper_indeed import save_jobs
    save_jobs(jobs)
    print(f"\n✅ Done! {len(jobs)} jobs scraped from Reed.")
