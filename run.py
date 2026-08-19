"""
Job Scraper Pipeline — Main Entry Point
=========================================
Usage:
    python3 run.py                     # Run all sites
    python3 run.py --site indeed       # Run only Indeed
    python3 run.py --site linkedin     # Run only LinkedIn
    python3 run.py --pages 5           # More pages per search
    python3 run.py --headless          # Headless browser (Indeed only)
    python3 run.py --no-filter         # Skip filtering, show all results
    python3 run.py --from-saved        # Skip scraping, analyze from 00_saved/ staging
    python3 run.py --site reed --scrape-only   # Scrape into staging, no analysis
"""


import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import fcntl
from datetime import datetime
from pathlib import Path

import yaml
import gen_version

from scraper_indeed import scrape_indeed_all, save_jobs as save_indeed
# Guest endpoints, not the authenticated UI: the logged-in scraper cannot run
# unattended (no valid session on the cron box, and auto-login lands on a
# checkpoint), which is why LinkedIn contributed nothing to the nightly run.
# scraper_linkedin.py is still used by scraper_saved.py for the user's own
# saved jobs, which genuinely need the account.
from scraper_linkedin_guest import scrape_linkedin_all
from scraper_reed import scrape_reed_all
from scraper_guardian import scrape_guardian_all
from scraper_adzuna import scrape_adzuna_all
from scraper_remote_apis import scrape_remote_apis_all
from scraper_url_list import normalize_url
from analyzer import analyze_job
from filter import filter_jobs, print_filter_summary
from matcher import (analyze_match, generate_match_report, load_user_skills, load_user_experience,
                     make_safe_name, read_applied_flag, read_expired_flag)
from cv_generator import generate_cv, detect_role_type
from cover_letter_generator import save_cover_letter

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


def _try_acquire_lock(name="url_list_jobs"):
    """Try to acquire an exclusive file lock (non-blocking).
    Returns the lock file handle (keep open while locked) or None if already locked."""
    lock_path = f"/tmp/jis_{name}.lock"
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file
    except (IOError, OSError, BlockingIOError):
        lock_file.close()
        return None


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    # Defaults
    cfg.setdefault("keywords", [])
    cfg.setdefault("locations", [""])
    cfg.setdefault("max_pages_per_search", 3)
    cfg.setdefault("sites", ["indeed"])
    cfg.setdefault("min_salary_gbp", 0)
    cfg.setdefault("include_levels", ["entry_level", "mid", "senior"])
    cfg.setdefault("employment_types", ["full_time", "part_time", "contract"])
    cfg.setdefault("exclude_title_keywords", [])
    cfg.setdefault("exclude_description_keywords", [])
    cfg.setdefault("output_dir", "10_output")
    return cfg


# ── Staging (00_saved) ──────────────────────────────────────────
SAVED_DIR = os.path.join(os.path.dirname(__file__), "00_saved")


def match_all(jobs: list[dict], config: dict, label: str = "matched", **kwargs) -> int:
    """Score every job in place. Returns the failure count.

    Shared by every matching pass because each one needs the same two things and
    none of them originally had either:

    - Containment. analyze_match reaches the LLM for context scoring, so it raises
      whenever the provider chain is exhausted — an ordinary end-state after a bulk
      day. Unguarded, one job's failure discarded the scoring of every job in the
      batch.
    - Progress. A silent loop over 1000 jobs runs for over an hour with no output,
      which looks exactly like a hung process. That ambiguity produced three false
      "the process died" reports in one session while it was simply waiting on the
      API.

    A failed job keeps an empty match dict rather than none, so downstream code that
    assumes the key exists still works and `--reanalyze` can retry it.
    """
    failures = 0
    for i, job in enumerate(jobs, 1):
        try:
            job["match"] = analyze_match(job, config, **kwargs)
        except Exception as e:
            failures += 1
            if failures <= 3:
                print(f"  ⚠ {label} failed for {(job.get('title') or '?')[:40]}: "
                      f"{type(e).__name__}: {str(e)[:70]}", flush=True)
            job.setdefault("match", {})
        if i % 100 == 0 or i == len(jobs):
            print(f"  … {i}/{len(jobs)} {label} ({failures} failed)", flush=True)
    if failures:
        print(f"  ⚠ {failures}/{len(jobs)} jobs left without a match score. "
              f"Re-run `run.py --reanalyze` to retry them.")
    return failures


def save_raw_to_saved(jobs: list[dict], source: str):
    """Save raw scraped jobs to 00_saved/ staging area."""
    os.makedirs(SAVED_DIR, exist_ok=True)
    valid = [j for j in jobs if j.get("url")]
    if not valid:
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(SAVED_DIR, f"_raw_{source}_{timestamp}.json")
    with open(path, "w") as f:
        json.dump(valid, f, indent=2, ensure_ascii=False, default=str)
    print(f"  📦 Staged {len(valid)} {source} jobs → 00_saved/")


def record_site_yield(site: str, count: int) -> None:
    """Append 'site<TAB>count' to the file named by JIS_YIELD_FILE, if set.

    Exit status alone cannot tell a healthy quiet night from a scraper that
    silently returns nothing: a site whose selectors stopped matching exits 0
    with an empty list, which is exactly how Indeed contributed nothing for 11
    nights while the cron recorded success. The nightly summary records the exit
    code; this records what the run actually produced, so nightly_scout.py can
    say "linkedin scraped 0 jobs two nights running" instead of staying silent.

    Written only when the environment names a file, so ad-hoc runs from the
    Streamlit UI do not overwrite the nightly's record of its own run.
    """
    path = os.environ.get("JIS_YIELD_FILE")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{site}\t{count}\n")
    except OSError as e:  # never let bookkeeping take the scrape down
        print(f"  ⚠ could not record site yield: {e}")


def load_saved_from_index() -> list[dict]:
    """Load manual saved jobs from 00_saved/_saved_index.json (scraper_saved.py format)."""
    index_path = os.path.join(SAVED_DIR, "_saved_index.json")
    if not os.path.exists(index_path):
        return []
    try:
        with open(index_path) as fh:
            index = json.load(fh)
    except Exception:
        return []
    saved = []
    for entry in index:
        jd = os.path.join(SAVED_DIR, entry.get("folder", ""), "job-description.md")
        if not os.path.exists(jd):
            continue
        with open(jd) as fh:
            md = fh.read()
        saved.append({
            "title": entry.get("title", ""),
            "company": entry.get("company", ""),
            "location": entry.get("location", ""),
            "salary": "",
            "description": md,
            "snippet": md[:500] if md else "",
            "url": entry.get("url", ""),
            "source": entry.get("source", "saved"),
            "type": "manual",
            "source_site": "Saved" if entry.get("source") == "saved"
                          else entry.get("source", "").capitalize(),
            "scraped_at": datetime.now().isoformat(),
        })
    return saved


def load_all_from_saved() -> list[dict]:
    """Load ALL jobs from 00_saved/ staging (raw auto JSON + manual saved index)."""
    all_jobs = []
    if not os.path.isdir(SAVED_DIR):
        return all_jobs
    # 1. Raw auto JSON files written by save_raw_to_saved() or local_html_jobs.json or url_list_jobs.json
    for f in sorted(os.listdir(SAVED_DIR)):
        if (f.startswith("_raw_") and f.endswith(".json")) or f in ["local_html_jobs.json", "url_list_jobs.json"]:
            fp = os.path.join(SAVED_DIR, f)
            try:
                with open(fp) as fh:
                    batch = json.load(fh)
                # Tag the collection route so match reports can be filtered by
                # how the job was collected (Dataview: WHERE route = "url_list").
                route = {"url_list_jobs.json": "url_list", "local_html_jobs.json": "local_html"}.get(f, "scraper")
                for job in batch:
                    job.setdefault("route", route)
                all_jobs.extend(batch)
            except Exception:
                pass
    # 2. Manual saved jobs via index
    all_jobs.extend(load_saved_from_index())
    return all_jobs


def _same_posting(a: dict, b: dict) -> bool:
    """Are these two same-company+title records the SAME posting?

    Scraped titles can be wrong (e.g. the LLM extractor picking a title from a
    LinkedIn "Similar jobs" sidebar), so title equality alone is not enough —
    require the descriptions to actually match. Missing/short descriptions
    can't disprove a duplicate, so they count as matching.
    """
    from difflib import SequenceMatcher
    da = (a.get("description") or "")[:1500]
    db = (b.get("description") or "")[:1500]
    if len(da) < 100 or len(db) < 100:
        return True
    return SequenceMatcher(None, da, db).ratio() >= 0.9


def dedupe_by_company_title(jobs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Merge duplicate postings of the same role (e.g. LinkedIn reposts under a
    new job ID): identical (company, title) AND matching descriptions.

    Priority: source (LinkedIn > Indeed > Others) -> description length -> composite score.
    Returns (kept_jobs, archived_jobs).
    """
    def source_priority(job: dict) -> int:
        src = (job.get("source") or "").lower()
        if src == "linkedin":
            return 3
        elif src == "indeed":
            return 2
        return 1

    groups: dict[tuple, list[dict]] = {}
    no_key = []
    for j in jobs:
        company = (j.get("company") or "").strip().lower()
        title = (j.get("title") or "").strip().lower()
        if company and title:
            groups.setdefault((company, title), []).append(j)
        else:
            no_key.append(j)

    result = []
    archived = []
    merged_away = 0
    for group in groups.values():
        group.sort(key=lambda j: (
            source_priority(j),
            len(j.get("description") or ""),
            j.get("match", {}).get("composite_score", 0),
        ), reverse=True)
        # Greedy clustering: each job joins the first kept entry it matches
        kept: list[dict] = []
        for j in group:
            target = next((k for k in kept if _same_posting(k, j)), None)
            if target is None:
                kept.append(j)
                continue
            dup_urls = list(target.get("duplicate_urls") or [])
            if j.get("url") and j["url"] != target.get("url"):
                dup_urls.append(j["url"])
            dup_urls.extend(u for u in (j.get("duplicate_urls") or []) if u not in dup_urls)
            if dup_urls:
                target["duplicate_urls"] = sorted(set(dup_urls))
            archived.append(j)
            merged_away += 1
        result.extend(kept)

    if merged_away:
        print(f"  🔀 Merged {merged_away} duplicate postings (prioritizing LinkedIn > Indeed)")
    return result + no_key, archived

def archive_duplicate_files(archived_jobs: list[dict], output_dir: str):
    """Scan existing output files and move files belonging to archived_jobs to archive folders."""
    if not archived_jobs:
        return
        
    import shutil
    from pathlib import Path
    import re
    
    archived_urls = {j.get("url") for j in archived_jobs if j.get("url")}
    if not archived_urls:
        return
        
    out_dir = Path(output_dir)
    matches_dir = out_dir / "00_matches"
    
    if not matches_dir.exists():
        return
        
    archived_count = 0
    for match_file in matches_dir.glob("*.md"):
        try:
            content = match_file.read_text(encoding="utf-8")
            # Extract URL from frontmatter
            m = re.search(r'^url:\s*"(.*?)"', content, re.MULTILINE)
            if not m:
                continue
            url = m.group(1)
            
            if url in archived_urls:
                base_name = match_file.stem
                
                # Define all related files
                related_files = [
                    matches_dir / f"{base_name}.md",
                    out_dir / "10_cvs" / f"{base_name}_CV.md",
                    out_dir / "10_cover-letters" / f"{base_name}_CL.md",
                    out_dir / "15_reviews" / f"{base_name}_CV_review.md",
                    out_dir / "15_reviews" / f"{base_name}_CL_review.md",
                ]
                
                pdf_dir = out_dir / "20_pdfs"
                if pdf_dir.exists():
                    related_files.extend(pdf_dir.glob(f"{base_name}_*_v*.pdf"))
                    
                # Move them to their respective archive dirs
                for fpath in related_files:
                    if fpath.exists():
                        parent_name = fpath.parent.name
                        if parent_name == "00_matches":
                            archive_dir = out_dir / ".matches_archive"
                        elif parent_name == "10_cvs":
                            archive_dir = out_dir / ".cvs_archive"
                        elif parent_name == "10_cover-letters":
                            archive_dir = out_dir / ".cls_archive"
                        elif parent_name == "15_reviews":
                            archive_dir = out_dir / "15_reviews" / ".archive"
                        elif parent_name == "20_pdfs":
                            archive_dir = out_dir / "20_pdfs" / ".archive"
                        else:
                            continue
                            
                        archive_dir.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(fpath), str(archive_dir / fpath.name))
                archived_count += 1
        except Exception:
            pass
            
    if archived_count > 0:
        print(f"  🗑️  Archived files for {archived_count} duplicate jobs.")



# Frontmatter keys on a match report that the analyzer does not own, so a full
# report regeneration must copy them across instead of dropping them. Anything
# the WebUI writes after the fact belongs here — otherwise the next run
# silently discards it.
#
# `applied:` deliberately does NOT belong here any more. generate_match_report
# now emits it itself (so Obsidian renders a checkbox on every report), and a
# key appearing in both places lands TWICE in the frontmatter — the generated
# `applied: false` first, the carried `applied: true` after. Every reader takes
# the first match, so the duplicate would read as "not applied" and quietly
# unlock a submitted application. Ticked checkboxes ride the `expired=` /
# `applied=` arguments instead, which is also what fixed this path resetting
# `expired` on every run.
PRESERVED_FRONTMATTER_PREFIXES = (
    "cv_pdf:",
    "cl_pdf:",
    "cv_review:",
    "cl_review:",
    "applied_at:",
    "screening_passed_at:",
    "interview_passed_at:",
    "screening_failed_at:",
    "interview_failed_at:",
)


def generate_outputs(jobs: list[dict], config: dict, output_dir: str):
    """Generate match reports for all jobs, and tailored CVs/cover letters for filter-passed jobs.

    Shared by the normal scrape path and --reanalyze. Existing CV/CL files are
    never overwritten (manual edits are preserved); match reports are always
    refreshed.
    """
    match_dir = os.path.join(output_dir, "00_matches")
    os.makedirs(match_dir, exist_ok=True)
    cv_dir = os.path.join(output_dir, "10_cvs")
    os.makedirs(cv_dir, exist_ok=True)
    letter_dir = os.path.join(output_dir, "10_cover-letters")
    os.makedirs(letter_dir, exist_ok=True)

    passed_jobs = [j for j in jobs if not j.get("_filter_reason")]

    cv_threshold = config.get("match_score_threshold", 0.50)
    # CV/CL generation is the expensive part (one LLM pass each), so it acts only
    # on the top generation_top_percent of the ranked pool — the same selection
    # every stage uses (selection.py), so generation and review stay in step.
    # A count cap still guards against a huge first run.
    from selection import select_top, stretch_jobs
    selected = select_top("generation", config, jobs=passed_jobs)
    eligible_ids: set[int] = {id(j) for j in selected}
    # Postings the level gate rejected that are still worth judging. They are
    # not in passed_jobs and never will be, so they cannot come through
    # select_top — they carry their own small allowance instead, and they do not
    # count against cv_generation_limit, which governs the ranked pool.
    from matcher import set_stretch_urls
    _stretch = stretch_jobs(config, jobs)
    stretch_ids: set[int] = {id(j) for j in _stretch}
    # The report writer needs the same answer, and it must come from this run's
    # jobs rather than from the DB on disk, which is still last night's.
    set_stretch_urls(j.get("url") for j in _stretch)
    cv_limit = config.get("cv_generation_limit", 0)
    if cv_limit and len(eligible_ids) > cv_limit:
        # The cap counts what this run would WRITE, not where a job sits in the
        # ranking. Slicing the ranked list at cv_limit instead made everything
        # below that rank permanently unreachable: the top 150 are re-selected
        # every night, almost all of them already have a CV, and the loop below
        # only writes when the file is absent — so the run generated 10 CVs
        # against a cap of 150 and handed the 140 unused slots back rather than
        # to rank 151. "Synechron Graphic Designer" sat at rank 437 of 1,636,
        # inside the top 30% and above threshold, and no number of runs would
        # ever have reached it.
        #
        # Skipping jobs that already have a CV does not weaken the overwrite
        # protection, because there is none to weaken: this path never
        # regenerates an existing document (see `if not os.path.exists` below,
        # and the docstring — manual edits are preserved). Regeneration is
        # regen_top_docs.py's job, the same split as nightly_scout vs
        # rereview_top on the review side.
        pending = [j for j in selected
                   if not os.path.exists(os.path.join(
                       cv_dir,
                       f"{make_safe_name(j.get('company', 'company'), j.get('title', 'job'))}_CV.md"))]
        eligible_ids = {id(j) for j in pending[:cv_limit]}

    cv_generated = 0
    cv_skipped = 0
    letter_generated = 0
    letter_skipped = 0
    cv_over_limit = 0
    cv_locked = 0

    seen_bases: set[str] = set()
    for job in jobs:
        match = job.get("match", {})
        if not match:
            continue
        is_filtered = bool(job.get("_filter_reason"))
        base = make_safe_name(job.get('company', 'company'), job.get('title', 'job'))
        # Distinct jobs can share company+title (dedupe keeps them separate when
        # descriptions differ) — disambiguate with a stable URL-hash suffix so
        # they don't overwrite each other's report/CV/CL.
        if base in seen_bases:
            suffix = hashlib.md5((job.get("url") or "").encode()).hexdigest()[:6]
            base = f"{base}_{suffix}"
        seen_bases.add(base)
        composite_score = match.get("composite_score", 0)

        # Pre-calculate base filenames (without paths or extensions for Obsidian links)
        match_filename = f"{base}"
        cv_name = f"{base}_CV"
        cl_name = f"{base}_CL"

        cv_filename_md = f"{cv_name}.md"
        cl_filename_md = f"{cl_name}.md"

        # Step 1: Generate CV first (top-N match, above threshold, has description, not filtered out)
        within_limit = (not cv_limit) or (id(job) in eligible_ids)
        if not within_limit and composite_score >= cv_threshold and not is_filtered:
            cv_over_limit += 1
        # A stretch job qualifies on none of those three: it is filtered by
        # definition, and its composite sits under the threshold because the
        # level rejection is what put it there. It is admitted on the strength
        # of its skills overlap alone (selection.stretch_jobs), so that the CV
        # review — the score actually used to decide whether to apply — exists
        # for it at all.
        is_stretch = id(job) in stretch_ids
        wants_documents = is_stretch or (
            within_limit and composite_score >= cv_threshold and not is_filtered
        )
        # A job ticked applied or expired is frozen (see gen_version). Both
        # steps below only write when the file is absent, so what this stops is
        # a FIRST CV/CL — which is the whole point for `expired`: a closed
        # posting must not be handed freshly generated documents.
        job_locked = gen_version.job_lock_reason(base, Path(match_dir))
        if job_locked:
            cv_locked += 1
            cv_skipped += 1
            letter_skipped += 1
        elif wants_documents and not match.get("description_missing", False):
            cv_path = os.path.join(cv_dir, cv_filename_md)
            if not os.path.exists(cv_path):
                role_type = detect_role_type(job.get('title', ''), job.get('description', ''))
                cv = generate_cv(
                    role_type=role_type,
                    job_title=job.get('title', ''),
                    company=job.get('company', ''),
                    job_description=job.get('description', ''),
                    match_filename=match_filename,
                    cl_filename=cl_name
                )
                with open(cv_path, "w") as f:
                    f.write(cv)
                cv_generated += 1
            else:
                cv_skipped += 1

            # Step 2: Generate cover letter (skip if exists)
            cl_path = os.path.join(letter_dir, cl_filename_md)
            if not os.path.exists(cl_path):
                # The assembler refuses to build a letter without its authored
                # assets rather than emitting one with the identity block
                # missing. That is the right call for one letter and the wrong
                # one for the run, which still has its CVs and its report to
                # finish — so the refusal is caught per job and named.
                try:
                    save_cover_letter(
                        job.get('title', ''),
                        job.get('company', ''),
                        job.get('location', 'Edinburgh'),
                        job.get('description', ''),
                        letter_dir,
                        match_filename=match_filename,
                        cv_filename=cv_name
                    )
                    letter_generated += 1
                except Exception as e:
                    letter_skipped += 1
                    print(f"  ✗ CL {base[:45]}: {str(e)[:80]}", flush=True)
            else:
                letter_skipped += 1
        else:
            cv_skipped += 1
            letter_skipped += 1

        # The report's cv:/cover_letter: links describe WHAT IS ON DISK, not what
        # this pass happened to generate. Deriving them from the branch above
        # instead meant every job that fell out of the generation set — score
        # drifting under the threshold, or the top-N% boundary moving past it —
        # had its links dropped on the next run while its CV and CL sat there,
        # reviewed and scored. That is how 368 of 534 existing CVs ended up
        # orphaned in their own reports. It also un-linked the applied/expired
        # documents, which take the skip branch by design and are exactly the
        # ones whose links must never move.
        cv_filename_link = cv_filename_md if os.path.exists(os.path.join(cv_dir, cv_filename_md)) else None
        cl_filename_link = cl_filename_md if os.path.exists(os.path.join(letter_dir, cl_filename_md)) else None

        # Step 3: Generate match report (with links to CV/CL)
        report_path = os.path.join(match_dir, f"{match_filename}.md")
        # The two hand-ticked checkboxes must be read off the previous report and
        # handed back, or a full regeneration resets them. This call used to pass
        # neither, so every run silently cleared `expired` — the sibling path
        # (matcher.save_match_report) passed `expired` but not `applied`, so the
        # two paths each wiped exactly what the other preserved.
        report = generate_match_report(
            job, match, cv_filename=cv_filename_link, cl_filename=cl_filename_link,
            expired=read_expired_flag(Path(report_path)),
            applied=read_applied_flag(Path(report_path)),
        )
        # Reports are fully regenerated each run, but some frontmatter is owned
        # by the WebUI rather than the analyzer — cv_pdf/cl_pdf are written at
        # PDF-conversion time. Carry them over or they'd vanish on every
        # reanalyze. (applied/expired ride the arguments above instead.)
        if os.path.exists(report_path):
            try:
                with open(report_path) as f:
                    old = f.read()
                m_old = re.match(r"\A---\n(.*?)\n---\n", old, flags=re.DOTALL)
                if m_old:
                    pdf_lines = [
                        ln for ln in m_old.group(1).split("\n")
                        if ln.startswith(PRESERVED_FRONTMATTER_PREFIXES)
                    ]
                    if pdf_lines:
                        m_new = re.match(r"\A---\n(.*?)\n---\n", report, flags=re.DOTALL)
                        if m_new:
                            fm = m_new.group(1) + "\n" + "\n".join(pdf_lines)
                            report = f"---\n{fm}\n---\n" + report[m_new.end():]
            except Exception:
                pass  # never let carry-over break report generation
        with open(report_path, "w") as f:
            f.write(report)

    print(f"  📊 Saved {len(passed_jobs)} match reports to {match_dir}/")
    # "deferred", not "outside top N": the cap now counts documents this run
    # would write, so these are jobs whose turn is a later run rather than jobs
    # permanently below a rank line.
    limit_note = f", {cv_over_limit} deferred past this run's cap of {cv_limit}" if cv_limit else ""
    limit_note += f", {cv_locked} locked (applied/expired)" if cv_locked else ""
    print(f"  📄 Saved {cv_generated} tailored CVs to {cv_dir}/ (skipped {cv_skipped} below {cv_threshold:.0%} threshold or missing desc{limit_note})")
    print(f"  ✉️  Saved {letter_generated} cover letters to {letter_dir}/ (skipped {letter_skipped} below {cv_threshold:.0%} threshold or missing desc{limit_note})")


def print_summary(jobs: list[dict]):
    """Print a readable summary of scraped jobs."""
    print(f"\n{'='*60}")
    print(f"📋 JOB LISTINGS SUMMARY")
    print(f"{'='*60}")

    for i, job in enumerate(jobs, 1):
        analysis = job.get("analysis", {})
        salary = analysis.get("salary", {})
        salary_str = ""
        if salary.get("min") and salary.get("max"):
            salary_str = f"  £{salary['min']:.0f}K-{salary['max']:.0f}K"
        elif salary.get("min"):
            salary_str = f"  From £{salary['min']:.0f}K"
        elif salary.get("max"):
            salary_str = f"  Up to £{salary['max']:.0f}K"

        level = analysis.get("experience_level", "?")
        work_style = analysis.get("work_style", "?")
        skills = analysis.get("skills", [])

        print(f"\n  {i}. {job['title']}")
        print(f"     🏢 {job.get('company', '?')}  |  📍 {job.get('location', '?')}")
        print(f"     🏷 {level}  |  🏠 {work_style}{salary_str}")
        print(f"     🔗 {job.get('url', '')[:80]}")
        if skills:
            skill_str = ", ".join(skills[:8])
            print(f"     🛠 {skill_str}{'...' if len(skills) > 8 else ''}")
        fmt = job.get("_filter_reason", "")
        if fmt:
            print(f"     ❌ Filtered: {fmt}")


async def main():
    parser = argparse.ArgumentParser(description="Job Scraper Pipeline")
    parser.add_argument("--site", choices=["indeed", "linkedin", "reed", "guardian", "adzuna", "remote_apis", "all"], default="all")
    parser.add_argument("--pages", type=int, default=None, help="Pages per search")
    parser.add_argument("--headless", action="store_true", default=False,
                        help="Headless mode (Indeed only; LinkedIn needs login)")
    parser.add_argument("--no-filter", action="store_true", default=False,
                        help="Skip filtering, show all raw results")
    parser.add_argument("--summary", action="store_true", default=True,
                        help="Print summary")
    parser.add_argument("--saved", action="store_true", default=False,
                        help="Run saved jobs scraper first (scraper_saved.py)")
    parser.add_argument("--reanalyze", action="store_true", default=False,
                        help="Re-analyze existing _analyzed.json with updated analyzer")
    parser.add_argument("--force-reanalyze", action="store_true", default=False,
                        help="Force re-run LLM context match on all jobs (ignore cached context_score)")
    parser.add_argument("--fetch-descriptions", action="store_true", default=False,
                        help="Fetch full job descriptions from detail page URLs for existing _analyzed.json")
    parser.add_argument("--llm-context", action="store_true", default=False,
                        help="Use Ollama LLM for context/ethos matching (slower but more accurate)")
    parser.add_argument("--llm-limit", type=int, default=None,
                        help="Limit LLM context matching to top N jobs by score (e.g. 30)")
    parser.add_argument("--watched", action="store_true", default=False,
                        help="Process watched jobs from 00_saved/watched-list/ folder")
    parser.add_argument("--scrape-only", action="store_true", default=False,
                        help="Scrape into 00_saved/ staging and stop, before the "
                             "merge/analyse/match/generate pass")
    parser.add_argument("--from-saved", action="store_true", default=False,
                        help="Skip scraping, read everything from 00_saved/ staging")
    args = parser.parse_args()

    config = load_config()
    from filter import filter_jobs, print_filter_summary
    if args.pages:
        # Clear the per-site table too, or --pages is silently ignored: selection.
        # max_pages_for prefers max_pages_per_site and only falls back to
        # max_pages_per_search, so setting the fallback alone left the Streamlit
        # page slider (and this flag) with no effect on any configured site.
        config["max_pages_per_search"] = args.pages
        config["max_pages_per_site"] = {}

    # --- Fetch descriptions from detail pages ---
    if args.fetch_descriptions:
        print(f"\n{'='*60}")
        print("📄 FETCHING JOB DESCRIPTIONS FROM DETAIL PAGES...")
        print(f"{'='*60}")
        output_dir = os.path.join(os.path.dirname(__file__), config.get("output_dir", "10_output"))
        raw_path = os.path.join(output_dir, "_analyzed.json")
        full_data_path = os.path.join(output_dir, "_analyzed_full.json")
        if os.path.exists(raw_path):
            with open(raw_path) as f:
                analyzed = json.load(f)
            print(f"  📂 Loaded {len(analyzed)} jobs from {raw_path}")

            # Calculate temporary match scores so we can target only the top ones
            user_skills = load_user_skills()
            user_exp = load_user_experience()
            match_all([j for j in analyzed if not j.get("match")], config,
                      label="scored for targeting")

            # Sort and apply filters first to identify the relevant subset
            passed, _ = filter_jobs(analyzed, config)
            passed.sort(key=lambda j: j.get("match", {}).get("composite_score", 0), reverse=True)

            # Limit target set to fetch descriptions for
            limit = args.llm_limit if args.llm_limit else 150
            target_jobs = passed[:limit]
            print(f"  🎯 Targeting top {len(target_jobs)} scoring jobs for description fetching (out of {len(passed)} passed filters)")

            # Map back to original list for updating
            url_to_desc = {}
            missing = sum(1 for j in target_jobs if not j.get("description"))
            print(f"  🔍 {missing} targeted jobs missing descriptions")

            if missing > 0:
                from scraper_indeed import _fetch_job_description
                from playwright.async_api import async_playwright
                from playwright_stealth import Stealth

                async def fetch_all_descriptions(jobs_to_fetch, cookie_state):
                    fetched = 0
                    async with async_playwright() as p:
                        launch_args = ["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"]
                        browser = await p.chromium.launch(headless=False, args=launch_args)
                        context_args = {
                            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                            "viewport": {"width": 1920, "height": 1080},
                            "locale": "en-GB",
                            "timezone_id": "Europe/London",
                        }
                        if os.path.exists(cookie_state):
                            context_args["storage_state"] = cookie_state
                        context = await browser.new_context(**context_args)
                        stealth = Stealth()
                        await stealth.apply_stealth_async(context)

                        # Single page reused for all jobs — consistent fingerprint
                        page = await context.new_page()

                        for i, job in enumerate(jobs_to_fetch):
                            if not job.get("description") and job.get("url"):
                                import re
                                jk_match = re.search(r"jk=([a-f0-9]+)", job.get("url", ""))
                                if not jk_match:
                                    continue
                                jk = jk_match.group(1)
                                viewjob_url = f"https://uk.indeed.com/viewjob?jk={jk}"

                                # Reuse same page for all jobs — consistent fingerprint avoids Cloudflare
                                desc = await _fetch_job_description(page, viewjob_url, retries=5)

                                if desc:
                                    job["description"] = desc
                                    url_to_desc[job["url"]] = desc
                                    fetched += 1
                                    print(f"    → [{fetched}/{missing}] {job.get('company','')} — {job.get('title','')[:40]} ({len(desc)} chars)")
                                else:
                                    print(f"    ❌ [{i+1}/{len(jobs_to_fetch)}] Blocked: {job.get('company','')} — {job.get('title','')[:40]}")

                                # Graceful delay to avoid detection
                                await asyncio.sleep(8)

                        await browser.close()
                        return fetched

                cookie_state = os.path.join(output_dir, "..", "cookies", "indeed_cookies.json")
                fetched = await fetch_all_descriptions(target_jobs, cookie_state)
                print(f"  ✅ Fetched {fetched} descriptions")

                # Sync descriptions back to main list
                for job in analyzed:
                    if job.get("url") in url_to_desc:
                        job["description"] = url_to_desc[job["url"]]

                # Save updated analyzed data
                with open(raw_path, "w") as f:
                    json.dump(analyzed, f, indent=2, ensure_ascii=False, default=str)
                print(f"  💾 Saved updated descriptions to {raw_path}")
            else:
                print("  ✓ All targeted jobs already have descriptions")
        else:
            print(f"  ⚠ No _analyzed.json found at {raw_path}")
        print(f"{'='*60}\n")
        if not args.reanalyze:
            return

    # --- Process watched jobs if requested ---
    if args.watched:
        print(f"\n{'='*60}")
        print("👁 WATCHED JOBS MATCHER")
        print(f"{'='*60}")
        watched_args = []
        if args.llm_context:
            watched_args.append("--llm-context")
        if args.llm_limit:
            watched_args.extend(["--llm-limit", str(args.llm_limit)])
        import subprocess
        result = subprocess.run(
            [sys.executable, "watched_matcher.py"] + watched_args,
            cwd=os.path.dirname(__file__),
            timeout=600,
        )
        if result.returncode != 0:
            print(f"  ⚠ Watched matcher exited with code {result.returncode}")
        print(f"{'='*60}\n")
        return

    # --- Load from 00_saved/ staging (skip scraping) ---
    _from_saved_mode = False
    _saved_lock = None  # file lock handle — released on exit
    if args.from_saved:
        # ── File lock: prevent concurrent access with scraper_url_list.py ──
        _saved_lock = _try_acquire_lock()
        if _saved_lock is None:
            print("⚠ Another process is already using url_list_jobs.json (scrape or analysis).")
            print("  Wait for it to finish before running again.")
            return

        print(f"\n{'='*60}")
        print("📂 LOADING FROM 00_SAVED/ STAGING")
        print(f"{'='*60}")
        _saved_jobs_to_merge = []          # already part of load_all_from_saved()
        all_jobs = load_all_from_saved()
        print(f"  → Loaded {len(all_jobs)} jobs from staging")
        if not all_jobs:
            print("  ⚠ No jobs found in 00_saved/. Run scraper first or check path.")
            _saved_lock.close()
            return
        print(f"{'='*60}\n")
        _from_saved_mode = True

    # --- Re-analyze existing data if requested ---
    if args.reanalyze:
        print(f"\n{'='*60}")
        print("🔄 RE-ANALYZING EXISTING DATA...")
        print(f"{'='*60}")
        output_dir = os.path.join(os.path.dirname(__file__), config.get("output_dir", "10_output"))
        raw_path = os.path.join(output_dir, "_analyzed.json")
        full_data_path = os.path.join(output_dir, "_analyzed_full.json")
        if os.path.exists(raw_path):
            with open(raw_path) as f:
                analyzed = json.load(f)
            print(f"  📂 Loaded {len(analyzed)} pre-analyzed jobs from {raw_path}")
            analyzed, archived = dedupe_by_company_title(analyzed)
            archive_duplicate_files(archived, output_dir)
            
            if args.force_reanalyze:
                print("  🔄 Re-running full keyword/Ollama analysis (skills and experience classification) on all jobs...")
                _reanalyze_failures = 0
                for idx, job in enumerate(analyzed):
                    try:
                        analyzed[idx] = analyze_job(job)
                    except Exception as e:
                        # Contained for the same reason as every other analysis loop:
                        # analyze_job reaches the LLM, and this is the pass users are
                        # told to run to recover from a rate-limited night. It must
                        # not be the pass that discards everything.
                        _reanalyze_failures += 1
                        if _reanalyze_failures <= 3:
                            print(f"    ⚠ {(job.get('title') or '?')[:40]}: "
                                  f"{type(e).__name__}: {str(e)[:60]}", flush=True)
                    if (idx + 1) % 10 == 0 or idx + 1 == len(analyzed):
                        print(f"    → Re-analyzed {idx + 1}/{len(analyzed)} jobs "
                              f"({_reanalyze_failures} failed)...", flush=True)
            else:
                print(f"  ⚡ Skipping re-analysis (use --force-reanalyze to re-run Ollama extraction)")
            
            # Run matcher and save match reports
            user_skills = load_user_skills()
            user_exp = load_user_experience()
            total_skills = sum(len(s) for s in user_skills.values())
            print(f"  📋 Loaded profile: {total_skills} skills, {user_exp.get('years_python', 0)}y Python, {user_exp.get('years_linux', 0)}y Linux")
            match_all(analyzed, config, skip_summary=True)

            # --- LLM Context Match (optional, slow but accurate) ---
            if args.llm_context:
                from matcher import _ollama_context_score, _load_persona_summary

                # Pre-flight check: only when the provider is actually Ollama
                # (importing llm_client loads .env, which sets ANALYSIS_PROVIDER)
                import llm_client as _llm_client  # noqa: F401 — .env side effect
                if os.environ.get("ANALYSIS_PROVIDER", "ollama") == "ollama":
                    import requests as _req
                    try:
                        _req.get("http://localhost:11434/api/tags", timeout=5)
                    except Exception:
                        print("  ❌ ERROR: Ollama is not running on localhost:11434!")
                        print("     Start it with: ollama serve")
                        print("     Aborting LLM Context Match to prevent fallback 50% contamination.")
                        sys.exit(1)

                # Sort by composite score and optionally limit to top N
                analyzed_with_scores = sorted(analyzed, key=lambda j: j.get("match", {}).get("composite_score", 0), reverse=True)
                if args.llm_limit:
                    llm_jobs = analyzed_with_scores[:args.llm_limit]
                    print(f"  🧠 LLM Context Match: scoring top {len(llm_jobs)} jobs with gemma4:26b...")
                else:
                    llm_jobs = analyzed_with_scores
                    print(f"  🧠 LLM Context Match: scoring all {len(llm_jobs)} jobs with gemma4:26b...")
                llm_done = 0
                llm_skipped = 0
                for job in llm_jobs:
                    # Skip jobs that already have an LLM-scored context (incremental mode)
                    # unless --force-reanalyze is set.
                    # We detect LLM-scored jobs via match["context_source"].
                    if not args.force_reanalyze:
                        if job.get("match", {}).get("context_source") == "llm":
                            llm_skipped += 1
                            continue
                    if job.get("match", {}).get("description_missing"):
                        llm_skipped += 1
                        continue
                    # Build description (with fallback to pseudo-description from analysis metadata)
                    desc = job.get("description", "") or job.get("snippet", "")
                    if not desc or len(desc) <= 50:
                        # Same fallback as analyze_match in matcher.py
                        analysis = job.get("analysis", {})
                        parts = [job.get("title", ""), job.get("company", "")]
                        job_skills = analysis.get("skills", [])
                        if job_skills:
                            parts.append("Skills: " + ", ".join(job_skills))
                        job_level = analysis.get("experience_level", "")
                        if job_level and job_level != "unknown":
                            parts.append(f"Experience level: {job_level}")
                        job_work_style = analysis.get("work_style", "")
                        if job_work_style and job_work_style != "unknown":
                            parts.append(f"Work style: {job_work_style}")
                        emp_types = analysis.get("employment_types", [])
                        if emp_types and emp_types != ["unknown"]:
                            parts.append("Employment: " + ", ".join(emp_types))
                        desc = ". ".join(p for p in parts if p)

                    if desc and len(desc) > 30:
                        persona = _load_persona_summary()
                        ctx = _ollama_context_score(desc, persona)
                        if ctx is None:
                            print(f"    ⚠️  LLM returned no valid response for: {job.get('company','')} — {job.get('title','')[:40]}")
                            print(f"       Skipping (will NOT tag as LLM-scored).")
                            continue
                        job["match"]["context_score"] = ctx["score"]
                        job["match"]["context_reasoning"] = ctx.get("reasoning", "")
                        job["match"]["context_reasoning_en"] = ctx.get("reasoning_en", "")
                        job["match"]["context_reasoning_ja"] = ctx.get("reasoning_ja", "")
                        job["match"]["context_source"] = "llm"  # mark LLM-scored
                        # Recompute composite with new context score
                        w = job["match"]["weights"]
                        composite = (
                            job["match"]["skills"]["score"] * w["skills"]
                            + job["match"]["experience"]["score"] * w["experience"]
                            + job["match"]["location"]["score"] * w["location"]
                            + job["match"]["salary"]["score"] * w["salary"]
                            + ctx["score"] * w["context"]
                        )
                        job["match"]["composite_score"] = round(composite, 2)
                        # Update tier
                        if composite >= 0.8:
                            job["match"]["tier"] = "🟢 Strong Match"
                        elif composite >= 0.6:
                            job["match"]["tier"] = "🟡 Good Match"
                        elif composite >= 0.4:
                            job["match"]["tier"] = "🟠 Partial Match"
                        else:
                            job["match"]["tier"] = "🔴 Weak Match"
                    llm_done += 1
                    if llm_done % 5 == 0:
                        print(f"    → LLM scored {llm_done}/{len(llm_jobs)}...")
                print(f"  ✅ LLM Context Match complete")

                # --- LLM Job Summary (bilingual EN+JA) for top 30% ---
                from matcher import _ollama_job_summary
                sorted_for_summary = sorted(analyzed, key=lambda j: j.get("match", {}).get("composite_score", 0), reverse=True)
                top_30_pct = max(1, int(len(sorted_for_summary) * 0.30))
                summary_jobs = sorted_for_summary[:top_30_pct]
                summary_done = 0
                print(f"  📋 Generating bilingual summaries for top {top_30_pct} jobs...")
                for job in summary_jobs:
                    if job.get("match", {}).get("description_missing"):
                        continue
                    desc = job.get("description", "") or job.get("snippet", "")
                    if desc and len(desc) > 50:
                        if not job.get("match", {}).get("summary_en"):
                            summary = _ollama_job_summary(desc)
                            if summary:
                                job["match"]["summary_en"] = summary.get("summary_en", "")
                                job["match"]["summary_ja"] = summary.get("summary_ja", "")
                                summary_done += 1
                                if summary_done % 5 == 0:
                                    print(f"    → Summarized {summary_done}/{len(summary_jobs)}...")
                    else:
                        # No description available — skip
                        pass
                print(f"  ✅ Generated {summary_done} job summaries")

            # Checkpoint save BEFORE report/CV generation: LLM context scores and
            # summaries are expensive — a crash below must not lose them.
            raw_path = os.path.join(output_dir, "_analyzed.json")
            with open(raw_path, "w") as f:
                json.dump(analyzed, f, indent=2, ensure_ascii=False, default=str)

            # Apply filters (title exclusion etc.) even in reanalyze mode
            passed, filtered_out = filter_jobs(analyzed, config)
            print_filter_summary(passed, filtered_out)
            # Save FULL data (including filtered-out jobs) for future refetch
            with open(full_data_path, "w") as f:
                json.dump(analyzed, f, indent=2)

            # NOTE: Previously this block deleted old reports/CVs not in the current filtered set.
            # Removed to preserve high-match reports across runs.
            generate_outputs(analyzed, config, output_dir)

            # Warn about missing descriptions
            missing_desc = [j for j in passed if j.get("match", {}).get("description_missing")]
            if missing_desc:
                print(f"\n  ⚠️  WARNING: {len(missing_desc)} jobs had missing descriptions (unreliable match score, no CV/CL generated):")
                for j in missing_desc:
                    print(f"     - {j.get('company', 'Unknown')}: {j.get('title', 'Unknown')} ({j.get('url', 'No URL')})")

            # Save updated _analyzed.json with new match scores.
            # Must contain ALL jobs (not just filter-passed): this file is the
            # incremental-dedup DB — shrinking it makes the next scrape re-fetch
            # and re-analyze every filtered-out job.
            raw_path = os.path.join(output_dir, "_analyzed.json")
            with open(raw_path, "w") as f:
                json.dump(analyzed, f, indent=2, ensure_ascii=False, default=str)
            print(f"  💾 Saved updated scores for {len(analyzed)} jobs ({len(passed)} passed filters) to {raw_path}")

            print(f"{'='*60}\n")
            return

    # Initialize saved jobs container (may be populated by --saved)
    _saved_jobs_to_merge: list[dict] = []

    if not _from_saved_mode:
        # --- Run saved jobs scraper first if requested ---
        if args.saved:
            print(f"\n{'='*60}")
            print("💾 SAVED JOBS SCRAPER (saved + tracker)")
            print(f"{'='*60}")
            # Use subprocess to avoid Playwright context conflicts
            import subprocess
            result = subprocess.run(
                [sys.executable, "scraper_saved.py", "--max-jobs", "50", "--site", "linkedin"],
                cwd=os.path.dirname(__file__),
                timeout=300,
            )
            if result.returncode != 0:
                print(f"  ⚠ Saved scraper exited with code {result.returncode}")
            # Always reload from index after (or despite) scraper run
            _saved_jobs_to_merge = load_saved_from_index()
            print(f"  → Loaded {len(_saved_jobs_to_merge)} saved jobs from 00_saved/ for analysis")
            print(f"{'='*60}\n")

        sites = ["reed", "guardian", "adzuna", "remote_apis", "indeed", "linkedin"] if args.site == "all" else [args.site]

        all_jobs = []
        # Each scraper's except prints and continues, so one dead site never stops
        # the others — right for a nightly run, but it also meant the process exited
        # 0 no matter what. Indeed failed on Cloudflare for 11 consecutive nights
        # and the cron recorded success every time, because the only trace was a
        # line in a log nobody reads. Collected here and turned into a non-zero exit
        # at the end when EVERY requested site failed.
        scraper_failures: list[str] = []

        if "indeed" in sites:
            print(f"\n{'='*60}")
            print("🌐 INDEED SCRAPER")
            print(f"{'='*60}")
            try:
                indeed_jobs = await scrape_indeed_all(config)
                print(f"  → {len(indeed_jobs)} jobs from Indeed")
                save_raw_to_saved(indeed_jobs, "indeed")
                all_jobs.extend(indeed_jobs)
            except Exception as e:
                print(f"  ❌ Indeed scraper failed: {e}")
                scraper_failures.append("indeed")

        if "linkedin" in sites:
            print(f"\n{'='*60}")
            print("🔗 LINKEDIN SCRAPER")
            print(f"{'='*60}")
            print("  (guest endpoints — no login, no browser)")
            try:
                linkedin_jobs = await scrape_linkedin_all(config)
                print(f"  → {len(linkedin_jobs)} jobs from LinkedIn")
                save_raw_to_saved(linkedin_jobs, "linkedin")
                all_jobs.extend(linkedin_jobs)
            except Exception as e:
                print(f"  ❌ LinkedIn scraper failed: {e}")
                scraper_failures.append("linkedin")

        if "guardian" in sites:
            print(f"\n{'='*60}")
            print("🏛️  GUARDIAN JOBS SCRAPER")
            print(f"{'='*60}")
            print("  (Creative/arts/media jobs from The Guardian)")
            try:
                guardian_jobs = await scrape_guardian_all(config)
                print(f"  → {len(guardian_jobs)} jobs from Guardian Jobs")
                save_raw_to_saved(guardian_jobs, "guardian")
                all_jobs.extend(guardian_jobs)
            except Exception as e:
                print(f"  ❌ Guardian scraper failed: {e}")
                scraper_failures.append("guardian")

        if "adzuna" in sites:
            print(f"\n{'='*60}")
            print("📊 ADZUNA SCRAPER")
            print(f"{'='*60}")
            print("  (Aggregated jobs from 1000+ UK sources)")
            try:
                adzuna_jobs = await scrape_adzuna_all(config)
                print(f"  → {len(adzuna_jobs)} jobs from Adzuna")
                save_raw_to_saved(adzuna_jobs, "adzuna")
                all_jobs.extend(adzuna_jobs)
            except Exception as e:
                print(f"  ❌ Adzuna scraper failed: {e}")
                scraper_failures.append("adzuna")

        if "remote_apis" in sites:
            print(f"\n{'='*60}")
            print("🌍 REMOTE APIs (Remotive / Arbeitnow)")
            print(f"{'='*60}")
            print("  (Free remote-native boards — Nordics/CH/LU/EU remote roles)")
            try:
                remote_jobs = scrape_remote_apis_all(config)
                print(f"  → {len(remote_jobs)} jobs from remote APIs")
                save_raw_to_saved(remote_jobs, "remote_apis")
                all_jobs.extend(remote_jobs)
            except Exception as e:
                print(f"  ❌ Remote APIs scraper failed: {e}")
                scraper_failures.append("remote_apis")

        if "reed" in sites:
            print(f"\n{'='*60}")
            print("📋 REED SCRAPER")
            print(f"{'='*60}")
            try:
                reed_jobs = await scrape_reed_all(config)
                print(f"  → {len(reed_jobs)} jobs from Reed")
                save_raw_to_saved(reed_jobs, "reed")
                all_jobs.extend(reed_jobs)
            except Exception as e:
                print(f"  ❌ Reed scraper failed: {e}")
                scraper_failures.append("reed")

        # Recorded here, before the saved-jobs merge below adds to all_jobs, so
        # the number is what this site actually scraped. Only meaningful for a
        # single-site invocation, which is how the nightly calls this.
        if len(sites) == 1 and sites[0] not in scraper_failures:
            record_site_yield(sites[0], len(all_jobs))

        # --scrape-only stops here, having staged what it scraped.
        #
        # Everything below this line — the 00_saved merge, analysis, matching,
        # CV/CL generation — operates on every new job in the pool, not on the
        # jobs this invocation scraped. So the nightly's six `run.py --site X`
        # calls were six analysis passes over an accumulating backlog: on
        # 2026-08-18 they reported 26, 318, 333, 370 and 586 new jobs to analyse
        # as it grew, and each site's own timeout killed that shared work
        # part-way. remote_apis scraped its 57 jobs in seconds, then enriched 260
        # and died at 1500s while matching them — which also made per-site
        # elapsed times useless as a measure of any scraper.
        #
        # Six cheap scrapes and one analysis instead. --from-saved is the other
        # half and already existed.
        if args.scrape_only:
            print(f"\n{'='*60}")
            print(f"📦 SCRAPE-ONLY: {len(all_jobs)} jobs staged, stopping before analysis")
            if scraper_failures:
                print(f"  ⚠ failed: {', '.join(scraper_failures)}")
            print(f"{'='*60}")
            return

    if not _from_saved_mode:
        # Always ingest staged jobs (url-list.md extracts, raw staging, manual
        # saves) so extraction doesn't require a separate --from-saved run.
        # URL-level dedup below (and against the existing DB) drops repeats.
        staged = load_all_from_saved()
        if staged:
            _saved_jobs_to_merge.extend(staged)

    # Merge saved jobs (from --saved / 00_saved staging) into the analysis pipeline
    if _saved_jobs_to_merge:
        print(f"\n{'='*60}")
        print(f"📂 MERGING {len(_saved_jobs_to_merge)} SAVED JOBS INTO ANALYSIS")
        print(f"{'='*60}")
        # Deduplicate by URL (normalized — the same posting reaches this list
        # under both its clean URL and a tracking-param variant when url-list.md
        # holds both, and two records for one job is the result)
        existing_urls = {normalize_url(j["url"]) for j in all_jobs if j.get("url")}
        merged = 0
        for j in _saved_jobs_to_merge:
            u = normalize_url(j["url"]) if j.get("url") else None
            if u not in existing_urls:
                all_jobs.append(j)
                existing_urls.add(u)
                merged += 1
        print(f"  → Merged {merged} new jobs (skipped {len(_saved_jobs_to_merge) - merged} duplicates)")
        print(f"{'='*60}\n")

    if not all_jobs:
        print("\n⚠ No jobs scraped.")
        # Every site failing is the case that produces an empty all_jobs, so
        # returning None here would exit 0 and hide exactly the outage the exit
        # code at the end of this function exists to report.
        return 1 if (locals().get("scraper_failures") or []) else 0

    # --- Load existing _analyzed.json FIRST (incremental dedup) ---
    output_dir = os.path.join(os.path.dirname(__file__), config.get("output_dir", "output"))
    os.makedirs(output_dir, exist_ok=True)
    raw_path = os.path.join(output_dir, "_analyzed.json")

    existing_analyzed = []
    existing_urls: set[str] = set()
    if os.path.exists(raw_path):
        try:
            with open(raw_path, "r", encoding="utf-8") as f:
                existing_analyzed = json.load(f)
            # Normalized, because "known" is a property of the posting, not of
            # the string it was pasted as. A LinkedIn URL copied out of the app
            # carries ?lipi=<tracking>, an Adzuna one ?utm_medium=api — neither
            # changes the job, but both miss an exact-string match and get
            # ingested as a second copy of a job already in the DB. Those copies
            # score lower by construction (the filter/LLM budget has already
            # been spent on the original, so the re-scrape falls back to TF-IDF
            # context and loses the title_relevance rescue): Digital Waffle "AI
            # Applications Specialist" sat at 0.81 and its ?lipi= twin at 0.05,
            # and 12 such pairs were in the DB on 2026-08-07.
            existing_urls = {normalize_url(j["url"]) for j in existing_analyzed if j.get("url")}
            # duplicate_urls: alternate postings of jobs already merged away —
            # still "known", must not be re-ingested as new
            for j in existing_analyzed:
                existing_urls.update(normalize_url(u) for u in (j.get("duplicate_urls") or []))
            print(f"\n  📂 Existing DB: {len(existing_analyzed)} jobs ({len(existing_urls)} known URLs)")
        except Exception:
            existing_analyzed = []

    # --- Propagate collection route onto already-known jobs --------------
    # A URL re-submitted through a priority route (url_list / local_html)
    # may already live in the DB tagged with the default route (or none).
    # The incremental skip below drops it before its route is recorded, so
    # it would never satisfy the Dataview `route = "url_list"` filter and
    # never show up in "URL List Match Table.md". Copy the fresher route
    # onto the existing record here — match reports are fully regenerated
    # every run, so the frontmatter picks it up automatically.
    priority_routes = {"url_list", "local_html"}
    fresh_route_by_url: dict[str, str] = {}
    for j in all_jobs:
        u, r = j.get("url"), j.get("route")
        if u and r in priority_routes:
            fresh_route_by_url[normalize_url(u)] = r
    if fresh_route_by_url:
        route_upgraded = 0
        for j in existing_analyzed:
            for u in [j.get("url"), *(j.get("duplicate_urls") or [])]:
                r = fresh_route_by_url.get(normalize_url(u)) if u else None
                if r and j.get("route") != r:
                    j["route"] = r
                    route_upgraded += 1
                    break
        if route_upgraded:
            print(f"  🏷  Re-tagged route on {route_upgraded} already-known jobs")

    # --- Skip already-known jobs (incremental mode) ---
    new_jobs = [j for j in all_jobs
                if j.get("url") and normalize_url(j["url"]) not in existing_urls]
    no_url_jobs = [j for j in all_jobs if not j.get("url")]
    skipped_count = len(all_jobs) - len(new_jobs) - len(no_url_jobs)
    print(f"  🆕 {len(new_jobs)} new jobs to analyze (skipped {skipped_count} already in DB)")

    # --- Analyze only new jobs ---
    if new_jobs or no_url_jobs:
        print(f"\n{'='*60}")
        print("🔬 ANALYZING NEW JOBS...")
        print(f"{'='*60}")
        # One job at a time, with the failure contained. This was a single list
        # comprehension, so an exception on any job discarded the analysis of every
        # job before it: an adzuna run scraped 774 postings, then died inside this
        # line when every LLM provider was exhausted, and stored none of them. The
        # scrape survived only because save_raw_to_saved had already staged it.
        #
        # analyze_job reaches call_llm (extract_skills_ollama), so exhausting the
        # provider chain raises here — a normal end-state after a bulk day, not an
        # exceptional one. It must cost that job's enrichment, not the whole run.
        _to_analyze = new_jobs + no_url_jobs

        def _analyze_all(jobs, skip_llm, label):
            """Analyse a batch, containing per-job failures. Returns (results, fails)."""
            out, fails = [], 0
            for i, job in enumerate(jobs, 1):
                try:
                    out.append(analyze_job(job, skip_llm=skip_llm))
                except Exception as e:
                    fails += 1
                    if fails <= 3:
                        print(f"  ⚠ {label} failed for {(job.get('title') or '?')[:40]}: "
                              f"{type(e).__name__}: {str(e)[:70]}")
                        # Location too, not just the message. A bare
                        # "TypeError: unhashable type: 'list'" is unactionable —
                        # the frame is what says which field carried the list.
                        import traceback
                        print("    " + "    ".join(
                            traceback.format_exc(limit=4).splitlines(True)[-6:]).rstrip())
                    out.append(job)  # keep the posting, unenriched
                if i % 100 == 0 or i == len(jobs):
                    print(f"  … {i}/{len(jobs)} {label} ({fails} failed)", flush=True)
            return out, fails

        # Pass 1, no LLM. Everything passes_filter reads (salary, experience_level,
        # employment_types, work_style) comes from regex and rules, so the filter can
        # decide on this alone.
        print(f"  ① regex/rule pass over {len(_to_analyze)} jobs (no LLM)")
        _cheap, _ = _analyze_all(_to_analyze, True, "scanned")

        # Filter here, before paying for anything. Analysis used to run in full over
        # every scraped job and the filter came ~60 lines later, so ~35% of the LLM
        # spend went to postings dropped immediately afterwards — 213 of 890 on a
        # title keyword alone, which needs no model at all.
        _keep, _drop = filter_jobs(_cheap, config)
        print(f"  ② filter: {len(_keep)} kept, {len(_drop)} dropped before any LLM call")

        # Pass 2, LLM top-ups, on survivors only. analyze_job is idempotent, and the
        # top-ups only fire where the cheap pass fell short (<3 skills, or an
        # "unknown" level), so this re-run costs just the calls that add something.
        print(f"  ③ LLM enrichment for {len(_keep)} kept jobs")
        _enriched, _analyze_failures = _analyze_all(_keep, False, "enriched")
        if _analyze_failures:
            print(f"  ⚠ {_analyze_failures}/{len(_keep)} jobs kept without LLM "
                  f"enrichment (likely every provider rate-limited). Re-run "
                  f"`run.py --reanalyze` once keys recover.")

        # Dropped jobs stay in the DB with their cheap analysis: _analyzed.json is
        # deliberately a superset of what passes, so loosening a filter keyword later
        # does not need a re-scrape.
        new_analyzed = _enriched + _drop

        print(f"\n{'='*60}")
        print("🎯 MATCHING AGAINST YOUR PROFILE...")
        print(f"{'='*60}")
        user_skills = load_user_skills()
        user_exp = load_user_experience()
        total_skills = sum(len(s) for s in user_skills.values())
        print(f"  📋 Loaded profile: {total_skills} skills, {user_exp.get('years_python', 0)}y Python, {user_exp.get('years_linux', 0)}y Linux")
        # Scored separately, because the two groups are not worth the same spend.
        # analyze_match calls the LLM once per job for context scoring, and it was
        # doing so for the filter's rejects too: on 2026-08-05 that was 181 of 677
        # jobs — 27% of the pass — spent on postings already excluded by title,
        # level or salary. They still get a TF-IDF context score, so every job in
        # the DB keeps a composite and nothing downstream sees a hole; `run.py
        # --reanalyze` upgrades them for real if a filter is ever loosened.
        match_all(_enriched, config)
        if _drop:
            match_all(_drop, config, label="scored (filtered out, TF-IDF only)",
                      skip_llm_context=True)
            # The stretch tier is chosen from the rejects and then paid for
            # properly. It has to run in this order: the ranking is by skills
            # score, which only exists once a job has been matched at all, so
            # the cheap pass comes first and the handful it promotes are scored
            # again with the real context call. Without that second pass a
            # stretch job carries a TF-IDF context at 64% of the composite
            # weight and its report reads as a weak match whatever the CV
            # review later says.
            from selection import stretch_jobs
            _stretch = stretch_jobs(config, _drop)
            if _stretch:
                match_all(_stretch, config, label="rescored (stretch tier, LLM context)")
    else:
        new_analyzed = []
        print("  ✅ No new jobs — using existing DB")

    # --- Merge new into existing (by URL) ---
    merged_by_url = {j["url"]: j for j in existing_analyzed if j.get("url")}
    for j in new_analyzed:
        if j.get("url"):
            merged_by_url[j["url"]] = j
    merged_analyzed = list(merged_by_url.values())
    # Append no-URL jobs
    for j in new_analyzed:
        if not j.get("url"):
            merged_analyzed.append(j)

    # Merge duplicate postings (same company+title under different URLs)
    merged_analyzed, archived = dedupe_by_company_title(merged_analyzed)
    archive_duplicate_files(archived, output_dir)

    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(merged_analyzed, f, indent=2, ensure_ascii=False, default=str)
    print(f"  💾 DB updated: {len(merged_analyzed)} total jobs (+{len(new_analyzed)} new)")

    # --- Filter on ALL merged jobs (not just this run's new ones) ---
    # When --from-saved found nothing new and no route re-tag, skip the
    # expensive output regeneration (filter summary + 1811 match reports +
    # cover letters = 577KB of stdout).  These outputs are unchanged from
    # the last run that *did* have new jobs, so regenerating them is a no-op
    # that costs ~18 s of wall time and, via the Streamlit PIPE, the stall
    # observed 2026-08-06.  --reanalyze intentionally bypasses this skip.
    _skip_outputs = (
        not new_analyzed
        and not no_url_jobs
        and not locals().get("route_upgraded", 0)
        and not getattr(args, "reanalyze", False)
    )
    if _skip_outputs:
        print("  ⏭  No new jobs — skipping match report regeneration")
        passed = [j for j in merged_analyzed]  # final summary only
        filtered = []
    elif not args.no_filter:
        passed, filtered = filter_jobs(merged_analyzed, config)
        print_filter_summary(passed, filtered)
    else:
        passed = merged_analyzed
        filtered = []
        print("\n  ⚠ Skipping filter (--no-filter)")

    # --- Save filtered results as job-description.md files ---
    if merged_analyzed and not _skip_outputs:
        print(f"\n{'='*60}")
        print(f"💾 SAVING ALL JOBS & MATCH REPORTS...")
        print(f"{'='*60}")
        # Save to 00_matches for unified structure
        matches_dir = os.path.join(output_dir, "00_matches")
        os.makedirs(matches_dir, exist_ok=True)
        save_indeed(passed, matches_dir)
        # Save match reports for all jobs, CVs and cover letters for passed jobs
        generate_outputs(merged_analyzed, config, output_dir)

    # --- Summary ---
    if args.summary and not _skip_outputs:
        print_summary(passed)

    # --- Final stats ---
    print(f"\n{'='*60}")
    print(f"✅ PIPELINE COMPLETE")
    print(f"{'='*60}")
    _analyzed_count = len(locals().get('merged_analyzed', locals().get('analyzed', [])))
    print(f"  Scraped:   {len(all_jobs)} total")
    print(f"  Analyzed:  {_analyzed_count}")
    print(f"  Passed:    {len(passed)}")
    print(f"  Filtered:  {len(locals().get('filtered', []))}")
    print(f"  Output:    {output_dir}/")
    
    # Warn about missing descriptions (only when outputs were actually
    # regenerated — otherwise the warning is identical to the last run).
    if not _skip_outputs:
        missing_desc = [j for j in passed if j.get("match", {}).get("description_missing")]
        if missing_desc:
            print(f"\n  ⚠️  WARNING: {len(missing_desc)} matched jobs had missing descriptions (unreliable match score, no CV/CL generated):")
            for j in missing_desc:
                print(f"     - {j.get('company', 'Unknown')}: {j.get('title', 'Unknown')} ({j.get('url', 'No URL')})")
            
    print(f"{'='*60}\n")

    # Release file lock if held (--from-saved mode)
    if _saved_lock is not None:
        _saved_lock.close()

    # Non-zero exit when every requested site failed. Per-site failures stay
    # non-fatal on purpose (one dead board must not cost a night's other sites),
    # but "nothing scraped at all" has to be distinguishable from success, or the
    # cron keeps recording green runs — which is exactly how Indeed's Cloudflare
    # failure went unnoticed for 11 nights.
    failures = locals().get("scraper_failures") or []
    requested = locals().get("sites") or []
    if failures and requested and len(set(failures)) >= len(set(requested)):
        print(f"  ❌ every requested site failed: {', '.join(sorted(set(failures)))}")
        return 1
    if failures:
        print(f"  ⚠ {len(set(failures))}/{len(set(requested))} sites failed: "
              f"{', '.join(sorted(set(failures)))}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
