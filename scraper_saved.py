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
import sys
import re
import time
from datetime import datetime
from urllib.parse import urljoin

import yaml
from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from playwright_stealth import Stealth

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "00_saved")


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
    # Resolve relative cookie_dir relative to this file
    if not os.path.isabs(cookie_dir):
        cookie_dir = os.path.join(os.path.dirname(__file__), cookie_dir)
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


async def _create_browser_context(p, headless, linkedin_state_file: str = None):
    """Create browser and context, optionally loading LinkedIn storage state."""
    context_kwargs = dict(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1920, "height": 1080},
        locale="en-GB",
        timezone_id="Europe/London",
    )

    browser = await p.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )

    # Load LinkedIn session via storage_state for reliability
    # storage_state preserves the full browser session, not just cookies
    if linkedin_state_file and os.path.exists(linkedin_state_file):
        try:
            context = await browser.new_context(
                **context_kwargs,
                storage_state=linkedin_state_file,
            )
            print(f"  → Loaded LinkedIn session (native format) from {linkedin_state_file}")
        except Exception as e:
            print(f"  ⚠ storage_state failed, using add_cookies fallback: {e}")
            context = await browser.new_context(**context_kwargs)
            with open(linkedin_state_file) as f:
                state_data = json.load(f)
            cookies = state_data.get("cookies", [])
            if cookies:
                await context.add_cookies(cookies)
                print(f"  → Fallback: loaded {len(cookies)} cookies directly")
    else:
        context = await browser.new_context(**context_kwargs)

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
        try:
            with open(indeed_cookie_file) as f:
                cookies = json.load(f)
            if not isinstance(cookies, list):
                print(f"  ⚠ Indeed cookie file format invalid (expected array, got {type(cookies).__name__}). Skipping Indeed.")
                return False
            await page.context.add_cookies(cookies)
            await page.reload(wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            content = await page.content()
            if "data-jk" in content or "jobsearch-SavedJobsList" in content:
                print("  ✓ Restored session from cached cookies.")
                return True
            else:
                print("  ⚠ Cached cookies expired or invalid.")
        except Exception as e:
            print(f"  ⚠ Failed to restore Indeed cookies: {e}. Skipping Indeed.")
            return False

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


def parse_linkedin_tracker_html(html_path: str) -> list:
    """Parse LinkedIn Jobs Tracker HTML file (saved from browser) and extract job cards.

    LinkedIn uses minified CSS class names, so we rely on <p> tag structure:
      <p> = Job title
      <p> = Company · Location
      <p> = Posted time
    """
    import re
    from datetime import datetime

    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    job_link_pattern = r'<a[^>]*href="(https://www\.linkedin\.com/jobs/view/[^"]*)"[^>]*>(.*?)</a>'
    matches = re.findall(job_link_pattern, html, re.DOTALL)

    jobs = []
    seen_ids = set()
    for url, inner in matches:
        text = re.sub(r'<[^>]+>', ' ', inner).strip()
        text = re.sub(r'\s+', ' ', text)
        if text in ('応募', 'Easy応募', 'Apply', 'Easy Apply'):
            continue

        jid = re.search(r'/jobs/view/(?:[^/]*/)?(\d+)', url)
        if not jid:
            continue
        job_id = jid.group(1)
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        # Extract <p> elements (title, company·location, posted time)
        p_elements = re.findall(r'<p[^>]*>(.*?)</p>', inner, re.DOTALL)
        if len(p_elements) >= 3:
            title = re.sub(r'<[^>]+>', '', p_elements[0]).strip()
            company_loc = re.sub(r'<[^>]+>', '', p_elements[1]).strip()
            posted = re.sub(r'<[^>]+>', '', p_elements[2]).strip()
            cl_parts = company_loc.split('·')
            company = cl_parts[0].strip()
            location = '·'.join(cl_parts[1:]).strip()
        else:
            title = text
            company = ''
            location = ''
            posted = ''

        jobs.append({
            'job_id': job_id,
            'title': title,
            'company': company,
            'location': location,
            'posted': posted,
            'url': f'https://www.linkedin.com/jobs/view/{job_id}/',
            'source': 'linkedin_tracker',
            'scraped_at': datetime.now().isoformat(),
        })

    return jobs


def save_saved_jobs_to_output(jobs: list, output_dir: str = 'output/00_saved'):
    """Save job list to JSON + CSV in the output directory."""
    import json, csv, os
    os.makedirs(output_dir, exist_ok=True)

    json_path = os.path.join(output_dir, 'saved_linkedin_jobs.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    csv_path = os.path.join(output_dir, 'saved_linkedin_jobs.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['job_id', 'title', 'company', 'location', 'posted', 'url', 'source'])
        writer.writeheader()
        for job in jobs:
            writer.writerow({k: v for k, v in job.items() if k in ['job_id', 'title', 'company', 'location', 'posted', 'url', 'source']})

    return json_path, csv_path


async def _auto_login(page, config) -> bool:
    """Auto-login to LinkedIn using credentials from .env."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    email = os.environ.get("LINKEDIN_EMAIL", "")
    password = os.environ.get("LINKEDIN_PASSWORD", "")
    if not email or not password:
        print("  ✗ No LinkedIn credentials in .env")
        return False

    print("🔑 Auto-logging in to LinkedIn...")
    try:
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)  # Wait longer for JS to render form in headless

        # Try page.fill first (works in non-headless)
        try:
            await page.wait_for_selector('input[name="session_key"]:visible', timeout=5000)
            await page.fill('input[name="session_key"]', email)
        except Exception:
            # Fallback: use evaluate to set values directly (works in headless when form is hidden)
            print("  → Form not visible, trying JS injection...")
            await page.evaluate(f'''
                const emailInput = document.querySelector('input[name="session_key"]');
                const passInput = document.querySelector('input[name="session_password"]');
                if (emailInput) {{
                    emailInput.value = "{email}";
                    emailInput.dispatchEvent(new Event('input', {{bubbles: true}}));
                }}
                if (passInput) {{
                    passInput.value = "{password}";
                    passInput.dispatchEvent(new Event('input', {{bubbles: true}}));
                }}
            ''')
            await page.wait_for_timeout(500)

        # Try page.fill for password too
        try:
            await page.fill('input[name="session_password"]', password)
        except Exception:
            pass  # Already set via JS above

        await page.wait_for_timeout(300)

        # Try clicking submit button, fallback to JS click
        try:
            await page.click('button[type="submit"]', timeout=5000)
        except Exception:
            print("  → Submit button not clickable, trying JS click...")
            await page.evaluate('''
                const btn = document.querySelector('button[type="submit"]') ||
                           document.querySelector('.btn__primary--large') ||
                           document.querySelector('[data-id="sign-in-form__submit-btn"]');
                if (btn) btn.click();
            ''')

        await page.wait_for_timeout(5000)

        # Check if logged in (redirected to feed or jobs)
        content = await page.content()
        if "feed" in page.url or "jobs" in page.url or "mynetwork" in page.url:
            print("  ✓ LinkedIn auto-login successful")
            return True

        # Check for CAPTCHA or verification
        if "captcha" in content.lower() or "verify" in content.lower() or "challenge" in content.lower():
            print("  ⚠ CAPTCHA/verification detected — manual intervention needed")
            return False

        print("  ✗ Login may have failed (no redirect to feed/jobs)")
        return False

    except Exception as e:
        print(f"  ✗ Auto-login error: {e}")
        return False


async def _ensure_linkedin_logged_in(page, linkedin_cookie_file: str, max_cookie_age_days: int, headless: bool) -> bool:
    """Check if logged into LinkedIn using storage_state, auto-login if expired.

    1. Try storage_state on a public job search page (same as scraper_linkedin.py)
    2. If session invalid, try _auto_login using .env credentials
    3. After successful login, save new storage_state for next run
    4. Then navigate to /my-items/saved-jobs/ with valid session
    """
    print("🔍 Checking LinkedIn login status...")
    state_file = linkedin_cookie_file.replace(".json", ".state")
    state_exists = os.path.exists(state_file)

    # Step 1: Check login on a public job search page first
    await page.goto(
        "https://www.linkedin.com/jobs/search/?keywords=software&location=UK",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await page.wait_for_timeout(3000)

    content = await page.content()
    has_results = "jobs-search-results" in content or "job-card" in content or "/jobs/view" in content

    if has_results:
        print("  ✓ Already logged into LinkedIn (session valid).")
        # Save state in Playwright's native format for future runs
        try:
            state = await page.context.storage_state()
            with open(state_file, "w") as f:
                json.dump(state, f)
        except Exception:
            pass
        return True

    # Step 2: Session expired — try auto-login
    print("  ⚠ LinkedIn session not valid. Attempting auto-login...")
    config = load_config()
    if await _auto_login(page, config):
        # Save new storage state for next run
        state = await page.context.storage_state()
        with open(state_file, "w") as f:
            json.dump(state, f)
        print(f"  ✓ LinkedIn session cached after auto-login: {state_file}")
        return True

    # Step 3: Auto-login failed (CAPTCHA, wrong creds, etc.)
    if headless:
        print("  ✗ Auto-login failed in headless mode. Try running with --no-headless.")
    else:
        print("  ✗ Auto-login failed. CAPTCHA may be required.")
    return False


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
            "type": "manual",
            "source_site": "Indeed",
            "scraped_at": datetime.now().isoformat(),
        }

    except Exception as e:
        print(f"    Error extracting job: {e}")
        return None


async def _debug_dump_page(page, label: str):
    """Save page HTML and screenshot for debugging selector issues."""
    debug_dir = os.path.join(os.path.dirname(__file__), "10_output", "_debug")
    os.makedirs(debug_dir, exist_ok=True)
    try:
        content = await page.content()
        html_path = os.path.join(debug_dir, f"{label}.html")
        with open(html_path, "w") as f:
            f.write(content)
        url = page.url
        print(f"  📸 Debug dump: {html_path} (URL: {url}, {len(content)} chars)")
        # Also try screenshot
        ss_path = os.path.join(debug_dir, f"{label}.png")
        await page.screenshot(path=ss_path, full_page=False)
        print(f"  📸 Screenshot: {ss_path}")
    except Exception as e:
        print(f"  ⚠ Debug dump failed: {e}")


async def scrape_linkedin_saved(page, max_jobs: int = 50, linkedin_cookie_file: str = None):
    """Navigate to LinkedIn saved jobs page and extract full job details."""
    jobs = []

    # Go to saved jobs (requires login)
    await page.goto(
        "https://www.linkedin.com/my-items/saved-jobs/",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await page.wait_for_timeout(5000)  # Give SPA time to render

    # Check if we got redirected to login page (session not valid for private pages)
    current_url = page.url
    if "login" in current_url.lower() or "authwall" in current_url.lower() or "uas/login" in current_url.lower():
        print("  ⚠ Saved jobs page redirected to login. Trying auto-login...")
        config = load_config()
        if await _auto_login(page, config):
            # Save new storage state
            if linkedin_cookie_file:
                state_file = linkedin_cookie_file.replace(".json", ".state")
                state = await page.context.storage_state()
                with open(state_file, "w") as f:
                    json.dump(state, f)
                print(f"  ✓ Session refreshed: {state_file}")
            # Retry saved jobs page
            await page.goto(
                "https://www.linkedin.com/my-items/saved-jobs/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await page.wait_for_timeout(5000)
            current_url = page.url
            if "login" in current_url.lower() or "uas/login" in current_url.lower():
                print("  ✗ Still redirected after auto-login. Saved jobs may require manual login.")
                return jobs
            print("  ✓ Successfully accessed saved jobs after auto-login.")
        else:
            print("  ✗ Auto-login failed. Cannot access saved jobs.")
            return jobs

    # Check if we landed on guest homepage (not authenticated)
    # LinkedIn may redirect to root instead of login page
    content = await page.content()
    if "guest-home" in content or "guest-upsells" in content:
        print("  ⚠ Landed on guest homepage (session not recognized for private page).")
        print("  → Trying to establish session via /jobs/ first...")
        await page.goto(
            "https://www.linkedin.com/jobs/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)
        # Now retry saved jobs
        await page.goto(
            "https://www.linkedin.com/my-items/saved-jobs/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(5000)
        current_url = page.url
        content = await page.content()
        if "guest-home" in content or "guest-upsells" in content or "login" in current_url.lower():
            print("  ✗ Still guest after /jobs/ redirect. Checking actual saved jobs URL...")
            # Try alternative saved jobs URL pattern
            alt_urls = [
                "https://www.linkedin.com/jobs/saved/",
                "https://www.linkedin.com/jobs/collections/",
            ]
            for alt_url in alt_urls:
                print(f"  → Trying: {alt_url}")
                await page.goto(alt_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)
                alt_content = await page.content()
                if "guest-home" not in alt_content and "guest-upsells" not in alt_content:
                    print(f"  ✓ Found working URL: {alt_url}")
                    break
            else:
                print("  ✗ None of the saved jobs URLs worked. Session may need refresh.")
                return jobs

    # Debug: dump page content for selector analysis
    await _debug_dump_page(page, "saved_jobs")

    # Wait for job cards — try multiple selectors
    card_selectors = [
        "a[href*='/jobs/view/']",
        "div.jobs-saved-jobs-list__list-item a",
        "div[data-test-id='saved-jobs-list'] a",
        "a.jobs-postings__top-upskill-button",  # LinkedIn sometimes uses data attributes
        "div.jobs-saved-job-card a",
    ]

    found = False
    for selector in card_selectors:
        try:
            await page.wait_for_selector(selector, timeout=5000)
            found = True
            break
        except PwTimeout:
            continue

    if not found:
        # Maybe logged in but page structure changed — try scrolling
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(3000)
        for selector in card_selectors:
            try:
                await page.wait_for_selector(selector, timeout=3000)
                found = True
                break
            except PwTimeout:
                continue

    if not found:
        print("  ✗ No saved jobs found (page may have changed structure).")
        return jobs

    # Extract saved job links — use the selector that worked
    cards: list = []
    for selector in card_selectors:
        cards = await page.query_selector_all(selector)
        if cards:
            break

    job_urls = []
    for card in cards[:max_jobs]:
        url = await card.get_attribute("href")
        if url:
            if not url.startswith("http"):
                url = urljoin("https://www.linkedin.com", url)
            if url not in job_urls:
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
            "type": "manual",
            "source_site": "LinkedIn",
            "scraped_at": datetime.now().isoformat(),
        }

    except Exception as e:
        print(f"    Error extracting LinkedIn job: {e}")
        return None


async def scrape_linkedin_tracker(page, max_jobs: int = 50):
    """
    Navigate to LinkedIn Jobs Tracker page and extract job details.
    The Jobs Tracker (linkedin.com/jobs-tracker/) aggregates applied/saved jobs
    in a card layout. We extract job links and visit each for full details.
    """
    jobs = []

    # Go to jobs tracker page
    await page.goto(
        "https://www.linkedin.com/jobs-tracker/",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await page.wait_for_timeout(5000)  # Give SPA time to render

    # Check if we got redirected to login, 404, or guest homepage
    current_url = page.url
    if "login" in current_url.lower() or "authwall" in current_url.lower() or "uas/login" in current_url.lower():
        print("  ⚠ Jobs Tracker page redirected to login. URL may be incorrect or session expired.")
        return jobs
    content = await page.content()
    if "not-found-404" in content or "page-not-found" in content.lower():
        print("  ⚠ Jobs Tracker page returned 404. This URL may not be available.")
        return jobs
    if "guest-home" in content or "guest-upsells" in content:
        print("  ⚠ Jobs Tracker: guest homepage detected (session not recognized).")
        return jobs

    # Debug: dump page content for selector analysis
    await _debug_dump_page(page, "jobs_tracker")

    # Wait for job cards to load — try multiple selector patterns
    card_selectors = [
        "a[href*='/jobs/view/']",
        "div.jobs-saved-jobs-list__list-item a",
        "div.job-card-list__title a",
        "a[data-control-name='saved_jhip_card']",
    ]

    job_urls: list[str] = []
    for selector in card_selectors:
        try:
            await page.wait_for_selector(selector, timeout=5000)
            cards = await page.query_selector_all(selector)
            for card in cards[:max_jobs]:
                href = await card.get_attribute("href")
                if href and "/jobs/view/" in href:
                    if not href.startswith("http"):
                        href = urljoin("https://www.linkedin.com", href)
                    if href not in job_urls:
                        job_urls.append(href)
            break
        except PwTimeout:
            continue

    print(f"  → Found {len(job_urls)} job URLs on LinkedIn Jobs Tracker")

    if not job_urls:
        # Fallback: try scrolling to load dynamic content
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(3000)
        for selector in card_selectors:
            try:
                cards = await page.query_selector_all(selector)
                for card in cards[:max_jobs]:
                    href = await card.get_attribute("href")
                    if href and "/jobs/view/" in href:
                        if not href.startswith("http"):
                            href = urljoin("https://www.linkedin.com", href)
                        if href not in job_urls:
                            job_urls.append(href)
                if job_urls:
                    break
            except Exception:
                continue
        print(f"  → After scroll: found {len(job_urls)} job URLs")

    # Visit each job URL to get full details
    for i, url in enumerate(job_urls, 1):
        try:
            print(f"  [{i}/{len(job_urls)}] Fetching: {url[:80]}...")
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

    # Prefer storage_state file over cookies JSON (more reliable for LinkedIn)
    linkedin_state_file = linkedin_cookie_file.replace(".json", ".state")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    async with async_playwright() as p:
        browser, context = await _create_browser_context(p, headless, linkedin_state_file)

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

        # LinkedIn saved jobs
        if "linkedin" in sites:
            print("🔍 Scraping LinkedIn saved jobs...")
            page = await context.new_page()
            logged_in = await _ensure_linkedin_logged_in(page, linkedin_cookie_file, max_cookie_age_days, headless)
            if logged_in:
                linkedin_jobs = await scrape_linkedin_saved(page, max_jobs, linkedin_cookie_file)
                print(f"  → Extracted {len(linkedin_jobs)} saved jobs from LinkedIn")
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
    parser.add_argument("--html", type=str, default=None,
                        help="Parse LinkedIn Jobs Tracker from saved HTML file (skip browser automation)")

    args = parser.parse_args()

    # HTML mode: parse saved HTML file directly
    if args.html:
        print(f"📄 Parsing LinkedIn Jobs Tracker HTML: {args.html}")
        jobs = parse_linkedin_tracker_html(args.html)
        if jobs:
            json_path, csv_path = save_saved_jobs_to_output(jobs)
            print(f"✓ Extracted {len(jobs)} saved jobs from LinkedIn Jobs Tracker HTML")
            print(f"  JSON: {json_path}")
            print(f"  CSV: {csv_path}")
            print()
            for job in jobs:
                print(f"  [{job['job_id']}] {job['title']}")
                print(f"         {job['company']} · {job['location']} · {job['posted']}")
        else:
            print("✗ No jobs found in HTML file.")
        sys.exit(0)

    sites = ["indeed", "linkedin"] if args.site == "all" else [args.site]

    asyncio.run(main(
        headless=args.headless,
        max_jobs=args.max_jobs,
        sites=sites
    ))