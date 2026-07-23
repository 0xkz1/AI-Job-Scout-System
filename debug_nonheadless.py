#!/usr/bin/env python3
"""Debug: try /jobs-tracker/ with non-headless browser via xvfb-run.
Also intercept network requests to find the API endpoint that serves saved jobs data.
"""
import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parent
STATE_FILE = PROJECT_ROOT / "cookies" / "linkedin_cookies.state"
DEBUG_DIR = PROJECT_ROOT / "10_output" / "_debug"


async def main():
    os.makedirs(DEBUG_DIR, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # Non-headless to bypass bot detection
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        context_kwargs = dict(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-GB",
            timezone_id="Europe/London",
        )
        if STATE_FILE.exists():
            context_kwargs["storage_state"] = str(STATE_FILE)
            print(f"  → Loading session from {STATE_FILE}")
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        # Capture all network responses
        api_responses = []

        def handle_response(response):
            url = response.url
            # Capture LinkedIn API calls
            if "linkedin" in url and any(kw in url for kw in ["/api/", "/voyager/", "/graphql", "jobs-tracker", "saved"]):
                try:
                    status = response.status
                    content_type = response.headers.get("content-type", "")
                    if "json" in content_type or "graphql" in url:
                        body = response.text()
                        api_responses.append({
                            "url": url,
                            "status": status,
                            "content_type": content_type,
                            "body_length": len(body),
                            "body_preview": body[:500] if body else "",
                        })
                        print(f"  📡 API: [{status}] {url[:120]}")
                except Exception:
                    pass

        page.on("response", handle_response)

        # Login check
        print("\n0. Login check...")
        await page.goto("https://www.linkedin.com/jobs/search/?keywords=software&location=UK", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        content = await page.content()
        logged_in = "job-card" in content or "/jobs/view" in content
        print(f"   Logged in: {logged_in}")

        if not logged_in:
            print("   Aborting.")
            await browser.close()
            return

        # Navigate to /jobs-tracker/
        print("\n1. Navigating to /jobs-tracker/ (non-headless)...")
        try:
            await page.goto("https://www.linkedin.com/jobs-tracker/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(10000)  # Long wait for SPA rendering

            final_url = page.url
            page_content = await page.content()
            is_404 = "not-found-404" in page_content.lower()
            body_text = ""
            try:
                body_text = await page.inner_text("body")
            except Exception:
                pass

            print(f"   URL: {final_url}")
            print(f"   Content: {len(page_content)} chars")
            print(f"   404: {is_404}")
            print(f"   Body (300): {body_text[:300].strip()[:200]}")

            # Save HTML
            html_path = DEBUG_DIR / "tracker_nonheadless.html"
            with open(html_path, "w") as f:
                f.write(page_content)
            print(f"   📸 HTML saved: {html_path}")

            ss_path = DEBUG_DIR / "tracker_nonheadless.png"
            await page.screenshot(path=str(ss_path), full_page=True)
            print(f"   📸 Screenshot: {ss_path}")

            # Search for job elements
            for sel in [
                "a[href*='/jobs/view/']",
                "div[class*='job']",
                "div[class*='saved']",
                "div[class*='tracker']",
                "div[class*='card']",
                "li[class*='job']",
                "div[class*='application']",
                "artdeco-tab[role='tab']",
                "button[role='tab']",
            ]:
                try:
                    els = await page.query_selector_all(sel)
                    if els:
                        print(f"   ✓ {sel}: {len(els)} elements")
                        # Show first element's text
                        if len(els) > 0:
                            first_text = await els[0].inner_text()
                            print(f"     First: {first_text[:100].strip()}")
                except Exception:
                    pass

        except Exception as e:
            print(f"   ✗ Error: {e}")

        # Also try /jobs/my-items/saved-jobs/ with non-headless
        print("\n2. Navigating to /jobs/my-items/saved-jobs/ (non-headless)...")
        try:
            await page.goto("https://www.linkedin.com/jobs/my-items/saved-jobs/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(8000)

            final_url = page.url
            page_content = await page.content()
            body_text = ""
            try:
                body_text = await page.inner_text("body")
            except Exception:
                pass

            print(f"   URL: {final_url}")
            print(f"   Body (300): {body_text[:300].strip()[:200]}")

            html_path = DEBUG_DIR / "saved_nonheadless.html"
            with open(html_path, "w") as f:
                f.write(page_content)
            ss_path = DEBUG_DIR / "saved_nonheadless.png"
            await page.screenshot(path=str(ss_path), full_page=True)
            print(f"   📸 Saved HTML + screenshot")

            # Check for job card selectors
            for sel in [
                "a[href*='/jobs/view/']",
                "div[class*='job-card']",
                "div.job-card-list",
                "div.jobs-search-results-list",
                "li.jobs-search-results__list-item",
                "div.scaffold-finite-scroll__content",
            ]:
                try:
                    els = await page.query_selector_all(sel)
                    if els:
                        print(f"   ✓ {sel}: {len(els)} elements")
                except Exception:
                    pass

        except Exception as e:
            print(f"   ✗ Error: {e}")

        # Save API responses
        print(f"\n3. API responses captured: {len(api_responses)}")
        if api_responses:
            api_path = DEBUG_DIR / "api_responses.json"
            with open(api_path, "w") as f:
                json.dump(api_responses, f, indent=2, ensure_ascii=False)
            print(f"   Saved to {api_path}")
            for r in api_responses[:10]:
                print(f"   [{r['status']}] {r['url'][:100]} ({r['body_length']} bytes)")

        await browser.close()

    print("\n✅ Debug complete")


if __name__ == "__main__":
    asyncio.run(main())
