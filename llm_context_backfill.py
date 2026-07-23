"""LLM context scoring, decoupled from document generation.

`run.py --reanalyze --llm-context` also regenerates every CV/CL (slow, and a
past source of multi-minute hangs) and only saves _analyzed.json once at the
very end — a kill mid-run loses all the scoring work. This script does the
opposite: it ONLY updates match.context_score via the LLM and rewrites
_analyzed.json, checkpointing every few jobs so an interrupt keeps progress.
It never touches generated documents.

Why it matters (option A): the TF-IDF fallback can't tell "UI Designer" from
"Gas Designer" — both saturate to a high context score on shared vocabulary.
matcher.py caps TF-IDF context and blocks TF-IDF-only jobs from "Strong Match"
(option B). This script is option A: it replaces those word-overlap guesses
with a real semantic read, so genuine matches regain a full score and
off-domain jobs (gas mains, etc.) get correctly demoted.

Incremental: jobs already tagged context_source=="llm" are skipped unless
--force. --limit N scores only the top N by current composite (the ones where
the Strong/Good boundary actually matters). Runs against whatever provider
.env selects (ANALYSIS_PROVIDER, currently Mistral cloud — no local Ollama
needed despite the internal function name).

Usage:
  .venv/bin/python3 llm_context_backfill.py               # all un-scored jobs
  .venv/bin/python3 llm_context_backfill.py --limit 150   # top 150 by composite
  .venv/bin/python3 llm_context_backfill.py --force        # re-score everything
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values
for k, v in dotenv_values(ROOT / ".env").items():
    if v:
        os.environ.setdefault(k, v)

from matcher import (  # noqa: E402
    _ollama_context_score, _ollama_job_summary, _load_persona_summary,
    translate_to_ja,
)

ANALYZED_PATH = ROOT / "10_output" / "_analyzed.json"
CHECKPOINT_EVERY = 5
# Only jobs at/above this composite get a Japanese translation of their
# reasoning — matches the notify threshold, so exactly the jobs that surface
# to the user (report/Telegram) carry bilingual text; the rest stay EN-only.
JA_MIN = float(os.environ.get("SCOUT_NOTIFY_MIN", "0.70"))
# Bilingual job summary threshold — mirrors matcher.analyze_match's own
# "50%+ matches" rule (see its "A) Bilingual job summary" comment). Wider net
# than JA_MIN because a summary is cheap context for a still-maybe job, not
# a translated verdict on a near-certain one.
SUMMARY_MIN = 0.50


def _pseudo_description(job: dict) -> str:
    """Same fallback shape matcher/run use when a job has no real description."""
    desc = job.get("description", "") or job.get("snippet", "")
    if desc and len(desc) > 50:
        return desc
    a = job.get("analysis", {})
    parts = [job.get("title", ""), job.get("company", "")]
    if a.get("skills"):
        parts.append("Skills: " + ", ".join(a["skills"]))
    if a.get("experience_level"):
        parts.append(f"Experience level: {a['experience_level']}")
    if a.get("work_style") and a["work_style"] != "unknown":
        parts.append(f"Work style: {a['work_style']}")
    return ". ".join(p for p in parts if p)


def _recompute(job: dict, ctx_score: float) -> None:
    """Rewrite composite + tier for a freshly LLM-scored job. Mirrors
    matcher.analyze_match: an LLM context source is allowed to reach the top
    tier (unlike the TF-IDF fallback, which is capped there)."""
    m = job["match"]
    w = m.get("weights") or {"skills": 0.4, "experience": 0.25,
                             "location": 0.1, "salary": 0.05, "context": 0.2}
    composite = (
        m.get("skills", {}).get("score", 0) * w["skills"]
        + m.get("experience", {}).get("score", 0) * w["experience"]
        + m.get("location", {}).get("score", 0) * w["location"]
        + m.get("salary", {}).get("score", 0) * w["salary"]
        + ctx_score * w["context"]
    )
    m["composite_score"] = round(composite, 2)
    if composite >= 0.8:
        m["tier"] = "🟢 Strong Match"
    elif composite >= 0.6:
        m["tier"] = "🟡 Good Match"
    elif composite >= 0.4:
        m["tier"] = "🟠 Partial Match"
    else:
        m["tier"] = "🔴 Weak Match"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                     help="score only the top N jobs by current composite")
    ap.add_argument("--force", action="store_true",
                     help="re-score even jobs already tagged context_source=llm")
    args = ap.parse_args()

    try:
        jobs = json.loads(ANALYZED_PATH.read_text())
    except Exception as e:
        print(f"❌ _analyzed.json を読めません: {e}")
        return 1

    persona = _load_persona_summary()
    if not persona:
        print("❌ persona summary が空 — 中断")
        return 1

    ranked = sorted(jobs, key=lambda j: j.get("match", {}).get("composite_score", 0), reverse=True)
    if args.limit:
        ranked = ranked[:args.limit]

    todo = [
        j for j in ranked
        if j.get("match")
        and (args.force or j["match"].get("context_source") != "llm")
        and not j["match"].get("description_missing")
    ]
    print(f"[{time.strftime('%H:%M:%S')}] LLM context: {len(todo)} 件を採点 "
          f"(全{len(jobs)}件中、上限={args.limit or 'なし'}, force={args.force})", flush=True)

    done, failed, promoted, demoted = 0, 0, 0, 0
    for i, job in enumerate(todo, 1):
        desc = _pseudo_description(job)
        if not desc or len(desc) <= 30:
            continue
        before = job["match"].get("composite_score", 0)
        try:
            # brief: score gates filtering; the long bilingual reasoning is
            # added lazily only to the high-match reports that display it.
            ctx = _ollama_context_score(desc, persona, brief=True)
        except Exception as e:
            failed += 1
            print(f"  ✗ {job.get('company','?')[:25]}: {str(e)[:60]}", flush=True)
            continue
        if ctx is None:
            failed += 1
            continue
        job["match"]["context_score"] = ctx["score"]
        job["match"]["context_reasoning"] = ctx.get("reasoning", "")
        job["match"]["context_reasoning_en"] = ctx.get("reasoning_en", "")
        job["match"]["context_reasoning_ja"] = ctx.get("reasoning_ja", "")
        job["match"]["context_source"] = "llm"
        _recompute(job, ctx["score"])
        after = job["match"]["composite_score"]
        if after - before >= 0.05:
            promoted += 1
        elif before - after >= 0.05:
            demoted += 1
        done += 1
        if done % CHECKPOINT_EVERY == 0:
            ANALYZED_PATH.write_text(json.dumps(jobs, indent=2, ensure_ascii=False, default=str))
            print(f"  [{time.strftime('%H:%M:%S')}] {done}/{len(todo)} 採点済 "
                  f"(↑{promoted} ↓{demoted}) — チェックポイント保存", flush=True)

    ANALYZED_PATH.write_text(json.dumps(jobs, indent=2, ensure_ascii=False, default=str))
    print(f"[{time.strftime('%H:%M:%S')}] 採点完了: {done} 採点, {failed} 失敗 "
          f"(スコア上昇 {promoted} / 下降 {demoted}) — 保存済", flush=True)

    # Japanese pass: only high-match jobs, only if they have EN reasoning but
    # no JA yet. Keeps the bulk scoring English-only/fast while the reports
    # that users actually read stay bilingual.
    ja_todo = [
        j for j in jobs
        if j.get("match", {}).get("composite_score", 0) >= JA_MIN
        and j["match"].get("context_reasoning_en")
        and not j["match"].get("context_reasoning_ja")
    ]
    if ja_todo:
        print(f"[{time.strftime('%H:%M:%S')}] 和訳: 高マッチ {len(ja_todo)} 件 "
              f"(>= {JA_MIN:.0%})", flush=True)
        ja_done = 0
        for j in ja_todo:
            m = j["match"]
            ja = translate_to_ja(m["context_reasoning_en"])
            if not ja:
                continue
            m["context_reasoning_ja"] = ja
            m["context_reasoning"] = f"{m['context_reasoning_en']}\n\n**和訳:** {ja}"
            ja_done += 1
            if ja_done % CHECKPOINT_EVERY == 0:
                ANALYZED_PATH.write_text(json.dumps(jobs, indent=2, ensure_ascii=False, default=str))
        ANALYZED_PATH.write_text(json.dumps(jobs, indent=2, ensure_ascii=False, default=str))
        print(f"[{time.strftime('%H:%M:%S')}] 和訳完了: {ja_done}/{len(ja_todo)} — 保存済", flush=True)

    # Summary pass (EN-first): generate English-only job summaries for jobs at
    # SUMMARY_MIN+ that don't have one yet. run.py --llm-context used to
    # generate these bilingual in one call as part of the same pass; splitting
    # mirrors the context-reasoning treatment above — EN is cheap and covers
    # every maybe-relevant job, JA is added lazily only where it will be read.
    sum_todo = [
        j for j in jobs
        if j.get("match", {}).get("composite_score", 0) >= SUMMARY_MIN
        and not j.get("match", {}).get("summary_en")
        and (j.get("description") or j.get("snippet"))
    ]
    if sum_todo:
        print(f"[{time.strftime('%H:%M:%S')}] 概要文(EN): {len(sum_todo)} 件 "
              f"(>= {SUMMARY_MIN:.0%}, 未生成)", flush=True)
        sum_done = 0
        for j in sum_todo:
            desc = j.get("description", "") or j.get("snippet", "")
            if not desc or len(desc) < 50:
                continue
            try:
                s = _ollama_job_summary(desc, en_only=True)
            except Exception as e:
                print(f"  ✗ {j.get('company','?')[:25]} summary: {str(e)[:50]}", flush=True)
                continue
            if not s:
                continue
            j["match"]["summary_en"] = s.get("summary_en", "")
            sum_done += 1
            if sum_done % CHECKPOINT_EVERY == 0:
                ANALYZED_PATH.write_text(json.dumps(jobs, indent=2, ensure_ascii=False, default=str))
                print(f"  [{time.strftime('%H:%M:%S')}] {sum_done}/{len(sum_todo)} 概要文(EN)生成済", flush=True)
        ANALYZED_PATH.write_text(json.dumps(jobs, indent=2, ensure_ascii=False, default=str))
        print(f"[{time.strftime('%H:%M:%S')}] 概要文(EN)完了: {sum_done}/{len(sum_todo)} — 保存済", flush=True)

    # Summary JA pass: only high-match jobs (same JA_MIN as context reasoning)
    # that have an EN summary but no JA yet.
    sum_ja_todo = [
        j for j in jobs
        if j.get("match", {}).get("composite_score", 0) >= JA_MIN
        and j["match"].get("summary_en")
        and not j["match"].get("summary_ja")
    ]
    if sum_ja_todo:
        print(f"[{time.strftime('%H:%M:%S')}] 概要文(和訳): 高マッチ {len(sum_ja_todo)} 件 "
              f"(>= {JA_MIN:.0%})", flush=True)
        sum_ja_done = 0
        for j in sum_ja_todo:
            m = j["match"]
            ja = translate_to_ja(m["summary_en"])
            if not ja:
                continue
            m["summary_ja"] = ja
            sum_ja_done += 1
            if sum_ja_done % CHECKPOINT_EVERY == 0:
                ANALYZED_PATH.write_text(json.dumps(jobs, indent=2, ensure_ascii=False, default=str))
        ANALYZED_PATH.write_text(json.dumps(jobs, indent=2, ensure_ascii=False, default=str))
        print(f"[{time.strftime('%H:%M:%S')}] 概要文(和訳)完了: {sum_ja_done}/{len(sum_ja_todo)} — 保存済", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
