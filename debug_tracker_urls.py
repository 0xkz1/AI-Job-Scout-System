#!/usr/bin/env python3
"""Last-resort debug: try /jobs-tracker without trailing slash and other variants."""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parent
STATE_FILE = PROJECT_ROOT / "cookies" / "linkedin_cookies.state"
DEBUG_DIR = PROJECT_ROOT / "10_output" / "_debug"


async def main():
    os.makedirs(DEBUG_DIR, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context_kwargs = dict(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-GB",
            timezone_id="Europe/London",
        )
        if STATE_FILE.exists():
            context_kwargs["storage_state"] = str(STATE_FILE)
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        # Check login
        print("0. Login check...")
        for attempt in range(3):
            try:
                await page.goto("https://www.linkedin.com/jobs/search/?keywords=software&location=UK", wait_until="domcontentloaded", timeout=30000)
                break
            except Exception as e:
                print(f"   retry {attempt+1}: {e}")
                await asyncio.sleep(5)
        await page.wait_for_timeout(3000)
        content = await page.content()
        logged_in = "job-card" in content or "/jobs/view" in content
        print(f"   Logged in: {logged_in}")

        if not logged_in:
            print("   Aborting.")
            await browser.close()
            return

        # Try jobs-tracker variants
        urls = [
            "https://www.linkedin.com/jobs-tracker",
            "https://www.linkedin.com/jobs-tracker/",
            "https://www.linkedin.com/jobs-tracker/?_l=en_US",
            # Maybe it's under /my-items/
            "https://www.linkedin.com/my-items/jobs-tracker/",
            # Or the "Job Application Tracker"
            "https://www.linkedin.com/jobs/application-tracker/",
            "https://www.linkedin.com/jobs/applied/",
        ]

        for url in urls:
            print(f"\n→ {url}")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(5000)
                final_url = page.url
                content = await page.content()
                is_404 = "not-found-404" in content.lower()
                is_login = "session_redirect" in content
                body = ""
                try:
                    body = await page.inner_text("body")
                except Exception:
                    pass

                print(f"  URL: {final_url}")
                print(f"  404: {is_404}, Login redirect: {is_login}")
                print(f"  Body (200): {body[:200].strip()[:150]}")

                # Look for job cards
                for sel in ["a[href*='/jobs/view/']", "div[class*='job-card']", "div[class*='tracker']", "div[class*='saved']"]:
                    try:
                        els = await page.query_selector_all(sel)
                        if els:
                            print(f"  ✓ {sel}: {len(els)} elements")
                    except Exception:
                        pass

                if not is_404 and not is_login:
                    safe = url.replace("https://www.linkedin.com/", "").replace("/", "_").strip("_")
                    html_path = DEBUG_DIR / f"tracker_{safe}.html"
                    with open(html_path, "w") as f:
                        f.write(content)
                    ss_path = DEBUG_DIR / f"tracker_{safe}.png"
                    await page.screenshot(path=str(ss_path), full_page=True)
                    print(f"  📸 Saved HTML + screenshot")

            except Exception as e:
                print(f"  ✗ Error: {e}")

        await browser.close()
    print("\n✅ Done")


if __name__ == "__main__":
    asyncio.run(main())
