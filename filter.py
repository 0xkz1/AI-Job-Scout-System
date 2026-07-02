"""
Job Filter
==========
Filters analyzed job listings based on user preferences from config.yaml.
"""

import re
from typing import Any


def passes_filter(job: dict, config: dict) -> tuple[bool, str]:
    """
    Check if a job passes all configured filters.
    Returns (True, "") or (False, "reason why filtered out").
    """
    analysis = job.get("analysis", {})
    title = job.get("title", "")
    description = (job.get("description", "") or job.get("snippet", "") or "")
    salary = analysis.get("salary", {})
    level = analysis.get("experience_level", "unknown")

    # --- Exclude by title keywords ---
    exclude_titles = config.get("exclude_title_keywords", [])
    title_lower = title.lower()
    for kw in exclude_titles:
        if kw.lower() in title_lower:
            return False, f"title contains excluded keyword '{kw}'"

    # --- Exclude by description keywords ---
    exclude_desc = config.get("exclude_description_keywords", [])
    desc_lower = description.lower()
    for kw in exclude_desc:
        if kw.lower() in desc_lower:
            return False, f"description contains excluded keyword '{kw}'"

    # --- Filter by experience level ---
    allowed_levels = config.get("include_levels", [])
    if allowed_levels:
        # If job level is "unknown", let it pass (we can't be sure)
        if level != "unknown" and level not in allowed_levels:
            return False, f"level '{level}' not in allowed levels {allowed_levels}"

    # --- Filter by salary ---
    min_salary = config.get("min_salary_gbp", 0)
    if min_salary > 0 and salary.get("max"):
        if salary["max"] < min_salary:
            return False, f"max salary £{salary['max']:.0f} < min £{min_salary}"

    # --- Filter by employment type ---
    allowed_types = config.get("employment_types", [])
    if allowed_types:
        job_types = analysis.get("employment_types", ["unknown"])
        # If all detected types are unknown, let it pass
        detected_known = [t for t in job_types if t != "unknown"]
        if detected_known:
            if not any(t in allowed_types for t in detected_known):
                return False, f"employment type {detected_known} not in allowed {allowed_types}"

    return True, ""


def filter_jobs(jobs: list[dict], config: dict) -> tuple[list[dict], list[dict]]:
    """
    Filter all jobs. Returns (passed_jobs, filtered_out_jobs).
    """
    passed = []
    filtered = []

    for job in jobs:
        ok, reason = passes_filter(job, config)
        if ok:
            passed.append(job)
        else:
            job["_filter_reason"] = reason
            filtered.append(job)

    return passed, filtered


def print_filter_summary(passed: list, filtered: list):
    """Pretty-print filter results."""
    print(f"\n{'='*60}")
    print(f"📊 FILTER SUMMARY")
    print(f"{'='*60}")
    print(f"  ✅ Passed:     {len(passed)} jobs")
    print(f"  ❌ Filtered:   {len(filtered)} jobs")

    if filtered:
        print(f"\n  Filtered out reasons:")
        reasons = {}
        for j in filtered:
            r = j.get("_filter_reason", "unknown")
            reasons[r] = reasons.get(r, 0) + 1
        for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    • {r}: {c} jobs")
