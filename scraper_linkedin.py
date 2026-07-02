"""
LinkedIn Job Scraper
====================
Scrapes job listings from LinkedIn using Playwright.
Requires a LinkedIn account (login handled interactively on first run,
then cookies are cached for reuse).
"""

import asyncio
import json
import os
import re
import time
from datetime import datetime
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from playwright_stealth import Stealth

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def sanitize_filename(text: str, max_len: int = 80) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', "", text).strip().replace(" ", "_")
    return safe[:max_len]


def load_config():
    """Load configuration from config.yaml."""
    import yaml
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_cookie_paths(config):
    """Get cookie file paths from config."""
    cookie_config = config.get("cookie_config", {})
    cookie_dir = cookie_config.get("cookie_dir", os.path.dirname(__file__))
    linkedin_file = cookie_config.get("linkedin_cookie_file", "linkedin_cookies.json")
    indeed_file = cookie_config.get("indeed_cookie_file", "indeed_cookies.json")
    return (
        os.path.join(cookie_dir, linkedin_file),
        os.path.join(cookie_dir, indeed_file),
    )


def is_cookie_valid(cookie_file: str, max_age_days: int = 30) -> bool:
    """Check if cookie file exists and is not expired."""
    if not os.path.exists(cookie_file):
        return False
    try:
        with open(cookie_file) as f:
            cookies = json.load(f)
        if not cookies:
            return False
        # Check age of cookie file
        file_age = time.time() - os.path.getmtime(cookie_file)
        max_age_seconds = max_age_days * 24 * 60 * 60
        return file_age < max_age_seconds
    except Exception:
        return False


async def _ensure_logged_in(page, config, linkedin_cookie_file: str, max_cookie_age_days: int) -> bool:
    """Check if logged into LinkedIn; if not, ask user to log in."""
    print("🔍 Checking LinkedIn login status...")
    await page.goto("https://www.linkedin.com/jobs/", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)

    # Check if already logged in (look for job search elements)
    content = await page.content()
    if "jobs-search-results" in content or "job-card" in content:
        print("  ✓ Already logged into LinkedIn.")
        return True

    # Try to load cached cookies first
    if is_cookie_valid(linkedin_cookie_file, max_cookie_age_days):
        print("  → Found valid cached cookies, restoring session...")
        with open(linkedin_cookie_file) as f:
            cookies = json.load(f)
        await page.context.add_cookies(cookies)
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Check again
        content = await page.content()
        if "jobs-search-results" in content or "job-card" in content:
            print("  ✓ Restored session from cached cookies.")
            return True
        else:
            print("  ⚠ Cached cookies expired or invalid.")

    # Interactive login — launch with UI
    headless = config.get("cookie_config", {}).get("headless", True)
    if headless:
        print("  ✗ Running in headless mode but no valid cookies. Run interactively first to log in.")
        print("     Set cookie_config.headless: false in config.yaml for interactive login.")
        return False

    print("🔑 LinkedIn login required.")
    print("   Please log in manually in the browser window (60s timeout)...")
    print("   (Cookies will be cached for next time)")

    await page.wait_for_timeout(60000)  # Wait 60s for manual login

    content = await page.content()
    if "jobs-search-results" not in content and "job-card" not in content:
        print("  ✗ Login not detected. Try running again.")
        return False

    # Cache cookies
    cookies = await page.context.cookies()
    with open(linkedin_cookie_file, "w") as f:
        json.dump(cookies, f)
    print("  ✓ LinkedIn session cached.")
    return True


async def scrape_linkedin(
    keyword: str,
    location: str = "",
    max_pages: int = 3,
    headless: bool = False,
    config: dict | None = None,
) -> list[dict]:
    """
    Search LinkedIn Jobs and return listings.

    NOTE: LinkedIn requires login. First run opens a visible browser
    for you to log in manually. After that, cookies are cached.

    Args:
        keyword: Job title / search term
        location: City or "Remote"
        max_pages: Number of pages to scrape (≈25 jobs per page)
        headless: NOT recommended for LinkedIn (login needed)
        config: Configuration dict (optional, loads from config.yaml if not provided)

    Returns:
        List of job dicts
    """
    if config is None:
        config = load_config()

    linkedin_cookie_file, _ = get_cookie_paths(config)
    max_cookie_age_days = config.get("cookie_config", {}).get("max_cookie_age_days", 30)

    jobs = []
    seen_urls = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
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
            geolocation={"latitude": 55.9533, "longitude": -3.1883},
            permissions=["geolocation"],
        )
        stealth = Stealth()
        await stealth.apply_stealth_async(context)
        page = await context.new_page()

        # Login check
        logged_in = await _ensure_logged_in(page, config, linkedin_cookie_file, max_cookie_age_days)
        if not logged_in:
            await browser.close()
            return jobs

        # Build search URL
        geo_map = {
            "edinburgh": "100542537",
            "glasgow": "102841198",
            "remote": "101165590",
        }
        geo_id = geo_map.get(location.strip().lower(), "")

        search_url = (
            f"https://www.linkedin.com/jobs/search/"
            f"?keywords={quote_plus(keyword)}"
        )
        if geo_id:
            search_url += f"&locationId={geo_id}"
        elif location:
            search_url += f"&location={quote_plus(location)}"

        print(f"🔍 LinkedIn: searching '{keyword}' in '{location}'...")
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        for page_num in range(1, max_pages + 1):
            try:
                await page.wait_for_selector(
                    "li.jobs-search-results__list-item, div.job-card-container",
                    timeout=10000,
                )
            except PwTimeout:
                print("  ⚠ No job cards found.")
                break

            # Scroll to load all results on page
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(500)

            # Get job cards
            cards = await page.query_selector_all(
                "li.jobs-search-results__list-item"
            )
            if not cards:
                cards = await page.query_selector_all("div.job-card-container")

            print(f"  Page {page_num}: {len(cards)} job cards")

            for card in cards:
                try:
                    job = await _extract_job_card(page, card)
                    if job and job["url"] not in seen_urls:
                        seen_urls.add(job["url"])
                        jobs.append(job)
                except Exception:
                    continue

            # Next page
            next_btn = await page.query_selector(
                'button[aria-label="Next"], '
                'button.jobs-search-pagination__button--next'
            )
            if next_btn:
                is_disabled = await next_btn.get_attribute("disabled")
                if is_disabled is not None:
                    print("  ✓ No more pages reachable.")
                    break
                try:
                    await next_btn.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await page.wait_for_timeout(2000)
                except Exception:
                    break
            else:
                print("  ✓ No more pages.")
                break

        await browser.close()

    print(f"  ✓ Total: {len(jobs)} unique jobs from LinkedIn")
    return jobs


async def _extract_job_card(page, card) -> dict | None:
    """Extract details from a LinkedIn job card."""
    try:
        # Click card to load details
        try:
            await card.click()
            await page.wait_for_timeout(1000)
        except Exception:
            pass

        # --- Title ---
        title_el = await card.query_selector(
            "a.job-card-list__title, "
            "a.job-card-container__link, "
            "strong.job-card-list__title"
        )
        title = await title_el.inner_text() if title_el else ""
        title = title.strip()

        # --- URL ---
        url = ""
        if title_el:
            url = await title_el.get_attribute("href") or ""

        # --- Company ---
        company_el = await card.query_selector(
            "a.job-card-container__company-name, "
            "span.job-card-container__company-name"
        )
        company = await company_el.inner_text() if company_el else ""
        company = company.strip()

        # --- Location ---
        loc_el = await card.query_selector(
            "span.job-card-container__metadata-item, "
            "li.job-card-container__metadata-item"
        )
        location_text = await loc_el.inner_text() if loc_el else ""
        location_text = location_text.strip()

        # --- Salary ---
        salary_el = await card.query_selector(
            "span.job-card-container__salary-info, "
            "li.job-card-container__salary-info"
        )
        salary_text = ""
        if salary_el:
            salary_text = (await salary_el.inner_text()).strip()

        # --- Try to get full description from detail panel ---
        full_desc = ""
        try:
            desc_el = await page.query_selector(
                "div.jobs-description-content__text, "
                "section.job-details-jobs-unified-description "
                "article"
            )
            if desc_el:
                full_desc = await desc_el.inner_text()
                full_desc = full_desc.strip()
        except Exception:
            pass

        if not title:
            return None

        return {
            "title": title,
            "company": company,
            "location": location_text,
            "salary": salary_text,
            "snippet": full_desc[:300] if full_desc else "",
            "description": full_desc,
            "url": url,
            "source": "linkedin",
            "source_site": "LinkedIn",
            "scraped_at": datetime.now().isoformat(),
        }

    except Exception as e:
        return None


async def scrape_linkedin_all(config: dict) -> list[dict]:
    """
    Run LinkedIn scraper for all keyword+location combos.
    LinkedIn login required (interactive on first run).
    """
    all_jobs = []
    seen = set()

    locations = config.get("locations", [""])
    keywords = config.get("keywords", [])
    max_pages = config.get("max_pages_per_search", 3)
    headless = config.get("cookie_config", {}).get("headless", True)

    for kw in keywords:
        for loc in locations:
            jobs = await scrape_linkedin(kw, loc, max_pages=max_pages, headless=headless, config=config)
            for j in jobs:
                dedup_key = (j["title"], j["company"], j["location"])
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    all_jobs.append(j)

    return all_jobs


# --- CLI ---
if __name__ == "__main__":
    import yaml

    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    jobs = asyncio.run(scrape_linkedin_all(cfg))
    from scraper_indeed import save_jobs
    save_jobs(jobs)
    print(f"\n✅ Done! {len(jobs)} jobs scraped from LinkedIn.")