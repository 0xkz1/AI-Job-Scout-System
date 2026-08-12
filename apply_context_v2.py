"""Promote the measured role_fit scores into context_score.

context_rescore_v2.py wrote context_score_v2 (ethos) and context_v2 (both axes
plus the requirement judged) beside the score in use, so the two could be
compared before anything switched. They were, on the 316 jobs carrying a stored
CV review: old single-axis score r=+0.294, new ethos +0.382, new role_fit
+0.459, and every blend below role_fit alone.

So role_fit becomes context_score, ethos is kept beside it, and composite_score
is recomputed with the weights as they stand. The scale moves down with it —
mean context 44.4 to 27.2, mean composite 0.464 to 0.354 — which is why
match_score_threshold moves 0.45 to 0.32 in the same change: the floor is an
absolute number, and leaving it would have cut the pipeline roughly in half for
a reason that has nothing to do with the jobs.

  python apply_context_v2.py            # dry run
  python apply_context_v2.py --write
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path

import selection

ANALYZED = Path(__file__).resolve().parent / "10_output" / "_analyzed.json"
DEFAULT_WEIGHTS = {"skills": 0.20, "experience": 0.05, "location": 0.10,
                   "salary": 0.01, "context": 0.64}


def composite(match: dict, context: float, weights: dict) -> float:
    total = weights.get("context", 0.64) * context
    for dim in ("skills", "experience", "location", "salary"):
        total += weights.get(dim, 0.0) * (match.get(dim) or {}).get("score", 0.0)
    return round(total, 4)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    raw = json.loads(ANALYZED.read_text(encoding="utf-8"))
    jobs = list(raw.values()) if isinstance(raw, dict) else raw
    weights = selection.load_config().get("weights") or DEFAULT_WEIGHTS

    before, after, moved = [], [], 0
    for job in jobs:
        m = job.get("match") or {}
        v2 = m.get("context_v2")
        if not v2 or m.get("context_score_v2") is None:
            continue
        role_fit = float(v2["role_fit"]) / 100.0
        before.append(m.get("composite_score") or composite(m, m["context_score"], weights))
        m["context_score"] = round(role_fit, 2)
        m["context_ethos"] = round(float(m["context_score_v2"]), 2)
        if v2.get("role_requirement"):
            m["context_role_requirement"] = v2["role_requirement"]
        if v2.get("reasoning"):
            m["context_reasoning_en"] = v2["reasoning"]
            m["context_reasoning"] = v2["reasoning"]
            # The stored Japanese belongs to the score that was just replaced.
            m["context_reasoning_ja"] = ""
        m["composite_score"] = composite(m, role_fit, weights)
        after.append(m["composite_score"])
        # The comparison is over; keeping both would leave two scores in the
        # record with nothing saying which one is live.
        m.pop("context_score_v2", None)
        m.pop("context_v2", None)
        m.pop("context_score_v2a", None)
        m.pop("context_v2a", None)
        moved += 1

    if not moved:
        print("nothing to promote")
        return

    print(f"{moved} jobs")
    print(f"  composite  {st.mean(before):.3f} -> {st.mean(after):.3f}  "
          f"({st.mean(after) - st.mean(before):+.3f})")
    old_floor = float(selection.load_config().get("match_score_threshold", 0.45))
    print(f"  above {old_floor}: {sum(1 for x in before if x >= old_floor)} -> "
          f"{sum(1 for x in after if x >= old_floor)}")
    print(f"  above 0.32: {sum(1 for x in after if x >= 0.32)}")

    if not args.write:
        print("\ndry run — pass --write to apply")
        return
    ANALYZED.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nwritten")


if __name__ == "__main__":
    main()
