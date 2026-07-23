"""Recompute stored skill scores + composite/tier after a matcher logic change.

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

from matcher import calculate_skill_match, load_user_skills  # noqa: E402

ANALYZED_PATH = ROOT / "10_output" / "_analyzed.json"


def main():
    db = json.loads(ANALYZED_PATH.read_text())
    user_skills = load_user_skills()

    changed, tier_changed = 0, 0
    ups, downs = [], []
    for job in db:
        m = job.get("match")
        if not m:
            continue
        job_skills = job.get("analysis", {}).get("skills", [])
        if not job_skills:
            continue
        desc = job.get("description", "") or job.get("snippet", "")
        old_score = m["skills"]["score"]
        new_skill = calculate_skill_match(job_skills, user_skills, job.get("title", ""), desc)
        if new_skill["score"] == old_score:
            continue
        changed += 1
        (ups if new_skill["score"] > old_score else downs).append(
            f"  {'↑' if new_skill['score'] > old_score else '↓'} "
            f"{old_score:.2f}->{new_skill['score']:.2f}  "
            f"{job.get('company','?')[:22]} — {job.get('title','?')[:45]}"
        )
        m["skills"] = new_skill
        w = m["weights"]
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
