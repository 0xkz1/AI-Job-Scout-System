"""Re-score every job, then rebuild and review the top 56 applications.

Run after backfill_reed_locations.py: the restored locations change
location_score, which changes composite_score, which changes *which* jobs are
the top 56 — so the CVs and cover letters have to be rebuilt against the new
ranking rather than the one they were generated for.

Phases:
  A. re-analyse  — recompute match scores for all jobs (run.py --reanalyze)
  B. regenerate  — rebuild top-56 cover letters (and any missing CVs)
  C. review      — re-review the top-56 CV/CL pairs

Usage:
  .venv/bin/python3 -u _pipeline_top56.py
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = str(ROOT / ".venv" / "bin" / "python3")


def run(label: str, cmd: list[str]) -> bool:
    print(f"\n{'='*64}\n[{time.strftime('%H:%M:%S')}] {label}\n{'='*64}", flush=True)
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        print(f"  ✗ {label} failed (exit {proc.returncode})", flush=True)
        return False
    return True


def main() -> int:
    if not run("PHASE A: マッチ再分析 (location反映)",
               [PY, "-u", "run.py", "--reanalyze"]):
        return 1
    if not run("PHASE B: CL再生成 (top56, ethos+projects改修版)",
               [PY, "-u", "regen_top_docs.py", "--limit", "56"]):
        return 1
    if not run("PHASE C: 再レビュー (top56 CV+CL)",
               [PY, "-u", "rereview_top.py", "--limit", "56"]):
        return 1
    print(f"\n[{time.strftime('%H:%M:%S')}] 全工程完了", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
