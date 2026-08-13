#!/bin/bash
set -euo pipefail
cd /media/kz003/atelier/00_Kazuki/career/Job-Intelligence-System

VENV_PYTHON="$(dirname "$0")/.venv/bin/python3"
[ -x "$VENV_PYTHON" ] || VENV_PYTHON="python3"

# Indeed answers a headless browser with a Cloudflare challenge, and the only
# way through it is a headed relaunch — which needs an X display cron does not
# have. scraper_indeed._headed_display_available() detects that and raises
# rather than pretending the search returned nothing, but detecting it does not
# scrape anything: the run just loses those searches. Its own message says to
# wrap the command in xvfb-run, so wrap it.
#
# Checked, not assumed: DISPLAY set does NOT mean an X server is reachable. Cron
# inherits DISPLAY from the desktop session that installed the crontab while
# having no access to that server, which is exactly how Indeed spent 11 days
# returning nothing while every night's job exited 0.
RUNNER=()
if [ -z "${DISPLAY:-}" ] || [ ! -e "/tmp/.X11-unix/X${DISPLAY#*:}" ]; then
    if command -v xvfb-run >/dev/null 2>&1; then
        RUNNER=(xvfb-run -a --server-args="-screen 0 1920x1080x24")
    else
        echo "⚠ no usable X display and no xvfb-run — Indeed will lose every " \
             "Cloudflare-challenged search. Install xvfb." >&2
    fi
fi

"${RUNNER[@]}" "$VENV_PYTHON" scraper_saved.py 2>/dev/null || true
"${RUNNER[@]}" "$VENV_PYTHON" run.py --site indeed --pages 5 2>&1 || true

echo "---"
echo "00_matches: $(find 10_output/00_matches -name '*_match.md' 2>/dev/null | wc -l) match reports"
echo "10_cvs: $(ls 10_output/10_cvs/*.md 2>/dev/null | wc -l) CVs"
echo "10_cover-letters: $(ls 10_output/10_cover-letters/*.md 2>/dev/null | wc -l) cover letters"
echo "00_saved: $(ls 00_saved/*.json 2>/dev/null | wc -l) saved jobs"
