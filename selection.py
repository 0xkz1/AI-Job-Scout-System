"""One place that decides which jobs each pipeline stage acts on.

The cutoff used to live in three unrelated forms — an absolute score threshold
plus a count cap for generation (run.py), a hardcoded --limit for review
(rereview_top.py), and a top-3% calculation elsewhere (_regen_and_review.py).
Nothing kept them in step, so "the top jobs" meant a different set at each
stage and CVs, cover letters and reviews drifted apart.

Now every stage asks the same question here: given the ranked, filter-passed
pool, which jobs fall in this stage's top N percent? The percentages live in
config.yaml (generation_top_percent, review_top_percent) so one number governs
each stage.

A score floor (match_score_threshold) is kept as a quality guard only: when the
pool is small, "top 10%" could otherwise include weak matches, and no CV should
be written for a job the candidate barely fits. It never expands the set — it
only trims matches below the floor.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
ANALYZED = ROOT / "10_output" / "_analyzed.json"

# Stage → config key holding that stage's top-percent. Add a stage here and it
# is available everywhere; no caller hardcodes a percentage.
_STAGE_KEYS = {
    "generation": "generation_top_percent",
    "review": "review_top_percent",
}
_DEFAULT_PERCENT = 20.0


def load_config() -> dict:
    try:
        return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def max_pages_for(site: str, config: dict | None = None) -> int:
    """Result pages to scrape for one site, from max_pages_per_site[site] with
    max_pages_per_search as the fallback.

    One depth for every site is wrong in both directions, and measurably so. Each
    site walks keywords x locations (9 x 7 = 63 searches) fully serially, so depth
    multiplies straight into wall-clock: at 10 pages, reed and adzuna both hit the
    1500s per-site cron timeout (exit 124) and were killed mid-run — which is where
    the half-written descriptions behind the unscoreable backlog came from.

    But flattening everything to 3 is not free either: 22% of reed's 706 jobs came
    from page 4+, including 18 of the 134 jobs in the current top 30%. Adzuna drew
    0 jobs from page 4+, so depth there bought nothing but timeout. Hence per-site.
    """
    config = config if config is not None else load_config()
    default = int(config.get("max_pages_per_search", 3))
    per_site = config.get("max_pages_per_site") or {}
    try:
        return max(1, int(per_site.get(site, default)))
    except (TypeError, ValueError):
        return default


def _dedupe(jobs: list[dict]) -> list[dict]:
    """One entry per (company, title) — the one scored against the fullest
    description.

    Repeat scrapes of the same posting are stored as separate entries and scored
    independently, and the same posting can score very differently across them:
    Penguin Recruitment's "Geotechnical Design Engineer" was held at 0.34, 0.38
    AND 0.66. Downstream that split is invisible but harmful, because
    make_safe_name(company, title) maps all of them to ONE document path — so the
    match report on disk came from whichever entry was written last while
    selection ranked by the highest-scoring one. A job could sit in the top N%
    while its own report read "Weak Match".

    Keeping the fullest description (not the best score) is the point: score
    spread between duplicates is mostly denominator noise from how many skills
    got extracted, so picking max score would systematically keep the entry
    scored on the least evidence. Usable prose outranks raw length, or a scrape
    that captured kilobytes of tracker JavaScript would beat the real posting.

    Deliberately stricter than run.dedupe_by_company_title, which also requires
    the descriptions to match (_same_posting) so that two genuinely different
    roles filed under one bad title are not merged. That caution is right when
    building the database, but it leaves the Geotechnical case behind: three
    scrapes, descriptions of 2280/2150/2815 chars, so no two "matched" and all
    three survived. Selection cannot carry them, because make_safe_name(company,
    title) gives all three ONE document path — so past this point a job must be a
    single entry whatever the database decided.
    """
    from matcher import is_junk_description  # local import: avoids a cycle

    def rank(j: dict) -> tuple[int, int]:
        desc = j.get("description") or ""
        return (0 if is_junk_description(desc) else 1, len(desc))

    best: dict[tuple[str, str], dict] = {}
    for j in jobs:
        key = (j.get("company", ""), j.get("title", ""))
        cur = best.get(key)
        if cur is None or rank(j) > rank(cur):
            best[key] = j
    return list(best.values())


def is_unscoreable(job: dict) -> bool:
    """True when nothing was scraped that a score could be based on.

    A posting whose description is empty or is page machinery cannot be matched
    OR reviewed, because neither stage has requirements to compare against. Both
    stages then fabricate instead of abstaining, in opposite directions: the
    matcher scores an LLM read of the metadata-only pseudo-description (title
    alone drove context scores up to 0.92), while the reviewer invents 3-5
    plausible requirements from the job title, finds them all satisfied by a
    generic CV, and emits submission_score 100 / submission_ready true.

    Measured on 170 reviewed documents, junk-description jobs averaged review 70.5
    against 57.1 for real ones — the inflation is systematic, not incidental.
    Re-scoring them does not help: replacing the junk text with the pseudo-
    description moved 29 jobs down and 33 up for a mean change of -0.002, which is
    what swapping one baseless number for another looks like. So they are excluded
    until a re-scrape supplies a real description.
    """
    from matcher import is_junk_description  # local import: avoids a cycle

    # An API summary counts as no description. Adzuna's API caps description at 500
    # chars ending in "…" with no full-text field, and what it cuts is the tail —
    # the requirements list. Long enough to look present, too short to check.
    if job.get("description_truncated"):
        return True

    # Judged on `description` alone, even though both the matcher and the reviewer
    # fall back to `snippet`. A snippet is a search-results blurb — enough to place
    # a match score, nowhere near enough to state and check 5 requirements. Counting
    # it as evidence let "Frontend Developer Needed for Business Website" (0-char
    # description, 174-char snippet) reach review 91 off an invented rubric.
    desc = job.get("description") or ""
    return len(desc.strip()) < 100 or is_junk_description(desc)


def ranked_jobs(config: dict | None = None, jobs: list[dict] | None = None) -> list[dict]:
    """Filter-passed, scoreable jobs with a positive score, best first, deduped.

    Same ordering every stage sees, so "rank N" means the same job everywhere.
    """
    from filter import passes_filter  # local import: avoids a cycle at import time
    config = config if config is not None else load_config()
    if jobs is None:
        jobs = json.loads(ANALYZED.read_text(encoding="utf-8"))
    passed = [
        j for j in _dedupe(jobs)
        if j.get("match")
        and passes_filter(j, config)[0]
        and j.get("match", {}).get("composite_score", 0) > 0
        and not is_unscoreable(j)
    ]
    passed.sort(key=lambda j: j["match"]["composite_score"], reverse=True)
    return passed


def unscoreable_jobs(jobs: list[dict] | None = None) -> list[dict]:
    """Jobs held out of every stage by is_unscoreable — the re-scrape backlog.

    Exposed so exclusion stays visible: a posting dropped for a scraper failure is
    a lead lost to a bug, not a poor match, and without a way to list them they
    would sit invisible forever.
    """
    if jobs is None:
        jobs = json.loads(ANALYZED.read_text(encoding="utf-8"))
    return [j for j in _dedupe(jobs) if j.get("match") and is_unscoreable(j)]


def top_percent_count(pool_size: int, percent: float) -> int:
    """How many jobs the top `percent` of a `pool_size` pool covers (>=1)."""
    if pool_size <= 0:
        return 0
    return max(1, math.ceil(pool_size * percent / 100.0))


def stage_percent(config: dict, stage: str) -> float:
    key = _STAGE_KEYS.get(stage)
    if not key:
        raise ValueError(f"unknown stage {stage!r}; expected one of {list(_STAGE_KEYS)}")
    try:
        return float(config.get(key, _DEFAULT_PERCENT))
    except (TypeError, ValueError):
        return _DEFAULT_PERCENT


def select_top(
    stage: str,
    config: dict | None = None,
    jobs: list[dict] | None = None,
    percent: float | None = None,
) -> list[dict]:
    """The jobs a stage should act on: the top N% of the ranked pool, minus any
    below the quality floor. `percent` overrides the configured value (used by a
    CLI --limit-style override that is expressed as a percentage)."""
    config = config if config is not None else load_config()
    ranked = ranked_jobs(config, jobs)
    pct = percent if percent is not None else stage_percent(config, stage)
    k = top_percent_count(len(ranked), pct)
    top = ranked[:k]

    floor = config.get("match_score_threshold")
    if floor:
        try:
            floor = float(floor)
            top = [j for j in top if j["match"]["composite_score"] >= floor]
        except (TypeError, ValueError):
            pass
    return top
