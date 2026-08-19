"""One-off: put the CV/CL review scores onto existing match reports.

generate_match_report now writes cv_review_score / cl_review_score (and a
_current flag each) so one Obsidian Base can show the match score beside the
review score. Reports already on disk only pick them up when the job is next
rescored, which for most of them is never — a job that stops appearing in the
feeds is never rewritten again. This back-fills them.

The values are NOT recomputed here: read_review_scores in matcher.py is the
same function the generator calls. Nothing is regenerated — no CV, no cover
letter, no review — the numbers are copied out of review files that already
exist.

Run with --apply to write. Without it, prints what would change.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from matcher import read_review_scores

MATCH_DIR = Path(__file__).resolve().parent / "10_output" / "00_matches"

_SCORE_KEYS = ("cv_review_score", "cv_review_current",
               "cl_review_score", "cl_review_current",
               # The CL has no score and never will; these two carry what its
               # review does know. See _cl_review_flags in matcher.py.
               "cl_fact_block", "cl_opening_source")


def patch(text: str, base: str) -> tuple[str, bool]:
    """Return the report with review scores refreshed, and whether it changed."""
    fm = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not fm:
        return text, False

    body_start = fm.end()
    lines = [l for l in fm.group(1).split("\n")
             if not any(re.match(rf"^{k}:", l) for k in _SCORE_KEYS)]

    scores = read_review_scores(base)
    for k, v in scores.items():
        lines.append(f"{k}: {str(v).lower() if isinstance(v, bool) else v}")

    new = "---\n" + "\n".join(lines) + "\n---\n" + text[body_start:]
    return new, new != text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    if not MATCH_DIR.exists():
        print(f"no such directory: {MATCH_DIR}")
        return 1

    files = sorted(MATCH_DIR.glob("*.md"))
    changed = with_scores = stale = 0
    for f in files:
        original = f.read_text(encoding="utf-8")
        patched, did = patch(original, f.stem)
        if did:
            changed += 1
            if args.apply:
                f.write_text(patched, encoding="utf-8")
        if "cv_review_score:" in patched or "cl_review_score:" in patched:
            with_scores += 1
            if "_review_current: false" in patched:
                stale += 1

    verb = "patched" if args.apply else "would patch"
    print(f"{verb} {changed}/{len(files)} reports")
    print(f"  レビュースコアを持つ: {with_scores}")
    print(f"  うち陳腐なレビューを含む: {stale}")
    if not args.apply:
        print("dry run — nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
