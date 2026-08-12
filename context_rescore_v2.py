"""Rescore context with the two-axis prompt, alongside the score in use.

The single-axis prompt asks whether a job suits the candidate's ethos, and
0.64 of the composite rests on the answer. It scores what it was asked: an
n8n Billing Specialist reached 92 because "reduce friction, automate" is a
real match of values, while the work is accounting. Reweighting cannot
separate "I would like this" from "I could do this" — a refit lost on all five
folds, and capping context by skills lost at every margin.

Asking for both axes separately fixes it, but not the way it was meant to.
`role_fit` adds nothing once blended (both pilots: pure ethos scores highest,
and every added part of role_fit lowers it). What the second axis does is make
the FIRST one strict: postings the old prompt gave 85 come back at 15-20 once
the model has somewhere else to put "the work is adjacent". Two pilots of 40
against stored CV review scores: +0.183 -> +0.477 and +0.317 -> +0.395.

Writes `context_score_v2` next to `context_score` and never overwrites the
score in use, so the two can be compared on the whole corpus before anything
switches over, and a bad run costs only the calls it made.

  python context_rescore_v2.py --limit 50     # try it
  python context_rescore_v2.py                # everything still unscored
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import selection
from filter import passes_filter

ANALYZED = Path(__file__).resolve().parent / "10_output" / "_analyzed.json"
CHECKPOINT_EVERY = 20

PROMPT = """You are a career alignment analyst. Rate this job against the candidate on TWO separate axes.

## Candidate Profile
{persona}

## Job Description
{description}

## Task
Score each axis 0-100, independently. Do not let one influence the other.

1. `ethos` — would this candidate WANT this job? Work philosophy, values, creative vs corporate culture, autonomy, multi-disciplinary creative-engineer fit.

2. `role_fit` — could this candidate DO this job? Judge the actual duties and required expertise against what the profile evidences. This is where a job that shares the candidate's values but demands expertise they do not have must score low. Ask what the posting says the person will DO all day, and whether the profile shows that work having been done. A posting whose core requirement appears nowhere in the profile scores under 30 on this axis no matter how appealing the company is.

Name the core requirement you judged `role_fit` on, in `role_requirement`.

Note: The candidate is deployment-agnostic. They run local models in personal research and standard enterprise cloud (AWS, hosted model APIs, managed services, third-party SaaS) in professional work, choosing per constraint — latency, cost, privacy, team toolchain — not per preference. This is portability, NOT a local-first bias. Do NOT describe the candidate as "local-first", do NOT treat a cloud or enterprise stack as a mismatch, and do NOT mention local-vs-cloud at all.

Respond ONLY with JSON:
{{"ethos": <0-100>, "role_fit": <0-100>, "role_requirement": "<the duty or expertise you judged role_fit on>", "reasoning_en": "<3-4 short, plain sentences>"}}
Plain prose only — no markdown, no bullets, no labels."""


def _load() -> tuple[list[dict], object]:
    raw = json.loads(ANALYZED.read_text(encoding="utf-8"))
    return (list(raw.values()), raw) if isinstance(raw, dict) else (raw, raw)


def due(jobs: list[dict], config: dict) -> list[dict]:
    """Jobs whose v2 score is worth paying for.

    A posting the filter drops, or one with too little description to score,
    never reaches a ranking — buying it a second opinion spends a call on an
    answer nothing reads.

    tfidf-scored jobs are included, not just LLM-scored ones. Restricting the
    first pass to context_source == "llm" left 828 jobs holding the TF-IDF
    fallback, which returns ~0.50 whenever it cannot find vocabulary overlap —
    a number that meant "no opinion" while everything around it meant "would
    want this job". Once the LLM scores were remeasured as "could do this job"
    and fell to a mean of 0.272, that inert 0.50 became a high score by
    standing still: 315 of them cleared the new floor, and a Senior Civil
    Engineer surfaced into the generation set. Two scales in one ranking rank
    nothing.
    """
    out = []
    for job in jobs:
        m = job.get("match") or {}
        if m.get("context_score") is None:
            continue
        if m.get("context_score_v2") is not None or m.get("context_ethos") is not None:
            continue
        if not passes_filter(job, config)[0] or selection.is_unscoreable(job):
            continue
        out.append(job)
    return out


def score_one(job: dict, persona: str) -> dict | None:
    from llm_client import call_llm

    content = call_llm(
        messages=[{"role": "user", "content": PROMPT.format(
            # 14,000 rather than 9,000: the persona is capped per file now, and
            # at 9,000 the window still ended inside timeline.md, so ethos.md —
            # the document the first axis is named after — never reached the
            # model at all. 14,000 admits profile, skills, timeline, about and
            # ethos, which is every file either axis is judged on.
            persona=persona[:14000],
            description=(job.get("description") or "")[:5000])}],
        system_prompt=("You are a career alignment scoring engine. Output ONLY valid JSON. "
                       "The candidate is deployment-agnostic: cloud and local are equally "
                       "normal for them. Never call them local-first."),
        temperature=0.1, max_tokens=400,
    )
    for match in reversed(list(re.finditer(r"\{.*\}", content, re.DOTALL))):
        try:
            data = json.loads(match.group(), strict=False)
            ethos = float(data["ethos"])
            role_fit = float(data["role_fit"])
        except Exception:
            continue
        if not (0 <= ethos <= 100 and 0 <= role_fit <= 100):
            continue
        return {"ethos": ethos, "role_fit": role_fit,
                "role_requirement": str(data.get("role_requirement", ""))[:200],
                "reasoning": str(data.get("reasoning_en", ""))[:1200]}
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="stop after N (0 = all)")
    ap.add_argument("--sleep", type=float, default=0.4)
    args = ap.parse_args()

    # _load_persona_summary, not _get_context_text: the first is what
    # _ollama_context_score reads in production, and the two build different
    # text from different files. Scoring against the second measured a persona
    # no live scoring path has ever seen.
    from matcher import _load_persona_summary
    jobs, container = _load()
    config = selection.load_config()
    todo = due(jobs, config)
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} to score")
    if not todo:
        return

    persona = _load_persona_summary()
    done = failed = 0
    for n, job in enumerate(todo, 1):
        try:
            result = score_one(job, persona)
        except Exception as e:
            print(f"  ⚠ {job.get('company','')[:24]}: {str(e)[:70]}", flush=True)
            failed += 1
            time.sleep(2)
            continue
        if not result:
            failed += 1
            continue
        m = job["match"]
        # Only `ethos` becomes the score. role_fit is kept because it is what
        # made ethos strict and because it is the reader's evidence, but both
        # pilots put its best blend weight at zero.
        m["context_score_v2"] = result["ethos"] / 100.0
        m["context_v2"] = result
        done += 1
        print(f"  [{n}/{len(todo)}] {m['context_score']*100:3.0f} -> {result['ethos']:3.0f} "
              f"(role {result['role_fit']:3.0f})  {job.get('company','')[:26]}", flush=True)
        if done % CHECKPOINT_EVERY == 0:
            ANALYZED.write_text(json.dumps(container, ensure_ascii=False, indent=2),
                                encoding="utf-8")
            print(f"  … checkpoint ({done} scored)", flush=True)
        time.sleep(args.sleep)

    ANALYZED.write_text(json.dumps(container, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nscored {done}, failed {failed}")


if __name__ == "__main__":
    main()
