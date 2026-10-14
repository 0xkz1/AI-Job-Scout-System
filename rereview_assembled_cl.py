"""Review the assembled cover letters, bridge only.

Every stored CL review predates the rescope: they judged the whole letter on
the CV's rubric, so they scored identity paragraphs that are identical in all
of them and marked down a stack the letter deliberately leaves to the CV. Their
scores were voided by null_stale_cl_scores.py; this replaces the findings.

Only letters the assembler produced are reviewed. A legacy-template letter has
no bridge to scope the review to, and re-reading one costs a call to describe a
document that will be replaced rather than fixed.

Resumable: a letter whose review is already current is skipped, so an
interrupted run continues where it stopped.

  python rereview_assembled_cl.py --limit 5
  python rereview_assembled_cl.py
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import reviewer
from matcher import make_safe_name

ROOT = Path(__file__).resolve().parent
LETTERS = ROOT / "10_output" / "10_cover-letters"
ANALYZED = ROOT / "10_output" / "_analyzed.json"


def assembled_letters() -> list[Path]:
    return [p for p in sorted(LETTERS.glob("*_CL.md"))
            if 'generation_mode: "assembler"' in p.read_text(encoding="utf-8")]


def jobs_by_base() -> dict[str, dict]:
    raw = json.loads(ANALYZED.read_text(encoding="utf-8"))
    jobs = list(raw.values()) if isinstance(raw, dict) else raw
    out = {}
    for job in jobs:
        base = make_safe_name(job.get("company", ""), job.get("title", ""))
        # First writer wins: duplicates resolve to the same filename and the
        # report on disk was rendered from one of them.
        out.setdefault(base, job)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    index = jobs_by_base()
    todo = []
    for path in assembled_letters():
        try:
            current, _ = reviewer.review_is_current(path)
        except Exception:
            current = False
        if current:
            continue
        job = index.get(path.name[: -len("_CL.md")])
        if job:
            todo.append((path, job))

    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} to review")

    done = failed = 0
    for n, (path, job) in enumerate(todo, 1):
        try:
            out = reviewer.run_review("CL", path, job)
        except Exception as e:
            print(f"  ⚠ {job.get('company', '')[:24]}: {str(e)[:70]}", flush=True)
            failed += 1
            time.sleep(2)
            continue
        text = out.read_text(encoding="utf-8")
        blocked = "fact_block: true" in text
        nits = text.split("style_nits:")[1].split("\n")[0].strip() if "style_nits:" in text else "?"
        print(f"  [{n}/{len(todo)}] {'⛔事実' if blocked else 'ok'} nits {nits:>2}  "
              f"{job.get('company', '')[:30]}", flush=True)
        done += 1
        time.sleep(args.sleep)

    print(f"\nreviewed {done}, failed {failed}")


if __name__ == "__main__":
    main()
