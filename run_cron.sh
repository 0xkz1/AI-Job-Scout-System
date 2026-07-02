#!/bin/bash
set -euo pipefail
cd /media/kz003/atelier/00_Kazuki/career/scraper

VENV_PYTHON="$(dirname "$0")/.venv/bin/python3"
[ -x "$VENV_PYTHON" ] || VENV_PYTHON="python3"

"$VENV_PYTHON" scraper_saved.py 2>/dev/null || true
"$VENV_PYTHON" run.py --site indeed --pages 5 2>&1 || true

echo "---"
echo "00_matches: $(find output/00_matches -name '*_match.md' 2>/dev/null | wc -l) match reports"
echo "00_cvs: $(ls output/00_cvs/*.md 2>/dev/null | wc -l) CVs"
echo "00_cover-letters: $(ls output/00_cover-letters/*.md 2>/dev/null | wc -l) cover letters"
echo "00_saved: $(ls output/00_saved/*.json 2>/dev/null | wc -l) saved jobs"
