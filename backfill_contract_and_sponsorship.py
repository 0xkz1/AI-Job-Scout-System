#!/usr/bin/env python3
"""Backfill contract_kind / contract_months / sponsorship onto the existing DB.

The four fields are computed by analyze_job, so every posting scraped from now on
carries them. The 5202 already in _analyzed.json do not, and re-running analyze_job
over them is not an option: it would recompute skills and experience_level from the
cheap pass and overwrite LLM enrichment that has already been paid for.

So this writes ONLY the four new keys, from the title and description already
stored, and touches nothing else. No model calls — all four are regex.

Idempotent: a posting that already carries `sponsorship` is skipped unless
--force, so a second run costs nothing and cannot drift.

Usage:
    python3 backfill_contract_and_sponsorship.py            # dry run
    python3 backfill_contract_and_sponsorship.py --apply    # write (backs up first)
    python3 backfill_contract_and_sponsorship.py --apply --force   # recompute all
"""
import argparse
import collections
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from analyzer import (  # noqa: E402
    classify_contract_kind,
    classify_sponsorship,
    contract_duration_months,
)

ANALYZED = ROOT / "10_output" / "_analyzed.json"

# Only these keys are ever written. Named explicitly rather than merged from a
# dict, so a future field cannot ride along into a backfill run by accident.
FIELDS = ("contract_kind", "contract_months", "sponsorship", "sponsorship_evidence")


def compute(job: dict) -> dict:
    title = job.get("title") or ""
    description = job.get("description") or job.get("snippet") or ""
    state, evidence = classify_sponsorship(title, description)
    return {
        "contract_kind": classify_contract_kind(title, description),
        "contract_months": contract_duration_months(title, description),
        "sponsorship": state,
        "sponsorship_evidence": evidence,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the database")
    ap.add_argument("--force", action="store_true",
                    help="recompute postings that already carry the fields")
    args = ap.parse_args()

    if not ANALYZED.exists():
        print(f"no database at {ANALYZED}")
        return 1

    jobs = json.loads(ANALYZED.read_text(encoding="utf-8"))
    kinds, months, sponsor = collections.Counter(), collections.Counter(), collections.Counter()
    written, already, no_analysis = 0, 0, 0

    for job in jobs:
        analysis = job.get("analysis")
        if not isinstance(analysis, dict):
            # Never scored at all. Creating an `analysis` here would fake a
            # cheap-pass result that no other field backs up.
            no_analysis += 1
            continue
        if "sponsorship" in analysis and not args.force:
            already += 1
            kinds[analysis.get("contract_kind")] += 1
            months[bool(analysis.get("contract_months"))] += 1
            sponsor[analysis.get("sponsorship")] += 1
            continue
        values = compute(job)
        kinds[values["contract_kind"]] += 1
        months[bool(values["contract_months"])] += 1
        sponsor[values["sponsorship"]] += 1
        if args.apply:
            analysis.update(values)
        written += 1

    if args.apply:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = ANALYZED.with_name(f"_analyzed.bak_{stamp}.json")
        shutil.copy2(ANALYZED, backup)
        # Same serialisation run.py uses (indent=2, ensure_ascii=False,
        # default=str). A compact rewrite would reformat all 44MB and make every
        # future diff of this file useless.
        with open(ANALYZED, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False, default=str)
        print(f"  backup: {backup.name}")

    print(f"\ncomputed={written} already_present={already} no_analysis={no_analysis} "
          f"apply={args.apply}")
    print(f"  contract_kind:    {dict(kinds)}")
    print(f"  contract_months:  stated={months[True]} unstated={months[False]}")
    print(f"  sponsorship:      {dict(sponsor)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
