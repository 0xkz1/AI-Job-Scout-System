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
"""

import argparse
import asyncio
import json
import os
import re
import sys

import yaml

from scraper_indeed import scrape_indeed_all, save_jobs as save_indeed
from scraper_linkedin import scrape_linkedin_all
from analyzer import analyze_job
from filter import filter_jobs, print_filter_summary
from matcher import analyze_match, generate_match_report, load_user_skills, load_user_experience, make_safe_name
from cv_generator import generate_cv, detect_role_type
from cover_letter_generator import save_cover_letter

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    # Defaults
    cfg.setdefault("keywords", [])
    cfg.setdefault("locations", [""])
    cfg.setdefault("max_pages_per_search", 3)
    cfg.setdefault("sites", ["indeed"])
    cfg.setdefault("min_salary_gbp", 0)
    cfg.setdefault("include_levels", ["entry_level", "mid_senior", "director"])
    cfg.setdefault("employment_types", ["full_time", "part_time", "contract"])
    cfg.setdefault("exclude_title_keywords", [])
    cfg.setdefault("exclude_description_keywords", [])
    cfg.setdefault("output_dir", "output")
    return cfg


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
    parser.add_argument("--site", choices=["indeed", "linkedin", "all"], default="all")
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
    args = parser.parse_args()

    config = load_config()
    if args.pages:
        config["max_pages_per_search"] = args.pages

    # --- Re-analyze existing data if requested ---
    if args.reanalyze:
        print(f"\n{'='*60}")
        print("🔄 RE-ANALYZING EXISTING DATA...")
        print(f"{'='*60}")
        output_dir = os.path.join(os.path.dirname(__file__), config.get("output_dir", "output"))
        raw_path = os.path.join(output_dir, "_analyzed.json")
        if os.path.exists(raw_path):
            with open(raw_path) as f:
                analyzed = json.load(f)
            print(f"  📂 Loaded {len(analyzed)} pre-analyzed jobs from {raw_path}")
            print(f"  ⚡ Skipping re-analysis (use --force-reanalyze to re-run Ollama extraction)")
            
            # Run matcher and save match reports
            user_skills = load_user_skills()
            user_exp = load_user_experience()
            total_skills = sum(len(s) for s in user_skills.values())
            print(f"  📋 Loaded profile: {total_skills} skills, {user_exp.get('years_python', 0)}y Python, {user_exp.get('years_linux', 0)}y Linux")
            for job in analyzed:
                job["match"] = analyze_match(job, config)
            
            # Save match reports
            match_dir = os.path.join(output_dir, "00_matches")
            os.makedirs(match_dir, exist_ok=True)
            cv_dir = os.path.join(output_dir, "00_cvs")
            os.makedirs(cv_dir, exist_ok=True)
            letter_dir = os.path.join(output_dir, "00_cover-letters")
            os.makedirs(letter_dir, exist_ok=True)
            
            import re
            cv_threshold = config.get("match_score_threshold", 0.50)
            cv_generated = 0
            cv_skipped = 0
            letter_generated = 0
            letter_skipped = 0
            
            for job in analyzed:
                match = job.get("match", {})
                if match:
                    base = make_safe_name(job.get('company', 'company'), job.get('title', 'job'))
                    composite_score = match.get("composite_score", 0)

                    cv_filename = None
                    cl_filename = None

                    # Step 1: Generate CV first (if above threshold)
                    if composite_score >= cv_threshold:
                        role_type = detect_role_type(job.get('title', ''), job.get('description', ''))
                        cv = generate_cv(role_type)
                        cv_filename = f"{base}_CV.md"
                        cv_path = os.path.join(cv_dir, cv_filename)
                        with open(cv_path, "w") as f:
                            f.write(cv)
                        cv_generated += 1

                        # Step 2: Generate cover letter
                        cl_path = save_cover_letter(
                            job.get('title', ''),
                            job.get('company', ''),
                            job.get('location', 'Edinburgh'),
                            job.get('description', ''),
                            letter_dir
                        )
                        cl_filename = os.path.basename(cl_path)
                        letter_generated += 1
                    else:
                        cv_skipped += 1
                        letter_skipped += 1

                    # Step 3: Generate match report (with links to CV/CL)
                    report = generate_match_report(job, match, cv_filename=cv_filename, cl_filename=cl_filename)
                    report_path = os.path.join(match_dir, f"{base}.md")
                    with open(report_path, "w") as f:
                        f.write(report)
            
            print(f"  📊 Saved {len(analyzed)} match reports to {match_dir}/")
            print(f"  📄 Saved {cv_generated} tailored CVs to {cv_dir}/ (skipped {cv_skipped} below {cv_threshold:.0%} threshold)")
            print(f"  ✉️  Saved {letter_generated} cover letters to {letter_dir}/ (skipped {letter_skipped} below {cv_threshold:.0%} threshold)")
            
            print(f"{'='*60}\n")
            return

    # --- Run saved jobs scraper first if requested ---
    if args.saved:
        print(f"\n{'='*60}")
        print("💾 SAVED JOBS SCRAPER")
        print(f"{'='*60}")
        # Run as subprocess to avoid Playwright context conflicts
        import subprocess
        result = subprocess.run(
            [sys.executable, "scraper_saved.py", "--max-jobs", "50"],
            cwd=os.path.dirname(__file__),
            timeout=300,
        )
        if result.returncode != 0:
            print(f"  ⚠ Saved scraper exited with code {result.returncode}")
        print(f"{'='*60}\n")

    sites = ["indeed", "linkedin"] if args.site == "all" else [args.site]

    all_jobs = []

    if "indeed" in sites:
        print(f"\n{'='*60}")
        print("🌐 INDEED SCRAPER")
        print(f"{'='*60}")
        indeed_jobs = await scrape_indeed_all(config)
        print(f"  → {len(indeed_jobs)} jobs from Indeed")
        all_jobs.extend(indeed_jobs)

    if "linkedin" in sites:
        print(f"\n{'='*60}")
        print("🔗 LINKEDIN SCRAPER")
        print(f"{'='*60}")
        print("  (LinkedIn requires login on first run — use non-headless)")
        linkedin_jobs = await scrape_linkedin_all(config)
        print(f"  → {len(linkedin_jobs)} jobs from LinkedIn")
        all_jobs.extend(linkedin_jobs)

    if not all_jobs:
        print("\n⚠ No jobs scraped.")
        return

    # --- Analyze ---
    print(f"\n{'='*60}")
    print("🔬 ANALYZING JOBS...")
    print(f"{'='*60}")
    analyzed = [analyze_job(j) for j in all_jobs]

    # --- Match against user profile ---
    print(f"\n{'='*60}")
    print("🎯 MATCHING AGAINST YOUR PROFILE...")
    print(f"{'='*60}")
    user_skills = load_user_skills()
    user_exp = load_user_experience()
    total_skills = sum(len(s) for s in user_skills.values())
    print(f"  📋 Loaded profile: {total_skills} skills, {user_exp.get('years_python', 0)}y Python, {user_exp.get('years_linux', 0)}y Linux")
    for job in analyzed:
        job["match"] = analyze_match(job, config)

    # --- Save raw analyzed results ---
    output_dir = os.path.join(os.path.dirname(__file__), config.get("output_dir", "output"))
    os.makedirs(output_dir, exist_ok=True)

    raw_path = os.path.join(output_dir, "_analyzed.json")
    with open(raw_path, "w") as f:
        json.dump(analyzed, f, indent=2, ensure_ascii=False, default=str)
    print(f"  💾 Saved analyzed data to {raw_path}")

    # --- Filter ---
    if not args.no_filter:
        passed, filtered = filter_jobs(analyzed, config)
        print_filter_summary(passed, filtered)
    else:
        passed = analyzed
        filtered = []
        print("\n  ⚠ Skipping filter (--no-filter)")

    # --- Save filtered results as job-description.md files ---
    
    # Score threshold for CV generation (default 0.50 = 50%)
    cv_threshold = config.get("match_score_threshold", 0.50)
    
    if passed:
        print(f"\n{'='*60}")
        print(f"💾 SAVING FILTERED JOBS...")
        print(f"{'='*60}")
        # Save to 00_matches for unified structure
        matches_dir = os.path.join(output_dir, "00_matches")
        os.makedirs(matches_dir, exist_ok=True)
        save_indeed(passed, matches_dir)
        # Save match reports
        match_dir = os.path.join(output_dir, "00_matches")
        os.makedirs(match_dir, exist_ok=True)
        cv_dir = os.path.join(output_dir, "00_cvs")
        os.makedirs(cv_dir, exist_ok=True)
        letter_dir = os.path.join(output_dir, "00_cover-letters")
        os.makedirs(letter_dir, exist_ok=True)
        
        cv_generated = 0
        cv_skipped = 0
        letter_generated = 0
        letter_skipped = 0
        
        for job in passed:
            match = job.get("match", {})
            if match:
                base = make_safe_name(job.get('company', 'company'), job.get('title', 'job'))
                composite_score = match.get("composite_score", 0)

                cv_filename = None
                cl_filename = None

                # Step 1: Generate CV first (if above threshold)
                if composite_score >= cv_threshold:
                    role_type = detect_role_type(job.get('title', ''), job.get('description', ''))
                    cv = generate_cv(role_type)
                    cv_filename = f"{base}_CV.md"
                    cv_path = os.path.join(cv_dir, cv_filename)
                    with open(cv_path, "w") as f:
                        f.write(cv)
                    cv_generated += 1

                    # Step 2: Generate cover letter
                    cl_path = save_cover_letter(
                        job.get('title', ''),
                        job.get('company', ''),
                        job.get('location', 'Edinburgh'),
                        job.get('description', ''),
                        letter_dir
                    )
                    cl_filename = os.path.basename(cl_path)
                    letter_generated += 1
                else:
                    cv_skipped += 1
                    letter_skipped += 1

                # Step 3: Generate match report (with links to CV/CL)
                report = generate_match_report(job, match, cv_filename=cv_filename, cl_filename=cl_filename)
                report_path = os.path.join(match_dir, f"{base}.md")
                with open(report_path, "w") as f:
                    f.write(report)
        
        print(f"  📊 Saved {len(passed)} match reports to {match_dir}/")
        print(f"  📄 Saved {cv_generated} tailored CVs to {cv_dir}/ (skipped {cv_skipped} below {cv_threshold:.0%} threshold)")
        print(f"  ✉️  Saved {letter_generated} cover letters to {letter_dir}/ (skipped {letter_skipped} below {cv_threshold:.0%} threshold)")

    # --- Summary ---
    if args.summary:
        print_summary(passed)

    # --- Final stats ---
    print(f"\n{'='*60}")
    print(f"✅ PIPELINE COMPLETE")
    print(f"{'='*60}")
    print(f"  Scraped:   {len(all_jobs)} total")
    print(f"  Analyzed:  {len(analyzed)}")
    print(f"  Passed:    {len(passed)}")
    print(f"  Filtered:  {len(filtered)}")
    print(f"  Output:    {output_dir}/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
