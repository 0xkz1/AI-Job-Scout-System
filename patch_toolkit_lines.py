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
import gen_version

CV_DIR = Path(__file__).resolve().parent / "10_output" / "10_cvs"
MATCH_DIR = Path(__file__).resolve().parent / "10_output" / "00_matches"

def current_lines() -> dict[str, str]:
    """The live skill line for every category, read from the master.

    The categories used to be a hardcoded list of the two that had changed,
    which is the second source of truth this file's own docstring warns about —
    and it went stale exactly as predicted: "REST API integration (Postman),
    n8n workflow automation" was dropped from the master on 2026-08-31 and 1249
    CVs kept claiming both, because "Programming & Automation" was not on the
    list. Reading the categories from the master means a line removed there is
    removed from the CVs, whichever line it was.
    """
    master = (_cv_root() / "skill-toolkit" / "master.md").read_text(encoding="utf-8")
    body = master.split("## Technical Toolkit", 1)[-1]
    out = {}
    for block in re.split(r"\n\s*\n", body.strip()):
        rows = [l.strip() for l in block.strip().split("\n") if l.strip()]
        # A category is a heading line followed by its skill list. Anything
        # else in the file (front matter, the section title) is not one.
        if len(rows) == 2 and not rows[0].startswith("#"):
            out[rows[0]] = rows[1]
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
    if not lines:
        print("could not read any category from the toolkit master")
        return 1

    files = sorted(CV_DIR.glob("*_CV.md"))
    changed = total = locked = 0
    for f in files:
        original = f.read_text(encoding="utf-8")
        if gen_version.is_locked(f.stem[:-3], original, MATCH_DIR):
            locked += 1
            continue
        patched, n = patch(original, lines)
        if not n:
            continue
        changed += 1
        total += n
        if args.apply:
            f.write_text(patched, encoding="utf-8")

    verb = "patched" if args.apply else "would patch"
    print(f"{verb} {changed}/{len(files)} CVs, {total} toolkit lines"
          + (f", {locked} locked (skipped)" if locked else ""))
    if not args.apply:
        print("dry run — nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
