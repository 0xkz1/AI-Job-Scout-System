#!/usr/bin/env python3
"""Summarise what the pipeline's LLM calls actually cost, per stage.

`llm_client.record_llm_call` appends one row per call to the file named by
JIS_LLM_STATS_FILE — stage, provider, elapsed, prompt chars, max_tokens,
outcome. This reads them back.

It exists because the tiering decision could not otherwise be made honestly.
Assigning a cheap model to "analysis" and an expensive one to "review" assumes
the stages are what their names suggest, and the one time that was checked it
was wrong: url-list extraction reads 15,000 characters and reproduces a whole
job description at max_tokens=4096, which is not a light task however light
"extraction" sounds. The token budgets each call site asks for are a better
guide than the stage name, and the measured time is better than either.

Usage:
    python3 llm_stats.py                        # today's nightly stats
    python3 llm_stats.py --file <path>          # a specific stats file
    python3 llm_stats.py --by provider          # group by provider instead
"""
import argparse
import collections
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT = ROOT / "10_output" / "_llm_stats.tsv"


def load(path: Path) -> list[dict]:
    rows = []
    try:
        for line in path.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) != 6:
                continue
            try:
                rows.append({
                    "stage": parts[0], "provider": parts[1],
                    "elapsed": float(parts[2]), "prompt_chars": int(parts[3]),
                    "max_tokens": int(parts[4]), "outcome": parts[5],
                })
            except ValueError:
                continue
    except OSError:
        pass
    return rows


def summarise(rows: list[dict], key: str) -> None:
    if not rows:
        print("no rows — was JIS_LLM_STATS_FILE set for the run?")
        return

    groups = collections.defaultdict(list)
    for r in rows:
        groups[r[key]].append(r)

    print(f"{key:22} {'calls':>6} {'ok':>5} {'fail':>5} "
          f"{'total_s':>9} {'median_s':>9} {'p90_s':>8} {'med_chars':>10}")
    print("-" * 88)
    # Sorted by total seconds: the question this is asked to answer is always
    # "where did the night go", and that is a sum, not an average.
    for name, rs in sorted(groups.items(), key=lambda kv: -sum(r["elapsed"] for r in kv[1])):
        el = sorted(r["elapsed"] for r in rs)
        ok = sum(1 for r in rs if r["outcome"] == "ok")
        chars = sorted(r["prompt_chars"] for r in rs)
        print(f"{name:22} {len(rs):>6} {ok:>5} {len(rs)-ok:>5} "
              f"{sum(el):>9.1f} {el[len(el)//2]:>9.1f} "
              f"{el[int(len(el)*0.9)] if len(el) > 1 else el[0]:>8.1f} "
              f"{chars[len(chars)//2]:>10}")

    total = sum(r["elapsed"] for r in rows)
    fails = sum(1 for r in rows if r["outcome"] != "ok")
    print("-" * 88)
    print(f"{'TOTAL':22} {len(rows):>6} {len(rows)-fails:>5} {fails:>5} {total:>9.1f}")

    # A chain that falls through is the cost nobody sees: the failed attempt is
    # paid for in full before the next provider is tried.
    if fails:
        wasted = sum(r["elapsed"] for r in rows if r["outcome"] != "ok")
        print(f"\n{wasted:.1f}s ({wasted/total*100:.0f}%) spent on calls that did not answer:")
        by = collections.Counter((r["provider"], r["outcome"])
                                 for r in rows if r["outcome"] != "ok")
        for (prov, outcome), n in by.most_common(8):
            print(f"  {n:4} x {prov} {outcome}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", default=os.environ.get("JIS_LLM_STATS_FILE") or str(DEFAULT))
    ap.add_argument("--by", default="stage", choices=["stage", "provider", "outcome"])
    args = ap.parse_args()

    path = Path(args.file)
    rows = load(path)
    print(f"{path}  ({len(rows)} calls)\n")
    summarise(rows, args.by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
