"""Configured local work, recognised from titles without model calls."""
from __future__ import annotations

import re


def local_job_role(title: str, config: dict | None = None) -> str | None:
    if config is None:
        from selection import load_config
        config = load_config()
    for role, profile in (config.get("local_job_profiles") or {}).items():
        def matches(phrase: str) -> bool:
            return bool(re.search(r"(?<!\w)" + re.escape(phrase) + r"s?(?!\w)",
                                  title or "", re.IGNORECASE))
        if any(matches(p) for p in profile.get("exclude_title_keywords", [])):
            continue
        if any(matches(p) for p in profile.get("title_keywords", [])):
            return role
    return None


def local_job_cv(role: str | None, config: dict) -> str:
    return (config.get("local_job_profiles", {}).get(role, {}).get("cv") or "")


def local_job_location_allowed(location: str, config: dict) -> bool:
    """Reject known distant locations; missing location still needs human checking."""
    location = (location or "").strip()
    if location.lower() in {"", "unknown", "not specified", "n/a"}:
        return True
    if any(re.search(r"(?<!\w)" + re.escape(place) + r"(?!\w)", location, re.IGNORECASE)
           for place in config.get("local_job_locations", ["Edinburgh", "Leith", "Newbridge"])):
        return True
    return bool(re.search(r"\bEH(?:1[0-7]|28|29|30|[1-9])(?:\s*\d[A-Z]{2})?\b", location, re.IGNORECASE))


def local_job_cv_file(role: str | None, config: dict):
    """The verified shared CV file, when it exists in the profile vault."""
    from pathlib import Path
    from matcher import USER_PROFILE_DIR
    cv = local_job_cv(role, config)
    source = Path(USER_PROFILE_DIR) / (cv + ".md") if cv else None
    return source if source and source.is_file() else None


def local_persona_extra(job: dict, config: dict) -> str:
    """Use the same verified local facts in initial scoring and later rescoring."""
    source = local_job_cv_file(local_job_role(job.get("title", ""), config), config)
    return "\n--- LOCAL WORK: VERIFIED SHARED CV ---\n" + source.read_text(encoding="utf-8") if source else ""
