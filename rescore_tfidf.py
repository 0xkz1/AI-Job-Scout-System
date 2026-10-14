#!/usr/bin/env python3
"""Recompute the context score for jobs that hold the dead TF-IDF constant.

scikit-learn is declared in requirements.txt but was missing from the venv, so
calculate_context_match returned on its first line — `if not SKLEARN_AVAILABLE`
— and every job the LLM path did not cover scored exactly 0.50 on context. 596
of 604. Context carries 0.64 of the composite, so each held 0.32 of unearned
score, and 0.50 sat above the LLM-scored median of 0.30: "no opinion" outranked
most real opinions.

Nothing below that early return had ever run, so its calibration was stale too.
Both were re-measured on 588 postings and fixed in matcher.py: the P1-P99 stretch
(0.015-0.079 -> 0.008-0.136) and the cap, which is now applied as a scale factor
rather than a clip so the ordering survives.

No LLM calls. These are jobs the filter rejected, which is why they took the
fallback in the first place — buying them a model's opinion is the spend this
project explicitly avoids.

  python rescore_tfidf.py --dry-run
  python rescore_tfidf.py --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ANALYZED = ROOT / "10_output" / "_analyzed.json"


def tier_for(composite: float) -> str:
    if composite >= 0.8:
        return "🟢 Strong Match"
    if composite >= 0.6:
        return "🟡 Good Match"
    if composite >= 0.4:
        return "🟠 Partial Match"
    return "🔴 Weak Match"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import matcher
    if not matcher.SKLEARN_AVAILABLE:
        raise SystemExit(
            "scikit-learn is still not importable — install it first, or this "
            "would rewrite every score with the same constant it is fixing"
        )

    raw = json.loads(ANALYZED.read_text(encoding="utf-8"))
    jobs = list(raw.values()) if isinstance(raw, dict) else raw
    todo = [j for j in jobs if (j.get("match") or {}).get("context_source") == "tfidf"]
    print(f"{len(todo)} jobs holding a TF-IDF context score")
    if not todo:
        return

    deltas, before_scores, after_scores = [], [], []
    for job in todo:
        m = job["match"]
        ctx = matcher.calculate_context_match(job.get("description") or "")
        before = m["composite_score"]
        before_scores.append(m["context_score"])
        m["context_score"] = ctx["score"]
        m["context_reasoning"] = ctx.get("reasoning", "")
        m["context_top_terms"] = ctx.get("top_terms", [])
        w = m["weights"]
        composite = (m["skills"]["score"] * w["skills"]
                     + m["experience"]["score"] * w["experience"]
                     + m["location"]["score"] * w["location"]
                     + m["salary"]["score"] * w["salary"]
                     + ctx["score"] * w["context"])
        m["composite_score"] = round(composite, 4)
        m["tier"] = tier_for(composite)
        after_scores.append(ctx["score"])
        deltas.append(m["composite_score"] - before)

    print(f"  context: {statistics.mean(before_scores):.3f} -> {statistics.mean(after_scores):.3f} (mean)")
    print(f"  composite change: mean {statistics.mean(deltas):+.3f}  "
          f"median {statistics.median(deltas):+.3f}  "
          f"up {sum(1 for d in deltas if d > 0)}  down {sum(1 for d in deltas if d < 0)}")

    if not args.apply:
        print("\ndry run — nothing written. Pass --apply.")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ANALYZED.with_name(f"_analyzed.bak_pre_tfidf_rescore_{stamp}.json")
    shutil.copy2(ANALYZED, backup)
    print(f"backup: {backup.name}")
    ANALYZED.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(todo)} rescored jobs")


if __name__ == "__main__":
    main()
