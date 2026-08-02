"""One-off: bring the TECHNICAL TOOLKIT block of existing CVs onto the current master.

The toolkit is a fixed block — cv_generator copies the category lines out of
career/cv/skill-toolkit/master.md verbatim, identically on every CV. So when a
line in the master changes, every generated CV carries the old one until it is
regenerated. Regeneration re-rolls the LLM ordering and rewrites every project
write-up, which would discard prose just measured to fit two pages in order to
add two skills to a list. This is a string edit; do it as a string edit.

The replacements are derived from the master file itself rather than typed out
here: a hardcoded copy of the new line is a second source of truth, and the one
thing this session has proved repeatedly is that the second copy is the one
that goes stale.

Run with --apply to write. Without it, prints what would change.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from cv_generator import _cv_root

CV_DIR = Path(__file__).resolve().parent / "10_output" / "10_cvs"

# Category lines whose text changed. Keyed by the CV's category heading, which
# is stable — only the skill list under it moves.
TRACKED_CATEGORIES = [
    "Frontend & Product Engineering",
    "Design & Visual Production",
]


def current_lines() -> dict[str, str]:
    """The live skill line for each tracked category, read from the master."""
    master = (_cv_root() / "skill-toolkit" / "master.md").read_text(encoding="utf-8")
    body = master.split("## Technical Toolkit", 1)[-1]
    out = {}
    for cat in TRACKED_CATEGORIES:
        m = re.search(rf"^{re.escape(cat)}\n(.+)$", body, re.MULTILINE)
        if m:
            out[cat] = m.group(1).strip()
    return out


def patch(text: str, lines: dict[str, str]) -> tuple[str, int]:
    """Replace each tracked category's skill line with the current one."""
    changed = 0
    out = text.split("\n")
    for i, line in enumerate(out[:-1]):
        # The heading renders bold on the CV ("**Frontend & Product Engineering**")
        # and plain in the master; accept either.
        cat = line.strip().replace("**", "")
        if cat in lines and out[i + 1].strip() and out[i + 1].strip() != lines[cat]:
            out[i + 1] = lines[cat]
            changed += 1
    return "\n".join(out), changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    lines = current_lines()
    if len(lines) != len(TRACKED_CATEGORIES):
        missing = set(TRACKED_CATEGORIES) - set(lines)
        print(f"could not read from master: {', '.join(sorted(missing))}")
        return 1

    files = sorted(CV_DIR.glob("*_CV.md"))
    changed = total = 0
    for f in files:
        original = f.read_text(encoding="utf-8")
        patched, n = patch(original, lines)
        if not n:
            continue
        changed += 1
        total += n
        if args.apply:
            f.write_text(patched, encoding="utf-8")

    verb = "patched" if args.apply else "would patch"
    print(f"{verb} {changed}/{len(files)} CVs, {total} toolkit lines")
    if not args.apply:
        print("dry run — nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
