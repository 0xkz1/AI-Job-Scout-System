import os
import re
import sys
import json
import asyncio
import fcntl
from datetime import datetime
from urllib.parse import urlparse
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from llm_client import call_llm
from scraper_linkedin_guest import fetch_one, job_id_from_url

SAVED_DIR = os.path.join(os.path.dirname(__file__), "00_saved")
URL_LIST_FILE = os.path.join(SAVED_DIR, "url-list.md")
OUTPUT_FILE = os.path.join(SAVED_DIR, "url_list_jobs.json")
COOKIE_FILE = os.path.join(os.path.dirname(__file__), "cookies", "indeed_cookies.json")

# Anti-bot interstitials are short, but not short enough to trip the
# too-short guard: Indeed's Cloudflare page renders 250 characters of "Additional
# Verification Required / Your Ray ID is ...", which passed the len < 100 test
# and was then handed to the model as if it were a job posting. Every one of
# those cost a full extraction call and produced nothing. Detect them by what
# they say instead of how long they are.
BLOCK_MARKERS = (
    "additional verification required",          # Indeed
    "performing security verification",          # jobleads, learn4good
    "protect against malicious bots",            # same family, different wording
    "just a moment",
    "checking your browser",
    "enable javascript and cookies to continue",
    "verify you are human",
    "attention required! | cloudflare",
    "access to this page has been denied",
    "performance and security by cloudflare",
)

# A last-resort check for interstitials whose wording is not in the list above.
# Every anti-bot page seen so far is under 400 characters AND cites a Cloudflare
# Ray ID; a real job posting is thousands of characters and cites none. Both
# conditions together, so a genuinely terse posting is not thrown away.
BLOCK_MAX_CHARS = 400
RAY_ID_RE = re.compile(r"\bray id\b", re.IGNORECASE)

# Indeed answers a signed-out /viewjob with a sign-in wall rather than a 403: a
# 404-character page reading "Ready to take the next step? / Create an account
# or sign in." It cites no Cloudflare and carries no Ray ID, so neither guard
# above sees it, and at 404 characters it clears BLOCK_MAX_CHARS by four. On
# 2026-09-07 that handed the model a login form 27 times in one 33-URL run and
# every one of them came back an empty object.
#
# Length-gated because real postings do close with "ready to take the next
# step?" as a call to action. A page that says it in under a thousand
# characters is the wall; a posting that says it is thousands long.
LOGIN_WALL_MARKERS = (
    "create an account or sign in",
    "ready to take the next step",
)
LOGIN_WALL_MAX_CHARS = 1000

# Floor for accepting an Indeed page that has no #jobDescriptionText element —
# the branch the sign-in wall walked through. Measured on the same run: the
# wall bodies were 404 characters, the one genuine page that reached this
# branch was 7,954. The old floor of 300 sat below both.
INDEED_BODY_MIN_CHARS = 1200


ANALYZED_PATH = os.path.join(os.path.dirname(__file__), "10_output", "_analyzed.json")


def _indeed_jk(url: str) -> str:
    m = re.search(r"[?&]jk=([a-f0-9]+)", url or "")
    return m.group(1) if m else ""


def adopt_from_database(urls: list[str]) -> list[dict]:
    """Postings among `urls` the nightly scraper has already fetched.

    Matched on Indeed's `jk`, which identifies the posting regardless of how
    many tracking parameters the copied URL carries — the reason the two are
    compared by id rather than by URL equality.
    """
    wanted = {_indeed_jk(u): u for u in urls if _indeed_jk(u)}
    if not wanted:
        return []
    try:
        with open(ANALYZED_PATH, encoding="utf-8") as f:
            db = json.load(f)
    except Exception as e:
        print(f"  ⚠ could not read the analysed DB ({e}) — nothing to adopt")
        return []

    out = []
    for job in db:
        jk = _indeed_jk(job.get("url") or "")
        if jk not in wanted or not (job.get("description") or "").strip():
            continue
        adopted = dict(job)
        # Keep the URL the user actually pasted so re-runs recognise it, and
        # drop the scoring — url_list_jobs.json is a staging file, and run.py
        # re-analyses from scratch on merge.
        adopted["url"] = wanted.pop(jk)
        adopted.pop("match", None)
        adopted["type"] = "manual"
        out.append(adopted)

    if out:
        print(f"  ♻ Adopted {len(out)} Indeed posting(s) already scraped by the "
              f"nightly run — /viewjob cannot be fetched directly")
        for j in out:
            print(f"      {(j.get('title') or '?')[:44]:46} | {(j.get('company') or '?')[:24]}")
    return out


def looks_blocked(text: str) -> str | None:
    """Why this page is an anti-bot interstitial rather than a posting, or None.

    Needed because the model does not refuse these pages — asked to extract a
    job from "Performing security verification", it returns a well-formed JSON
    object with every field empty, which the caller then rejects for missing a
    title. The URL is recorded as a failed extraction and the real cause, that
    the fetch never got through, is never stated.
    """
    low = text.lower()
    for marker in BLOCK_MARKERS:
        if marker in low:
            return marker
    if len(text) < BLOCK_MAX_CHARS and RAY_ID_RE.search(text):
        return "cloudflare ray id on a near-empty page"
    if len(text) < LOGIN_WALL_MAX_CHARS:
        for marker in LOGIN_WALL_MARKERS:
            if marker in low:
                return f"sign-in wall ({marker})"
    return None


def _try_acquire_lock(name="url_list_jobs"):
    """Try to acquire an exclusive file lock (non-blocking).
    Returns the lock file handle (keep open while locked) or None if already locked."""
    lock_path = f"/tmp/jis_{name}.lock"
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file
    except (IOError, OSError, BlockingIOError):
        lock_file.close()
        return None

def extract_job_from_text(text: str) -> dict:
    prompt = f"""
You are an expert data extractor. Extract the job listing details from the following text (which was scraped from a job board or company website).

IMPORTANT: The page text may include unrelated listings from "Similar jobs" /
"More jobs at this company" sidebars. Extract ONLY the MAIN job posting — the
one whose full description appears on this page (its title is near the top,
directly above the description). The title MUST be the one that belongs to
that description, never a title from a sidebar list.

Extract the following fields:
- title (string)
- company (string)
- location (string)
- description (string) - The full job description text.
- salary (string) - Leave blank if not found.

Respond ONLY with valid JSON in this exact format:
{{
  "title": "Job Title",
  "company": "Company Name",
  "location": "Location",
  "salary": "Salary if mentioned, else empty string",
  "description": "Full job description text..."
}}

Text:
{text[:15000]}
"""
    # Note: increased text limit to 15000 chars because we use raw innerText now
    #
    # Through call_llm rather than a hardcoded POST to localhost:11434. This was
    # the one module in the project talking to Ollama directly, which meant it
    # ignored FALLBACK_PROVIDERS and, more importantly, key_quarantine — so it
    # could neither use a cloud key when one was healthy nor stand down from one
    # that had started returning 401. It also pinned every extraction to a local
    # 26B reasoning model: measured 2026-08-03, a median 107s per URL against a
    # 120s timeout, so the slowest pages timed out and were discarded outright.
    # The chain ends at ollama, so a local-only setup behaves as before.
    try:
        content = call_llm(
            [{"role": "user", "content": prompt}],
            system_prompt="You are a helpful assistant that outputs only valid JSON.",
            temperature=0.1,
            # The description is the whole point of this call and job postings
            # run long; the default 512 truncates them mid-sentence.
            max_tokens=4096,
        )
        matches = list(re.finditer(r'\{.*\}', content, re.DOTALL))
        for match in reversed(matches):
            try:
                extracted = json.loads(match.group(), strict=False)
                return extracted
            except json.JSONDecodeError:
                continue
        print("    ⚠ LLM returned no parseable JSON")
    except Exception as e:
        print(f"    Error calling LLM: {type(e).__name__}: {e}")
    return None

def get_source_site(url: str) -> str:
    """Human-readable site name for source_site field."""
    domain = urlparse(url).netloc.lower()
    if "linkedin.com" in domain:
        return "LinkedIn"
    elif "indeed" in domain:
        return "Indeed"
    elif "reed.co.uk" in domain:
        return "Reed"
    elif "ycombinator.com" in domain:
        return "Y Combinator"
    elif "glassdoor" in domain:
        return "Glassdoor"
    return domain.replace("www.", "")

def normalize_url(url: str) -> str:
    """Normalize URL for robust duplicate detection.

    - Lowercase scheme + netloc (domain)
    - Remove trailing slash from path
    - Strip known tracking parameters (Indeed, LinkedIn, etc.)
    - Sort remaining query params so different ordering doesn't cause dup false-negatives
    """
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"

    # Strip tracking params — keep only the core job-identifying param
    TRACKING_PARAMS = {
        # Indeed. `hl` is the display language, not part of the job's identity —
        # observed 2026-08-06, jk=041cc148b17a1ece appeared twice in one run as
        # "?jk=...&hl=en" and "?jk=...&from=serp&vjs=3", because only the second
        # form's params were being stripped.
        "from", "SP", "pos", "sid", "tk", "rq", "rl", "vjs", "iaai", "ad", "hl",
        "advn", "adid", "sjdu", "acatk", "pub", "xkcb", "xpse", "xfps",
        # LinkedIn. `lipi` is the one the "Saved jobs" page appends, so a URL
        # copied from there and the same job copied from search read as two
        # different postings — observed 2026-08-06, Bettervits Product
        # Specialist fetched twice in one run and stored twice.
        "refId", "trk", "trkInfo", "utm_source", "utm_medium", "utm_campaign",
        "lipi", "licu", "midToken", "midSig", "eBP", "trackingId", "position",
        "pageNum", "originalSubdomain",
        # Generic
        "utm_content", "utm_term", "gclid", "fbclid", "msclkid",
    }
    if parts.query:
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        kept = [(k, v) for k, v in pairs if k not in TRACKING_PARAMS]
        kept.sort()
        query = urlencode(kept)
    else:
        query = ""

    return urlunsplit((scheme, netloc, path, query, ""))


def get_source_key(url: str) -> str:
    """Lowercase source key for the source field (used in reports/filters)."""
    domain = urlparse(url).netloc.lower()
    if "linkedin.com" in domain:
        return "linkedin"
    elif "indeed" in domain:
        return "indeed"
    elif "reed.co.uk" in domain:
        return "reed"
    elif "ycombinator.com" in domain:
        return "ycombinator"
    elif "glassdoor" in domain:
        return "glassdoor"
    return domain.replace("www.", "").split(".")[0]


def dropped_sources() -> set[str]:
    """The boards config.yaml says this pipeline no longer takes."""
    try:
        import yaml
        config = yaml.safe_load(
            open(os.path.join(os.path.dirname(__file__), "config.yaml"),
                 encoding="utf-8")) or {}
    except Exception:
        return set()
    return {str(s).strip().lower() for s in config.get("dropped_sources", [])}


def drop_dropped_sources(urls: list[str]) -> tuple[list[str], list[str]]:
    """Split pasted URLs into the ones to fetch and the ones from a dropped board.

    run.py drops these on the way in from staging, which is enough to keep them
    out of the database but not enough to stop the fetch: url-list.md is read
    before any of that, so a dropped board was still costing a page load and an
    extraction call per link. Filtering here means a URL from talents.studysmarter
    .co.uk (fraudulent, dropped 2026-08-31) is never requested at all.
    """
    dropped = dropped_sources()
    if not dropped:
        return urls, []
    keep, skip = [], []
    for u in urls:
        (skip if get_source_key(u) in dropped else keep).append(u)
    return keep, skip



async def _fetch_indeed_page(page, url: str, jk: str) -> str | None:
    """Fetch job posting text from Indeed using the fastest, highest-yield variant first.

    Direct /viewjob is heavily blocked by Cloudflare (403), whereas the mobile Web
    endpoint (m/viewjob) with cookies + stealth succeeds in ~2s and returns the full
    #jobDescriptionText. We try m/viewjob first, and only fall back if needed.
    """
    variants = [
        ("m/viewjob (mobile - fastest & highest yield)", f"https://uk.indeed.com/m/viewjob?jk={jk}"),
        ("rc/clk (redirect route)", f"https://uk.indeed.com/rc/clk?jk={jk}"),
        ("viewjob (standard direct)", f"https://uk.indeed.com/viewjob?jk={jk}"),
    ]
    for label, target_url in variants:
        try:
            print(f"    → Trying {label}...")
            resp = await page.goto(target_url, wait_until="domcontentloaded", timeout=12000)
            await page.wait_for_timeout(2000)
            text = (await page.evaluate("document.body.innerText") or "").strip()
            if len(text) < 100:
                continue
            blocked = looks_blocked(text)
            if blocked:
                print(f"      ↳ {label}: {blocked}, {len(text)} chars")
                continue
            desc_el = await page.query_selector("#jobDescriptionText, .jobsearch-JobComponent-description")
            if desc_el:
                desc_text = (await desc_el.inner_text()).strip()
                if len(desc_text) > 100:
                    print(f"    ✓ Successfully retrieved Indeed description via {label} ({len(desc_text)} chars)")
                    return text
            elif len(text) >= INDEED_BODY_MIN_CHARS:
                print(f"    ✓ Retrieved Indeed page content via {label} ({len(text)} chars)")
                return text
            else:
                # Say which of the two it was, so the next wall variant is
                # diagnosable from the log instead of from a rerun.
                print(f"      ↳ {label}: no #jobDescriptionText and only "
                      f"{len(text)} chars of body — not a posting")
        except Exception:
            continue
    return None

async def _new_browser(p, announce: bool = True):
    """A fresh browser carrying the stored Indeed session, stealth applied.

    A factory rather than inline setup because the run rebuilds it mid-flight:
    Indeed's sign-in wall is a per-browser-session counter, not a block on
    being signed out. Measured 2026-09-11 with the same anonymous cookies —
    12 postings fetched in one browser session returned 1; the same postings
    fetched one per fresh browser returned 8 of 8, every one on m/viewjob at
    the first attempt. Relaunching resets it.
    """
    browser = await p.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    context_kwargs = {
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
        "locale": "en-GB",
        "timezone_id": "Europe/London",
    }
    if os.path.exists(COOKIE_FILE):
        context_kwargs["storage_state"] = COOKIE_FILE
        if announce:
            print(f"  → Loaded Indeed session from {COOKIE_FILE}")
    context = await browser.new_context(**context_kwargs)
    await Stealth().apply_stealth_async(context)
    page = await context.new_page()
    return browser, page


async def scrape_urls(urls):
    jobs = []
    
    # Load existing jobs to avoid re-scraping the same URLs
    existing_urls = set()
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing_jobs = json.load(f)
                existing_urls = {j.get("url") for j in existing_jobs if j.get("url")}
                jobs.extend(existing_jobs)
                print(f"Loaded {len(existing_jobs)} existing jobs from {OUTPUT_FILE}")
        except Exception:
            pass

    urls_to_scrape = [u for u in urls if u not in existing_urls]
    # Indeed's /viewjob is a hard block, not a challenge — measured 2026-08-06
    # under xvfb-run with a headed browser, cached cookies, stealth applied and
    # 30s of waiting, it still answered "Additional Verification Required" with
    # a Cloudflare Ray ID. No fetcher this module can build will read one.
    #
    # The nightly scraper reaches the same postings another way: it reads the
    # search listing and clicks each card to load the description into a pane,
    # never navigating to /viewjob at all. So a pasted Indeed URL is very often
    # already in the database — 12 of the 21 in url-list.md were, including a
    # Revolut Product Designer scoring 0.81. Adopt those instead of failing on
    # them; only the ones no search happened to surface are genuinely lost.
    adopted = adopt_from_database(urls_to_scrape)
    if adopted:
        jobs.extend(adopted)
        adopted_urls = {j["url"] for j in adopted}
        urls_to_scrape = [u for u in urls_to_scrape if u not in adopted_urls]
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)

    if not urls_to_scrape:
        print("No new URLs to scrape.")
        return jobs

    print(f"Found {len(urls_to_scrape)} new URLs to scrape.")

    async with async_playwright() as p:
        browser, page = await _new_browser(p)

        for i, url in enumerate(urls_to_scrape, 1):
            print(f"\n[{i}/{len(urls_to_scrape)}] Fetching: {url}")
            try:
                # LinkedIn publishes these fields as markup on its logged-out
                # endpoint, so asking a local 26B reasoning model to read them
                # back out of rendered prose buys nothing. Measured 2026-08-03:
                # the model path took a median 107s per URL and the slowest
                # exceeded its own 120s timeout and was discarded — 34 minutes
                # produced 16 jobs, and the run stopped with 50 URLs unread.
                # The guest endpoint answers the same question in ~0.3s.
                if job_id_from_url(url):
                    job_data = fetch_one(url)
                    if job_data:
                        job_data["url"] = url
                        job_data["source"] = get_source_key(url)
                        job_data["source_site"] = get_source_site(url)
                        jobs.append(job_data)
                        print(f"    ✓ Extracted (LinkedIn guest, no LLM): "
                              f"{job_data.get('title')} at {job_data.get('company')}")
                        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                            json.dump(jobs, f, indent=2, ensure_ascii=False)
                        continue
                    # Withdrawn, or LinkedIn changed its markup. Fall through to
                    # the model rather than dropping the URL outright.
                    print("    ⚠ Guest endpoint gave nothing — falling back to the LLM path")

                indeed_jk = _indeed_jk(url)
                if indeed_jk:
                    text = await _fetch_indeed_page(page, url, indeed_jk)
                    if not text:
                        # Not a retry of the same request — a new browser. The
                        # wall counts per session, so every route staying blocked
                        # says this session is spent, not that the posting is
                        # unreachable. Adaptive rather than a fixed relaunch
                        # interval: costs nothing on a run that is not being
                        # walled, and keeps up with one that is.
                        print("    ↻ every route walled — new browser session, one retry")
                        await browser.close()
                        browser, page = await _new_browser(p, announce=False)
                        text = await _fetch_indeed_page(page, url, indeed_jk)
                    if not text:
                        print(f"    🚫 Indeed blocked jk={indeed_jk} in a fresh session too. "
                              f"(Tip: Open URL in browser and save HTML to 00_saved/local_html/ for 100% extraction)")
                        continue
                else:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(5000) # Give it 5s to render JS/SPA content
                    
                    try:
                        btns = await page.query_selector_all("button")
                        for btn in btns:
                            b_text = await btn.inner_text()
                            if b_text and any(w in b_text.lower() for w in ["accept", "agree", "allow"]):
                                await btn.click()
                                await page.wait_for_timeout(1000)
                                break
                    except Exception:
                        pass

                    text = await page.evaluate("document.body.innerText")
                    text = text.strip() if text else ""
                    
                    if len(text) < 100:
                        print("    ⚠ Page content seems too short or blocked.")
                        continue

                    blocked = looks_blocked(text)
                    if blocked:
                        print(f"    🚫 Blocked by an anti-bot check ({blocked!r}) — no job data on this page.")
                        continue

                print("    Processing text with the LLM...")
                job_data = extract_job_from_text(text)
                
                if job_data and job_data.get("title") and job_data.get("description"):
                    job_data["url"] = url
                    job_data["source"] = get_source_key(url)
                    job_data["source_site"] = get_source_site(url)
                    job_data["scraped_at"] = datetime.now().isoformat()
                    job_data["snippet"] = job_data["description"][:500]
                    jobs.append(job_data)
                    print(f"    ✓ Extracted: {job_data.get('title')} at {job_data.get('company')}")
                    
                    # Save progressively
                    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                        json.dump(jobs, f, indent=2, ensure_ascii=False)
                else:
                    # Distinguish "the model gave us nothing" from "the model
                    # gave us a well-formed but empty object", which is what it
                    # returns for an interstitial that slipped past
                    # looks_blocked — the difference decides whether to widen
                    # BLOCK_MARKERS or to look at the prompt.
                    if isinstance(job_data, dict) and not any(
                        (job_data.get(k) or "").strip()
                        for k in ("title", "company", "description")
                    ):
                        print(f"    ✗ Model returned an empty object — the page "
                              f"({len(text)} chars) probably had no posting on it. "
                              f"First 80 chars: {text[:80]!r}")
                    else:
                        print("    ✗ Failed to extract structured job data.")

            except Exception as e:
                print(f"    ✗ Error scraping {url}: {e}")
                
        await browser.close()
        
    return jobs

def main():
    # ── File lock: prevent concurrent access to url_list_jobs.json ──
    lock = _try_acquire_lock()
    if lock is None:
        print("⚠ Another process is already using url_list_jobs.json (scrape or analysis).")
        print("  Wait for it to finish before running again.")
        sys.exit(2)  # non-zero so the WebUI surfaces the contention as an error

    if not os.path.exists(URL_LIST_FILE):
        print(f"File not found: {URL_LIST_FILE}")
        lock.close()
        return

    with open(URL_LIST_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract all http/https URLs
    urls = re.findall(r'(https?://[^\s)\]]+)', content)

    # De-duplicate using normalized URL (strips tracking params, normalizes case/slash)
    # so "indeed.com/viewjob?jk=abc&from=xxx" and "indeed.com/viewjob?jk=abc" match
    seen = set()
    unique_urls = []
    removed = 0
    for u in urls:
        key = normalize_url(u)
        if key not in seen:
            seen.add(key)
            unique_urls.append(u)
        else:
            removed += 1

    unique_urls, skipped = drop_dropped_sources(unique_urls)

    print(f"Found {len(urls)} URLs in url-list.md")
    if skipped:
        print(f"  → Skipped {len(skipped)} URL(s) from a dropped source (config.yaml dropped_sources)")
    if removed:
        print(f"  → Removed {removed} duplicate(s) after URL normalization (tracking params stripped, case/slash normalized)")
    print(f"  → {len(unique_urls)} unique URLs to process")
    
    if unique_urls:
        asyncio.run(scrape_urls(unique_urls))
        print("\nDone.")
    else:
        print("No URLs found in the markdown file.")

    lock.close()

if __name__ == "__main__":
    main()
