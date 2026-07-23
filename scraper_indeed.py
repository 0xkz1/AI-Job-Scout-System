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
from scraper_helper import load_description_cache

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "10_output")


def sanitize_filename(text: str, max_len: int = 80) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', "", text).strip().replace(" ", "_")
    return safe[:max_len]


async def _stealth_context(context):
    """Apply anti-detection measures using playwright-stealth."""
    stealth = Stealth()
    await stealth.apply_stealth_async(context)


async def _fetch_job_description(page, url: str, retries: int = 3) -> str:
    """
    Navigate to a job's detail page and extract the full description text.
    Returns up to 5000 chars of cleaned text, or "" on failure.
    """
    for attempt in range(retries + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            # Fixed wait for JS rendering (networkidle timeout causes issues)
            await page.wait_for_timeout(8000)  # Wait for Cloudflare JS challenge + rendering

            # Indeed job description container — try multiple selectors
            desc_selectors = [
                "#jobDescriptionText",
                "div.jobsearch-JobComponentDescription",
                "div[data-testid='jobsearch-JobComponentDescription']",
                "#job-details",
                "div.job-description",
                "section.jobsearch-JobComponentDescription",
            ]
            # Check for Cloudflare block before trying selectors
            page_title = await page.title()
            if "just a moment" in page_title.lower():
                # Cloudflare challenge — wait longer and retry
                if attempt < retries:
                    await page.wait_for_timeout(10000)
                    continue
                return ""

            body_el = await page.query_selector("body")
            if body_el:
                body_text = await body_el.inner_text()
                if "additional verification required" in body_text.lower() or "cloudflare" in body_text.lower():
                    # Rate limited — wait longer and retry
                    if attempt < retries:
                        await page.wait_for_timeout(15000)
                        continue
                    return ""

            for sel in desc_selectors:
                desc_el = await page.query_selector(sel)
                if desc_el:
                    text = await desc_el.inner_text()
                    if text and len(text.strip()) > 50:
                        # Check if text is actually a Cloudflare page (162 chars)
                        if "cloudflare" in text.lower() or "verification" in text.lower():
                            if attempt < retries:
                                await page.wait_for_timeout(10000)
                                continue
                            return ""
                        text = re.sub(r"\n{3,}", "\n\n", text.strip())
                        return text[:5000]

            # Fallback: grab the main content area
            main_el = await page.query_selector("main, #main-content, #wrapper")
            if main_el:
                text = await main_el.inner_text()
                if text and len(text.strip()) > 100 and "cloudflare" not in text.lower():
                    return text.strip()[:5000]

            return ""
        except Exception:
            if attempt < retries:
                await page.wait_for_timeout(2000)
                continue
            return ""
    return ""


async def scrape_indeed(
    keyword: str,
    location: str = "",
    max_pages: int = 3,
    headless: bool = True,
    config: dict | None = None,
    cache: dict | None = None,
) -> list[dict]:
    """
    Search Indeed UK and return job listings.
    """
    jobs = []
    seen_urls = set()

    base_url = "https://uk.indeed.com"
    search_url = f"{base_url}/jobs?q={quote_plus(keyword)}&l={quote_plus(location)}"

    # --- Cookie Configuration ---
    cookie_dir = None
    cookie_path = None
    if config and "cookie_config" in config:
        cc = config["cookie_config"]
        cookie_dir = cc.get("cookie_dir", "")
        if cookie_dir:
            import os as _os
            os.makedirs(cookie_dir, exist_ok=True)
            cookie_path = _os.path.join(cookie_dir, cc.get("indeed_cookie_file", "indeed_cookies.json"))

    async with async_playwright() as p:
        # Step 1: Attempt to launch browser
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ]
        
        # Determine headless state. If no cookies exist, force non-headless once to bypass Cloudflare
        is_headless = headless
        force_bypass = False
        import os as _os
        if cookie_path and not _os.path.exists(cookie_path):
            print("  🔑 No cookies found. Launching in non-headless mode for Cloudflare verification...")
            is_headless = False
            force_bypass = True

        browser = await p.chromium.launch(
            headless=is_headless,
            args=launch_args,
        )

        context_args = {
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "viewport": {"width": 1920, "height": 1080},
            "locale": "en-GB",
            "timezone_id": "Europe/London",
            "geolocation": {"latitude": 55.9533, "longitude": -3.1883},
            "permissions": ["geolocation"],
        }
        
        if cookie_path and _os.path.exists(cookie_path):
            context_args["storage_state"] = cookie_path
            print(f"  🔑 Loaded persistent cookies from {cookie_path}")

        context = await browser.new_context(**context_args)
        await _stealth_context(context)
        page = await context.new_page()

        print(f"🔍 Indeed: searching '{keyword}' in '{location}'...")
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # Step 2: Detect Cloudflare challenge page
        page_title = await page.title()
        if "just a moment" in page_title.lower() or "cloudflare" in (await page.content()).lower():
            print("  ⚠️ Cloudflare verification detected!")
            
            # If we are headless, we must restart in non-headless mode to let user bypass it
            if is_headless:
                print("  🔄 Headless mode blocked by Cloudflare. Relaunching in non-headless mode...")
                await browser.close()
                
                # Relaunch non-headless
                browser = await p.chromium.launch(headless=False, args=launch_args)
                context = await browser.new_context(
                    user_agent=context_args["user_agent"],
                    viewport=context_args["viewport"],
                    locale=context_args["locale"],
                    timezone_id=context_args["timezone_id"],
                    geolocation=context_args["geolocation"],
                    permissions=context_args["permissions"],
                )
                if cookie_path and _os.path.exists(cookie_path):
                    with open(cookie_path) as fh:
                        await context.add_cookies(json.load(fh)["cookies"])
                await _stealth_context(context)
                page = await context.new_page()
                
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)
                force_bypass = True

            if force_bypass or not is_headless:
                print("\n" + "="*80)
                print("  🚨 ACTION REQUIRED: Please solve the Cloudflare verification in the browser window.")
                print("  Once you are on the search results page, press ENTER in this terminal to continue...")
                print("="*80 + "\n")
                
                # Wait for user input or auto-detect success
                import sys
                # Since we run inside a tool context, we can attempt to wait for 15 seconds to let the user solve it,
                # or wait for terminal keyboard input. Because we can't easily block on stdin in some automated runs,
                # we'll wait for the title to change or up to 20 seconds, checking every 2 seconds.
                for _ in range(15):
                    await page.wait_for_timeout(2000)
                    title = await page.title()
                    if "just a moment" not in title.lower():
                        print("  ✅ Cloudflare bypassed!")
                        break
                else:
                    # Final fallback: wait for any input if we are interactive
                    print("  ⚠️ Timeout waiting for bypass. Attempting to continue anyway...")

                # Save new storage state
                if cookie_path:
                    await context.storage_state(path=cookie_path)
                    print(f"  💾 Saved bypass cookies to {cookie_path}")

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

            page_jobs_start = len(jobs)

            for card in cards:
                try:
                    job = await _extract_job_card(card, base_url)
                    if job and job["url"] not in seen_urls:
                        seen_urls.add(job["url"])
                        jobs.append(job)
                except Exception as e:
                    continue

            # --- Fetch full descriptions via /viewjob?jk=... URLs ---
            # Check cache first
            if cache is None:
                cache = load_description_cache()
                
            fetched = 0
            skipped = 0
            for i, job in enumerate(jobs[page_jobs_start:]):
                # Check cache
                title_lower = job.get("title", "").strip().lower()
                company_lower = job.get("company", "").strip().lower()
                cache_key = (title_lower, company_lower)
                
                if cache_key in cache and cache[cache_key].get("description"):
                    cached_job = cache[cache_key]
                    job["description"] = cached_job["description"]
                    job["snippet"] = cached_job.get("snippet", cached_job["description"][:300])
                    if "analysis" in cached_job:
                        job["analysis"] = cached_job["analysis"]
                    skipped += 1
                    continue

                if not job.get("description"):
                    url = job.get("url", "")
                    jk_match = re.search(r"jk=([a-f0-9]+)", url)
                    if jk_match:
                        jk = jk_match.group(1)
                        viewjob_url = f"{base_url}/viewjob?jk={jk}"
                        try:
                            # Use a fresh page for each detail fetch
                            detail_page = await context.new_page()
                            desc = await _fetch_job_description(detail_page, viewjob_url)
                            await detail_page.close()
                            if desc:
                                job["description"] = desc
                                # Update cache
                                cache[cache_key] = job
                                fetched += 1
                                if fetched % 5 == 0:
                                    print(f"    → Fetched {fetched} descriptions...")
                            await page.wait_for_timeout(1000)  # Rate limit courtesy
                        except Exception as e:
                            try:
                                await detail_page.close()
                            except Exception:
                                pass
                            print(f"    ⚠ Failed to fetch description for jk={jk}: {e}")
            if fetched or skipped:
                print(f"    → Fetched {fetched} descriptions, skipped {skipped} (cache hits) from detail pages")

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

        # --- Description snippet (from card, may be empty) ---
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
            "description": "",  # Will be filled by _fetch_job_description
            "url": url,
            "source": "indeed",
            "type": "auto",
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
    cache = load_description_cache()

    for kw in keywords:
        for loc in locations:
            jobs = await scrape_indeed(kw, loc, max_pages=max_pages, config=config, cache=cache)
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


def filter_jobs_by_keywords(jobs: list[dict], keywords: list[str]) -> list[dict]:
    """Filter jobs to only keep those whose title or description contains any keyword."""
    if not keywords:
        return jobs
    kw_lower = [k.lower() for k in keywords]
    kept = []
    removed = 0
    for j in jobs:
        text = f"{j.get('title', '')} {j.get('description', '')} {j.get('snippet', '')}".lower()
        if any(kw in text for kw in kw_lower):
            kept.append(j)
        else:
            removed += 1
    if removed:
        print(f"  🗑️ Filtered out {removed} jobs (no keyword match)")
    return kept


def _format_job_md(job: dict) -> str:
    # Jobs from other scrapers / saved-jobs staging pass through here too
    # (run.py save_indeed), so no key can be assumed present.
    url = job.get("url", "")
    return f"""# Job Description: {job.get('title', 'Unknown')}

> **Source:** [{job.get('source_site') or job.get('source', 'unknown')}]({url})
> **Scraped:** {job.get('scraped_at', 'unknown')}

---

## Company

**{job.get('company', 'Unknown')}**
Location: {job.get('location', 'Unknown')}

---

## Salary

{job.get('salary') or 'Not specified'}

---

## Description

{job.get('description') or job.get('snippet') or 'No description available.'}

---

## Metadata

- **Search Source:** {job.get('source', 'unknown')}
- **URL:** {url}
"""


if __name__ == "__main__":
    import yaml

    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    jobs = asyncio.run(scrape_indeed_all(cfg))
    save_jobs(jobs)
    print(f"\n✅ Done! {len(jobs)} jobs scraped from Indeed.")