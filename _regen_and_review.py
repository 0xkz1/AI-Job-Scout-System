"""Regenerate top-3% CV/CL with current sources, then re-review all stale docs."""
import sys, math, json, hashlib, shutil, time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import os
from dotenv import dotenv_values
for k, v in dotenv_values(ROOT / ".env").items():
    if v:
        os.environ[k] = v

import yaml
from filter import passes_filter
from matcher import make_safe_name
from cv_generator import detect_role_type, generate_cv
from cover_letter_generator import save_cover_letter
from reviewer import run_review, review_is_current

OUTPUT_DIR = ROOT / "10_output"
CV_DIR = OUTPUT_DIR / "10_cvs"
CL_DIR = OUTPUT_DIR / "10_cover-letters"


def resolve_base(company, title, url):
    base = make_safe_name(company, title)
    hashed = f"{base}_{hashlib.md5((url or '').encode()).hexdigest()[:6]}"
    if not (CV_DIR / f"{base}_CV.md").exists() and (CV_DIR / f"{hashed}_CV.md").exists():
        return hashed
    return base


def main():
    config = yaml.safe_load((ROOT / "config.yaml").read_text())
    all_jobs = json.loads((OUTPUT_DIR / "_analyzed.json").read_text())
    passed = [j for j in all_jobs if passes_filter(j, config)[0]]
    job_map = {j.get("url", ""): j for j in passed if j.get("url")}
    rows = sorted(job_map.values(),
                  key=lambda j: j.get("match", {}).get("composite_score", 0), reverse=True)
    scored = [j for j in rows if j.get("match", {}).get("composite_score", 0) > 0]
    targets = scored[:math.ceil(len(scored) * 3 / 100)]

    print(f"[{time.strftime('%H:%M:%S')}] === PHASE A: regenerate top-3% = {len(targets)} jobs ===", flush=True)
    backup_dir = OUTPUT_DIR / ".backups_pre_regen" / f"pre_regen_{datetime.now():%Y%m%d_%H%M%S}"
    for j in targets:
        company, title, url = j.get("company", "company"), j.get("title", "job"), j.get("url", "")
        base = resolve_base(company, title, url)
        backup_dir.mkdir(exist_ok=True)
        for p in (CV_DIR / f"{base}_CV.md", CL_DIR / f"{base}_CL.md"):
            if p.exists():
                shutil.copyfile(p, backup_dir / p.name)
                p.unlink()
        desc = j.get("description", "")
        role_type = detect_role_type(title, desc)
        cv = generate_cv(role_type=role_type, job_title=title, company=company,
                         job_description=desc, match_filename=base, cl_filename=f"{base}_CL")
        (CV_DIR / f"{base}_CV.md").write_text(cv, encoding="utf-8")
        save_cover_letter(title, company, j.get("location", "Edinburgh"), desc,
                          str(CL_DIR), match_filename=base, cv_filename=f"{base}_CV")
        print(f"  [{time.strftime('%H:%M:%S')}] regen: {base}", flush=True)
    print(f"[{time.strftime('%H:%M:%S')}] backup: {backup_dir.name}", flush=True)

    to_review = []
    for j in targets:
        base = resolve_base(j.get("company", ""), j.get("title", ""), j.get("url", ""))
        for kind, d in (("CV", CV_DIR), ("CL", CL_DIR)):
            doc = d / f"{base}_{kind}.md"
            if doc.exists():
                cur, _ = review_is_current(doc)
                if not cur:
                    to_review.append((kind, doc, j))

    print(f"\n[{time.strftime('%H:%M:%S')}] === PHASE B: review {len(to_review)} stale docs ===", flush=True)
    ok, failed = 0, []
    for i, (kind, doc, job) in enumerate(to_review, 1):
        t0 = time.time()
        try:
            run_review(kind, doc, job)
            print(f"  [{time.strftime('%H:%M:%S')}] {i:2d}/{len(to_review)}  {job.get('company','?')[:25]:25s} {kind:2s} {time.time()-t0:5.1f}s ✓", flush=True)
            ok += 1
        except Exception as e:
            print(f"  [{time.strftime('%H:%M:%S')}] {i:2d}/{len(to_review)}  {job.get('company','?')[:25]:25s} {kind:2s} {time.time()-t0:5.1f}s ✗ {str(e)[:60]}", flush=True)
            failed.append((doc.stem, str(e)))
        time.sleep(1)

    print(f"\n[{time.strftime('%H:%M:%S')}] === DONE: reviews {ok} ok, {len(failed)} failed ===", flush=True)
    for stem, err in failed:
        print(f"  ✗ {stem}: {err[:80]}", flush=True)


if __name__ == "__main__":
    main()
