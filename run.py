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
"""


import argparse
import asyncio
import json
import os
import re
import sys
import fcntl
from datetime import datetime

import yaml

from scraper_indeed import scrape_indeed_all, save_jobs as save_indeed
from scraper_linkedin import scrape_linkedin_all
from scraper_reed import scrape_reed_all
from scraper_guardian import scrape_guardian_all
from scraper_adzuna import scrape_adzuna_all
from analyzer import analyze_job
from filter import filter_jobs, print_filter_summary
from matcher import analyze_match, generate_match_report, load_user_skills, load_user_experience, make_safe_name
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
                    all_jobs.extend(json.load(fh))
            except Exception:
                pass
    # 2. Manual saved jobs via index
    all_jobs.extend(load_saved_from_index())
    return all_jobs


def generate_outputs(passed_jobs: list[dict], config: dict, output_dir: str):
    """Generate match reports, tailored CVs and cover letters for filter-passed jobs.

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

    cv_threshold = config.get("match_score_threshold", 0.50)
    cv_generated = 0
    cv_skipped = 0
    letter_generated = 0
    letter_skipped = 0

    for job in passed_jobs:
        match = job.get("match", {})
        if not match:
            continue
        base = make_safe_name(job.get('company', 'company'), job.get('title', 'job'))
        composite_score = match.get("composite_score", 0)

        # Pre-calculate base filenames (without paths or extensions for Obsidian links)
        match_filename = f"{base}"
        cv_name = f"{base}_CV"
        cl_name = f"{base}_CL"

        cv_filename_md = f"{cv_name}.md"
        cl_filename_md = f"{cl_name}.md"

        cv_filename_link = None
        cl_filename_link = None

        # Step 1: Generate CV first (if above threshold and description is available)
        if composite_score >= cv_threshold and not match.get("description_missing", False):
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
            cv_filename_link = cv_filename_md

            # Step 2: Generate cover letter (skip if exists)
            cl_path = os.path.join(letter_dir, cl_filename_md)
            if not os.path.exists(cl_path):
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
            else:
                letter_skipped += 1
            cl_filename_link = cl_filename_md
        else:
            cv_skipped += 1
            letter_skipped += 1

        # Step 3: Generate match report (with links to CV/CL)
        report = generate_match_report(job, match, cv_filename=cv_filename_link, cl_filename=cl_filename_link)
        report_path = os.path.join(match_dir, f"{match_filename}.md")
        with open(report_path, "w") as f:
            f.write(report)

    print(f"  📊 Saved {len(passed_jobs)} match reports to {match_dir}/")
    print(f"  📄 Saved {cv_generated} tailored CVs to {cv_dir}/ (skipped {cv_skipped} below {cv_threshold:.0%} threshold or missing desc)")
    print(f"  ✉️  Saved {letter_generated} cover letters to {letter_dir}/ (skipped {letter_skipped} below {cv_threshold:.0%} threshold or missing desc)")


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
    parser.add_argument("--site", choices=["indeed", "linkedin", "reed", "guardian", "adzuna", "all"], default="all")
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
    parser.add_argument("--from-saved", action="store_true", default=False,
                        help="Skip scraping, read everything from 00_saved/ staging")
    args = parser.parse_args()

    config = load_config()
    from filter import filter_jobs, print_filter_summary
    if args.pages:
        config["max_pages_per_search"] = args.pages

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
            for job in analyzed:
                if "match" not in job or not job["match"]:
                    job["match"] = analyze_match(job, config)

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
            
            if args.force_reanalyze:
                print("  🔄 Re-running full keyword/Ollama analysis (skills and experience classification) on all jobs...")
                for idx, job in enumerate(analyzed):
                    analyzed[idx] = analyze_job(job)
                    if (idx + 1) % 10 == 0 or idx + 1 == len(analyzed):
                        print(f"    → Re-analyzed {idx + 1}/{len(analyzed)} jobs...")
            else:
                print(f"  ⚡ Skipping re-analysis (use --force-reanalyze to re-run Ollama extraction)")
            
            # Run matcher and save match reports
            user_skills = load_user_skills()
            user_exp = load_user_experience()
            total_skills = sum(len(s) for s in user_skills.values())
            print(f"  📋 Loaded profile: {total_skills} skills, {user_exp.get('years_python', 0)}y Python, {user_exp.get('years_linux', 0)}y Linux")
            for job in analyzed:
                job["match"] = analyze_match(job, config, skip_summary=True)

            # --- LLM Context Match (optional, slow but accurate) ---
            if args.llm_context:
                from matcher import _ollama_context_score, _load_persona_summary

                # Pre-flight check: verify Ollama is alive before starting
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

            # Apply filters (title exclusion etc.) even in reanalyze mode
            passed, filtered_out = filter_jobs(analyzed, config)
            print_filter_summary(passed, filtered_out)
            # Save FULL data (including filtered-out jobs) for future refetch
            with open(full_data_path, "w") as f:
                json.dump(analyzed, f, indent=2)

            # NOTE: Previously this block deleted old reports/CVs not in the current filtered set.
            # Removed to preserve high-match reports across runs.
            generate_outputs(passed, config, output_dir)

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

        sites = ["reed", "guardian", "adzuna", "indeed", "linkedin"] if args.site == "all" else [args.site]

        all_jobs = []

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

        if "linkedin" in sites:
            print(f"\n{'='*60}")
            print("🔗 LINKEDIN SCRAPER")
            print(f"{'='*60}")
            print("  (LinkedIn requires login on first run — use non-headless)")
            try:
                linkedin_jobs = await scrape_linkedin_all(config)
                print(f"  → {len(linkedin_jobs)} jobs from LinkedIn")
                save_raw_to_saved(linkedin_jobs, "linkedin")
                all_jobs.extend(linkedin_jobs)
            except Exception as e:
                print(f"  ❌ LinkedIn scraper failed: {e}")

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

    # Merge saved jobs (from --saved) into the analysis pipeline
    if _saved_jobs_to_merge:
        print(f"\n{'='*60}")
        print(f"📂 MERGING {len(_saved_jobs_to_merge)} SAVED JOBS INTO ANALYSIS")
        print(f"{'='*60}")
        # Deduplicate by URL
        existing_urls = {j.get("url") for j in all_jobs if j.get("url")}
        merged = 0
        for j in _saved_jobs_to_merge:
            if j.get("url") not in existing_urls:
                all_jobs.append(j)
                existing_urls.add(j.get("url"))
                merged += 1
        print(f"  → Merged {merged} new jobs (skipped {len(_saved_jobs_to_merge) - merged} duplicates)")
        print(f"{'='*60}\n")

    if not all_jobs:
        print("\n⚠ No jobs scraped.")
        return

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
            existing_urls = {j["url"] for j in existing_analyzed if j.get("url")}
            print(f"\n  📂 Existing DB: {len(existing_analyzed)} jobs ({len(existing_urls)} unique URLs)")
        except Exception:
            existing_analyzed = []

    # --- Skip already-known jobs (incremental mode) ---
    new_jobs = [j for j in all_jobs if j.get("url") and j["url"] not in existing_urls]
    no_url_jobs = [j for j in all_jobs if not j.get("url")]
    skipped_count = len(all_jobs) - len(new_jobs) - len(no_url_jobs)
    print(f"  🆕 {len(new_jobs)} new jobs to analyze (skipped {skipped_count} already in DB)")

    # --- Analyze only new jobs ---
    if new_jobs or no_url_jobs:
        print(f"\n{'='*60}")
        print("🔬 ANALYZING NEW JOBS...")
        print(f"{'='*60}")
        new_analyzed = [analyze_job(j) for j in (new_jobs + no_url_jobs)]

        print(f"\n{'='*60}")
        print("🎯 MATCHING AGAINST YOUR PROFILE...")
        print(f"{'='*60}")
        user_skills = load_user_skills()
        user_exp = load_user_experience()
        total_skills = sum(len(s) for s in user_skills.values())
        print(f"  📋 Loaded profile: {total_skills} skills, {user_exp.get('years_python', 0)}y Python, {user_exp.get('years_linux', 0)}y Linux")
        for job in new_analyzed:
            job["match"] = analyze_match(job, config)
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

    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(merged_analyzed, f, indent=2, ensure_ascii=False, default=str)
    print(f"  💾 DB updated: {len(merged_analyzed)} total jobs (+{len(new_analyzed)} new)")

    # --- Filter on ALL merged jobs (not just this run's new ones) ---
    if not args.no_filter:
        passed, filtered = filter_jobs(merged_analyzed, config)
        print_filter_summary(passed, filtered)
    else:
        passed = merged_analyzed
        filtered = []
        print("\n  ⚠ Skipping filter (--no-filter)")

    # --- Save filtered results as job-description.md files ---
    if passed:
        print(f"\n{'='*60}")
        print(f"💾 SAVING FILTERED JOBS...")
        print(f"{'='*60}")
        # Save to 00_matches for unified structure
        matches_dir = os.path.join(output_dir, "00_matches")
        os.makedirs(matches_dir, exist_ok=True)
        save_indeed(passed, matches_dir)
        # Save match reports, CVs and cover letters
        generate_outputs(passed, config, output_dir)

    # --- Summary ---
    if args.summary:
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
    
    # Warn about missing descriptions
    missing_desc = [j for j in passed if j.get("match", {}).get("description_missing")]
    if missing_desc:
        print(f"\n  ⚠️  WARNING: {len(missing_desc)} matched jobs had missing descriptions (unreliable match score, no CV/CL generated):")
        for j in missing_desc:
            print(f"     - {j.get('company', 'Unknown')}: {j.get('title', 'Unknown')} ({j.get('url', 'No URL')})")
            
    print(f"{'='*60}\n")

    # Release file lock if held (--from-saved mode)
    if _saved_lock is not None:
        _saved_lock.close()


if __name__ == "__main__":
    asyncio.run(main())
