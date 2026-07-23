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
from reviewer import run_review, _extract_score  # noqa: E402

ANALYZED = ROOT / "10_output" / "_analyzed.json"
CV_DIR = ROOT / "10_output" / "10_cvs"
CL_DIR = ROOT / "10_output" / "10_cover-letters"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=56)
    ap.add_argument("--kind", choices=["CV", "CL", "both"], default="both")
    args = ap.parse_args()

    jobs = json.loads(ANALYZED.read_text())
    config = yaml.safe_load((ROOT / "config.yaml").read_text()) or {}
    passed = [j for j in jobs if j.get("match") and passes_filter(j, config)[0]]
    passed.sort(key=lambda j: j["match"]["composite_score"], reverse=True)
    top = passed[:args.limit]

    kinds = ["CV", "CL"] if args.kind == "both" else [args.kind]
    todo = []
    for job in top:
        base = make_safe_name(job.get("company", ""), job.get("title", ""))
        for kind in kinds:
            d = CV_DIR if kind == "CV" else CL_DIR
            p = d / f"{base}_{kind}.md"
            if p.exists():
                todo.append((kind, p, job))

    print(f"[{time.strftime('%H:%M:%S')}] 再レビュー対象: {len(todo)}件 "
          f"(上位{args.limit}求人 / {args.kind})", flush=True)

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
        score, fact_block = _extract_score(rp.read_text(encoding="utf-8"))
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
