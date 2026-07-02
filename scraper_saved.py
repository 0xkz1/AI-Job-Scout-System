#!/usr/bin/env python3
"""
Scrape saved/favorited jobs from Indeed and LinkedIn
====================================================
Usage: python3 scraper_saved.py [--max-jobs N] [--site indeed|linkedin|all]

Features:
- Cookie persistence for both Indeed and LinkedIn
- Reuses LinkedIn cookies from scraper_linkedin.py
- Fetches full job details for each saved job
- Supports headless mode for cron (requires pre-cached cookies)
- Config via config.yaml (cookie_config section)
"""

import argparse
import asyncio
import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urljoin

import yaml
from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from playwright_stealth import Stealth

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output", "00_saved")


def sanitize_filename(text: str, max_len: int = 80) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', "", text).strip().replace(" ", "_")
    return safe[:max_len]


def load_config():
    """Load configuration from config.yaml."""
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
        file_age = time.time() - os.path.getmtime(cookie_file)
        max_age_seconds = max_age_days * 24 * 60 * 60
        return file_age < max_age_seconds
    except Exception:
        return False


async def _stealth_context(context):
    """Apply anti-detection measures using playwright-stealth."""
    stealth = Stealth()
    await stealth.apply_stealth_async(context)


async def _create_browser_context(p, headless: bool = True):
    """Create browser context with stealth."""
    browser = await p.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
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
    await _stealth_context(context)
    return browser, context


async def _ensure_indeed_logged_in(page, indeed_cookie_file: str, max_cookie_age_days: int, headless: bool) -> bool:
    """Check if logged into Indeed; if not, try cookies or ask user to log in."""
    print("🔍 Checking Indeed login status...")
    await page.goto("https://uk.indeed.com/myjobs", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)

    # Check if already logged in (saved jobs page shows job cards)
    content = await page.content()
    if "data-jk" in content or "jobsearch-SavedJobsList" in content:
        print("  ✓ Already logged into Indeed.")
        return True

    # Try cached cookies
    if is_cookie_valid(indeed_cookie_file, max_cookie_age_days):
        print("  → Found valid cached Indeed cookies, restoring session...")
        with open(indeed_cookie_file) as f:
            cookies = json.load(f)
        await page.context.add_cookies(cookies)
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        content = await page.content()
        if "data-jk" in content or "jobsearch-SavedJobsList" in content:
            print("  ✓ Restored session from cached cookies.")
            return True
        else:
            print("  ⚠ Cached cookies expired or invalid.")

    # Headless mode without valid cookies
    if headless:
        print("  ✗ Running in headless mode but no valid cookies.")
        print("     Run with --headless=false locally to log in and cache cookies.")
        return False

    # Interactive login
    print("🔑 Indeed login required.")
    print("   Please log in manually in the browser window (60s timeout)...")
    print("   (Cookies will be cached for next time)")

    await page.wait_for_timeout(60000)  # Wait 60s for manual login

    content = await page.content()
    if "data-jk" not in content and "jobsearch-SavedJobsList" not in content:
        print("  ✗ Login not detected. Try running again.")
        return False

    # Cache cookies
    cookies = await page.context.cookies()
    with open(indeed_cookie_file, "w") as f:
        json.dump(cookies, f)
    print("  ✓ Indeed session cached.")
    return True


async def _ensure_linkedin_logged_in(page, linkedin_cookie_file: str, max_cookie_age_days: int, headless: bool) -> bool:
    """Check if logged into LinkedIn; if not, try cookies or ask user to log in."""
    print("🔍 Checking LinkedIn login status...")
    await page.goto("https://www.linkedin.com/my/items/saved-jobs/", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)

    # Check if already logged in
    content = await page.content()
    if "/jobs/view/" in content or "saved-jobs" in content:
        print("  ✓ Already logged into LinkedIn.")
        return True

    # Try cached cookies
    if is_cookie_valid(linkedin_cookie_file, max_cookie_age_days):
        print("  → Found valid cached LinkedIn cookies, restoring session...")
        with open(linkedin_cookie_file) as f:
            cookies = json.load(f)
        await page.context.add_cookies(cookies)
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        content = await page.content()
        if "/jobs/view/" in content or "saved-jobs" in content:
            print("  ✓ Restored session from cached cookies.")
            return True
        else:
            print("  ⚠ Cached cookies expired or invalid.")

    # Headless mode without valid cookies
    if headless:
        print("  ✗ Running in headless mode but no valid cookies.")
        print("     Run scraper_linkedin.py locally first to cache LinkedIn cookies.")
        return False

    # Interactive login
    print("🔑 LinkedIn login required.")
    print("   Please log in manually in the browser window (60s timeout)...")
    print("   (Cookies will be cached for next time)")

    await page.wait_for_timeout(60000)  # Wait 60s for manual login

    content = await page.content()
    if "/jobs/view/" not in content and "saved-jobs" not in content:
        print("  ✗ Login not detected. Try running again.")
        return False

    # Cache cookies
    cookies = await page.context.cookies()
    with open(linkedin_cookie_file, "w") as f:
        json.dump(cookies, f)
    print("  ✓ LinkedIn session cached.")
    return True


async def scrape_indeed_saved(page, max_jobs: int = 50):
    """Navigate to Indeed saved jobs page and extract full job details."""
    jobs = []

    # Go to saved jobs (requires login)
    await page.goto("https://uk.indeed.com/myjobs", wait_until="domcontentloaded", timeout=30000)

    # Check if logged in - look for saved job links
    try:
        await page.wait_for_selector("a[data-jk]", timeout=5000)
    except PwTimeout:
        print("  ✗ Not logged into Indeed (no saved jobs found).")
        return jobs

    # Extract saved job links
    cards = await page.query_selector_all("a[data-jk]")
    job_urls = []
    for card in cards[:max_jobs]:
        url = await card.get_attribute("href")
        if url:
            full_url = urljoin("https://uk.indeed.com", url)
            job_urls.append(full_url)

    print(f"  → Found {len(job_urls)} saved job URLs on Indeed")

    # Visit each job URL to get full details
    for i, url in enumerate(job_urls, 1):
        try:
            print(f"  [{i}/{len(job_urls)}] Fetching: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # Accept cookies if shown
            try:
                accept_btn = await page.query_selector("button:has-text('Accept All')")
                if accept_btn:
                    await accept_btn.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            # Extract job details
            job = await _extract_indeed_job(page, url)
            if job:
                jobs.append(job)
                print(f"    ✓ {job['title']} at {job['company']}")
            else:
                print(f"    ✗ Failed to extract job details")

        except Exception as e:
            print(f"    ✗ Error: {e}")
            continue

    return jobs


async def _extract_indeed_job(page, url: str):
    """Extract full job details from an Indeed job page."""
    try:
        # Title
        title_el = await page.query_selector("h1.jobsearch-JobInfoHeader-title")
        if not title_el:
            title_el = await page.query_selector("h1[data-testid='jobsearch-JobInfoHeader-title']")
        title = await title_el.inner_text() if title_el else ""
        title = title.strip()

        # Company
        company_el = await page.query_selector(
            'div[data-testid="inlineHeader-companyName"], '
            'span[data-testid="company-name"], '
            ".companyName"
        )
        company = await company_el.inner_text() if company_el else ""
        company = company.strip()

        # Location
        loc_el = await page.query_selector(
            'div[data-testid="inlineHeader-companyLocation"], '
            'div[data-testid="jobLocation"]'
        )
        location = await loc_el.inner_text() if loc_el else ""
        location = location.strip()

        # Salary
        salary_el = await page.query_selector(
            'div[data-testid="jobsearch-JobInfoHeader-salary"], '
            ".salary-snippet-container, "
            ".salaryOnly"
        )
        salary = await salary_el.inner_text() if salary_el else ""
        salary = salary.strip()

        # Description
        desc_el = await page.query_selector("#jobDescriptionText, .jobsearch-jobDescriptionText")
        description = await desc_el.inner_text() if desc_el else ""
        description = description.strip()

        if not title:
            return None

        return {
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "description": description,
            "snippet": description[:500] if description else "",
            "url": url,
            "source": "indeed",
            "source_site": "Indeed",
            "scraped_at": datetime.now().isoformat(),
        }

    except Exception as e:
        print(f"    Error extracting job: {e}")
        return None


async def scrape_linkedin_saved(page, max_jobs: int = 50):
    """Navigate to LinkedIn saved jobs page and extract full job details."""
    jobs = []

    # Go to saved jobs (requires login)
    await page.goto(
        "https://www.linkedin.com/my/items/saved-jobs/",
        wait_until="domcontentloaded",
        timeout=30000,
    )

    # Wait for manual login if needed
    try:
        await page.wait_for_selector("a[href*='/jobs/view/']", timeout=5000)
    except PwTimeout:
        print("  ✗ Not logged into LinkedIn (no saved jobs found).")
        return jobs

    # Extract saved job links
    cards = await page.query_selector_all("a[href*='/jobs/view/']")
    job_urls = []
    for card in cards[:max_jobs]:
        url = await card.get_attribute("href")
        if url:
            job_urls.append(url)

    print(f"  → Found {len(job_urls)} saved job URLs on LinkedIn")

    # Visit each job URL to get full details
    for i, url in enumerate(job_urls, 1):
        try:
            print(f"  [{i}/{len(job_urls)}] Fetching: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            job = await _extract_linkedin_job(page, url)
            if job:
                jobs.append(job)
                print(f"    ✓ {job['title']} at {job['company']}")
            else:
                print(f"    ✗ Failed to extract job details")

        except Exception as e:
            print(f"    ✗ Error: {e}")
            continue

    return jobs


async def _extract_linkedin_job(page, url: str):
    """Extract full job details from a LinkedIn job page."""
    try:
        # Title
        title_el = await page.query_selector("h1.top-card-layout__title, h1.t-24")
        title = await title_el.inner_text() if title_el else ""
        title = title.strip()

        # Company
        company_el = await page.query_selector(
            "a.topcard__org-name-link, "
            "a[data-tracking-control-name='public_jobs_topcard-org-name'], "
            ".topcard__org-name-link"
        )
        company = await company_el.inner_text() if company_el else ""
        company = company.strip()

        # Location
        loc_el = await page.query_selector(
            "span.topcard__flavor--bullet, "
            ".topcard__flavor--bullet"
        )
        location = await loc_el.inner_text() if loc_el else ""
        location = location.strip()

        # Salary (often not shown on LinkedIn)
        salary_el = await page.query_selector(
            "div.salary, "
            "[data-testid='salary']"
        )
        salary = await salary_el.inner_text() if salary_el else ""
        salary = salary.strip()

        # Description
        desc_el = await page.query_selector(
            "div.description__text, "
            "div.show-more-less-html__markup, "
            ".description__text"
        )
        description = await desc_el.inner_text() if desc_el else ""
        description = description.strip()

        if not title:
            return None

        return {
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "description": description,
            "snippet": description[:500] if description else "",
            "url": url,
            "source": "linkedin",
            "source_site": "LinkedIn",
            "scraped_at": datetime.now().isoformat(),
        }

    except Exception as e:
        print(f"    Error extracting LinkedIn job: {e}")
        return None


def save_jobs(jobs: list[dict], output_dir: str = OUTPUT_DIR):
    """Save jobs as individual job-description.md files + a JSON index."""
    os.makedirs(output_dir, exist_ok=True)
    index = []

    for job in jobs:
        folder_name = sanitize_filename(f"{job['company']}_{job['title']}")
        job_dir = os.path.join(output_dir, folder_name)
        os.makedirs(job_dir, exist_ok=True)

        md = _format_job_md(job)
        md_path = os.path.join(job_dir, "job-description.md")
        with open(md_path, "w") as f:
            f.write(md)

        index.append({
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "source": job["source"],
            "folder": folder_name,
            "url": job["url"],
        })

    index_path = os.path.join(output_dir, "_saved_index.json")
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    print(f"  💾 Saved {len(jobs)} jobs to {output_dir}/")
    return index


def _format_job_md(job: dict) -> str:
    return f"""# Job Description: {job['title']}

> **Source:** [{job['source_site']}]({job['url']})
> **Scraped:** {job['scraped_at']}

---

## Company

**{job['company']}**
Location: {job['location']}

---

## Salary

{job['salary'] if job['salary'] else 'Not specified'}

---

## Description

{job['description'] or job['snippet'] or 'No description available.'}

---

## Metadata

- **Search Source:** {job['source']}
- **URL:** {job['url']}
"""


async def main(headless: bool = True, max_jobs: int = 50, sites: list[str] = None):
    if sites is None:
        sites = ["indeed", "linkedin"]

    config = load_config()
    linkedin_cookie_file, indeed_cookie_file = get_cookie_paths(config)
    max_cookie_age_days = config.get("cookie_config", {}).get("max_cookie_age_days", 30)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    async with async_playwright() as p:
        browser, context = await _create_browser_context(p, headless)

        all_saved = []

        # Indeed
        if "indeed" in sites:
            print("🔍 Scraping Indeed saved jobs...")
            page = await context.new_page()
            logged_in = await _ensure_indeed_logged_in(page, indeed_cookie_file, max_cookie_age_days, headless)
            if logged_in:
                indeed_jobs = await scrape_indeed_saved(page, max_jobs)
                print(f"  → Extracted {len(indeed_jobs)} jobs from Indeed")
                all_saved.extend(indeed_jobs)
            else:
                print("  → Skipped Indeed (login required)")

        # LinkedIn
        if "linkedin" in sites:
            print("🔍 Scraping LinkedIn saved jobs...")
            page = await context.new_page()
            logged_in = await _ensure_linkedin_logged_in(page, linkedin_cookie_file, max_cookie_age_days, headless)
            if logged_in:
                linkedin_jobs = await scrape_linkedin_saved(page, max_jobs)
                print(f"  → Extracted {len(linkedin_jobs)} jobs from LinkedIn")
                all_saved.extend(linkedin_jobs)
            else:
                print("  → Skipped LinkedIn (login required)")

        await browser.close()

    # Save all jobs
    if all_saved:
        save_jobs(all_saved)
        print(f"\n✅ Saved {len(all_saved)} jobs to {OUTPUT_DIR}")
    else:
        print("\n⚠ No jobs scraped.")
        print("   For headless mode: run locally with --headless=false to log in and cache cookies.")
        print("   For LinkedIn: run scraper_linkedin.py locally first to cache cookies.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape saved/favorited jobs from Indeed and LinkedIn")
    parser.add_argument("--headless", action="store_true", default=True,
                        help="Run headless (default: True).")
    parser.add_argument("--no-headless", action="store_false", dest="headless",
                        help="Run with visible browser for manual login.")
    parser.add_argument("--max-jobs", type=int, default=50,
                        help="Maximum saved jobs to fetch per site (default: 50)")
    parser.add_argument("--site", choices=["indeed", "linkedin", "all"], default="all",
                        help="Which site to scrape (default: all)")

    args = parser.parse_args()

    sites = ["indeed", "linkedin"] if args.site == "all" else [args.site]

    asyncio.run(main(
        headless=args.headless,
        max_jobs=args.max_jobs,
        sites=sites
    ))