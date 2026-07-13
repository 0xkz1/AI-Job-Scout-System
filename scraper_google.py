"""
Google Jobs Scraper
====================
Scrapes job listings from Google Search (Jobs tab, udm=8) using Playwright.

Google is the most aggressive at bot detection. This scraper uses:
1. Playwright stealth (same as Indeed scraper)
2. Cookie persistence for bypass sessions
3. Non-headless fallback for CAPTCHA
4. JSON-LD structured data parsing + DOM fallback

Usage (standalone):
    python scraper_google.py
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from playwright_stealth import Stealth

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "10_output")


def sanitize_filename(text: str, max_len: int = 80) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', "", text).strip().replace(" ", "_")
    return safe[:max_len]


async def _stealth_context(context):
    """Apply anti-detection measures using playwright-stealth."""
    stealth = Stealth()
    await stealth.apply_stealth_async(context)


async def _extract_json_ld(page) -> list[dict]:
    """Extract structured job data from JSON-LD in the page."""
    try:
        ld_data = await page.evaluate("""() => {
            const scripts = document.querySelectorAll('script[type="application/ld+json"]');
            const results = [];
            for (const script of scripts) {
                try {
                    const data = JSON.parse(script.textContent);
                    if (data && data['@type'] === 'ItemList' && data.itemListElement) {
                        results.push(...data.itemListElement.map(item =>
                            item.item || item
                        ));
                    } else if (data && data['@type'] === 'JobPosting') {
                        results.push(data);
                    }
                } catch(e) {}
            }
            return results;
        }""")
        return ld_data if ld_data else []
    except Exception:
        return []


async def _extract_google_jobs_from_dom(page) -> list[dict]:
    """
    Extract job listings from Google Jobs DOM.
    Uses multiple selector strategies (class names change frequently).
    """
    try:
        jobs = await page.evaluate("""() => {
            const results = [];

            // Strategy 1: Look for job card containers (Google Jobs often uses these)
            const cardSelectors = [
                'div[jsname] div[role="listitem"]',
                'div[data-hveid] g-scrolling-carousel',
                'div[class*="job"]',
                'div.g table',
                'div[data-job-card]',
                'div[jscontroller] div[role="listitem"]',
                'div.MQUd2b',  // common Google Jobs card class
            ];

            let cards = [];
            for (const sel of cardSelectors) {
                const found = document.querySelectorAll(sel);
                if (found.length > 0) {
                    cards = found;
                    break;
                }
            }

            // Fallback: find all divs containing links to /jobs/
            if (cards.length === 0) {
                const allLinks = document.querySelectorAll('a[href*="/jobs/"]');
                const parentCandidates = new Set();
                allLinks.forEach(link => {
                    let parent = link.closest('div[role="listitem"], div.g, div[class*="card"], div[class*="result"]');
                    if (parent) parentCandidates.add(parent);
                });
                cards = Array.from(parentCandidates);
            }

            cards.forEach(card => {
                const titleEl = card.querySelector('h3, a[href*="/jobs/"], [class*="title"], [class*="heading"]');
                const title = titleEl ? (titleEl.textContent || titleEl.getAttribute('aria-label') || '').trim() : '';

                // Company
                const companyEl = card.querySelector('[class*="company"], [class*="employer"], [class*="org"]');
                const companyText = companyEl ? companyEl.textContent.trim() : '';

                // Location
                const locEl = card.querySelector('[class*="location"], [class*="place"], [aria-label*="location"]');
                const location = locEl ? locEl.textContent.trim() : '';

                // Salary
                const salaryEl = card.querySelector('[class*="salary"], [class*="price"], [aria-label*="salary"]');
                const salary = salaryEl ? salaryEl.textContent.trim() : '';

                // Description snippet
                const snippetEl = card.querySelector('[class*="desc"], [class*="snippet"], [class*="summary"]');
                const snippet = snippetEl ? snippetEl.textContent.trim() : '';

                // URL
                const linkEl = card.querySelector('a[href*="/jobs/"], a[href*="http"]');
                let url = linkEl ? (linkEl.href || linkEl.getAttribute('href') || '') : '';
                if (url && !url.startsWith('http')) {
                    url = 'https://www.google.com' + url;
                }

                if (title) {
                    results.push({
                        title: title,
                        company: companyText,
                        location: location,
                        salary: salary,
                        snippet: snippet.slice(0, 500),
                        description: '',
                        url: url,
                        source: 'google',
                        type: 'auto',
                        source_site: 'Google Jobs',
                        scraped_at: new Date().toISOString(),
                    });
                }
            });

            return results;
        }""")
        return jobs if jobs else []
    except Exception:
        return []


def _parse_json_ld_jobs(ld_items: list[dict]) -> list[dict]:
    """Convert JSON-LD items to our standard job format."""
    jobs = []
    for item in ld_items:
        try:
            title = item.get("title", "") or item.get("name", "")
            if not title:
                continue

            company = ""
            hiring_org = item.get("hiringOrganization", {})
            if hiring_org:
                company = hiring_org.get("name", "") or hiring_org.get("legalName", "")

            location = ""
            job_loc = item.get("jobLocation", {})
            if job_loc:
                addr = job_loc.get("address", {})
                if isinstance(addr, dict):
                    location = ", ".join(filter(None, [
                        addr.get("addressLocality", ""),
                        addr.get("addressRegion", ""),
                        addr.get("addressCountry", ""),
                    ]))
                elif isinstance(addr, str):
                    location = addr

            salary_text = ""
            base_salary = item.get("baseSalary", {})
            if base_salary:
                value_spec = base_salary.get("value", {})
                if isinstance(value_spec, dict):
                    min_val = value_spec.get("minValue", "")
                    max_val = value_spec.get("maxValue", "")
                    currency = base_salary.get("currency", "")
                    if min_val and max_val:
                        salary_text = f"£{min_val} - £{max_val} per {value_spec.get('unitText', 'year')}"
                    elif min_val:
                        salary_text = f"From £{min_val} per {value_spec.get('unitText', 'year')}"
                    if currency:
                        salary_text = salary_text.replace("£", currency)

            desc = item.get("description", "") or item.get("descriptionText", "")

            url = item.get("url", "") or item.get("directApply", "") or ""

            jobs.append({
                "title": title.strip(),
                "company": company.strip(),
                "location": location.strip(),
                "salary": salary_text,
                "snippet": desc[:500] if desc else "",
                "description": desc if desc else "",
                "url": url,
                "source": "google",
                "type": "auto",
                "source_site": "Google Jobs",
                "scraped_at": datetime.now().isoformat(),
            })
        except Exception:
            continue

    return jobs


async def _handle_google_sorry(page) -> bool:
    """
    Check if we hit Google's 'Sorry' / CAPTCHA page.
    Returns True if we're past it (normal page), False if still blocked.
    """
    try:
        title = await page.title()
        content = await page.content()

        # Check for CAPTCHA/sorry indicators
        sorry_indicators = [
            "sorry" in title.lower(),
            "captcha" in title.lower(),
            "just a moment" in title.lower(),
            "unusual traffic" in content.lower(),
            "automated queries" in content.lower(),
            "captcha" in content.lower(),
            "g-recaptcha" in content,
            "cf-browser-verification" in content,
        ]

        if any(sorry_indicators):
            return False
        return True
    except Exception:
        return False


async def scrape_google(
    keyword: str,
    location: str = "",
    max_pages: int = 3,
    config: dict | None = None,
) -> list[dict]:
    """
    Search Google Jobs and return job listings.

    Args:
        keyword: Job title / search term
        location: City or "Remote"
        max_pages: Number of result pages to scrape
        config: Configuration dict (for cookie paths, etc.)

    Returns:
        List of job dicts
    """
    jobs = []
    seen_urls = set()

    # Build Google Jobs search URL (udm=8 = Jobs tab)
    query_parts = [keyword]
    if location:
        query_parts.append(location)
    query = " ".join(query_parts)
    search_url = f"https://www.google.com/search?q={quote_plus(query)}&udm=8"

    # --- Cookie Configuration ---
    cookie_dir = None
    cookie_path = None
    if config and "cookie_config" in config:
        cc = config["cookie_config"]
        cookie_dir = cc.get("cookie_dir", "")
        if cookie_dir:
            import os as _os
            _os.makedirs(cookie_dir, exist_ok=True)
            cookie_path = _os.path.join(cookie_dir, "google_cookies.json")

    async with async_playwright() as p:
        # Step 1: Launch browser
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ]

        # Determine headless state
        is_headless = config.get("cookie_config", {}).get("headless", True) if config else True
        force_bypass = False

        # Check if we can actually run non-headless (has display server)
        has_display = bool(os.environ.get("DISPLAY"))
        if cookie_path and not os.path.exists(cookie_path) and has_display:
            print("  🔑 No Google cookies found. Launching non-headless for CAPTCHA bypass...")
            is_headless = False
            force_bypass = True
        elif cookie_path and not os.path.exists(cookie_path):
            print("  🔑 No Google cookies found. Starting headless (no display server) — may trigger CAPTCHA.")

        browser = await p.chromium.launch(
            headless=is_headless,
            args=launch_args,
        )

        context_args = {
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1920, "height": 1080},
            "locale": "en-GB",
            "timezone_id": "Europe/London",
            "geolocation": {"latitude": 55.9533, "longitude": -3.1883},
            "permissions": ["geolocation"],
        }

        if cookie_path and os.path.exists(cookie_path):
            context_args["storage_state"] = cookie_path
            print(f"  🔑 Loaded Google cookies from {cookie_path}")

        context = await browser.new_context(**context_args)
        await _stealth_context(context)
        page = await context.new_page()

        print(f"🔍 Google Jobs: searching '{query}'...")
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # Step 2: Check for CAPTCHA / Sorry page
        if not await _handle_google_sorry(page):
            print("  ⚠️ Google CAPTCHA / 'Sorry' page detected!")

            if is_headless:
                print("  🔄 Relaunching in non-headless mode for manual bypass...")
                await browser.close()
                browser = await p.chromium.launch(headless=False, args=launch_args)
                context = await browser.new_context(**context_args)
                await _stealth_context(context)
                page = await context.new_page()

                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)
                force_bypass = True

            if force_bypass or not is_headless:
                print("\n" + "=" * 80)
                print("  🚨 ACTION REQUIRED: Google CAPTCHA detected!")
                print("  Please solve the CAPTCHA in the browser window.")
                print("  Once you see search results, press ENTER in the terminal...")
                print("=" * 80 + "\n")

                # Wait for CAPTCHA bypass (check every 2s, up to 60s)
                for _ in range(30):
                    await page.wait_for_timeout(2000)
                    if await _handle_google_sorry(page):
                        print("  ✅ CAPTCHA bypassed!")
                        break
                else:
                    print("  ⚠️ Timeout waiting for CAPTCHA bypass. Continuing anyway...")

                # Save cookies after bypass
                if cookie_path:
                    await context.storage_state(path=cookie_path)
                    print(f"  💾 Saved Google cookies to {cookie_path}")

        # Step 3: Check final state
        if not await _handle_google_sorry(page):
            print("  ❌ Still blocked by Google CAPTCHA after bypass attempt.")
            await browser.close()
            return jobs

        # Step 4: Wait for results to render
        await page.wait_for_timeout(3000)

        # Step 5: Extract jobs (try JSON-LD first, then DOM)
        print("  📋 Extracting job listings...")

        # JSON-LD structured data (most reliable when available)
        ld_items = await _extract_json_ld(page)
        if ld_items:
            ld_jobs = _parse_json_ld_jobs(ld_items)
            print(f"  → Found {len(ld_jobs)} jobs via JSON-LD")
            for j in ld_jobs:
                if j["url"] and j["url"] not in seen_urls:
                    seen_urls.add(j["url"])
                    jobs.append(j)
                elif not j["url"]:
                    jobs.append(j)  # allow jobs without URLs too

        # DOM extraction (fallback / supplement)
        if len(jobs) < 5:
            dom_jobs = await _extract_google_jobs_from_dom(page)
            print(f"  → Found {len(dom_jobs)} jobs via DOM")
            for j in dom_jobs:
                dedup_key = (j["title"], j["company"], j.get("location", ""))
                # Check if already added by URL or similar title+company
                already_have = any(
                    existing["title"] == j["title"]
                    and existing.get("company") == j.get("company")
                    for existing in jobs
                )
                if not already_have and j["url"] not in seen_urls:
                    if j["url"]:
                        seen_urls.add(j["url"])
                    jobs.append(j)

        # Step 6: Scroll to load more results
        if max_pages > 1:
            print(f"  📜 Scrolling to load more results...")
            for page_num in range(1, max_pages):
                # Scroll down to trigger lazy loading
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

                # Try to click "More jobs" / "Show more" button if present
                try:
                    more_btn = await page.query_selector(
                        'button:has-text("More"), '
                        'button:has-text("Show more"), '
                        '[aria-label*="more"], '
                        '[role="button"]:has-text("More jobs")'
                    )
                    if more_btn:
                        await more_btn.click()
                        await page.wait_for_timeout(2000)
                        print(f"    → Clicked 'Show more' (page {page_num + 1})")
                except Exception:
                    pass

                # Extract any newly loaded jobs
                new_ld = await _extract_json_ld(page)
                if new_ld:
                    new_jobs = _parse_json_ld_jobs(new_ld)
                    for j in new_jobs:
                        if j["url"] and j["url"] not in seen_urls:
                            seen_urls.add(j["url"])
                            jobs.append(j)
                        elif not j["url"]:
                            dedup_key = (j["title"], j["company"])
                            if not any(
                                e["title"] == j["title"]
                                and e.get("company") == j.get("company")
                                for e in jobs
                            ):
                                jobs.append(j)
                    print(f"    → Total jobs: {len(jobs)}")

                # Check if we've hit the bottom
                scroll_pos = await page.evaluate("window.scrollY + window.innerHeight")
                scroll_max = await page.evaluate("document.body.scrollHeight")
                if scroll_pos >= scroll_max - 100:
                    print("  ✓ Reached bottom of page.")
                    break

        await browser.close()

    print(f"  ✓ Total: {len(jobs)} unique jobs from Google Jobs")
    return jobs


async def scrape_google_all(config: dict) -> list[dict]:
    """Run Google scraper for all keyword+location combos in config."""
    all_jobs = []
    seen = set()

    locations = config.get("locations", [""])
    keywords = config.get("keywords", [])
    max_pages = config.get("max_pages_per_search", 3)

    for kw in keywords:
        for loc in locations:
            jobs = await scrape_google(kw, loc, max_pages=max_pages, config=config)
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

    jobs = asyncio.run(scrape_google_all(cfg))
    # Save using same format as other scrapers
    from scraper_indeed import save_jobs
    save_jobs(jobs)
    print(f"\n✅ Done! {len(jobs)} jobs scraped from Google Jobs.")
