#!/usr/bin/env python3
"""Debug script: try multiple LinkedIn saved-jobs URLs to find the correct one."""
import asyncio
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

        # Check login first
        print("\n0. Checking login on /jobs/search/ ...")
        for attempt in range(3):
            try:
                await page.goto(
                    "https://www.linkedin.com/jobs/search/?keywords=software&location=UK",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                break
            except Exception as e:
                print(f"   Attempt {attempt+1} failed: {e}")
                await page.wait_for_timeout(5000)
        await page.wait_for_timeout(3000)
        content = await page.content()
        has_results = "jobs-search-results" in content or "job-card" in content or "/jobs/view" in content
        print(f"   Login valid: {has_results}")

        if not has_results:
            print("   ✗ Not logged in. Aborting.")
            await browser.close()
            return

        # Try multiple URLs
        urls_to_try = [
            "https://www.linkedin.com/my-items/saved-jobs/",
            "https://www.linkedin.com/jobs/saved/",
            "https://www.linkedin.com/jobs/collections/",
            "https://www.linkedin.com/jobs-tracker/",
            "https://www.linkedin.com/jobs/my-items/saved-jobs/",
        ]

        for i, url in enumerate(urls_to_try, 1):
            print(f"\n{i}. Trying {url} ...")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(5000)

                final_url = page.url
                page_content = await page.content()
                content_len = len(page_content)

                # Is it a login redirect?
                is_login = "login" in final_url.lower() or "authwall" in page_content.lower() or "session_redirect" in page_content.lower()
                # Is it 404?
                is_404 = "not-found-404" in page_content.lower() or "not found" in page_content.lower()[:5000]
                # Has job cards?
                has_job_cards = "job-card" in page_content.lower() or "jobs-view" in page_content.lower() or "/jobs/view/" in page_content.lower()
                # Has "saved" text?
                body_text = ""
                try:
                    body_text = await page.inner_text("body")
                except Exception:
                    pass
                has_saved_text = "saved" in body_text.lower()[:2000]

                print(f"   URL: {final_url}")
                print(f"   Content: {content_len} chars")
                print(f"   Login redirect: {is_login}")
                print(f"   404: {is_404}")
                print(f"   Job cards: {has_job_cards}")
                print(f"   'Saved' text: {has_saved_text}")

                if has_saved_text and not is_login and not is_404:
                    # This might be the right page — save HTML and screenshot
                    safe_name = url.replace("https://www.linkedin.com/", "").replace("/", "_").strip("_")
                    html_path = DEBUG_DIR / f"saved_{safe_name}.html"
                    with open(html_path, "w") as f:
                        f.write(page_content)
                    print(f"   📸 Saved HTML to {html_path}")

                    ss_path = DEBUG_DIR / f"saved_{safe_name}.png"
                    await page.screenshot(path=str(ss_path), full_page=True)
                    print(f"   📸 Screenshot: {ss_path}")

                    # Try to find job elements
                    selectors = [
                        "a[href*='/jobs/view/']",
                        "div[class*='job']",
                        "div[class*='saved']",
                        "li[class*='job']",
                        "div[class*='card']",
                        "div[data-test-id]",
                        "artdeco-tab[role='tab']",
                        "button[role='tab']",
                    ]
                    for sel in selectors:
                        try:
                            elements = await page.query_selector_all(sel)
                            if elements:
                                print(f"   ✓ {sel}: {len(elements)} elements")
                        except Exception:
                            pass

                # Save first 2000 chars of body text for debugging
                print(f"   Body text (first 500): {body_text[:500].strip()[:300]}")

            except Exception as e:
                print(f"   ✗ Error: {e}")

        await browser.close()

    print("\n✅ Debug complete.")


if __name__ == "__main__":
    asyncio.run(main())
