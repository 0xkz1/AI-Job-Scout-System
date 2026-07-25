"""Recompute stored skill AND location scores, plus composite/tier, after a matcher
logic change.

Despite the name it covers location as well: both are deterministic sub-scores, and
both were unreachable once stored. LLM context scores, summaries and reasoning are
still left alone — those are expensive and unrelated to matcher rules.


Local-only (no LLM calls, runs in seconds): rereads every job in
_analyzed.json, reruns calculate_skill_match with the CURRENT matcher logic,
and rewrites composite_score/tier where the skill sub-score changed. LLM
context scores, summaries, and reasoning are left untouched — those are
expensive and unrelated to skill-matching rules.

Run this after editing skill-trust rules (_AMBIGUOUS_DESIGN_TERMS,
_DIGITAL_DESIGN_SIGNALS, _digital_role_affinity, NON_SKILL_FILTER, …) so the
stored DB reflects the new rules without waiting for the next scrape.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from matcher import (  # noqa: E402
    DEFAULT_WEIGHTS,
    _infer_country,
    calculate_location_match,
    calculate_skill_match,
    load_user_experience,
    load_user_skills,
)

ANALYZED_PATH = ROOT / "10_output" / "_analyzed.json"


def main():
    db = json.loads(ANALYZED_PATH.read_text())
    user_skills = load_user_skills()
    user_exp = load_user_experience()
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}

    changed, tier_changed = 0, 0
    ups, downs = [], []
    for job in db:
        m = job.get("match")
        if not m:
            continue
        # No early skip for a job with no extracted skills: composite must be
        # recomputed for EVERY entry, or a weight change (or a title_relevance
        # that has since gone to 0) never reaches it. Skipping these left "Class 2
        # Driver" holding composite 0.49 while its own title_relevance was 0.0 —
        # a hard-excluded job sitting inside the top 30%. calculate_skill_match
        # already returns its own no-skills default, so just let it run.
        job_skills = job.get("analysis", {}).get("skills", [])
        desc = job.get("description", "") or job.get("snippet", "")
        old_score = m["skills"]["score"]
        new_skill = calculate_skill_match(
            job_skills, user_skills, job.get("title", ""), desc,
            llm_coverage=job.get("analysis", {}).get("skill_coverage"))
        if new_skill["score"] != old_score:
            changed += 1
            (ups if new_skill["score"] > old_score else downs).append(
                f"  {'↑' if new_skill['score'] > old_score else '↓'} "
                f"{old_score:.2f}->{new_skill['score']:.2f}  "
                f"{job.get('company','?')[:22]} — {job.get('title','?')[:45]}"
            )
        m["skills"] = new_skill

        # Location too, for the same reason the weights are re-read from config:
        # a stored sub-score makes a rule change unreachable for jobs already in the
        # DB. Location scoring now takes the country label rather than matching place
        # names against a hand-kept alias list, which moved 45 jobs — "España" and
        # "Hagsfeld, Karlsruhe" had been scoring 0.15 "location unknown", ABOVE the
        # 0.20 that on-site abroad is meant to get.
        if m.get("location"):
            m["location"] = calculate_location_match(
                job.get("location", ""),
                job.get("analysis", {}).get("work_style", ""),
                user_exp,
                country=_infer_country(job),
            )

        # Weights come from config, NOT from m["weights"] — that field records the
        # weights this entry was LAST scored with, so reusing it made a weight
        # change in config.yaml permanently unreachable for already-scored jobs.
        # Recomputing unconditionally (rather than only when the skill sub-score
        # moved) is what lets a pure weight change take effect at all.
        w = dict(DEFAULT_WEIGHTS)
        w.update(config.get("weights") or {})
        m["weights"] = w
        composite = (
            new_skill["score"] * w["skills"]
            + m["experience"]["score"] * w["experience"]
            + m["location"]["score"] * w["location"]
            + m["salary"]["score"] * w["salary"]
            + m["context_score"] * w["context"]
        ) * m.get("title_relevance", 1.0)
        old_tier = m["tier"]
        m["composite_score"] = round(composite, 2)
        relevance = m.get("title_relevance", 1.0)
        ctx_source = m.get("context_source")
        if relevance < 0.5:
            new_tier = "🔴 Completely Irrelevant"
        elif composite >= 0.8 and ctx_source == "llm":
            new_tier = "🟢 Strong Match"
        elif composite >= 0.8:
            new_tier = "🟡 Good Match (未検証: LLM文脈スコア無し)"
        elif composite >= 0.6:
            new_tier = "🟡 Good Match"
        elif composite >= 0.4:
            new_tier = "🟠 Partial Match"
        else:
            new_tier = "🔴 Weak Match"
        m["tier"] = new_tier
        if new_tier != old_tier:
            tier_changed += 1

    ANALYZED_PATH.write_text(json.dumps(db, indent=2, ensure_ascii=False, default=str))
    print(f"{changed} 件のスキルスコアを更新 (↑{len(ups)} ↓{len(downs)}), "
          f"うち {tier_changed} 件でtierが変化 — 保存済")
    for line in ups + downs:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
