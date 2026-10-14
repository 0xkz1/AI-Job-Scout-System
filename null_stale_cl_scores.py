"""Void submission_score on cover-letter reviews written before the rescope.

A CL review used to score the whole letter against the posting's requirements,
the same rubric the CV is scored on. That stopped making sense when the letter
became an assembled document: the identity paragraphs are byte-identical in
every letter, so scoring them per posting measured nothing, and the stack the
rubric looks for is deliberately the CV's job. ba8fc9c narrowed CL review to
the one paragraph written for the posting and dropped the rubric with it —
_extract_score now returns None and submission_score is written null.

Reviews already on disk kept their old number, and generate_match_report reads
it into cl_review_score, so match reports still carry a figure produced by a
scoring rule that no longer exists. Nulling it costs nothing: apply_priority
never read cl_review_score, and app.py renders a null score as "スコア未算出
(再レビューで算出)", which is exactly what is true of these.

Only reviews predating the rescope are touched; a review written since already
has null and is left alone.

  python null_stale_cl_scores.py            # dry run
  python null_stale_cl_scores.py --write
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

REVIEWS = Path(__file__).resolve().parent / "10_output" / "15_reviews"
SCORE = re.compile(r"^submission_score:\s*(\d+)\s*$", re.MULTILINE)
READY = re.compile(r"^submission_ready:\s*\w+\s*$", re.MULTILINE)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    changed = []
    for path in sorted(REVIEWS.glob("*_CL_review.md")):
        text = path.read_text(encoding="utf-8")
        found = SCORE.search(text)
        if not found:
            continue
        updated = SCORE.sub("submission_score: null", text, count=1)
        # A letter cannot be "ready" on a score that no longer exists.
        updated = READY.sub("submission_ready: false", updated, count=1)
        changed.append((path.name, found.group(1)))
        if args.write:
            path.write_text(updated, encoding="utf-8")

    print(f"{len(changed)} CL reviews carrying a pre-rescope score")
    for name, score in changed[:5]:
        print(f"  {score:>3} -> null  {name}")
    if len(changed) > 5:
        print(f"  … and {len(changed) - 5} more")
    print("\nwritten" if args.write else "\ndry run — pass --write to apply")


if __name__ == "__main__":
    main()
