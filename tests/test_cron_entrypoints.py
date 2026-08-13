"""The scheduled entrypoints must give Indeed a display and the right interpreter.

Two failures that only ever showed up on the cron path, never interactively:

1. Indeed answers a headless browser with a Cloudflare challenge, and the only
   way through is a headed relaunch, which needs an X display. Cron has none, so
   scraper_indeed raises CloudflareBlocked and the searches are lost — its own
   message says to wrap the command in xvfb-run, and neither entrypoint did.
   Verified by hand: under `xvfb-run -a`, DISPLAY becomes :99,
   _headed_display_available() returns True, and a headed chromium starts.

2. scraper_runner.sh called bare `python3` while run_cron.sh called the venv.
   They are not interchangeable — on 2026-08-13 scikit-learn was importable from
   the system interpreter and missing from the venv, so matcher's TF-IDF context
   fallback returned a constant 0.5 under one and a real score under the other.

Both are shell, so these are text assertions. They are still worth having: the
failure mode is a scheduled job that exits 0 while scraping nothing, which is
how Indeed once went 11 days contributing nothing with a green cron log.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINTS = [ROOT / "run_cron.sh", ROOT / "scraper_runner.sh"]


@pytest.mark.parametrize("script", ENTRYPOINTS, ids=lambda p: p.name)
def test_entrypoint_is_valid_bash(script):
    assert script.exists(), f"{script.name} is missing"
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, f"{script.name} has a syntax error: {result.stderr}"


@pytest.mark.parametrize("script", ENTRYPOINTS, ids=lambda p: p.name)
def test_entrypoint_falls_back_to_xvfb(script):
    text = script.read_text(encoding="utf-8")
    assert "xvfb-run" in text, (
        f"{script.name} runs Indeed with no X display fallback, so every "
        f"Cloudflare-challenged search is lost while the job still exits 0"
    )


@pytest.mark.parametrize("script", ENTRYPOINTS, ids=lambda p: p.name)
def test_the_display_socket_is_checked_not_just_the_variable(script):
    """DISPLAY set does not mean an X server is reachable. Cron inherits it from
    the desktop session that installed the crontab while having no access to
    that server — the exact condition that produced 11 silent days."""
    text = script.read_text(encoding="utf-8")
    assert "/tmp/.X11-unix/" in text, (
        f"{script.name} decides on DISPLAY alone; it must test the socket, "
        f"because an inherited-but-unreachable DISPLAY is the failure case"
    )


@pytest.mark.parametrize("script", ENTRYPOINTS, ids=lambda p: p.name)
def test_python_is_the_venv_not_whatever_is_on_path(script):
    text = script.read_text(encoding="utf-8")
    assert ".venv/bin/python" in text, (
        f"{script.name} does not prefer the venv interpreter; the two disagree "
        f"about which packages exist, and scikit-learn's absence silently turns "
        f"the TF-IDF context score into a constant"
    )
    bare = re.findall(r"^\s*(?:if\s+)?python3\s+\w+\.py", text, re.M)
    assert not bare, f"{script.name} still invokes a bare python3: {bare}"


def test_the_scraper_still_tells_the_operator_to_use_xvfb():
    """The entrypoints implement what scraper_indeed's message advises. If that
    advice is ever reworded away, these wrappers lose their stated reason."""
    text = (ROOT / "scraper_indeed.py").read_text(encoding="utf-8")
    assert "xvfb-run" in text
    assert "_headed_display_available" in text


# The nightly is only a nightly if it runs every stage. Each of these was
# missing at some point and the absence showed up as a quiet backlog rather than
# an error: url-list.md unread for weeks, five of six sites never scraped, and
# 237 jobs carrying a generated CV with no review because nothing invoked the
# reviewer.
@pytest.mark.parametrize("script,reason", [
    ("scraper_url_list.py", "pasted job links are never ingested"),
    ("scraper_saved.py", "manually saved jobs are never ingested"),
    ("run.py", "nothing is scraped, analysed or matched"),
    ("nightly_scout.py", "nothing is ever reviewed — run.py does not review"),
])
def test_the_nightly_runs_every_stage(script, reason):
    text = (ROOT / "run_cron.sh").read_text(encoding="utf-8")
    assert script in text, f"run_cron.sh omits {script}: {reason}"


def _commands(script: Path) -> str:
    """The script with comments stripped.

    Asserting over raw text is what made this test fail on the comment
    explaining the very flag it forbids. Behaviour lives in the commands.
    """
    return "\n".join(line for line in script.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#"))


def test_the_pipeline_stage_is_not_pinned_to_one_site():
    """A single-site nightly meant LinkedIn, Reed, Adzuna, Guardian and the
    remote APIs contributed nothing on the scheduled path."""
    assert "--site" not in _commands(ROOT / "run_cron.sh"), (
        "the nightly pins run.py to one site; with no --site it covers them all"
    )


def test_one_failing_stage_does_not_cancel_the_others():
    """A flaky site must not cost the night its reviews. `set -e` would end the
    run on the first non-zero exit."""
    text = (ROOT / "run_cron.sh").read_text(encoding="utf-8")
    assert "set -euo" not in text, "set -e aborts the nightly on the first stage that fails"
    assert "timeout" in text, "a hung browser would otherwise eat the whole night"
