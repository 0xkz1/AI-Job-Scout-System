"""
Job Filter
==========
Filters analyzed job listings based on user preferences from config.yaml.
"""

import re
from typing import Any

# UK full-time convention: 37.5h/week over 52 weeks.
_HOURS_PER_YEAR = 37.5 * 52

# Below this, an "annual" figure is not a salary. parse_salary tags anything
# without "hour" in the text as annual, so a stray pair of numbers in a
# description becomes min=1.0/max=2.0 — 33 such rows exist, several from postings
# reading only "Salary negotiable". Rejecting a job for a £2 salary would be
# absurd, so an implausible annual figure is treated as no data at all.
_MIN_PLAUSIBLE_ANNUAL = 1000


def _annualise(amount: float, period: str | None) -> float | None:
    """`amount` as an annual figure, or None when it cannot be trusted.

    None means "do not filter on this" rather than zero — an unparseable or
    implausible salary must not be read as a low one.
    """
    if amount is None:
        return None
    if period == "hourly":
        return amount * _HOURS_PER_YEAR
    # annual, or unknown-but-annual-shaped
    return amount if amount >= _MIN_PLAUSIBLE_ANNUAL else None


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

    # --- Exclude by title keywords (word-boundary match, title only) ---
    # Uses \b word boundaries so "senior" matches "Senior Developer" but NOT
    # "seniority" or description text like "cooperate with senior engineers".
    exclude_titles = config.get("exclude_title_keywords", [])
    title_lower = title.lower()
    for kw in exclude_titles:
        kw_lower = kw.lower().strip()
        if kw_lower and re.search(r'\b' + re.escape(kw_lower) + r'\b', title_lower):
            return False, f"title contains excluded keyword '{kw}'"

    # --- Exclude by description keywords (word-boundary match) ---
    exclude_desc = config.get("exclude_description_keywords", [])
    desc_lower = description.lower()
    for kw in exclude_desc:
        kw_lower = kw.lower().strip()
        if kw_lower and re.search(r'\b' + re.escape(kw_lower) + r'\b', desc_lower):
            return False, f"description contains excluded keyword '{kw}'"

    # --- Exclude by timezone lock (Americas-hours remote = night shift) ---
    # Scans title + description. Phrases in config are specific enough that a
    # plain substring check won't false-positive on incidental "EST"/"CET" text.
    exclude_tz = config.get("exclude_timezone_keywords", [])
    haystack = (title_lower + " " + desc_lower)
    for kw in exclude_tz:
        kw_lower = kw.lower().strip()
        if kw_lower and kw_lower in haystack:
            return False, f"timezone-locked (Americas): '{kw}'"

    # --- Filter by experience level ---
    allowed_levels = config.get("include_levels", [])
    if allowed_levels:
        # If job level is "unknown", let it pass (we can't be sure)
        if level != "unknown" and level not in allowed_levels:
            return False, f"level '{level}' not in allowed levels {allowed_levels}"

    # --- Filter by salary ---
    # min_salary_gbp is annual, so a non-annual figure has to be converted before
    # the comparison means anything. Comparing raw values rejected every hourly and
    # daily posting outright: "£30 - £35 per hour" read as "max salary £35 < £26000"
    # and was dropped, though it annualises to roughly £67k. 33 postings in the DB
    # carried a max under 100 — all of them hourly or daily rates.
    min_salary = config.get("min_salary_gbp", 0)
    if min_salary > 0 and salary.get("max"):
        annual = _annualise(salary["max"], salary.get("period"))
        if annual is not None and annual < min_salary:
            unit = f" ({salary['period']})" if salary.get("period") else ""
            return False, (f"max salary £{salary['max']:.0f}{unit} "
                           f"≈ £{annual:.0f}/yr < min £{min_salary}")

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
