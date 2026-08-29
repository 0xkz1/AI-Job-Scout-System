#!/usr/bin/env python3
"""Backfill the strategy layer onto the existing DB, without re-scoring anything.

analyze_match now emits remote_scope, runway_fit, role_family, ladder_step,
strategic_value, strategic_terms and action_tier. Re-running it over the 5148
stored postings to get them is the wrong way round: the composite is expensive
(a stored LLM context score is reused, but a missing one would be re-drawn), and
none of the new fields depend on it being recomputed.

So this writes ONLY the new keys, from data already on each job, and touches no
existing key. No model calls — every value is arithmetic.

The CV review score is read from 10_output/15_reviews/*_CV_review.md, because
action_tier's top tier requires a human-checked signal and the review is the only
one there is. A posting with no review file gets a tier computed without it,
which is a defined case (see strategy.action_tier), not a gap.

Idempotent: a posting that already carries `action_tier` is skipped unless
--force.

Usage:
    python3 backfill_strategy_layer.py            # dry run
    python3 backfill_strategy_layer.py --apply
    python3 backfill_strategy_layer.py --apply --force
"""
import argparse
import collections
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from matcher import (  # noqa: E402
    _infer_country,
    _runway_fit,
    classify_remote_scope,
    make_safe_name,
)
from strategy import annotate  # noqa: E402

ANALYZED = ROOT / "10_output" / "_analyzed.json"
REVIEWS = ROOT / "10_output" / "15_reviews"
SCORE_RE = re.compile(r"^submission_score:\s*(\d+)\s*$", re.MULTILINE)
UNSCOREABLE_RE = re.compile(r"^unscoreable:\s*true\s*$", re.MULTILINE)


def review_scores() -> dict[str, int]:
    """safe_name -> submission_score, for CV reviews that carry a live one.

    CV only. Cover letters are written without a rubric and their
    submission_score is null by design, so including them would read a missing
    number as a low one.
    """
    out: dict[str, int] = {}
    if not REVIEWS.exists():
        return out
    for path in REVIEWS.glob("*_CV_review.md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        head = text[:1200]
        if UNSCOREABLE_RE.search(head):
            continue
        m = SCORE_RE.search(head)
        if m:
            out[path.stem[: -len("_CV_review")]] = int(m.group(1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if not ANALYZED.exists():
        print(f"no database at {ANALYZED}")
        return 1

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    jobs = json.loads(ANALYZED.read_text(encoding="utf-8"))
    scores = review_scores()

    tiers, families, scopes, runways = (collections.Counter() for _ in range(4))
    values: list[float] = []
    written, already, no_match, matched_review = 0, 0, 0, 0

    for job in jobs:
        match = job.get("match")
        if not isinstance(match, dict):
            no_match += 1
            continue
        if "action_tier" in match and not args.force:
            already += 1
            tiers[match.get("action_tier")] += 1
            continue

        analysis = job.get("analysis") or {}
        country = _infer_country(job)
        scope, confidence = classify_remote_scope(
            job.get("location") or "", analysis.get("work_style") or "",
            country, job.get("description") or "",
        )
        new = {
            "runway_fit": _runway_fit(analysis.get("contract_months"), config),
            "remote_scope": scope,
            "remote_scope_confidence": confidence,
        }
        # annotate reads remote_scope and runway_fit off the match, so the new
        # values have to be visible to it before it runs.
        review = scores.get(make_safe_name(job.get("company", ""), job.get("title", "")))
        if review is not None:
            matched_review += 1
        new.update(annotate(job, {**match, **new}, config, review_score=review))

        tiers[new["action_tier"]] += 1
        families[new["role_family"]] += 1
        scopes[scope] += 1
        runways[new["runway_fit"]] += 1
        if new["strategic_value"] is not None:
            values.append(new["strategic_value"])
        if args.apply:
            match.update(new)
        written += 1

    if args.apply:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = ANALYZED.with_name(f"_analyzed.bak_{stamp}.json")
        shutil.copy2(ANALYZED, backup)
        with open(ANALYZED, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False, default=str)
        print(f"  backup: {backup.name}")

    values.sort()
    median = values[len(values) // 2] if values else None
    print(f"\ncomputed={written} already_present={already} no_match={no_match} "
          f"review_scores_found={len(scores)} matched_to_a_job={matched_review} "
          f"apply={args.apply}")
    print(f"  action_tier:      {dict(sorted(tiers.items(), key=lambda x: (x[0] is None, x[0])))}")
    print(f"  role_family:      {dict(families)}")
    print(f"  remote_scope:     {dict(scopes)}")
    print(f"  runway_fit:       {dict(runways)}")
    print(f"  strategic_value:  n={len(values)} median={median} "
          f"p90={values[int(len(values) * 0.9)] if values else None}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
