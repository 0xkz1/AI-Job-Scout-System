"""Fill in missing Reed job locations from each posting's structured data.

Reed's search-results markup only yields a location when it matches a hardcoded
city shortlist (edinburgh/glasgow/london/remote/united kingdom), so anything
else — Liverpool, Manchester, Leeds — was stored blank, and a blank location
scores as if the job were local. scraper_reed now reads jobLocation from the
detail page's Schema.org JSON-LD, but jobs collected before that fix keep their
empty value.

Re-running the scraper would fix them only as a side effect of re-fetching
630 search pages through a browser. Locations live on the detail pages, which
are plain HTTP, so this walks the already-collected jobs instead and asks each
posting directly.

Usage:
  .venv/bin/python3 backfill_reed_locations.py --dry-run
  .venv/bin/python3 backfill_reed_locations.py
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scraper_reed import _fetch_reed_description_sync  # noqa: E402

ANALYZED = ROOT / "10_output" / "_analyzed.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--sleep", type=float, default=0.4)
    args = ap.parse_args()

    jobs = json.loads(ANALYZED.read_text(encoding="utf-8"))
    targets = [
        j for j in jobs
        if j.get("source") == "reed"
        and not (j.get("location") or "").strip()
        and (j.get("url") or "").strip()
    ]
    if args.limit:
        targets = targets[:args.limit]

    print(f"[{time.strftime('%H:%M:%S')}] location欠損のReed求人: {len(targets)}件", flush=True)
    if args.dry_run:
        for j in targets[:10]:
            print(f"  {j.get('company','')[:30]:30s} {j.get('title','')[:40]}")
        print("  ...")
        return 0

    backup = ANALYZED.with_suffix(f".bak_{datetime.now():%Y%m%d_%H%M%S}.json")
    shutil.copyfile(ANALYZED, backup)
    print(f"  backup: {backup.name}", flush=True)

    filled = failed = 0
    for i, job in enumerate(targets, 1):
        try:
            result = _fetch_reed_description_sync(job["url"])
            loc = (result.get("location") or "").strip()
            if loc:
                job["location"] = loc
                filled += 1
            else:
                failed += 1
        except Exception:
            failed += 1
        if i % 25 == 0:
            print(f"  [{i}/{len(targets)}] 取得済み {filled}件 / 取得不可 {failed}件", flush=True)
        if args.sleep:
            time.sleep(args.sleep)

    ANALYZED.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[{time.strftime('%H:%M:%S')}] 完了: {filled}件にlocationを補完, {failed}件は取得できず", flush=True)
    print("  次: マッチ再分析でlocation_scoreを反映させること", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
