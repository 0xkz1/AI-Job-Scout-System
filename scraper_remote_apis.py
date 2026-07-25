"""
Remote-native job APIs
======================
Free, key-less JSON APIs for remote roles. These catch remote postings from
companies in countries Adzuna does not cover (Nordics, Switzerland, Luxembourg,
Belgium) because a Swedish/Swiss company hiring remote-EMEA lists here anyway.

Sources:
  - Remotive   (https://remotive.com/api/remote-jobs)   — has ?search=, remote-only
  - RemoteOK   (https://remoteok.com/api)                — all remote, client filter
  - Arbeitnow  (https://www.arbeitnow.com/api/job-board-api) — DE/EU, remote + on-site

All are inherently remote (except some Arbeitnow rows), so remote listings get a
"Remote - <region>" location so the matcher scores them as remote, not on-site.

Usage (standalone):
    python scraper_remote_apis.py
"""

import re
import time
from datetime import datetime

import requests

_UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/125.0.0.0 Safari/537.36")}


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _job(title, company, location, salary, description, url, source, remote=True):
    desc = _strip_html(description)
    # Inherently-remote rows get a "Remote" token so the matcher's remote
    # detection fires and scores by region instead of assuming on-site.
    loc = location.strip()
    if remote and "remote" not in loc.lower():
        loc = f"Remote - {loc}" if loc else "Remote"
    return {
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "location": loc,
        "salary": (salary or "").strip() if isinstance(salary, str) else "",
        "snippet": desc[:500],
        "description": desc,
        "url": url or "",
        "source": source,
        "type": "auto",
        "source_site": source.capitalize(),
        "scraped_at": datetime.utcnow().isoformat() + "Z",
    }


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(kw.lower().strip() in t for kw in keywords if kw.strip())


# ── Remotive (has server-side search) ─────────────────────────────────────
def scrape_remotive(keyword: str, limit: int = 50) -> list[dict]:
    jobs = []
    try:
        r = requests.get("https://remotive.com/api/remote-jobs",
                         params={"search": keyword, "limit": limit},
                         headers=_UA, timeout=25)
        if r.status_code != 200:
            print(f"  ⚠ Remotive '{keyword}': HTTP {r.status_code}")
            return []
        for it in r.json().get("jobs", []):
            jobs.append(_job(
                it.get("title"),
                it.get("company_name"),
                it.get("candidate_required_location") or "Worldwide",
                it.get("salary"),
                it.get("description"),
                it.get("url"),
                "remotive",
            ))
    except Exception as e:
        print(f"  ⚠ Remotive '{keyword}' error: {e}")
    print(f"  ✓ Remotive: {len(jobs)} jobs for '{keyword}'")
    return jobs


# ── RemoteOK (single feed, client-side keyword filter) ────────────────────
def scrape_remoteok(keywords: list[str]) -> list[dict]:
    jobs = []
    try:
        r = requests.get("https://remoteok.com/api", headers=_UA, timeout=25)
        if r.status_code != 200:
            print(f"  ⚠ RemoteOK: HTTP {r.status_code}")
            return []
        data = r.json()
    except Exception as e:
        print(f"  ⚠ RemoteOK error: {e}")
        return []
    for it in data:
        if not isinstance(it, dict) or it.get("legal"):
            continue  # first element is API metadata
        title = it.get("position") or it.get("title") or ""
        tags = " ".join(it.get("tags", []) or [])
        if not _matches_keywords(f"{title} {tags}", keywords):
            continue
        jobs.append(_job(
            title,
            it.get("company"),
            it.get("location") or "Worldwide",
            "",
            it.get("description"),
            it.get("url") or (f"https://remoteok.com/l/{it.get('id')}" if it.get("id") else ""),
            "remoteok",
        ))
    print(f"  ✓ RemoteOK: {len(jobs)} keyword-matched jobs")
    return jobs


# ── Arbeitnow (DE/EU board, paginated, client-side filter) ────────────────
def scrape_arbeitnow(keywords: list[str], max_pages: int = 3) -> list[dict]:
    jobs = []
    for page in range(1, max_pages + 1):
        try:
            r = requests.get("https://www.arbeitnow.com/api/job-board-api",
                             params={"page": page}, headers=_UA, timeout=25)
            if r.status_code != 200:
                print(f"  ⚠ Arbeitnow p{page}: HTTP {r.status_code}")
                break
            rows = r.json().get("data", [])
        except Exception as e:
            print(f"  ⚠ Arbeitnow p{page} error: {e}")
            break
        if not rows:
            break
        for it in rows:
            title = it.get("title") or ""
            tags = " ".join(it.get("tags", []) or [])
            if not _matches_keywords(f"{title} {tags}", keywords):
                continue
            jobs.append(_job(
                title,
                it.get("company_name"),
                it.get("location") or "Europe",
                "",
                it.get("description"),
                it.get("url"),
                "arbeitnow",
                remote=bool(it.get("remote")),
            ))
        time.sleep(0.3)
    print(f"  ✓ Arbeitnow: {len(jobs)} keyword-matched jobs")
    return jobs


def scrape_remote_apis_all(config: dict) -> list[dict]:
    """Run all remote-native APIs, dedup, keyword-filter."""
    keywords = config.get("keywords", [])
    max_pages = min(config.get("max_pages_per_search", 3), 5)
    all_jobs = []
    seen = set()

    def _add(js):
        for j in js:
            key = (j["title"], j.get("company", ""), j.get("location", ""))
            if key not in seen:
                seen.add(key)
                all_jobs.append(j)

    for kw in keywords:
        _add(scrape_remotive(kw))
        time.sleep(0.3)
    _add(scrape_remoteok(keywords))
    _add(scrape_arbeitnow(keywords, max_pages=max_pages))

    # Final keyword gate (title-level) reusing the shared filter.
    from scraper_indeed import filter_jobs_by_keywords
    all_jobs = filter_jobs_by_keywords(all_jobs, keywords)
    print(f"  ✓ Remote APIs total: {len(all_jobs)} unique jobs")
    return all_jobs


# ── CLI ──
if __name__ == "__main__":
    import yaml
    import os
    cfg_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    jobs = scrape_remote_apis_all(cfg)
    print(f"\nTotal: {len(jobs)} jobs")
    for j in jobs[:10]:
        print(f"  [{j['source']}] {j['title']} @ {j['company']} — {j['location']}")
