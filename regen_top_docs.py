"""Rebuild the top jobs' CV **and** cover letter together, as a pair.

Both documents are generated at write time by gates that keep improving — the
CV against the reviewer's evidence base, the cover letter against the
fabrication / person-inversion / project-selection gates. Regenerating only one
leaves the pair inconsistent: a fresh CV beside a cover letter written before
the current gates, or vice versa. That is exactly how the two drifted apart
before (a CV-only rerun left cover letters citing withdrawn projects).

So this rebuilds both for every selected job. The selection is the shared
top-percent set (selection.py) unless overridden. Old cover letters are archived
before replacement; CVs are overwritten (the previous copy is reproducible).

Usage:
  .venv/bin/python3 regen_top_docs.py                 # top review/generation %
  .venv/bin/python3 regen_top_docs.py --percent 20
  .venv/bin/python3 regen_top_docs.py --limit 56
  .venv/bin/python3 regen_top_docs.py --only FILE      # just these base names
  .venv/bin/python3 regen_top_docs.py --pair-audit     # list CLs older than CV
  .venv/bin/python3 regen_top_docs.py --dry-run
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
from matcher import make_safe_name  # noqa: E402
from selection import ranked_jobs, select_top  # noqa: E402

ANALYZED = ROOT / "10_output" / "_analyzed.json"
CV_DIR = ROOT / "10_output" / "10_cvs"
CL_DIR = ROOT / "10_output" / "10_cover-letters"
MATCH_DIR = ROOT / "10_output" / "00_matches"
ARCHIVE = ROOT / "10_output" / ".cls_archive" / f"pre_gate_{date.today():%Y%m%d}"


def _stamp(text: str, stamp_line: str) -> str:
    """Insert/replace the gen_fingerprint line inside the doc's frontmatter."""
    import re
    if not text.startswith("---"):
        return text  # no frontmatter to stamp into; leave untouched
    # Replace an existing stamp, else insert before the closing '---'.
    if re.search(r'^gen_fingerprint:.*$', text, re.MULTILINE):
        return re.sub(r'^gen_fingerprint:.*$', stamp_line, text, count=1, flags=re.MULTILINE)
    m = re.search(r'\n---\s*\n', text)
    if not m:
        return text
    return text[:m.start()] + f"\n{stamp_line}" + text[m.start():]


def _pair_audit(config) -> int:
    """Report selected jobs whose cover letter predates its CV — the drift this
    script exists to prevent. Read-only."""
    top = select_top("generation", config)
    stale = []
    for job in top:
        base = make_safe_name(job.get("company", ""), job.get("title", ""))
        cv, cl = CV_DIR / f"{base}_CV.md", CL_DIR / f"{base}_CL.md"
        if cv.exists() and cl.exists() and cl.stat().st_mtime < cv.stat().st_mtime - 1:
            stale.append(base)
        elif cv.exists() and not cl.exists():
            stale.append(base + " (CL欠損)")
    print(f"CVより古い/欠損のCL: {len(stale)}件 / 選定{len(top)}件")
    for b in stale:
        print("  ", b)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="rebuild the best N jobs (overrides the configured percent)")
    ap.add_argument("--percent", type=float, default=None,
                    help="rebuild the top P%% (overrides generation_top_percent)")
    ap.add_argument("--offset", type=int, default=0,
                    help="skip the first OFFSET ranked jobs (with --limit)")
    ap.add_argument("--only", metavar="FILE",
                    help="rebuild just the base names listed in FILE (one per line)")
    ap.add_argument("--pair-audit", action="store_true",
                    help="list selected jobs whose CL is older than its CV, then exit")
    ap.add_argument("--stale-only", action="store_true",
                    help="skip pairs already stamped with the current generation "
                         "fingerprint — rebuild only what a spec change invalidated")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config = yaml.safe_load((ROOT / "config.yaml").read_text()) or {}

    if args.pair_audit:
        return _pair_audit(config)

    if args.limit is not None:
        top = ranked_jobs(config)[args.offset:args.offset + args.limit]
        scope = f"{args.offset + 1}〜{args.offset + len(top)}位"
    else:
        top = select_top("generation", config, percent=args.percent)
        pct = args.percent if args.percent is not None else config.get("generation_top_percent", 20)
        scope = f"上位{pct}%"

    only = None
    if args.only:
        only = {l.strip() for l in Path(args.only).read_text().splitlines() if l.strip()}

    from cv_generator import detect_role_type
    import gen_version

    targets = []
    skipped_current = 0
    skipped_locked = 0
    for job in top:
        base = make_safe_name(job.get("company", ""), job.get("title", ""))
        if only is not None and base not in only:
            continue
        role = detect_role_type(job.get("title", ""), job.get("description", ""))
        cv_p, cl_p = CV_DIR / f"{base}_CV.md", CL_DIR / f"{base}_CL.md"
        # Hand-edited / applied / expired — see gen_version. A lock on either
        # half freezes the pair, and the job-scoped ones hold even before either
        # file exists, so an expired posting is not handed a first CV either.
        if gen_version.pair_lock_reason(base, (cv_p, cl_p), MATCH_DIR):
            skipped_locked += 1
            continue
        # --stale-only: skip a pair whose CV and CL both already carry the current
        # fingerprint — nothing affecting them has changed since they were built.
        if args.stale_only:
            if cv_p.exists() and cl_p.exists():
                try:
                    if (gen_version.is_current(cv_p.read_text(encoding="utf-8"), role)
                            and gen_version.is_current(cl_p.read_text(encoding="utf-8"), role)):
                        skipped_current += 1
                        continue
                except Exception:
                    pass
        targets.append((base, job, role))

    scope_note = scope
    if args.stale_only:
        scope_note += f", 最新版スキップ{skipped_current}件"
    if skipped_locked:
        scope_note += f", ロック済みスキップ{skipped_locked}件"
    print(f"[{time.strftime('%H:%M:%S')}] CV+CLペア再生成: {len(targets)}件 ({scope_note})", flush=True)
    if args.dry_run:
        for b, _, r in targets:
            print(f"   {b}  [{r}]")
        return 0

    from cover_letter_generator import save_cover_letter
    from cv_generator import generate_cv

    ARCHIVE.mkdir(parents=True, exist_ok=True)
    cv_done = cv_fail = cl_done = cl_fail = fallback = 0
    for i, (base, job, role) in enumerate(targets, 1):
        title = job.get("title", "")
        company = job.get("company", "")
        desc = job.get("description", "") or job.get("snippet", "")
        stamp = gen_version.stamp_line(role)

        # CV first — the CL frontmatter links to it.
        try:
            cv = generate_cv(
                role_type=role,
                job_title=title, company=company, job_description=desc,
                match_filename=base, cl_filename=f"{base}_CL",
            )
            (CV_DIR / f"{base}_CV.md").write_text(_stamp(cv, stamp), encoding="utf-8")
            cv_done += 1
        except Exception as e:
            cv_fail += 1
            print(f"  ✗ CV {base[:45]}: {str(e)[:60]}", flush=True)

        # CL — archive the previous copy first (its opening may be irreplaceable
        # if a later run's gates reject a fresh one).
        old = CL_DIR / f"{base}_CL.md"
        if old.exists():
            shutil.copy2(old, ARCHIVE / old.name)
        try:
            save_cover_letter(
                title, company, job.get("location", "Edinburgh"), desc,
                str(CL_DIR), match_filename=base, cv_filename=f"{base}_CV",
            )
            cl_p = CL_DIR / f"{base}_CL.md"
            cl_p.write_text(_stamp(cl_p.read_text(encoding="utf-8"), stamp), encoding="utf-8")
            cl_done += 1
            # "assembled-static" is the assembler's equivalent of the old
            # template fallback: the letter is valid, but its bridge is the
            # neutral one, so nothing in it was written for this posting.
            cl_text = cl_p.read_text(encoding="utf-8")
            if 'opening_source: "assembled-static"' in cl_text \
                    or 'opening_source: "template"' in cl_text:
                fallback += 1
        except Exception as e:
            cl_fail += 1
            print(f"  ✗ CL {base[:45]}: {str(e)[:60]}", flush=True)

        if i % 10 == 0:
            print(f"  [{i}/{len(targets)}] ペア再生成中 (テンプレ回避 {fallback}件)", flush=True)

    print(f"\n[{time.strftime('%H:%M:%S')}] 完了: CV {cv_done}/{cv_done + cv_fail}, "
          f"CL {cl_done}/{cl_done + cl_fail}")
    print(f"  ゲートで冒頭文が破棄されテンプレートに退避: {fallback}件")
    print(f"  旧CLの退避先: {ARCHIVE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
