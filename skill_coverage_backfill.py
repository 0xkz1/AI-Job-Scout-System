"""Compute and store the LLM skill-coverage verdict for jobs that lack one.

Why this exists: the dictionary match path (exact → SKILL_SYNONYMS → substring →
TF-IDF) only matches shared words, so paraphrases with no lexical overlap read as
gaps ("Software Engineering" vs the candidate's "Code Standards"/"Python"), and no
hand-maintained synonym list can ever cover job-posting vocabulary. A bare-name
embedding fallback was measured and rejected — nomic-embed-text rates
"Mechanical Design ~ Visual Design" 0.707, above every genuine pair, which would
resurrect the physical-design false positives. The LLM gets the job title and
description, so it can tell a gas-pipe "Design Engineer" from a UI one.

The verdict is stored on the job (analysis.skill_coverage) so every later offline
rerun (recompute_skill_scores.py) reuses it without another LLM call.

Resumable: jobs that already have a verdict are skipped, so an interrupted run
just continues. Highest composite score first — the jobs whose reports matter.

Usage:
  .venv/bin/python3 skill_coverage_backfill.py --limit 200
  .venv/bin/python3 skill_coverage_backfill.py --limit 200 --dry-run
  .venv/bin/python3 skill_coverage_backfill.py --all --refresh   # recompute existing too
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from matcher import _llm_skill_coverage, load_user_skills  # noqa: E402

ANALYZED = ROOT / "10_output" / "_analyzed.json"
SAVE_EVERY = 10  # checkpoint cadence — an interrupted run keeps its work


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--all", action="store_true", help="no limit")
    ap.add_argument("--refresh", action="store_true",
                    help="recompute jobs that already have a verdict")
    ap.add_argument("--min-composite", type=float, default=0.0,
                    help="skip jobs scoring below this. Skills carry 0.35 of the "
                         "composite, so a job under 0.25 cannot reach Good Match "
                         "(0.6) even if coverage credits every requirement — "
                         "spending an LLM call on it buys nothing.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = json.loads(ANALYZED.read_text())
    user_skills = load_user_skills()

    candidates = []
    for job in db:
        analysis = job.get("analysis") or {}
        if not analysis.get("skills"):
            continue  # nothing to judge
        if analysis.get("skill_coverage") and not args.refresh:
            continue
        if (job.get("match") or {}).get("composite_score", 0) < args.min_composite:
            continue
        candidates.append(job)
    candidates.sort(key=lambda j: (j.get("match") or {}).get("composite_score", 0),
                    reverse=True)
    todo = candidates if args.all else candidates[:args.limit]

    have = sum(1 for j in db if (j.get("analysis") or {}).get("skill_coverage"))
    # Print what --limit LEAVES BEHIND, not just what this run will do. Reporting
    # only len(todo) once made a capped run read as a finished one (2026-07-24:
    # "完了" was relayed for the top 250 while 382 report-carrying jobs still had
    # no verdict at all).
    deferred = len(candidates) - len(todo)
    print(f"jobs={len(db)} already-covered={have} todo={len(todo)} "
          f"(refresh={args.refresh})", flush=True)
    if deferred:
        print(f"⚠️  --limit {args.limit} により {deferred}件を未処理のまま残す "
              f"(全件処理は --all)", flush=True)
    if args.dry_run:
        for j in todo[:30]:
            print(f"  {(j.get('match') or {}).get('composite_score', 0):.2f} "
                  f"{j.get('company','?')[:22]} — {j.get('title','?')[:45]}")
        return 0

    done = failed = 0
    for i, job in enumerate(todo, 1):
        analysis = job["analysis"]
        try:
            cov = _llm_skill_coverage(
                job.get("title", ""),
                job.get("description", "") or job.get("snippet", ""),
                analysis["skills"],
                user_skills,
            )
            if cov:
                analysis["skill_coverage"] = cov
                rescued = sum(1 for v in cov.values() if v["verdict"] in ("full", "partial"))
                done += 1
                print(f"  ✓ [{i}/{len(todo)}] {job.get('company','?')[:20]} — "
                      f"{job.get('title','?')[:38]} ({rescued}/{len(cov)} covered)", flush=True)
            else:
                failed += 1
                print(f"  ✗ [{i}/{len(todo)}] {job.get('title','?')[:38]}: no verdict", flush=True)
        except Exception as e:
            failed += 1
            print(f"  ✗ [{i}/{len(todo)}] {job.get('title','?')[:38]}: {str(e)[:60]}", flush=True)
        if i % SAVE_EVERY == 0:
            ANALYZED.write_text(json.dumps(db, indent=2, ensure_ascii=False, default=str))

    ANALYZED.write_text(json.dumps(db, indent=2, ensure_ascii=False, default=str))
    print(f"\n完了: {done}件に coverage 付与, {failed}件失敗 — 保存済", flush=True)
    # Count only what this run was SUPPOSED to cover — jobs excluded by
    # --min-composite are a deliberate skip, not a backlog, and reporting them
    # as leftovers would make the warning cry wolf every night.
    remaining = sum(1 for j in db
                    if (j.get("analysis") or {}).get("skills")
                    and not (j.get("analysis") or {}).get("skill_coverage")
                    and (j.get("match") or {}).get("composite_score", 0) >= args.min_composite)
    if remaining:
        print(f"⚠️  未カバレッジが {remaining}件 残っている — この実行は部分的。"
              f"全件やるなら --all", flush=True)
    else:
        print("カバレッジ: 対象求人すべてに判定あり", flush=True)
    _health_report(todo)
    print("次: recompute_skill_scores.py でスコア再計算", flush=True)
    return 0


# A verdict of full/partial is the only thing this layer exists to produce. The
# 2026-07-24 "by"-echo bug kept every call succeeding while silently discarding
# ~all of them (positives fell to 0%), and nothing complained. These floors turn
# that class of silent degradation into a loud one.
MIN_POSITIVE_RATE = 0.15      # observed healthy: 0.23 (tail jobs) – 0.55 (top jobs)
MIN_JUDGED_RATE = 0.70        # share of a job's skills the model actually answered
MIN_VERDICTS_TO_JUDGE = 150   # below this the positive rate is noise, not signal


def _health_report(jobs: list) -> None:
    verdicts = judged = expected = 0
    positive = 0
    for job in jobs:
        cov = (job.get("analysis") or {}).get("skill_coverage") or {}
        skills = (job.get("analysis") or {}).get("skills") or []
        expected += len(skills)
        judged += len(cov)
        for v in cov.values():
            verdicts += 1
            if v.get("verdict") in ("full", "partial"):
                positive += 1
    if not verdicts:
        print("⚠️  健全性: 判定が1件も保存されていない — カバレッジ層が機能していない", flush=True)
        return
    pos_rate = positive / verdicts
    judged_rate = judged / expected if expected else 0.0
    print(f"健全性: 判定 {verdicts}件 / positive {positive}件 ({pos_rate:.0%}) / "
          f"要求スキルの判定率 {judged_rate:.0%}", flush=True)
    # A handful of genuinely-irrelevant jobs (an HR post, a gas-main engineer)
    # legitimately produce zero positives, so a tiny run says nothing about the
    # parser's health — only flag once there is enough signal to mean something.
    if verdicts < MIN_VERDICTS_TO_JUDGE:
        print(f"  (判定 {verdicts}件は少なすぎるため positive率の判定は保留)", flush=True)
    elif pos_rate < MIN_POSITIVE_RATE:
        print(f"⚠️  positive率 {pos_rate:.0%} が下限 {MIN_POSITIVE_RATE:.0%} 未満 — "
              f"判定が黙って捨てられている疑い（'by' の解決失敗が典型）。"
              f"matcher._resolve_by と _llm_skill_coverage のパースを確認", flush=True)
    if judged_rate < MIN_JUDGED_RATE:
        print(f"⚠️  判定率 {judged_rate:.0%} が下限 {MIN_JUDGED_RATE:.0%} 未満 — "
              f"モデルが一部スキルに答えていない（出力truncation / max_tokens不足の疑い）", flush=True)


if __name__ == "__main__":
    sys.exit(main())
