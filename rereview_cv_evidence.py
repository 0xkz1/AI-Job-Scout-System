"""Re-run CV reviews written before Strong had to quote the CV.

Until c5f0fdf a rubric row could read `evidence: "Strong"` with nothing behind
it, and the rubric IS the submission score — 30 + 70 * coverage. A Meltwater AI
Engineer posting naming NLP, Transformers, fine-tuning and transfer analysis
throughout scored Strong on exactly that requirement against a CV containing
none of those words: 14 points, reaching apply_priority at 0.6 weight. Asked to
quote the CV instead, the same review came back with no Strong rows at all and
72 fell to 51.

425 stored reviews still carry scores produced the old way, so cv_review_score
— the only review number apply_priority reads — is unreliable across most of
the corpus. This re-runs them.

A review is judged old by the absence of `evidence_quote`, not by date: the
field only appears once the new prompt produced it.

Resumable — anything already carrying the field is skipped.

  python rereview_cv_evidence.py --limit 5
  python rereview_cv_evidence.py
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import reviewer
from matcher import make_safe_name

ROOT = Path(__file__).resolve().parent
CVS = ROOT / "10_output" / "10_cvs"
REVIEWS = ROOT / "10_output" / "15_reviews"
ANALYZED = ROOT / "10_output" / "_analyzed.json"


def jobs_by_base() -> dict[str, dict]:
    raw = json.loads(ANALYZED.read_text(encoding="utf-8"))
    jobs = list(raw.values()) if isinstance(raw, dict) else raw
    out: dict[str, dict] = {}
    for job in jobs:
        out.setdefault(make_safe_name(job.get("company", ""), job.get("title", "")), job)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    index = jobs_by_base()
    todo = []
    for review in sorted(REVIEWS.glob("*_CV_review.md")):
        if "evidence_quote" in review.read_text(encoding="utf-8"):
            continue
        base = review.name[: -len("_CV_review.md")]
        doc = CVS / f"{base}_CV.md"
        job = index.get(base)
        if doc.exists() and job:
            todo.append((doc, job))

    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} to re-review")

    done = failed = 0
    moved: list[int] = []
    for n, (doc, job) in enumerate(todo, 1):
        before = REVIEWS / f"{doc.stem}_review.md"
        old = re.search(r"^submission_score:\s*(\d+)",
                        before.read_text(encoding="utf-8"), re.M) if before.exists() else None
        try:
            out = reviewer.run_review("CV", doc, job)
        except Exception as e:
            print(f"  ⚠ {job.get('company', '')[:24]}: {str(e)[:70]}", flush=True)
            failed += 1
            time.sleep(2)
            continue
        new = re.search(r"^submission_score:\s*(\d+)",
                        out.read_text(encoding="utf-8"), re.M)
        o = int(old.group(1)) if old else None
        w = int(new.group(1)) if new else None
        if o is not None and w is not None:
            moved.append(w - o)
        print(f"  [{n}/{len(todo)}] {o} -> {w}  {job.get('company', '')[:30]}", flush=True)
        done += 1
        time.sleep(args.sleep)

    print(f"\nre-reviewed {done}, failed {failed}")
    if moved:
        import statistics as st
        print(f"  score change: mean {st.mean(moved):+.1f}, "
              f"{sum(1 for m in moved if m < 0)} down / {sum(1 for m in moved if m > 0)} up")


if __name__ == "__main__":
    main()
