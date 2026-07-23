"""Regenerate top-N cover letters (and any missing CVs) with the current gates.

Why CLs must be regenerated rather than re-reviewed: the fabrication and
person-inversion gates in cover_letter_generator only run at GENERATION time.
Letters written before those gates exist still contain the invented claims
("I designed the visual pipeline for a remote compute platform …", industry
experience the candidate never had), so re-reviewing them just re-reports the
same findings. Only regeneration replaces the offending opening.

CVs are different — their problems were in the reviewer's evidence base, which
is fixed review-side, so existing CVs are fine. The exception is CVs deleted as
contaminated (Real Estate Photography internship leaking into unrelated roles);
those are simply missing and get rebuilt here.

Existing CLs are archived before being replaced, never deleted outright.

Usage:
  .venv/bin/python3 regen_top_docs.py --limit 56
  .venv/bin/python3 regen_top_docs.py --limit 56 --dry-run
"""
import argparse
import json
import shutil
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from filter import passes_filter  # noqa: E402
from matcher import make_safe_name  # noqa: E402

ANALYZED = ROOT / "10_output" / "_analyzed.json"
CV_DIR = ROOT / "10_output" / "10_cvs"
CL_DIR = ROOT / "10_output" / "10_cover-letters"
ARCHIVE = ROOT / "10_output" / ".cls_archive" / f"pre_gate_{date.today():%Y%m%d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=56)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", metavar="FILE",
                    help="rebuild just the base names listed in FILE (one per line) — "
                         "for reruns after a targeted change, e.g. a project being "
                         "withdrawn from cover-letter openings")
    args = ap.parse_args()

    jobs = json.loads(ANALYZED.read_text())
    config = yaml.safe_load((ROOT / "config.yaml").read_text()) or {}
    passed = [j for j in jobs if j.get("match") and passes_filter(j, config)[0]]
    passed.sort(key=lambda j: j["match"]["composite_score"], reverse=True)
    top = passed[args.offset:args.offset + args.limit]

    only = None
    if args.only:
        only = {l.strip() for l in Path(args.only).read_text().splitlines() if l.strip()}

    cl_targets, cv_targets = [], []
    for job in top:
        base = make_safe_name(job.get("company", ""), job.get("title", ""))
        if only is not None and base not in only:
            continue
        cl_targets.append((base, job))
        if not (CV_DIR / f"{base}_CV.md").exists():
            cv_targets.append((base, job))

    print(f"[{time.strftime('%H:%M:%S')}] CL再生成: {len(cl_targets)}件 / "
          f"欠損CV再生成: {len(cv_targets)}件 "
          f"({args.offset + 1}〜{args.offset + len(top)}位)", flush=True)
    if args.dry_run:
        for b, _ in cv_targets:
            print("  CV(欠損):", b)
        return 0

    from cover_letter_generator import save_cover_letter
    from cv_generator import generate_cv, detect_role_type

    # --- Missing CVs first: a CL links to its CV in frontmatter ---
    for base, job in cv_targets:
        try:
            cv = generate_cv(
                role_type=detect_role_type(job.get("title", ""), job.get("description", "")),
                job_title=job.get("title", ""),
                company=job.get("company", ""),
                job_description=job.get("description", "") or job.get("snippet", ""),
                match_filename=base,
                cl_filename=f"{base}_CL",
            )
            (CV_DIR / f"{base}_CV.md").write_text(cv, encoding="utf-8")
            print(f"  ✓ CV {base[:55]}", flush=True)
        except Exception as e:
            print(f"  ✗ CV {base[:45]}: {str(e)[:60]}", flush=True)

    # --- Cover letters ---
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    done = failed = fallback = 0
    for i, (base, job) in enumerate(cl_targets, 1):
        old = CL_DIR / f"{base}_CL.md"
        if old.exists():
            shutil.copy2(old, ARCHIVE / old.name)
        try:
            save_cover_letter(
                job.get("title", ""), job.get("company", ""),
                job.get("location", "Edinburgh"),
                job.get("description", "") or job.get("snippet", ""),
                str(CL_DIR), match_filename=base, cv_filename=f"{base}_CV",
            )
        except Exception as e:
            failed += 1
            print(f"  ✗ CL {base[:45]}: {str(e)[:60]}", flush=True)
            continue
        done += 1
        # opening_source records whether the tailored LLM opening survived the
        # gates or fell back to the role template — the fallback rate is the
        # signal for how often the model was trying to fabricate.
        try:
            if 'opening_source: "template"' in (CL_DIR / f"{base}_CL.md").read_text(encoding="utf-8"):
                fallback += 1
        except Exception:
            pass
        if i % 10 == 0:
            print(f"  [{i}/{len(cl_targets)}] CL再生成中 "
                  f"(テンプレ回避 {fallback}件)", flush=True)

    print(f"\n[{time.strftime('%H:%M:%S')}] 完了: CL {done}件再生成, {failed}件失敗")
    print(f"  ゲートで冒頭文が破棄されテンプレートに退避: {fallback}件")
    print(f"  旧CLの退避先: {ARCHIVE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
