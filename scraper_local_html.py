"""Extract postings from job pages saved out of a browser.

The manual route for pages the network path cannot reach. Indeed answers a
signed-out /viewjob with a sign-in wall (see scraper_url_list.looks_blocked),
and no amount of retrying from here gets past it — but the page renders fine
in a browser that is logged in, and "Save page as… → Web Page, HTML only"
puts the whole posting on disk.

Four faults fixed on 2026-09-11, any one of which made this route silently
do nothing:

  * It globbed 00_saved/*.html while the WebUI told the user to save into
    00_saved/local_html/. Files put where the instructions said were never
    read, and the run reported "No .html files found".

  * It POSTed to localhost:11434 directly — the same fault removed from
    scraper_url_list on 2026-08-03. That meant no FALLBACK_PROVIDERS and no
    key_quarantine, and every extraction pinned to a local 26B model at a
    median 107s. It now shares that module's extractor.

  * It imported html2text, which is not in requirements.txt and is not
    installed — so even a correctly placed file would have died at import.
    BeautifulSoup is already a declared dependency, and its get_text gives
    the same shape of text as the document.body.innerText the network path
    feeds the extractor, which is what that prompt is tuned for.

  * It wrote url: "" on every job, so nothing downstream could join or
    dedupe the row against the posting it came from. The saved HTML carries
    its own canonical URL; that is now read out of it.

Nothing ran this module either — run_saved_chain drove the URL scrape and the
analysis and skipped this entirely. It is stage ①b there now.
"""

import os
import re
import glob
import json
from datetime import datetime

from bs4 import BeautifulSoup

from scraper_url_list import extract_job_from_text, looks_blocked, get_source_key, get_source_site

SAVED_DIR = os.path.join(os.path.dirname(__file__), "00_saved")
LOCAL_HTML_DIR = os.path.join(SAVED_DIR, "local_html")
OUTPUT_FILE = os.path.join(SAVED_DIR, "local_html_jobs.json")

# "Web Page, complete" saves the assets beside the HTML in a _files/ directory;
# only the .html itself is a posting.
_ASSET_DIR_RE = re.compile(r"_files[/\\]")

_CANONICAL_RES = (
    re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', re.I),
    re.compile(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']', re.I),
    re.compile(r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    # Chrome and Firefox both stamp the source URL into the saved file.
    re.compile(r'<!--\s*saved from url=\(\d+\)(\S+)\s*-->', re.I),
)


def html_files() -> list[str]:
    """Every saved page under the directory the WebUI names.

    Recursive, so a folder per site or per day still works, and sorted so a
    run's log reads in a stable order.

    Only that directory. The old glob also swept 00_saved/*.html, whose one
    hit on this machine is a saved LinkedIn tracker page — a model call spent
    on a list of jobs, not a posting. A save that lands anywhere else is an
    accident, and paying to extract accidents is how the spend guards get
    undermined.
    """
    found = glob.glob(os.path.join(LOCAL_HTML_DIR, "**", "*.html"), recursive=True)
    found += glob.glob(os.path.join(LOCAL_HTML_DIR, "**", "*.htm"), recursive=True)
    return sorted({f for f in found if not _ASSET_DIR_RE.search(f)})


def source_url(html: str) -> str:
    """The posting's own URL, so the row can be joined and deduped.

    (company, title) is not unique — two postings at one company share it, and
    the same posting re-saved would look like a second job. The URL is what
    run.py merges on.
    """
    for pattern in _CANONICAL_RES:
        m = pattern.search(html)
        if m:
            return m.group(1).strip()
    return ""


def page_text(html: str) -> str:
    """The visible text, as close as possible to document.body.innerText.

    Script and style bodies come out of get_text() as source code otherwise,
    and a saved Indeed page carries tens of kilobytes of it — enough to fill
    the extractor's 15,000-character window before the posting starts.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    body = soup.body or soup
    return body.get_text("\n", strip=True)


def main():
    files = html_files()
    if not files:
        print(f"No saved pages in {LOCAL_HTML_DIR}/ — nothing to do.")
        return

    # Append rather than replace: a second run over a folder that has grown by
    # one page must not throw away the extractions already paid for.
    jobs = []
    seen = set()
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                jobs = json.load(f)
            seen = {j.get("url") for j in jobs if j.get("url")}
            print(f"Loaded {len(jobs)} existing jobs from {OUTPUT_FILE}")
        except Exception:
            jobs = []

    print(f"Found {len(files)} saved page(s).")

    for filepath in files:
        name = os.path.relpath(filepath, SAVED_DIR)
        print(f"Processing {name}...")
        try:
            with open(filepath, encoding="utf-8", errors="replace") as f:
                html_content = f.read()
        except OSError as e:
            print(f"  ✗ could not read it ({e})")
            continue

        url = source_url(html_content)
        if url and url in seen:
            print(f"  ⏭ already extracted ({url})")
            continue

        text_content = page_text(html_content)
        if not text_content:
            print("  ✗ nothing left after converting the HTML to text")
            continue

        # A saved wall is still a wall. Extracting it would spend a model call
        # to produce the empty object the caller then has to reject.
        blocked = looks_blocked(text_content)
        if blocked:
            print(f"  🚫 this page is an interstitial, not a posting ({blocked}) — "
                  f"re-save it from a logged-in browser")
            continue

        job_data = extract_job_from_text(text_content)
        if not (job_data and job_data.get("title") and job_data.get("description")):
            print(f"  ✗ failed to extract a posting from {name}")
            continue

        job_data["url"] = url
        job_data["source"] = get_source_key(url) if url else "local_html"
        job_data["source_site"] = get_source_site(url) if url else "Local HTML"
        job_data["saved_html"] = name
        job_data["scraped_at"] = datetime.now().isoformat()
        job_data["snippet"] = job_data.get("description", "")[:500]
        jobs.append(job_data)
        if url:
            seen.add(url)
        else:
            # Without one the row cannot be deduped on a re-run, so say so
            # rather than letting a duplicate appear later as a scraper bug.
            print("  ⚠ no canonical URL in this file — the row cannot be deduped")
        print(f"  ✓ Extracted: {job_data.get('title')} at {job_data.get('company')}")

        # Progressively, so a crash twenty pages in does not lose the first
        # nineteen extractions.
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(jobs)} jobs to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
