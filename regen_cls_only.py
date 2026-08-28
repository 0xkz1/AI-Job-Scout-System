"""Rebuild the top-ranked COVER LETTERS only, leaving every CV untouched.

The sibling of regen_cvs_only.py, and it exists for the same reason in the
other direction: a change confined to the letter sources — the canonical
narrative, the evidence bank — makes every CV a no-op, and regen_top_docs.py
would still pay a CV generation pass for each pair. On 2026-08-28 the canonical
narrative went from 252 words to 170 and four fact blocks gained a role gate;
nothing a CV reads changed at all.

Locks are honoured exactly as the paired rebuild honours them: a hand-edited,
applied or expired job keeps the letter it has. The previous letter is copied
into .cls_archive first, because a fresh bridge can be rejected by its gates and
the archived one may be the better letter.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import os
from dotenv import dotenv_values
for _k, _v in dotenv_values(ROOT / ".env").items():
    if _v:
        os.environ[_k] = _v

import yaml  # noqa: E402
import gen_version  # noqa: E402
from matcher import make_safe_name  # noqa: E402
from selection import ranked_jobs  # noqa: E402
from cv_generator import detect_role_type  # noqa: E402
from cover_letter_generator import save_cover_letter  # noqa: E402

CV_DIR = ROOT / "10_output" / "10_cvs"
CL_DIR = ROOT / "10_output" / "10_cover-letters"
MATCH_DIR = ROOT / "10_output" / "00_matches"
ARCHIVE = ROOT / "10_output" / ".cls_archive" / f"pre_gate_{date.today():%Y%m%d}"


def _stamp(text: str, line: str) -> str:
    """Replace the gen_fingerprint line, or insert one after the frontmatter."""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("gen_fingerprint:"):
            lines[i] = line
            return "\n".join(lines)
    for i, ln in enumerate(lines[1:], 1):
        if ln.strip() == "---":
            lines.insert(i, line)
            return "\n".join(lines)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200,
                    help="rebuild the best N ranked jobs (default 200)")
    ap.add_argument("--offset", type=int, default=0,
                    help="skip the first OFFSET ranked jobs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config = yaml.safe_load((ROOT / "config.yaml").read_text()) or {}
    top = ranked_jobs(config)[args.offset:args.offset + args.limit]

    targets, skipped_locked, skipped_missing = [], 0, 0
    for job in top:
        base = make_safe_name(job.get("company", ""), job.get("title", ""))
        cv_p, cl_p = CV_DIR / f"{base}_CV.md", CL_DIR / f"{base}_CL.md"
        if not cl_p.exists():
            # No letter yet is generation's job, not this script's.
            skipped_missing += 1
            continue
        if gen_version.pair_lock_reason(base, (cv_p, cl_p), MATCH_DIR):
            skipped_locked += 1
            continue
        targets.append((base, job, detect_role_type(job.get("title", ""),
                                                    job.get("description", ""))))

    print(f"[{time.strftime('%H:%M:%S')}] CL再生成: {len(targets)}件 "
          f"(順位{args.offset + 1}〜{args.offset + len(top)}, "
          f"ロック済みスキップ{skipped_locked}件, 未生成スキップ{skipped_missing}件)",
          flush=True)
    if args.dry_run:
        for b, _, r in targets[:20]:
            print(f"   {b}  [{r}]")
        if len(targets) > 20:
            print(f"   … 他 {len(targets) - 20} 件")
        return 0

    ARCHIVE.mkdir(parents=True, exist_ok=True)
    done = fail = fallback = 0
    for i, (base, job, role) in enumerate(targets, 1):
        old = CL_DIR / f"{base}_CL.md"
        shutil.copy2(old, ARCHIVE / old.name)
        try:
            save_cover_letter(
                job.get("title", ""), job.get("company", ""),
                job.get("location", "Edinburgh"),
                job.get("description", "") or job.get("snippet", ""),
                str(CL_DIR), match_filename=base, cv_filename=f"{base}_CV",
            )
            cl_p = CL_DIR / f"{base}_CL.md"
            text = _stamp(cl_p.read_text(encoding="utf-8"),
                          gen_version.stamp_line(role))
            cl_p.write_text(text, encoding="utf-8")
            done += 1
            if 'opening_source: "assembled-static"' in text:
                fallback += 1
        except Exception as e:
            fail += 1
            print(f"  ✗ {base[:45]}: {str(e)[:70]}", flush=True)
        if i % 10 == 0:
            print(f"  [{i}/{len(targets)}] 再生成中 (静的冒頭 {fallback}件)", flush=True)

    print(f"\n[{time.strftime('%H:%M:%S')}] 完了: CL {done}/{done + fail}")
    print(f"  ブリッジが静的に退避: {fallback}件")
    print(f"  旧CLの退避先: {ARCHIVE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
