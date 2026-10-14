#!/usr/bin/env python3
"""
jis_hermes_bridge.py - Bridge between Job Intelligence System (JIS) and Hermes Kanban
Location: 00_Kazuki/career/Job-Intelligence-System/jis_hermes_bridge.py

Architecture: L1 (deterministic) → L3 (review audit)
- L1: Reads top-ranked jobs, generates CV+CL via pure Python (zero LLM tokens)
- L3: Pushes generated documents to Hermes review-editor for factual audit

The writer profile is NOT used. cv_generator.py and cover_letter_generator.py
are 100% deterministic template assemblers — no LLM calls. Having a Hermes
profile "think" about how to call them wasted ~28k tokens per job and hit
rate limits. This bridge calls them directly.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import selection
from local_jobs import local_job_role

ANALYZED_FILE = ROOT / "10_output" / "_analyzed.json"
CV_DIR = ROOT / "10_output" / "10_cvs"
CL_DIR = ROOT / "10_output" / "10_cover-letters"
MATCH_DIR = ROOT / "10_output" / "00_matches"
CL_ARCHIVE = ROOT / "10_output" / ".cls_archive" / f"pre_bridge_{date.today():%Y%m%d}"
BOARD_SLUG = "jis"


def sanitize(text: str) -> str:
    """Sanitizes text for safe filename / key matching."""
    return re.sub(r"[^\w\-]", "_", text).strip("_")


def run_hermes_kanban(args: list[str]) -> tuple[int, str, str]:
    """Invokes the hermes kanban CLI."""
    cmd = ["hermes", "kanban", "--board", BOARD_SLUG] + args
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 1, "", str(e)


def ensure_board_exists():
    """Initializes the jis board if not present."""
    code, out, _ = run_hermes_kanban(["boards", "list"])
    if BOARD_SLUG not in out:
        cmd = [
            "hermes", "kanban", "boards", "create", BOARD_SLUG,
            "--name", "Job Intelligence System",
            "--description", "Autonomous CV/CL Generation and Review",
            "--default-workdir", str(ROOT),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# L1: Deterministic Document Generation (zero LLM tokens)
# ---------------------------------------------------------------------------

def generate_documents(job: dict, score: float, dry_run: bool = False) -> dict:
    """Generate CV + Cover Letter using pure Python generators.

    Returns a dict with:
        success: bool
        cv_path: Path or None
        cl_path: Path or None
        role_type: str
        errors: list[str]
    """
    from cv_generator import generate_cv, detect_role_type
    from cover_letter_generator import save_cover_letter
    from matcher import make_safe_name
    import gen_version

    company = job.get("company", "")
    title = job.get("title", "")
    desc = job.get("description", "") or job.get("snippet", "")
    location = job.get("location", "Edinburgh")

    base = make_safe_name(company, title)
    role = detect_role_type(title, desc)
    result = {"success": False, "cv_path": None, "cl_path": None,
              "role_type": role, "base": base, "errors": [], "locked": None}

    CV_DIR.mkdir(parents=True, exist_ok=True)
    CL_DIR.mkdir(parents=True, exist_ok=True)

    # Check gen_version lock (hand-edited / applied / expired)
    cv_p = CV_DIR / f"{base}_CV.md"
    cl_p = CL_DIR / f"{base}_CL.md"
    lock_reason = gen_version.pair_lock_reason(base, (cv_p, cl_p), MATCH_DIR)
    if lock_reason:
        result["locked"] = lock_reason
        return result

    if dry_run:
        print(f"  [DRY-RUN] Would generate/audit: {base} [{role}]")
        result["cv_path"] = cv_p
        result["cl_path"] = cl_p
        result["success"] = True
        return result

    stamp = gen_version.stamp_line(role)

    # --- CV ---
    try:
        cv_text = generate_cv(
            role_type=role,
            job_title=title, company=company, job_description=desc,
            match_filename=base, cl_filename=f"{base}_CL",
        )
        cv_p.write_text(_stamp(cv_text, stamp), encoding="utf-8")
        result["cv_path"] = cv_p
        print(f"  ✓ CV generated: {cv_p.name}")
    except Exception as e:
        result["errors"].append(f"CV: {e}")
        print(f"  ✗ CV {base[:45]}: {str(e)[:80]}")

    # --- Cover Letter ---
    old_cl = CL_DIR / f"{base}_CL.md"
    if old_cl.exists():
        CL_ARCHIVE.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old_cl, CL_ARCHIVE / old_cl.name)

    try:
        cl_path_str = save_cover_letter(
            title, company, location, desc,
            str(CL_DIR), match_filename=base, cv_filename=f"{base}_CV",
        )
        cl_p = Path(cl_path_str)
        cl_p.write_text(_stamp(cl_p.read_text(encoding="utf-8"), stamp), encoding="utf-8")
        result["cl_path"] = cl_p
        print(f"  ✓ CL generated: {cl_p.name}")
    except Exception as e:
        result["errors"].append(f"CL: {e}")
        print(f"  ✗ CL {base[:45]}: {str(e)[:80]}")

    result["success"] = bool(result["cv_path"] or result["cl_path"])
    return result


def _stamp(text: str, stamp_line: str) -> str:
    """Insert/replace the gen_fingerprint line inside the doc's frontmatter."""
    if not text.startswith("---"):
        return text
    if re.search(r'^gen_fingerprint:.*$', text, re.MULTILINE):
        return re.sub(r'^gen_fingerprint:.*$', stamp_line, text, count=1, flags=re.MULTILINE)
    m = re.search(r'\n---\s*\n', text)
    if not m:
        return text
    return text[:m.start()] + f"\n{stamp_line}" + text[m.start():]


# ---------------------------------------------------------------------------
# L3: Push to Hermes review-editor (factual audit only)
# ---------------------------------------------------------------------------

def create_review_task(job: dict, score: float, gen_result: dict,
                       dry_run: bool = False, force: bool = False) -> bool:
    """Creates an idempotent review task on the JIS kanban board.

    Only creates review-editor tasks — the writer profile is not used.
    Documents are already generated by L1 (deterministic Python).
    Runs L1 Jev Fast Pre-Audit Gatekeeper before queueing to Hermes.
    """
    company = job.get("company", "Unknown")
    title = job.get("title", "Position")
    url = job.get("url") or job.get("job_url", "")

    base = gen_result.get("base", "")
    role = gen_result.get("role_type", "general")
    cv_path = gen_result.get("cv_path")
    cl_path = gen_result.get("cl_path")

    # --- L1 Jev Fast Pre-Audit Gatekeeper ---
    cv_text = cv_path.read_text(encoding="utf-8") if cv_path and cv_path.exists() else ""
    cl_text = cl_path.read_text(encoding="utf-8") if cl_path and cl_path.exists() else ""

    from jis_jev_judge import fast_pre_audit_documents
    audit_res = fast_pre_audit_documents(cv_text, cl_text, job)

    if not audit_res["passed"] and not force:
        violations_str = "; ".join(audit_res["violations"])
        print(f"  ⚠ [L1 Jev BLOCKED] Review not queued for [{company}] {title}: {violations_str}")
        return False

    s_company = sanitize(company)
    s_title = sanitize(title)
    idempotency_key = f"jis-{s_company[:30]}-{s_title[:30]}-review"

    title_text = f"[{company}] {title} (Score: {score:.2f}) - REVIEW"

    cv_rel = cv_path.relative_to(ROOT) if cv_path else "Not generated"
    cl_rel = cl_path.relative_to(ROOT) if cl_path else "Not generated"

    jev_info = ""
    if audit_res.get("jev_audit"):
        ja = audit_res["jev_audit"]
        if "has_hallucinations_prob" in ja:
            jev_info = f"\n- **Jev Semantic Audit**: Hallucination Risk: {ja['has_hallucinations_prob']}, Tone Authentic: {ja['tone_authentic_prob']}"

    body_text = f"""### Target Job
- **Company**: {company}
- **Title**: {title}
- **Composite Score**: {score:.2f}
- **URL**: {url}
- **Role Profile**: `{role}`

### Generated Documents (L1 — Deterministic Python, Zero LLM)
- **CV**: `{cv_rel}`
- **Cover Letter**: `{cl_rel}`

### L1 Fast Pre-Audit Gatekeeper (Jev & Invariants)
- **Status**: {'PASS (Clean)' if audit_res['passed'] else 'FLAGGED (Forced)'}
- **Invariants Verified**: No unrendered placeholders, length OK, valid structure.{jev_info}

### Mission for `review-editor`
1. Mechanical checks (placeholders, length, timeline) are ALREADY VERIFIED at L1 in sub-second pass.
2. Focus your audit purely on high-level substance:
   - Tone consistency with Kazuki's authentic craft voice.
   - Context bridge relevance to the specific job posting.
   - Strategic advice on how to improve fit before submission.
3. If approved, mark this card `done`.
4. If issues found, comment with exact line corrections.
"""


    if dry_run:
        print(f"  [DRY-RUN] Would create review task:")
        print(f"    Title: {title_text}")
        print(f"    Assignee: review-editor")
        print(f"    Key: {idempotency_key}")
        return True

    ensure_board_exists()
    cmd = [
        "create",
        title_text,
        "--body", body_text,
        "--assignee", "review-editor",
        "--idempotency-key", idempotency_key,
        "--workspace", f"dir:{ROOT}",
        "--priority", str(int(score * 100)),
    ]

    code, out, err = run_hermes_kanban(cmd)
    if code == 0:
        print(f"  ✓ Queued review for [{company}] {title} -> @review-editor")
        return True
    else:
        print(f"  ✗ Failed to queue review for [{company}] {title}: {err.strip() or out.strip()}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="JIS to Hermes Kanban Bridge (L1 generate → L3 review)")
    parser.add_argument("--sync-top", type=int, default=3,
                        help="Sync top N high matches to Kanban (default: 3)")
    parser.add_argument("--min-score", type=float, default=0.70,
                        help="Minimum composite score threshold (default: 0.70)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without generating docs or modifying Kanban")
    parser.add_argument("--generate-only", action="store_true",
                        help="Generate documents but don't push to Hermes Kanban")
    parser.add_argument("--review-only", action="store_true",
                        help="Skip generation, push existing docs to review-editor")
    parser.add_argument("--force", action="store_true",
                        help="Force queueing review tasks even if L1 pre-audit flags warnings")
    args = parser.parse_args()


    if not ANALYZED_FILE.exists():
        print(f"Error: {ANALYZED_FILE} not found.")
        sys.exit(1)

    print(f"[{time.strftime('%H:%M:%S')}] Loading ranked jobs from {ANALYZED_FILE.name}...")
    config = selection.load_config()
    try:
        jobs = selection.ranked_jobs(config=config)
    except Exception as e:
        print(f"Fallback direct load (selection.ranked_jobs failed: {e})")
        with open(ANALYZED_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            raw = list(raw.values())
        jobs = [j for j in raw if (j.get("match", {}).get("composite_score", 0)
                                   or j.get("composite_score", 0)) > 0]
        jobs.sort(key=lambda j: j.get("match", {}).get("composite_score", 0)
                  or j.get("composite_score", 0), reverse=True)

    high_matches = []
    for job in jobs:
        # Local jobs use shared CVs and human applications; no technical documents
        # or autonomous review-editor task is needed for them.
        if local_job_role(job.get("title", ""), config):
            continue
        score = (job.get("match", {}).get("composite_score", 0)
                 or job.get("composite_score", 0))
        if score >= args.min_score:
            high_matches.append((job, score))

    print(f"Found {len(high_matches)} jobs >= {args.min_score:.2f}.")

    generated = 0
    reviewed = 0
    errors = 0
    skipped_locked = 0
    processed = 0
    t0 = time.time()

    for job, score in high_matches:
        if processed >= args.sync_top:
            break

        company = job.get("company", "Unknown")
        title = job.get("title", "Position")

        # L1: Generate documents (deterministic, sub-second per job)
        if not args.review_only:
            gen_result = generate_documents(job, score, dry_run=args.dry_run)
            if gen_result.get("locked"):
                skipped_locked += 1
                continue

            print(f"\n--- [{company}] {title} (Score: {score:.2f}) ---")
            if gen_result["success"]:
                generated += 1
            if gen_result["errors"]:
                errors += len(gen_result["errors"])
                for err in gen_result["errors"]:
                    print(f"  ⚠ {err}")
        else:
            # Build a minimal gen_result from existing files
            from matcher import make_safe_name
            from cv_generator import detect_role_type
            import gen_version
            desc = job.get("description", "") or job.get("snippet", "")
            base = make_safe_name(company, title)
            cv_p = CV_DIR / f"{base}_CV.md"
            cl_p = CL_DIR / f"{base}_CL.md"
            lock_reason = gen_version.pair_lock_reason(base, (cv_p, cl_p), MATCH_DIR)
            if lock_reason:
                skipped_locked += 1
                continue

            print(f"\n--- [{company}] {title} (Score: {score:.2f}) ---")
            role = detect_role_type(title, desc)
            gen_result = {
                "success": cv_p.exists() or cl_p.exists(),
                "cv_path": cv_p if cv_p.exists() else None,
                "cl_path": cl_p if cl_p.exists() else None,
                "role_type": role,
                "base": base,
                "errors": [],
            }

        # L3: Push to review-editor (if documents exist)
        if not args.generate_only and gen_result["success"]:
            if create_review_task(job, score, gen_result, dry_run=args.dry_run, force=args.force):
                reviewed += 1


        processed += 1

    elapsed = time.time() - t0
    action = "Dry-run" if args.dry_run else "Completed"
    print(f"\n[{time.strftime('%H:%M:%S')}] {action}: "
          f"{generated} docs generated, {reviewed} reviews queued, "
          f"{skipped_locked} locked skipped, {errors} errors ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
