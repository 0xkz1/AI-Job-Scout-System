import os
import re
import json
import asyncio
import requests
import fcntl
from datetime import datetime
from urllib.parse import urlparse
from playwright.async_api import async_playwright

SAVED_DIR = os.path.join(os.path.dirname(__file__), "00_saved")
URL_LIST_FILE = os.path.join(SAVED_DIR, "url-list.md")
OUTPUT_FILE = os.path.join(SAVED_DIR, "url_list_jobs.json")

OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma-4-26b-a4b-it-gguf")


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
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant that outputs only valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }
    
    try:
        resp = requests.post(OLLAMA_ENDPOINT, json=payload, timeout=120)
        resp.raise_for_status()
        # The Ollama API might return either 'message.content' or just 'response' depending on the endpoint used.
        # Since we use /api/generate, it returns 'response' field.
        data = resp.json()
        content = data.get("response", "")
        if not content:
            # Fallback for /api/chat format just in case
            content = data.get("message", {}).get("content", "")
            
        matches = list(re.finditer(r'\{.*\}', content, re.DOTALL))
        for match in reversed(matches):
            try:
                extracted = json.loads(match.group())
                return extracted
            except json.JSONDecodeError:
                continue
    except Exception as e:
        print(f"    Error calling Ollama: {e}")
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
        # Indeed
        "from", "SP", "pos", "sid", "tk", "rq", "rl", "vjs", "iaai", "ad",
        # LinkedIn
        "refId", "trk", "trkInfo", "utm_source", "utm_medium", "utm_campaign",
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
    if not urls_to_scrape:
        print("No new URLs to scrape.")
        return jobs

    print(f"Found {len(urls_to_scrape)} new URLs to scrape.")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()

        for i, url in enumerate(urls_to_scrape, 1):
            print(f"\n[{i}/{len(urls_to_scrape)}] Fetching: {url}")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(5000) # Give it 5s to render JS/SPA content
                
                # Try to reject/accept cookies if popups appear (generic approach)
                try:
                    btns = await page.query_selector_all("button")
                    for btn in btns:
                        text = await btn.inner_text()
                        if text and any(w in text.lower() for w in ["accept", "agree", "allow"]):
                            await btn.click()
                            await page.wait_for_timeout(1000)
                            break
                except Exception:
                    pass

                # Get entire page text
                text = await page.evaluate("document.body.innerText")
                text = text.strip() if text else ""
                
                if len(text) < 100:
                    print("    ⚠ Page content seems too short or blocked.")
                    continue

                print("    Processing text with Ollama...")
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
        return

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

    print(f"Found {len(urls)} URLs in url-list.md")
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
