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


# The card element on the search listing. Used both to extract the card fields and
# to click through to the preview pane, so the two stay in the same DOM order.
_CARD_SELECTOR = "div.job_seen_beacon"

# The pane renders client-side after the click. Waiting on the selector rather than
# a fixed sleep is what keeps the per-job cost near 1s instead of the 4s a blind
# wait needed.
_PANE_TIMEOUT_MS = 8000

# Pause between searches. Indeed throttles the search listing itself — three
# back-to-back searches succeeded and the fourth timed out — and the listing is
# fetched once per search whether it returns 2 cards or 16.
_SEARCH_PAUSE_SECONDS = 8

# Cloudflare's decision is not deterministic — on 2026-08-04, 11 of 36 searches
# were let through and 25 were challenged; on 2026-08-05, all 36 were challenged.
# A challenge is therefore worth re-attempting from a fresh browser context
# rather than writing the search off, as long as the retries are paced enough to
# not read as a burst themselves.
_CLOUDFLARE_RETRIES = 2
_CLOUDFLARE_RETRY_PAUSE_SECONDS = 45


class CloudflareBlocked(RuntimeError):
    """The search listing served a challenge page that this run cannot solve.

    Distinct from a generic failure so the caller can retry it specifically: a
    timeout means Indeed is throttling and more requests make it worse, whereas
    a challenge is a coin flip that is worth flipping again.
    """


def _headed_display_available() -> bool:
    """Whether a headed chromium could actually start.

    Testing `DISPLAY` for presence alone is not enough and was the specific
    reason Indeed produced nothing for weeks: the cron job inherits DISPLAY from
    the desktop session that spawned the scheduler, so the variable is set while
    no X server is reachable from the job. The headed relaunch then died with
    "Missing X server or $DISPLAY" on every one of the 36 searches. Check that
    the socket the display names is actually there.
    """
    display = os.environ.get("DISPLAY", "").strip()
    if not display:
        return False
    # "host:0.0" — a remote/TCP display; no local socket to inspect, so trust it.
    host, _, rest = display.rpartition(":")
    if host:
        return True
    number = rest.split(".")[0]
    if not number.isdigit():
        return False
    return os.path.exists(f"/tmp/.X11-unix/X{number}")

# Description containers in the preview pane, best first. The second is the
# wrapper and carries the "Job details / Pay / Job type" header as well, so it is
# only a fallback — it inflates every description by the same ~220 chars.
_PANE_SELECTORS = ("#jobDescriptionText", ".jobsearch-JobComponent-description")


# Indeed is the only site that truncates at scrape time, and 5,000 cut 203 of
# its 438 stored descriptions — 46% — at exactly that boundary. Unlike a prompt
# cap this one is not recoverable: the rest of the posting is never written to
# disk, so no later rescoring can reach it. Deliberately well above
# matcher.JOB_DESC_CHAR_BUDGET rather than equal to it — the scorer is not the
# only reader (the CV and cover-letter generators and the reviewer read the
# same field), and a cap raised later cannot recover text that was never
# stored. Sized past the 12,807-20,406 chars per posting measured on the pane
# in _fill_descriptions_from_pane, so this cuts nothing seen so far and exists
# only to bound a runaway. Postings already saved at 5,000 stay truncated
# until they are scraped again.
_MAX_DESCRIPTION_CHARS = 24000


async def _pane_description(page) -> str:
    """The description text currently shown in the listing page's preview pane."""
    for selector in _PANE_SELECTORS:
        el = await page.query_selector(selector)
        if not el:
            continue
        text = (await el.inner_text()).strip()
        if len(text) > 50:
            return text[:_MAX_DESCRIPTION_CHARS]
    return ""


async def _fill_descriptions_from_pane(page, jobs_by_jk: dict[str, dict]) -> int:
    """Fill `description` in place by clicking each card and reading the pane.

    Indeed's /viewjob detail page cannot be used at all. It answers with
    "Additional Verification Required" and a Cloudflare Ray ID — a hard block, not
    a challenge that waiting or retrying solves — even under `xvfb-run` with a
    headed browser and stealth applied. Measured 2026-07-26: the search listing
    loads fine in 11s and yields 16 cards, while three retries against /viewjob
    spent 62s and returned 0 characters. That 62s per posting is also where the
    1021s-per-search figure came from, which is why indeed scraped nothing for 12
    days without ever reporting an error.

    Clicking a card loads the same description into a pane on the listing page.
    No navigation happens, so nothing is challenged: measured 12,807-20,406 chars
    per posting.

    Cards are re-queried on every iteration because the click re-renders the list,
    and jobs are matched by `jk` rather than by index — a duplicate URL is dropped
    from `jobs` but still occupies a card, so index alignment would silently pair
    descriptions with the wrong postings.
    """
    filled = 0
    card_count = len(await page.query_selector_all(_CARD_SELECTOR))
    for idx in range(card_count):
        cards = await page.query_selector_all(_CARD_SELECTOR)
        if idx >= len(cards):
            break
        try:
            link = await cards[idx].query_selector("h2 a, a.jcs-JobTitle")
            if link is None:
                continue
            href = await link.get_attribute("href") or ""
            jk_match = re.search(r"jk=([a-f0-9]+)", href)
            if not jk_match:
                continue
            job = jobs_by_jk.get(jk_match.group(1))
            if job is None or job.get("description"):
                continue
            await link.click()
            await page.wait_for_selector(_PANE_SELECTORS[0], timeout=_PANE_TIMEOUT_MS)
            description = await _pane_description(page)
        except Exception:
            continue
        if description:
            job["description"] = description
            filled += 1
    return filled


async def _fetch_job_description(page, url: str, retries: int = 3) -> str:
    """
    Navigate to a job's detail page and extract the full description text.
    Returns up to _MAX_DESCRIPTION_CHARS of cleaned text, or "" on failure.

    DOES NOT WORK on Indeed and cannot be made to. /viewjob is Cloudflare-blocked
    outright (see _fill_descriptions_from_pane), so every call here burns ~62s over
    its retries and returns "". It is retained only because `run.py` and
    `refetch_unscoreable.py` still import it by name for the per-site refetch path,
    where it fails as an empty result rather than an error — those two call sites
    are known-broken for indeed and should move to the pane approach.
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
                        return text[:_MAX_DESCRIPTION_CHARS]

            # Fallback: grab the main content area
            main_el = await page.query_selector("main, #main-content, #wrapper")
            if main_el:
                text = await main_el.inner_text()
                if text and len(text.strip()) > 100 and "cloudflare" not in text.lower():
                    return text.strip()[:_MAX_DESCRIPTION_CHARS]

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
            if _headed_display_available():
                print("  🔑 No cookies found. Launching in non-headless mode for Cloudflare verification...")
                is_headless = False
                force_bypass = True
            else:
                # Same trap as the Cloudflare relaunch below: headed chromium cannot
                # start without a reachable X server, so forcing it here would crash
                # instead of falling back. Stay headless and let the Cloudflare check
                # report the real problem.
                print("  🔑 No cookies found and no usable X display — staying headless; "
                      "Cloudflare will likely block. Use `xvfb-run`, or run "
                      "interactively once to create cookies/indeed_cookies.json.")

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
            if is_headless and not _headed_display_available():
                # No reachable X server: chromium cannot start headed, so the
                # relaunch below would die with "Target page, context or browser has
                # been closed" and the caller's except would print a failure and exit
                # 0. That is how Indeed went 11 days contributing nothing while the
                # cron recorded success every night. Raise instead of returning [] so
                # the caller can retry the coin flip rather than treating a challenge
                # as "this search has no results".
                print("  ⛔ Cloudflare challenge, and no usable X display for a headed "
                      "retry. Wrap the command in `xvfb-run`, or run it interactively "
                      "once to refresh cookies/indeed_cookies.json.")
                await browser.close()
                raise CloudflareBlocked(f"{keyword}/{location}: Cloudflare challenge, no headed fallback")
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
                await page.wait_for_selector(_CARD_SELECTOR, timeout=10000)
            except PwTimeout:
                print("  ⚠ No job cards found, stopping.")
                break

            # --- Extract job cards ---
            cards = await page.query_selector_all(_CARD_SELECTOR)
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

            # --- Fill descriptions from the listing page's preview pane ---
            # Not from /viewjob: see _fill_descriptions_from_pane for why that URL
            # cannot be used at all.
            if cache is None:
                cache = load_description_cache()

            fetched = 0
            skipped = 0
            needing: dict[str, dict] = {}
            for job in jobs[page_jobs_start:]:
                cache_key = (job.get("title", "").strip().lower(),
                             job.get("company", "").strip().lower())
                cached_job = cache.get(cache_key)
                if cached_job and cached_job.get("description"):
                    job["description"] = cached_job["description"]
                    job["snippet"] = cached_job.get("snippet", cached_job["description"][:300])
                    if "analysis" in cached_job:
                        job["analysis"] = cached_job["analysis"]
                    skipped += 1
                    continue
                jk_match = re.search(r"jk=([a-f0-9]+)", job.get("url", ""))
                if jk_match:
                    needing[jk_match.group(1)] = job

            if needing:
                fetched = await _fill_descriptions_from_pane(page, needing)
                for job in needing.values():
                    if job.get("description"):
                        cache[(job.get("title", "").strip().lower(),
                               job.get("company", "").strip().lower())] = job

            if fetched or skipped:
                print(f"    → Fetched {fetched} descriptions, skipped {skipped} "
                      f"(cache hits) from the listing pane")

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
    """Run Indeed scraper for all keyword+location combos in config.

    One failed search must not discard the rest. Indeed starts refusing the search
    listing after a few consecutive requests — measured 2026-07-26, three searches
    succeeded and the fourth raised `Page.goto: Timeout 30000ms exceeded`. That one
    exception propagated out of this function, so run.py reported "every requested
    site failed" and threw away the 6 postings already in hand. Failures are counted
    instead, and only a run where nothing at all succeeded is escalated, which keeps
    the non-zero exit code meaningful for the cron summary.
    """
    all_jobs = []
    seen = set()

    locations = config.get("locations", [""])
    keywords = config.get("keywords", [])
    from selection import max_pages_for
    max_pages = max_pages_for("indeed", config)
    cache = load_description_cache()

    searches = [(kw, loc) for kw in keywords for loc in locations]
    failures = []
    # Circuit breaker on the retries. Retrying every search costs up to
    # 36 x 2 x 45s = 54 minutes of sleeping, which on a night where Cloudflare
    # blocks everything would blow the 2400s per-site cron budget and turn a
    # clean "indeed blocked" into a scheduler timeout. Once several searches in
    # a row are blocked it is the IP being refused, not a coin flip, so the
    # retries stop earning their keep and are switched off for the rest of the
    # run — the first searches still get their chances.
    consecutive_blocked = 0
    _RETRY_GIVE_UP_AFTER = 3

    for index, (kw, loc) in enumerate(searches):
        if index:
            # Pacing between searches. The listing is what gets throttled, and it is
            # requested once per search regardless of how many cards it returns.
            await asyncio.sleep(_SEARCH_PAUSE_SECONDS)

        retries = 0 if consecutive_blocked >= _RETRY_GIVE_UP_AFTER else _CLOUDFLARE_RETRIES
        jobs = None
        for attempt in range(retries + 1):
            try:
                jobs = await scrape_indeed(kw, loc, max_pages=max_pages, config=config,
                                           cache=cache)
                break
            except CloudflareBlocked as e:
                if attempt == retries:
                    failures.append(f"{kw}/{loc}: {e}")
                    consecutive_blocked += 1
                    print(f"  ⚠ Indeed search blocked after {attempt + 1} attempt(s) "
                          f"({kw} in {loc})")
                    if consecutive_blocked == _RETRY_GIVE_UP_AFTER:
                        print(f"  ⛔ {consecutive_blocked} searches blocked in a row — "
                              f"retries disabled for the rest of this run")
                    break
                print(f"  ↻ Cloudflare challenge — retrying in "
                      f"{_CLOUDFLARE_RETRY_PAUSE_SECONDS}s "
                      f"({attempt + 1}/{retries})")
                await asyncio.sleep(_CLOUDFLARE_RETRY_PAUSE_SECONDS)
            except Exception as e:
                failures.append(f"{kw}/{loc}: {e}")
                print(f"  ⚠ Indeed search failed ({kw} in {loc}): {e}")
                break
        if jobs is None:
            continue
        consecutive_blocked = 0
        for j in jobs:
            dedup_key = (j["title"], j["company"], j["location"])
            if dedup_key not in seen:
                seen.add(dedup_key)
                all_jobs.append(j)

    if failures:
        print(f"  ⚠ Indeed: {len(failures)} of {len(searches)} searches failed, "
              f"kept {len(all_jobs)} jobs")
    if len(failures) == len(searches) and searches:
        raise RuntimeError(
            f"all {len(searches)} Indeed searches failed; first: {failures[0]}")

    # Indeed was the only site that skipped this, trusting its own search
    # relevance. It should not be trusted: measured 2026-08-05, 133 of the 296
    # postings a full run returned contained none of the configured keywords
    # anywhere — not in the title, not in the description. Searching "Technical
    # Artist" brought back "Technologist - Analog Design" and "Non-Apparel
    # Technologist"; semiconductor and garment roles, priced at an LLM
    # enrichment call each because the drop happened after that spend, if at all.
    #
    # The filter reads title + description + snippet, so it keeps the postings
    # whose relevance only shows in the body — of the jobs currently scoring
    # 0.80+, six match on the body alone and would be lost to a title-only test.
    from_search = len(all_jobs)
    all_jobs = filter_jobs_by_keywords(all_jobs, keywords)
    if from_search:
        print(f"  ✓ Indeed: {len(all_jobs)} of {from_search} postings match a "
              f"configured keyword")

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