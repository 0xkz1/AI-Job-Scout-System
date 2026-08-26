"""Re-score the database and write nothing else.

`run.py --reanalyze` is the obvious way to apply a scoring change to jobs
already on disk, and it does far more than score: it runs the whole downstream
pipeline, selecting jobs, generating CVs and cover letters and reviewing them.
On 2026-08-26 that rewrote 70 CVs and 65 letters as a side effect of what was
meant to be a re-scoring pass, and one letter came back degraded to
`assembled-static` — the state where the tailored opening has been lost.
run.py currently has no guard against overwriting a document that already
exists, so there is nothing between a scoring pass and the application
documents.

So: this scores, and stops. It never reads or writes 10_cvs, 10_cover-letters,
15_reviews or 00_matches. Re-render the reports afterwards with
regen_match_reports.py, which preserves the applied/expired locks.

It still costs model calls — analyze_match reaches the LLM for any job whose
context has never been read, and for the second draw when skills and context
contradict each other. match_all decides per job whether that call is worth
making, and a job the filter has already rejected does not buy one.

Usage:
    python3 rescore_only.py                    # score 10_output/_analyzed.json in place
    python3 rescore_only.py --from BACKUP.json # score a backup, write to _analyzed.json
    python3 rescore_only.py --dry-run          # count the model calls, change nothing
    python3 rescore_only.py --no-dedupe        # skip duplicate merging
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
import matcher  # noqa: E402
from run import match_all, dedupe_by_company_title  # noqa: E402

DB = ROOT / "10_output" / "_analyzed.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="source", default=None,
                    help="score this file instead of the live database")
    ap.add_argument("--dry-run", action="store_true",
                    help="stub the context scorer and report how many calls it would make")
    ap.add_argument("--no-dedupe", action="store_true",
                    help="do not merge duplicate postings first")
    args = ap.parse_args()

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    source = Path(args.source) if args.source else DB
    if not source.exists():
        print(f"❌ {source} does not exist")
        return 1

    jobs = json.loads(source.read_text(encoding="utf-8"))
    print(f"📂 {len(jobs)} jobs from {source.name}")

    if not args.no_dedupe:
        jobs, archived = dedupe_by_company_title(jobs)
        print(f"🔀 {len(archived)} merged away, {len(jobs)} remain")

    calls = {"n": 0}
    if args.dry_run:
        real = matcher._ollama_context_score

        def stub(*a, **k):
            calls["n"] += 1
            return {"score": 0.5, "reasoning": "", "reasoning_en": "", "provider": "dry-run"}

        matcher._ollama_context_score = stub

    started = time.time()
    try:
        failures = match_all(jobs, config, label="rescored", skip_summary=True)
    finally:
        if args.dry_run:
            matcher._ollama_context_score = real

    took = time.time() - started
    print(f"⏱  {took/60:.1f} min, {failures} jobs left unscored")

    if args.dry_run:
        print(f"🧪 dry run: {calls['n']} context calls would have been made. Nothing written.")
        return 0

    # Backed up because this rewrites the one file every later stage reads, and
    # a scoring change that turns out wrong is otherwise unrecoverable.
    if DB.exists():
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = DB.with_name(f"_analyzed.bak_pre_rescore_{stamp}.json")
        shutil.copy2(DB, backup)
        print(f"💾 previous database kept at {backup.name}")

    DB.write_text(json.dumps(jobs, indent=2, ensure_ascii=False, default=str),
                  encoding="utf-8")
    print(f"✅ {len(jobs)} jobs written to {DB.name}")
    print("   Documents untouched. Run regen_match_reports.py to re-render 00_matches.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
