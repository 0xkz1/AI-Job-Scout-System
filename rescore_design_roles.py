"""Rescore design-role postings against the persona that now carries the design work.

Measured against 387 stored CV reviews, role_fit undershot graphic_designer
postings by 23.2 points and product_designer by 12.8, because the persona
evidenced engineering as work done and design mostly as asserted skill. The
persona now carries education.md and five portfolio files; on a 44-job paired
sample the design-vs-other residual gap closed from +12.2 to +1.2, 95% CI on
the change [-19.4, -2.9].

This puts the design-role slice of the corpus onto that scale. It is a slice on
purpose: it verifies the effect at corpus scale before the remaining ~1,600
postings are paid for. Until the rest follow, design roles and everything else
are on two scales and cannot be ranked against each other — see the tier and
threshold note printed at the end.

tfidf-scored design jobs are included. Their ~0.50 fallback means "no opinion",
and leaving it beside rescored LLM values repeats the failure 5dedcf8 documented:
an inert 0.50 becomes a high score by standing still while everything around it
moves.

  python rescore_design_roles.py --dry-run     # what would be scored
  python rescore_design_roles.py --limit 25    # try it
  python rescore_design_roles.py               # the slice
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import time
from datetime import datetime
from pathlib import Path

import selection
from filter import passes_filter

ROOT = Path(__file__).resolve().parent
ANALYZED = ROOT / "10_output" / "_analyzed.json"
DESIGN_ROLES = {"graphic_designer", "product_designer"}
CHECKPOINT_EVERY = 20


def due(jobs: list[dict], config: dict) -> list[dict]:
    """Design-role postings a ranking will actually read."""
    out = []
    for job in jobs:
        m = job.get("match") or {}
        if m.get("detected_role") not in DESIGN_ROLES:
            continue
        if m.get("context_score") is None:
            continue
        if not passes_filter(job, config)[0] or selection.is_unscoreable(job):
            continue
        out.append(job)
    return out


def tier_for(composite: float) -> str:
    if composite >= 0.8:
        return "🟢 Strong Match"
    if composite >= 0.6:
        return "🟡 Good Match"
    if composite >= 0.4:
        return "🟠 Partial Match"
    return "🔴 Weak Match"


def apply(job: dict, ctx: dict) -> tuple[float, float]:
    """Write the new context score and recompute the composite. Returns (before, after)."""
    m = job["match"]
    before = m["composite_score"]
    m["context_score"] = ctx["score"]
    m["context_reasoning"] = ctx.get("reasoning", "")
    m["context_reasoning_en"] = ctx.get("reasoning_en", "")
    m["context_reasoning_ja"] = ctx.get("reasoning_ja", "")
    m["context_source"] = "llm"
    if ctx.get("provider"):
        m["context_provider"] = ctx["provider"]
    if ctx.get("ethos") is not None:
        m["context_ethos"] = ctx["ethos"]
    if ctx.get("role_requirement"):
        m["context_role_requirement"] = ctx["role_requirement"]
    w = m["weights"]
    composite = (m["skills"]["score"] * w["skills"]
                 + m["experience"]["score"] * w["experience"]
                 + m["location"]["score"] * w["location"]
                 + m["salary"]["score"] * w["salary"]
                 + ctx["score"] * w["context"])
    m["composite_score"] = round(composite, 4)
    m["tier"] = tier_for(composite)
    return before, m["composite_score"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw = json.loads(ANALYZED.read_text(encoding="utf-8"))
    jobs = list(raw.values()) if isinstance(raw, dict) else raw
    config = selection.load_config()
    todo = due(jobs, config)
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(todo)} design-role postings to rescore")
    if args.dry_run or not todo:
        for j in todo[:15]:
            print(f"  {j['match']['detected_role']:18s} "
                  f"{j['match']['context_score']*100:3.0f}  {str(j.get('company'))[:30]}")
        return

    # The corpus is the product of every scoring run before this one; a failed
    # write halfway through a 555-call pass is not something to re-derive.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ANALYZED.with_name(f"_analyzed.bak_pre_design_rescore_{stamp}.json")
    shutil.copy2(ANALYZED, backup)
    print(f"backup: {backup.name}")

    from matcher import _load_persona_summary, _ollama_context_score
    persona = _load_persona_summary()
    print(f"persona: {len(persona)} chars\n")

    deltas, done, failed = [], 0, 0
    for n, job in enumerate(todo, 1):
        desc = job.get("description") or ""
        try:
            ctx = _ollama_context_score(desc, persona, brief=True)
        except Exception as e:
            print(f"  ⚠ {str(job.get('company',''))[:24]}: {str(e)[:60]}", flush=True)
            failed += 1
            time.sleep(2)
            continue
        if not ctx:
            failed += 1
            continue
        before, after = apply(job, ctx)
        deltas.append(after - before)
        done += 1
        print(f"  [{n}/{len(todo)}] {job['match']['detected_role'][:16]:16s} "
              f"{before:.2f} -> {after:.2f}  {str(job.get('company',''))[:24]}", flush=True)
        if done % CHECKPOINT_EVERY == 0:
            ANALYZED.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  … checkpoint ({done} scored)", flush=True)
        time.sleep(args.sleep)

    ANALYZED.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nscored {done}, failed {failed}")
    if deltas:
        print(f"composite change: mean {statistics.mean(deltas):+.3f}  "
              f"median {statistics.median(deltas):+.3f}  "
              f"up {sum(1 for d in deltas if d > 0)}  down {sum(1 for d in deltas if d < 0)}")
    thr = config.get("match_score_threshold")
    rest = [j["match"]["composite_score"] for j in jobs
            if (j.get("match") or {}).get("detected_role") not in DESIGN_ROLES
            and (j.get("match") or {}).get("composite_score") is not None]
    now = [j["match"]["composite_score"] for j in todo]
    print(f"\nthreshold is {thr}. design-role mean is now {statistics.mean(now):.3f}, "
          f"everything else {statistics.mean(rest):.3f} on the previous scale.")
    print("Two scales. Rescore the rest before trusting a ranking that mixes them.")


if __name__ == "__main__":
    main()
