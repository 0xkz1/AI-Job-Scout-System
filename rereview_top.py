"""Re-review the top-N filter-passing jobs with the CURRENT reviewer logic.

Written after _load_review_facts() replaced a 2500-char persona slice with the
full persona + every career/cv/projects entry: existing reviews were produced
against that starved evidence base and wrongly flagged substantiated claims
(e.g. "systems-level approach to UX and UI", evidenced by portfolio_website.md
and feral-research-living-archive.md) as fabrication. Those stale verdicts stay
on disk until the documents are reviewed again.

Checkpoint-free by nature — run_review() writes each review file as it goes, so
an interrupt only loses the in-flight document. Existing reviews are always
overwritten (that is the point).

Usage:
  .venv/bin/python3 rereview_top.py --limit 56
  .venv/bin/python3 rereview_top.py --limit 56 --kind CV
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from filter import passes_filter  # noqa: E402
from matcher import make_safe_name  # noqa: E402
from reviewer import REVIEWS_DIR, run_review, _extract_score  # noqa: E402

ANALYZED = ROOT / "10_output" / "_analyzed.json"
CV_DIR = ROOT / "10_output" / "10_cvs"
CL_DIR = ROOT / "10_output" / "10_cover-letters"


def main():
    ap = argparse.ArgumentParser()
    # --limit is an explicit count override; without it the stage acts on the
    # configured review_top_percent, the same selection generation uses.
    ap.add_argument("--limit", type=int, default=None,
                    help="review the best N jobs (overrides review_top_percent)")
    ap.add_argument("--percent", type=float, default=None,
                    help="review the top P%% (overrides review_top_percent)")
    ap.add_argument("--kind", choices=["CV", "CL", "both"], default="both")
    ap.add_argument("--only", metavar="FILE",
                    help="review just the base names listed in FILE (one per line) — "
                         "for re-checking a handful of documents after a targeted rebuild")
    # Widening the top-% pulls in never-reviewed jobs AND documents whose review
    # went stale for an unrelated reason (a bulk text edit changes reviewed_sha).
    # --new-only spends the LLM budget on the former only.
    ap.add_argument("--new-only", action="store_true",
                    help="skip documents that already have a review file, even a stale one")
    args = ap.parse_args()

    config = yaml.safe_load((ROOT / "config.yaml").read_text()) or {}
    from selection import ranked_jobs, select_top
    if args.limit is not None:
        top = ranked_jobs(config)[:args.limit]
        scope = f"上位{args.limit}求人"
    else:
        top = select_top("review", config, percent=args.percent)
        pct = args.percent if args.percent is not None else config.get("review_top_percent", 20)
        scope = f"上位{pct}%={len(top)}求人"

    only = None
    if args.only:
        only = {l.strip() for l in Path(args.only).read_text().splitlines() if l.strip()}
        scope = f"指定{len(only)}件"

    kinds = ["CV", "CL"] if args.kind == "both" else [args.kind]
    todo = []
    skipped_reviewed = 0
    for job in top:
        base = make_safe_name(job.get("company", ""), job.get("title", ""))
        if only is not None and base not in only:
            continue
        for kind in kinds:
            d = CV_DIR if kind == "CV" else CL_DIR
            p = d / f"{base}_{kind}.md"
            if not p.exists():
                continue
            if args.new_only and (REVIEWS_DIR / f"{p.stem}_review.md").exists():
                skipped_reviewed += 1
                continue
            todo.append((kind, p, job))

    print(f"[{time.strftime('%H:%M:%S')}] 再レビュー対象: {len(todo)}件 "
          f"({scope} / {args.kind})"
          + (f" / 既レビューをスキップ: {skipped_reviewed}件" if args.new_only else ""),
          flush=True)

    done = failed = 0
    cleared = still_blocked = 0
    for i, (kind, path, job) in enumerate(todo, 1):
        try:
            rp = run_review(kind, path, job)
        except Exception as e:
            failed += 1
            print(f"  ✗ {path.stem}: {str(e)[:70]}", flush=True)
            continue
        done += 1
        score, fact_block, _nits = _extract_score(rp.read_text(encoding="utf-8"))
        if fact_block:
            still_blocked += 1
        else:
            cleared += 1
        print(f"  [{i}/{len(todo)}] {kind} {job.get('company','?')[:20]:20s} "
              f"score={score} fact_block={fact_block}", flush=True)

    print(f"\n[{time.strftime('%H:%M:%S')}] 完了: {done}件 再レビュー, {failed}件 失敗")
    print(f"  事実誤りなし(送付可): {cleared}件 / 事実誤りあり: {still_blocked}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
