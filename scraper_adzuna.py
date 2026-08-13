"""
Adzuna UK Scraper
=================
Scrapes job listings from Adzuna UK (www.adzuna.co.uk) using Playwright.

Adzuna aggregates from 1000+ sources across the UK.
No aggressive bot detection — Playwright works fine.

Usage (standalone):
    python scraper_adzuna.py
"""

import asyncio
import json
import os
import re
import time
from datetime import datetime
from urllib.parse import quote_plus

import requests
from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from scraper_helper import load_description_cache, fetch_descriptions_sequential

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "10_output")


def sanitize_filename(text: str, max_len: int = 80) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', "", text).strip().replace(" ", "_")
    return safe[:max_len]


async def _extract_adzuna_jobs(page) -> list[dict]:
    """Extract job listings from the current Adzuna search results page."""
    try:
        jobs = await page.evaluate(r"""() => {
            const results = [];
            const articles = document.querySelectorAll('article');

            articles.forEach(article => {
                // Title from h2 > a
                const titleLink = article.querySelector('h2 a[data-js="jobLink"]');
                if (!titleLink) return;
                const title = (titleLink.textContent || '').trim();
                if (!title) return;
                const url = titleLink.href || '';

                // Company: try logo alt text first, otherwise extract from text
                let company = '';
                const logoImg = article.querySelector('.ui-logo-col img');
                if (logoImg && logoImg.alt && logoImg.alt !== 'Company logo') {
                    company = logoImg.alt.trim().replace(/\s+logo$/i, '').trim();
                }

                // Location: from ui-location class
                let location = '';
                const locEl = article.querySelector('.ui-location');
                if (locEl) {
                    location = locEl.textContent.trim();
                }

                // Salary: from JOBSWORTH link or visible salary text
                let salary = '';
                const salaryEl = article.querySelector('.ui-salary');
                if (salaryEl) {
                    // First try visible salary (not inside JOBSWORTH)
                    const salaryTexts = Array.from(salaryEl.querySelectorAll('*'))
                        .map(el => el.textContent.trim())
                        .filter(t => /£/.test(t) && !t.includes('JOBSWORTH'));
                    // Also try the jobsworth value
                    const jobsworthEl = salaryEl.querySelector('[data-js="toggle-jobsworth"] span');
                    if (salaryTexts.length > 0) {
                        salary = salaryTexts[0];
                    } else if (jobsworthEl) {
                        salary = '£' + jobsworthEl.textContent.trim();
                    }
                }

                // If no company from logo, try to extract from article text
                if (!company) {
                    // Get all direct text nodes / children text
                    const allText = Array.from(article.querySelectorAll('*'))
                        .map(el => el.textContent.trim())
                        .filter(t => t.length > 2 && t.length < 80);
                    // Find text that looks like a company name (all caps, not a location)
                    const locationText = location.toLowerCase();
                    const companyText = allText.find(t => {
                        const lower = t.toLowerCase();
                        return /^[A-Z][A-Z\s&.]+$/.test(t) && 
                               t !== location && 
                               !lower.includes('jobsworth') &&
                               !lower.includes('top match') &&
                               !lower.includes('easy apply') &&
                               !lower.includes('closing soon') &&
                               t.length < 60 && t.length > 3;
                    });
                    if (companyText) company = companyText;
                }

                // Description snippet
                let snippet = '';
                const snippetEl = article.querySelector('.max-snippet-height, [class*="snippet"]');
                if (snippetEl) {
                    snippet = snippetEl.textContent.trim().slice(0, 500);
                } else {
                    // Fallback: get text after the salary section
                    const allSpans = Array.from(article.querySelectorAll('span'))
                        .filter(s => s.textContent.trim().length > 50);
                    if (allSpans.length > 0) {
                        snippet = allSpans[0].textContent.trim().slice(0, 500);
                    }
                }

                results.push({
                    title: title,
                    company: company,
                    location: location,
                    salary: salary,
                    snippet: snippet,
                    description: '',
                    url: url,
                    source: 'adzuna',
                    type: 'auto',
                    source_site: 'Adzuna',
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
        await page.goto(job_url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(2000)

        desc = await page.evaluate("""() => {
            // textContent includes the raw source of <script>/<style> tags,
            // and '[data-js*="description"]' can match Adzuna's tracking
            // scripts (they tag JS hooks with data-js site-wide) — this
            // once caused the "description" to be a client-side analytics
            // snippet (window.addEventListener(...tokenData...)) instead
            // of the actual job posting. Reject non-content tags and any
            // text that looks like inline JS rather than prose.
            const looksLikeJs = (t) => /^\\s*(window\\.|var |const |let |function\\s*\\(|\\(function|document\\.)/.test(t)
                || t.includes('addEventListener') || t.includes('tokenData');
            const isContentEl = (el) => !['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(el.tagName);

            // Adzuna detail page selectors. '[class*="adp-body"]' leads because
            // it is what the current markup uses — as of 2026-07-25 every one of
            // the older selectors matched ZERO elements on a live detail page,
            // which is why adzuna stopped yielding descriptions after 07-12 and
            // why the tracking-script text got picked up instead.
            const selectors = [
                '[class*="adp-body"]',
                '[class*="job-description"]',
                '[class*="description__text"]',
                '[data-js*="description"]',
                '.job-description-section',
                '.ad-detail *',
                'main [class*="prose"]',
                '[itemprop="description"]',
                '[class*="detail"] p',
            ];
            // innerText, not textContent: textContent concatenates the source of
            // <script> tags and every hidden nav/consent string, so a page whose
            // real prose is fine still trips looksLikeJs and returns nothing.
            // That is how the <main> fallback below failed on pages holding 4600
            // characters of readable posting.
            const readable = (el) => (el.innerText || el.textContent || '').trim();
            for (const sel of selectors) {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    if (!isContentEl(el)) continue;
                    const text = readable(el);
                    if (text.length > 150 && !looksLikeJs(text)) {
                        return text.slice(0, 5000);
                    }
                }
            }
            // Fallback
            const main = document.querySelector('main');
            if (main) {
                const text = readable(main);
                if (text.length > 200 && !looksLikeJs(text)) return text.slice(0, 5000);
            }
            return '';
        }""")
        return desc or ""
    except Exception:
        return ""


async def scrape_adzuna(
    keyword: str,
    location: str = "",
    max_pages: int = 3,
    config: dict | None = None,
    cache: dict | None = None,
    playwright_instance=None,
) -> list[dict]:
    """
    Search Adzuna UK and return job listings.

    Args:
        keyword: Job title / search term
        location: City or region in UK
        max_pages: Number of result pages to scrape
        config: Configuration dict

    Returns:
        List of job dicts
    """
    jobs = []
    seen_urls = set()

    # Build search URL
    kw_q = quote_plus(keyword)
    loc_q = quote_plus(location) if location else "uk"
    search_url = f"https://www.adzuna.co.uk/jobs/search?q={kw_q}&l={loc_q}"

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

    print(f"🔍 Adzuna: searching '{keyword}' in '{location}'...")
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
        body_text = await page.evaluate("() => document.body.textContent.toLowerCase().slice(0, 500)")
        if "0 jobs" in body_text and "found" in body_text:
            print(f"  ⚠ No jobs found for this search.")
            break

        # Check for CAPTCHA
        if "captcha" in body_text or "sorry" in body_text[:200]:
            print(f"  ⚠ CAPTCHA/page blocked on page {page_num}. Stopping.")
            break

        # Extract jobs from current page
        page_jobs = await _extract_adzuna_jobs(page)
        print(f"  Page {page_num}: found {len(page_jobs)} job cards")

        for j in page_jobs:
            if j["url"] and j["url"] not in seen_urls:
                seen_urls.add(j["url"])
                jobs.append(j)

        # Navigate to next page
        if page_num >= max_pages:
            break

        next_url = f"https://www.adzuna.co.uk/jobs/search?q={kw_q}&l={loc_q}&p={page_num + 1}"

        try:
            await page.goto(next_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
        except Exception:
            print(f"  ⚠ Could not navigate to page {page_num + 1}.")
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

    print(f"  ✓ Total: {len(jobs)} unique jobs from Adzuna")
    return jobs


# ── Adzuna official REST API (multi-country) ──────────────────────────────
# Preferred path when ADZUNA_APP_ID / ADZUNA_APP_KEY are set (free tier). Covers
# gb, de, nl, fr, at, es, it, pl, us … one call returns title/company/location/
# salary/description, so no Playwright + detail-page fetch needed.

_ADZUNA_CURRENCY = {"gb": "£", "de": "€", "nl": "€", "fr": "€", "at": "€",
                    "es": "€", "it": "€", "us": "$", "pl": "zł"}


def _fmt_adzuna_salary(smin, smax, country: str) -> str:
    sym = _ADZUNA_CURRENCY.get(country, "")
    def f(v):
        return f"{sym}{v:,.0f}"
    if smin and smax:
        return f"{f(smin)} - {f(smax)}"
    if smax:
        return f(smax)
    if smin:
        return f(smin)
    return ""


def scrape_adzuna_api(keyword: str, country: str, app_id: str, app_key: str,
                      max_pages: int = 3, results_per_page: int = 50) -> list[dict]:
    """Query the Adzuna API for one keyword in one country. Non-UK queries are
    biased toward remote (a UK YMS resident works these remotely, not on-site)."""
    jobs = []
    # gb kept broad (UK on-site is in scope); non-UK narrowed to remote.
    what = keyword if country == "gb" else f"{keyword} remote"
    print(f"🔍 Adzuna API [{country}]: '{what}'...")
    for page in range(1, max_pages + 1):
        url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "what": what,
            "results_per_page": results_per_page,
            "content-type": "application/json",
        }
        try:
            r = requests.get(url, params=params, timeout=25)
        except Exception as e:
            print(f"  ⚠ Adzuna API {country} p{page} request error: {e}")
            break
        if r.status_code != 200:
            print(f"  ⚠ Adzuna API {country} p{page}: HTTP {r.status_code}")
            break
        try:
            results = r.json().get("results", [])
        except Exception as e:
            print(f"  ⚠ Adzuna API {country} p{page} JSON error: {e}")
            break
        if not results:
            break
        for it in results:
            desc = (it.get("description") or "").strip()
            # The API truncates description to 500 chars and ends it with "…";
            # there is no full-text field, only redirect_url. That length clears a
            # naive "is there a description" test while omitting exactly the part a
            # review rubric is checked against — the requirements — so the reviewer
            # would invent them. Flagged at the source so selection can keep these
            # out of review until enrich_truncated_descriptions.py fills them in.
            truncated = desc.endswith("…") or len(desc) >= 500
            jobs.append({
                "description_truncated": truncated,
                "title": (it.get("title") or "").strip(),
                "company": ((it.get("company") or {}).get("display_name") or "").strip(),
                "location": ((it.get("location") or {}).get("display_name") or "").strip(),
                "salary": _fmt_adzuna_salary(it.get("salary_min"), it.get("salary_max"), country),
                "snippet": desc[:500],
                "description": desc,
                "url": it.get("redirect_url", ""),
                "source": "adzuna",
                "type": "auto",
                "source_site": f"Adzuna {country.upper()}",
                "scraped_at": datetime.utcnow().isoformat() + "Z",
            })
        if len(results) < results_per_page:
            break
        time.sleep(0.5)  # stay under free-tier rate limit
    print(f"  ✓ Adzuna API [{country}]: {len(jobs)} jobs for '{keyword}'")
    return jobs


def _scrape_adzuna_api_all(config: dict, app_id: str, app_key: str) -> list[dict]:
    """API path: keyword × country matrix over config['adzuna_countries']."""
    keywords = config.get("keywords", [])
    countries = config.get("adzuna_countries", ["gb"])
    from selection import max_pages_for
    # The API path multiplies by country as well as keyword, so it keeps its own
    # cap of 3 on top of the per-site setting.
    max_pages = min(max_pages_for("adzuna", config), 3)
    seen = set()
    all_jobs = []
    for country in countries:
        for kw in keywords:
            for j in scrape_adzuna_api(kw, country, app_id, app_key, max_pages=max_pages):
                key = (j["title"], j.get("company", ""), j.get("location", ""))
                if key not in seen:
                    seen.add(key)
                    all_jobs.append(j)
            time.sleep(0.5)
    from scraper_indeed import filter_jobs_by_keywords
    all_jobs = filter_jobs_by_keywords(all_jobs, keywords)
    print(f"  ✓ Adzuna API total: {len(all_jobs)} unique jobs across {countries}")
    return all_jobs


async def scrape_adzuna_all(config: dict) -> list[dict]:
    """Run Adzuna scraper for all keyword+location combos in config.

    Uses the official multi-country API when ADZUNA_APP_ID / ADZUNA_APP_KEY are
    set; otherwise falls back to the UK-only Playwright scraper below.
    """
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if app_id and app_key:
        return _scrape_adzuna_api_all(config, app_id, app_key)
    print("  ℹ Adzuna API keys not set (ADZUNA_APP_ID/ADZUNA_APP_KEY) — "
          "falling back to UK-only Playwright scrape.")

    all_jobs = []
    seen = set()
    cache = load_description_cache()

    keywords = config.get("keywords", [])
    from selection import max_pages_for, search_pairs
    max_pages = max_pages_for("adzuna", config)

    async with async_playwright() as p:
        for kw, loc in search_pairs(config):
            jobs = await scrape_adzuna(kw, loc, max_pages=max_pages, config=config, cache=cache, playwright_instance=p)
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

    jobs = asyncio.run(scrape_adzuna_all(cfg))
    from scraper_indeed import save_jobs
    save_jobs(jobs)
    print(f"\n✅ Done! {len(jobs)} jobs scraped from Adzuna.")
