"""Recompute submission_score / style_nits / fact_block / submission_ready in
existing review files, in place, without calling any LLM.

Run this after changing the scoring rule in reviewer._extract_score — the YAML
rubric and the findings sections are already in each review file, so the score
is fully re-derivable offline.

    python3 backfill_scores.py --dry-run   # preview the distribution shift
    python3 backfill_scores.py             # write

reviewed_sha is never touched: the score rule changed, the reviewed document
did not, so a recompute must not mark fresh reviews stale.
"""
import argparse
import re
import statistics
import sys
from pathlib import Path

from reviewer import (
    PRISTINE_DIR,
    REVIEWS_DIR,
    _extract_score,
    _score_line,
    get_score_threshold,
)

FM_RE = re.compile(r"\A(---\n)(.*?\n)(---\n)", re.DOTALL)
SCORE_LINE_RE = re.compile(r"^\*\*提出スコア:\*\*.*\n?", re.MULTILINE)


def _set_field(fm: str, key: str, val, after: str) -> str:
    """Update key in a frontmatter body, or insert it after `after`'s line."""
    if re.search(rf"^{key}:", fm, flags=re.MULTILINE):
        return re.sub(rf"^{key}:.*$", f"{key}: {val}", fm, count=1, flags=re.MULTILINE)
    if re.search(rf"^{after}:", fm, flags=re.MULTILINE):
        return re.sub(rf"^({after}:.*)$", rf"\1\n{key}: {val}", fm, count=1,
                      flags=re.MULTILINE)
    return fm.rstrip("\n") + f"\n{key}: {val}\n"


def rewrite(text: str) -> tuple[str, int | None, int, bool] | None:
    """(new_text, score, style_nits, fact_block), or None when unparseable."""
    m = FM_RE.match(text)
    if not m:
        return None
    fm, body = m.group(2), text[m.end():]

    score, fact_block, style_nits = _extract_score(body)
    ready = score is not None and not fact_block and score >= get_score_threshold()

    fm = _set_field(fm, "submission_score", score if score is not None else "null",
                    after="reviewed_at")
    fm = _set_field(fm, "style_nits", style_nits, after="submission_score")
    fm = _set_field(fm, "fact_block", "true" if fact_block else "false",
                    after="style_nits")
    fm = _set_field(fm, "submission_ready", "true" if ready else "false",
                    after="fact_block")

    # Replace the in-body badge so it agrees with the frontmatter.
    line = _score_line(score, fact_block, style_nits)
    body = SCORE_LINE_RE.sub("", body)
    if re.search(r"###\s*総評", body):
        body = re.sub(r"(###\s*総評)", f"{line}\n\n\\1", body, count=1)
    else:
        body = body.rstrip() + f"\n\n{line}\n"

    return m.group(1) + fm + m.group(3) + body, score, style_nits, fact_block


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    old_scores, new_scores, nits = [], [], []
    written = bad = 0

    for f in sorted(REVIEWS_DIR.glob("*_review.md")):
        text = f.read_text(encoding="utf-8")
        prev = re.search(r"^submission_score:\s*(\d+)", text, flags=re.MULTILINE)
        out = rewrite(text)
        if out is None:
            print(f"  SKIP (no frontmatter): {f.name}")
            bad += 1
            continue
        new_text, score, style_nits, _fb = out
        if prev:
            old_scores.append(int(prev.group(1)))
        if score is not None:
            new_scores.append(score)
        nits.append(style_nits)

        if not args.dry_run and new_text != text:
            f.write_text(new_text, encoding="utf-8")
            # Keep the annotation baseline in step, or every recomputed line
            # would later read as a user annotation and get fed back into the
            # re-review prompt.
            pristine = PRISTINE_DIR / f.name
            if pristine.exists():
                p_out = rewrite(pristine.read_text(encoding="utf-8"))
                if p_out:
                    pristine.write_text(p_out[0], encoding="utf-8")
            written += 1

    def stat(label, v):
        if len(v) > 1:
            print(f"  {label:14s} n={len(v):3d} mean={statistics.mean(v):5.1f} "
                  f"sd={statistics.stdev(v):5.1f} min={min(v):3d} max={max(v):3d}")

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}reviews: {len(nits)}"
          f"  scored: {len(new_scores)}  no rubric: {len(nits) - len(new_scores)}"
          f"  unparseable: {bad}  written: {written}")
    stat("old score", old_scores)
    stat("new score", new_scores)
    stat("style_nits", nits)
    th = get_score_threshold()
    print(f"  submission_ready at threshold {th}: "
          f"{sum(1 for s in new_scores if s >= th)}/{len(new_scores)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
