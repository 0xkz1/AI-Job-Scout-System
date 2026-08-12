"""Put the corpus onto one context scale — the persona that carries the design work.

Measured against 387 stored CV reviews, role_fit undershot graphic_designer
postings by 23.2 points and product_designer by 12.8, because the persona
evidenced engineering as work done and design mostly as asserted skill. The
persona now carries education.md and five portfolio files. On the 179
design-role postings that have a stored review, before and after, the residual
moved +26.3 -> +22.8, 95% CI [-5.5, -1.5]: real, separable, and far short of
closing the gap.

The design roles went first, which left the corpus holding two scales — and two
scales in one ranking rank nothing (5dedcf8). This finishes the job. Run it with
no --roles to rescore everything eligible that is not already on the current
persona.

Which scale a posting is on used to be unanswerable: a rescored job whose score
did not move looked exactly like one that was never rescored. Every job this
writes is stamped with `context_persona_chars`, the length of the persona that
produced it, and anything already carrying the current one is skipped. Cheap,
self-describing, and enough to resume a half-finished pass.

tfidf-scored jobs are included. Their ~0.50 fallback means "no opinion", and
leaving it beside rescored LLM values repeats the failure 5dedcf8 documented: an
inert 0.50 becomes a high score by standing still while everything around it
moves.

  python rescore_context.py --dry-run              # what would be scored
  python rescore_context.py --roles design         # the design slice only
  python rescore_context.py --backfill-stamp       # mark an earlier pass, no calls
  python rescore_context.py                        # everything still stale
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


def due(jobs: list[dict], config: dict, roles: set[str] | None = None,
        persona_chars: int | None = None) -> list[dict]:
    """Postings a ranking will actually read, that are not already on this persona.

    A posting the filter drops, or one with too little description to score,
    never reaches a ranking — buying it a second opinion spends a call on an
    answer nothing reads.
    """
    out = []
    for job in jobs:
        m = job.get("match") or {}
        if roles is not None and m.get("detected_role") not in roles:
            continue
        if persona_chars is not None and m.get("context_persona_chars") == persona_chars:
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


def apply(job: dict, ctx: dict, persona_chars: int) -> tuple[float, float]:
    """Write the new context score and recompute the composite. Returns (before, after)."""
    m = job["match"]
    before = m["composite_score"]
    m["context_persona_chars"] = persona_chars
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
    ap.add_argument("--roles", choices=["all", "design"], default="all")
    ap.add_argument("--backfill-stamp", action="store_true",
                    help="stamp context_persona_chars on the design slice an "
                         "earlier pass already rescored, without making calls")
    args = ap.parse_args()

    raw = json.loads(ANALYZED.read_text(encoding="utf-8"))
    jobs = list(raw.values()) if isinstance(raw, dict) else raw
    config = selection.load_config()

    from matcher import _load_persona_summary, _ollama_context_score
    persona = _load_persona_summary()
    persona_chars = len(persona)

    if args.backfill_stamp:
        # The design pass predates the stamp. Its members are recoverable
        # because `due` is deterministic given the same corpus and config, and
        # `context_ethos` is only present on a two-axis reply — so this marks
        # what that pass actually wrote and nothing else.
        n = 0
        for job in due(jobs, config, roles=DESIGN_ROLES):
            m = job["match"]
            if m.get("context_ethos") is not None and "context_persona_chars" not in m:
                m["context_persona_chars"] = persona_chars
                n += 1
        ANALYZED.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"stamped {n} postings with context_persona_chars={persona_chars}")
        return

    roles = DESIGN_ROLES if args.roles == "design" else None
    todo = due(jobs, config, roles=roles, persona_chars=persona_chars)
    if args.limit:
        todo = todo[:args.limit]

    print(f"persona: {persona_chars} chars")
    print(f"{len(todo)} postings still on an older persona"
          + (f" (roles={args.roles})" if roles else ""))
    if args.dry_run or not todo:
        for j in todo[:15]:
            print(f"  {str(j['match'].get('detected_role')):18s} "
                  f"{j['match']['context_score']*100:3.0f}  {str(j.get('company'))[:30]}")
        return

    # The corpus is the product of every scoring run before this one; a failed
    # write partway through a several-hundred-call pass is not something to
    # re-derive.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ANALYZED.with_name(f"_analyzed.bak_pre_rescore_{stamp}.json")
    shutil.copy2(ANALYZED, backup)
    print(f"backup: {backup.name}\n")

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
        before, after = apply(job, ctx, persona_chars)
        deltas.append(after - before)
        done += 1
        print(f"  [{n}/{len(todo)}] {str(job['match'].get('detected_role'))[:16]:16s} "
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
    # Whether the corpus is on one scale yet, and what the threshold now means.
    # The threshold is a number on a distribution; move the distribution and it
    # stops meaning what it was set to mean. 5dedcf8 moved it 0.45 -> 0.32 for
    # exactly this reason, to hold pipeline volume rather than halve it for a
    # reason unrelated to the jobs.
    thr = config.get("match_score_threshold")
    eligible = due(jobs, config)
    stale = [j for j in eligible if j["match"].get("context_persona_chars") != persona_chars]
    scored = [j["match"]["composite_score"] for j in eligible
              if j["match"].get("context_persona_chars") == persona_chars]
    print(f"\n{len(stale)} eligible postings still on an older persona.")
    if scored:
        passing = sum(1 for s in scored if s >= thr)
        print(f"on the current persona: n={len(scored)}  mean {statistics.mean(scored):.3f}  "
              f"median {statistics.median(scored):.3f}  passing at {thr}: {passing}")
    if stale:
        print("Two scales. A ranking that mixes them ranks nothing — finish the pass "
              "before moving match_score_threshold.")
    else:
        print("One scale. match_score_threshold can be recalibrated against the "
              "distribution above.")


if __name__ == "__main__":
    main()
