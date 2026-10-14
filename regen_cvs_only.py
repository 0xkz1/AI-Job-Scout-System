"""Rebuild only the CV for the top jobs, leaving every cover letter untouched.

regen_top_docs.py rebuilds both halves together on purpose: a CV built against
the current gates must not sit beside a letter built against older ones, and a
CV-only rerun once left letters citing withdrawn projects. That coupling is
right whenever a source change reaches both documents.

It is the wrong trade when a change reaches only the CV. Letters take their
facts from career/cover-letter/letter_facts_v1.md, not from the CV entries in
career/cv/**, so an edit to a CV entry can leave every letter true. Rebuilding
them anyway costs a model call each and can lose a tailored opening to
"assembled-static", which re-running does not get back.

So: before using this, read the fact blocks in letter_facts_v1.md for the
entries you edited. If any of them states what you changed, the letters are
stale too — use regen_top_docs.py and rebuild the pair. This script exists for
the other case, and says so in its output so a later reader knows which was
claimed.

Selection, locking and fingerprint stamping are regen_top_docs.py's, imported
rather than restated, so the two cannot drift apart on what "the top jobs"
means or on which pairs are frozen.

Usage:
  .venv/bin/python3 regen_cvs_only.py --limit 100
  .venv/bin/python3 regen_cvs_only.py --percent 20 --dry-run
  .venv/bin/python3 regen_cvs_only.py --only FILE
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

import gen_version  # noqa: E402
import regen_top_docs as rtd  # noqa: E402
from matcher import make_safe_name  # noqa: E402
from selection import ranked_jobs, select_top  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None,
                    help="rebuild the top N jobs by rank instead of a percentage")
    ap.add_argument("--percent", type=float, default=None,
                    help="override config's generation_top_percent")
    ap.add_argument("--offset", type=int, default=0,
                    help="skip this many ranks before --limit takes its slice")
    ap.add_argument("--only", metavar="FILE",
                    help="a file of base names, one per line; rebuild just those")
    ap.add_argument("--stale-only", action="store_true",
                    help="skip a CV that already carries the current fingerprint")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config = yaml.safe_load((ROOT / "config.yaml").read_text()) or {}

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

    targets = []
    skipped_current = 0
    skipped_locked = 0
    for job in top:
        base = make_safe_name(job.get("company", ""), job.get("title", ""))
        if only is not None and base not in only:
            continue
        role = detect_role_type(job.get("title", ""), job.get("description", ""))
        cv_p = rtd.CV_DIR / f"{base}_CV.md"
        cl_p = rtd.CL_DIR / f"{base}_CL.md"
        # The same pair lock regen_top_docs.py honours. A hand-edited or applied
        # COVER LETTER still freezes the CV: the reader received the two
        # together, and replacing one half of a sent application is worse than
        # leaving both stale.
        if gen_version.pair_lock_reason(base, (cv_p, cl_p), rtd.MATCH_DIR):
            skipped_locked += 1
            continue
        if args.stale_only and cv_p.exists():
            try:
                if gen_version.is_current(cv_p.read_text(encoding="utf-8"), role):
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
    print(f"[{time.strftime('%H:%M:%S')}] CVのみ再生成: {len(targets)}件 ({scope_note})", flush=True)
    print("  カバーレターは書き換えない — letter_facts_v1.md 側が無変更である前提", flush=True)
    if args.dry_run:
        for b, _, r in targets:
            print(f"   {b}  [{r}]")
        return 0

    from cv_generator import generate_cv

    done = fail = 0
    for i, (base, job, role) in enumerate(targets, 1):
        title = job.get("title", "")
        company = job.get("company", "")
        desc = job.get("description", "") or job.get("snippet", "")
        try:
            cv = generate_cv(
                role_type=role,
                job_title=title, company=company, job_description=desc,
                match_filename=base, cl_filename=f"{base}_CL",
            )
            (rtd.CV_DIR / f"{base}_CV.md").write_text(
                rtd._stamp(cv, gen_version.stamp_line(role)), encoding="utf-8")
            done += 1
        except Exception as e:
            fail += 1
            print(f"  ✗ CV {base[:45]}: {str(e)[:60]}", flush=True)
        if i % 10 == 0 or i == len(targets):
            print(f"  [{time.strftime('%H:%M:%S')}] {i}/{len(targets)} "
                  f"成功{done} 失敗{fail}", flush=True)

    print(f"[{time.strftime('%H:%M:%S')}] 完了: CV {done}件 (失敗{fail}件)。"
          f"レビューは reviewed_sha が変わるため要再実行。", flush=True)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
