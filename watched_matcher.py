#!/usr/bin/env python3
"""
Watched Jobs Matcher
====================
Scans watched-list/ for manually pasted job description MDs,
runs them through the analyze_job → analyze_match pipeline,
generates match reports, and appends match-report links back
into the original Watched MD files.

Usage:
    python3 watched_matcher.py                    # Match all watched MDs
    python3 watched_matcher.py --llm-context      # Also run Ollama LLM context scoring
    python3 watched_matcher.py --llm-limit 10      # Limit LLM to top N by composite score
    python3 watched_matcher.py --force            # Re-analyze even if link already exists

File format expected in watched-list/:
    # Job Title (first H1 line)
    <rest of file = job description text>

If no H1 found, filename (without .md) is used as title.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Resolve project root from __file__
PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "10_output"
WATCHED_DIR = PROJECT_ROOT / "00_saved" / "watched-list"
MATCH_DIR = OUTPUT_DIR / "00_matches"

# Import from project root
sys.path.insert(0, str(PROJECT_ROOT))

from analyzer import analyze_job
from matcher import (
    analyze_match,
    generate_match_report,
    make_safe_name,
    load_user_skills,
    load_user_experience,
)

# --- Config loading ---
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def _load_config() -> dict:
    """Load config.yaml."""
    import yaml
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    cfg.setdefault("output_dir", "10_output")
    cfg.setdefault("match_score_threshold", 0.50)
    return cfg


# --- MD parsing ---

def parse_watched_md(filepath: Path) -> dict | None:
    """
    Parse a manually-pasted job description MD into a job dict.
    Returns None on unrecoverable errors.
    """
    try:
        content = filepath.read_text(encoding="utf-8").strip()
    except Exception as e:
        print(f"  ✗ Cannot read {filepath.name}: {e}")
        return None

    if not content or len(content) < 20:
        print(f"  ⚠ {filepath.name}: too short, skipping")
        return None

    lines = content.split("\n")

    # Extract title from first H1
    title = ""
    description_lines = []
    found_h1 = False
    for i, line in enumerate(lines):
        if not found_h1 and line.strip().startswith("# ") and not line.strip().startswith("## "):
            title = line.strip().lstrip("# ").strip()
            description_lines = lines[i + 1:]
            found_h1 = True
            break

    if not found_h1:
        # No H1 found — use filename
        title = filepath.stem.replace("_", " ").replace("-", " ")
        description_lines = lines

    description = "\n".join(description_lines).strip()

    # Try to extract URL from content
    url_match = re.search(r'https?://[^\s\)\]]+', content)
    url = url_match.group() if url_match else ""

    # Try to extract company: look for patterns like "Company: X" or "**Company**" or filename
    company = "Unknown"
    company_match = re.search(r'(?:Company|Employer)[:\s]*\*?\*?([^*\n]{2,60})', content, re.IGNORECASE)
    if company_match:
        company = company_match.group(1).strip()

    # If still Unknown, try filename
    if company == "Unknown":
        # Filename like "Company_JobTitle.md" → take part before last _
        parts = filepath.stem.rsplit("_", 1)
        if len(parts) > 1:
            company = parts[0].replace("_", " ").replace("-", " ")
        else:
            company = filepath.stem.replace("_", " ")

    # Try to extract location
    location = "Unknown"
    loc_match = re.search(r'(?:Location|Based in|Office)[:\s]*([^|\n]{2,60})', content, re.IGNORECASE)
    if loc_match:
        location = loc_match.group(1).strip()
    else:
        # Try common UK city names
        for city in ["Edinburgh", "Glasgow", "London", "Manchester", "Birmingham", "Remote", "Berlin", "Amsterdam"]:
            if city.lower() in content.lower():
                location = city
                break

    job = {
        "title": title[:200],
        "company": company[:200],
        "location": location[:200],
        "salary": "",
        "description": description,
        "snippet": description[:500] if description else "",
        "url": url,
        "source": "watched",
        "type": "manual",
        "source_site": "Manual",
        "scraped_at": datetime.now().isoformat(),
    }

    return job


# --- Match link management ---

MATCH_LINK_HEADER = "## Match Analysis"
MATCH_LINK_PATTERN = re.compile(
    r'\n---\n\n## Match Analysis\n\[Match Report\]\(\.\./00_matches/watched_[^\)]+\)',
    re.DOTALL
)


def remove_existing_match_link(content: str) -> str:
    """Remove existing Match Analysis section from watched MD content."""
    return MATCH_LINK_PATTERN.sub("", content)


def append_match_link(filepath: Path, match_filename: str) -> bool:
    """
    Append (or update) a match-report link at the end of the watched MD.
    Returns True if file was modified.
    """
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return False

    # Remove existing match link if present
    content = remove_existing_match_link(content)

    # Append fresh link
    link_block = f"\n---\n\n{MATCH_LINK_HEADER}\n[Match Report](../00_matches/{match_filename})\n"
    content = content.rstrip() + "\n" + link_block

    filepath.write_text(content, encoding="utf-8")
    return True


def has_match_link(filepath: Path) -> bool:
    """Check if the watched MD already has a match link."""
    try:
        content = filepath.read_text(encoding="utf-8")
        return bool(MATCH_LINK_PATTERN.search(content))
    except Exception:
        return False


# --- LLM Context Score ---

def run_llm_context(jobs: list[dict], limit: int | None = None) -> None:
    """Run Ollama LLM context scoring on jobs (modifies in-place)."""
    from matcher import _ollama_context_score, _load_persona_summary

    persona = _load_persona_summary()
    if not persona:
        print("  ⚠ No persona summary loaded — skipping LLM context scoring")
        return

    # Sort by composite score, take top N
    sorted_jobs = sorted(jobs, key=lambda j: j.get("match", {}).get("composite_score", 0), reverse=True)
    if limit:
        sorted_jobs = sorted_jobs[:limit]

    print(f"  🧠 LLM Context Match: scoring {len(sorted_jobs)} watched jobs with Ollama...")
    persona = _load_persona_summary()
    done = 0
    for job in sorted_jobs:
        desc = job.get("description", "") or job.get("snippet", "")
        if desc and len(desc) > 30:
            ctx = _ollama_context_score(desc, persona)
            if ctx:
                job["match"]["context_score"] = ctx["score"]
                job["match"]["context_reasoning"] = ctx.get("reasoning", "")
                job["match"]["context_reasoning_en"] = ctx.get("reasoning_en", "")
                job["match"]["context_reasoning_ja"] = ctx.get("reasoning_ja", "")
                job["match"]["context_source"] = "llm"

                # Recompute composite
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

                done += 1
                if done % 3 == 0:
                    print(f"    → LLM scored {done}/{len(sorted_jobs)}...")

    print(f"  ✅ LLM Context Match complete ({done} scored)")


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Watched Jobs Matcher")
    parser.add_argument("--llm-context", action="store_true", default=False,
                        help="Use Ollama LLM for context/ethos matching")
    parser.add_argument("--llm-limit", type=int, default=None,
                        help="Limit LLM context matching to top N jobs by score")
    parser.add_argument("--force", action="store_true", default=False,
                        help="Re-analyze even if match link already exists")
    args = parser.parse_args()

    # Ensure watched-list directory exists
    if not WATCHED_DIR.exists():
        WATCHED_DIR.mkdir(parents=True, exist_ok=True)
        # Create README
        readme = WATCHED_DIR / "README.md"
        readme.write_text(_readme_content(), encoding="utf-8")
        print(f"📁 Created {WATCHED_DIR} with README.md")
        print("   Place job description MDs in this folder and re-run.")
        return

    # Find all non-README MDs
    watched_mds = sorted([
        f for f in WATCHED_DIR.glob("*.md")
        if f.name.lower() != "readme.md"
    ])

    if not watched_mds:
        print(f"📭 No watched job MDs found in {WATCHED_DIR}/")
        print("   Place job description MDs (1 job per file) and re-run.")
        return

    print(f"\n{'='*60}")
    print(f"👁 WATCHED JOBS MATCHER")
    print(f"{'='*60}")
    print(f"  Found {len(watched_mds)} watched job MDs")

    # Load config and user profile
    config = _load_config()
    user_skills = load_user_skills()
    user_exp = load_user_experience()
    total_skills = sum(len(s) for s in user_skills.values())
    print(f"  📋 Loaded profile: {total_skills} skills, {user_exp.get('years_python', 0)}y Python, {user_exp.get('years_linux', 0)}y Linux")

    # Process each MD
    jobs = []
    skipped = 0
    for md_path in watched_mds:
        if not args.force and has_match_link(md_path):
            print(f"  ⏭ {md_path.name}: already has match link (use --force to re-analyze)")
            skipped += 1
            continue

        job = parse_watched_md(md_path)
        if job is None:
            skipped += 1
            continue

        jobs.append(job)

    if not jobs:
        print(f"\n  No jobs to analyze ({skipped} skipped). Use --force to re-analyze existing ones.")
        return

    print(f"\n  → Analyzing {len(jobs)} jobs...")

    # Run analyzer on each job
    for job in jobs:
        job["analysis"] = analyze_job(job)

    # Run matcher on each job
    for job in jobs:
        job["match"] = analyze_match(job, config)

    # LLM Context scoring (optional)
    if args.llm_context:
        run_llm_context(jobs, limit=args.llm_limit)

    # Ensure match output directory exists
    MATCH_DIR.mkdir(parents=True, exist_ok=True)

    # Generate match reports and append links
    print(f"\n{'='*60}")
    print(f"📊 MATCH RESULTS")
    print(f"{'='*60}")
    results = []
    for job in jobs:
        match = job["match"]
        score = match.get("composite_score", 0)
        tier = match.get("tier", "?")
        safe_name = make_safe_name(job.get("company", "unknown"), job.get("title", "unknown"))
        match_filename = f"watched_{safe_name}.md"
        match_path = MATCH_DIR / match_filename

        # Generate and save match report
        report = generate_match_report(job, match)
        match_path.write_text(report, encoding="utf-8")

        # Append link back to watched MD
        # Find the original filepath — need to match by company+title
        # We stored jobs in order with watched_mds, but some were skipped
        # Re-derive from safe_name
        original_md = None
        for md_path in watched_mds:
            if md_path.name.lower() == "readme.md":
                continue
            # Check if this md_path was used for this job
            if not args.force and has_match_link(md_path):
                continue
            # Match by checking content title
            try:
                md_content = md_path.read_text(encoding="utf-8")
                if job["title"] in md_content or job["company"] in md_content:
                    original_md = md_path
                    break
            except Exception:
                continue

        if original_md:
            append_match_link(original_md, match_filename)

        results.append({
            "title": job["title"],
            "company": job["company"],
            "score_pct": int(score * 100),
            "tier": tier,
            "match_file": match_filename,
        })

        print(f"  {tier} ({int(score*100)}%) — {job['title']} @ {job['company']}")

    # Final summary
    print(f"\n{'='*60}")
    print(f"📋 SUMMARY: {len(results)} watched jobs analyzed")
    print(f"   {skipped} skipped (already analyzed — use --force to re-run)")
    if results:
        best = max(results, key=lambda r: r["score_pct"])
        worst = min(results, key=lambda r: r["score_pct"])
        print(f"   Best: {best['tier']} ({best['score_pct']}%) — {best['title']} @ {best['company']}")
        print(f"   Worst: {worst['tier']} ({worst['score_pct']}%) — {worst['title']} @ {worst['company']}")
    print(f"   Reports: {MATCH_DIR}/watched_*.md")
    print(f"{'='*60}\n")


def _readme_content() -> str:
    return """# Watched Jobs

Place job description MDs in this folder for match analysis.

## Usage

1. **Copy-paste** a job description into a new `.md` file here.
2. **Format:**
   - First line: `# Job Title` (H1)
   - Remaining lines: full job description text
3. **Filename:** `CompanyName_JobTitle.md` (recommended)
4. Run: `python3 watched_matcher.py`
   - Add `--llm-context` for Ollama LLM context scoring
   - Add `--force` to re-analyze already-processed files

## What happens

- Each MD is parsed into a job dict (title, company, description, etc.)
- The job goes through `analyzer.py` (skill extraction, level classification)
- Then `matcher.py` (match score against your profile)
- A match report is generated in `output/00_matches/watched_*.md`
- A link to that report is **appended to this file** automatically
"""


if __name__ == "__main__":
    main()
