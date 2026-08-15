"""One-off: put each entry's live URL on its title line in existing CVs.

A record gained a `url:` field and cv_generator now prints it after the entry
title. Regenerating would apply it too, but regeneration re-rolls the LLM
ordering and rewrites every write-up, which would discard prose that was just
generated and measured to fit two pages — to add one address. This is a string
edit; do it as a string edit.

The decision of which line gets which URL is NOT reimplemented here: it comes
from cv_generator._with_project_url, the same function the generator uses. A
second copy of that matching rule is exactly how the two PDF renderers drifted.

Also cleans up this script's own earlier mistake: the URL first went on the
SELECTED PROJECTS line as a bare shortened host ("· taifunome.com"), which
does two things wrong at once — it names the platform's own site as a
project's incidental link rather than the studio's, on a line that many CVs
never even promote to a full write-up; and appended as plain text after a
"**...**" span, it broke the PDF preprocessor's heading match (see app.py's
_md_to_pdf_bytes), so the entry silently lost its heading tag, its
page-break-avoid rule, and its bullet list — collapsed into one run-on
paragraph with literal "-" characters. Both are fixed now: the URL lives on
the EXPERIENCE line, as a full clickable [text](link), and the heading
regex accepts the " · [...](...)" suffix. This patch strips the old form
wherever it finds it before adding the new one.

Run with --apply to write. Without it, prints what would change.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from cv_generator import _with_project_url
import gen_version

CV_DIR = Path(__file__).resolve().parent / "10_output" / "10_cvs"
MATCH_DIR = Path(__file__).resolve().parent / "10_output" / "00_matches"

# The only thing this session's earlier version of _with_project_url ever
# wrote: a bare shortened host after a middle dot, on the Selected Projects
# title line. Nothing else on a CV produces this exact shape, so removing it
# by string match carries no risk of touching unrelated text.
_STALE_SUFFIX = re.compile(r" · [a-z0-9.-]+\.[a-z]{2,}$")


def patch(text: str) -> tuple[str, int]:
    """Return the CV with URLs on the right entry line, and how many lines changed."""
    changed = 0
    out = []
    for line in text.split("\n"):
        s = line.strip()
        was = s
        s = _STALE_SUFFIX.sub("", s)
        # Same shape test the generator uses for a title line. Whichever kind
        # of entry actually carries a url — project or employment — is decided
        # by _with_project_url, not by anything here.
        if s.count(" | ") >= 2 and not s.startswith(("•", "-", "#")):
            inner = s.replace("**", "").strip()
            s = _with_project_url(s, inner)
        if s != was:
            changed += 1
            out.append(s)
        else:
            out.append(line)
    return "\n".join(out), changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    if not CV_DIR.exists():
        print(f"no such directory: {CV_DIR}")
        return 1

    files = sorted(CV_DIR.glob("*_CV.md"))
    changed = total = locked = 0
    for f in files:
        original = f.read_text(encoding="utf-8")
        if gen_version.is_locked(f.stem[:-3], original, MATCH_DIR):
            locked += 1
            continue
        patched, added = patch(original)
        if not added:
            continue
        changed += 1
        total += added
        if args.apply:
            f.write_text(patched, encoding="utf-8")

    verb = "patched" if args.apply else "would patch"
    print(f"{verb} {changed}/{len(files)} CVs, {total} entry lines"
          + (f", {locked} locked (skipped)" if locked else ""))
    if not args.apply:
        print("dry run — nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
