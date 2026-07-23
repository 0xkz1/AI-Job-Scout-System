#!/usr/bin/env python3
"""Debug script: navigate to LinkedIn jobs-tracker and dump HTML for selector analysis."""
import asyncio
import json
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parent
STATE_FILE = PROJECT_ROOT / "cookies" / "linkedin_cookies.state"
DEBUG_DIR = PROJECT_ROOT / "10_output" / "_debug"


async def main():
    os.makedirs(DEBUG_DIR, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )

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

        if STATE_FILE.exists():
            context_kwargs["storage_state"] = str(STATE_FILE)
            print(f"  → Loading LinkedIn session from {STATE_FILE}")

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        # 1. Check login on public page
        print("\n1. Checking login on /jobs/search/ ...")
        await page.goto(
            "https://www.linkedin.com/jobs/search/?keywords=software&location=UK",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)
        content = await page.content()
        has_results = "jobs-search-results" in content or "job-card" in content or "/jobs/view" in content
        print(f"   Login valid: {has_results}")
        print(f"   URL: {page.url}")

        if not has_results:
            print("   ✗ Not logged in. Aborting.")
            await browser.close()
            return

        # 2. Navigate to jobs-tracker
        print("\n2. Navigating to /jobs-tracker/ ...")
        await page.goto(
            "https://www.linkedin.com/jobs-tracker/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(8000)  # Give SPA plenty of time

        tracker_url = page.url
        tracker_content = await page.content()
        print(f"   URL: {tracker_url}")
        print(f"   Content length: {len(tracker_content)} chars")

        # Save HTML
        html_path = DEBUG_DIR / "jobs_tracker_live.html"
        with open(html_path, "w") as f:
            f.write(tracker_content)
        print(f"   Saved HTML to {html_path}")

        # Screenshot
        ss_path = DEBUG_DIR / "jobs_tracker_live.png"
        await page.screenshot(path=str(ss_path), full_page=True)
        print(f"   Screenshot: {ss_path}")

        # 3. Try to find job-related elements
        print("\n3. Searching for job-related elements ...")

        # Check for common selectors
        selectors_to_try = [
            "a[href*='/jobs/view/']",
            "a[href*='/jobs/search/']",
            "div[class*='job']",
            "div[class*='saved']",
            "div[class*='tracker']",
            "div[class*='card']",
            "li[class*='job']",
            "article",
            "div[data-test-id]",
            "div[data-id]",
            "a[data-control-name]",
            "section[class*='jobs']",
            "div[class*='application']",
            "div[class*='listing']",
            "div[class*='my-items']",
            "div[class*='my-jobs']",
            "div.jobs-my-jobs",
            "div.jobs-saved-jobs",
            "div.jobs-tracker",
            "div.artdeco-list",
            "li.artdeco-list__item",
        ]

        for selector in selectors_to_try:
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    print(f"   ✓ {selector}: {len(elements)} elements found")
                    # Get first element's outer HTML for structure analysis
                    if len(elements) > 0:
                        first_html = await elements[0].evaluate("el => el.outerHTML.substring(0, 500)")
                        print(f"     First element: {first_html[:200]}...")
            except Exception:
                pass

        # 4. Also check for tab/list elements
        print("\n4. Checking for tabs and lists ...")
        tab_selectors = [
            "artdeco-tab[role='tab']",
            "button[role='tab']",
            "a[role='tab']",
            "div[role='tablist']",
            "artdeco-tablist",
        ]
        for selector in tab_selectors:
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    texts = []
                    for el in elements[:5]:
                        text = await el.inner_text()
                        texts.append(text.strip())
                    print(f"   ✓ {selector}: {len(elements)} elements — {texts}")
            except Exception:
                pass

        # 5. Check URL for redirect
        print(f"\n5. Final URL: {page.url}")
        if "login" in page.url.lower() or "authwall" in page.url.lower():
            print("   ⚠ Page redirected to login/authwall!")
        elif "404" in tracker_content.lower() or "not-found" in tracker_content.lower():
            print("   ⚠ Page appears to be a 404!")

        # 6. Check for "Saved" text on page
        print("\n6. Checking for 'Saved' text on page ...")
        try:
            body_text = await page.inner_text("body")
            # Find lines containing "saved" or "Saved"
            lines = [l.strip() for l in body_text.split("\n") if "saved" in l.lower() or "applied" in l.lower()]
            for line in lines[:10]:
                print(f"   → {line[:100]}")
        except Exception as e:
            print(f"   Error: {e}")

        await browser.close()

    print("\n✅ Debug complete. Check output/_debug/ for HTML and screenshot.")


if __name__ == "__main__":
    asyncio.run(main())
