"""
LinkedIn Job Scraper — guest endpoints, no login
================================================
LinkedIn serves its job listings to logged-out visitors through two endpoints
that need no cookies, no session and no browser:

    /jobs-guest/jobs/api/seeMoreJobPostings/search   -> 10 result cards of HTML
    /jobs-guest/jobs/api/jobPosting/<jobId>          -> the full posting

scraper_linkedin.py drives the authenticated /jobs/search/ UI instead, which is
why it produced nothing on the nightly cron for weeks: the unattended run has no
valid session, and the auto-login path lands on a checkpoint ("Login may have
failed (no redirect to feed/jobs)"). The guest endpoints have no such failure
mode, so this module replaces it for the automated search; scraper_saved.py
still uses the authenticated scraper for the user's own saved jobs, which really
do require the account.

Plain HTTP — no Playwright. A full run is ~110 search requests plus one detail
request per NEW posting, well inside the 1500s per-site cron budget.
"""

import os
import re
import sys
import time
import random
import asyncio
from datetime import datetime
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
JOB_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

# The guest search endpoint pages in fixed steps of 10, regardless of how many
# cards it actually returns (a short page still means "ask for the next 10").
PAGE_SIZE = 10

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Politeness / rate limiting. LinkedIn answers a steady trickle indefinitely but
# returns 429 to bursts, so every request pays a randomised pause and a 429 is
# backed off rather than retried immediately.
MIN_DELAY = float(os.environ.get("LINKEDIN_GUEST_DELAY", "1.5"))
MAX_DELAY = MIN_DELAY + 1.0
MAX_RETRIES = 4


def _sleep():
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


def _get(url: str, params: dict | None = None) -> str | None:
    """GET with backoff. Returns the body, or None once the retries are spent.

    429 is the expected failure here, not an error: it means the pace was too
    high, so the wait doubles each time and the caller keeps its place.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-GB,en;q=0.9",
    }
    backoff = 5.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
        except requests.RequestException as e:
            print(f"    ⚠ request failed ({type(e).__name__}), retry {attempt}/{MAX_RETRIES}")
            time.sleep(backoff)
            backoff *= 2
            continue

        if resp.status_code == 200:
            return resp.text
        if resp.status_code == 404:
            return None  # posting withdrawn — not worth retrying
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = float(resp.headers.get("Retry-After") or backoff)
            print(f"    ⚠ HTTP {resp.status_code} — waiting {wait:.0f}s "
                  f"(retry {attempt}/{MAX_RETRIES})")
            time.sleep(wait)
            backoff *= 2
            continue
        print(f"    ⚠ HTTP {resp.status_code} — giving up on this request")
        return None
    return None


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def _job_id_from_card(card) -> str:
    """LinkedIn puts the posting id in data-entity-urn on the card wrapper; the
    href carries it too but only as a trailing number on a slug that changes."""
    urn = card.get("data-entity-urn") or ""
    m = re.search(r"(\d+)$", urn)
    if m:
        return m.group(1)
    link = card.select_one("a[href*='/jobs/view/']")
    if link:
        m = re.search(r"/jobs/view/[^/?]*?(\d+)", link.get("href", ""))
        if m:
            return m.group(1)
    return ""


def _parse_search_html(html: str) -> list[dict]:
    """Cards -> partial job dicts (no description yet)."""
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("div.base-card, div.job-search-card"):
        job_id = _job_id_from_card(card)
        title = _text(card.select_one("h3.base-search-card__title"))
        if not job_id or not title:
            continue
        company = _text(card.select_one("h4.base-search-card__subtitle"))
        location = _text(card.select_one("span.job-search-card__location"))
        salary = _text(card.select_one("span.job-search-card__salary-info"))
        posted = ""
        time_el = card.select_one("time")
        if time_el:
            posted = time_el.get("datetime", "") or _text(time_el)
        jobs.append({
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "snippet": "",
            "description": "",
            # Canonical form: the slug and tracking params in the card href vary
            # per request, which would defeat URL-based dedup downstream.
            "url": f"https://www.linkedin.com/jobs/view/{job_id}",
            "job_id": job_id,
            "posted_date": posted,
            "source": "linkedin",
            "type": "auto",
            "source_site": "LinkedIn",
            "scraped_at": datetime.now().isoformat(),
        })
    return jobs


def _parse_job_html(html: str) -> dict:
    """Detail endpoint -> description plus the criteria LinkedIn exposes
    (seniority, employment type). Returns {} when the body has no description,
    which is what a withdrawn or region-blocked posting looks like."""
    soup = BeautifulSoup(html, "html.parser")
    desc_el = soup.select_one("div.description__text, div.show-more-less-html__markup")
    if not desc_el:
        return {}
    for junk in desc_el.select("button, icon, .show-more-less-html__button"):
        junk.decompose()
    description = desc_el.get_text("\n", strip=True)
    description = re.sub(r"\n{3,}", "\n\n", description).strip()
    if not description:
        return {}

    out = {"description": description}
    for item in soup.select("li.description__job-criteria-item"):
        label = _text(item.select_one("h3.description__job-criteria-subheader")).lower()
        value = _text(item.select_one("span.description__job-criteria-text"))
        if not value:
            continue
        if "seniority" in label:
            out["seniority"] = value
        elif "employment type" in label:
            out["employment_type"] = value
        elif "job function" in label:
            out["job_function"] = value
        elif "industr" in label:
            out["industry"] = value
    return out


def job_id_from_url(url: str) -> str:
    """The posting id out of any LinkedIn job URL, or "".

    Handles the two shapes the user pastes: the bare /jobs/view/<id>/ and the
    slugged /jobs/view/some-title-at-company-<id>?refId=... form.
    """
    if "linkedin.com" not in (url or "").lower():
        return ""
    m = re.search(r"/jobs/view/(?:[^/?#]*?-)?(\d{6,})", url)
    return m.group(1) if m else ""


def fetch_one(url: str) -> dict | None:
    """One pasted LinkedIn URL -> a full job dict, with no LLM involved.

    scraper_url_list.py reads whatever the page renders and asks a local 26B
    reasoning model to pull the fields back out of the prose — measured at ~107s
    per URL on 2026-08-03, with the slowest exceeding its own 120s timeout and
    being discarded. LinkedIn already publishes the same fields as markup on its
    logged-out endpoint, so for these URLs the model buys nothing: this is the
    same request the search scraper makes, at ~2s.
    """
    job_id = job_id_from_url(url)
    if not job_id:
        return None
    html = _get(JOB_URL.format(job_id=job_id))
    if not html:
        return None
    detail = _parse_job_html(html)
    if not detail:
        return None

    soup = BeautifulSoup(html, "html.parser")
    title = _text(soup.select_one("h2.topcard__title, h1.topcard__title, .top-card-layout__title"))
    company = _text(soup.select_one("a.topcard__org-name-link, span.topcard__flavor"))
    location = _text(soup.select_one("span.topcard__flavor.topcard__flavor--bullet"))
    if not title:
        return None

    job = {
        "title": title,
        "company": company,
        "location": location,
        "salary": "",
        "snippet": detail["description"][:500],
        "url": f"https://www.linkedin.com/jobs/view/{job_id}",
        "job_id": job_id,
        "source": "linkedin",
        "source_site": "LinkedIn",
        "type": "manual",
        "scraped_at": datetime.now().isoformat(),
    }
    job.update(detail)
    return job


def _location_params(location: str) -> dict:
    """Config locations are bare city names plus the pseudo-location 'Remote'.
    Remote is not a place LinkedIn understands, it is the f_WT=2 workplace-type
    filter over a real geography — passing the word through as a location
    returns the handful of postings with 'Remote' in their office name."""
    loc = (location or "").strip()
    if loc.lower() == "remote":
        return {"location": "United Kingdom", "f_WT": "2"}
    if not loc:
        return {"location": "United Kingdom"}
    return {"location": loc}


def search(keyword: str, location: str = "", max_pages: int = 3) -> list[dict]:
    """One keyword x location search, without descriptions."""
    found: list[dict] = []
    seen_ids: set[str] = set()

    print(f"🔍 LinkedIn(guest): searching '{keyword}' in '{location or 'UK'}'...")
    for page in range(max_pages):
        params = {"keywords": keyword, "start": page * PAGE_SIZE}
        params.update(_location_params(location))
        html = _get(SEARCH_URL, params)
        _sleep()
        if not html:
            break
        cards = _parse_search_html(html)
        if not cards:
            break
        new = [c for c in cards if c["job_id"] not in seen_ids]
        for c in new:
            seen_ids.add(c["job_id"])
        found.extend(new)
        # A page that adds nothing new means the endpoint has started repeating
        # itself, which is how it signals the end of the result set.
        if not new:
            break

    print(f"  → {len(found)} cards")
    return found


# The shared (title, company) description cache mixes sources, and Adzuna's API
# caps its description at 500 characters — 706 of the cached entries are exactly
# that long. Adopting one of those in place of LinkedIn's full text would swap a
# 7,000-character posting for a 500-character stub and score it as if complete,
# so a cached description at or under this length is treated as a miss. The cost
# of being wrong is one extra request.
_CACHE_MIN_CHARS = 600


def fill_descriptions(jobs: list[dict], cache: dict | None = None) -> None:
    """Fetch the full text for each job, in place. Cache hits by (title,
    company) skip the request entirely — the same mechanism the other scrapers
    use, so a posting already scraped elsewhere costs nothing here."""
    cache = cache if cache is not None else {}
    fetched = skipped = dropped = 0

    for job in jobs:
        key = (job.get("title", "").strip().lower(), job.get("company", "").strip().lower())
        cached = cache.get(key)
        if cached and len(cached.get("description") or "") >= _CACHE_MIN_CHARS:
            job["description"] = cached["description"]
            job["snippet"] = cached.get("snippet") or cached["description"][:300]
            if "analysis" in cached:
                job["analysis"] = cached["analysis"]
            skipped += 1
            continue

        html = _get(JOB_URL.format(job_id=job["job_id"]))
        _sleep()
        detail = _parse_job_html(html) if html else {}
        if not detail:
            dropped += 1
            continue
        job.update(detail)
        job["snippet"] = job["description"][:300]
        cache[key] = job
        fetched += 1
        if fetched % 10 == 0:
            print(f"    → fetched {fetched} descriptions...")

    print(f"  📄 descriptions: {fetched} fetched, {skipped} cache hits, "
          f"{dropped} unavailable (withdrawn/blocked)")


def scrape_linkedin_guest_all(config: dict) -> list[dict]:
    """Every keyword x location in config, deduped by posting id."""
    from selection import max_pages_for
    from scraper_helper import load_description_cache

    keywords = config.get("keywords", [])
    locations = config.get("locations", [""])
    max_pages = max_pages_for("linkedin", config)

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    for kw in keywords:
        for loc in locations:
            for job in search(kw, loc, max_pages=max_pages):
                if job["job_id"] in seen_ids:
                    continue
                seen_ids.add(job["job_id"])
                all_jobs.append(job)

    print(f"\n  🔗 {len(all_jobs)} unique postings before descriptions")
    fill_descriptions(all_jobs, load_description_cache())

    # A posting with no description cannot be scored (review_score treats a
    # missing description as void), so it is dead weight in the pipeline.
    all_jobs = [j for j in all_jobs if j.get("description")]

    from scraper_indeed import filter_jobs_by_keywords
    all_jobs = filter_jobs_by_keywords(all_jobs, keywords)

    print(f"  ✓ Total: {len(all_jobs)} jobs from LinkedIn (guest)")
    return all_jobs


async def scrape_linkedin_all(config: dict) -> list[dict]:
    """Async shim so run.py can await this exactly like the other scrapers.
    The work is blocking HTTP, so it runs in a worker thread rather than
    pretending to be async."""
    return await asyncio.to_thread(scrape_linkedin_guest_all, config)


# --- CLI ---
if __name__ == "__main__":
    import yaml

    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    if "--dry-run" in sys.argv:
        # One search, no descriptions — enough to prove the endpoints answer.
        kw = cfg.get("keywords", ["Designer"])[0]
        loc = cfg.get("locations", ["Edinburgh"])[0]
        for j in search(kw, loc, max_pages=1):
            print(f"  {j['title']} @ {j['company']} — {j['location']} — {j['url']}")
        sys.exit(0)

    jobs = scrape_linkedin_guest_all(cfg)
    from scraper_indeed import save_jobs
    save_jobs(jobs)
    print(f"\n✅ Done! {len(jobs)} jobs scraped from LinkedIn (guest).")
