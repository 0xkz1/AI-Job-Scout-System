"""
Indeed Job Scraper
==================
Scrapes job listings from Indeed UK using Playwright (headless Chromium).
Uses stealth config to bypass Cloudflare.
"""

import asyncio
import json
import re
import os
from datetime import datetime
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from playwright_stealth import Stealth

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def sanitize_filename(text: str, max_len: int = 80) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', "", text).strip().replace(" ", "_")
    return safe[:max_len]


async def _stealth_context(context):
    """Apply anti-detection measures using playwright-stealth."""
    stealth = Stealth()
    await stealth.apply_stealth_async(context)


async def scrape_indeed(
    keyword: str,
    location: str = "",
    max_pages: int = 3,
    headless: bool = True,
) -> list[dict]:
    """
    Search Indeed UK and return job listings.
    """
    jobs = []
    seen_urls = set()

    base_url = "https://uk.indeed.com"
    search_url = f"{base_url}/jobs?q={quote_plus(keyword)}&l={quote_plus(location)}"

    async with async_playwright() as p:
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
            geolocation={"latitude": 55.9533, "longitude": -3.1883},
            permissions=["geolocation"],
        )
        await _stealth_context(context)
        page = await context.new_page()

        print(f"🔍 Indeed: searching '{keyword}' in '{location}'...")
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

        # Accept cookies if shown
        try:
            accept_btn = await page.query_selector("button:has-text('Accept All')")
            if accept_btn:
                await accept_btn.click()
                await page.wait_for_timeout(1000)
        except Exception:
            pass

        await page.wait_for_timeout(2000)

        for page_num in range(1, max_pages + 1):
            try:
                await page.wait_for_selector("div.job_seen_beacon", timeout=10000)
            except PwTimeout:
                print("  ⚠ No job cards found, stopping.")
                break

            # --- Extract job cards ---
            cards = await page.query_selector_all("div.job_seen_beacon")
            print(f"  Page {page_num}: found {len(cards)} job cards")

            for card in cards:
                try:
                    job = await _extract_job_card(card, base_url)
                    if job and job["url"] not in seen_urls:
                        seen_urls.add(job["url"])
                        jobs.append(job)
                except Exception as e:
                    continue

            # --- Go to next page ---
            next_link = await page.query_selector(
                'a[data-testid="pagination-page-next"]'
            )
            if next_link:
                try:
                    href = await next_link.get_attribute("href")
                    if href and href != "#":
                        await page.goto(
                            base_url + href,
                            wait_until="domcontentloaded",
                            timeout=30000,
                        )
                        await page.wait_for_timeout(2000)
                    else:
                        print("  ✓ No more pages.")
                        break
                except Exception:
                    print("  ⚠ Could not navigate to next page.")
                    break
            else:
                print("  ✓ No more pages.")
                break

        await browser.close()

    print(f"  ✓ Total: {len(jobs)} unique jobs from Indeed")
    return jobs


async def _extract_job_card(card, base_url: str) -> dict | None:
    """Extract details from a job_seen_beacon div."""
    try:
        # --- Title ---
        title_el = await card.query_selector("a.jcs-JobTitle")
        if not title_el:
            title_el = await card.query_selector("h2.jobTitle a")
        if not title_el:
            title_el = await card.query_selector("a[data-jk]")
        if not title_el:
            return None

        title = await title_el.get_attribute("title") or await title_el.inner_text()
        title = title.strip()

        # --- URL ---
        url = await title_el.get_attribute("href") or ""
        if url and not url.startswith("http"):
            url = base_url + url

        # --- Company ---
        company_el = await card.query_selector(
            'span[data-testid="company-name"], '
            "span.companyName, "
            ".companyName"
        )
        company = await company_el.inner_text() if company_el else ""
        company = company.strip()

        # --- Location ---
        loc_el = await card.query_selector(
            'div[data-testid="text-location"], '
            ".companyLocation"
        )
        location_text = await loc_el.inner_text() if loc_el else ""
        location_text = location_text.strip()

        # --- Salary ---
        salary_el = await card.query_selector(
            'div.salary-snippet-container, '
            ".salary-snippet, "
            ".salaryOnly, "
            ".metadata.salary"
        )
        salary_text = await salary_el.inner_text() if salary_el else ""
        salary_text = salary_text.strip()

        # --- Description snippet ---
        desc_el = await card.query_selector("div.job-snippet")
        description = await desc_el.inner_text() if desc_el else ""
        description = description.strip().replace("\n", " ")[:500]

        if not title:
            return None

        return {
            "title": title,
            "company": company,
            "location": location_text,
            "salary": salary_text,
            "snippet": description,
            "description": "",
            "url": url,
            "source": "indeed",
            "source_site": "Indeed",
            "scraped_at": datetime.now().isoformat(),
        }

    except Exception as e:
        return None


async def scrape_indeed_all(config: dict) -> list[dict]:
    """Run Indeed scraper for all keyword+location combos in config."""
    all_jobs = []
    seen = set()

    locations = config.get("locations", [""])
    keywords = config.get("keywords", [])
    max_pages = config.get("max_pages_per_search", 3)

    for kw in keywords:
        for loc in locations:
            jobs = await scrape_indeed(kw, loc, max_pages=max_pages)
            for j in jobs:
                dedup_key = (j["title"], j["company"], j["location"])
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    all_jobs.append(j)

    return all_jobs


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

    index_path = os.path.join(output_dir, "_index.json")
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


if __name__ == "__main__":
    import yaml

    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    jobs = asyncio.run(scrape_indeed_all(cfg))
    save_jobs(jobs)
    print(f"\n✅ Done! {len(jobs)} jobs scraped from Indeed.")
