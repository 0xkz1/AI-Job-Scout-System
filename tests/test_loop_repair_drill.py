"""Replay actual Guardian JS offline, inject a broken selector, exercise the gate.

The repair is scripted. This proves parser/gate behavior, not model repair skill.
"""
import asyncio
import json
import subprocess
from pathlib import Path

from playwright.async_api import async_playwright

import loop_repair as lr
from scraper_guardian import _extract_guardian_jobs


def test_saved_html_selector_fault_repair_and_legitimate_zero(tmp_path, monkeypatch):
    fixtures = Path(__file__).parent / "fixtures"
    monkeypatch.setattr(lr, "YIELD_HISTORY", tmp_path / "no-history.json")
    monkeypatch.setattr(lr, "_run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""))
    monkeypatch.setattr(lr, "tests_have_no_new_failures", lambda *a: (True, ""))
    staged = tmp_path / "00_saved"
    staged.mkdir()
    raw = staged / "_raw_guardian_fixture.json"

    async def replay():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page()
            await page.route("**/*", lambda route: route.abort())
            await page.set_content((fixtures / "guardian-listings.html").read_text())
            healthy = await _extract_guardian_jobs(page)
            raw.write_text(json.dumps(healthy))
            assert lr.verify(tmp_path, "guardian")[0]
            assert lr.inspect_staged(tmp_path, "guardian") == (4, 3, 3)

            class BrokenSelector:
                async def evaluate(self, script):
                    return await page.evaluate(script.replace("li.lister__item", "li.missing-selector"))

            raw.write_text(json.dumps(await _extract_guardian_jobs(BrokenSelector())))
            assert lr.verify(tmp_path, "guardian") == (False, 0, "still returns nothing")
            raw.write_text(json.dumps(await _extract_guardian_jobs(page)))
            assert lr.verify(tmp_path, "guardian")[0]

            # A wrong repair that repeats one job cannot meet the distinct URL floor.
            raw.write_text(json.dumps([healthy[0]] * 10))
            assert not lr.verify(tmp_path, "guardian")[0]
            await page.set_content((fixtures / "guardian-empty.html").read_text())
            assert await _extract_guardian_jobs(page) == []
            assert "0 jobs found" in await page.inner_text("main")
            await browser.close()

    asyncio.run(replay())
