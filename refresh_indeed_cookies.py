"""Re-save cookies/indeed_cookies.json from a browser you sign in to yourself.

Why this exists. The scrapers load that file as Playwright's storage_state, and
on 2026-09-11 it was five weeks stale and had never held a session: every
cookie in it was anonymous. Signed out, Indeed no longer answers /viewjob with
a posting or with a Cloudflare challenge — it answers with a sign-in wall, 404
characters of "Ready to take the next step? / Create an account or sign in."
On 2026-09-07 that wall came back for 27 of 33 URLs in one run.

So no amount of retrying, stealth or route-switching fixes it from here. The
session has to be a real one, and only you can create it.

    xvfb-run does NOT work for this. It needs a browser you can see and type
    into, so run it from your desktop session, not over a bare SSH shell.

This script never sees your password. It opens a browser, waits while you sign
in, and saves the resulting session. Then it proves the session works by
fetching a real posting and checking the answer is not a wall — the previous
file looked perfectly valid on disk and was worthless in practice.

    python refresh_indeed_cookies.py
    python refresh_indeed_cookies.py --jk 9ccd44268a8664fb   # verify with this posting
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import sys
from datetime import datetime

from playwright.async_api import async_playwright

from scraper_url_list import looks_blocked, _indeed_jk

ROOT = os.path.dirname(os.path.abspath(__file__))
COOKIE_FILE = os.path.join(ROOT, "cookies", "indeed_cookies.json")
URL_LIST_FILE = os.path.join(ROOT, "00_saved", "url-list.md")

SIGN_IN_URL = "https://uk.indeed.com/account/login"


def _a_jk_to_verify_with() -> str:
    """An Indeed posting from the URL list, so the check uses a page you care
    about rather than one that may have expired months ago."""
    try:
        with open(URL_LIST_FILE, encoding="utf-8") as f:
            for url in re.findall(r"https?://[^\s)\]]+", f.read()):
                jk = _indeed_jk(url)
                if jk:
                    return jk
    except OSError:
        pass
    return ""


def _backup() -> str | None:
    if not os.path.exists(COOKIE_FILE):
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = f"{COOKIE_FILE}.bak_{stamp}"
    shutil.copy2(COOKIE_FILE, dest)
    return dest


async def _verify(context, jk: str) -> bool:
    """Fetch one posting with the new session and report what came back.

    The same three routes the scraper uses, in the same order, because a
    session that only works on one of them is a session that will still fail
    the next run.
    """
    routes = [
        ("m/viewjob", f"https://uk.indeed.com/m/viewjob?jk={jk}"),
        ("rc/clk", f"https://uk.indeed.com/rc/clk?jk={jk}"),
        ("viewjob", f"https://uk.indeed.com/viewjob?jk={jk}"),
    ]
    page = await context.new_page()
    ok = False
    for label, url in routes:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
            text = (await page.evaluate("document.body.innerText") or "").strip()
        except Exception as e:
            print(f"  {label}: could not load it ({type(e).__name__})")
            continue

        blocked = looks_blocked(text)
        if blocked:
            print(f"  {label}: {blocked}, {len(text)} chars")
            continue
        desc = await page.query_selector("#jobDescriptionText, .jobsearch-JobComponent-description")
        if desc:
            print(f"  {label}: ✓ posting, description present ({len(text)} chars)")
            ok = True
        elif len(text) >= 1200:
            print(f"  {label}: ✓ posting-sized page, no description element ({len(text)} chars)")
            ok = True
        else:
            print(f"  {label}: only {len(text)} chars and no description element")
    await page.close()
    return ok


async def run(jk: str) -> int:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print("✗ No display. This needs a browser you can type into — run it from "
              "your desktop session. xvfb-run will not help: it has no screen for "
              "you to sign in on.")
        return 1

    os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context_kwargs = {
            "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "viewport": {"width": 1440, "height": 900},
            "locale": "en-GB",
            "timezone_id": "Europe/London",
        }
        # Start from whatever session exists, so a still-valid one only needs
        # confirming rather than signing in again.
        if os.path.exists(COOKIE_FILE):
            context_kwargs["storage_state"] = COOKIE_FILE
            print(f"→ Opened with the existing session from {COOKIE_FILE}")
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        await page.goto(SIGN_IN_URL, wait_until="domcontentloaded")

        print()
        print("A browser window is open on Indeed's sign-in page.")
        print("Sign in there — this script never sees what you type.")
        print("Accept the cookie banner too; the banner's own cookies are part")
        print("of the session.")
        print()
        try:
            input("When you are signed in and can see a job page, press Enter here… ")
        except EOFError:
            print("✗ No terminal to wait on. Run this interactively.")
            await browser.close()
            return 1

        if not jk:
            print("⚠ No Indeed posting to verify against — saving unverified.")
        else:
            print(f"\nChecking the session against jk={jk}:")
            worked = await _verify(context, jk)
            if not worked:
                print("\n✗ Every route still came back a wall or an empty page. "
                      "Not saving — the file you have is no worse than this one.")
                await browser.close()
                return 1

        backup = _backup()
        await context.storage_state(path=COOKIE_FILE)
        await browser.close()

    print(f"\n✓ Saved the session to {COOKIE_FILE}")
    if backup:
        print(f"  previous file kept at {os.path.basename(backup)}")
    print("  Now re-run the URL-list scrape; the Indeed URLs that returned a "
          "sign-in wall should extract.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jk", default="",
                    help="Indeed posting id to verify the session against "
                         "(default: the first one in 00_saved/url-list.md)")
    ap.add_argument("--no-verify", action="store_true",
                    help="save without proving the session can fetch a posting")
    args = ap.parse_args()

    jk = "" if args.no_verify else (args.jk or _a_jk_to_verify_with())
    return asyncio.run(run(jk))


if __name__ == "__main__":
    raise SystemExit(main())
