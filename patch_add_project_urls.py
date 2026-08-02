"""One-off: put each project's live URL on its entry line in existing CVs.

A project record gained a `url:` field and cv_generator now prints it after the
entry title. Regenerating would apply it too, but regeneration re-rolls the LLM
ordering and rewrites every write-up, which would discard prose that was just
generated and measured to fit two pages — to add one address. This is a string
edit; do it as a string edit.

The decision of which line gets which URL is NOT reimplemented here: it comes
from cv_generator._with_project_url, the same function the generator uses. A
second copy of that matching rule is exactly how the two PDF renderers drifted.

Run with --apply to write. Without it, prints what would change.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cv_generator import _with_project_url

CV_DIR = Path(__file__).resolve().parent / "10_output" / "10_cvs"


def patch(text: str) -> tuple[str, int]:
    """Return the CV with URLs appended to entry lines, and how many were added."""
    added = 0
    out = []
    for line in text.split("\n"):
        s = line.strip()
        # Same shape test the generator uses for a title line. Employment lines
        # ("Independent Creative Technologist | TAIFUNOME (...) | 2023 – Present")
        # match it too, but their first segment is a job title, so no project
        # matches and they are returned untouched.
        if s.count(" | ") >= 2 and not s.startswith(("•", "-", "#")):
            inner = s.replace("**", "").strip()
            new = _with_project_url(s, inner)
            if new != s:
                added += 1
                out.append(new)
                continue
        out.append(line)
    return "\n".join(out), added


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    if not CV_DIR.exists():
        print(f"no such directory: {CV_DIR}")
        return 1

    files = sorted(CV_DIR.glob("*_CV.md"))
    changed = total = 0
    for f in files:
        original = f.read_text(encoding="utf-8")
        patched, added = patch(original)
        if not added:
            continue
        changed += 1
        total += added
        if args.apply:
            f.write_text(patched, encoding="utf-8")

    verb = "patched" if args.apply else "would patch"
    print(f"{verb} {changed}/{len(files)} CVs, {total} entry lines")
    if not args.apply:
        print("dry run — nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
